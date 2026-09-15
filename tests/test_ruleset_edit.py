"""lib/ruleset.py 的草稿編輯（輪番設定分頁用）。⚠️ 一律在暫存資料庫操作。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from lib import db_schema, db_seed, db_utils, ruleset
from lib.rota import MODE_BLANK, MODE_FIXED, MODE_ROTATE, RangeError


class _EditTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="rota-edit-")
        self.conn = db_utils.connect(str(Path(self._temp.name) / "t.db"))
        db_schema.create_all(self.conn)
        db_seed.seed_all(self.conn)
        self.ruleset_id = self.conn.execute("SELECT ruleset_id FROM Ruleset").fetchone()[0]
        self.draft = ruleset.drafts(self.conn)[0]["version_id"]
        self.empty = ruleset.create_draft(self.conn, self.ruleset_id, "空白草稿")

    def tearDown(self):
        self.conn.close()
        self._temp.cleanup()

    def group_id(self, version_id, name):
        return self.conn.execute(
            "SELECT group_id FROM RV_Group WHERE version_id = ? AND name = ?",
            (version_id, name),
        ).fetchone()[0]


class TestGroups(_EditTestCase):
    def test_default_names_count_up_and_fill_gaps(self):
        self.assertEqual(ruleset.default_group_name(self.conn, self.empty), "番組1")
        ruleset.add_group(self.conn, self.empty, "番組1", MODE_ROTATE, "1-5")
        ruleset.add_group(self.conn, self.empty, "番組3", MODE_ROTATE, "6-9")
        self.assertEqual(ruleset.default_group_name(self.conn, self.empty), "番組2")

    def test_add_expands_slots_and_goes_last(self):
        a = ruleset.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "1-5")
        b = ruleset.add_group(self.conn, self.empty, "乙組", MODE_BLANK, "早,中,晚")
        self.assertEqual([r["group_id"] for r in ruleset.group_rows(self.conn, self.empty)], [a, b])
        self.assertEqual(len(ruleset.slot_rows(self.conn, a)), 5)
        self.assertEqual(len(ruleset.slot_rows(self.conn, b)), 3)

    def test_weight_comes_from_mode_not_user(self):
        gid = ruleset.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "1-5")
        row = self.conn.execute("SELECT col_weight FROM RV_Group WHERE group_id = ?", (gid,)).fetchone()
        self.assertEqual(row[0], 1.1)
        ruleset.update_group(self.conn, gid, "甲組", MODE_FIXED, "1-5", True, "")
        row = self.conn.execute("SELECT col_weight FROM RV_Group WHERE group_id = ?", (gid,)).fetchone()
        self.assertEqual(row[0], 1.2)

    def test_bad_range_is_refused(self):
        with self.assertRaises(RangeError):
            ruleset.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "20-1")

    def test_duplicate_or_blank_name_is_refused(self):
        ruleset.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "1-5")
        with self.assertRaisesRegex(ruleset.RulesetError, "已經有"):
            ruleset.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "6-9")
        with self.assertRaisesRegex(ruleset.RulesetError, "空白"):
            ruleset.add_group(self.conn, self.empty, "  ", MODE_ROTATE, "6-9")

    def test_changing_range_clears_rests_and_overrides(self):
        """⚠️ 改了範圍，已設好的休一律清空（DEVELOPER §3）。"""
        gid = self.group_id(self.draft, "大輪番")
        ruleset.set_code_override(self.conn, gid, 1, "X1")
        self.assertTrue(ruleset.update_group(self.conn, gid, "大輪番", MODE_ROTATE, "1-22", True, ""))
        slots = ruleset.slot_rows(self.conn, gid)
        self.assertEqual(len(slots), 22)
        self.assertFalse(any(s["is_rest"] or s["code_override"] for s in slots))

    def test_renaming_only_keeps_rests(self):
        gid = self.group_id(self.draft, "大輪番")
        self.assertFalse(ruleset.update_group(self.conn, gid, "新名稱", MODE_ROTATE, "1-20", True, ""))
        self.assertTrue(any(s["is_rest"] for s in ruleset.slot_rows(self.conn, gid)))

    def test_delete_and_reorder(self):
        a = ruleset.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "1-5")
        b = ruleset.add_group(self.conn, self.empty, "乙組", MODE_ROTATE, "6-9")
        c = ruleset.add_group(self.conn, self.empty, "丙組", MODE_ROTATE, "10-12")
        ruleset.save_group_order(self.conn, [c, a, b])
        self.assertEqual([r["group_id"] for r in ruleset.group_rows(self.conn, self.empty)], [c, a, b])
        ruleset.delete_group(self.conn, a)
        self.assertEqual([r["group_id"] for r in ruleset.group_rows(self.conn, self.empty)], [c, b])
        self.assertEqual(ruleset.slot_rows(self.conn, a), [])


class TestSlots(_EditTestCase):
    def test_toggle_rest(self):
        gid = self.group_id(self.draft, "大輪番")
        self.assertFalse(ruleset.toggle_rest(self.conn, gid, 6))    # 種子第 6 格原本是休
        self.assertTrue(ruleset.toggle_rest(self.conn, gid, 6))

    def test_rest_only_on_rotate_groups(self):
        gid = self.group_id(self.draft, "固定番")
        with self.assertRaisesRegex(ruleset.RulesetError, "只有輪番組"):
            ruleset.toggle_rest(self.conn, gid, 1)

    def test_override_and_reset(self):
        gid = self.group_id(self.draft, "大輪番")
        ruleset.set_code_override(self.conn, gid, 2, "甲")
        self.assertEqual(ruleset.slot_rows(self.conn, gid)[1]["code_override"], "甲")
        ruleset.set_code_override(self.conn, gid, 2, "02")          # 與預設相同＝取消改寫
        self.assertIsNone(ruleset.slot_rows(self.conn, gid)[1]["code_override"])
        ruleset.set_code_override(self.conn, gid, 2, "甲")
        ruleset.set_code_override(self.conn, gid, 2, "")
        self.assertIsNone(ruleset.slot_rows(self.conn, gid)[1]["code_override"])


class TestCheckAndActivate(_EditTestCase):
    def test_seed_draft_passes(self):
        ruleset.check_version(self.conn, self.draft)

    def test_empty_version_fails_check(self):
        with self.assertRaisesRegex(ruleset.RulesetError, "沒有任何番組"):
            ruleset.check_version(self.conn, self.empty)

    def test_overlapping_codes_block_check_and_activation(self):
        ruleset.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "1-20")
        ruleset.add_group(self.conn, self.empty, "乙組", MODE_FIXED, "18-25")
        with self.assertRaisesRegex(ruleset.RulesetError, "同時出現"):
            ruleset.check_version(self.conn, self.empty)
        with self.assertRaisesRegex(ruleset.RulesetError, "不能啟用"):
            ruleset.activate(self.conn, self.empty)

    def test_all_rest_group_fails_check(self):
        gid = ruleset.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "1-2")
        ruleset.toggle_rest(self.conn, gid, 1)
        ruleset.toggle_rest(self.conn, gid, 2)
        with self.assertRaisesRegex(ruleset.RulesetError, "每一格都是休"):
            ruleset.check_version(self.conn, self.empty)


class TestActiveVersionIsLocked(_EditTestCase):
    def setUp(self):
        super().setUp()
        ruleset.activate(self.conn, self.draft)
        self.gid = self.group_id(self.draft, "大輪番")

    def test_every_edit_path_is_refused(self):
        calls = [
            lambda: ruleset.rename_draft(self.conn, self.draft, "改名"),
            lambda: ruleset.add_group(self.conn, self.draft, "新組", MODE_ROTATE, "30-35"),
            lambda: ruleset.update_group(self.conn, self.gid, "大輪番", MODE_ROTATE, "1-22", True, ""),
            lambda: ruleset.delete_group(self.conn, self.gid),
            lambda: ruleset.save_group_order(self.conn, [self.gid]),
            lambda: ruleset.toggle_rest(self.conn, self.gid, 1),
            lambda: ruleset.set_code_override(self.conn, self.gid, 1, "X"),
        ]
        for call in calls:
            with self.subTest(call=call):
                with self.assertRaisesRegex(ruleset.RulesetError, "不可修改"):
                    call()

    def test_database_refuses_inserting_into_active_version(self):
        """⚠️ 繞過程式直接下 SQL 也要被擋：新增番組與新增槽位。"""
        with self.assertRaisesRegex(sqlite3.DatabaseError, "不可修改"):
            self.conn.execute(
                "INSERT INTO RV_Group(version_id, name, mode, range_expr) "
                "VALUES (?, '偷塞', 'rotate', '40-41')", (self.draft,))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "不可修改"):
            self.conn.execute(
                "INSERT INTO RV_Slot(version_id, group_id, seq) VALUES (?, ?, 99)",
                (self.draft, self.gid))


if __name__ == "__main__":
    unittest.main()
