# -*- coding: utf-8 -*-
"""錯誤訊息轉換與記錄（ui_utils.friendlyErrorMessage／reportError）。

⚠️ 舊寫法以「訊息裡有沒有中文」判斷該不該原樣顯示，會把 SQLite 英文原文
直接丟給承辦人（2026-09-16 檢視發現）。
"""
import logging
import os
import sqlite3
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import ui_utils
from lib.plan import PlanError
from lib.rota import GroupError, RangeError
from lib.template import TemplateError

_app = QApplication.instance() or QApplication([])


class TestFriendlyErrorMessage(unittest.TestCase):
    def test_project_errors_are_shown_as_is(self):
        for exc in (TemplateError("已經有叫「大輪番」的群組"),
                    PlanError("2026 年 10 月已經有月表了"),
                    RangeError("「20-1」的起迄相反了"),
                    GroupError("代碼「18」同時出現在兩個群組")):
            with self.subTest(exc=exc):
                self.assertEqual(ui_utils.friendlyErrorMessage(exc), str(exc))

    def test_other_errors_never_leak_the_raw_text(self):
        msg = ui_utils.friendlyErrorMessage(TypeError("unsupported operand type(s)"))
        self.assertNotIn("unsupported", msg)
        self.assertIn("error.log", msg)


class TestReportError(unittest.TestCase):
    def test_writes_log_and_shows_friendly_text(self):
        exc = sqlite3.DatabaseError("no such table: Foo")
        with mock.patch.object(ui_utils.ui_common, "msgWarning") as warn, \
             mock.patch.object(logging, "error") as log:
            ui_utils.reportError("儲存失敗", exc)
        log.assert_called_once()
        self.assertIn("no such table", "".join(str(a) for a in log.call_args.args))
        title, shown = warn.call_args.args[0], warn.call_args.args[1]
        self.assertEqual(title, "儲存失敗")
        self.assertNotIn("no such table", shown)


if __name__ == "__main__":
    unittest.main()
