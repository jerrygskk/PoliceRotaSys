"""產生月表分頁（DEVELOPER §4「產生月表」）。

版面：淺灰底上兩張卡片
  - 上：「產生月表」——年、月唯讀下拉（民國），右側「接續上月」「自訂起始」
  - 下：「預覽」——直接用 PDF 的繪圖程式畫出該月月表（ui_utils/sheet_preview.py）

兩條產生的路（維護者裁示，不做條件判斷）：
  接續上月  沿用上月快照往後推，承辦人什麼都不用輸入
  自訂起始  開配對彈窗，選模板、配好每一格

⚠️ 年月用兩個下拉而不是日期欄：焦點停在日期欄時滾輪會靜默改掉日期（CLAUDE.md §B）。
下拉也一樣會吃滾輪，所以掛 installComboWheelGuard。
⚠️ 已產生的月份不可再產生；修改、刪除、匯出是下一階段。
"""
from datetime import date

from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QVBoxLayout, QWidget

from lib import plan
from lib.db_utils import KEY_UNIT_NAME, get_setting, opened
from ui_utils import installComboWheelGuard, msgWarning, reportError, styleButton
from ui_utils.card import Card, cardHint
from ui_utils.pairing_dialog import PairingDialog, rocYear
from ui_utils.sheet_preview import SheetPreview

YEARS_BEFORE = 1       # 年份下拉：今年往前 1 年（補產上月跨年用）
YEARS_AFTER = 1        # 往後 1 年（12 月排明年 1 月用）


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
        self.btn_chain.setToolTip("沿用上個月的規則與名單，番號從上月最後一天接著推")
        self.btn_custom.setToolTip("選一份模板，自己配好每一格 1 日的站位")

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
        root.addWidget(head)

        preview_card = Card("預覽")
        self.preview = SheetPreview()
        preview_card.body.addWidget(self.preview, 1)
        root.addWidget(preview_card, 1)

        self.cmb_year.currentIndexChanged.connect(self.refresh)
        self.cmb_month.currentIndexChanged.connect(self.refresh)
        self.btn_chain.clicked.connect(self._chain)
        self.btn_custom.clicked.connect(self._custom)

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

    def _assertNotGenerated(self, year, month):
        """已產生的月份不可再產生。按鈕不反灰——每個進入點都自己擋。"""
        with opened(self.db_path) as conn:
            exists = plan.get_plan(conn, year, month) is not None
        if exists:
            msgWarning("此月份已產生", f"{self._label(year, month)}已經有月表。", self)
        return not exists

    # ── 產生 ────────────────────────────────────────────────────
    def _chain(self):
        year, month = self.yearMonth()
        if not self._assertNotGenerated(year, month):
            return
        try:
            with opened(self.db_path) as conn:
                reason = plan.chain_blocked_reason(conn, year, month)
                if reason:
                    msgWarning("無法接續上月", f"{reason}，請改用「自訂起始」。", self)
                    return
                plan.create_chained_plan(conn, year, month)
        except Exception as exc:
            reportError("無法產生月表", exc, self)
            return
        self.refresh()

    def _custom(self):
        year, month = self.yearMonth()
        if not self._assertNotGenerated(year, month):
            return
        dlg = PairingDialog(self.db_path, year, month, parent=self)
        if not dlg.exec():
            return
        try:
            with opened(self.db_path) as conn:
                plan.create_plan(conn, year, month, dlg.template_id, dlg.seeds)
        except Exception as exc:
            reportError("無法產生月表", exc, self)
            return
        self.refresh()
