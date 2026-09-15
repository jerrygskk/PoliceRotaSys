"""lib/ruleset.py：草稿↔啟用狀態機。⚠️ 姓名一律虛構。"""
import tempfile
import unittest
from pathlib import Path

from lib import db_schema, db_seed, db_utils, ruleset
from lib.rota import slot_on_day


class _RulesetTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="rota-rs-")
        self.conn = db_utils.connect(str(Path(self._temp.name) / "t.db"))
        db_schema.create_all(self.conn)
        db_seed.seed_all(self.conn)
        self.ruleset_id = self.conn.execute(
            "SELECT ruleset_id FROM Ruleset"
        ).fetchone()[0]
        self.draft = self.conn.execute(
            "SELECT version_id FROM Ruleset_Version WHERE status = '草稿'"
        ).fetchone()[0]

    def tearDown(self):
        self.conn.close()
        self._temp.cleanup()


class TestActivate(_RulesetTestCase):
    def test_activation_assigns_version_one(self):
        self.assertEqual(ruleset.activate(self.conn, self.draft), 1)

    def test_version_numbers_increment(self):
        ruleset.activate(self.conn, self.draft)
        second = ruleset.copy_to_draft(self.conn, self.draft, "第二版")
        self.assertEqual(ruleset.activate(self.conn, second), 2)

    def test_draft_has_no_version_number_before_activation(self):
        """⚠️ 草稿先占號會造成跳號——所長只挑一個，其餘刪掉。"""
        row = self.conn.execute(
            "SELECT version_no FROM Ruleset_Version WHERE version_id = ?",
            (self.draft,),
        ).fetchone()
        self.assertIsNone(row["version_no"])

    def test_deleted_drafts_do_not_consume_version_numbers(self):
        throwaway = ruleset.create_draft(self.conn, self.ruleset_id, "丟掉的")
        ruleset.delete_draft(self.conn, throwaway)
        self.assertEqual(ruleset.activate(self.conn, self.draft), 1)

    def test_activating_twice_is_refused(self):
        ruleset.activate(self.conn, self.draft)
        with self.assertRaisesRegex(ruleset.RulesetError, "已經啟用"):
            ruleset.activate(self.conn, self.draft)

    def test_empty_draft_cannot_be_activated(self):
        empty = ruleset.create_draft(self.conn, self.ruleset_id, "空的")
        with self.assertRaisesRegex(ruleset.RulesetError, "沒有任何番組"):
            ruleset.activate(self.conn, empty)

    def test_unknown_version_is_refused(self):
        with self.assertRaisesRegex(ruleset.RulesetError, "找不到"):
            ruleset.activate(self.conn, 9999)


class TestDrafts(_RulesetTestCase):
    def test_three_drafts_are_allowed(self):
        ruleset.create_draft(self.conn, self.ruleset_id, "第二份")
        ruleset.create_draft(self.conn, self.ruleset_id, "第三份")
        self.assertEqual(len(ruleset.drafts(self.conn)), 3)

    def test_fourth_draft_is_refused(self):
        ruleset.create_draft(self.conn, self.ruleset_id, "第二份")
        ruleset.create_draft(self.conn, self.ruleset_id, "第三份")
        with self.assertRaisesRegex(ruleset.RulesetError, "最多 3 份"):
            ruleset.create_draft(self.conn, self.ruleset_id, "第四份")

    def test_activating_frees_a_draft_slot(self):
        ruleset.create_draft(self.conn, self.ruleset_id, "第二份")
        ruleset.create_draft(self.conn, self.ruleset_id, "第三份")
        ruleset.activate(self.conn, self.draft)
        ruleset.create_draft(self.conn, self.ruleset_id, "再一份")

    def test_deleting_a_draft_removes_its_groups_and_slots(self):
        ruleset.delete_draft(self.conn, self.draft)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM RV_Group").fetchone()[0], 0
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM RV_Slot").fetchone()[0], 0
        )


