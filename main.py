"""警察勤務輪番表產生器：程式進入點。

開機流程：建立／補齊資料庫結構 → 第一次開啟時塞入種子資料（假名模板＋一份輪番草稿）
→ 套全域公版樣式 → 開主視窗。

⚠️ 目前有「輪番設定」「人員」分頁；產生月表／維護兩頁依序補上（DEVELOPER §4）。
"""
import logging
import os
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from lib import db_schema, db_seed
from lib.db_utils import opened
from lib.theme import APPLE_STYLE
from lib.version import __version__
from lib.window_geometry import apply_startup_geometry
from res import resources_rc  # noqa: F401  註冊 Qt resource（下拉箭頭、勾選框圖示）
from tabs.tab_personnel import TabPersonnel
from tabs.tab_rules import TabRules
from ui_utils import installDateEditInputGuard

APP_NAME = "警察勤務輪番表產生器"
DB_NAME = "dbfile.db"
LOG_NAME = "error.log"


def db_file_path():
    """資料庫永遠放在程式所在目錄（打包後＝exe 旁，開發時＝專案根目錄）。"""
    base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, DB_NAME)


def setup_logging(log_path):
    """把未預期的錯誤寫進程式目錄的 error.log（ui_utils.reportError 會用到）。"""
    logging.basicConfig(
        filename=log_path, filemode="a", encoding="utf-8", level=logging.ERROR,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def prepare_database(db_path):
    """建立或補齊結構；已有資料時種子資料不會重複塞（seed_all 可重複執行）。"""
    with opened(db_path) as conn:
        db_schema.create_all(conn)
        db_seed.seed_all(conn)


class MainWindow(QMainWindow):
    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        # 預設尺寸照 PoliceDocSys 主視窗（Layout1.ui 的 1440x780）
        self.resize(1440, 780)

        self.tabs = QTabWidget()
        # 分頁順序照使用頻率（DEVELOPER §4）：產生月表／輪番設定／人員設定／維護
        self.tab_rules = TabRules(db_path)
        self.tabs.addTab(self.tab_rules, "輪番設定")
        self.tab_personnel = TabPersonnel(db_path)
        self.tabs.addTab(self.tab_personnel, "人員設定")
        self.setCentralWidget(self.tabs)

    def closeEvent(self, event):
        # 未存排序：詢問儲存或放棄（leave 一律放行關閉）
        self.tab_rules.promptUnsaved(context="leave")
        self.tab_personnel.promptUnsaved(context="leave")
        event.accept()


def main():
    db_path = db_file_path()
    setup_logging(os.path.join(os.path.dirname(db_path), LOG_NAME))
    prepare_database(db_path)

    app = QApplication(sys.argv)
    installDateEditInputGuard(app)
    app.setFont(QFont("Microsoft JhengHei", 14))
    app.setStyleSheet(APPLE_STYLE)

    win = MainWindow(db_path)
    # 開窗前依「實際可用桌面範圍」（已扣工作列）收斂尺寸／位置，避免縮放倍率、
    # 解析度或投影機造成視窗一開就超出畫面；沒超出則不動（PoliceDocSys 同一做法）
    apply_startup_geometry(win, QApplication.primaryScreen())
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
