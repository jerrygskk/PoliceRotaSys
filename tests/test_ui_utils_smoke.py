# -*- coding: utf-8 -*-
"""ui_utils 公版元件的冒煙測試：自 PoliceDocSys 搬入後，確認建得起來、行為沒被裁壞。

搬遷時砍掉了公文專屬的部分（收件人輸入元件、錯誤轉譯、各設定面板），
這支釘住「剩下的公版仍可獨立使用、沒有殘留對公文模組的相依」。
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout

import ui_utils
from ui_utils.settings_panels import _SettingsPanel, _save_row

_app = QApplication.instance() or QApplication([])


class _DemoPanel(_SettingsPanel):
    """最小設定面板：一個文字欄＋儲存鈕，驗 isDirty 與儲存鈕亮灰。"""

    def _build(self):
        lay = QVBoxLayout(self)
        self.edit = QLineEdit()
        self.edit.textChanged.connect(self._updateSaveBtn)
        lay.addWidget(self.edit)
        self._btn_save = _save_row(lay)

    def _values(self):
        return (self.edit.text(),)

    def reload(self):
        self.edit.setText("預設")
        self._markLoaded()


class TestExports(unittest.TestCase):
    def test_all_names_resolve(self):
        for name in ui_utils.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(ui_utils, name), f"{name} 匯出了卻不存在")

    def test_no_document_specific_leftovers(self):
        for name in ("reportError", "RecipientCombo", "setupRecipientCombo"):
            self.assertFalse(hasattr(ui_utils, name), f"{name} 是公文專屬，不該留著")

    def test_fixed_col_widths_starts_empty(self):
        self.assertEqual(ui_utils.FIXED_COL_WIDTHS, {})


class TestSettingsPanel(unittest.TestCase):
    def setUp(self):
        self.panel = _DemoPanel("測試面板", db_path="")
        self.addCleanup(self.panel.deleteLater)

    def test_save_button_disabled_until_dirty(self):
        self.assertFalse(self.panel.isDirty())
        self.assertFalse(self.panel._btn_save.isEnabled())

    def test_edit_enables_save_and_revert_disables(self):
        self.panel.edit.setText("改過")
        self.assertTrue(self.panel.isDirty())
        self.assertTrue(self.panel._btn_save.isEnabled())
        self.panel.edit.setText("預設")
        self.assertFalse(self.panel._btn_save.isEnabled())

    def test_mark_loaded_resets_baseline(self):
        self.panel.edit.setText("改過")
        self.panel._markLoaded()
        self.assertFalse(self.panel.isDirty())


class TestNullableDateEdit(unittest.TestCase):
    def test_blank_and_valid_date(self):
        w = ui_utils.NullableDateEdit()
        self.addCleanup(w.deleteLater)
        self.assertTrue(w.isBlank())
        w.setText("2026-10-01")
        w.validateNow()
        self.assertFalse(w.hasError())
        self.assertEqual(w.getDate().toString("yyyy-MM-dd"), "2026-10-01")


if __name__ == "__main__":
    unittest.main()
