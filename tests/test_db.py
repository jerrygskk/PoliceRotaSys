"""資料庫結構與種子資料的測試。⚠️ 姓名一律虛構。

⚠️ 這一版**沒有任何 trigger**：規則版本鎖死那一整套已經拿掉。歷史正確性
改由月表自己的 snapshot 保證（見 tests/test_plan.py 的 TestSnapshotIsDetached），
模板與月表都可以隨時改、隨時刪。
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from lib import db_schema, db_seed, db_utils, template


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

    def template_id(self):
        return self.conn.execute(
            "SELECT template_id FROM Rota_Template"
        ).fetchone()[0]

    def insert_plan(self, year=2026, month=10, origin="自訂起始"):
        return self.conn.execute(
            "INSERT INTO Month_Plan(year, month, origin, created_at, snapshot) "
            "VALUES (?, ?, ?, 'x', '{}')", (year, month, origin)
        ).lastrowid


class TestSchema(_DbTestCase):
    def test_all_tables_exist(self):
        names = {
            r[0] for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue({
            "App_Settings", "Member", "Rota_Template",
            "T_Group", "T_Slot", "Month_Plan",
        }.issubset(names))

    def test_no_triggers_are_left(self):
        """⚠️ 鎖死規則版本的 trigger 全部拿掉了，別再長回來。"""
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
        self.assertEqual(rows, [])

    def test_create_all_is_idempotent(self):
        db_schema.create_all(self.conn)
        db_schema.create_all(self.conn)

    def test_foreign_keys_are_enabled(self):
        self.assertEqual(
            self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1
        )

    def test_month_is_range_checked(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_plan(month=13)

    def test_one_plan_per_month(self):
        self.insert_plan()
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_plan()

    def test_a_month_can_be_edited_and_deleted(self):
        """⚠️ 承辦人排下個月本來就會邊排邊調——資料庫不擋修改也不擋刪除。"""
        plan_id = self.insert_plan()
        self.conn.execute(
            "UPDATE Month_Plan SET snapshot = ? WHERE plan_id = ?",
            (json.dumps({"groups": []}), plan_id),
        )
        self.conn.execute("DELETE FROM Month_Plan WHERE plan_id = ?", (plan_id,))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM Month_Plan").fetchone()[0], 0
        )

    def test_a_used_template_can_be_edited_and_deleted(self):
        self.seed()
        self.insert_plan()
        tid = self.template_id()
        gid = template.group_rows(self.conn, tid)[0]["group_id"]
        template.toggle_rest(self.conn, gid, 1)
        template.delete_template(self.conn, tid)
        self.assertEqual(template.list_templates(self.conn), [])


class TestSeed(_DbTestCase):
    def test_seed_has_female_officers_marked(self):
        """假資料要有女警，一開起來才看得到「紅字＝女警」。"""
        self.assertTrue(db_seed.SEED_FEMALE)
        self.assertTrue(set(db_seed.SEED_FEMALE) <= set(db_seed.SEED_MEMBERS))
        self.seed()
        marked = {r[0] for r in self.conn.execute("SELECT name FROM Member WHERE female = 1")}
        self.assertEqual(marked, set(db_seed.SEED_FEMALE))

    def test_seed_creates_members_and_one_template(self):
        self.seed()
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM Member").fetchone()[0],
            len(db_seed.SEED_MEMBERS),
        )
        self.assertEqual(len(template.list_templates(self.conn)), 1)

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
            "SELECT name, mode, range_expr FROM T_Group ORDER BY sort_order"
        ).fetchall()
        self.assertEqual(
            [tuple(r) for r in rows],
            [("大輪番", "rotate", "1-20"),
             ("固定番", "fixed", "21-28"),
             ("同仁專案臨檢", "blank", "同仁專案臨檢"),
             ("劃假", "blank", "早,中,晚"),
             ("幹部", "fixed", "A-F"),
             ("快打勤務", "blank", "快打勤務")],
        )

    def test_seed_rest_positions_match_the_paper_form(self):
        self.seed()
        rests = [
            r[0] for r in self.conn.execute(
                "SELECT seq FROM T_Slot WHERE is_rest = 1 ORDER BY seq"
            )
        ]
        self.assertEqual(rests, [6, 7, 13, 14, 19, 20])

    def test_template_has_exactly_enough_people_for_the_default_rules(self):
        """⚠️ 模板若配不滿自己的預設規則，第一次開起來就會產出有空欄的月表，
        承辦人會以為程式壞了。改 SEED_GROUPS 時要回頭核對這個數字。"""
        total = sum(
            db_seed._slot_count(mode, expr)
            for _, mode, expr, _, _, _, _ in db_seed.SEED_GROUPS
            if mode != "blank"          # 空白欄不配人
        )
        self.assertEqual(len(db_seed.SEED_MEMBERS), total)

    def test_template_has_no_duplicate_names(self):
        self.assertEqual(
            len(db_seed.SEED_MEMBERS), len(set(db_seed.SEED_MEMBERS))
        )

    def test_the_shift_note_is_stored_with_the_template(self):
        """⚠️ 註記提到番號，換單位就不一樣，所以存在模板裡、隨月表拷進快照。"""
        self.seed()
        note = self.conn.execute(
            "SELECT note FROM T_Group WHERE name = '劃假'"
        ).fetchone()[0]
        self.assertIn("早班", note)
        # ⚠️ 註記一律純文字，不得再出現「顏色|」前綴（維護者裁示 2026-09-16）
        self.assertNotIn("|", note)

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


class TestOldDatabaseIsUpgraded(unittest.TestCase):
    """⚠️ 現場已在用的資料庫缺後來加的欄位，開庫時要補，不然整個程式開不起來。"""

    def test_missing_group_columns_are_added(self):
        with tempfile.TemporaryDirectory(prefix="rota-old-") as folder:
            path = str(Path(folder) / "old.db")
            conn = db_utils.connect(path)
            db_schema.create_all(conn)
            db_seed.seed_all(conn)
            # 模擬舊版：拿掉兩個後加的欄位
            conn.execute("ALTER TABLE T_Group DROP COLUMN code_position")
            conn.execute("ALTER TABLE T_Group DROP COLUMN reverse_order")
            conn.commit()
            db_schema.create_all(conn)
            rows = conn.execute(
                "SELECT name, mode, code_position, reverse_order FROM T_Group"
            ).fetchall()
            conn.close()
        self.assertTrue(rows)
        for name, mode, position, reverse in rows:
            self.assertEqual(reverse, 0)
            expected = "above" if (mode, name) == ("fixed", "幹部") else "below"
            self.assertEqual(position, expected, name)
