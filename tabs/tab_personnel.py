"""人員分頁：純名單（姓名、女警、在職／離職）。

版面與操作自 PoliceDocSys 設定頁「人員管理」子頁搬入：
  - 表格：拖拉把手 ⠿／序號（點一下可打數字搬位置）／姓名／女警／狀態
  - 離職列整列淺灰；沒有刪除（舊月表還指著這個人）
  - 排序先暫存於記憶體，按「儲存排序」才寫入；新增／修改後保留未存順序
拿掉別名欄、權限檢查與稽核（本專案只有承辦人一人使用）。
"""
from PySide6.QtCore import Qt, QObject, QEvent, QRegularExpression
from PySide6.QtGui import QColor, QPen, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QStyledItemDelegate, QStyle, QLineEdit,
    QAbstractItemView,
)

from lib import members
from lib.db_utils import opened
from ui_utils import BTN_CONFIRM, BTN_CANCEL, confirmBox, msgWarning, msgCritical, preserveScroll
from ui_utils.member_dialog import MemberDialog


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
_TABLE_SS = """
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

# 離職列灰字
_COLOR_INACTIVE = "#aeaeb2"

# 儲存排序鈕樣式（含 disabled 灰色狀態）
_SAVE_BTN_SS = """
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

_HANDLE_COL = 0
_SEQ_COL    = 1
_NAME_COL   = 2
_FEMALE_COL = 3
_STATUS_COL = 4
_HEADERS = ("", "序號", "姓名", "女警", "狀態")


