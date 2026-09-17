"""勤休預定表產生器：程式進入點。

開機流程：檢查資料庫有沒有損毀 → 建立／補齊資料庫結構 → 第一次開啟時塞入種子資料
（假名名單＋一份輪番模板）→ 自動備份（GFS）→ 套全域公版樣式 → 開主視窗。

⚠️ 先檢查、再補結構、最後才備份（PoliceDocSys 同一順序）：對已損毀的檔做 ALTER 會
增加搶救難度；損毀的檔拿去備份會被輪替進 GFS、擠掉還好的舊備份。
"""
import logging
import os
import sys

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from lib import db_backup, db_schema, db_seed
from lib.db_utils import KEY_BACKUP_SECOND_DIR, get_setting, opened
from lib.resource_path import resource_path
from lib.theme import APPLE_STYLE
from lib.version import __version__
from lib.window_geometry import apply_startup_geometry
from res import resources_rc  # noqa: F401  註冊 Qt resource（下拉箭頭、勾選框圖示）
from tabs.tab_generate import TabGenerate
from tabs.tab_maintenance import TabMaintenance
from tabs.tab_personnel import TabPersonnel
from tabs.tab_rules import TabRules
from ui_utils import installDateEditInputGuard, msgCritical
from ui_utils.loading_screen import LoadingScreen

APP_NAME = "勤休預定表產生器"
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


def database_is_healthy(db_path):
    """每次開機快速檢查、每週第一次開機完整檢查。鎖定等無法判定的情況一律放行。"""
    return db_backup.quick_check(db_path) and db_backup.deep_check_if_due(db_path)


def run_auto_backup(db_path):
    """開機自動備份（主備份＋有設定時的異地位置）；任何失敗都不擋開程式。"""
    try:
        with opened(db_path) as conn:
            second = get_setting(conn, KEY_BACKUP_SECOND_DIR).strip()
    except Exception:
        logging.error("讀取異地備份位置失敗", exc_info=True)
        second = ""
    db_backup.run_auto_backup(db_path, extra_dirs=[second] if second else None)


CORRUPT_MESSAGE = (
    "資料庫檔案疑似損毀，為避免損壞擴大，程式將關閉，今天也不會進行自動備份。\n\n"
    "請聯絡維護人員：可從程式旁的 backups 資料夾取回最近的備份檔，"
    "改名為 dbfile.db 後蓋回程式旁的同名檔。"
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
        app = QApplication.instance()
        if app is not None and not app.windowIcon().isNull():
            self.setWindowIcon(app.windowIcon())
        # 預設尺寸照 PoliceDocSys 主視窗（Layout1.ui 的 1440x780）
        self.resize(1440, 780)

        self.tabs = QTabWidget()
        # 分頁順序照使用頻率（DEVELOPER §4）：產生月表／輪番設定／人員設定／功能維護
        self.tab_generate = TabGenerate(db_path)
        self.tabs.addTab(self.tab_generate, "產生月表")
        self.tab_rules = TabRules(db_path)
        self.tabs.addTab(self.tab_rules, "輪番設定")
        self.tab_personnel = TabPersonnel(db_path)
        self.tabs.addTab(self.tab_personnel, "人員設定")
        self.tab_maintenance = TabMaintenance(db_path)
        self.tabs.addTab(self.tab_maintenance, "功能維護")
        self.setCentralWidget(self.tabs)

    def closeEvent(self, event):
        # 未存排序：詢問儲存或放棄（leave 一律放行關閉）
        self.tab_rules.promptUnsaved(context="leave")
        self.tab_personnel.promptUnsaved(context="leave")
        event.accept()


def main():
    db_path = db_file_path()
    setup_logging(os.path.join(os.path.dirname(db_path), LOG_NAME))

    app = QApplication(sys.argv)
    icon_path = resource_path("res/buttons/police_badge.svg")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    installDateEditInputGuard(app)
    app.setFont(QFont("Microsoft JhengHei", 14))
    app.setStyleSheet(APPLE_STYLE)

    loading = LoadingScreen(product_name=APP_NAME)
    loading.show()
    loading.raise_()
    loading.activateWindow()
    app.processEvents()

    def update_loading(desc, percent):
        app.processEvents()
        loading.setStep(desc, percent)
        app.processEvents()

    update_loading("檢查資料庫...", 10)
    if not database_is_healthy(db_path):
        loading.finishAndClose()
        app.processEvents()
        msgCritical("資料庫需要修復", CORRUPT_MESSAGE)
        return 1

    update_loading("準備資料庫...", 35)
    prepare_database(db_path)

    update_loading("備份資料庫...", 60)
    run_auto_backup(db_path)

    update_loading("建立操作介面...", 80)
    win = MainWindow(db_path)
    # 開窗前依「實際可用桌面範圍」（已扣工作列）收斂尺寸／位置，避免縮放倍率、
    # 解析度或投影機造成視窗一開就超出畫面；沒超出則不動（PoliceDocSys 同一做法）
    apply_startup_geometry(win, QApplication.primaryScreen())

    update_loading("啟動完成", 100)
    loading.finishAndClose()
    app.processEvents()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
