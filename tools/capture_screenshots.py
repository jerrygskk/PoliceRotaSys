"""以 Windows Qt 與公開候選資料庫重建 README 的七張正式截圖。"""
from __future__ import annotations

import argparse
import hmac
import os
import sqlite3
from contextlib import closing
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if sys.platform == "win32" and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget

from lib.db_utils import get_setting, opened
from lib.theme import APPLE_STYLE
from main import MainWindow
from ui_utils import installDateEditInputGuard
from ui_utils.group_dialog import GroupDialog
from ui_utils.help_dialog import HelpDialog
from ui_utils.pairing_dialog import PairingDialog
from tools.seed_screenshot_data import (
    CANDIDATE_DIGEST_KEY,
    CANDIDATE_MARKER_KEY,
    CANDIDATE_MARKER_VALUE,
    DISPLAY_MONTH_KEY,
    DISPLAY_YEAR_KEY,
    ROOT_DATABASE,
    candidate_digest,
)

SCREENSHOT_FILENAMES = (
    "01-month-preview.png",
    "02-pairing.png",
    "03-rules.png",
    "04-group-dialog.png",
    "05-personnel.png",
    "06-maintenance.png",
    "07-help.png",
)


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def validate_candidate_database(db_path: Path) -> Path:
    """只接受 seed 工具建立且含完整展示月表的候選資料庫。"""
    db_path = Path(db_path).expanduser().resolve()
    if _same_path(db_path, ROOT_DATABASE):
        raise ValueError("拒絕讀取專案根目錄的正式資料庫 dbfile.db")
    if not db_path.is_file():
        raise ValueError(f"候選資料庫不存在：{db_path}")
    try:
        with closing(sqlite3.connect(db_path)) as conn, conn:
            marker = conn.execute(
                "SELECT value FROM App_Settings WHERE key = ?",
                (CANDIDATE_MARKER_KEY,),
            ).fetchone()
            stored_digest = conn.execute(
                "SELECT value FROM App_Settings WHERE key = ?",
                (CANDIDATE_DIGEST_KEY,),
            ).fetchone()
            actual_digest = candidate_digest(conn)
    except sqlite3.Error as exc:
        raise ValueError(f"不是有效的候選資料庫：{exc}") from exc
    if marker is None or marker[0] != CANDIDATE_MARKER_VALUE or stored_digest is None:
        raise ValueError("不是 seed_screenshot_data.py 建立的完整候選資料庫")
    if not hmac.compare_digest(stored_digest[0], actual_digest):
        raise ValueError("候選資料庫內容指紋不符，可能不完整或已在建立後遭修改")
    return db_path


def validate_output_directory(output: Path, *, force: bool) -> Path:
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    existing = [output / name for name in SCREENSHOT_FILENAMES if (output / name).exists()]
    if existing and not force:
        names = "、".join(path.name for path in existing)
        raise FileExistsError(f"截圖已存在，若要覆寫請加 --force：{names}")
    if any(path.is_dir() for path in existing):
        raise ValueError("固定截圖路徑中含有同名資料夾，無法寫入")
    return output


def _settle(app: QApplication) -> None:
    for _ in range(4):
        app.processEvents()


def _capture(widget: QWidget, output: Path, app: QApplication) -> tuple[int, int]:
    widget.show()
    widget.raise_()
    widget.activateWindow()
    _settle(app)
    pixmap = widget.grab()
    if pixmap.isNull() or pixmap.width() <= 0 or pixmap.height() <= 0:
        raise RuntimeError(f"擷取到空白影像：{output.name}")
    if not pixmap.save(str(output), "PNG") or not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"無法儲存截圖：{output}")
    return pixmap.width(), pixmap.height()


def _display_month(db_path: Path) -> tuple[int, int]:
    with opened(str(db_path)) as conn:
        return (
            int(get_setting(conn, DISPLAY_YEAR_KEY)),
            int(get_setting(conn, DISPLAY_MONTH_KEY)),
        )


