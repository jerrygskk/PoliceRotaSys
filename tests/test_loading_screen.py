# -*- coding: utf-8 -*-
"""啟動畫面（ui_utils/loading_screen.py）與資源路徑（lib/resource_path.py）。

⚠️ 本專案測試一律 unittest（`python -m unittest discover -s tests -t .`）；
pytest 式的裸函式與 fixture 不會被 unittest 收進去，等於沒跑。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from lib.resource_path import resource_path
from ui_utils.loading_screen import LoadingScreen

_app = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parent.parent


class TestLoadingScreen(unittest.TestCase):
    def test_renders_banner_at_fixed_size(self):
        loading = LoadingScreen()
        self.addCleanup(loading.close)
        actual = loading.banner_label.pixmap()
        self.assertEqual((loading.width(), loading.height()), (700, 319))
        self.assertEqual((loading.banner_label.width(), loading.banner_label.height()), (700, 279))
        self.assertIsNotNone(actual)
        self.assertFalse(actual.isNull())

    def test_missing_banner_shows_product_name(self):
        loading = LoadingScreen(banner_path="missing-banner.png", product_name="勤休預定表產生器")
        self.addCleanup(loading.close)
        self.assertEqual(loading.banner_label.text(), "勤休預定表產生器")
        self.assertTrue(loading.windowFlags() & Qt.FramelessWindowHint)
        self.assertFalse(loading.windowFlags() & Qt.WindowStaysOnTopHint)

    def test_updates_visible_progress_state(self):
        loading = LoadingScreen()
        self.addCleanup(loading.close)
        loading.setStep("建立主視窗...", 80)
        self.assertEqual(loading.status_label.text(), "建立主視窗...")
        self.assertEqual(loading.pct_label.text(), "80%")
        self.assertEqual(loading.progress_bar.value(), 80)


class TestResourcePath(unittest.TestCase):
    def test_uses_project_root_during_development(self):
        self.assertFalse(hasattr(sys, "_MEIPASS"))   # 跑原始碼時沒有打包暫存目錄
        actual = resource_path("res/buttons/banner.png")
        self.assertEqual(actual, os.path.join(str(ROOT), "res/buttons/banner.png"))

    def test_uses_pyinstaller_bundle_root(self):
        bundle = os.path.join("X:", "bundle")
        with mock.patch.object(sys, "_MEIPASS", bundle, create=True):
            actual = resource_path("res/buttons/banner.png")
        self.assertEqual(actual, os.path.join(bundle, "res/buttons/banner.png"))


if __name__ == "__main__":
    unittest.main()
