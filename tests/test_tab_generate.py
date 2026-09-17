# -*- coding: utf-8 -*-
"""產生月表分頁與配對彈窗（離線 Qt，暫存資料庫）。⚠️ 姓名一律虛構。"""
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

import main
from lib import plan
from lib.db_utils import opened
from tabs import tab_generate
from tabs.tab_generate import TabGenerate, defaultYearMonth
from ui_utils import pairing_dialog
from ui_utils.pairing_dialog import PairingDialog

_app = QApplication.instance() or QApplication([])
TODAY = date(2026, 9, 16)


class _TempDb(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        main.prepare_database(self.db)

    def tearDown(self):
        os.remove(self.db)

    def full_seeds(self):
        """在職名單照順序從第一個群組第 1 格一路配滿（種子人數剛好等於格數）。"""
        with opened(self.db) as conn:
            tpl = conn.execute("SELECT template_id FROM Rota_Template").fetchone()[0]
            queue = [row["member_id"] for row in plan.active_members(conn)]
            seeds = {}
            for row, group in plan.pairable_groups(conn, tpl):
                seeds[row["group_id"]] = {queue.pop(0): seq
                                          for seq in range(1, group.cycle_len + 1)}
            return tpl, seeds

    def has_plan(self, year, month):
        with opened(self.db) as conn:
            return plan.get_plan(conn, year, month) is not None


class TestDefaults(unittest.TestCase):
    def test_default_is_next_month(self):
        self.assertEqual(defaultYearMonth(date(2026, 9, 16)), (2026, 10))

    def test_december_rolls_into_next_year(self):
        self.assertEqual(defaultYearMonth(date(2026, 12, 1)), (2027, 1))


class TestTabGenerate(_TempDb):
    def setUp(self):
        super().setUp()
        self.tab = TabGenerate(self.db, today=TODAY)
        self.addCleanup(self.tab.deleteLater)

    def test_year_is_shown_in_roc(self):
        self.assertEqual(self.tab.cmb_year.currentText(), "115")
        self.assertEqual(self.tab.yearMonth(), (2026, 10))

    def test_empty_month_says_not_generated(self):
        self.assertEqual(self.tab.lbl_status.text(), "尚未產生")
        self.assertFalse(self.tab.preview.hasSheet())

    def test_chain_without_previous_month_warns_and_creates_nothing(self):
        with mock.patch.object(tab_generate, "msgWarning") as warn:
            self.tab._chain()
        warn.assert_called_once()
        self.assertIn("115 年 9 月", warn.call_args[0][1])
        self.assertFalse(self.has_plan(2026, 10))

    def test_custom_creates_the_month_and_shows_the_preview(self):
        tpl, seeds = self.full_seeds()
        fake = mock.MagicMock(template_id=tpl, seeds=seeds)
        fake.exec.return_value = True
        with mock.patch.object(tab_generate, "PairingDialog", return_value=fake):
            self.tab._custom()
        self.assertTrue(self.has_plan(2026, 10))
        self.assertTrue(self.tab.preview.hasSheet())
        self.assertIn("自訂起始", self.tab.lbl_status.text())
        with opened(self.db) as conn:
            self.assertEqual(plan.get_plan(conn, 2026, 10)["origin"], plan.ORIGIN_CUSTOM)

    def test_chain_after_custom(self):
        tpl, seeds = self.full_seeds()
        with opened(self.db) as conn:
            plan.create_plan(conn, 2026, 10, tpl, seeds)
        self.tab.cmb_month.setCurrentIndex(10)       # 11 月
        self.tab._chain()
        self.assertTrue(self.has_plan(2026, 11))

    # ── 已產生的月份：軟擋（維護者裁示），確認後覆蓋 ──
    def _make_october(self):
        tpl, seeds = self.full_seeds()
        with opened(self.db) as conn:
            plan.create_plan(conn, 2026, 10, tpl, seeds)
        return tpl, seeds

    def test_cancelling_the_overwrite_changes_nothing(self):
        self._make_october()
        with mock.patch.object(tab_generate, "confirmBox", return_value=False) as ask, \
             mock.patch.object(tab_generate, "PairingDialog") as dlg:
            self.tab._custom()
        ask.assert_called_once()
        dlg.assert_not_called()

    def test_custom_overwrite_opens_the_dialog_with_the_existing_pairing(self):
        tpl, seeds = self._make_october()
        fake = mock.MagicMock(template_id=tpl, seeds=seeds)
        fake.exec.return_value = True
        with mock.patch.object(tab_generate, "confirmBox", return_value=True), \
             mock.patch.object(tab_generate, "PairingDialog", return_value=fake) as dlg:
            self.tab._custom()
        self.assertTrue(dlg.call_args.kwargs["edit_existing"])
        with opened(self.db) as conn:
            self.assertEqual(len(plan.list_plans(conn)), 1)

    def test_chain_overwrite_after_confirm(self):
        tpl, seeds = self._make_october()
        with opened(self.db) as conn:
            plan.create_plan(conn, 2026, 11, tpl, seeds)       # 11 月先自訂一份
        self.tab.cmb_month.setCurrentIndex(10)
        with mock.patch.object(tab_generate, "confirmBox", return_value=True):
            self.tab._chain()
        with opened(self.db) as conn:
            self.assertEqual(plan.get_plan(conn, 2026, 11)["origin"], plan.ORIGIN_CHAIN)

    def test_past_month_confirmation_mentions_it(self):
        self._make_october()
        tab = TabGenerate(self.db, today=date(2026, 11, 5))
        self.addCleanup(tab.deleteLater)
        tab.cmb_month.setCurrentIndex(9)                      # 10 月已經過去
        with mock.patch.object(tab_generate, "confirmBox", return_value=False) as ask:
            tab._custom()
        self.assertIn("此為歷史勤休表", ask.call_args.kwargs["informative"])

    def test_current_month_confirmation_has_no_past_note(self):
        self._make_october()
        with mock.patch.object(tab_generate, "confirmBox", return_value=False) as ask:
            self.tab._custom()
        self.assertNotIn("歷史勤休表", ask.call_args.kwargs["informative"])

    # ── 刪除 ──
    def test_delete_asks_then_removes(self):
        self._make_october()
        with mock.patch.object(tab_generate, "confirmBox", return_value=False):
            self.tab._delete()
        self.assertTrue(self.has_plan(2026, 10))
        with mock.patch.object(tab_generate, "confirmBox", return_value=True):
            self.tab._delete()
        self.assertFalse(self.has_plan(2026, 10))
        self.assertFalse(self.tab.preview.hasSheet())

    def test_delete_without_a_plan_warns(self):
        with mock.patch.object(tab_generate, "msgWarning") as warn, \
             mock.patch.object(tab_generate, "confirmBox") as ask:
            self.tab._delete()
        warn.assert_called_once()
        ask.assert_not_called()

    # ── 匯出 ──
    def test_export_file_names_use_roc_year(self):
        self.assertEqual(tab_generate.exportFileNames(2026, 10),
                         ("115年10月輪番表.xlsx", "115年10月輪番表.pdf"))

    def _to_desktop(self, folder, choice=0):
        """匯出目的地：假桌面＝folder，確認框選 choice（0 匯出／1 另存／None 取消）。"""
        stack = mock.patch.multiple(tab_generate, desktopFolder=mock.DEFAULT,
                                    choiceBox=mock.DEFAULT)
        patched = stack.start()
        self.addCleanup(stack.stop)
        patched["desktopFolder"].return_value = folder
        patched["choiceBox"].return_value = choice
        return patched

    def test_export_writes_both_files_to_the_desktop_by_default(self):
        self._make_october()
        folder = tempfile.mkdtemp()
        self._to_desktop(folder)
        with mock.patch.object(tab_generate, "msgInfo"),              mock.patch.object(tab_generate, "QFileDialog") as picker:
            self.tab._export()
        picker.getExistingDirectory.assert_not_called()
        self.assertEqual(sorted(os.listdir(folder)),
                         ["115年10月輪番表.pdf", "115年10月輪番表.xlsx"])

    def test_export_save_as_uses_the_picked_folder_only_once(self):
        self._make_october()
        desktop, other = tempfile.mkdtemp(), tempfile.mkdtemp()
        patched = self._to_desktop(desktop, choice=1)
        with mock.patch.object(tab_generate, "msgInfo"),              mock.patch.object(tab_generate.QFileDialog, "getExistingDirectory",
                               return_value=other):
            self.tab._export()
        self.assertEqual(len(os.listdir(other)), 2)
        self.assertEqual(os.listdir(desktop), [])
        # 下一次仍預設桌面：沒有記住另存的資料夾
        patched["choiceBox"].return_value = 0
        with mock.patch.object(tab_generate, "msgInfo"),              mock.patch.object(tab_generate, "confirmBox", return_value=True):
            self.tab._export()
        self.assertEqual(len(os.listdir(desktop)), 2)

    def test_export_cancel_writes_nothing(self):
        self._make_october()
        folder = tempfile.mkdtemp()
        self._to_desktop(folder, choice=None)
        with mock.patch.object(tab_generate, "msgInfo") as done,              mock.patch.object(tab_generate, "QFileDialog") as picker:
            self.tab._export()
        picker.getExistingDirectory.assert_not_called()
        done.assert_not_called()
        self.assertEqual(os.listdir(folder), [])

    def test_export_asks_before_overwriting_existing_files(self):
        self._make_october()
        folder = tempfile.mkdtemp()
        self._to_desktop(folder)
        open(os.path.join(folder, "115年10月輪番表.xlsx"), "w").close()
        with mock.patch.object(tab_generate, "confirmBox", return_value=False) as ask,              mock.patch.object(tab_generate, "msgInfo") as done:
            self.tab._export()
        ask.assert_called_once()
        done.assert_not_called()
        self.assertEqual(os.path.getsize(os.path.join(folder, "115年10月輪番表.xlsx")), 0)

    def test_export_locked_file_gives_a_plain_message(self):
        """Excel 開著同名檔時 Windows 不讓覆寫：給看得懂的提示，不丟英文原文。"""
        self._make_october()
        self._to_desktop(tempfile.mkdtemp())
        with mock.patch.object(tab_generate.xlsx_writer, "write_sheet",
                               side_effect=PermissionError("locked")),              mock.patch.object(tab_generate, "msgWarning") as warn:
            self.tab._export()
        message = warn.call_args[0][1]
        self.assertIn("請關閉", message)
        self.assertNotIn("locked", message)
        self.assertNotIn("PermissionError", message)

    def test_export_without_a_plan_warns(self):
        with mock.patch.object(tab_generate, "msgWarning") as warn, \
             mock.patch.object(tab_generate, "QFileDialog") as picker:
            self.tab._export()
        warn.assert_called_once()
        picker.getExistingDirectory.assert_not_called()

    def _wheel(self, widget, notches):
        vp = widget.viewport()
        pos = QPointF(vp.width() / 2, vp.height() / 2)
        event = QWheelEvent(pos, vp.mapToGlobal(pos), QPoint(0, 0), QPoint(0, 120 * notches),
                            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(vp, event)

    def test_preview_zooms_with_the_wheel_within_limits(self):
        """預設左右填滿（上下出捲軸）；滾輪最小到完整塞進、最大到底圖原始解析度。"""
        tpl, seeds = self.full_seeds()
        with opened(self.db) as conn:
            plan.create_plan(conn, 2026, 10, tpl, seeds)
        self.tab.resize(1400, 760)
        self.tab.show()
        self.tab.refresh()
        _app.processEvents()
        preview = self.tab.preview
        self.assertAlmostEqual(preview.zoom(), preview.widthZoom())
        self.assertFalse(preview.horizontalScrollBar().isVisible(), "左右填滿不得出橫向捲軸")
        self.assertTrue(preview.verticalScrollBar().isVisible())
        start = preview.zoom()
        self._wheel(preview, 3)
        self.assertGreater(preview.zoom(), start)
        self._wheel(preview, 50)
        self.assertAlmostEqual(preview.zoom(), preview.maxZoom())
        self._wheel(preview, -80)
        self.assertEqual(preview.zoom(), 1.0)            # 1.0＝整張完整塞進

    def test_dragging_pans_only_when_zoomed(self):
        from PySide6.QtTest import QTest
        tpl, seeds = self.full_seeds()
        with opened(self.db) as conn:
            plan.create_plan(conn, 2026, 10, tpl, seeds)
        self.tab.resize(1400, 760)
        self.tab.show()
        self.tab.refresh()
        _app.processEvents()
        preview = self.tab.preview
        preview.setZoom(1.0)
        _app.processEvents()
        self.assertFalse(preview.canPan())          # 完整塞進時沒東西可拖
        preview.setZoom(2.0)
        _app.processEvents()
        self.assertTrue(preview.canPan())
        bar = preview.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        before = bar.value()
        vp = preview.viewport()
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(300, 300))
        QTest.mouseMove(vp, QPoint(300, 250))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(300, 250))
        self.assertGreater(bar.value(), before)     # 往上拖，畫面跟著往上＝捲軸往下

    def test_changing_month_resets_the_zoom(self):
        tpl, seeds = self.full_seeds()
        with opened(self.db) as conn:
            plan.create_plan(conn, 2026, 10, tpl, seeds)
        self.tab.resize(1400, 760)
        self.tab.show()
        self.tab.refresh()
        _app.processEvents()
        self._wheel(self.tab.preview, 3)
        self.tab.cmb_month.setCurrentIndex(10)           # 切到 11 月（沒有月表）
        self.tab.cmb_month.setCurrentIndex(9)            # 切回 10 月
        _app.processEvents()
        self.assertAlmostEqual(self.tab.preview.zoom(), self.tab.preview.widthZoom())

    def test_wheel_does_not_change_the_month(self):
        """⚠️ 游標停在年月下拉上捲動，不得靜默改掉月份。"""
        before = self.tab.cmb_month.currentIndex()
        event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120),
                            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(self.tab.cmb_month, event)
        self.assertEqual(self.tab.cmb_month.currentIndex(), before)


