"""產生月表分頁（DEVELOPER §4「產生月表」）。

版面：淺灰底上兩張卡片
  - 上：「產生月表」——年、月唯讀下拉（民國），右側「接續上月」「自訂起始」
  - 下：「預覽」——直接用 PDF 的繪圖程式畫出該月月表（ui_utils/sheet_preview.py）

兩條產生的路（維護者裁示，不做條件判斷）：
  接續上月  沿用上月快照往後推，承辦人什麼都不用輸入
  自訂起始  開配對彈窗，選模板、配好每一格

已產生的月份（維護者裁示：軟擋，不硬擋）：
  兩顆產生鈕照樣能按，先確認「要覆蓋嗎」；已經過去的月份確認框多一句提醒。
  自訂起始覆蓋時，配對彈窗填入這個月現有的配對，只改要改的格。
  「刪除月表」一樣先確認。

匯出：xlsx 與 pdf 一次產出，檔名「115年10月輪番表」。預設存到桌面，確認框可選
  「另存到其他位置」；另存的資料夾只用這一次、不記住（維護者 2026-09-17）。
  同名檔已存在先問覆蓋。

⚠️ 年月用兩個下拉而不是日期欄：焦點停在日期欄時滾輪會靜默改掉日期（CLAUDE.md §B）。
下拉也一樣會吃滾輪，所以掛 installComboWheelGuard。
"""
import os
from datetime import date

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from export import pdf_writer, xlsx_writer
from lib import plan
from lib.db_utils import KEY_UNIT_NAME, get_setting, opened
from ui_utils import (
    choiceBox, confirmBox, installComboWheelGuard, msgInfo, msgWarning, reportError, runWithBusy,
    styleButton,
)
from ui_utils.card import Card, cardHint
from ui_utils.pairing_dialog import PairingDialog, rocYear
from ui_utils.sheet_preview import SheetPreview

YEARS_BEFORE = 1       # 年份下拉：今年往前 1 年（補產上月跨年用）
YEARS_AFTER = 1        # 往後 1 年（12 月排明年 1 月用）


# 本分頁確認框的統一最小寬度（維護者 2026-09-16：撐寬到主文與說明不斷行，
# 但不要大到突兀；幾個確認框一律同寬）。數值是用微軟正黑體 14pt、125% 截圖定的。
CONFIRM_MIN_W = 600


def unbreakablePath(path):
    """讓訊息框不要在路徑中間斷行：每個字之間插入 WORD JOINER（U+2060，不佔寬度）。

    ⚠️ Qt 斷行把反斜線、以及中文字與字之間都當成可斷點，長路徑會斷成「C:」一行、
    其餘一行（維護者回報）。維護者裁示：路徑整段放第二行，不要中途斷開。
    整段不可斷之後，訊息框會自己撐寬（實測長中文路徑撐到約 665px）。
    """
    return "\u2060".join(path)


def exportFileNames(year, month):
    """匯出檔名（不含資料夾）：115年10月輪番表.xlsx／.pdf。"""
    stem = f"{rocYear(year)}年{month}月輪番表"
    return f"{stem}.xlsx", f"{stem}.pdf"


def desktopFolder():
    """使用者桌面（OneDrive 接管桌面時 Qt 也回實際位置）；找不到回空字串。"""
    folder = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
    return folder if folder and os.path.isdir(folder) else ""


def defaultYearMonth(today=None):
    """預設帶「下個月」：承辦人通常是月底排下個月。"""
    today = today or date.today()
    return (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)


