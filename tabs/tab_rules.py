"""輪番設定分頁（DEVELOPER §4「輪番設定」）。

版面：淺灰底上三張卡片
  - 左：「輪番模板」卡片——每份模板是一張小卡（名稱＋建立日期），下方新增／複製／改名／刪除
  - 右上：提示條＋「群組」卡片（拖拉把手／序號／名稱／模式／型態／範圍），新增與修改走 GroupDialog
  - 右下：槽位卡片——每格一個圓角方塊。輪番群組點一下切換輪休；雙擊自訂代碼；
    輪休是淡紅底、自訂代碼是淡黃底；標題列右側「輪番群組的番號都由 1 起算」只作用在輪番類型

⚠️ 模板可隨時修改——改模板**不影響已經產生的月表**（月表有自己的快照，
見 lib/plan.py）。沒選到模板時整個編輯區不可操作；按鈕反灰擋不住雙擊、
點方塊、Enter、拖拉，所以**每個進入點都自己檢查一次** `_editable()`。
"""
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QListWidget, QListWidgetItem,
    QHeaderView, QLabel, QSplitter, QGridLayout, QTableWidget, QCheckBox,
    QApplication, QScrollArea, QFrame,
)

from lib import template
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

_HANDLE_COL, _SEQ_COL, _NAME_COL, _MODE_COL, _KIND_COL, _EXPR_COL, _DATE_COL = range(7)
_HEADERS = ("", "序號", "群組名稱", "模式", "型態", "範圍", "左側日期")
_KIND_LABELS = {KIND_NUM: "數字", KIND_ALPHA: "英文", KIND_CJK: "天干"}

SLOTS_PER_ROW = 10
# 勤休方塊最多直接顯示幾排，超過才在卡片內捲動（維護者裁示：做到 30 格）。
# 3 排以內照原本作法，卡片往上長、擠壓群組表（3 排時群組表第 6 列會被切到、出現捲軸，
# 維護者接受）；不設上限的話 50 格群組表只剩一列，80 格以上連視窗都裝不下。
MAX_VISIBLE_TILE_ROWS = 3
TILE_H = 60
TILE_SPACING = 8
COLOR_READONLY_TEXT = "#8e8e93"


def template_label(row):
    """模板的完整文字（無障礙文字與測試用）。"""
    return f"模板「{row['name']}」　{row['created_at'][:10]} 建立"


def kind_label(mode, expr):
    if mode == MODE_BLANK:
        return "—"
    try:
        return _KIND_LABELS[detect_kind(expr)]
    except RangeError:
        return "?"


