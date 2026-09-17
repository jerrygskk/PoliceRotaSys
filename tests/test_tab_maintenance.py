# -*- coding: utf-8 -*-
"""維護分頁：月表標題、資料庫備份、壓縮（離線 Qt，暫存資料夾）。⚠️ 單位名稱一律虛構。"""
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import main
from lib import db_backup
from lib.db_utils import KEY_BACKUP_SECOND_DIR, KEY_UNIT_NAME, get_setting, opened
from tabs.tab_maintenance import TabMaintenance
from tabs import tab_maintenance
from tabs.tab_maintenance import UNIT_MAX, TitleCard, normPath

_app = QApplication.instance() or QApplication([])


class _TempDb(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="rota-maint-")
        self.dir = Path(self._temp.name)
        self.db = str(self.dir / "dbfile.db")
        main.prepare_database(self.db)
        self.tab = TabMaintenance(self.db)

    def tearDown(self):
        self.tab.deleteLater()
        self._temp.cleanup()

    def setting(self, key):
        with opened(self.db) as conn:
            return get_setting(conn, key)


class TestTitlePanel(_TempDb):
    def test_save_changes_the_sheet_title(self):
        panel = self.tab.card_title
        panel.w_unit.setText("甲分局乙派出所")
        self.assertTrue(panel.btn_save.isEnabled())
        self.assertTrue(panel.save())
        self.assertFalse(panel.btn_save.isEnabled())
        # 產生月表／匯出都從這個設定讀單位名稱（tab_generate.refresh、_export）
        self.assertEqual(self.setting(KEY_UNIT_NAME), "甲分局乙派出所")

    def test_blank_name_is_not_saved(self):
        panel = self.tab.card_title
        before = self.setting(KEY_UNIT_NAME)
        panel.w_unit.setText("   ")
        with mock.patch.object(tab_maintenance, "msgWarning") as warn:
            self.assertFalse(panel.save())
        warn.assert_called_once()
        self.assertEqual(self.setting(KEY_UNIT_NAME), before)

    def test_restore_default_waits_for_save(self):
        panel = self.tab.card_title
        panel.w_unit.setText("甲分局乙派出所")
        panel.save()
        panel.restoreDefault()
        self.assertEqual(panel.w_unit.text(), TitleCard.defaultUnit())
        self.assertEqual(self.setting(KEY_UNIT_NAME), "甲分局乙派出所")

    def test_name_cannot_exceed_the_limit(self):
        panel = self.tab.card_title
        panel.w_unit.setText("甲" * (UNIT_MAX + 5))
        self.assertEqual(len(panel.w_unit.text()), UNIT_MAX)


class TestBackupPanel(_TempDb):
    def test_offsite_path_is_saved_normalized(self):
        panel = self.tab.card_backup
        panel.w_path.setText(str(self.dir / "offsite") + "/")
        panel.save()
        self.assertEqual(self.setting(KEY_BACKUP_SECOND_DIR), normPath(str(self.dir / "offsite")))

    def test_empty_offsite_path_disables_it(self):
        panel = self.tab.card_backup
        panel.w_path.setText("")
        panel.save()
        self.assertEqual(self.setting(KEY_BACKUP_SECOND_DIR), "")
        self.assertEqual(panel.lbl_status.text(), "")

    def test_norm_path_keeps_drive_root(self):
        self.assertEqual(normPath("D:"), "D:" + os.sep)
        self.assertEqual(normPath("  "), "")

    def test_backup_now_writes_a_manual_copy(self):
        panel = self.tab.card_backup
        with mock.patch.object(tab_maintenance, "msgInfo") as done:
            panel.backupNow()
        done.assert_called_once()
        names = os.listdir(db_backup.backup_dir(self.db))
        self.assertTrue(any(n.startswith(db_backup.MANUAL_PREFIX) for n in names))

    def test_backup_now_asks_before_overwriting_the_same_minute(self):
        panel = self.tab.card_backup
        fixed = datetime(2026, 9, 17, 15, 30)
        dest = db_backup.manual_backup_path(self.db, fixed)
        os.makedirs(os.path.dirname(dest))
        Path(dest).write_bytes(b"")
        with mock.patch.object(db_backup, "manual_backup_path", return_value=dest), \
             mock.patch.object(tab_maintenance, "confirmBox", return_value=False) as ask:
            panel.backupNow()
        ask.assert_called_once()
        self.assertEqual(os.path.getsize(dest), 0)


class TestVacuumPanel(_TempDb):
    def test_vacuum_reports_sizes(self):
        with mock.patch.object(tab_maintenance.db_backup, "vacuum",
                               return_value=(4096000, 2048000)) as run, \
             mock.patch.object(tab_maintenance, "msgInfo") as done:
            self.tab.card_vacuum.vacuum()
        run.assert_called_once_with(self.db)
        message = done.call_args[0][1]
        self.assertIn("4,000", message)
        self.assertIn("2,000", message)


class TestSideNav(_TempDb):
    """左側選單切換子頁；有未存修改先問（取消留原頁、儲存、放棄修改）。"""

    def click(self, index):
        self.tab.nav.navButton(index).click()

    def test_clicking_the_menu_switches_page(self):
        self.click(1)
        self.assertEqual(self.tab.nav.currentIndex(), 1)
        self.assertTrue(self.tab.nav.navButton(1).isChecked())

    def test_unsaved_change_cancel_stays(self):
        self.tab.card_title.w_unit.setText("甲分局乙派出所")
        with mock.patch.object(tab_maintenance, "choiceBox", return_value=None) as ask:
            self.click(2)
        ask.assert_called_once()
        self.assertEqual(self.tab.nav.currentIndex(), 0)
        self.assertTrue(self.tab.nav.navButton(0).isChecked())
        self.assertFalse(self.tab.nav.navButton(2).isChecked())

    def test_unsaved_change_save_then_switch(self):
        self.tab.card_title.w_unit.setText("甲分局乙派出所")
        with mock.patch.object(tab_maintenance, "choiceBox", return_value=0):
            self.click(1)
        self.assertEqual(self.tab.nav.currentIndex(), 1)
        self.assertEqual(self.setting(KEY_UNIT_NAME), "甲分局乙派出所")

    def test_unsaved_change_discard_then_switch(self):
        before = self.setting(KEY_UNIT_NAME)
        self.tab.card_title.w_unit.setText("甲分局乙派出所")
        with mock.patch.object(tab_maintenance, "choiceBox", return_value=1):
            self.click(1)
        self.assertEqual(self.tab.nav.currentIndex(), 1)
        self.assertEqual(self.setting(KEY_UNIT_NAME), before)
        self.assertFalse(self.tab.card_title.isDirty())

    def test_failed_save_stays(self):
        self.tab.card_title.w_unit.setText("  ")
        with mock.patch.object(tab_maintenance, "choiceBox", return_value=0),              mock.patch.object(tab_maintenance, "msgWarning"):
            self.click(1)
        self.assertEqual(self.tab.nav.currentIndex(), 0)


if __name__ == "__main__":
    unittest.main()
