# -*- coding: utf-8 -*-
"""人員分頁與新增／修改彈窗（離線 Qt，暫存資料庫）。"""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import main
from lib import members
from lib.db_utils import opened
from tabs import tab_personnel
from tabs.tab_personnel import TabPersonnel, _NAME_COL, _FEMALE_COL, _STATUS_COL
from ui_utils.sort_table import COLOR_INACTIVE as _COLOR_INACTIVE
from ui_utils.member_dialog import MemberDialog

_app = QApplication.instance() or QApplication([])


class _TempDb(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        main.prepare_database(self.db)       # 與正式開機同一條路徑：結構＋種子

    def tearDown(self):
        os.remove(self.db)

    def names(self):
        with opened(self.db) as conn:
            return [r[1] for r in members.list_members(conn)]


class TestPrepareDatabase(_TempDb):
    def test_seed_once_only(self):
        n = len(self.names())
        main.prepare_database(self.db)
        self.assertEqual(len(self.names()), n)


class TestMemberDialog(_TempDb):
    def test_focus_on_name(self):
        dlg = MemberDialog(self.db)
        self.addCleanup(dlg.deleteLater)
        dlg.show(); _app.processEvents()
        self.assertIs(_app.focusWidget(), dlg.w_name)
        self.assertEqual(dlg.styleSheet(), "", "彈窗不得自帶 stylesheet（QSS-8）")

    def test_blank_name_rejected(self):
        dlg = MemberDialog(self.db)
        self.addCleanup(dlg.deleteLater)
        before = len(self.names())
        dlg._submit()
        self.assertIsNone(dlg.get_result())
        self.assertEqual(len(self.names()), before)

    def test_add_with_female_and_position(self):
        dlg = MemberDialog(self.db)
        self.addCleanup(dlg.deleteLater)
        dlg.w_name.setText("新人員")
        dlg.w_female.setChecked(True)
        dlg.w_seq.setText("3")
        dlg._submit()
        self.assertEqual(dlg.get_target_position(), 2)
        with opened(self.db) as conn:
            row = [r for r in members.list_members(conn) if r[1] == "新人員"][0]
        self.assertTrue(row[3])
        self.assertTrue(row[2])

    def test_bad_position_rejected(self):
        dlg = MemberDialog(self.db)
        self.addCleanup(dlg.deleteLater)
        dlg.w_name.setText("新人員")
        dlg.w_seq.setText("999")
        dlg._submit()
        self.assertIsNone(dlg.get_result())
        self.assertNotIn("新人員", self.names())

    def test_edit_retire(self):
        with opened(self.db) as conn:
            mid, name, active, female = members.list_members(conn)[0]
        dlg = MemberDialog(self.db, existing=(mid, 1, name, active, female))
        self.addCleanup(dlg.deleteLater)
        dlg.w_retired.setChecked(True)
        dlg._submit()
        with opened(self.db) as conn:
            self.assertFalse(members.list_members(conn)[0][2])


class TestTabPersonnel(_TempDb):
    def setUp(self):
        super().setUp()
        self.tab = TabPersonnel(self.db)
        self.addCleanup(self.tab.deleteLater)

    def test_lists_seed_with_female_mark(self):
        tbl = self.tab.tbl
        self.assertEqual(tbl.rowCount(), len(self.names()))
        with opened(self.db) as conn:
            rows = members.list_members(conn)
        for r, (_mid, name, _active, female) in enumerate(rows):
            self.assertEqual(tbl.item(r, _NAME_COL).text(), name)
            self.assertEqual(tbl.item(r, _FEMALE_COL).text(), "✓" if female else "")

    def test_move_then_save(self):
        first, second = self.names()[:2]
        self.tab._moveRow(0, 1)
        self.assertTrue(self.tab.btn_save.isEnabled())
        self.assertEqual(self.names()[:2], [first, second], "未按儲存前不得寫入")
        self.assertTrue(self.tab.saveSort())
        self.assertFalse(self.tab.btn_save.isEnabled())
        self.assertEqual(self.names()[:2], [second, first])

    def test_seq_cell_edit_moves_row(self):
        name0 = self.tab.tbl.item(0, _NAME_COL).text()
        self.tab.tbl.item(0, tab_personnel._SEQ_COL).setText("3")
        self.assertEqual(self.tab.tbl.item(2, _NAME_COL).text(), name0)
        self.assertTrue(self.tab.hasUnsavedSort())

    def test_bad_seq_cell_reverts(self):
        self.tab.tbl.item(0, tab_personnel._SEQ_COL).setText("999")
        self.assertEqual(self.tab.tbl.item(0, tab_personnel._SEQ_COL).text(), "1")
        self.assertFalse(self.tab.hasUnsavedSort())

    def test_retired_row_is_grey(self):
        with opened(self.db) as conn:
            mid, name, _a, female = members.list_members(conn)[0]
            members.update_member(conn, mid, name, female, active=False)
            conn.commit()
        self.tab.load()
        self.assertEqual(self.tab.tbl.item(0, _STATUS_COL).text(), "離職")
        for col in (tab_personnel._SEQ_COL, _NAME_COL, _STATUS_COL):   # 整列反灰
            self.assertEqual(self.tab.tbl.item(0, col).foreground().color(),
                             QColor(_COLOR_INACTIVE), col)

    def test_add_keeps_unsaved_order(self):
        first, second = self.names()[:2]
        self.tab._moveRow(0, 1)
        dlg = MemberDialog(self.db)
        self.addCleanup(dlg.deleteLater)
        dlg.w_name.setText("新人員")
        dlg._submit()
        self.tab._afterAdd(dlg)
        tbl = self.tab.tbl
        self.assertEqual([tbl.item(r, _NAME_COL).text() for r in range(3)],
                         ["新人員", second, first])
        self.assertTrue(self.tab.hasUnsavedSort())

    def test_leave_prompt_discard(self):
        self.tab._moveRow(0, 1)
        with mock.patch.object(tab_personnel, "confirmBox", return_value=False):
            self.assertTrue(self.tab.promptUnsaved("leave"))
        self.assertFalse(self.tab.hasUnsavedSort())

    def test_edit_without_selection_warns(self):
        with mock.patch.object(tab_personnel, "msgWarning") as warn:
            self.tab._editMember()
        warn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
