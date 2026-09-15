# -*- coding: utf-8 -*-
"""輪番設定分頁與番組彈窗（離線 Qt，暫存資料庫）。"""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import main
from lib import ruleset
from lib.db_utils import opened
from lib.rota import MODE_BLANK, MODE_ROTATE
from tabs import tab_rules
from tabs.tab_rules import TabRules, _NAME_COL
from ui_utils import group_dialog
from ui_utils.group_dialog import GroupDialog

_app = QApplication.instance() or QApplication([])


class _TempDb(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        main.prepare_database(self.db)
        with opened(self.db) as conn:
            self.draft = ruleset.drafts(conn)[0]["version_id"]

    def tearDown(self):
        os.remove(self.db)

    def groups(self, version_id=None):
        with opened(self.db) as conn:
            return ruleset.group_rows(conn, version_id or self.draft)


class TestGroupDialog(_TempDb):
    def test_new_group_gets_default_name_and_focus(self):
        dlg = GroupDialog(self.db, self.draft)
        self.addCleanup(dlg.deleteLater)
        dlg.show(); _app.processEvents()
        self.assertEqual(dlg.w_name.text(), "番組1")
        self.assertIs(_app.focusWidget(), dlg.w_name)
        self.assertEqual(dlg.styleSheet(), "", "彈窗不得自帶 stylesheet（QSS-8）")

    def test_bad_range_shows_inline_error_without_popup(self):
        dlg = GroupDialog(self.db, self.draft)
        self.addCleanup(dlg.deleteLater)
        dlg.w_expr.setText("20-1")
        with mock.patch.object(group_dialog, "msgWarning") as warn:
            self.assertFalse(dlg._validateExpr())
            dlg._submit()
        warn.assert_not_called()
        self.assertIn("相反", dlg.lbl_expr.text())
        self.assertEqual(len(self.groups()), 6)

    def test_add_group_appends(self):
        dlg = GroupDialog(self.db, self.draft)
        self.addCleanup(dlg.deleteLater)
        dlg.w_expr.setText("40-45")
        dlg._submit()
        rows = self.groups()
        self.assertEqual(rows[-1]["name"], "番組1")
        self.assertEqual(rows[-1]["range_expr"], "40-45")

    def test_blank_mode_accepts_labels(self):
        dlg = GroupDialog(self.db, self.draft)
        self.addCleanup(dlg.deleteLater)
        dlg.w_mode.setCurrentIndex(2)
        self.assertEqual(dlg.mode(), MODE_BLANK)
        dlg.w_expr.setText("早,中,晚")
        dlg._submit()
        self.assertEqual(self.groups()[-1]["mode"], MODE_BLANK)

    def test_range_change_asks_before_clearing_rests(self):
        big = self.groups()[0]
        dlg = GroupDialog(self.db, self.draft, existing=big)
        self.addCleanup(dlg.deleteLater)
        dlg.w_expr.setText("1-22")
        with mock.patch.object(group_dialog, "confirmBox", return_value=False) as ask:
            dlg._submit()
        ask.assert_called_once()
        self.assertEqual(self.groups()[0]["range_expr"], "1-20", "取消時不得寫入")


class TestTabRules(_TempDb):
    def setUp(self):
        super().setUp()
        self.tab = TabRules(self.db)
        self.addCleanup(self.tab.deleteLater)

    def test_draft_selected_and_groups_listed(self):
        self.assertEqual(self.tab.currentVersion()["version_id"], self.draft)
        names = [self.tab.tbl_groups.item(r, _NAME_COL).text()
                 for r in range(self.tab.tbl_groups.rowCount())]
        self.assertEqual(names, [g["name"] for g in self.groups()])
        self.assertTrue(self.tab.btn_add_group.isEnabled())

    def test_slot_grid_shows_rest_and_click_toggles(self):
        self.tab.tbl_groups.selectRow(0)          # 大輪番，第 6 格是休
        self.assertIn("休", self.tab.tbl_slots.item(0, 5).text())
        self.tab._onSlotClicked(0, 5)
        self.assertNotIn("休", self.tab.tbl_slots.item(0, 5).text())

    def test_reorder_then_save(self):
        first, second = [g["name"] for g in self.groups()[:2]]
        self.tab._moveRow(0, 1)
        self.assertTrue(self.tab.btn_save.isEnabled())
        self.assertTrue(self.tab.saveSort())
        self.assertEqual([g["name"] for g in self.groups()[:2]], [second, first])

    def test_active_version_blocks_every_entry_point(self):
        """⚠️ 反灰擋不住雙擊、點格子、拖拉、序號格：每條路徑都要自己擋。"""
        with opened(self.db) as conn:
            ruleset.activate(conn, self.draft)
        self.tab.reload(self.draft)
        self.assertFalse(self.tab._editable())
        for btn in (self.tab.btn_add_group, self.tab.btn_edit_group, self.tab.btn_delete_group,
                    self.tab.btn_rename, self.tab.btn_delete_draft, self.tab.btn_activate):
            self.assertFalse(btn.isEnabled(), btn.text())
        self.assertTrue(self.tab.btn_copy.isEnabled())
        before = [dict(g) for g in self.groups()]
        self.tab.tbl_groups.selectRow(0)
        with mock.patch.object(tab_rules, "GroupDialog") as dlg:
            self.tab._onGroupCellDoubleClicked(0, _NAME_COL)
            self.tab._editGroup(0)
            self.tab._addGroup()
        dlg.assert_not_called()
        self.tab._moveRow(0, 1)
        self.tab._onSlotClicked(0, 5)
        self.tab.tbl_groups.item(0, tab_rules._SEQ_COL).setText("2")
        self.assertFalse(self.tab.saveSort())
        self.assertEqual([dict(g) for g in self.groups()], before)
        with opened(self.db) as conn:
            self.assertTrue(ruleset.slot_rows(conn, before[0]["group_id"])[5]["is_rest"])

    def test_activate_confirms_and_marks_latest(self):
        with mock.patch.object(tab_rules, "confirmBox", return_value=True) as ask:
            self.tab._activate()
        ask.assert_called_once()
        v = self.tab.currentVersion()
        self.assertEqual(v["status"], ruleset.ACTIVE)
        self.assertIn("★ 最新", self.tab.list_versions.currentItem().text())

    def test_activate_blocked_when_codes_overlap(self):
        with opened(self.db) as conn:
            ruleset.add_group(conn, self.draft, "撞號組", MODE_ROTATE, "18-25")   # 與大輪番 18-20 撞號
        with mock.patch.object(tab_rules, "msgWarning") as warn, \
             mock.patch.object(tab_rules, "confirmBox") as ask:
            self.tab._activate()
        warn.assert_called_once()
        ask.assert_not_called()
        with opened(self.db) as conn:
            self.assertEqual(ruleset.drafts(conn)[0]["version_id"], self.draft)

    def test_copy_active_to_new_draft(self):
        with opened(self.db) as conn:
            ruleset.activate(conn, self.draft)
        self.tab.reload(self.draft)
        with mock.patch.object(tab_rules.QInputDialog, "getText", return_value=("方案二", True)):
            self.tab._copyDraft()
        v = self.tab.currentVersion()
        self.assertEqual((v["status"], v["draft_name"]), (ruleset.DRAFT, "方案二"))
        self.assertTrue(self.tab._editable())


if __name__ == "__main__":
    unittest.main()
