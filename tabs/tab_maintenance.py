"""維護分頁（DEVELOPER §4「維護」）。

版面：左側選單（ui_utils/side_nav.py 公版）切換子頁，右側一次顯示一張卡片
（ui_utils/card.py，標題列右側放按鈕）。維護者 2026-09-17：三張卡片直排太長。
  - 月表標題    單位名稱（印在月表最左標題欄）
  - 資料庫備份  開機自動備份說明、異地備份位置、立即備份
  - 壓縮資料庫  VACUUM

儲存鈕平常反灰，有未存修改才亮（比照 PoliceDocSys 設定面板）；存檔成功回灰＝完成回饋。
⚠️ 不做還原、不做回收桶（DEVELOPER §3）：要還原時把 backups 裡的檔案蓋回 dbfile.db。
"""
import os
import tempfile
from datetime import date

from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from lib import db_backup
from lib.db_seed import DEFAULT_SETTINGS
from lib.db_utils import (
    KEY_BACKUP_SECOND_DIR, KEY_UNIT_NAME, get_setting, opened, set_setting,
)
from ui_utils import choiceBox, confirmBox, msgInfo, msgWarning, reportError, styleButton
from ui_utils.card import Card, cardHint, setTone
from ui_utils.side_nav import SideNavPage

# 單位名稱字數上限：實量 PDF 標題欄（維護者 2026-09-17 放大標題後），
# 20 字以內中文維持滿欄寬；再長整串要跟著縮，字會變小。
UNIT_MAX = 20
# 異地最近備份超過此天數即紅字提醒（技術參數，不放 UI 設定）
STALE_DAYS = 7


def normPath(raw):
    """正規化路徑：保留磁碟根與 UNC 根、斜線收斂成反斜線；空字串維持空字串
    （normpath("") 會回 "."）；裸磁碟代號（D:）補成根目錄，避免被當相對路徑。"""
    raw = (raw or "").strip()
    if not raw:
        return ""
    result = os.path.normpath(raw)
    if len(result) == 2 and result[1] == ":" and result[0].isalpha():
        result += os.sep
    return result


def isWritable(path):
    """試建目錄並寫入／刪除一個測試檔，驗證此位置目前可寫入。"""
    try:
        os.makedirs(path, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path, prefix=".backup_test_", suffix=".tmp")
        os.close(fd)
        os.remove(tmp)
        return True
    except Exception:
        return False


def _wrapHint(text):
    lbl = cardHint(text)
    lbl.setWordWrap(True)
    return lbl


class TitleCard(Card):
    """月表標題：單位名稱（比照 PoliceDocSys「簽收表標題」）。"""

    def __init__(self, db_path, parent=None):
        super().__init__("月表標題", parent)
        self.db_path = db_path
        self._loaded = None

        self.btn_reset = styleButton(QPushButton("恢復預設"), "normal")
        self.btn_save = styleButton(QPushButton("儲存"), "primary")
        self.header.addStretch()
        self.header.addWidget(self.btn_reset)
        self.header.addWidget(self.btn_save)

        self.body.addWidget(_wrapHint("印在月表最左側標題欄的單位名稱。"))
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(QLabel("單位名稱"))
        self.w_unit = QLineEdit()
        self.w_unit.setMaxLength(UNIT_MAX)
        self.w_unit.setMinimumWidth(360)
        self.lbl_count = cardHint()
        row.addWidget(self.w_unit)
        row.addWidget(self.lbl_count)
        row.addStretch()
        self.body.addLayout(row)

        self.btn_reset.clicked.connect(self.restoreDefault)
        self.btn_save.clicked.connect(self.save)
        self.w_unit.textChanged.connect(self._onChanged)
        self.reload()

    @staticmethod
    def defaultUnit():
        return DEFAULT_SETTINGS[KEY_UNIT_NAME]

    def reload(self):
        with opened(self.db_path) as conn:
            cur = get_setting(conn, KEY_UNIT_NAME)
        self.w_unit.setText(cur or self.defaultUnit())
        self._loaded = self.w_unit.text().strip()
        self._onChanged()

    def isDirty(self):
        return self._loaded is not None and self.w_unit.text().strip() != self._loaded

    def _onChanged(self, *_):
        n = len(self.w_unit.text())
        self.lbl_count.setText(f"{n} / {UNIT_MAX}")
        setTone(self.lbl_count, "warn" if n >= UNIT_MAX else "near" if n >= UNIT_MAX * 0.9 else "")
        dirty = self.isDirty()
        # 停用持有焦點的按鈕時 Qt 會把焦點塞給下一個輸入欄，先取消焦點
        if not dirty and self.btn_save.hasFocus():
            self.btn_save.clearFocus()
        self.btn_save.setEnabled(dirty)

    def restoreDefault(self):
        """填回預設字串（不立即寫入，按儲存才生效）。"""
        self.w_unit.setText(self.defaultUnit())

    def save(self):
        unit = self.w_unit.text().strip()
        if not unit:
            msgWarning("無法儲存", "單位名稱不可空白。", self)
            return False
        try:
            with opened(self.db_path) as conn:
                set_setting(conn, KEY_UNIT_NAME, unit)
        except Exception as exc:
            reportError("無法儲存", exc, self)
            return False
        # 產生月表分頁切回去時（showEvent）會重讀單位名稱重畫預覽，不必另發訊號
        self.reload()
        return True