class TestCopyToDraft(_RulesetTestCase):
    def test_copy_duplicates_groups_and_slots(self):
        ruleset.activate(self.conn, self.draft)
        copy = ruleset.copy_to_draft(self.conn, self.draft, "改一下")
        self.assertEqual(
            len(ruleset.load_groups(self.conn, copy)),
            len(ruleset.load_groups(self.conn, self.draft)),
        )

    def test_the_copy_is_editable_while_the_source_is_locked(self):
        """改已啟用規則的唯一途徑就是複製為草稿。"""
        ruleset.activate(self.conn, self.draft)
        copy = ruleset.copy_to_draft(self.conn, self.draft, "改一下")
        group_id = self.conn.execute(
            "SELECT group_id FROM RV_Group WHERE version_id = ? LIMIT 1", (copy,)
        ).fetchone()[0]
        self.conn.execute(
            "UPDATE RV_Group SET range_expr = '1-22' WHERE group_id = ?",
            (group_id,),
        )

    def test_editing_the_copy_does_not_touch_the_original(self):
        ruleset.activate(self.conn, self.draft)
        before = ruleset.load_groups(self.conn, self.draft)[0]
        copy = ruleset.copy_to_draft(self.conn, self.draft, "改一下")
        gid = self.conn.execute(
            "SELECT group_id FROM RV_Group WHERE version_id = ? ORDER BY sort_order",
            (copy,),
        ).fetchone()[0]
        self.conn.execute(
            "UPDATE RV_Slot SET is_rest = 1 WHERE group_id = ? AND seq = 1", (gid,)
        )
        self.conn.commit()
        self.assertEqual(ruleset.load_groups(self.conn, self.draft)[0], before)

    def test_copying_an_unknown_version_is_refused(self):
        with self.assertRaisesRegex(ruleset.RulesetError, "找不到"):
            ruleset.copy_to_draft(self.conn, 9999, "x")


class TestLatestActive(_RulesetTestCase):
    def test_none_before_any_activation(self):
        self.assertIsNone(ruleset.latest_active(self.conn))

    def test_latest_is_the_highest_version_number(self):
        ruleset.activate(self.conn, self.draft)
        second = ruleset.copy_to_draft(self.conn, self.draft, "第二版")
        ruleset.activate(self.conn, second)
        self.assertEqual(ruleset.latest_active(self.conn)["version_no"], 2)

    def test_older_versions_stay_active(self):
        """⚠️ 沒有「停用」狀態——版本不會失效，只是舊，而且舊月份還指著它。"""
        ruleset.activate(self.conn, self.draft)
        second = ruleset.copy_to_draft(self.conn, self.draft, "第二版")
        ruleset.activate(self.conn, second)
        statuses = {
            r["status"] for r in self.conn.execute(
                "SELECT status FROM Ruleset_Version WHERE version_no IS NOT NULL"
            )
        }
        self.assertEqual(statuses, {"啟用"})

    def test_drafts_sort_before_active_versions(self):
        ruleset.activate(self.conn, self.draft)
        ruleset.create_draft(self.conn, self.ruleset_id, "編輯中")
        self.assertEqual(ruleset.list_versions(self.conn)[0]["status"], "草稿")


class TestLoadGroups(_RulesetTestCase):
    def test_groups_match_the_paper_form(self):
        groups = ruleset.load_groups(self.conn, self.draft)
        self.assertEqual(
            [g.name for g in groups],
            ["大輪番", "固定番", "同仁專案臨檢", "班別", "幹部", "快打勤務"],
        )
        self.assertEqual(groups[0].cycle_len, 20)
        self.assertEqual(groups[4].slots[0].code, "A")

    def test_blank_group_columns_come_from_literal_labels(self):
        """⚠️ blank 模式的 range_expr 是字面欄標題，不是範圍式。"""
        groups = ruleset.load_groups(self.conn, self.draft)
        blank = next(g for g in groups if g.name == "班別")
        self.assertEqual([s.code for s in blank.slots], ["早", "中", "晚"])
        self.assertTrue(all(not s.is_rest for s in blank.slots))

    def test_loaded_group_reproduces_the_paper_row(self):
        """從資料庫載入的規則，推出來的結果必須與紙本相同。"""
        group = ruleset.load_groups(self.conn, self.draft)[0]
        row = [
            "00" if slot_on_day(group, 12, day).is_rest
            else slot_on_day(group, 12, day).code
            for day in range(1, 11)
        ]
        self.assertEqual(
            row, ["12", "00", "00", "15", "16", "17", "18", "00", "00", "01"]
        )

    def test_code_override_beats_the_expanded_default(self):
        gid = self.conn.execute(
            "SELECT group_id FROM RV_Group WHERE version_id = ? ORDER BY sort_order",
            (self.draft,),
        ).fetchone()[0]
        self.conn.execute(
            "UPDATE RV_Slot SET code_override = '甲' WHERE group_id = ? AND seq = 1",
            (gid,),
        )
        self.conn.commit()
        self.assertEqual(
            ruleset.load_groups(self.conn, self.draft)[0].slots[0].code, "甲"
        )

    def test_slot_count_mismatch_is_reported(self):
        gid = self.conn.execute(
            "SELECT group_id FROM RV_Group WHERE version_id = ? ORDER BY sort_order",
            (self.draft,),
        ).fetchone()[0]
        self.conn.execute(
            "DELETE FROM RV_Slot WHERE group_id = ? AND seq = 20", (gid,)
        )
        self.conn.commit()
        with self.assertRaisesRegex(ruleset.RulesetError, "應展開成"):
            ruleset.load_groups(self.conn, self.draft)


if __name__ == "__main__":
    unittest.main()
