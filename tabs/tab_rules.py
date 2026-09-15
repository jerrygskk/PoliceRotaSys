"""輪番設定分頁（DEVELOPER §4「輪番設定」）。

版面：淺灰底上三張卡片
  - 左：「規則版本」卡片——每筆版本是一張小卡（名稱＋狀態標籤），下方草稿操作鈕與「啟用」
  - 右上：提示條＋「群組」卡片（拖拉把手／序號／名稱／模式／型態／範圍），新增與修改走 GroupDialog
  - 右下：槽位卡片——每格一個圓角方塊。輪番群組點一下切換輪休；雙擊自訂代碼；
    輪休是淡紅底、自訂代碼是淡黃底；標題列右側「輪番群組的番號都由 1 起算」只作用在輪番類型

⚠️ 選到啟用版本時整個編輯區唯讀。按鈕反灰擋不住雙擊、點方塊、Enter、拖拉，
所以**每個進入點都自己檢查一次** `_editable()`；真正的保證仍在資料庫 trigger。
"""
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QListWidget, QListWidgetItem,
    QHeaderView, QLabel, QSplitter, QGridLayout, QTableWidget, QCheckBox,
    QApplication,
)

from lib import ruleset
from lib.db_utils import KEY_SLOT_NUMBER_FROM_ONE, get_setting, opened, set_setting
from lib.members import parse_seq_move_target
from lib.rota import KIND_ALPHA, KIND_CJK, KIND_NUM, MODE_BLANK, MODE_ROTATE, RangeError, detect_kind
from ui_utils import (
    BTN_ROW_SPACING, confirmBox, msgInfo, msgWarning, preserveScroll,
    reportError, styleButton,
)
from ui_utils.card import Card, cardHint, infoBanner, setTone
from ui_utils.group_dialog import GroupDialog
from ui_utils.sort_table import makeHandleItem, makeItem, makeSeqItem, setupSortTable
from ui_utils.text_dialog import askText

_HANDLE_COL, _SEQ_COL, _NAME_COL, _MODE_COL, _KIND_COL, _EXPR_COL = range(6)
_HEADERS = ("", "序號", "名稱", "模式", "型態", "範圍")
_KIND_LABELS = {KIND_NUM: "數字", KIND_ALPHA: "英文", KIND_CJK: "天干"}

SLOTS_PER_ROW = 10
COLOR_READONLY_TEXT = "#8e8e93"


def version_label(row, latest_id):
    """版本的完整文字（無障礙文字與測試用）。"""
    if row["status"] == ruleset.DRAFT:
        return f"草稿「{row['draft_name'] or '未命名'}」　{row['created_at'][:10]}"
    star = "　★ 最新" if row["version_id"] == latest_id else ""
    return f"v{row['version_no']}　啟用　{(row['activated_at'] or '')[:10]}{star}"


def kind_label(mode, expr):
    if mode == MODE_BLANK:
        return "—"
    try:
        return _KIND_LABELS[detect_kind(expr)]
    except RangeError:
        return "?"