class TabGenerate(QWidget):
    def __init__(self, db_path, parent=None, today=None):
        super().__init__(parent)
        self.db_path = db_path
        self._today = today or date.today()
        self._build()
        self.refresh()
        self.btn_custom.setFocus()      # ⚠️ 初始焦點不停在年月下拉上

    # ── 版面 ────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        head = Card("產生月表")
        self.cmb_year = QComboBox()
        for y in range(self._today.year - YEARS_BEFORE, self._today.year + YEARS_AFTER + 1):
            self.cmb_year.addItem(str(rocYear(y)), y)
        self.cmb_month = QComboBox()
        for m in range(1, 13):
            self.cmb_month.addItem(str(m), m)
        # ⚠️ 寬度不靠 sizeHint：125% 下算得剛好（月份文字區實測只剩 21px 塞「10」），
        # 稍有誤差就切字（PoliceDocSys QTW-6）。留最小寬度當餘裕。
        self.cmb_year.setMinimumWidth(120)
        self.cmb_month.setMinimumWidth(104)
        for combo in (self.cmb_year, self.cmb_month):
            installComboWheelGuard(combo)
        year, month = defaultYearMonth(self._today)
        self.cmb_year.setCurrentIndex(self.cmb_year.findData(year))
        self.cmb_month.setCurrentIndex(month - 1)

        self.lbl_status = cardHint("")
        self.btn_chain = styleButton(QPushButton("接續上月"), "normal")
        self.btn_custom = styleButton(QPushButton("自訂起始"), "primary")
        self.btn_export = styleButton(QPushButton("匯出"), "normal")
        self.btn_delete = styleButton(QPushButton("刪除月表"), "danger")
        self.btn_chain.setToolTip("沿用上個月的規則與名單，番號從上月最後一天接著推")
        self.btn_custom.setToolTip("選一份模板，自己配好每一格 1 日的番號")
        self.btn_export.setToolTip("產出 Excel 與 PDF 兩個檔案")

        h = head.header
        h.addSpacing(16)
        h.addWidget(self.cmb_year)
        h.addWidget(QLabel("年"))
        h.addWidget(self.cmb_month)
        h.addWidget(QLabel("月"))
        h.addSpacing(12)
        h.addWidget(self.lbl_status)
        h.addStretch()
        h.addWidget(self.btn_chain)
        h.addWidget(self.btn_custom)
        h.addSpacing(20)             # 左群產生、右群輸出與刪除
        h.addWidget(self.btn_export)
        h.addWidget(self.btn_delete)
        root.addWidget(head)

        preview_card = Card("預覽")
        self.preview = SheetPreview()
        preview_card.body.addWidget(self.preview, 1)
        root.addWidget(preview_card, 1)

        self.cmb_year.currentIndexChanged.connect(self.refresh)
        self.cmb_month.currentIndexChanged.connect(self.refresh)
        self.btn_chain.clicked.connect(self._chain)
        self.btn_custom.clicked.connect(self._custom)
        self.btn_export.clicked.connect(self._export)
        self.btn_delete.clicked.connect(self._delete)

    # ── 狀態 ────────────────────────────────────────────────────
    def yearMonth(self):
        return self.cmb_year.currentData(), self.cmb_month.currentData()

    def _label(self, year, month):
        return f"{rocYear(year)} 年 {month} 月"

    def showEvent(self, event):
        # 單位名稱、標題格式可能在別處改過：切回來時重畫預覽
        super().showEvent(event)
        self.refresh()

    def refresh(self, *_):
        year, month = self.yearMonth()
        label = self._label(year, month)
        try:
            with opened(self.db_path) as conn:
                row = plan.get_plan(conn, year, month)
                sheet = None
                if row is not None:
                    unit = get_setting(conn, KEY_UNIT_NAME)
                    sheet = plan.build_sheet_for(conn, year, month, unit)
        except Exception as exc:
            reportError("無法載入月表", exc, self)
            row, sheet = None, None
        if row is None:
            self.lbl_status.setText("尚未產生")
            self.preview.setSheet(None, f"{label}尚未產生月表")
        else:
            self.lbl_status.setText(f"已產生・{row['origin']}・{row['created_at'][:10]} 建立")
            self.preview.setSheet(sheet)

    def _hasPlan(self, year, month):
        with opened(self.db_path) as conn:
            return plan.get_plan(conn, year, month) is not None

    def isPast(self, year, month):
        """這個月份是否已經過去（早於今天所在的月份）。"""
        return (year, month) < (self._today.year, self._today.month)

    def _pastNote(self, year, month, action="重新產生覆蓋原資料"):
        """過去月份的提醒（維護者 2026-09-16 定稿措辭）：覆蓋與刪除各用自己的動作字眼。"""
        return (f"\n此為歷史勤休預定表，請確認是否要{action}。"
                if self.isPast(year, month) else "")

    def _confirmOverwrite(self, year, month, how):
        """已產生的月份：軟擋，先確認才覆蓋。回傳 (是否繼續, 是否為覆蓋)。"""
        if not self._hasPlan(year, month):
            return True, False
        ok = confirmBox(
            "覆蓋月表",
            f"{self._label(year, month)}已有資料，要以「{how}」重新產生並覆蓋嗎？",
            confirm_text="覆蓋", confirm_danger=True, default_confirm=False,
            informative="覆蓋後原本的月表無法復原。" + self._pastNote(year, month),
            min_width=CONFIRM_MIN_W, parent=self)
        return ok, True

    # ── 產生 ────────────────────────────────────────────────────
    def _chain(self):
        year, month = self.yearMonth()
        try:
            with opened(self.db_path) as conn:
                reason = plan.chain_blocked_reason(conn, year, month)
            if reason:
                msgWarning("無法接續上月", f"{reason}，請改用「自訂起始」。", self)
                return
            ok, overwrite = self._confirmOverwrite(year, month, "接續上月")
            if not ok:
                return
            with opened(self.db_path) as conn:
                plan.create_chained_plan(conn, year, month, overwrite=overwrite)
        except Exception as exc:
            reportError("無法產生月表", exc, self)
            return
        self.refresh()

    def _custom(self):
        year, month = self.yearMonth()
        ok, overwrite = self._confirmOverwrite(year, month, "自訂起始")
        if not ok:
            return
        dlg = PairingDialog(self.db_path, year, month, edit_existing=overwrite, parent=self)
        if not dlg.exec():
            return
        try:
            with opened(self.db_path) as conn:
                plan.create_plan(conn, year, month, dlg.template_id, dlg.seeds,
                                 overwrite=overwrite)
        except Exception as exc:
            reportError("無法產生月表", exc, self)
            return
        self.refresh()

    # ── 刪除 ────────────────────────────────────────────────────
    def _delete(self):
        year, month = self.yearMonth()
        label = self._label(year, month)
        if not self._hasPlan(year, month):
            msgWarning("無法刪除", f"{label}還沒有月表。", self)
            return
        if not confirmBox("刪除月表", f"確定刪除 {label}的月表？",
                          confirm_text="刪除", confirm_danger=True, default_confirm=False,
                          informative="刪除後無法復原；已匯出的 Excel／PDF 檔案不受影響。"
                                      + self._pastNote(year, month, "刪除資料"),
                          min_width=CONFIRM_MIN_W, parent=self):
            return
        try:
            with opened(self.db_path) as conn:
                plan.delete_plan(conn, year, month)
        except Exception as exc:
            reportError("無法刪除", exc, self)
            return
        self.refresh()

    # ── 匯出 ────────────────────────────────────────────────────
    def _exportFolder(self):
        """先問要存桌面還是另存；另存選的資料夾只用這一次。取消回 None。"""
        desktop = desktopFolder()
        if desktop:
            choice = choiceBox(
                "匯出月表", "將匯出到桌面：", ("匯出", "另存到其他位置…"),
                informative=unbreakablePath(os.path.normpath(desktop)),
                min_width=CONFIRM_MIN_W, parent=self)
            if choice is None:
                return None
            if choice == 0:
                return desktop
        folder = QFileDialog.getExistingDirectory(self, "選擇匯出資料夾", desktop)
        return folder or None

    def _export(self):
        year, month = self.yearMonth()
        label = self._label(year, month)
        try:
            with opened(self.db_path) as conn:
                if plan.get_plan(conn, year, month) is None:
                    msgWarning("無法匯出", f"{label}還沒有月表。", self)
                    return
                sheet = plan.build_sheet_for(conn, year, month, get_setting(conn, KEY_UNIT_NAME))
        except Exception as exc:
            reportError("無法匯出", exc, self)
            return
        folder = self._exportFolder()
        if folder is None:
            return
        names = exportFileNames(year, month)
        paths = [os.path.join(folder, name) for name in names]
        existing = [name for name, path in zip(names, paths) if os.path.exists(path)]
        if existing and not confirmBox(
                "檔案已存在", "資料夾裡已經有同名檔案，要覆蓋嗎？",
                confirm_text="覆蓋", confirm_danger=True, default_confirm=False,
                informative="\n".join(existing), min_width=CONFIRM_MIN_W, parent=self):
            return

        def write():
            xlsx_writer.write_sheet(sheet, paths[0])
            pdf_writer.write_sheet(sheet, paths[1])

        try:
            runWithBusy(self, write, "匯出中，請稍候…")
        except PermissionError:
            # 最常見：Excel 或 PDF 閱讀器正開著同名檔，Windows 不讓覆寫
            msgWarning("無法匯出", "檔案可能正被 Excel 或 PDF 閱讀器開啟，請關閉後再匯出。", self)
            return
        except Exception as exc:
            reportError("無法匯出", exc, self)
            return
        msgInfo("匯出完成", f"已匯出到：\n{unbreakablePath(os.path.normpath(folder))}\n\n"
                + "\n".join(names), self)
