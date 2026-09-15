"""
card.py — 卡片區塊公版

分頁底色是淺灰（`lib/theme.py` 的 `QTabWidget::pane`），每個區塊放在一張白色圓角卡片裡：
上方一列是粗體標題（右側可放按鈕），下方是內容。外觀全部在 `lib/theme.py` 的
`QFrame#card`／`QLabel#cardTitle`／`QLabel#cardHint`／`QLabel#infoBanner`，這裡不寫任何色碼。
"""
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout


class Card(QFrame):
    """白色圓角卡片：header（標題＋右側元件）與 body（內容）。"""

    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(12)
        self.header = QHBoxLayout()
        self.header.setSpacing(12)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.header.addWidget(self.title)
        outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body)

    def setTitle(self, text):
        self.title.setText(text)


def infoBanner(text=""):
    """提示條（淡藍底）。setProperty('tone', 'locked') 可切成灰色的「唯讀」樣式。"""
    lbl = QLabel(text)
    lbl.setObjectName("infoBanner")
    lbl.setWordWrap(True)
    return lbl


def cardHint(text=""):
    """卡片標題旁的次要說明文字（灰色、較小）。"""
    lbl = QLabel(text)
    lbl.setObjectName("cardHint")
    return lbl


def setTone(widget, tone):
    """切換以動態屬性控制的樣式（例如 infoBanner 的 tone），並讓樣式重新套用。"""
    widget.setProperty("tone", tone)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