class BackupCard(Card):
    """資料庫備份：開機自動備份說明、異地備份位置、立即備份。"""

    def __init__(self, db_path, parent=None):
        super().__init__("資料庫備份", parent)
        self.db_path = db_path
        self._loaded = None

        self.btn_backup_now = styleButton(QPushButton("立即備份"), "normal")
        self.btn_backup_now.setToolTip("備份一份到 backups 資料夾，不會被自動刪除")
        self.btn_save = styleButton(QPushButton("儲存"), "primary")
        self.header.addStretch()
        self.header.addWidget(self.btn_backup_now)
        self.header.addWidget(self.btn_save)

        self.body.addWidget(_wrapHint(
            "程式每天第一次開啟時會自動備份至程式旁的 backups 資料夾"
            "（保留最近 7 天、4 週、12 個月）。\n"
            "可另外指定異地備份位置（建議選另一顆硬碟或網路磁碟），程式開啟時會一併備份一份，"
            "防範整顆硬碟故障；留空則不啟用。"))
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(QLabel("異地備份位置"))
        self.w_path = QLineEdit()
        self.w_path.setPlaceholderText("留空時不啟用異地備份")
        self.btn_pick = styleButton(QPushButton("選擇資料夾"), "normal")
        row.addWidget(self.w_path, 1)
        row.addWidget(self.btn_pick)
        self.body.addLayout(row)
        self.lbl_status = _wrapHint("")
        self.body.addWidget(self.lbl_status)

        self.btn_pick.clicked.connect(self._pick)
        self.btn_save.clicked.connect(self.save)
        self.btn_backup_now.clicked.connect(self.backupNow)
        self.w_path.textChanged.connect(self._onChanged)
        self.reload()

    def reload(self):
        with opened(self.db_path) as conn:
            cur = (get_setting(conn, KEY_BACKUP_SECOND_DIR) or "").strip()
        self.w_path.setText(cur)
        self._loaded = cur
        self._refreshStatus(cur)
        self._onChanged()

    def isDirty(self):
        return self._loaded is not None and self.w_path.text().strip() != self._loaded

    def _onChanged(self, *_):
        dirty = self.isDirty()
        if not dirty and self.btn_save.hasFocus():
            self.btn_save.clearFocus()
        self.btn_save.setEnabled(dirty)

    def _pick(self):
        start = self.w_path.text().strip()
        folder = QFileDialog.getExistingDirectory(
            self, "選擇異地備份位置", start if os.path.isdir(start) else "")
        if folder:
            self.w_path.setText(normPath(folder))

    def _setStatus(self, text, warn=False):
        self.lbl_status.setText(text)
        self.lbl_status.setVisible(bool(text))
        setTone(self.lbl_status, "warn" if warn else "")

    def _refreshStatus(self, path):
        """異地位置狀態：未設定不顯示；本次開機失敗／寫不進／過舊紅字，正常灰字。"""
        if not path:
            self._setStatus("")
            return
        failed = db_backup.last_backup_error(path)
        if failed:
            self._setStatus(failed, warn=True)
            return
        latest = db_backup.latest_backup_date(path)
        if latest is None:
            if isWritable(path):
                self._setStatus("此位置尚無備份，將於下次開啟程式時建立。")
            else:
                self._setStatus(
                    "此位置目前無法寫入，請確認資料夾權限或連線狀態；"
                    "若為需要登入的網路位置，請先開啟過該位置並勾選「記住我的認證」。", warn=True)
            return
        age = (date.today() - latest).days
        if age > STALE_DAYS:
            self._setStatus(f"最近異地備份：{latest:%Y-%m-%d}（已逾 {age} 天，"
                            "請確認此位置是否正常可寫入）。", warn=True)
        else:
            self._setStatus(f"最近異地備份：{latest:%Y-%m-%d}。")

    def save(self):
        try:
            with opened(self.db_path) as conn:
                set_setting(conn, KEY_BACKUP_SECOND_DIR, normPath(self.w_path.text()))
        except Exception as exc:
            reportError("無法儲存", exc, self)
            return False
        self.reload()
        return True

    def backupNow(self):
        dest = db_backup.manual_backup_path(self.db_path)
        if os.path.exists(dest) and not confirmBox(
                "備份已存在", "這一分鐘已經備份過，要覆蓋嗎？",
                confirm_text="覆蓋", confirm_danger=True, default_confirm=False,
                informative=os.path.basename(dest), parent=self):
            return
        try:
            db_backup.manual_backup(self.db_path, dest)
        except Exception as exc:
            reportError("備份失敗", exc, self)
            return
        msgInfo("備份完成", f"已備份到：\n{os.path.normpath(dest)}", self)


