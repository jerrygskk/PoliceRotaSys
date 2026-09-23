"""Qt 繁中翻譯載入：找檔順序、缺檔與載入失敗的退路。"""
import os
import tempfile
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

from ui_utils import widgets as qt

_app = QApplication.instance() or QApplication([])


class _FakeApp:
    def __init__(self, ok=True):
        self.ok = ok
        self.installed = []

    def installTranslator(self, t):
        self.installed.append(t)
        return self.ok


class _FakeTranslator:
    loaded = []
    fail_paths = set()

    def __init__(self, parent=None):
        pass

    def load(self, path):
        _FakeTranslator.loaded.append(path)
        return path not in _FakeTranslator.fail_paths


class InstallTranslatorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.official = os.path.join(self.tmp.name, "official")
        self.bundle = os.path.join(self.tmp.name, "bundle")
        os.makedirs(self.official)
        os.makedirs(self.bundle)
        _FakeTranslator.loaded = []
        _FakeTranslator.fail_paths = set()
        self.patches = [
            mock.patch.object(qt, "QTranslator", _FakeTranslator),
            mock.patch.object(qt, "_qtTranslationDirs",
                              lambda: [self.official, self.bundle]),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def _touch(self, directory):
        path = os.path.join(directory, qt.QT_ZH_TW_QM)
        open(path, "wb").close()
        return path

    def test_official_dir_used_and_reference_kept(self):
        self._touch(self.official)
        self._touch(self.bundle)
        app = _FakeApp()
        self.assertTrue(qt.installChineseTranslator(app))
        self.assertEqual(_FakeTranslator.loaded, [os.path.join(self.official, qt.QT_ZH_TW_QM)])
        self.assertIs(app._qtbase_zh_tw_translator, app.installed[0])

    def test_falls_back_to_bundle_dir(self):
        bundled = self._touch(self.bundle)
        app = _FakeApp()
        self.assertTrue(qt.installChineseTranslator(app))
        self.assertEqual(_FakeTranslator.loaded, [bundled])

    def test_no_file_returns_false(self):
        app = _FakeApp()
        self.assertFalse(qt.installChineseTranslator(app))
        self.assertFalse(hasattr(app, "_qtbase_zh_tw_translator"))

    def test_load_failure_tries_next_dir(self):
        _FakeTranslator.fail_paths.add(self._touch(self.official))
        bundled = self._touch(self.bundle)
        app = _FakeApp()
        self.assertTrue(qt.installChineseTranslator(app))
        self.assertEqual(_FakeTranslator.loaded[-1], bundled)


if __name__ == "__main__":
    unittest.main()