class TabPersonnel(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._rows = []        # [[member_id, name, active, female], ...]（畫面順序）
        self._dirty = False
        self._build()
        self.load()

    # ── 版面 ────────────────────────────────────────────────────
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(20, 16, 20, 16)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_add = QPushButton("＋ 新增")
        self.btn_edit = QPushButton("✎ 修改")
        self.btn_save = QPushButton("💾 儲存排序")
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_edit)
        row.addStretch()
        row.addWidget(self.btn_save)
        lay.addLayout(row)

        tbl = self.tbl = QTableWidget(0, len(_HEADERS))
        tbl.setHorizontalHeaderLabels(_HEADERS)
        lay.addWidget(tbl)

        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setSelectionBehavior(QTableWidget.SelectRows)
        tbl.setSelectionMode(QTableWidget.SingleSelection)
        tbl.setAlternatingRowColors(True)
        tbl.setShowGrid(False)
        tbl.verticalHeader().setDefaultSectionSize(36)
        tbl.setStyleSheet(_TABLE_SS)
        tbl.setItemDelegate(_NoFocusDelegate(tbl))
        hdr = tbl.horizontalHeader()
        hdr.setSectionResizeMode(_HANDLE_COL, QHeaderView.Fixed)
        tbl.setColumnWidth(_HANDLE_COL, 36)
        hdr.setSectionResizeMode(_SEQ_COL, QHeaderView.Fixed)
        tbl.setColumnWidth(_SEQ_COL, 64)
        hdr.setSectionResizeMode(_FEMALE_COL, QHeaderView.Fixed)
        tbl.setColumnWidth(_FEMALE_COL, 80)
        hdr.setSectionResizeMode(_STATUS_COL, QHeaderView.Fixed)
        tbl.setColumnWidth(_STATUS_COL, 80)
        hdr.setSectionResizeMode(_NAME_COL, QHeaderView.Stretch)

        # 序號欄：單擊即進行內編輯；其餘欄雙擊開修改對話框
        tbl.cellClicked.connect(self._onCellClicked)
        tbl.cellDoubleClicked.connect(self._onCellDoubleClicked)

        # 拖拉排序（event filter 攔截 Drop，改成整列記憶體操作）
        tbl.setDragDropMode(QAbstractItemView.InternalMove)
        tbl.setDefaultDropAction(Qt.MoveAction)
        tbl.setAutoScrollMargin(90)
        self._drag_filter = _RowDragFilter(tbl, self._moveRow)
        tbl.viewport().installEventFilter(self._drag_filter)

        # 序號欄可編輯（打數字搬移）
        self._seq_delegate = _SeqEditDelegate(tbl)
        tbl.setItemDelegateForColumn(_SEQ_COL, self._seq_delegate)
        tbl.itemChanged.connect(self._onSeqItemChanged)

        self.btn_add.setStyleSheet(BTN_CONFIRM)
        self.btn_edit.setStyleSheet(BTN_CANCEL)
        self.btn_save.setStyleSheet(_SAVE_BTN_SS)
        self.btn_add.clicked.connect(self._addMember)
        self.btn_edit.clicked.connect(lambda: self._editMember())
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.saveSort)

    # ── 載入／重繪 ──────────────────────────────────────────────
    def load(self):
        """從 DB 依 sort_order 撈進記憶體，清掉暫存 dirty，重繪表格。"""
        try:
            with opened(self.db_path) as conn:
                rows = members.list_members(conn)
        except Exception as e:
            msgCritical("DB錯誤", f"讀取人員名單失敗：{e}", self)
            return
        self._rows = [list(r) for r in rows]
        self._setDirty(False)
        self._render()

    def _item(self, text, color=None):
        it = QTableWidgetItem(str(text) if text is not None else "")
        it.setTextAlignment(Qt.AlignCenter)
        it.setForeground(QColor(color if color else "#1c1c1e"))
        return it

    def _handleItem(self):
        """拖拉把手格（⠿）：灰色、置中、提示可拖拉整列。"""
        it = QTableWidgetItem("⠿")
        it.setTextAlignment(Qt.AlignCenter)
        it.setForeground(QColor("#8e8e93"))
        it.setToolTip("按住可拖拉整列以調整排序")
        return it

    def _render(self):
        tbl = self.tbl

        def _build():
            tbl.blockSignals(True)   # 重建表格時不要讓 itemChanged 誤判成使用者手動改序號
            try:
                tbl.setRowCount(0)
                for r, (_mid, name, active, female) in enumerate(self._rows):
                    tbl.insertRow(r)
                    color = None if active else _COLOR_INACTIVE
                    tbl.setItem(r, _HANDLE_COL, self._handleItem())
                    seq_item = self._item(r + 1, color)
                    seq_item.setBackground(QColor("#F5F7FA"))
                    tbl.setItem(r, _SEQ_COL, seq_item)
                    tbl.setItem(r, _NAME_COL, self._item(name, color))
                    tbl.setItem(r, _FEMALE_COL, self._item("✓" if female else "", color))
                    tbl.setItem(r, _STATUS_COL, self._item("在職" if active else "離職", color))
            finally:
                tbl.blockSignals(False)

        # 重繪前後保留捲動位置（新增／修改後不跳回頂端）
        preserveScroll(tbl, _build)

    # ── 排序 ────────────────────────────────────────────────────
    def _setDirty(self, dirty):
        self._dirty = dirty
        self.btn_save.setEnabled(dirty)

    def hasUnsavedSort(self):
        return self._dirty

    def _moveRow(self, src, dst):
        """共用搬移邏輯：拖拉、序號欄編輯、彈窗指定位置三條路徑共用。"""
        self._rows.insert(dst, self._rows.pop(src))
        self._setDirty(True)
        self._render()
        self.tbl.selectRow(dst)

    def _onCellClicked(self, row, col):
        if col != _SEQ_COL:
            return
        item = self.tbl.item(row, _SEQ_COL)
        if item:
            self.tbl.editItem(item)

    def _onCellDoubleClicked(self, row, col):
        if col == _SEQ_COL:
            return
        self._editMember(row)

    def _onSeqItemChanged(self, item):
        """序號欄編輯完成（Enter／離焦）：合法則搬移，不合法安靜跳回原數字。"""
        if item.column() != _SEQ_COL:
            return
        row = item.row()
        target = members.parse_seq_move_target(item.text(), len(self._rows))
        if target is None:
            self.tbl.blockSignals(True)
            item.setText(str(row + 1))
            self.tbl.blockSignals(False)
            return
        if target == row:
            return
        self._moveRow(row, target)

    def saveSort(self):
        """把記憶體順序寫回 DB。成功後鈕反灰即表示已存，不另跳提示。"""
        try:
            with opened(self.db_path) as conn:
                members.save_order(conn, [r[0] for r in self._rows])
        except Exception as e:
            msgCritical("儲存失敗", f"儲存排序失敗：{e}", self)
            return False
        self._setDirty(False)
        return True

    def promptUnsaved(self, context="leave"):
        """有未存排序時詢問。
        context='leave'：按離開＝放棄變更，一律回 True
        context='edit' ：按取消＝保留變更、中止動作（回 False）"""
        if not self._dirty:
            return True
        if context == "leave":
            msg, cancel = "離開將遺失排序資料", "離開"
        else:
            msg, cancel = "儲存目前排序後繼續編輯？", "取消"
        if confirmBox("排序未儲存", msg, confirm_text="儲存", cancel_text=cancel, parent=self):
            return self.saveSort() or context == "leave"
        if context == "leave":
            self._setDirty(False)
            return True
        return False

    def _reloadPreservingOrder(self):
        """新增／修改後重載：取 DB 最新資料，但把動作前的暫存順序套回去
        （新增的列不在舊順序中 → 排到最前），dirty 狀態原樣保留。"""
        old_order = [r[0] for r in self._rows]
        was_dirty = self._dirty
        self.load()
        pos = {mid: i for i, mid in enumerate(old_order)}
        self._rows.sort(key=lambda r: pos.get(r[0], -1))
        self._setDirty(was_dirty)
        self._render()

    # ── 新增／修改 ──────────────────────────────────────────────
    def _selectedRow(self):
        sel = self.tbl.selectedItems()
        return self.tbl.row(sel[0]) if sel else -1

    def _addMember(self):
        dlg = MemberDialog(self.db_path, parent=self)
        if dlg.exec():
            self._afterAdd(dlg)

    def _afterAdd(self, dlg):
        self._reloadPreservingOrder()
        pos = dlg.get_target_position()
        if pos is not None:
            self._moveRow(0, pos)          # 新增後預設在最前，搬到指定位置

    def _editMember(self, row=None):
        if row is None:
            row = self._selectedRow()
        if row < 0:
            msgWarning("請選擇項目", "請先點選要修改的人員", self)
            return
        mid, name, active, female = self._rows[row]
        dlg = MemberDialog(self.db_path, existing=(mid, row + 1, name, active, female),
                           parent=self)
        if dlg.exec() and dlg.get_result():
            self._afterEdit(dlg, row)

    def _afterEdit(self, dlg, row):
        self._reloadPreservingOrder()
        pos = dlg.get_target_position()
        if pos is not None and pos != row:
            self._moveRow(row, pos)
