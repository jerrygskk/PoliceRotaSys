"""lib/template.py：模板的建立、複製、刪除與載入。⚠️ 姓名一律虛構。"""
import tempfile
import unittest
from pathlib import Path

from lib import db_schema, db_seed, db_utils, template
from lib.rota import slot_on_day


class _TemplateTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="rota-tpl-")
        self.conn = db_utils.connect(str(Path(self._temp.name) / "t.db"))
        db_schema.create_all(self.conn)
        db_seed.seed_all(self.conn)
        self.template_id = self.conn.execute(
            "SELECT template_id FROM Rota_Template"
        ).fetchone()[0]

    def tearDown(self):
        self.conn.close()
        self._temp.cleanup()


class TestTemplates(_TemplateTestCase):
    def test_seed_creates_one_template(self):
        self.assertEqual(len(template.list_templates(self.conn)), 1)

    def test_templates_have_no_count_limit(self):
        """⚠️ 模板就是設定，不是草稿——沒有 3 份上限。"""
        for i in range(5):
            template.create_template(self.conn, f"方案{i}")
        self.assertEqual(len(template.list_templates(self.conn)), 6)

    def test_duplicate_name_is_refused(self):
        name = template.get_template(self.conn, self.template_id)["name"]
        with self.assertRaisesRegex(template.TemplateError, "已經有叫"):
            template.create_template(self.conn, name)

    def test_blank_name_is_refused(self):
        with self.assertRaisesRegex(template.TemplateError, "不可空白"):
            template.create_template(self.conn, "   ")

    def test_rename(self):
        template.rename_template(self.conn, self.template_id, "龍興所")
        self.assertEqual(
            template.get_template(self.conn, self.template_id)["name"], "龍興所"
        )

    def test_default_name_skips_used_ones(self):
        template.create_template(self.conn, "模板1")
        self.assertEqual(template.default_template_name(self.conn), "模板2")

    def test_unknown_template_is_refused(self):
        with self.assertRaisesRegex(template.TemplateError, "找不到"):
            template.get_template(self.conn, 9999)


class TestUsedTemplateStaysEditable(_TemplateTestCase):
    """⚠️ 用過的模板照樣可以改、可以刪——月表有自己的快照，不受影響。"""

    def test_slots_can_be_edited_any_time(self):
        gid = template.group_rows(self.conn, self.template_id)[0]["group_id"]
        self.assertTrue(template.toggle_rest(self.conn, gid, 1))

    def test_delete_removes_groups_and_slots(self):
        template.delete_template(self.conn, self.template_id)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM T_Group").fetchone()[0], 0
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM T_Slot").fetchone()[0], 0
        )


class TestCopyTemplate(_TemplateTestCase):
    def test_copy_duplicates_groups_and_slots(self):
        copy = template.copy_template(self.conn, self.template_id, "改一下")
        self.assertEqual(
            len(template.load_groups(self.conn, copy)),
            len(template.load_groups(self.conn, self.template_id)),
        )

    def test_editing_the_copy_does_not_touch_the_original(self):
        before = template.load_groups(self.conn, self.template_id)[0]
        copy = template.copy_template(self.conn, self.template_id, "改一下")
        gid = template.group_rows(self.conn, copy)[0]["group_id"]
        template.toggle_rest(self.conn, gid, 1)
        self.assertEqual(
            template.load_groups(self.conn, self.template_id)[0], before
        )

    def test_copying_an_unknown_template_is_refused(self):
        with self.assertRaisesRegex(template.TemplateError, "找不到"):
            template.copy_template(self.conn, 9999, "x")


class TestLoadGroups(_TemplateTestCase):
    def test_groups_match_the_paper_form(self):
        groups = template.load_groups(self.conn, self.template_id)
        self.assertEqual(
            [g.name for g in groups],
            ["大輪番", "固定番", "同仁專案臨檢", "劃假", "幹部", "快打勤務"],
        )
        self.assertEqual(groups[0].cycle_len, 20)
        self.assertEqual(groups[4].slots[0].code, "A")

    def test_blank_group_columns_come_from_literal_labels(self):
        """⚠️ blank 模式的 range_expr 是字面欄標題，不是範圍式。"""
        groups = template.load_groups(self.conn, self.template_id)
        blank = next(g for g in groups if g.name == "劃假")
        self.assertEqual([s.code for s in blank.slots], ["早", "中", "晚"])
        self.assertTrue(all(not s.is_rest for s in blank.slots))

    def test_loaded_group_reproduces_the_paper_row(self):
        """從資料庫載入的規則，推出來的結果必須與紙本相同。"""
        group = template.load_groups(self.conn, self.template_id)[0]
        row = [
            "00" if slot_on_day(group, 12, day).is_rest
            else slot_on_day(group, 12, day).code
            for day in range(1, 11)
        ]
        self.assertEqual(
            row, ["12", "00", "00", "15", "16", "17", "18", "00", "00", "01"]
        )

    def test_code_override_beats_the_expanded_default(self):
        gid = template.group_rows(self.conn, self.template_id)[0]["group_id"]
        template.set_code_override(self.conn, gid, 1, "甲")
        self.assertEqual(
            template.load_groups(self.conn, self.template_id)[0].slots[0].code, "甲"
        )

    def test_slot_count_mismatch_is_reported(self):
        gid = template.group_rows(self.conn, self.template_id)[0]["group_id"]
        self.conn.execute(
            "DELETE FROM T_Slot WHERE group_id = ? AND seq = 20", (gid,)
        )
        self.conn.commit()
        with self.assertRaisesRegex(template.TemplateError, "應展開成"):
            template.load_groups(self.conn, self.template_id)


if __name__ == "__main__":
    unittest.main()
