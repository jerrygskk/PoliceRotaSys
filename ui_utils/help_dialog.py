"""程式內使用指引視窗，以及主分頁右上角的共用入口。"""
import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QTabWidget,
    QVBoxLayout, QWidget,
)

from lib.resource_path import resource_path
from lib.theme import HINT_COLOR, TEXT_COLOR
from .help_content import HELP_HTML, HELP_TITLES
from .ui_common import styleButton


class HelpDialog(QDialog):
    """顯示指定主分頁的完整操作說明。"""

    def __init__(self, page_index: int, parent: QWidget | None = None):
        super().__init__(parent)
        if page_index not in HELP_TITLES:
            raise ValueError(f"不存在的說明頁索引：{page_index}")

        self.setWindowTitle(f"使用指引｜{HELP_TITLES[page_index]}")
        self.setModal(True)
        self.resize(860, 680)
        self.setMinimumSize(680, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 14)
        root.setSpacing(10)

        # 標題列：大標＋「使用說明」淺灰，下方一條細橫線。字級在 rich text 裡明寫，
        # 不靠 <h1>（Qt 會套自己的標題放大倍率，字會大到不成比例）。
        head = QHBoxLayout()
        head.setContentsMargins(2, 0, 2, 0)
        self.header = QLabel(
            f'<span style="font-size:18pt; font-weight:600; color:{TEXT_COLOR};">'
            f'{HELP_TITLES[page_index]}</span>'
            f'<span style="font-size:12pt; color:{HINT_COLOR};">　使用說明</span>')
        head.addWidget(self.header)
        head.addStretch(1)
        root.addLayout(head)

        # 橫線的顏色在公版 `lib/theme.py` 的 QLabel#helpRule，元件不自帶 stylesheet
        self.rule = QLabel()
        self.rule.setObjectName("helpRule")
        self.rule.setFixedHeight(2)
        root.addWidget(self.rule)

        self.browser = QTextBrowser()
        self.browser.setObjectName("helpBrowser")
        self.browser.setFrameShape(QFrame.NoFrame)
        self.browser.setOpenExternalLinks(False)
        self.browser.setHtml(HELP_HTML[page_index])
        root.addWidget(self.browser, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.close_button = styleButton(QPushButton("關閉"), "normal")
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)
        root.addLayout(buttons)

        self.close_button.setFocus()


def showHelpDialog(page_index: int, parent: QWidget | None = None) -> None:
    """以 modal 視窗顯示指定分頁的使用指引。"""
    HelpDialog(page_index, parent).exec()


def attachHelpButton(tab_widget: QTabWidget, window: QWidget) -> QPushButton:
    """在分頁列右上角安裝說明鈕；點擊時依目前索引開啟對應頁。"""
    # 外觀走公版 QPushButton#helpButton（與未選取的分頁同一組灰），不自帶 stylesheet。
    # ⚠️ 高度取分頁列的 sizeHint：用寫死的 40 會比分頁矮，看起來像歪掉浮在旁邊。
    button = QPushButton()
    button.setObjectName("helpButton")
    button.setCursor(Qt.PointingHandCursor)
    height = tab_widget.tabBar().sizeHint().height()
    button.setFixedSize(height + 6, height)
    button.setToolTip("開啟目前分頁的使用指引")
    button.setAccessibleName("使用指引")

    icon_path = resource_path("res/buttons/icon_help.svg")
    if os.path.exists(icon_path):
        button.setIcon(QIcon(icon_path))
        button.setIconSize(QSize(height - 16, height - 16))
    else:
        button.setText("？")

    button.clicked.connect(
        lambda _checked=False: showHelpDialog(tab_widget.currentIndex(), window))

    # ⚠️ 角落元件會被 Qt 垂直置中，而分頁是靠上排的（分頁列比分頁本身高），直接放
    # 進去會比分頁低一截、右側也會貼齊視窗邊被切到。包一層容器，用外距把它對齊
    # 第一個分頁的上緣並留右邊界。
    bar = tab_widget.tabBar()
    top = bar.tabRect(0).top() if bar.count() else 0
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, top, 4, 0)
    layout.setSpacing(0)
    layout.addWidget(button)
    tab_widget.setCornerWidget(holder, Qt.TopRightCorner)
    return button