class VacuumCard(Card):
    """壓縮資料庫（VACUUM）。"""

    def __init__(self, db_path, parent=None):
        super().__init__("壓縮資料庫", parent)
        self.db_path = db_path
        self.btn_vacuum = styleButton(QPushButton("壓縮資料庫"), "normal")
        self.header.addStretch()
        self.header.addWidget(self.btn_vacuum)
        self.body.addWidget(_wrapHint("刪除月表後，資料庫檔案不會自動變小；壓縮可回收這些空間。"))
        self.btn_vacuum.clicked.connect(self.vacuum)

    def vacuum(self):
        try:
            before, after = db_backup.vacuum(self.db_path)
        except Exception as exc:
            reportError("壓縮失敗", exc, self)
            return
        msgInfo("壓縮完成", f"資料庫大小：{before / 1024:,.0f} KB → {after / 1024:,.0f} KB", self)


class TabMaintenance(QWidget):
    """左側選單切換三個子頁（ui_utils/side_nav.py 公版），一次只顯示一張卡片。"""

    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.card_title = TitleCard(db_path)
        self.card_backup = BackupCard(db_path)
        self.card_vacuum = VacuumCard(db_path)
        self.cards = (self.card_title, self.card_backup, self.card_vacuum)

        self.nav = SideNavPage()
        for card in self.cards:
            page = QWidget()
            col = QVBoxLayout(page)
            col.setContentsMargins(0, 0, 0, 0)
            col.addWidget(card)
            col.addStretch()
            self.nav.addPage(card.title.text(), page)
        self.nav.setLeaveGuard(self._canLeave)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.nav)

    def _canLeave(self, index):
        """離開子頁前：有未存修改就問「儲存／放棄修改／取消」。儲存失敗留在原頁。"""
        card = self.cards[index]
        if not getattr(card, "isDirty", lambda: False)():
            return True
        choice = choiceBox(
            "尚未儲存", f"「{card.title.text()}」尚未儲存，要儲存後切換嗎？",
            ("儲存", "放棄修改"), parent=self)
        if choice is None:
            return False
        if choice == 0:
            return card.save()
        card.reload()
        return True

    def showEvent(self, event):
        # 異地備份狀態、單位名稱可能已變：切進來時重讀（有未存修改就不蓋掉）
        super().showEvent(event)
        for card in (self.card_title, self.card_backup):
            if not card.isDirty():
                card.reload()
