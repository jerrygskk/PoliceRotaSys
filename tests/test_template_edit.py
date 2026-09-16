"""lib/template.py 的群組與槽位編輯（輪番設定分頁用）。⚠️ 一律在暫存資料庫操作。"""
import tempfile
import unittest
from pathlib import Path

from lib import db_schema, db_seed, db_utils, template
from lib.rota import MODE_BLANK, MODE_FIXED, MODE_ROTATE, RangeError


class _EditTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="rota-edit-")
        self.conn = db_utils.connect(str(Path(self._temp.name) / "t.db"))
        db_schema.create_all(self.conn)
        db_seed.seed_all(self.conn)
        self.tpl = template.list_templates(self.conn)[0]["template_id"]
        self.empty = template.create_template(self.conn, "空白模板")

    def tearDown(self):
        self.conn.close()
        self._temp.cleanup()

    def group_id(self, template_id, name):
        return self.conn.execute(
            "SELECT group_id FROM T_Group WHERE template_id = ? AND name = ?",
            (template_id, name),
        ).fetchone()[0]


class TestGroups(_EditTestCase):
    def test_default_names_count_up_and_fill_gaps(self):
        self.assertEqual(template.default_group_name(self.conn, self.empty), "群組1")
        template.add_group(self.conn, self.empty, "群組1", MODE_ROTATE, "1-5")
        template.add_group(self.conn, self.empty, "群組3", MODE_ROTATE, "6-9")
        self.assertEqual(template.default_group_name(self.conn, self.empty), "群組2")

    def test_add_expands_slots_and_goes_last(self):
        a = template.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "1-5")
        b = template.add_group(self.conn, self.empty, "乙組", MODE_BLANK, "早,中,晚")
        self.assertEqual([r["group_id"] for r in template.group_rows(self.conn, self.empty)], [a, b])
        self.assertEqual(len(template.slot_rows(self.conn, a)), 5)
        self.assertEqual(len(template.slot_rows(self.conn, b)), 3)

    def test_weight_comes_from_mode_not_user(self):
        gid = template.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "1-5")
        row = self.conn.execute("SELECT col_weight FROM T_Group WHERE group_id = ?", (gid,)).fetchone()
        self.assertEqual(row[0], 1.1)
        template.update_group(self.conn, gid, "甲組", MODE_FIXED, "1-5", True, "")
        row = self.conn.execute("SELECT col_weight FROM T_Group WHERE group_id = ?", (gid,)).fetchone()
        self.assertEqual(row[0], 1.2)

    def test_lowercase_range_is_stored_uppercase(self):
        """⚠️ 使用者打 a-f，資料庫要存 A-F——否則群組表顯示小寫、月表印大寫。"""
        gid = template.add_group(self.conn, self.empty, "甲組", MODE_FIXED, " a-f ")
        row = self.conn.execute(
            "SELECT range_expr FROM T_Group WHERE group_id = ?", (gid,)).fetchone()
        self.assertEqual(row[0], "A-F")

    def test_changing_only_the_case_keeps_rests(self):
        """a-f 改成 A-F 不算改範圍，不得清掉已設的休。"""
        gid = template.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "A-F")
        template.toggle_rest(self.conn, gid, 2)
        self.assertFalse(
            template.update_group(self.conn, gid, "甲組", MODE_ROTATE, "a-f", True, ""))
        self.assertTrue(template.slot_rows(self.conn, gid)[1]["is_rest"])

    def test_blank_labels_keep_their_case(self):
        gid = template.add_group(self.conn, self.empty, "甲組", MODE_BLANK, "am,pm")
        row = self.conn.execute(
            "SELECT range_expr FROM T_Group WHERE group_id = ?", (gid,)).fetchone()
        self.assertEqual(row[0], "am,pm")

    def test_group_name_is_limited_to_seven_characters(self):
        template.add_group(self.conn, self.empty, "一二三四五六七", MODE_ROTATE, "1-5")
        with self.assertRaisesRegex(template.TemplateError, "最多 7 個字"):
            template.add_group(self.conn, self.empty, "一二三四五六七八", MODE_ROTATE, "6-9")

    def test_bad_range_is_refused(self):
        with self.assertRaises(RangeError):
            template.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "20-1")

    def test_duplicate_or_blank_name_is_refused(self):
        template.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "1-5")
        with self.assertRaisesRegex(template.TemplateError, "已經有"):
            template.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "6-9")
        with self.assertRaisesRegex(template.TemplateError, "空白"):
            template.add_group(self.conn, self.empty, "  ", MODE_ROTATE, "6-9")

    def test_changing_range_clears_rests_and_overrides(self):
        """⚠️ 改了範圍，已設好的休一律清空（DEVELOPER §3）。"""
        gid = self.group_id(self.tpl, "大輪番")
        template.set_code_override(self.conn, gid, 1, "X1")
        self.assertTrue(template.update_group(self.conn, gid, "大輪番", MODE_ROTATE, "1-22", True, ""))
        slots = template.slot_rows(self.conn, gid)
        self.assertEqual(len(slots), 22)
        self.assertFalse(any(s["is_rest"] or s["code_override"] for s in slots))

    def test_renaming_only_keeps_rests(self):
        gid = self.group_id(self.tpl, "大輪番")
        self.assertFalse(template.update_group(self.conn, gid, "新名稱", MODE_ROTATE, "1-20", True, ""))
        self.assertTrue(any(s["is_rest"] for s in template.slot_rows(self.conn, gid)))

    def test_delete_and_reorder(self):
        a = template.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "1-5")
        b = template.add_group(self.conn, self.empty, "乙組", MODE_ROTATE, "6-9")
        c = template.add_group(self.conn, self.empty, "丙組", MODE_ROTATE, "10-12")
        template.save_group_order(self.conn, [c, a, b])
        self.assertEqual([r["group_id"] for r in template.group_rows(self.conn, self.empty)], [c, a, b])
        template.delete_group(self.conn, a)
        self.assertEqual([r["group_id"] for r in template.group_rows(self.conn, self.empty)], [c, b])
        self.assertEqual(template.slot_rows(self.conn, a), [])


