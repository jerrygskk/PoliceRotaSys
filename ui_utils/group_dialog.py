"""
group_dialog.py — 番組新增 / 修改彈窗（輪番設定分頁）

版型照 member_dialog（自 PoliceDocSys 人員設定彈窗搬入）：表單＋右下「取消／儲存」。
  - 名稱：新增時預帶「番組N」
  - 模式：唯讀下拉（輪番／固定／空白欄）。⚠️ 不用可打字 combo（DEVELOPER §4）
  - 範圍：焦點離開即驗語法，錯誤以欄位下方紅字提示，**不跳彈窗**（DEVELOPER §3）
  - 欄寬權重不在這裡：由程式依模式決定（維護者裁示）

⚠️ 彈窗不自帶 stylesheet，外觀全部交給公版 `lib/theme.py`（PITFALLS QSS-8）。
"""
import sqlite3

from PySide6.QtCore    import Qt, QObject, QEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel, QLineEdit, QCheckBox,
    QComboBox, QPlainTextEdit,
)

from lib import ruleset
from lib.db_utils import opened
from lib.rota import MODE_BLANK, MODE_FIXED, MODE_ROTATE, RangeError
from .member_dialog import _add_buttons, _ERR_BORDER_SS, _FIELD_W, _LABEL_W, _MARGIN
from .ui_common import confirmBox, msgCritical, msgWarning

_MODES = (MODE_ROTATE, MODE_FIXED, MODE_BLANK)
_HINTS = {
    MODE_ROTATE: "例：1-20（可用逗號分段：1-5,8-12）",
    MODE_FIXED:  "例：21-28 或 A-F",
    MODE_BLANK:  "欄標題，逗號分隔。例：早,中,晚",
}
_ERR_TEXT_SS = "color: #e74c3c;"


class _FocusOutFilter(QObject):
    def __init__(self, widget, callback):
        super().__init__(widget)
        self._cb = callback

    def eventFilter(self, obj, event):
        if event.type() == QEvent.FocusOut:
            self._cb()
        return False


class GroupDialog(QDialog):
    """existing=None → 新增；existing=RV_Group 列（sqlite3.Row）→ 修改。"""

    def __init__(self, db_path, version_id, existing=None, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.version_id = version_id
        self.existing = existing
        self.is_edit = existing is not None
        self.group_id = existing["group_id"] if self.is_edit else None
        self.reshaped = False
        self.setWindowTitle("修改番組" if self.is_edit else "新增番組")
        self.setMinimumWidth(_LABEL_W + _FIELD_W + _MARGIN)
        self._build()

    def _build(self):
        ex = self.existing
        if not self.is_edit:
            with opened(self.db_path) as conn:
                default_name = ruleset.default_group_name(conn, self.version_id)

        vlay = QVBoxLayout(self)
        vlay.setSpacing(16)
        vlay.setContentsMargins(24, 20, 24, 16)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        self.w_name = QLineEdit(ex["name"] if self.is_edit else default_name)
        self.w_name.setFixedWidth(_FIELD_W)
        form.addRow("名稱：", self.w_name)

        self.w_mode = QComboBox()
        for mode in _MODES:
            self.w_mode.addItem(ruleset.MODE_LABELS[mode], mode)
        self.w_mode.setFixedWidth(_FIELD_W)
        if self.is_edit:
            self.w_mode.setCurrentIndex(_MODES.index(ex["mode"]))
        form.addRow("模式：", self.w_mode)

        self.w_expr = QLineEdit(ex["range_expr"] if self.is_edit else "")
        self.w_expr.setFixedWidth(_FIELD_W)
        form.addRow("範圍：", self.w_expr)
        self.lbl_expr = QLabel("")
        self.lbl_expr.setFixedWidth(_FIELD_W)
        self.lbl_expr.setWordWrap(True)
        form.addRow("", self.lbl_expr)
        self._expr_filter = _FocusOutFilter(self.w_expr, self._validateExpr)
        self.w_expr.installEventFilter(self._expr_filter)

        self.w_header = QCheckBox("左邊加印日期／星期欄")
        self.w_header.setChecked(bool(ex["header_before"]) if self.is_edit else True)
        form.addRow("版面：", self.w_header)

        self.w_note = QPlainTextEdit(ex["note"] if self.is_edit else "")
        self.w_note.setFixedWidth(_FIELD_W)
        self.w_note.setFixedHeight(96)
        self.w_note.setPlaceholderText("選填。一行一筆「顏色|文字」\n顏色：black、red、blue")
        form.addRow("註記：", self.w_note)

        vlay.addLayout(form)
        _, btn_ok = _add_buttons(self, vlay, confirm_text=("儲存" if self.is_edit else "新增"))
        btn_ok.clicked.connect(self._submit)
        self.w_mode.currentIndexChanged.connect(self._onModeChanged)
        self._onModeChanged()
        if self.is_edit:
            self._validateExpr()      # 修改時一開就顯示「共 N 格」
        self.w_name.setFocus()

    def mode(self):
        return self.w_mode.currentData()

    def _onModeChanged(self, *_):
        self.w_expr.setPlaceholderText(_HINTS[self.mode()])
        if self.lbl_expr.text():
            self._validateExpr()

    def _validateExpr(self):
        """語法驗證：錯誤顯示在欄位下方，不跳彈窗。回傳是否合法。"""
        try:
            codes = ruleset.expand_codes(self.mode(), self.w_expr.text())
        except RangeError as exc:
            self.w_expr.setStyleSheet(_ERR_BORDER_SS)
            self.lbl_expr.setStyleSheet(_ERR_TEXT_SS)
            self.lbl_expr.setText(str(exc))
            return False
        self.w_expr.setStyleSheet("")
        self.lbl_expr.setStyleSheet("")
        self.lbl_expr.setText(f"共 {len(codes)} 格")
        return True

    def _submit(self):
        if not self.w_name.text().strip():
            self.w_name.setStyleSheet(_ERR_BORDER_SS)
            return
        self.w_name.setStyleSheet("")
        if not self._validateExpr():
            return
        mode, expr = self.mode(), self.w_expr.text().strip()
        if self.is_edit and (mode != self.existing["mode"] or expr != self.existing["range_expr"]):
            if not confirmBox(
                    "範圍已變更",
                    "模式或範圍已變更，儲存後將重新展開槽位。",
                    confirm_text="儲存", cancel_text="取消",
                    informative="這個番組已設定的休與改寫代碼將全部清空。",
                    parent=self):
                return
        try:
            with opened(self.db_path) as conn:
                if self.is_edit:
                    self.reshaped = ruleset.update_group(
                        conn, self.group_id, self.w_name.text(), mode, expr,
                        self.w_header.isChecked(), self.w_note.toPlainText().strip())
                else:
                    self.group_id = ruleset.add_group(
                        conn, self.version_id, self.w_name.text(), mode, expr,
                        self.w_header.isChecked(), self.w_note.toPlainText().strip())
        except ruleset.RulesetError as exc:
            msgWarning("無法儲存", str(exc), self)
            return
        except sqlite3.Error as exc:
            msgCritical("寫入失敗", f"資料庫寫入失敗：{exc}", self)
            return
        self.accept()
