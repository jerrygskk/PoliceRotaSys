"""環境契約：釘住產品 runtime 相依是一份封閉清單。

AGENTS.md §B：產品 runtime 只能有 PySide6 與 openpyxl。多一個套件就多一段
開機解壓與載入時間，而開啟速度是刻意付出代價換來的。

⚠️ 這支測試守的是**分界**，不是版本號。要加新的 runtime 相依，先問維護者；
得到同意後改 ALLOWED 並在 requirements.txt 一併更新。
"""
import ast
import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# 產品 runtime 允許的第三方套件。標準函式庫不在此限。
ALLOWED = {"PySide6", "openpyxl"}

# 產品程式的範圍（tools/ 與 tests/ 不受限）。
PRODUCT_DIRS = ("lib", "export", "tabs", "ui_utils")

_STDLIB_HINT = re.compile(r"^(?:[a-z_]+)$")


def _product_files():
    for name in PRODUCT_DIRS:
        directory = _ROOT / name
        if directory.is_dir():
            yield from sorted(directory.rglob("*.py"))
    main = _ROOT / "main.py"
    if main.exists():
        yield main


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


class TestRuntimeDependencies(unittest.TestCase):
    def test_product_code_imports_nothing_outside_the_closed_list(self):
        import sys

        stdlib = set(sys.stdlib_module_names)
        local = {"lib", "export", "tabs", "ui_utils", "main", "res"}
        for path in _product_files():
            for module in _top_level_imports(path):
                if module in stdlib or module in local or module in ALLOWED:
                    continue
                self.fail(
                    f"{path.relative_to(_ROOT)} import 了 {module}；"
                    "產品 runtime 相依是封閉清單，要加請先問維護者"
                )

    def test_requirements_matches_the_allowed_set(self):
        text = (_ROOT / "requirements.txt").read_text(encoding="utf-8")
        listed = {
            re.split(r"[=<>!~ ]", line.strip())[0]
            for line in text.splitlines()
            if line.strip() and not line.startswith("#")
        }
        self.assertEqual(listed, ALLOWED)

    def test_reportlab_is_not_imported(self):
        """PDF 走 QPdfWriter；reportlab 是被明確排除的（AGENTS.md §B）。

        ⚠️ 檢查 import 而不是純文字搜尋——註解裡寫「不用 reportlab」會被
        文字搜尋誤判成違規（第一版就這樣自己抓到自己）。
        """
        for path in _product_files():
            self.assertNotIn("reportlab", _top_level_imports(path), str(path))


class TestPinnedVersions(unittest.TestCase):
    """⚠️ 裝好的版本必須與 requirements 裡釘的一致。

    PoliceDocSys 踩過：requirements 的版本號來自**另一支沒有 pytest 的
    直譯器**，與能跑測試的環境不符，而這種不一致**靠人工看不出來**。
    這支測試就是把關的人。

    只檢查「有裝的」——沒裝的套件由它自己的功能測試去 skip，不在這裡重複報。
    """

    # ⚠️ import 名稱與發行名稱可能不同：PySide6 可由 `PySide6` 或
    # `PySide6-Essentials` 提供，查版本時要兩個都試，否則會誤判成沒裝。
    DIST_ALIASES = {"PySide6": ("PySide6", "PySide6-Essentials")}

    def _pins(self, filename):
        text = (_ROOT / filename).read_text(encoding="utf-8")
        pins = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-r"):
                continue
            if "==" in line:
                name, _, version = line.partition("==")
                pins[name.strip()] = version.strip()
        return pins

    def _installed(self, name):
        from importlib.metadata import PackageNotFoundError, version

        for dist in self.DIST_ALIASES.get(name, (name,)):
            try:
                return version(dist)
            except PackageNotFoundError:
                continue
        return None

    def test_installed_versions_match_the_pins(self):
        checked = 0
        for filename in ("requirements.txt", "requirements-dev.txt"):
            for name, pinned in self._pins(filename).items():
                got = self._installed(name)
                if got is None:
                    continue          # 沒裝就不在這裡報
                checked += 1
                self.assertEqual(
                    got, pinned,
                    f"{filename} 釘 {name}=={pinned}，但裝的是 {got}；"
                    "版本號必須是正式 gate 那支 Python 的實際快照",
                )
        self.assertGreater(checked, 0, "一個釘住的套件都沒裝，環境不完整")

    def test_runtime_pins_cover_the_whole_closed_list(self):
        self.assertEqual(set(self._pins("requirements.txt")), ALLOWED)


class TestPureLogicModulesStayPure(unittest.TestCase):
    """★ 五支核心模組零 Qt 相依，才能在無 GUI 環境驗證（DEVELOPER §1）。"""

    PURE = ("lib/rota.py", "lib/layout_model.py")

    def test_core_modules_do_not_import_qt_or_openpyxl(self):
        for name in self.PURE:
            imports = _top_level_imports(_ROOT / name)
            self.assertNotIn("PySide6", imports, name)
            self.assertNotIn("openpyxl", imports, name)

    def test_rota_does_not_touch_the_database(self):
        """rota.py 更嚴格——連 db_utils 都不 import，測它不必準備資料庫。"""
        source = (_ROOT / "lib" / "rota.py").read_text(encoding="utf-8")
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("db_utils", source)


if __name__ == "__main__":
    unittest.main()
