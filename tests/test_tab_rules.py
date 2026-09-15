# -*- coding: utf-8 -*-
"""輪番設定分頁與群組彈窗（離線 Qt，暫存資料庫）。"""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
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
        self.assertEqual(dlg.w_name.text(), "群組1")
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
        self.assertEqual(rows[-1]["name"], "群組1")
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
        self.assertIn("休", self.tab.slotTiles[5].text())
        self.assertEqual(self.tab.slotTiles[5].property("state"), "rest")
        self.tab._onSlotClicked(5)
        self.tab._click_timer.stop()          # 單擊延後執行，測試裡直接催它
        self.tab._applyPendingSlotClick()
        self.assertNotIn("休", self.tab.slotTiles[5].text())
        self.assertEqual(self.tab.slotTiles[5].property("state"), "work")

    def test_double_click_does_not_toggle_rest(self):
        """⚠️ 雙擊會先送一次單擊：單擊要延後，雙擊時取消，不能靠事後切回來補償。"""
        self.tab.tbl_groups.selectRow(0)
        before = self.tab.slotTiles[0].text()
        self.tab._onSlotClicked(0)                     # 雙擊的第一下
        with mock.patch.object(tab_rules, "askText", return_value=("", False)):
            self.tab._onSlotDoubleClicked(0)
        self.assertIsNone(self.tab._pending_slot)
        self.assertFalse(self.tab._click_timer.isActive())
        self.tab._applyPendingSlotClick()              # 就算被叫到也不該改東西
        self.assertEqual(self.tab.slotTiles[0].text(), before)

    def test_single_click_toggles_after_the_delay(self):
        self.tab.tbl_groups.selectRow(0)
        self.tab._onSlotClicked(0)
        self.assertTrue(self.tab._click_timer.isActive())
        self.tab._click_timer.stop()
        self.tab._applyPendingSlotClick()
        self.assertIn("輪休", self.tab.slotTiles[0].text())

    def test_cancelling_the_code_dialog_changes_nothing(self):
        self.tab.tbl_groups.selectRow(0)
        before = self.tab.slotTiles[2].text()
        with mock.patch.object(tab_rules, "askText", return_value=("ZZ", False)):
            self.tab._onSlotDoubleClicked(2)
        self.assertEqual(self.tab.slotTiles[2].text(), before)

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
        self.tab._onSlotClicked(5)
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
        self.assertIn("★ 最新", self.tab.list_versions.currentItem().data(Qt.UserRole))

    def test_activate_blocked_when_codes_overlap(self):
        with opened(self.db) as conn:
            ruleset.add_group(conn, self.draft, "撞號組", MODE_ROTATE, "18-25")   # 與大輪番 18-20 撞號
        with mock.patch.object(tab_rules, "reportError") as warn, \
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
        with mock.patch.object(tab_rules, "askText", return_value=("方案二", True)):
            self.tab._copyDraft()
        v = self.tab.currentVersion()
        self.assertEqual((v["status"], v["draft_name"]), (ruleset.DRAFT, "方案二"))
        self.assertTrue(self.tab._editable())



class TestSlotNumbering(_TempDb):
    """方塊第二行「N番」：勾選從 1 起算，不勾照番號；選擇要記住。只影響畫面。"""

    def setUp(self):
        super().setUp()
        with opened(self.db) as conn:
            ruleset.add_group(conn, self.draft, "小輪番", MODE_ROTATE, "30-39")
        self.tab = TabRules(self.db)
        self.addCleanup(self.tab.deleteLater)
        self.tab.tbl_groups.selectRow(len(self.groups()) - 1)

    def test_default_counts_from_one(self):
        self.assertTrue(self.tab.chk_from_one.isChecked())
        self.assertEqual(self.tab.slotTiles[0].text(), "30\n1番")

    def test_unchecked_uses_code_and_is_remembered(self):
        self.tab.chk_from_one.setChecked(False)
        self.assertEqual(self.tab.slotTiles[0].text(), "30\n30番")
        again = TabRules(self.db)
        self.addCleanup(again.deleteLater)
        self.assertFalse(again.chk_from_one.isChecked())

    def test_blank_group_shows_label_only(self):
        """空白欄只顯示欄標題；固定番照番號（21 → 21番），兩者都不顯示由 1 起算的勾選框。"""
        names = [g["name"] for g in self.groups()]
        self.tab.tbl_groups.selectRow(names.index("班別"))
        self.assertEqual([t.text() for t in self.tab.slotTiles], ["早", "中", "晚"])
        self.assertTrue(self.tab.chk_from_one.isHidden())
        self.tab.tbl_groups.selectRow(names.index("固定番"))
        self.assertEqual(self.tab.slotTiles[0].text().splitlines(), ["21", "21番"])
        self.assertTrue(self.tab.chk_from_one.isHidden(), "由 1 起算只作用在輪番類型")

    def test_legend_lists_only_possible_states(self):
        names = [g["name"] for g in self.groups()]
        shown = lambda: {s for s, c in self.tab.legend_chips.items() if not c.isHidden()}
        self.tab.tbl_groups.selectRow(names.index("大輪番"))
        self.assertEqual(shown(), {"work", "rest", "override"})
        self.tab.tbl_groups.selectRow(names.index("固定番"))
        self.assertEqual(shown(), {"work", "override"})
        self.tab.tbl_groups.selectRow(names.index("班別"))
        self.assertEqual(shown(), set())


class TestTextInputDialog(unittest.TestCase):
    """公版輸入彈窗：中文按鈕、不自帶樣式、開啟時游標在輸入欄。"""

    def test_template_buttons_and_focus(self):
        from PySide6.QtWidgets import QPushButton
        from ui_utils.text_dialog import TextInputDialog
        dlg = TextInputDialog("自訂代碼", "第 4 格代碼：", "D")
        self.addCleanup(dlg.deleteLater)
        dlg.show(); _app.processEvents()
        self.assertEqual(sorted(b.text() for b in dlg.findChildren(QPushButton)), ["取消", "確定"])
        self.assertEqual(dlg.styleSheet(), "", "彈窗不得自帶 stylesheet（QSS-8）")
        self.assertIs(_app.focusWidget(), dlg.w_text)
        self.assertEqual(dlg.value(), "D")

if __name__ == "__main__":
    unittest.main()
