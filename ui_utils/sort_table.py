"""
sort_table.py — 可拖拉排序的表格公版（自 PoliceDocSys 設定頁人員管理搬入）

人員分頁與輪番設定的番組表共用：
  - _NoFocusDelegate   去掉「目前儲存格」焦點外框
  - _SeqEditDelegate   序號欄：只能打數字、常駐虛線框提示可點改
  - _RowDragFilter     攔截 Drop，改成整列搬移（Qt InternalMove 只移格）
  - TABLE_SS / SAVE_BTN_SS / COLOR_INACTIVE  表格、儲存排序鈕、停用灰字樣式
  - setupSortTable     套上述行為的一次性設定
"""
from PySide6.QtCore import Qt, QObject, QEvent, QRegularExpression
from PySide6.QtGui import QColor, QPen, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QStyledItemDelegate, QStyle, QLineEdit,
    QAbstractItemView,
)


class _NoFocusDelegate(QStyledItemDelegate):
    """移除「目前儲存格」焦點外框（Windows 樣式點擊後會在該格畫框）。
    僅去焦點框，保留列選取底色（拖拉排序需要 currentRow）。"""
    def paint(self, painter, option, index):
        if option.state & QStyle.State_HasFocus:
            option.state &= ~QStyle.State_HasFocus
        super().paint(painter, option, index)


class _SeqEditDelegate(_NoFocusDelegate):
    """序號欄專用 delegate：editor 限定只能打數字；
    paint 疊一層淺色虛線框，常駐提示「這格可以點來改」（呼應 ⠿ 把手欄的提示風格）。"""

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"[0-9]*"), editor))
        editor.setAlignment(Qt.AlignCenter)
        # 全域 theme.py 對所有 QLineEdit 套 padding: 6px 10px，疊上字級後在固定 36px 列高
        # 裡可能擠到下緣被裁切；padding/margin 歸零騰出空間。border 不覆寫，沿用
        # theme.py 原本的數字（平常 1px、focus 2px，cascade 自動接回來）
        editor.setStyleSheet("font-size: 13pt; padding: 0px; margin: 0px;")
        return editor

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        painter.save()
        pen = QPen(QColor("#9bb0c9"))
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawRect(option.rect.adjusted(2, 2, -3, -3))
        painter.restore()


class _RowDragFilter(QObject):
    """攔截 QTableWidget viewport 的 Drop 事件，實作整列拖拉（Qt InternalMove 只移格，不移列）。"""
    def __init__(self, tbl, callback):
        super().__init__(tbl)
        self._tbl = tbl
        self._cb  = callback  # callback(src_row, dst_row)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Drop:
            src = self._tbl.currentRow()
            dst = self._tbl.rowAt(int(event.position().y()))
            if dst < 0:
                dst = self._tbl.rowCount() - 1
            if src >= 0 and src != dst:
                self._cb(src, dst)
            return True   # 阻止 Qt 的預設錯位行為
        return False


# ── 表格樣式 ────────────────────────────────────────────────────
TABLE_SS = """
    QTableWidget {
        background-color: #ffffff;
        alternate-background-color: #f2f2f7;
        border: none;
        border-top: 1px solid #c6c6c8;
        font-size: 13pt;
        outline: 0;
    }
    QHeaderView::section {
        background-color: #f2f2f7;
        color: #3a3a3c;
        font-weight: 600;
        font-size: 13pt;
        padding: 4px 8px;
        border: none;
        border-bottom: 2px solid #c6c6c8;
        border-right: 1px solid #e5e5ea;
    }
    QTableWidget::item {
        padding: 4px 8px;
        border-bottom: 1px solid #e5e5ea;
    }
    QTableWidget::item:selected {
        background-color: #ccdaeb;
    }
"""

# 停用列（離職人員）灰字
COLOR_INACTIVE = "#aeaeb2"

# 儲存排序鈕樣式（含 disabled 灰色狀態）
SAVE_BTN_SS = """
    QPushButton {
        background-color: #D0ECF5;
        color: #000000;
        border: 1px solid #b0d4e0;
        border-radius: 6px;
        padding: 6px 16px;
        font-size: 13pt;
    }
    QPushButton:hover    { background-color: #B8D8E8; }
    QPushButton:disabled {
        background-color: #e8e8ed;
        color: #aeaeb2;
        border: 1px solid #d1d1d6;
    }
"""


def setupSortTable(tbl, seq_col, on_move, row_height=36):
    """套用排序表格公版：唯讀、整列選取、隔行底色、去焦點框、序號欄可打數字、整列拖拉。

    on_move(src_row, dst_row)：拖拉放下時呼叫。回傳 (drag_filter, seq_delegate)，呼叫端要留著防 GC。
    """
    tbl.verticalHeader().setVisible(False)
    tbl.setEditTriggers(QTableWidget.NoEditTriggers)
    tbl.setSelectionBehavior(QTableWidget.SelectRows)
    tbl.setSelectionMode(QTableWidget.SingleSelection)
    tbl.setAlternatingRowColors(True)
    tbl.setShowGrid(False)
    tbl.verticalHeader().setDefaultSectionSize(row_height)
    tbl.setStyleSheet(TABLE_SS)
    tbl.setItemDelegate(_NoFocusDelegate(tbl))
    tbl.setDragDropMode(QAbstractItemView.InternalMove)
    tbl.setDefaultDropAction(Qt.MoveAction)
    tbl.setAutoScrollMargin(90)
    drag_filter = _RowDragFilter(tbl, on_move)
    tbl.viewport().installEventFilter(drag_filter)
    seq_delegate = _SeqEditDelegate(tbl)
    tbl.setItemDelegateForColumn(seq_col, seq_delegate)
    return drag_filter, seq_delegate


def makeItem(text, color=None):
    """置中、指定前景色的一般格。"""
    it = QTableWidgetItem(str(text) if text is not None else "")
    it.setTextAlignment(Qt.AlignCenter)
    it.setForeground(QColor(color if color else "#1c1c1e"))
    return it


def makeHandleItem():
    """拖拉把手格（⠿）：灰色、置中、提示可拖拉整列。"""
    it = QTableWidgetItem("⠿")
    it.setTextAlignment(Qt.AlignCenter)
    it.setForeground(QColor("#8e8e93"))
    it.setToolTip("按住可拖拉整列以調整排序")
    return it


def makeSeqItem(seq, color=None):
    it = makeItem(seq, color)
    it.setBackground(QColor("#F5F7FA"))
    return it
