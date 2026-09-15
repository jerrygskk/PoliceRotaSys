"""
member_dialog.py — 人員新增 / 修改彈窗

自 PoliceDocSys `settings_dialogs.RefItemDialog`（人員設定）搬入：
  - 拿掉別名（本專案不用可打字 combo）、稽核紀錄、自動編號（member_id 由 SQLite 產生）
  - 加「女警」勾選框（勾了姓名在月表印紅）

⚠️ 彈窗不自帶 stylesheet，外觀全部交給公版 `lib/theme.py`（PITFALLS QSS-8）。
"""
import sqlite3

from PySide6.QtCore    import Qt, QRegularExpression
from PySide6.QtGui     import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox,
)

from lib import members
from lib.db_utils import opened
from .ui_common import BTN_CONFIRM, BTN_CANCEL, BTN_DANGER, msgCritical

_LABEL_W = 100
_FIELD_W = 280
_MARGIN  = 40

# 輸入框驗證失敗（必填留空）的紅框樣式
_ERR_BORDER_SS = "border: 1px solid #e74c3c; border-radius: 4px; padding: 4px 8px;"


def _add_buttons(dlg, layout, confirm_text='儲存', danger=False, default_confirm=True):
    row = QHBoxLayout()
    row.addStretch()
    btn_cancel = QPushButton('取消')
    btn_ok     = QPushButton(confirm_text)
    btn_cancel.setStyleSheet(BTN_CANCEL)
    btn_ok.setStyleSheet(BTN_DANGER if danger else BTN_CONFIRM)
    row.addWidget(btn_cancel)
    row.addWidget(btn_ok)
    layout.addLayout(row)
    btn_cancel.clicked.connect(dlg.reject)
    # default_confirm=True：Enter 確認（確認鈕為 default）
    # default_confirm=False：Enter 不確認，改由取消鈕為 default（高風險操作用，防誤按）
    if default_confirm:
        btn_cancel.setAutoDefault(False); btn_cancel.setDefault(False)
        btn_ok.setAutoDefault(True);      btn_ok.setDefault(True)
    else:
        btn_ok.setAutoDefault(False);     btn_ok.setDefault(False)
        btn_cancel.setAutoDefault(True);  btn_cancel.setDefault(True)
    return btn_cancel, btn_ok


class MemberDialog(QDialog):
    """人員新增 / 修改彈窗。

    - existing=None → 新增模式（INSERT、順序欄可留空塞最前）
    - existing=(member_id, seq, name, active, female) → 修改模式（UPDATE、順序欄預填目前列位置）
    - 結果：get_result() / get_target_position()
    """

    def __init__(self, db_path, existing=None, parent=None):
        super().__init__(parent)
        self.db_path  = db_path
        self.is_edit  = existing is not None
        self._result  = None
        self._target_pos = None
        if self.is_edit:
            self._pk, self._seq, self._old_name, old_active, old_female = existing
            self._old_active = bool(old_active)
            self._old_female = bool(old_female)
        else:
            self._pk = None
            self._seq = None
            self._old_name = None
            self._old_active = None
            self._old_female = False
        self.setWindowTitle("修改人員" if self.is_edit else "新增人員")
        self.setMinimumWidth(_LABEL_W + _FIELD_W + _MARGIN)
        self._build()

    def _count(self):
        with opened(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM Member").fetchone()[0]

    def _build(self):
        count = self._count()
        # 合法範圍上限：新增可插到最後（count+1），修改在既有列間搬移（count）
        seq_max = count + 1 if not self.is_edit else count

        vlay = QVBoxLayout(self)
        vlay.setSpacing(16)
        vlay.setContentsMargins(24, 20, 24, 16)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        self.w_name = QLineEdit(self._old_name if self.is_edit else "")
        if not self.is_edit:
            self.w_name.setPlaceholderText("例：王小明")
        self.w_name.setFixedWidth(_FIELD_W)
        form.addRow("姓名：", self.w_name)

        # 順序欄
        self.w_seq = QLineEdit(str(self._seq) if self.is_edit else "")
        self.w_seq.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"[0-9]*"), self.w_seq))
        self.w_seq.setFixedWidth(80)
        lbl_seq = QLabel("順序：")
        lbl_seq.setFixedWidth(_LABEL_W)
        lbl_seq.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hint = (f"（選填，1～{seq_max}）" if not self.is_edit
                else f"（1～{seq_max}）")
        seq_row = QHBoxLayout()
        seq_row.addWidget(self.w_seq)
        seq_row.addWidget(QLabel(hint))
        seq_row.addStretch()
        form.addRow(lbl_seq, seq_row)

        # 女警：勾了姓名在 xlsx 與 pdf 都印紅色
        self.w_female = QCheckBox("女警")
        self.w_female.setChecked(self._old_female)
        form.addRow("註記：", self.w_female)

        # 狀態（離職）
        self.w_retired = QCheckBox("離職")
        self.w_retired.setChecked(self._old_active is False if self.is_edit else False)
        form.addRow("狀態：", self.w_retired)

        vlay.addLayout(form)
        _, btn_ok = _add_buttons(
            self, vlay, confirm_text=('儲存' if self.is_edit else '新增'))
        btn_ok.clicked.connect(self._submit)
        self.w_name.returnPressed.connect(self._submit)
        self.w_name.setFocus()

    def _submit(self):
        name = self.w_name.text().strip()
        active = not self.w_retired.isChecked()
        female = self.w_female.isChecked()
        if not name:
            self.w_name.setStyleSheet(_ERR_BORDER_SS)
            return
        self.w_name.setStyleSheet("")
        try:
            with opened(self.db_path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM Member").fetchone()[0]
                if self.is_edit:
                    target = members.parse_seq_move_target(self.w_seq.text(), count)
                    seq_bad = target is None
                else:
                    valid, target = members.parse_add_position(self.w_seq.text(), count)
                    seq_bad = not valid
                if seq_bad:
                    self.w_seq.setStyleSheet(_ERR_BORDER_SS)
                    return
                self.w_seq.setStyleSheet("")

                if self.is_edit:
                    members.update_member(conn, self._pk, name, female, active)
                else:
                    self._pk = members.add_member(conn, name, female, active)
                conn.commit()
        except sqlite3.Error as e:
            msgCritical("更新失敗" if self.is_edit else "寫入失敗",
                        f"資料庫寫入失敗：{e}", self)
            return
        self._target_pos = target
        self._result = (self._pk, name, active, female)
        self.accept()

    def get_result(self):
        return self._result

    def get_target_position(self):
        return self._target_pos
