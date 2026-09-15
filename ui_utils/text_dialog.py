"""
text_dialog.py — 單行文字輸入彈窗公版

取代 Qt 內建的 `QInputDialog.getText`：內建那個的按鈕是英文 OK／Cancel，也不吃公版按鈕樣式。
版型照 member_dialog：說明文字＋輸入欄＋右下「取消／確定」。

⚠️ 彈窗不自帶 stylesheet，外觀全部交給公版 `lib/theme.py`（PITFALLS QSS-8）。
"""
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QVBoxLayout

from .member_dialog import _add_buttons, _FIELD_W, _LABEL_W


class TextInputDialog(QDialog):
    def __init__(self, title, label, text="", confirm_text="確定", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(_LABEL_W + _FIELD_W + 80)
        vlay = QVBoxLayout(self)
        vlay.setSpacing(12)
        vlay.setContentsMargins(24, 20, 24, 16)
        lbl = QLabel(label)
        lbl.setWordWrap(True)
        vlay.addWidget(lbl)
        self.w_text = QLineEdit(text)
        vlay.addWidget(self.w_text)
        vlay.addSpacing(4)
        _, btn_ok = _add_buttons(self, vlay, confirm_text=confirm_text)
        btn_ok.clicked.connect(self.accept)
        self.w_text.returnPressed.connect(self.accept)
        self.w_text.selectAll()
        self.w_text.setFocus()

    def value(self):
        return self.w_text.text()


def askText(parent, title, label, text="", confirm_text="確定"):
    """開單行輸入彈窗。回傳 (輸入文字, 是否按確定)，與 QInputDialog.getText 同形。"""
    dlg = TextInputDialog(title, label, text, confirm_text, parent)
    ok = bool(dlg.exec())
    return dlg.value(), ok