class _TemplateItem(QWidget):
    """模板清單的一筆：名稱與建立日期。"""

    def __init__(self, row, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.lbl_name = QLabel(row["name"])
        self.lbl_name.setObjectName("templateName")
        self.lbl_sub = cardHint(f"{row['created_at'][:10]} 建立")
        text.addWidget(self.lbl_name)
        text.addWidget(self.lbl_sub)
        lay.addLayout(text, 1)


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
        self._templates = []          # Rota_Template 列（清單順序）
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

        # 左：輪番模板卡片
        left = Card("輪番模板")
        self.list_templates = QListWidget()
        self.list_templates.setObjectName("templateList")
        self.list_templates.setSpacing(3)
        left.body.addWidget(self.list_templates, 1)
        self.btn_new_template = styleButton(QPushButton("新增模板"), "primary")
        self.btn_copy = styleButton(QPushButton("複製一份"), "normal")
        self.btn_rename = styleButton(QPushButton("改名"), "normal")
        self.btn_delete_template = styleButton(QPushButton("刪除模板"), "danger")
        grid = QGridLayout()
        grid.setHorizontalSpacing(BTN_ROW_SPACING)
        grid.setVerticalSpacing(BTN_ROW_SPACING)
        grid.addWidget(self.btn_new_template, 0, 0)
        grid.addWidget(self.btn_copy, 0, 1)
        grid.addWidget(self.btn_rename, 1, 0)
        grid.addWidget(self.btn_delete_template, 1, 1)
        left.body.addLayout(grid)
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
        self.btn_check.setToolTip("檢查所有群組：代碼是否衝突、輪番群組是否整組都是休")
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
        for col, width in ((_HANDLE_COL, 36), (_SEQ_COL, 64), (_MODE_COL, 90), (_KIND_COL, 80),
                           (_DATE_COL, 100)):
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
            # 預設不勾（維護者裁示 2026-09-16）：照原番號顯示
            self.chk_from_one.setChecked(get_setting(conn, KEY_SLOT_NUMBER_FROM_ONE, "0") == "1")
        self.chk_from_one.toggled.connect(self._onFromOneToggled)
        # 圖例放在標題列、勾選框左邊，不另佔卡片底下一列——省下的高度讓 3 排方塊
        # 不必擠壓上面的群組表
        self.legend_chips = {}
        for text, state in (("上班", "work"), ("輪休", "rest"), ("自訂", "override")):
            chip = _legendChip(text, state)
            self.legend_chips[state] = chip
            self.slots_card.header.addWidget(chip)
        self.slots_card.header.addSpacing(12)
        self.slots_card.header.addWidget(self.chk_from_one)
        tiles_host = QWidget()
        self.tiles_grid = QGridLayout(tiles_host)
        self.tiles_grid.setContentsMargins(0, 0, 4, 0)      # 右邊留一點給捲軸，方塊不貼著它
        self.tiles_grid.setHorizontalSpacing(TILE_SPACING)
        self.tiles_grid.setVerticalSpacing(TILE_SPACING)
        self.tiles_grid.setAlignment(Qt.AlignTop)
        self.tiles_scroll = QScrollArea()
        self.tiles_scroll.setWidget(tiles_host)
        self.tiles_scroll.setWidgetResizable(True)
        self.tiles_scroll.setFrameShape(QFrame.NoFrame)
        self.tiles_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.slots_card.body.addWidget(self.tiles_scroll)
        self.slots_card.body.addStretch()
        rv.addWidget(self.slots_card, 2)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([380, 1020])

        self.list_templates.currentRowChanged.connect(self._onVersionChanged)
        self.btn_new_template.clicked.connect(self._newTemplate)
        self.btn_copy.clicked.connect(self._copyTemplate)
        self.btn_rename.clicked.connect(self._renameTemplate)
        self.btn_delete_template.clicked.connect(self._deleteTemplate)
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
    def currentTemplate(self):
        row = self.list_templates.currentRow()
        return self._templates[row] if 0 <= row < len(self._templates) else None

    def _editable(self):
        return self.currentTemplate() is not None

    def _applyEditable(self):
        editable = self._editable()
        for btn in (self.btn_add_group, self.btn_edit_group, self.btn_delete_group,
                    self.btn_rename, self.btn_delete_template, self.btn_copy,
                    self.btn_check):
            btn.setEnabled(editable)
        self.btn_save.setEnabled(editable and self._dirty)
        if not editable:
            self.lbl_state.setText("目前尚無輪番模板，請先新增模板。")
        else:
            self.lbl_state.setText("模板可隨時修改；修改模板不會影響已經產生的月表。")
        setTone(self.lbl_state, "info")

    def hasUnsavedSort(self):
        return self._dirty

    def _setDirty(self, dirty):
        self._dirty = dirty
        self.btn_save.setEnabled(self._editable() and dirty)

    # ── 版本清單 ────────────────────────────────────────────────
    def reload(self, select_template_id=None):
        if select_template_id is None and self.currentTemplate() is not None:
            select_template_id = self.currentTemplate()["template_id"]
        with opened(self.db_path) as conn:
            self._templates = template.list_templates(conn)
        self.list_templates.blockSignals(True)
        self.list_templates.clear()
        target = 0
        for i, row in enumerate(self._templates):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, template_label(row))
            widget = _TemplateItem(row)
            item.setSizeHint(QSize(0, widget.sizeHint().height() + 4))
            self.list_templates.addItem(item)
            self.list_templates.setItemWidget(item, widget)
            if row["template_id"] == select_template_id:
                target = i
        self.list_templates.blockSignals(False)
        if self._templates:
            self.list_templates.setCurrentRow(target)
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

    def _newTemplate(self):
        if not self._confirmLeaveOrder():
            return
        with opened(self.db_path) as conn:
            default = template.default_template_name(conn)
        name = self._askName("新增模板", "模板名稱：", default)
        if name is None:
            return
        try:
            with opened(self.db_path) as conn:
                tid = template.create_template(conn, name)
        except Exception as exc:
            reportError("無法新增模板", exc, self)
            return
        self.reload(tid)

    def _copyTemplate(self):
        t = self.currentTemplate()
        if t is None or not self._confirmLeaveOrder():
            return
        name = self._askName("複製模板", "新模板名稱：", f"{t['name']} 的複本")
        if name is None:
            return
        try:
            with opened(self.db_path) as conn:
                tid = template.copy_template(conn, t["template_id"], name)
        except Exception as exc:
            reportError("無法複製", exc, self)
            return
        self.reload(tid)

    def _renameTemplate(self):
        t = self.currentTemplate()
        if not self._editable():
            return
        name = self._askName("模板改名", "模板名稱：", t["name"])
        if name is None:
            return
        try:
            with opened(self.db_path) as conn:
                template.rename_template(conn, t["template_id"], name)
        except Exception as exc:
            reportError("無法改名", exc, self)
            return
        self.reload(t["template_id"])

    def _deleteTemplate(self):
        t = self.currentTemplate()
        if not self._editable():
            return
        if not confirmBox("刪除模板", f"確定刪除模板「{t['name']}」？",
                          confirm_text="刪除", confirm_danger=True, default_confirm=False,
                          informative="刪除後無法復原。已經產生的月表不受影響。",
                          parent=self):
            return
        try:
            with opened(self.db_path) as conn:
                template.delete_template(conn, t["template_id"])
        except Exception as exc:
            reportError("無法刪除", exc, self)
            return
        self._setDirty(False)
        self.list_templates.setCurrentRow(-1)
        self.reload()

    # ── 群組表 ──────────────────────────────────────────────────
    def _loadGroups(self):
        t = self.currentTemplate()
        if t is None:
            self._groups = []
        else:
            with opened(self.db_path) as conn:
                self._groups = [[r["group_id"], r["name"], r["mode"], r["range_expr"],
                                 bool(r["header_before"])]
                                for r in template.group_rows(conn, t["template_id"])]
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
                for r, (_gid, name, mode, expr, header) in enumerate(self._groups):
                    tbl.insertRow(r)
                    tbl.setItem(r, _HANDLE_COL, makeHandleItem())
                    tbl.setItem(r, _SEQ_COL, makeSeqItem(r + 1, color))
                    tbl.setItem(r, _NAME_COL, makeItem(name, color))
                    tbl.setItem(r, _MODE_COL, makeItem(template.MODE_LABELS.get(mode, mode), color))
                    tbl.setItem(r, _KIND_COL, makeItem(kind_label(mode, expr), color))
                    tbl.setItem(r, _EXPR_COL, makeItem(expr, color))
                    tbl.setItem(r, _DATE_COL, makeItem("有" if header else "無", color))
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
                template.save_group_order(conn, [g[0] for g in self._groups])
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
            return conn.execute("SELECT * FROM T_Group WHERE group_id = ?", (group_id,)).fetchone()

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
        t = self.currentTemplate()
        if not self._editable():
            return
        dlg = GroupDialog(self.db_path, t["template_id"], parent=self)
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
        t = self.currentTemplate()
        gid = self._groups[row][0]
        dlg = GroupDialog(self.db_path, t["template_id"], existing=self._groupRowData(gid), parent=self)
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
                template.delete_group(conn, gid)
        except Exception as exc:
            reportError("無法刪除", exc, self)
            return
        self._reloadGroupsPreservingOrder()

    def _check(self):
        t = self.currentTemplate()
        if t is None:
            return
        try:
            with opened(self.db_path) as conn:
                template.check_template(conn, t["template_id"])
        except Exception as exc:
            reportError("規則有問題", exc, self)
            return
        msgInfo("檢查完成", "所有群組檢查無誤：代碼沒有衝突，輪番群組都有人上班。", self)

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
        gid, name, mode, expr, _header = group
        with opened(self.db_path) as conn:
            slots = template.slot_rows(conn, gid)
        try:
            codes = template.expand_codes(mode, expr)
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
            tile.setFixedHeight(TILE_H)
            self.tiles_grid.addWidget(tile, i // SLOTS_PER_ROW, i % SLOTS_PER_ROW)
            self.slotTiles.append(tile)
            self._slot_seqs.append(s["seq"])
        for col in range(SLOTS_PER_ROW):
            self.tiles_grid.setColumnStretch(col, 1)
        rows = min(-(-len(slots) // SLOTS_PER_ROW), MAX_VISIBLE_TILE_ROWS)
        self.tiles_scroll.setFixedHeight(rows * TILE_H + max(rows - 1, 0) * TILE_SPACING)
        self.slots_card.setTitle(f"{name} 勤休設定")
        self.chk_from_one.setVisible(mode == MODE_ROTATE)   # 由 1 起算只作用在輪番類型
        # 圖例只列該群組實際會出現的狀態：輪番三種、固定番沒有輪休、空白欄都沒有
        self._showLegend(
            ("work", "rest", "override") if mode == MODE_ROTATE
            else () if mode == MODE_BLANK else ("work", "override"))
        # 不顯示「共 N 格」：群組表的範圍欄已看得出格數，標題列留給群組名稱
        if not editable or mode == MODE_BLANK:
            hint = ""
        elif mode == MODE_ROTATE:
            hint = "點一下切換輪休，雙擊可自訂代碼"
        else:
            hint = "固定番無輪休設定，雙擊可自訂代碼"
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
                template.toggle_rest(conn, group[0], seq)
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
        codes = template.expand_codes(group[2], group[3])
        with opened(self.db_path) as conn:
            current = template.slot_rows(conn, group[0])[seq - 1]["code_override"] or codes[seq - 1]
        code, ok = askText(
            self, "自訂代碼", f"第 {seq} 格代碼（預設 {codes[seq - 1]}，清空即回復預設）：", current)
        if ok:
            try:
                with opened(self.db_path) as conn:
                    template.set_code_override(conn, group[0], seq, code)
            except Exception as exc:
                reportError("無法修改", exc, self)
        self._renderSlots()