class _VersionItem(QWidget):
    """版本清單的一筆：左側名稱與日期，右側狀態標籤。"""

    def __init__(self, row, latest_id, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(2)
        if row["status"] == ruleset.DRAFT:
            name, sub = row["draft_name"] or "未命名", f"{row['created_at'][:10]} 建立"
            badge, tone = "草稿", "draft"
        else:
            name, sub = f"v{row['version_no']}", f"{(row['activated_at'] or '')[:10]} 啟用"
            latest = row["version_id"] == latest_id
            badge, tone = ("啟用・最新", "latest") if latest else ("啟用", "active")
        self.lbl_name = QLabel(name)
        self.lbl_name.setObjectName("versionName")
        self.lbl_sub = cardHint(sub)
        text.addWidget(self.lbl_name)
        text.addWidget(self.lbl_sub)
        lay.addLayout(text, 1)
        self.lbl_badge = QLabel(badge)
        self.lbl_badge.setObjectName("badge")
        setTone(self.lbl_badge, tone)
        lay.addWidget(self.lbl_badge, 0, Qt.AlignVCenter)


class SlotTile(QLabel):
    """槽位方塊。state：work 上班／rest 休／override 自訂代碼；editable 控制滑鼠提示。"""
    clicked = Signal(int)
    doubleClicked = Signal(int)

    def __init__(self, index, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("slotTile")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(60)

    def setState(self, text, state, editable):
        self.setText(text)
        self.setProperty("state", state)
        self.setProperty("editable", "true" if editable else "false")
        self.setCursor(Qt.PointingHandCursor if editable else Qt.ArrowCursor)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self.index)
        super().mouseDoubleClickEvent(event)


def _legendChip(text, state):
    chip = QLabel(text)
    chip.setObjectName("legendChip")
    chip.setProperty("state", state)
    return chip


class TabRules(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._versions = []          # Ruleset_Version 列（清單順序）
        self._groups = []            # [group_id, name, mode, expr]（畫面順序）
        self._slot_seqs = []
        self.slotTiles = []
        self._dirty = False
        # 單擊切輪休要延後執行：Qt 的雙擊一定先送一次單擊，立刻切會先切掉再切回來，
        # 補償失敗就畫面與資料庫不一致（檢視發現）。改成等雙擊時限過了才真的切。
        self._pending_slot = None
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._applyPendingSlotClick)
        self._build()
        self.reload()

    # ── 版面 ────────────────────────────────────────────────────
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(16)
        root.addWidget(splitter)

        # 左：規則版本卡片
        left = Card("規則版本")
        self.list_versions = QListWidget()
        self.list_versions.setObjectName("versionList")
        self.list_versions.setSpacing(3)
        left.body.addWidget(self.list_versions, 1)
        self.btn_new_draft = styleButton(QPushButton("新增草稿"), "normal")
        self.btn_copy = styleButton(QPushButton("複製為草稿"), "normal")
        self.btn_rename = styleButton(QPushButton("改名"), "normal")
        self.btn_delete_draft = styleButton(QPushButton("刪除草稿"), "danger")
        self.btn_activate = styleButton(QPushButton("啟用"), "primary")
        grid = QGridLayout()
        grid.setHorizontalSpacing(BTN_ROW_SPACING)
        grid.setVerticalSpacing(BTN_ROW_SPACING)
        grid.addWidget(self.btn_new_draft, 0, 0)
        grid.addWidget(self.btn_copy, 0, 1)
        grid.addWidget(self.btn_rename, 1, 0)
        grid.addWidget(self.btn_delete_draft, 1, 1)
        left.body.addLayout(grid)
        left.body.addSpacing(6)      # 「啟用」是定案動作，與上面的編輯鈕隔開
        left.body.addWidget(self.btn_activate)
        splitter.addWidget(left)

        # 右：提示條＋群組卡片＋槽位卡片
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(12)
        self.lbl_state = infoBanner("")
        rv.addWidget(self.lbl_state)

        groups_card = Card("群組")
        self.btn_add_group = styleButton(QPushButton("新增群組"), "primary")
        self.btn_edit_group = styleButton(QPushButton("修改"), "normal")
        self.btn_delete_group = styleButton(QPushButton("刪除群組"), "danger")
        self.btn_check = styleButton(QPushButton("檢查規則"), "normal")
        self.btn_save = styleButton(QPushButton("儲存排序"), "primary")
        self.btn_check.setToolTip("檢查所有群組：代碼是否撞號、輪番群組是否整組都是休")
        h = groups_card.header
        h.addStretch()
        for btn in (self.btn_add_group, self.btn_edit_group, self.btn_delete_group):
            h.addWidget(btn)
        h.addSpacing(20)             # 左群編輯內容、右群檢查與存檔
        h.addWidget(self.btn_check)
        h.addWidget(self.btn_save)

        tbl = self.tbl_groups = QTableWidget(0, len(_HEADERS))
        tbl.setHorizontalHeaderLabels(_HEADERS)
        self._drag_filter, self._seq_delegate = setupSortTable(tbl, _SEQ_COL, self._moveRow)
        hdr = tbl.horizontalHeader()
        for col, width in ((_HANDLE_COL, 36), (_SEQ_COL, 64), (_MODE_COL, 90), (_KIND_COL, 80)):
            hdr.setSectionResizeMode(col, QHeaderView.Fixed)
            tbl.setColumnWidth(col, width)
        hdr.setSectionResizeMode(_NAME_COL, QHeaderView.Stretch)
        hdr.setSectionResizeMode(_EXPR_COL, QHeaderView.Stretch)
        groups_card.body.addWidget(tbl)
        rv.addWidget(groups_card, 3)

        self.slots_card = Card("")
        self.lbl_slot_hint = cardHint("")
        self.slots_card.header.addWidget(self.lbl_slot_hint)
        self.slots_card.header.addStretch()
        # 方塊第二行「N番」的算法，只影響畫面、所有群組共用，記在 App_Settings
        self.chk_from_one = QCheckBox("輪番群組的番號都由 1 起算")
        self.chk_from_one.setToolTip("勾選：各輪番群組的番號都由 1 起算（番號 21 顯示為 1番）；未勾選：依原番號顯示（21番）")
        with opened(self.db_path) as conn:
            self.chk_from_one.setChecked(get_setting(conn, KEY_SLOT_NUMBER_FROM_ONE, "1") == "1")
        self.chk_from_one.toggled.connect(self._onFromOneToggled)
        self.slots_card.header.addWidget(self.chk_from_one)
        self.tiles_grid = QGridLayout()
        self.tiles_grid.setHorizontalSpacing(8)
        self.tiles_grid.setVerticalSpacing(8)
        self.slots_card.body.addLayout(self.tiles_grid)
        self.legend = QHBoxLayout()
        self.legend.setSpacing(16)
        self.legend_chips = {}
        for text, state in (("上班", "work"), ("輪休", "rest"), ("自訂代碼", "override")):
            chip = _legendChip(text, state)
            self.legend_chips[state] = chip
            self.legend.addWidget(chip)
        self.legend.addStretch()
        self.slots_card.body.addLayout(self.legend)
        self.slots_card.body.addStretch()
        rv.addWidget(self.slots_card, 2)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([380, 1020])

        self.list_versions.currentRowChanged.connect(self._onVersionChanged)
        self.btn_new_draft.clicked.connect(self._newDraft)
        self.btn_copy.clicked.connect(self._copyDraft)
        self.btn_rename.clicked.connect(self._renameDraft)
        self.btn_delete_draft.clicked.connect(self._deleteDraft)
        self.btn_activate.clicked.connect(self._activate)
        self.btn_add_group.clicked.connect(self._addGroup)
        self.btn_edit_group.clicked.connect(lambda: self._editGroup())
        self.btn_delete_group.clicked.connect(self._deleteGroup)
        self.btn_check.clicked.connect(self._check)
        self.btn_save.clicked.connect(self.saveSort)
        tbl.cellClicked.connect(self._onGroupCellClicked)
        tbl.cellDoubleClicked.connect(self._onGroupCellDoubleClicked)
        tbl.itemChanged.connect(self._onSeqItemChanged)
        tbl.itemSelectionChanged.connect(self._renderSlots)

    # ── 狀態 ────────────────────────────────────────────────────
    def currentVersion(self):
        row = self.list_versions.currentRow()
        return self._versions[row] if 0 <= row < len(self._versions) else None

    def _editable(self):
        v = self.currentVersion()
        return v is not None and v["status"] == ruleset.DRAFT

    def _applyEditable(self):
        v = self.currentVersion()
        editable = self._editable()
        for btn in (self.btn_add_group, self.btn_edit_group, self.btn_delete_group,
                    self.btn_rename, self.btn_delete_draft, self.btn_activate):
            btn.setEnabled(editable)
        self.btn_copy.setEnabled(v is not None)
        self.btn_check.setEnabled(v is not None)
        self.btn_save.setEnabled(editable and self._dirty)
        if v is None:
            self.lbl_state.setText("目前尚無規則版本，請先新增草稿。")
            setTone(self.lbl_state, "info")
        elif editable:
            self.lbl_state.setText("草稿階段可任意修改；在確認無誤後正式啟用，啟用後無法再修改內容。")
            setTone(self.lbl_state, "info")
        else:
            self.lbl_state.setText("已啟用的版本無法修改內容；如需調整，請複製為草稿後編輯。")
            setTone(self.lbl_state, "locked")

    def hasUnsavedSort(self):
        return self._dirty

    def _setDirty(self, dirty):
        self._dirty = dirty
        self.btn_save.setEnabled(self._editable() and dirty)

    # ── 版本清單 ────────────────────────────────────────────────
    def reload(self, select_version_id=None):
        if select_version_id is None and self.currentVersion() is not None:
            select_version_id = self.currentVersion()["version_id"]
        with opened(self.db_path) as conn:
            self._versions = ruleset.list_versions(conn)
            latest = ruleset.latest_active(conn)
        latest_id = latest["version_id"] if latest else None
        self.list_versions.blockSignals(True)
        self.list_versions.clear()
        target = 0
        for i, row in enumerate(self._versions):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, version_label(row, latest_id))
            widget = _VersionItem(row, latest_id)
            item.setSizeHint(QSize(0, widget.sizeHint().height() + 4))
            self.list_versions.addItem(item)
            self.list_versions.setItemWidget(item, widget)
            if row["version_id"] == select_version_id:
                target = i
        self.list_versions.blockSignals(False)
        if self._versions:
            self.list_versions.setCurrentRow(target)
        self._onVersionChanged()

    def _onVersionChanged(self, *_):
        self._setDirty(False)
        self._loadGroups()
        self._applyEditable()

    def _askName(self, title, label, text=""):
        name, ok = askText(self, title, label, text)
        name = (name or "").strip()
        if ok and not name:
            msgWarning(title, "名稱不可空白", self)
            return None
        return name if ok else None

    def _confirmLeaveOrder(self):
        """有未存群組排序時先問；回傳 False＝中止動作。"""
        if not self._dirty:
            return True
        return self.promptUnsaved(context="edit")

    def _newDraft(self):
        if not self._confirmLeaveOrder():
            return
        name = self._askName("新增草稿", "草稿名稱：")
        if name is None:
            return
        try:
            with opened(self.db_path) as conn:
                row = conn.execute("SELECT ruleset_id FROM Ruleset ORDER BY ruleset_id LIMIT 1").fetchone()
                if row is None:
                    rid = conn.execute("INSERT INTO Ruleset(name) VALUES ('輪番規則')").lastrowid
                else:
                    rid = row[0]
                vid = ruleset.create_draft(conn, rid, name)
        except Exception as exc:
            reportError("無法新增草稿", exc, self)
            return
        self.reload(vid)

    def _copyDraft(self):
        v = self.currentVersion()
        if v is None or not self._confirmLeaveOrder():
            return
        default = (f"複製自 v{v['version_no']}" if v["status"] != ruleset.DRAFT
                   else f"{v['draft_name']} 的複本")
        name = self._askName("複製為草稿", "新草稿名稱：", default)
        if name is None:
            return
        try:
            with opened(self.db_path) as conn:
                vid = ruleset.copy_to_draft(conn, v["version_id"], name)
        except Exception as exc:
            reportError("無法複製", exc, self)
            return
        self.reload(vid)

    def _renameDraft(self):
        v = self.currentVersion()
        if not self._editable():
            return
        name = self._askName("草稿改名", "草稿名稱：", v["draft_name"] or "")
        if name is None:
            return
        try:
            with opened(self.db_path) as conn:
                ruleset.rename_draft(conn, v["version_id"], name)
        except Exception as exc:
            reportError("無法改名", exc, self)
            return
        self.reload(v["version_id"])

    def _deleteDraft(self):
        v = self.currentVersion()
        if not self._editable():
            return
        if not confirmBox("刪除草稿", f"確定刪除草稿「{v['draft_name']}」？",
                          confirm_text="刪除", confirm_danger=True, default_confirm=False,
                          informative="刪除後無法復原。", parent=self):
            return
        try:
            with opened(self.db_path) as conn:
                ruleset.delete_draft(conn, v["version_id"])
        except Exception as exc:
            reportError("無法刪除", exc, self)
            return
        self._setDirty(False)
        self.list_versions.setCurrentRow(-1)
        self.reload()

    def _activate(self):
        v = self.currentVersion()
        if not self._editable() or not self._confirmLeaveOrder():
            return
        try:
            with opened(self.db_path) as conn:
                ruleset.check_version(conn, v["version_id"])
                next_no = ruleset.next_version_no(conn)
        except Exception as exc:
            reportError("無法啟用", exc, self)
            return
        if not confirmBox("啟用規則", f"確定將草稿「{v['draft_name']}」啟用為 v{next_no}？",
                          confirm_text="啟用", default_confirm=False,
                          informative="啟用後不能再修改，也不能改回草稿。", parent=self):
            return
        try:
            with opened(self.db_path) as conn:
                ruleset.activate(conn, v["version_id"])
        except Exception as exc:
            reportError("無法啟用", exc, self)
            return
        self.reload(v["version_id"])

    # ── 群組表 ──────────────────────────────────────────────────
    def _loadGroups(self):
        v = self.currentVersion()
        if v is None:
            self._groups = []
        else:
            with opened(self.db_path) as conn:
                self._groups = [[r["group_id"], r["name"], r["mode"], r["range_expr"]]
                                for r in ruleset.group_rows(conn, v["version_id"])]
        self._renderGroups()

    def _renderGroups(self, select_row=None):
        tbl = self.tbl_groups
        if select_row is None:
            select_row = max(self._selectedGroupRow(), 0)
        color = None if self._editable() else COLOR_READONLY_TEXT

        def _build():
            tbl.blockSignals(True)
            try:
                tbl.setRowCount(0)
                for r, (_gid, name, mode, expr) in enumerate(self._groups):
                    tbl.insertRow(r)
                    tbl.setItem(r, _HANDLE_COL, makeHandleItem())
                    tbl.setItem(r, _SEQ_COL, makeSeqItem(r + 1, color))
                    tbl.setItem(r, _NAME_COL, makeItem(name, color))
                    tbl.setItem(r, _MODE_COL, makeItem(ruleset.MODE_LABELS.get(mode, mode), color))
                    tbl.setItem(r, _KIND_COL, makeItem(kind_label(mode, expr), color))
                    tbl.setItem(r, _EXPR_COL, makeItem(expr, color))
            finally:
                tbl.blockSignals(False)

        preserveScroll(tbl, _build)
        if self._groups:
            tbl.selectRow(min(select_row, len(self._groups) - 1))
        self._renderSlots()

    def _selectedGroupRow(self):
        sel = self.tbl_groups.selectedItems()
        return self.tbl_groups.row(sel[0]) if sel else -1

    def _moveRow(self, src, dst):
        if not self._editable():
            return
        self._groups.insert(dst, self._groups.pop(src))
        self._setDirty(True)
        self._renderGroups(select_row=dst)

    def _onGroupCellClicked(self, row, col):
        if col != _SEQ_COL or not self._editable():
            return
        item = self.tbl_groups.item(row, _SEQ_COL)
        if item:
            self.tbl_groups.editItem(item)

    def _onGroupCellDoubleClicked(self, row, col):
        if col == _SEQ_COL or not self._editable():
            return
        self._editGroup(row)

    def _onSeqItemChanged(self, item):
        if item.column() != _SEQ_COL:
            return
        row = item.row()
        target = parse_seq_move_target(item.text(), len(self._groups))
        if not self._editable() or target is None:
            self.tbl_groups.blockSignals(True)
            item.setText(str(row + 1))
            self.tbl_groups.blockSignals(False)
            return
        if target != row:
            self._moveRow(row, target)

    def saveSort(self):
        if not self._editable():
            return False
        try:
            with opened(self.db_path) as conn:
                ruleset.save_group_order(conn, [g[0] for g in self._groups])
        except Exception as exc:
            reportError("儲存失敗", exc, self)
            return False
        self._setDirty(False)
        return True

    def promptUnsaved(self, context="leave"):
        """有未存群組排序時詢問。leave：按離開＝放棄，一律回 True；edit：按取消＝中止（回 False）。"""
        if not self._dirty:
            return True
        msg, cancel = (("離開將遺失排序資料", "離開") if context == "leave"
                       else ("儲存目前排序後繼續編輯？", "取消"))
        if confirmBox("排序未儲存", msg, confirm_text="儲存", cancel_text=cancel, parent=self):
            return self.saveSort() or context == "leave"
        if context == "leave":
            self._setDirty(False)
            return True
        return False

    def _groupRowData(self, group_id):
        with opened(self.db_path) as conn:
            return conn.execute("SELECT * FROM RV_Group WHERE group_id = ?", (group_id,)).fetchone()

    def _reloadGroupsPreservingOrder(self, select_group_id=None):
        old_order = [g[0] for g in self._groups]
        was_dirty = self._dirty
        self._loadGroups()
        pos = {gid: i for i, gid in enumerate(old_order)}
        self._groups.sort(key=lambda g: pos.get(g[0], len(old_order)))   # 新群組排最後
        self._dirty = was_dirty
        row = next((i for i, g in enumerate(self._groups) if g[0] == select_group_id), None)
        self._renderGroups(select_row=row)
        self._applyEditable()

    def _addGroup(self):
        v = self.currentVersion()
        if not self._editable():
            return
        dlg = GroupDialog(self.db_path, v["version_id"], parent=self)
        if dlg.exec():
            self._reloadGroupsPreservingOrder(dlg.group_id)

    def _editGroup(self, row=None):
        if not self._editable():
            return
        if row is None:
            row = self._selectedGroupRow()
        if row < 0:
            msgWarning("請選擇群組", "請先點選要修改的群組", self)
            return
        v = self.currentVersion()
        gid = self._groups[row][0]
        dlg = GroupDialog(self.db_path, v["version_id"], existing=self._groupRowData(gid), parent=self)
        if dlg.exec():
            self._reloadGroupsPreservingOrder(gid)

    def _deleteGroup(self):
        if not self._editable():
            return
        row = self._selectedGroupRow()
        if row < 0:
            msgWarning("請選擇群組", "請先點選要刪除的群組", self)
            return
        gid, name = self._groups[row][0], self._groups[row][1]
        if not confirmBox("刪除群組", f"確定刪除群組「{name}」？",
                          confirm_text="刪除", confirm_danger=True, default_confirm=False,
                          informative="這個群組的槽位設定會一併刪除。", parent=self):
            return
        try:
            with opened(self.db_path) as conn:
                ruleset.delete_group(conn, gid)
        except Exception as exc:
            reportError("無法刪除", exc, self)
            return
        self._reloadGroupsPreservingOrder()

    def _check(self):
        v = self.currentVersion()
        if v is None:
            return
        try:
            with opened(self.db_path) as conn:
                ruleset.check_version(conn, v["version_id"])
        except Exception as exc:
            reportError("規則有問題", exc, self)
            return
        msgInfo("檢查完成", "所有群組檢查無誤：代碼沒有撞號，輪番群組都有人上班。", self)

    # ── 槽位方塊 ────────────────────────────────────────────────
    def _currentGroup(self):
        row = self._selectedGroupRow()
        return self._groups[row] if 0 <= row < len(self._groups) else None

    def _clearTiles(self):
        for tile in self.slotTiles:
            # 先隱藏並脫離卡片：deleteLater 要等事件迴圈才真的刪，
            # 期間舊方塊會以殘影疊在畫面上（上機截圖踩過）
            self.tiles_grid.removeWidget(tile)
            tile.hide()
            tile.setParent(None)
            tile.deleteLater()
        self.slotTiles = []
        self._slot_seqs = []

    def _renderSlots(self):
        self._clearTiles()
        group = self._currentGroup()
        if group is None:
            self.slots_card.setTitle("勤休設定")
            self.chk_from_one.setVisible(False)
            self._showLegend(())
            self.lbl_slot_hint.setText("")
            return
        gid, name, mode, expr = group
        with opened(self.db_path) as conn:
            slots = ruleset.slot_rows(conn, gid)
        try:
            codes = ruleset.expand_codes(mode, expr)
        except RangeError:
            codes = ()
        editable = self._editable()
        for i, s in enumerate(slots):
            default = codes[s["seq"] - 1] if s["seq"] - 1 < len(codes) else ""
            code = s["code_override"] or default
            if mode == MODE_BLANK:
                # 空白欄只顯示欄標題（維護者裁示）
                state, text = "work", code
            elif s["is_rest"]:
                state, text = "rest", f"{code}\n輪休"
            elif s["code_override"]:
                state, text = "override", f"{code}\n原 {default}"
            else:
                number = (s["seq"] if mode == MODE_ROTATE and self.chk_from_one.isChecked()
                          else default)
                state, text = "work", f"{code}\n{number}番"
            tile = SlotTile(i)
            tile.setState(text, state, editable and mode != MODE_BLANK)
            if s["code_override"]:
                tile.setToolTip(f"自訂代碼（預設為 {default}）")
            tile.clicked.connect(self._onSlotClicked)
            tile.doubleClicked.connect(self._onSlotDoubleClicked)
            self.tiles_grid.addWidget(tile, i // SLOTS_PER_ROW, i % SLOTS_PER_ROW)
            self.slotTiles.append(tile)
            self._slot_seqs.append(s["seq"])
        for col in range(SLOTS_PER_ROW):
            self.tiles_grid.setColumnStretch(col, 1)
        self.slots_card.setTitle(f"{name} 勤休設定")
        self.chk_from_one.setVisible(mode == MODE_ROTATE)   # 由 1 起算只作用在輪番類型
        # 圖例只列該群組實際會出現的狀態：輪番三種、固定番沒有輪休、空白欄都沒有
        self._showLegend(
            ("work", "rest", "override") if mode == MODE_ROTATE
            else () if mode == MODE_BLANK else ("work", "override"))
        if not editable:
            hint = f"共 {len(slots)} 格・已啟用的版本不能修改"
        elif mode == MODE_ROTATE:
            hint = f"共 {len(slots)} 格・點一下切換輪休，雙擊可自訂代碼"
        elif mode == MODE_BLANK:
            hint = f"共 {len(slots)} 欄"
        else:
            hint = f"共 {len(slots)} 格・固定番無輪休設定，雙擊可自訂代碼"
        self.lbl_slot_hint.setText(hint)

    def _showLegend(self, states):
        for state, chip in self.legend_chips.items():
            chip.setVisible(state in states)

    def _onFromOneToggled(self, checked):
        with opened(self.db_path) as conn:
            set_setting(conn, KEY_SLOT_NUMBER_FROM_ONE, "1" if checked else "0")
        self._renderSlots()

    def _slotAt(self, index):
        return self._slot_seqs[index] if 0 <= index < len(self._slot_seqs) else None

    def _onSlotClicked(self, index):
        """單擊＝切換輪休，但延後到雙擊時限過後才做（雙擊會先送一次單擊）。"""
        group, seq = self._currentGroup(), self._slotAt(index)
        if not self._editable() or group is None or seq is None or group[2] != MODE_ROTATE:
            return
        self._pending_slot = index
        self._click_timer.start(QApplication.doubleClickInterval())

    def _applyPendingSlotClick(self):
        index, self._pending_slot = self._pending_slot, None
        if index is None:
            return
        group, seq = self._currentGroup(), self._slotAt(index)
        if not self._editable() or group is None or seq is None or group[2] != MODE_ROTATE:
            return
        try:
            with opened(self.db_path) as conn:
                ruleset.toggle_rest(conn, group[0], seq)
        except Exception as exc:
            reportError("無法修改", exc, self)
            return
        self._renderSlots()

    def _onSlotDoubleClicked(self, index):
        group, seq = self._currentGroup(), self._slotAt(index)
        if not self._editable() or group is None or seq is None or group[2] == MODE_BLANK:
            return
        # 取消排隊中的單擊：雙擊只做自訂代碼，不順手切掉輪休
        self._click_timer.stop()
        self._pending_slot = None
        codes = ruleset.expand_codes(group[2], group[3])
        with opened(self.db_path) as conn:
            current = ruleset.slot_rows(conn, group[0])[seq - 1]["code_override"] or codes[seq - 1]
        code, ok = askText(
            self, "自訂代碼", f"第 {seq} 格代碼（預設 {codes[seq - 1]}，清空即回復預設）：", current)
        if ok:
            try:
                with opened(self.db_path) as conn:
                    ruleset.set_code_override(conn, group[0], seq, code)
            except Exception as exc:
                reportError("無法修改", exc, self)
        self._renderSlots()