def capture_all(db_path: Path, output: Path, *, force: bool = False) -> dict[str, tuple[int, int]]:
    if sys.platform != "win32":
        raise RuntimeError("正式截圖只能在 Windows 執行")
    if os.environ.get("QT_QPA_PLATFORM", "").lower() != "windows":
        raise RuntimeError("QT_QPA_PLATFORM 必須設為 windows，禁止 offscreen 截圖")

    db_path = validate_candidate_database(db_path)
    output = validate_output_directory(output, force=force)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    installDateEditInputGuard(app)
    app.setFont(QFont("Microsoft JhengHei", 14))
    app.setStyleSheet(APPLE_STYLE)

    year, month = _display_month(db_path)
    results: dict[str, tuple[int, int]] = {}
    window = MainWindow(str(db_path))
    window.resize(1440, 780)
    year_index = window.tab_generate.cmb_year.findData(year)
    month_index = window.tab_generate.cmb_month.findData(month)
    if year_index < 0 or month_index < 0:
        raise RuntimeError("候選資料庫的展示月份不在產生月表選單範圍內")
    window.tab_generate.cmb_year.setCurrentIndex(year_index)
    window.tab_generate.cmb_month.setCurrentIndex(month_index)
    window.tab_generate.refresh()

    try:
        window.tabs.setCurrentIndex(0)
        results[SCREENSHOT_FILENAMES[0]] = _capture(
            window, output / SCREENSHOT_FILENAMES[0], app
        )

        pairing = PairingDialog(
            str(db_path), year, month, edit_existing=True, parent=window
        )
        try:
            results[SCREENSHOT_FILENAMES[1]] = _capture(
                pairing, output / SCREENSHOT_FILENAMES[1], app
            )
        finally:
            pairing.close()
            _settle(app)

        window.tabs.setCurrentIndex(1)
        results[SCREENSHOT_FILENAMES[2]] = _capture(
            window, output / SCREENSHOT_FILENAMES[2], app
        )

        with opened(str(db_path)) as conn:
            group = conn.execute(
                "SELECT * FROM T_Group WHERE mode = 'rotate' "
                "ORDER BY sort_order, group_id LIMIT 1"
            ).fetchone()
        group_dialog = GroupDialog(
            str(db_path), group["template_id"], existing=group, parent=window
        )
        try:
            results[SCREENSHOT_FILENAMES[3]] = _capture(
                group_dialog, output / SCREENSHOT_FILENAMES[3], app
            )
        finally:
            group_dialog.close()
            _settle(app)

        window.tabs.setCurrentIndex(2)
        results[SCREENSHOT_FILENAMES[4]] = _capture(
            window, output / SCREENSHOT_FILENAMES[4], app
        )

        window.tabs.setCurrentIndex(3)
        window.tab_maintenance.nav.setCurrentIndex(1)
        results[SCREENSHOT_FILENAMES[5]] = _capture(
            window, output / SCREENSHOT_FILENAMES[5], app
        )

        help_dialog = HelpDialog(0, parent=window)
        try:
            results[SCREENSHOT_FILENAMES[6]] = _capture(
                help_dialog, output / SCREENSHOT_FILENAMES[6], app
            )
        finally:
            help_dialog.close()
            _settle(app)
    finally:
        window.close()
        _settle(app)

    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="擷取 README 正式截圖")
    parser.add_argument("--db", required=True, type=Path, help="seed 工具建立的候選資料庫")
    parser.add_argument("--output", required=True, type=Path, help="PNG 輸出資料夾")
    parser.add_argument("--force", action="store_true", help="覆寫既有七張截圖")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        results = capture_all(args.db, args.output, force=args.force)
    except (FileExistsError, OSError, RuntimeError, ValueError) as exc:
        print(f"錯誤：{exc}")
        return 1
    for name in SCREENSHOT_FILENAMES:
        width, height = results[name]
        print(f"{name}: {width} x {height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
