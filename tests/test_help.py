# -*- coding: utf-8 -*-
"""程式內使用指引：內容索引、視窗結構與主視窗接線。"""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

import main
from ui_utils.help_content import (
    HELP_HTML,
    HELP_PAGES,
    HELP_TITLES,
    QUICKSTART_PAGES,
    render_help_html,
)
from ui_utils.help_dialog import HelpDialog, attachHelpButton

_app = QApplication.instance() or QApplication([])


class TestHelpContent(unittest.TestCase):
    def test_four_pages_have_stable_titles_and_nonempty_content(self):
        expected = {
            0: "產生月表",
            1: "輪番設定",
            2: "人員設定",
            3: "功能維護",
        }
        self.assertEqual(HELP_TITLES, expected)
        self.assertEqual(set(HELP_PAGES), set(expected))
        self.assertEqual(set(HELP_HTML), set(expected))
        for page_index in expected:
            with self.subTest(page_index=page_index):
                self.assertTrue(HELP_PAGES[page_index])
                self.assertTrue(HELP_HTML[page_index].strip())
                self.assertEqual(render_help_html(page_index), HELP_HTML[page_index])

    def test_quickstart_has_two_pages_of_complete_workflow_cards(self):
        self.assertEqual(len(QUICKSTART_PAGES), 2)
        for page in QUICKSTART_PAGES:
            with self.subTest(page=page.get("title")):
                self.assertTrue(page["title"].strip())
                self.assertTrue(page["cards"])
                for card in page["cards"]:
                    self.assertTrue(card["title"].strip())
                    self.assertTrue(card["purpose"].strip())
                    self.assertTrue(card["steps"])
                    self.assertTrue(all(step.strip() for step in card["steps"]))
                    self.assertTrue(card["tip"].strip())


class TestHelpDialog(unittest.TestCase):
    def test_each_page_builds_with_title_content_and_no_dialog_stylesheet(self):
        for page_index, title in HELP_TITLES.items():
            with self.subTest(page_index=page_index):
                dialog = HelpDialog(page_index)
                self.addCleanup(dialog.deleteLater)
                self.assertIn(title, dialog.windowTitle())
                self.assertFalse(dialog.browser.toPlainText().strip() == "")
                self.assertEqual(dialog.styleSheet(), "")
                self.assertIs(dialog.focusWidget(), dialog.close_button)

    def test_corner_button_uses_current_page_when_clicked(self):
        tabs = QTabWidget()
        window = QWidget()
        self.addCleanup(tabs.deleteLater)
        self.addCleanup(window.deleteLater)
        for _ in range(4):
            tabs.addTab(QWidget(), "分頁")

        with mock.patch("ui_utils.help_dialog.showHelpDialog") as show:
            button = attachHelpButton(tabs, window)
            holder = tabs.cornerWidget(Qt.TopRightCorner)
            self.assertIs(button.parent(), holder)
            # 外觀走公版 QPushButton#helpButton，元件不自帶 stylesheet
            self.assertEqual(button.styleSheet(), "")
            self.assertEqual(button.objectName(), "helpButton")
            # 高度跟著分頁列，才會與分頁對齊
            self.assertEqual(button.height(), tabs.tabBar().sizeHint().height())
            for page_index in range(4):
                tabs.setCurrentIndex(page_index)
                button.click()
                self.assertEqual(show.call_args.args, (page_index, window))


class TestMainWindowHelp(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        main.prepare_database(self.db_path)
        self.window = main.MainWindow(self.db_path)

    def tearDown(self):
        self.window.deleteLater()
        os.remove(self.db_path)

    def test_main_window_help_button_tracks_all_four_tabs(self):
        from PySide6.QtWidgets import QPushButton
        holder = self.window.tabs.cornerWidget(Qt.TopRightCorner)
        self.assertIsNotNone(holder)
        button = holder.findChild(QPushButton)
        self.assertIsNotNone(button)
        with mock.patch("ui_utils.help_dialog.showHelpDialog") as show:
            for page_index in range(4):
                self.window.tabs.setCurrentIndex(page_index)
                button.click()
                self.assertEqual(show.call_args.args, (page_index, self.window))


if __name__ == "__main__":
    unittest.main()
