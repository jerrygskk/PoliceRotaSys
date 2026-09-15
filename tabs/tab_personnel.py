"""人員分頁：純名單（姓名、女警、在職／離職）。

版面與操作自 PoliceDocSys 設定頁「人員管理」子頁搬入：
  - 表格：拖拉把手 ⠿／序號（點一下可打數字搬位置）／姓名／女警／狀態
  - 離職列整列淺灰；沒有刪除（舊月表還指著這個人）
  - 排序先暫存於記憶體，按「儲存排序」才寫入；新增／修改後保留未存順序
拿掉別名欄、權限檢查與稽核（本專案只有承辦人一人使用）。
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QTableWidget, QHeaderView,
)

from lib import members
from lib.db_utils import opened
from ui_utils import confirmBox, msgWarning, preserveScroll, reportError, styleButton
from ui_utils.card import Card
from ui_utils.member_dialog import MemberDialog
from ui_utils.sort_table import (
    COLOR_INACTIVE, makeHandleItem, makeItem, makeSeqItem, setupSortTable,
)


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
        lay.setContentsMargins(20, 16, 20, 16)
        card = Card("人員名單")
        lay.addWidget(card)

        # 左群編輯內容、右群存檔；藍色一區只放一顆
        self.btn_add = styleButton(QPushButton("新增"), "primary")
        self.btn_edit = styleButton(QPushButton("修改"), "normal")
        self.btn_save = styleButton(QPushButton("儲存排序"), "primary")
        card.header.addStretch()
        card.header.addWidget(self.btn_add)
        card.header.addWidget(self.btn_edit)
        card.header.addSpacing(20)
        card.header.addWidget(self.btn_save)

        tbl = self.tbl = QTableWidget(0, len(_HEADERS))
        tbl.setHorizontalHeaderLabels(_HEADERS)
        card.body.addWidget(tbl)

        self._drag_filter, self._seq_delegate = setupSortTable(tbl, _SEQ_COL, self._moveRow)
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

        tbl.itemChanged.connect(self._onSeqItemChanged)

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
        except Exception as exc:
            reportError("讀取人員名單失敗", exc, self)
            return
        self._rows = [list(r) for r in rows]
        self._setDirty(False)
        self._render()

    def _render(self):
        tbl = self.tbl

        def _build():
            tbl.blockSignals(True)   # 重建表格時不要讓 itemChanged 誤判成使用者手動改序號
            try:
                tbl.setRowCount(0)
                for r, (_mid, name, active, female) in enumerate(self._rows):
                    tbl.insertRow(r)
                    color = None if active else COLOR_INACTIVE
                    tbl.setItem(r, _HANDLE_COL, makeHandleItem())
                    seq_item = makeSeqItem(r + 1, color)
                    tbl.setItem(r, _SEQ_COL, seq_item)
                    tbl.setItem(r, _NAME_COL, makeItem(name, color))
                    tbl.setItem(r, _FEMALE_COL, makeItem("✓" if female else "", color))
                    tbl.setItem(r, _STATUS_COL, makeItem("在職" if active else "離職", color))
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
        except Exception as exc:
            reportError("儲存排序失敗", exc, self)
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