class TestPairingDialog(_TempDb):
    def setUp(self):
        super().setUp()
        self.dlg = PairingDialog(self.db, 2026, 10)
        self.addCleanup(self.dlg.deleteLater)

    def fill_all(self):
        _tpl, seeds = self.full_seeds()
        self.dlg._setAssignments(seeds)

    def test_editing_an_existing_month_prefills_its_pairing(self):
        tpl, seeds = self.full_seeds()
        with opened(self.db) as conn:
            plan.create_plan(conn, 2026, 10, tpl, seeds)
        dlg = PairingDialog(self.db, 2026, 10, edit_existing=True)
        self.addCleanup(dlg.deleteLater)
        self.assertEqual(sum(mid is not None for mid in dlg._assign), 34)
        dlg._submit()
        self.assertEqual(dlg.seeds, seeds)

    def test_rows_cover_every_pairable_slot(self):
        self.assertEqual(len(self.dlg._rows), 34)     # 20 + 8 + 6，空白欄不配人
        self.assertEqual(self.dlg.styleSheet(), "", "彈窗不得自帶 stylesheet（QSS-8）")

    def test_picking_an_assigned_person_clears_the_other_slot(self):
        self.fill_all()
        moved = self.dlg._assign[4]
        combo = self.dlg._combos[0]
        combo.setCurrentIndex(combo.findData(moved))
        self.assertEqual(self.dlg._assign[0], moved)
        self.assertIsNone(self.dlg._assign[4])
        self.assertIn(4, self.dlg._flash_rows)

    def test_incomplete_pairing_is_not_accepted(self):
        with mock.patch.object(pairing_dialog, "msgWarning") as warn:
            self.dlg._submit()
        warn.assert_called_once()
        self.assertEqual(self.dlg.result(), 0)
        self.assertEqual(len(self.dlg._missing_rows), 34)

    def test_complete_pairing_returns_seeds(self):
        self.fill_all()
        self.dlg._submit()
        self.assertEqual(self.dlg.result(), 1)
        self.assertEqual(sum(len(m) for m in self.dlg.seeds.values()), 34)

    def test_clear_all_clears_without_asking(self):
        self.fill_all()
        with mock.patch.object(pairing_dialog, "confirmBox") as ask:
            self.dlg._clearAll()
        ask.assert_not_called()
        self.assertFalse(self.dlg._hasAssignment())

    # ── 可打字：只有確實選中才寫進格位（維護者 2026-09-16 裁示的兩條規矩）──
    def _type(self, row, text, finish=True):
        line = self.dlg._combos[row].lineEdit()
        line.setText(text)
        line.textEdited.emit(text)
        if finish:
            line.editingFinished.emit()

    def _name(self, mid):
        return dict(self.dlg._members).get(mid)

    def test_typing_half_a_name_changes_nothing(self):
        """⚠️ 打到一半不得寫入，否則打「李小」就可能把別格的李小華清掉。"""
        self.fill_all()
        before = list(self.dlg._assign)
        self._type(0, "李小", finish=False)
        self.assertEqual(self.dlg._assign, before)
        self._type(0, "李小")                        # 打一半就按 Enter 也不動
        self.assertEqual(self.dlg._assign, before)

    def test_half_typed_cell_blocks_submit(self):
        self.fill_all()
        self._type(0, "李小")
        with mock.patch.object(pairing_dialog, "msgWarning") as warn:
            self.dlg._submit()
        warn.assert_called_once()
        self.assertEqual(self.dlg.result(), 0)
        self.assertIn(0, self.dlg._missing_rows)

    def test_typing_a_full_name_picks_that_person(self):
        self.fill_all()
        target = self.dlg._assign[1]
        self._type(0, self._name(target))
        self.assertEqual(self.dlg._assign[0], target)
        self.assertIsNone(self.dlg._assign[1])       # 原本那格改成未配
        self.assertIn(1, self.dlg._flash_rows)

    def test_clearing_the_text_unassigns_the_cell(self):
        self.fill_all()
        self._type(0, "")
        self.assertIsNone(self.dlg._assign[0])

    # ── 右側名單：全部列出、已配變灰；點人名帶入目前那一格 ──
    def test_roster_keeps_assigned_people(self):
        self.fill_all()
        self.assertEqual(self.dlg.lst_roster.count(), len(self.dlg._members))
        first = self.dlg.lst_roster.item(0)
        name = self._name(first.data(Qt.UserRole))
        self.assertNotEqual(first.text(), name, "已配的人要有配對標示")

    def test_clicking_a_name_fills_the_active_cell(self):
        self.dlg._setActiveRow(4)
        item = self.dlg.lst_roster.item(10)
        self.dlg._onRosterClicked(item)
        self.assertEqual(self.dlg._assign[4], item.data(Qt.UserRole))

    def test_clicking_an_assigned_name_moves_that_person(self):
        self.fill_all()
        self.dlg._setActiveRow(4)
        moved = self.dlg._assign[1]
        row = [self.dlg.lst_roster.item(i).data(Qt.UserRole)
               for i in range(self.dlg.lst_roster.count())].index(moved)
        self.dlg._onRosterClicked(self.dlg.lst_roster.item(row))
        self.assertEqual(self.dlg._assign[4], moved)
        self.assertIsNone(self.dlg._assign[1])

    def test_clicking_a_name_scrolls_back_to_the_active_cell(self):
        """點完格位又捲走，點人名時畫面要拉回那一格。"""
        with mock.patch.object(self.dlg.tbl, "scrollToItem") as scroll:
            self.dlg._setActiveRow(30)
            self.dlg._onRosterClicked(self.dlg.lst_roster.item(0))
        scroll.assert_called_once()
        self.assertEqual(scroll.call_args[0][0].row(), 30)

    def test_clicking_a_name_keeps_the_roster_scroll_position(self):
        """⚠️ 點完名單下方的人名，名單不得跳回最上面。"""
        self.dlg.resize(1100, 500)
        self.dlg.show()
        _app.processEvents()
        bar = self.dlg.lst_roster.verticalScrollBar()
        bar.setValue(bar.maximum())
        position = bar.value()
        self.dlg._setActiveRow(0)
        self.dlg._onRosterClicked(self.dlg.lst_roster.item(self.dlg.lst_roster.count() - 1))
        _app.processEvents()
        self.assertEqual(bar.value(), position)

    def test_clicking_a_name_without_an_active_cell_changes_nothing(self):
        self.dlg._onRosterClicked(self.dlg.lst_roster.item(0))
        self.assertFalse(self.dlg._hasAssignment())
        self.assertIn("請先點選左側", self.dlg.lbl_people.text())


if __name__ == "__main__":
    unittest.main()
