"""資料庫結構、trigger 與種子資料的測試。⚠️ 姓名一律虛構。

最要緊的是 TestImmutabilityTriggers：規則版本的「不可修改」是靠 trigger
而不是程式自律，所以必須直接下 SQL 去撞它，確認資料庫層真的擋得住。
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from lib import db_schema, db_seed, db_utils, ruleset


class _DbTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="rota-db-")
        self.path = str(Path(self._temp.name) / "test.db")
        self.conn = db_utils.connect(self.path)
        db_schema.create_all(self.conn)

    def tearDown(self):
        self.conn.close()
        self._temp.cleanup()

    def seed(self):
        db_seed.seed_all(self.conn)

    def draft_id(self):
        return self.conn.execute(
            "SELECT version_id FROM Ruleset_Version WHERE status = '草稿'"
        ).fetchone()[0]


class TestSchema(_DbTestCase):
    def test_all_tables_exist(self):
        names = {
            r[0] for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue({
            "App_Settings", "Member", "Ruleset", "Ruleset_Version",
            "RV_Group", "RV_Slot", "Month_Plan", "Month_Seed",
        }.issubset(names))

    def test_create_all_is_idempotent(self):
        db_schema.create_all(self.conn)
        db_schema.create_all(self.conn)

    def test_foreign_keys_are_enabled(self):
        self.assertEqual(
            self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1
        )

    def test_month_is_range_checked(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO Month_Plan(year, month, ruleset_version_id, "
                "origin, created_at) VALUES (2026, 13, 1, 'chain', 'x')"
            )

    def test_one_plan_per_month(self):
        self.seed()
        vid = self.draft_id()
        self.conn.execute(
            "INSERT INTO Month_Plan(year, month, ruleset_version_id, origin, "
            "created_at) VALUES (2026, 10, ?, 'reset', 'x')", (vid,)
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO Month_Plan(year, month, ruleset_version_id, origin,"
                " created_at) VALUES (2026, 10, ?, 'reset', 'x')", (vid,)
            )


class TestImmutabilityTriggers(_DbTestCase):
    """⚠️ 直接下 SQL 撞 trigger——這些保證不能只靠程式自律。"""

    def setUp(self):
        super().setUp()
        self.seed()
        self.version_id = self.draft_id()
        self.group_id = self.conn.execute(
            "SELECT group_id FROM RV_Group WHERE version_id = ? LIMIT 1",
            (self.version_id,),
        ).fetchone()[0]

    def test_draft_can_be_edited(self):
        self.conn.execute(
            "UPDATE RV_Group SET name = '改過的名字' WHERE group_id = ?",
            (self.group_id,),
        )
        self.conn.execute(
            "UPDATE RV_Slot SET is_rest = 1 WHERE group_id = ? AND seq = 1",
            (self.group_id,),
        )

    def test_activated_group_cannot_be_updated(self):
        ruleset.activate(self.conn, self.version_id)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "不可修改"):
            self.conn.execute(
                "UPDATE RV_Group SET name = 'x' WHERE group_id = ?",
                (self.group_id,),
            )

    def test_activated_slot_cannot_be_updated(self):
        ruleset.activate(self.conn, self.version_id)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "不可修改"):
            self.conn.execute(
                "UPDATE RV_Slot SET is_rest = 1 WHERE group_id = ? AND seq = 1",
                (self.group_id,),
            )

    def test_activated_slot_cannot_be_deleted(self):
        ruleset.activate(self.conn, self.version_id)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "不可修改"):
            self.conn.execute(
                "DELETE FROM RV_Slot WHERE group_id = ?", (self.group_id,)
            )

    def test_activated_version_cannot_be_deleted(self):
        ruleset.activate(self.conn, self.version_id)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "不可刪除"):
            self.conn.execute(
                "DELETE FROM Ruleset_Version WHERE version_id = ?",
                (self.version_id,),
            )

    def test_activated_version_cannot_be_turned_back_into_a_draft(self):
        """⚠️ 不擋這條的話，改一個欄位就能把鎖解開，其他 trigger 全白做。"""
        ruleset.activate(self.conn, self.version_id)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "不可改回草稿"):
            self.conn.execute(
                "UPDATE Ruleset_Version SET status = '草稿' WHERE version_id = ?",
                (self.version_id,),
            )

    def test_activated_version_number_cannot_be_changed(self):
        ruleset.activate(self.conn, self.version_id)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "不可修改"):
            self.conn.execute(
                "UPDATE Ruleset_Version SET version_no = 99 WHERE version_id = ?",
                (self.version_id,),
            )

    def test_fourth_draft_is_rejected(self):
        rs_id = self.conn.execute("SELECT ruleset_id FROM Ruleset").fetchone()[0]
        ruleset.create_draft(self.conn, rs_id, "第二份")
        ruleset.create_draft(self.conn, rs_id, "第三份")
        with self.assertRaises((sqlite3.IntegrityError, ruleset.RulesetError)):
            ruleset.create_draft(self.conn, rs_id, "第四份")

    def test_month_plan_cannot_be_updated(self):
        self.conn.execute(
            "INSERT INTO Month_Plan(year, month, ruleset_version_id, origin, "
            "created_at) VALUES (2026, 10, ?, 'reset', 'x')", (self.version_id,)
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "刪除後重新產生"):
            self.conn.execute("UPDATE Month_Plan SET origin = 'chain'")


class TestMonthSeedConstraints(_DbTestCase):
    def setUp(self):
        super().setUp()
        self.seed()
        vid = self.draft_id()
        self.groups = [
            r[0] for r in self.conn.execute(
                "SELECT group_id FROM RV_Group WHERE version_id = ? "
                "ORDER BY sort_order", (vid,)
            )
        ]
        cur = self.conn.execute(
            "INSERT INTO Month_Plan(year, month, ruleset_version_id, origin, "
            "created_at) VALUES (2026, 10, ?, 'reset', 'x')", (vid,)
        )
        self.plan_id = cur.lastrowid

    def _seed_row(self, group_idx, member_id, slot_seq, row_no=1):
        self.conn.execute(
            "INSERT INTO Month_Seed(plan_id, rv_group_id, member_id, row_no, "
            "slot_seq) VALUES (?, ?, ?, ?, ?)",
            (self.plan_id, self.groups[group_idx], member_id, row_no, slot_seq),
        )

    def test_a_member_cannot_be_in_two_groups(self):
        """DEVELOPER §9：同一人同時在兩個番組，不允許。"""
        self._seed_row(0, 1, 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self._seed_row(1, 1, 1)

    def test_a_slot_cannot_be_taken_twice(self):
        self._seed_row(0, 1, 5)
        with self.assertRaises(sqlite3.IntegrityError):
            self._seed_row(0, 2, 5, row_no=2)

    def test_deleting_a_plan_cascades_to_its_seeds(self):
        self._seed_row(0, 1, 1)
        self.conn.execute("DELETE FROM Month_Plan WHERE plan_id = ?", (self.plan_id,))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM Month_Seed").fetchone()[0], 0
        )


class TestSeed(_DbTestCase):
    def test_seed_creates_members_and_a_draft(self):
        self.seed()
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM Member").fetchone()[0],
            len(db_seed.SEED_MEMBERS),
        )
        version = self.conn.execute("SELECT * FROM Ruleset_Version").fetchone()
        self.assertEqual(version["status"], "草稿")
        self.assertIsNone(version["version_no"])

    def test_seed_is_a_draft_not_an_active_version(self):
        """給啟用版等於逼承辦人第一件事就是複製為草稿（DEVELOPER §6）。"""
        self.seed()
        self.assertIsNone(ruleset.latest_active(self.conn))

    def test_seed_is_idempotent(self):
        self.seed()
        self.seed()
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM Member").fetchone()[0],
            len(db_seed.SEED_MEMBERS),
        )

    def test_seed_groups_match_the_paper_form(self):
        self.seed()
        rows = self.conn.execute(
            "SELECT name, mode, range_expr FROM RV_Group ORDER BY sort_order"
        ).fetchall()
        self.assertEqual(
            [tuple(r) for r in rows],
            [("大輪番", "rotate", "1-20"),
             ("固定番", "fixed", "21-28"),
             ("同仁專案臨檢／請假", "blank", "早,中,晚"),
             ("幹部", "fixed", "A-F"),
             ("快打勤務", "blank", "快打勤務")],
        )

    def test_seed_rest_positions_match_the_paper_form(self):
        self.seed()
        rests = [
            r[0] for r in self.conn.execute(
                "SELECT seq FROM RV_Slot WHERE is_rest = 1 ORDER BY seq"
            )
        ]
        self.assertEqual(rests, [6, 7, 13, 14, 19, 20])

    def test_template_has_exactly_enough_people_for_the_default_rules(self):
        """⚠️ 模板若配不滿自己的預設規則，第一次開起來就會產出有空欄的月表，
        承辦人會以為程式壞了。改 SEED_GROUPS 時要回頭核對這個數字。"""
        total = sum(
            db_seed._slot_count(mode, expr)
            for _, mode, expr, _, _ in db_seed.SEED_GROUPS
            if mode != "blank"          # 空白欄不配人
        )
        self.assertEqual(len(db_seed.SEED_MEMBERS), total)

    def test_template_has_no_duplicate_names(self):
        self.assertEqual(
            len(db_seed.SEED_MEMBERS), len(set(db_seed.SEED_MEMBERS))
        )

    def test_default_unit_name_is_a_placeholder(self):
        """⚠️ public repo：種子不得含真實單位名。"""
        self.seed()
        name = db_utils.get_setting(self.conn, db_utils.KEY_UNIT_NAME)
        self.assertIn("○", name)


class TestSettings(_DbTestCase):
    def test_round_trip(self):
        db_utils.set_setting(self.conn, "unit_name", "甲所")
        self.assertEqual(db_utils.get_setting(self.conn, "unit_name"), "甲所")

    def test_default_when_missing(self):
        self.assertEqual(db_utils.get_setting(self.conn, "nope", "x"), "x")

    def test_overwrite(self):
        db_utils.set_setting(self.conn, "k", "a")
        db_utils.set_setting(self.conn, "k", "b")
        self.assertEqual(db_utils.get_setting(self.conn, "k"), "b")


if __name__ == "__main__":
    unittest.main()
