# -*- coding: utf-8 -*-
"""打包設定（PoliceRotaSys.spec）有帶上程式圖示與啟動畫面（unittest，見 test_loading_screen 說明）。"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "PoliceRotaSys.spec"


def _keyword(call_name, keyword):
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    call = next(
        node.value for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", None) == call_name
    )
    return ast.literal_eval(next(item.value for item in call.keywords if item.arg == keyword))


class TestSpecBranding(unittest.TestCase):
    def test_spec_bundles_external_branding_assets(self):
        datas = _keyword("Analysis", "datas")
        self.assertIn(("res/buttons/police_badge.svg", "res/buttons"), datas)
        self.assertIn(("res/buttons/banner.png", "res/buttons"), datas)

    def test_spec_uses_windows_executable_icon(self):
        self.assertEqual(_keyword("EXE", "icon"), ["res\\buttons\\police_badge.ico"])


if __name__ == "__main__":
    unittest.main()
