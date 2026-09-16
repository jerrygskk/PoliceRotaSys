"""
side_nav.py — 左側選單＋右側內容公版（比照 PoliceDocSys 設定頁的左側引導）

版面：左邊固定寬的白色圓角選單（外觀同卡片），右邊一次只顯示一頁。
外觀全部在 `lib/theme.py` 的 `QFrame#sideNav`／`QPushButton#sideNavItem`，這裡不寫任何色碼。

用法：
    nav = SideNavPage()
    nav.addPage("月表標題", widget)
    nav.setLeaveGuard(lambda index: True)   # 回 False＝留在原頁（例如有未存修改被取消）
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

NAV_WIDTH = 180


class SideNavPage(QWidget):
    currentChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._guard = None

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        self.nav = QFrame()
        self.nav.setObjectName("sideNav")
        self.nav.setFixedWidth(NAV_WIDTH)
        self._nav_layout = QVBoxLayout(self.nav)
        self._nav_layout.setContentsMargins(8, 10, 8, 10)
        self._nav_layout.setSpacing(4)
        self._nav_layout.addStretch()
        root.addWidget(self.nav)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self.setCurrentIndex)

    def addPage(self, label, widget):
        """加一頁；回傳頁碼。第一頁自動選取。"""
        index = self.stack.addWidget(widget)
        btn = QPushButton(label)
        btn.setObjectName("sideNavItem")
        btn.setCheckable(True)
        # 選單項目不搶 Enter 預設鈕
        btn.setAutoDefault(False)
        self._group.addButton(btn, index)
        self._nav_layout.insertWidget(self._nav_layout.count() - 1, btn)
        if index == 0:
            btn.setChecked(True)
        return index

    def setLeaveGuard(self, guard):
        """guard(目前頁碼) 回 False 時不切換。"""
        self._guard = guard

    def currentIndex(self):
        return self.stack.currentIndex()

    def navButton(self, index):
        return self._group.button(index)

    def setCurrentIndex(self, index):
        current = self.stack.currentIndex()
        if index != current and self._guard is not None and not self._guard(current):
            # 點下去的按鈕已被勾起，退回原頁的勾選
            self._group.button(current).setChecked(True)
            return False
        self._group.button(index).setChecked(True)
        if index != current:
            self.stack.setCurrentIndex(index)
            self.currentChanged.emit(index)
        return True
