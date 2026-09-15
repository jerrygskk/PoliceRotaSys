"""輪番設定分頁（DEVELOPER §4「輪番設定」）。

左邊版本清單（草稿在上、啟用在下，★ 標最新）；右邊：
  - 上半：番組表（拖拉把手／序號／名稱／模式／型態／範圍），新增與修改走 GroupDialog
  - 下半：選中番組的槽位格子。輪番組點一下切換「休」；雙擊改寫代碼；改寫過的格子換底色

⚠️ 選到啟用版本時整個編輯區唯讀。按鈕反灰擋不住雙擊、點格子、Enter、拖拉，
所以**每個進入點都自己檢查一次** `_editable()`；真正的保證仍在資料庫 trigger。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QListWidget, QListWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QInputDialog, QSplitter,
    QAbstractItemView,
)

from lib import ruleset
from lib.db_utils import opened
from lib.rota import KIND_ALPHA, KIND_CJK, KIND_NUM, MODE_BLANK, MODE_ROTATE, RangeError, detect_kind
from ui_utils import BTN_CANCEL, BTN_CONFIRM, BTN_DANGER, confirmBox, msgInfo, msgWarning, preserveScroll
from ui_utils.group_dialog import GroupDialog
from ui_utils.sort_table import SAVE_BTN_SS, makeHandleItem, makeItem, makeSeqItem, setupSortTable

_HANDLE_COL, _SEQ_COL, _NAME_COL, _MODE_COL, _KIND_COL, _EXPR_COL = range(6)
_HEADERS = ("", "序號", "名稱", "模式", "型態", "範圍")
_KIND_LABELS = {KIND_NUM: "數字", KIND_ALPHA: "英文", KIND_CJK: "天干"}

SLOTS_PER_ROW = 10
COLOR_REST_TEXT = "#cc0000"
COLOR_OVERRIDE_BG = "#FFF4CC"
COLOR_READONLY_TEXT = "#8e8e93"


def version_label(row, latest_id):
    """版本清單的顯示文字。"""
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


class TabRules(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._versions = []          # Ruleset_Version 列（清單順序）
        self._groups = []            # [group_id, name, mode, expr]（畫面順序）
        self._dirty = False
        self._build()
        self.reload()

    # ── 版面 ────────────────────────────────────────────────────
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # 左：版本清單
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 8, 0)
        lv.addWidget(QLabel("規則版本"))
        self.list_versions = QListWidget()
        lv.addWidget(self.list_versions)
        self.btn_new_draft = QPushButton("＋ 新增草稿")
        self.btn_copy = QPushButton("複製為草稿")
        self.btn_rename = QPushButton("✎ 改名")
        self.btn_delete_draft = QPushButton("刪除草稿")
        self.btn_activate = QPushButton("啟用")
        for btn in (self.btn_new_draft, self.btn_copy, self.btn_rename,
                    self.btn_delete_draft, self.btn_activate):
            lv.addWidget(btn)
        self.btn_new_draft.setStyleSheet(BTN_CONFIRM)
        self.btn_copy.setStyleSheet(BTN_CANCEL)
        self.btn_rename.setStyleSheet(BTN_CANCEL)
        self.btn_delete_draft.setStyleSheet(BTN_DANGER)
        self.btn_activate.setStyleSheet(BTN_CONFIRM)
        splitter.addWidget(left)

        # 右：番組表＋槽位
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 0, 0, 0)
        self.lbl_state = QLabel("")
        rv.addWidget(self.lbl_state)

        row = QHBoxLayout()
        self.btn_add_group = QPushButton("＋ 新增番組")
        self.btn_edit_group = QPushButton("✎ 修改")
        self.btn_delete_group = QPushButton("刪除番組")
        self.btn_check = QPushButton("產 生")
        self.btn_save = QPushButton("💾 儲存排序")
        for btn in (self.btn_add_group, self.btn_edit_group, self.btn_delete_group, self.btn_check):
            row.addWidget(btn)
        row.addStretch()
        row.addWidget(self.btn_save)
        rv.addLayout(row)
        self.btn_add_group.setStyleSheet(BTN_CONFIRM)
        self.btn_edit_group.setStyleSheet(BTN_CANCEL)
        self.btn_delete_group.setStyleSheet(BTN_DANGER)
        self.btn_check.setStyleSheet(BTN_CONFIRM)
        self.btn_save.setStyleSheet(SAVE_BTN_SS)
        self.btn_check.setToolTip("檢查所有番組：代碼是否撞號、輪番組是否整組都是休")

        tbl = self.tbl_groups = QTableWidget(0, len(_HEADERS))
        tbl.setHorizontalHeaderLabels(_HEADERS)
        self._drag_filter, self._seq_delegate = setupSortTable(tbl, _SEQ_COL, self._moveRow)
        hdr = tbl.horizontalHeader()
        for col, width in ((_HANDLE_COL, 36), (_SEQ_COL, 64), (_MODE_COL, 90), (_KIND_COL, 80)):
            hdr.setSectionResizeMode(col, QHeaderView.Fixed)
            tbl.setColumnWidth(col, width)
        hdr.setSectionResizeMode(_NAME_COL, QHeaderView.Stretch)
        hdr.setSectionResizeMode(_EXPR_COL, QHeaderView.Stretch)
        rv.addWidget(tbl, 2)

        self.lbl_slots = QLabel("")
        rv.addWidget(self.lbl_slots)
        self.tbl_slots = QTableWidget(0, SLOTS_PER_ROW)
        self.tbl_slots.horizontalHeader().setVisible(False)
        self.tbl_slots.verticalHeader().setVisible(False)
        self.tbl_slots.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_slots.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl_slots.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_slots.verticalHeader().setDefaultSectionSize(40)
        rv.addWidget(self.tbl_slots, 1)
        self.lbl_slot_hint = QLabel("")
        rv.addWidget(self.lbl_slot_hint)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([360, 1040])

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
        self.tbl_slots.cellClicked.connect(self._onSlotClicked)
        self.tbl_slots.cellDoubleClicked.connect(self._onSlotDoubleClicked)

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
        is_draft = editable
        for btn in (self.btn_add_group, self.btn_edit_group, self.btn_delete_group,
                    self.btn_rename, self.btn_delete_draft, self.btn_activate):
            btn.setEnabled(is_draft)
        self.btn_copy.setEnabled(v is not None)
        self.btn_check.setEnabled(v is not None)
        self.btn_save.setEnabled(editable and self._dirty)
        if v is None:
            self.lbl_state.setText("尚無規則版本，請按「新增草稿」。")
        elif editable:
            self.lbl_state.setText("草稿：可修改。確認無誤後按「啟用」，啟用後不能再改。")
        else:
            self.lbl_state.setText("已啟用的版本不能修改；要調整請按「複製為草稿」。")

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
            item = QListWidgetItem(version_label(row, latest_id))
            if row["status"] != ruleset.DRAFT:
                item.setForeground(QColor(COLOR_READONLY_TEXT if row["version_id"] != latest_id else "#1c1c1e"))
            self.list_versions.addItem(item)
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
        name, ok = QInputDialog.getText(self, title, label, text=text)
        name = (name or "").strip()
        if ok and not name:
            msgWarning(title, "名稱不可空白", self)
            return None
        return name if ok else None

    def _confirmLeaveOrder(self):
        """有未存番組排序時先問；回傳 False＝中止動作。"""
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
            msgWarning("無法新增草稿", _friendly(exc), self)
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
            msgWarning("無法複製", _friendly(exc), self)
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
            msgWarning("無法改名", _friendly(exc), self)
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
            msgWarning("無法刪除", _friendly(exc), self)
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
            msgWarning("無法啟用", _friendly(exc), self)
            return
        if not confirmBox("啟用規則", f"確定將草稿「{v['draft_name']}」啟用為 v{next_no}？",
                          confirm_text="啟用", default_confirm=False,
                          informative="啟用後不能再修改，也不能改回草稿。", parent=self):
            return
        try:
            with opened(self.db_path) as conn:
                ruleset.activate(conn, v["version_id"])
        except Exception as exc:
            msgWarning("無法啟用", _friendly(exc), self)
            return
        self.reload(v["version_id"])

    # ── 番組表 ──────────────────────────────────────────────────
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
        from lib.members import parse_seq_move_target
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
            msgWarning("儲存失敗", _friendly(exc), self)
            return False
        self._setDirty(False)
        return True

    def promptUnsaved(self, context="leave"):
        """有未存番組排序時詢問。leave：按離開＝放棄，一律回 True；edit：按取消＝中止（回 False）。"""
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
        self._groups.sort(key=lambda g: pos.get(g[0], len(old_order)))   # 新番組排最後
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
            msgWarning("請選擇番組", "請先點選要修改的番組", self)
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
            msgWarning("請選擇番組", "請先點選要刪除的番組", self)
            return
        gid, name = self._groups[row][0], self._groups[row][1]
        if not confirmBox("刪除番組", f"確定刪除番組「{name}」？",
                          confirm_text="刪除", confirm_danger=True, default_confirm=False,
                          informative="這個番組的槽位設定會一併刪除。", parent=self):
            return
        try:
            with opened(self.db_path) as conn:
                ruleset.delete_group(conn, gid)
        except Exception as exc:
            msgWarning("無法刪除", _friendly(exc), self)
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
            msgWarning("規則有問題", _friendly(exc), self)
            return
        msgInfo("檢查完成", "所有番組檢查無誤：代碼沒有撞號，輪番組都有人上班。", self)

    # ── 槽位格子 ────────────────────────────────────────────────
    def _currentGroup(self):
        row = self._selectedGroupRow()
        return self._groups[row] if 0 <= row < len(self._groups) else None

    def _renderSlots(self):
        tbl = self.tbl_slots
        tbl.setRowCount(0)
        group = self._currentGroup()
        if group is None:
            self.lbl_slots.setText("")
            self.lbl_slot_hint.setText("")
            return
        gid, name, mode, expr = group
        with opened(self.db_path) as conn:
            slots = ruleset.slot_rows(conn, gid)
        try:
            codes = ruleset.expand_codes(mode, expr)
        except RangeError:
            codes = ()
        self._slot_seqs = [s["seq"] for s in slots]
        editable = self._editable()
        tbl.setRowCount((len(slots) + SLOTS_PER_ROW - 1) // SLOTS_PER_ROW)
        for i, s in enumerate(slots):
            default = codes[s["seq"] - 1] if s["seq"] - 1 < len(codes) else ""
            code = s["code_override"] or default
            text = f"{code} 休" if s["is_rest"] else code
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            if s["is_rest"]:
                item.setForeground(QColor(COLOR_REST_TEXT))
            elif not editable:
                item.setForeground(QColor(COLOR_READONLY_TEXT))
            if s["code_override"]:
                item.setBackground(QColor(COLOR_OVERRIDE_BG))
                item.setToolTip(f"手動改寫（預設為 {default}）")
            tbl.setItem(i // SLOTS_PER_ROW, i % SLOTS_PER_ROW, item)
        self.lbl_slots.setText(f"「{name}」的槽位（共 {len(slots)} 格）")
        if not editable:
            self.lbl_slot_hint.setText("已啟用的版本不能修改。")
        elif mode == MODE_ROTATE:
            self.lbl_slot_hint.setText("點一格切換「休」，雙擊可改寫代碼；底色不同的格子是手動改寫過的。")
        elif mode == MODE_BLANK:
            self.lbl_slot_hint.setText("空白欄只印欄標題，格子留白供手寫；要改欄標題請按「修改」。")
        else:
            self.lbl_slot_hint.setText("固定番沒有休；雙擊可改寫代碼。")

    def _slotAt(self, row, col):
        i = row * SLOTS_PER_ROW + col
        seqs = getattr(self, "_slot_seqs", [])
        return seqs[i] if i < len(seqs) else None

    def _onSlotClicked(self, row, col):
        group, seq = self._currentGroup(), self._slotAt(row, col)
        if not self._editable() or group is None or seq is None or group[2] != MODE_ROTATE:
            return
        try:
            with opened(self.db_path) as conn:
                ruleset.toggle_rest(conn, group[0], seq)
        except Exception as exc:
            msgWarning("無法修改", _friendly(exc), self)
            return
        self._renderSlots()

    def _onSlotDoubleClicked(self, row, col):
        group, seq = self._currentGroup(), self._slotAt(row, col)
        if not self._editable() or group is None or seq is None or group[2] == MODE_BLANK:
            return
        if group[2] == MODE_ROTATE:
            # 雙擊會先觸發一次單擊（切換休），這裡切回來，雙擊只做改寫代碼。
            try:
                with opened(self.db_path) as conn:
                    ruleset.toggle_rest(conn, group[0], seq)
            except Exception:
                pass
        codes = ruleset.expand_codes(group[2], group[3])
        with opened(self.db_path) as conn:
            current = ruleset.slot_rows(conn, group[0])[seq - 1]["code_override"] or codes[seq - 1]
        code, ok = QInputDialog.getText(
            self, "改寫代碼", f"第 {seq} 格代碼（預設 {codes[seq - 1]}，清空即回復預設）：", text=current)
        if ok:
            try:
                with opened(self.db_path) as conn:
                    ruleset.set_code_override(conn, group[0], seq, code)
            except Exception as exc:
                msgWarning("無法修改", _friendly(exc), self)
        self._renderSlots()


def _friendly(exc):
    """資料庫 trigger 的中文訊息原樣給使用者；其餘附上原文。"""
    msg = str(exc)
    return msg if any("一" <= ch <= "鿿" for ch in msg) else f"操作失敗：{msg}"
