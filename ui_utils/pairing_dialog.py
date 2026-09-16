"""
pairing_dialog.py — 配對彈窗（產生月表「自訂起始」）

規格見 DEVELOPER §4「配對彈窗的內容」：

  上方  模板下拉（換模板＝配對清空重來，先確認）
  左側  配對表：一列一格位（群組／格位／代碼／人員），人員欄是**唯讀下拉**
  右側  名單：列出全部在職人員，已配的變灰並標在哪一格；**點人名＝帶進左側目前那一格**
        （目前那一格＝最後點過或正在打字的人員欄，淡藍底標示）
  下方  接續上月填入／全部清空　　取消／確定

人員欄是**可打字篩選下拉**，用公版 `widgets.makeFilterCombo`（維護者 2026-09-16 裁示，
原規格禁止可打字；PoliceDocSys 補強後六個彈窗已在用）。本彈窗多了「選人會清空別格」的
連動，所以另加兩條規矩：

  1. **只有確實選中名字才寫進格位**（點候選、點下拉項目，或完整打出姓名後按 Enter／
     離開欄位）。打字過程中資料完全不動——否則打到一半就把別人的格位清掉。
     清空欄位文字後按 Enter／離開＝把這格改成未配。
  2. **確定前整張表檢查**：打了字卻沒選中的格標紅、不准送出（`checkFilterCombos`）。

⚠️ 下拉不吃滾輪：捲表格時游標一定會滑過下拉，吃了滾輪就是靜默換人。
⚠️ 彈窗不自帶 stylesheet（QSS-8），表格沿用 `sort_table.TABLE_SS` 公版。
⚠️ 「沒配完不准確定」在這裡擋一次，`plan.create_plan` 寫入前還會再擋一次。
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QStyledItemDelegate, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QAbstractItemView,
)

from lib import plan, template
from lib.db_utils import opened
from lib.rota import MODE_ROTATE
from .card import Card, cardHint
from .member_dialog import _add_buttons
from .sort_table import TABLE_SS
from .ui_common import confirmBox, msgInfo, msgWarning, reportError, styleButton
from .widgets import checkFilterCombos, installComboWheelGuard, makeFilterCombo

_GROUP_COL, _SEQ_COL, _CODE_COL, _PERSON_COL = range(4)
_HEADERS = ("群組", "格位", "代碼", "人員")

_COLOR_FLASH = QColor("#fff3cd")     # 被清空的那一格短暫標黃，與「自訂」方塊同色系
_COLOR_MISSING = QColor("#fde8e8")   # 按確定時還沒配的格
_COLOR_ACTIVE = QColor("#e3edf8")    # 目前那一格（點名單會帶進這裡），與提示條同色系
_COLOR_REST_TEXT = QColor("#b42318")
_COLOR_TAKEN_TEXT = QColor("#8e8e93")  # 名單上已配的人
_COLOR_NAME_TEXT = QColor("#1c1c1e")   # 名單上未配的人（公版內文色）
_FLASH_MS = 2000
ROSTER_W = 380
_ROW_H = 44


def rocYear(year):
    return year - 1911


class _BackgroundDelegate(QStyledItemDelegate):
    """先畫格子的底色再畫文字。

    ⚠️ 表格公版 TABLE_SS 有 ``QTableWidget::item`` 規則，套了樣式表之後 Qt 不再畫
    ``setBackground`` 設的底色——資料設進去了、畫面上卻看不到（實測踩過）。
    """

    def paint(self, painter, option, index):
        brush = index.data(Qt.BackgroundRole)
        if brush is not None and brush.color().alpha() > 0:
            painter.fillRect(option.rect, brush)
        super().paint(painter, option, index)


class PairingDialog(QDialog):
    """結果：accept 後讀 ``template_id`` 與 ``seeds``（``{group_id: {member_id: slot_seq}}``）。"""

    def __init__(self, db_path, year, month, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.year, self.month = year, month
        self.template_id = None
        self.seeds = {}
        self._rows = []          # [(group_id, group_name, seq, code, is_rest)]
        self._assign = []        # 與 _rows 對齊：member_id 或 None
        self._combos = []
        self._members = []       # [(member_id, name)]
        self._missing_rows = set()
        self._flash_rows = set()
        self._syncing = False
        self._active_row = None
        self.setWindowTitle(f"設定配對：{rocYear(year)} 年 {month} 月")
        self._build()
        self._loadTemplates()
        self._fitToScreen()
        # 「目前那一格」＝焦點所在的人員欄。⚠️ 不能掛在 lineEdit 的 FocusIn 上：
        # 可打字下拉的焦點實際落在 combo 本身，lineEdit 收不到（實測踩過）。
        QGuiApplication.instance().focusChanged.connect(self._onFocusChanged)
        self.tbl.setFocus()      # ⚠️ 焦點不停在模板下拉上

    # ── 版面 ────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(QLabel("模板："))
        self.cmb_template = QComboBox()
        self.cmb_template.setMinimumWidth(280)
        installComboWheelGuard(self.cmb_template)
        top.addWidget(self.cmb_template)
        top.addStretch()
        root.addLayout(top)

        middle = QHBoxLayout()
        middle.setSpacing(12)
        pair_card = Card("配對")
        tbl = self.tbl = QTableWidget(0, len(_HEADERS))
        tbl.setHorizontalHeaderLabels(_HEADERS)
        tbl.verticalHeader().setVisible(False)
        tbl.verticalHeader().setDefaultSectionSize(_ROW_H)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setSelectionMode(QAbstractItemView.NoSelection)
        tbl.setShowGrid(False)
        tbl.setStyleSheet(TABLE_SS)
        tbl.setItemDelegate(_BackgroundDelegate(tbl))
        hdr = tbl.horizontalHeader()
        for col, width in ((_GROUP_COL, 130), (_SEQ_COL, 80), (_CODE_COL, 130)):
            hdr.setSectionResizeMode(col, QHeaderView.Fixed)
            tbl.setColumnWidth(col, width)
        hdr.setSectionResizeMode(_PERSON_COL, QHeaderView.Stretch)
        pair_card.body.addWidget(tbl)
        middle.addWidget(pair_card, 3)

        roster_card = Card("名單")
        self.lbl_total = cardHint("")
        self.lbl_slots = QLabel("")
        self.lbl_people = QLabel("")
        self.lst_roster = QListWidget()
        self.lst_roster.setSelectionMode(QAbstractItemView.NoSelection)
        # ⚠️ 名單不搶焦點：點人名時焦點留在左側那一格，才知道要帶進哪裡
        self.lst_roster.setFocusPolicy(Qt.NoFocus)
        self.lst_roster.setCursor(Qt.PointingHandCursor)
        self.lst_roster.itemClicked.connect(self._onRosterClicked)
        roster_card.header.addStretch()
        roster_card.header.addWidget(self.lbl_total)
        roster_card.body.addWidget(self.lbl_slots)
        roster_card.body.addWidget(self.lbl_people)
        roster_card.body.addWidget(self.lst_roster, 1)
        # ⚠️ 名單卡片寬度寫死：已配的人會加上「大輪番 第 5 格」，寬度跟著內容伸縮的話，
        # 每配一個人左邊配對表就被擠一下（PoliceDocSys LAY-7：右側候選面板固定寬）。
        # 放不下的長群組名由清單自動以「…」省略。
        roster_card.setFixedWidth(ROSTER_W)
        middle.addWidget(roster_card)
        root.addLayout(middle, 1)

        bottom = QHBoxLayout()
        self.btn_previous = styleButton(QPushButton("接續上月填入"), "normal")
        self.btn_clear = styleButton(QPushButton("全部清空"), "danger")
        for btn in (self.btn_previous, self.btn_clear):
            btn.setAutoDefault(False)
            bottom.addWidget(btn)
        _, self.btn_ok = _add_buttons(self, bottom, confirm_text="確定")
        self.btn_ok.clicked.connect(self._submit)
        root.addLayout(bottom)

        self.cmb_template.currentIndexChanged.connect(self._onTemplateChanged)
        self.btn_previous.clicked.connect(self._fillFromPrevious)
        self.btn_clear.clicked.connect(self._clearAll)

    def _fitToScreen(self):
        want_w, want_h = 1100, 720
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            want_w = min(want_w, avail.width() - 40)
            want_h = min(want_h, avail.height() - 40)
        self.resize(want_w, want_h)

    # ── 模板 ────────────────────────────────────────────────────
    def _loadTemplates(self):
        with opened(self.db_path) as conn:
            templates = template.list_templates(conn)
            self._members = [(r["member_id"], r["name"]) for r in plan.active_members(conn)]
        self.cmb_template.blockSignals(True)
        for row in templates:
            self.cmb_template.addItem(row["name"], row["template_id"])
        self.cmb_template.blockSignals(False)
        self._current_template_index = -1
        if templates:
            self.cmb_template.setCurrentIndex(0)
            self._onTemplateChanged(0)

    def currentTemplateId(self):
        return self.cmb_template.currentData()

    def _hasAssignment(self):
        return any(mid is not None for mid in self._assign)

    def _onTemplateChanged(self, index):
        if index == self._current_template_index:
            return
        if self._hasAssignment() and not confirmBox(
                "更換模板", "更換模板會清空目前的配對，確定要更換嗎？",
                confirm_text="更換", default_confirm=False, parent=self):
            self.cmb_template.blockSignals(True)
            self.cmb_template.setCurrentIndex(self._current_template_index)
            self.cmb_template.blockSignals(False)
            return
        self._current_template_index = index
        self._loadRows()

    def _loadRows(self):
        tid = self.currentTemplateId()
        self._rows = []
        if tid is not None:
            try:
                with opened(self.db_path) as conn:
                    groups = plan.pairable_groups(conn, tid)
            except Exception as exc:
                reportError("無法載入模板", exc, self)
                groups = []
            for row, group in groups:
                for slot in group.slots:
                    self._rows.append((row["group_id"], row["name"], slot.seq,
                                       slot.code, slot.is_rest and group.mode == MODE_ROTATE))
        self._assign = [None] * len(self._rows)
        self._missing_rows.clear()
        self._buildTable()

    def _buildTable(self):
        tbl = self.tbl
        tbl.setRowCount(0)
        self._combos = []
        self._active_row = None
        tbl.setRowCount(len(self._rows))
        previous_group = None
        for r, (gid, gname, seq, code, is_rest) in enumerate(self._rows):
            first = gid != previous_group
            previous_group = gid
            tbl.setItem(r, _GROUP_COL, self._item(gname if first else ""))
            tbl.setItem(r, _SEQ_COL, self._item(seq))
            code_item = self._item(f"{code}（輪休）" if is_rest else code)
            if is_rest:
                code_item.setForeground(_COLOR_REST_TEXT)
            tbl.setItem(r, _CODE_COL, code_item)
            combo = makeFilterCombo(self._members)
            installComboWheelGuard(combo, forward_to=tbl.viewport())
            # 規矩 1：currentIndexChanged 只在「選中」時觸發——公版打字時會 blockSignals 重建清單
            combo.currentIndexChanged.connect(lambda _i, row=r: self._onPicked(row))
            combo.lineEdit().editingFinished.connect(lambda row=r: self._onEditingFinished(row))
            tbl.setCellWidget(r, _PERSON_COL, combo)
            self._combos.append(combo)
        self._refresh()

    @staticmethod
    def _item(text):
        it = QTableWidgetItem(str(text))
        it.setTextAlignment(Qt.AlignCenter)
        return it

    # ── 配對 ────────────────────────────────────────────────────
    def _slotLabel(self, row):
        _gid, gname, seq, _code, _rest = self._rows[row]
        return f"{gname} 第 {seq} 格"

    def _onPicked(self, row):
        if self._syncing:
            return
        self._commit(row, self._combos[row].currentData())

    def _onEditingFinished(self, row):
        """Enter／離開欄位：完整打出姓名就選中；清空就改成未配；打一半的不動資料。"""
        if self._syncing:
            return
        combo = self._combos[row]
        text = combo.currentText().strip()
        if not text:
            if self._assign[row] is not None:
                self._commit(row, None)
            return
        match = [mid for mid, name in self._members if name == text]
        if match and match[0] != self._assign[row]:
            self._commit(row, match[0])

    def _commit(self, row, mid):
        changed = {row}
        if mid is not None:
            for other, assigned in enumerate(self._assign):
                if other != row and assigned == mid:
                    # 選到已配過的人：原本那格改成未配，不跳確認，短暫標黃讓視線跟得上
                    self._assign[other] = None
                    self._flash(other)
                    changed.add(other)
        self._assign[row] = mid
        self._missing_rows.discard(row)
        self._refresh(changed)

    def _flash(self, row):
        self._flash_rows.add(row)
        QTimer.singleShot(_FLASH_MS, lambda r=row: self._endFlash(r))

    def _endFlash(self, row):
        self._flash_rows.discard(row)
        self._paintRow(row)

    def _setAssignments(self, seeds):
        """把 {group_id: {member_id: seq}} 套進畫面（先全部清空）。"""
        index = {(gid, seq): r for r, (gid, _n, seq, _c, _rest) in enumerate(self._rows)}
        valid = {mid for mid, _name in self._members}
        self._assign = [None] * len(self._rows)
        for gid, members in seeds.items():
            for mid, seq in members.items():
                r = index.get((gid, seq))
                if r is not None and mid in valid:
                    self._assign[r] = mid
        self._missing_rows.clear()
        self._refresh()

    def _setComboValue(self, combo, mid):
        """把下拉顯示成指定的人（None＝空白），不觸發 _onPicked。"""
        self._syncing = True
        try:
            combo.blockSignals(True)
            if combo.findData(mid) < 0 or combo.count() != len(self._members) + 1:
                # 打字篩選過的清單不完整，先還原成全部名單
                combo.clear()
                combo.addItem("", None)
                for member_id, name in self._members:
                    combo.addItem(name, member_id)
            combo.setCurrentIndex(max(combo.findData(mid), 0))
            if mid is None:
                combo.setEditText("")
            combo.blockSignals(False)
        finally:
            self._syncing = False

    def _refresh(self, rows=None):
        """依 _assign 更新下拉顯示、底色與右側名單。rows=None 表示全部列。

        ⚠️ 只同步有變動的列：其他列可能正打字打到一半，整表重設會把字吃掉。
        """
        targets = range(len(self._combos)) if rows is None else rows
        for r in targets:
            self._setComboValue(self._combos[r], self._assign[r])
            self._paintRow(r)
        owner = {mid: r for r, mid in enumerate(self._assign) if mid is not None}
        self._refreshRoster(owner)

    def _onFocusChanged(self, _old, new):
        for r, combo in enumerate(self._combos):
            if new is combo or new is combo.lineEdit():
                self._setActiveRow(r)
                return

    def _setActiveRow(self, row):
        previous, self._active_row = self._active_row, row
        for r in {previous, row} - {None}:
            self._paintRow(r)

    def _onRosterClicked(self, item):
        """點名單上的人名＝帶進左側目前那一格（已配在別格的人會從原格移過來）。"""
        row = self._active_row
        if row is None or not 0 <= row < len(self._combos):
            self.lbl_people.setText("請先點選左側要填入的格位")
            return
        self._commit(row, item.data(Qt.UserRole))
        # 使用者可能點完格位又把表格捲走了：把畫面拉回剛填入的那一格，讓他看到填到哪裡。
        # 格位本來就在畫面內時 EnsureVisible 不會捲動，不會跳來跳去。
        self.tbl.scrollToItem(self.tbl.item(row, _SEQ_COL), QAbstractItemView.EnsureVisible)
        self._combos[row].lineEdit().setFocus()

    def _paintRow(self, row):
        if row in self._missing_rows:
            color = _COLOR_MISSING
        elif row in self._flash_rows:
            color = _COLOR_FLASH
        elif row == self._active_row:
            color = _COLOR_ACTIVE
        else:
            color = None
        for col in (_GROUP_COL, _SEQ_COL, _CODE_COL):
            item = self.tbl.item(row, col)
            if item is not None:
                item.setBackground(color if color is not None else QColor(0, 0, 0, 0))

    def _refreshRoster(self, owner):
        empty = sum(1 for mid in self._assign if mid is None)
        left = sum(1 for mid, _name in self._members if mid not in owner)
        self.lbl_total.setText(f"在職 {len(self._members)} 人")
        self.lbl_slots.setText(f"共 {len(self._rows)} 格，尚有 {empty} 格未配")
        self.lbl_people.setText(f"尚有 {left} 人未配；點人名帶入左側格位" if left
                                else "所有人都已配對")
        # 全部人都列出來，不因為配了就消失；已配的變灰並標在哪一格。
        # ⚠️ 就地更新文字與顏色，不要 clear() 重建——重建會把名單捲回最上面，
        # 使用者點完名單下方的人名，清單就跳走了（維護者回報）。
        if self.lst_roster.count() != len(self._members):
            self.lst_roster.clear()
            for mid, _name in self._members:
                item = QListWidgetItem()
                item.setData(Qt.UserRole, mid)
                self.lst_roster.addItem(item)
        for i, (mid, name) in enumerate(self._members):
            item = self.lst_roster.item(i)
            where = owner.get(mid)
            item.setText(name if where is None else f"{name}　{self._slotLabel(where)}")
            item.setForeground(_COLOR_TAKEN_TEXT if where is not None else _COLOR_NAME_TEXT)

    # ── 填入按鈕 ────────────────────────────────────────────────
    def _confirmOverwrite(self, title):
        if not self._hasAssignment():
            return True
        return confirmBox(title, "會覆蓋目前的配對，確定要繼續嗎？",
                          confirm_text="繼續", default_confirm=False, parent=self)

    def _fillFromPrevious(self):
        tid = self.currentTemplateId()
        if tid is None or not self._confirmOverwrite("接續上月填入"):
            return
        try:
            with opened(self.db_path) as conn:
                seeds, skipped = plan.prefill_from_previous(conn, self.year, self.month, tid)
        except Exception as exc:
            reportError("無法接續上月", exc, self)
            return
        self._setAssignments(seeds)
        if skipped:
            msgInfo("部分群組未填入",
                    "以下群組與上月的格位或輪休不同，無法沿用上月站位，請自行配對：\n"
                    + "、".join(skipped), self)

    def _clearAll(self):
        """直接清空，不跳確認（維護者裁示：清錯了重填即可，還沒寫進資料庫）。"""
        self._setAssignments({})

    # ── 確定 ────────────────────────────────────────────────────
    def missingRows(self):
        return [r for r, mid in enumerate(self._assign) if mid is None]

    def _submit(self):
        if self.currentTemplateId() is None:
            msgWarning("無法確定", "目前沒有任何輪番模板，請先到「輪番設定」新增。", self)
            return
        if not self._rows:
            msgWarning("無法確定", "這份模板沒有需要配對的群組。", self)
            return
        # 規矩 2：打了字卻沒選中清單項目的格（完整打對姓名的會在這裡替他選中）
        pending = checkFilterCombos(
            [(str(r), combo) for r, combo in enumerate(self._combos)])
        if pending:
            rows = sorted(int(label) for label in pending)
            self._missing_rows = set(rows)
            for r in range(len(self._rows)):
                self._paintRow(r)
            self.tbl.scrollToItem(self.tbl.item(rows[0], _SEQ_COL))
            shown = "、".join(self._slotLabel(r) for r in rows[:5])
            more = f" 等 {len(rows)} 格" if len(rows) > 5 else ""
            msgWarning("姓名不在名單中",
                       f"以下格位輸入的姓名沒有選中名單裡的人，請重新選取：{shown}{more}", self)
            return
        missing = self.missingRows()
        if missing:
            self._missing_rows = set(missing)
            for r in range(len(self._rows)):
                self._paintRow(r)
            self.tbl.scrollToItem(self.tbl.item(missing[0], _SEQ_COL))
            shown = "、".join(self._slotLabel(r) for r in missing[:5])
            more = f" 等 {len(missing)} 格" if len(missing) > 5 else ""
            msgWarning("尚未配對完成", f"還有格位沒有配人：{shown}{more}", self)
            return
        seeds = {}
        for (gid, _name, seq, _code, _rest), mid in zip(self._rows, self._assign):
            seeds.setdefault(gid, {})[mid] = seq
        self.template_id = self.currentTemplateId()
        self.seeds = seeds
        self.accept()