class TestSlots(_EditTestCase):
    def test_toggle_rest(self):
        gid = self.group_id(self.tpl, "大輪番")
        self.assertFalse(template.toggle_rest(self.conn, gid, 6))    # 種子第 6 格原本是休
        self.assertTrue(template.toggle_rest(self.conn, gid, 6))

    def test_rest_only_on_rotate_groups(self):
        gid = self.group_id(self.tpl, "固定番")
        with self.assertRaisesRegex(template.TemplateError, "只有輪番群組"):
            template.toggle_rest(self.conn, gid, 1)

    def test_override_and_reset(self):
        gid = self.group_id(self.tpl, "大輪番")
        template.set_code_override(self.conn, gid, 2, "甲")
        self.assertEqual(template.slot_rows(self.conn, gid)[1]["code_override"], "甲")
        template.set_code_override(self.conn, gid, 2, "02")          # 與預設相同＝取消自訂
        self.assertIsNone(template.slot_rows(self.conn, gid)[1]["code_override"])
        template.set_code_override(self.conn, gid, 2, "甲")
        template.set_code_override(self.conn, gid, 2, "")
        self.assertIsNone(template.slot_rows(self.conn, gid)[1]["code_override"])


class TestCheck(_EditTestCase):
    def test_seed_template_passes(self):
        template.check_template(self.conn, self.tpl)

    def test_empty_template_fails_check(self):
        with self.assertRaisesRegex(template.TemplateError, "沒有任何群組"):
            template.check_template(self.conn, self.empty)

    def test_overlapping_codes_block_check(self):
        template.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "1-20")
        template.add_group(self.conn, self.empty, "乙組", MODE_FIXED, "18-25")
        with self.assertRaisesRegex(template.TemplateError, "同時出現"):
            template.check_template(self.conn, self.empty)

    def test_all_rest_group_fails_check(self):
        gid = template.add_group(self.conn, self.empty, "甲組", MODE_ROTATE, "1-2")
        template.toggle_rest(self.conn, gid, 1)
        template.toggle_rest(self.conn, gid, 2)
        with self.assertRaisesRegex(template.TemplateError, "每一格都是休"):
            template.check_template(self.conn, self.empty)


if __name__ == "__main__":
    unittest.main()
