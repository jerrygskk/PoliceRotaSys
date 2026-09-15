# -*- coding: utf-8 -*-
"""進版工具的純邏輯：版號讀寫與 version_info 產出（一律在暫存目錄操作）。"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("bump_version", ROOT / "tools" / "bump_version.py")
bump = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump)


class TestBumpVersion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.version_py = Path(self.tmp.name) / "version.py"
        self.version_py.write_text('"""說明"""\n__version__ = "0.1.0"\n', encoding="utf-8")
        self._orig = bump.VERSION_PY
        bump.VERSION_PY = self.version_py
        self.addCleanup(setattr, bump, "VERSION_PY", self._orig)

    def test_read_and_write_round_trip(self):
        self.assertEqual(bump.read_current(), "0.1.0")
        bump.write_version("0.2.3")
        self.assertEqual(bump.read_current(), "0.2.3")
        self.assertIn('"""說明"""', self.version_py.read_text(encoding="utf-8"))

    def test_render_info_pads_to_four_parts(self):
        text = bump.render_info("1.2", bump.PRODUCT, bump.EXE_NAME)
        self.assertIn("filevers=(1, 2, 0, 0)", text)
        self.assertIn("StringStruct('FileVersion', '1.2')", text)
        self.assertIn(bump.EXE_NAME, text)

    def test_repo_version_matches_version_info(self):
        """版本檔與 version_info.txt 必須同步（手改 lib/version.py 就會紅）。"""
        bump.VERSION_PY = self._orig
        info = (ROOT / "version_info.txt").read_text(encoding="utf-8")
        self.assertEqual(info, bump.render_info(bump.read_current(), bump.PRODUCT, bump.EXE_NAME))


if __name__ == "__main__":
    unittest.main()
