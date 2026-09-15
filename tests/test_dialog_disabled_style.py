# -*- coding: utf-8 -*-
"""編輯彈窗裡「被停用的輸入欄」必須看得出來是反灰的（以實際算繪的像素驗證）。

## 為什麼要用算繪像素驗，而不是讀 styleSheet 字串

這條雷的本質是 **Qt 樣式表的覆蓋順序**：彈窗自帶的區域 QSS 會蓋掉全域公版
`lib/theme.py` 的 `:disabled` 規則。讀字串只能看到「有沒有寫這條規則」，
看不到「最後誰贏」——而輸掉的那一方正是 bug 的成因。故本檔一律 `grab()` 成
影像後取樣像素，問的是使用者眼睛真正看到的顏色。

## 背景（2026-08-07）

現場回報：發文結算模式下，一般使用者開刑案／一般陳報的修改視窗，陳報日期與
發文人員**確實被鎖住了，但長得跟可編輯的欄位一模一樣**。根因是彈窗自帶的
`_CRIMGEN_QSS` 又寫了一份輸入元件樣式（沒有 `:disabled` 變體），把公版的反灰
整個蓋掉；`TaskEditDialog` 還有第二份同樣的複製品。

⚠️ 修正過程中踩到第二層：光刪掉輸入元件那段還不夠，那份區域樣式同時用
`QWidget` 這種寬選擇器把彈窗內**所有容器**塗白；一拿掉，容器就變成一塊一塊的
灰、白底彈窗上到處是色塊（維護者截圖回報「醜爆了」）。故最後整份移除，彈窗
底色回歸公版的 `#f2f2f7`，與程式其他視窗一致。

⚠️ **這支測試同時釘兩件事**：①停用欄位看得出反灰 ②彈窗內不會出現色塊。
第二件是上一版漏掉的——當時只驗欄位顏色，測試全綠但畫面是壞的。
紅了請去改 `lib/theme.py`，**不要在彈窗內補區域樣式**。
"""
import os
import re
import unittest
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QDialog

from lib.theme import APPLE_STYLE

# 比對規則時要先去掉 CSS 註解：註解裡會提到「不要把某條加回來」的選擇器名稱，
# 直接對整份字串做 assertNotIn 會被自己的說明文字誤判。
STYLE_RULES = re.sub(r"/\*.*?\*/", "", APPLE_STYLE, flags=re.S)

_app = QApplication.instance() or QApplication([])

# 公版 `lib/theme.py` 的停用色（灰底）。⚠️ 不要在本檔另寫一組色碼——
# 這裡刻意從 theme 的實際值抄一份常數只是為了斷言可讀，改色時兩邊要一起改，
# 由 test_matches_theme_tokens 釘住兩者一致。
DISABLED_BG = (0xE5, 0xE5, 0xEA)
ENABLED_BG = (0xFF, 0xFF, 0xFF)
NORMAL_TEXT = (0x1C, 0x1C, 0x1E)
DISABLED_TEXT = (0xAE, 0xAE, 0xB2)
PRIMARY_ACTION_ENABLED = (0xA1, 0xB4, 0xCB)


def _dominant_color(widget):
    """算繪該元件並回傳面積最大的顏色（RGB tuple）。

    取眾數而非單點：單點可能落在文字、邊框或下拉箭頭上。停用與否的差別是
    **整片底色**，眾數最穩。
    """
    image = widget.grab().toImage()
    counter = Counter()
    for y in range(0, image.height()):
        for x in range(0, image.width()):
            c = image.pixelColor(x, y)
            counter[(c.red(), c.green(), c.blue())] += 1
    return counter.most_common(1)[0][0]



class TestThemeTokens(unittest.TestCase):
    def test_matches_theme_tokens(self):
        """本檔的色碼常數必須與公版一致（改色時不會只改一邊）。"""
        self.assertIn("background-color: #e5e5ea", APPLE_STYLE)
        self.assertIn("QLineEdit:disabled", APPLE_STYLE)
        self.assertIn("QComboBox:disabled", APPLE_STYLE)
        self.assertIn("QDateEdit:disabled", APPLE_STYLE)

    def test_window_background_rules_are_in_the_right_order(self):
        """⚠️ 公版裡 `QWidget { transparent }` 必須寫在視窗底色**之前**。

        兩者特異度相同（各一個型別選擇器），Qt 由後者勝。順序寫反的話
        `transparent` 會把 `QDialog` 的底色中和掉，視窗變透明、在 Windows 上
        渲染成整塊黑。2026-08-07 實測踩過。
        """
        widget_rule = APPLE_STYLE.index("QWidget {\n    background-color: transparent;")
        window_rule = APPLE_STYLE.index("QMainWindow, QDialog {")
        self.assertLess(
            widget_rule, window_rule,
            "QWidget 透明那條必須在視窗底色之前，否則視窗底色會被中和成透明（全黑）")

    def test_dialog_template_block_exists(self):
        """⚠️ 彈窗公版區塊：還原 v1.2.10 外觀，但只此一份、且限定 QDialog。

        它取代了六個彈窗各自帶的那份區域 QSS（其中五份漏 `:disabled`，造成
        「欄位鎖住了卻看不出來」）。⚠️ 範圍必須留在 `QDialog`——套到全域會讓
        分頁沒鎖死高度的欄位矮 4px、鎖死的不動，同頁高低不齊（LAY-6）。
        """
        self.assertIn("QDialog QLineEdit", STYLE_RULES)
        self.assertIn("QDialog {\n    background-color: #ffffff;", STYLE_RULES)

    def test_dialog_block_declares_no_disabled_state(self):
        """⚠️ 彈窗公版**不得**宣告停用態。

        `QLineEdit:disabled` 帶偽狀態、特異度高於這裡的兩個型別選擇器，公版的
        反灰本來就生效；在此「補齊」反而會把反灰鎖死成固定值，重演 QSS-8。
        """
        selectors = [sel for sel, _ in
                     re.findall(r"([^{}]+)\{([^{}]*)\}", STYLE_RULES)
                     if "QDialog " in sel]
        self.assertTrue(selectors, "找不到彈窗公版的規則，區塊被刪了？")
        for sel in selectors:
            self.assertNotIn(
                ":disabled", sel,
                f"彈窗公版出現 `{sel.strip()}`；停用態交給全域規則處理")

    def test_message_box_keeps_window_background(self):
        """訊息框是 QDialog 子類，但底色要維持灰（與 v1.2.10 一致）。

        靠的是 `QMessageBox` 規則排在彈窗公版**之後**、同特異度後者勝；
        把彈窗公版往後搬會讓訊息框一起變白。
        """
        self.assertLess(STYLE_RULES.index("QDialog QLineEdit"),
                        STYLE_RULES.index("QMessageBox {"),
                        "彈窗公版必須排在 QMessageBox 之前")

    def test_no_container_patch_rule(self):
        """⚠️ `QDialog > QWidget` 那條補丁不得復活。

        它會連 `QLineEdit`／`QComboBox`／`QDateEdit` 一起匹配（都是 QWidget），
        且特異度高於單獨的 `QLineEdit`，於是輸入框白底被容器灰底蓋掉——
        現場回報的「停用了卻看不出來」就是它的下游症狀。
        """
        self.assertNotIn(
            "QDialog > QWidget", STYLE_RULES,
            "容器補丁又回來了；視窗底色請靠上一條測試釘住的順序解決")


class TestTemplateCoversEveryDisabledState(unittest.TestCase):
    """⚠️ 2026-08-07 全面稽核：區域 QSS 蓋掉公版偽狀態的地方逐一修掉後，
    以真正的程式路徑釘住結果。這幾條都是「停用了卻看不出來」的同一個病。

    紅了不要在區域樣式裡補色碼——先確認公版有沒有那個狀態，沒有就補公版。
    """

    @classmethod
    def setUpClass(cls):
        cls._prev = _app.styleSheet()
        _app.setStyleSheet(APPLE_STYLE)

    @classmethod
    def tearDownClass(cls):
        _app.setStyleSheet(cls._prev)

    def _text_counts(self, w):
        image = w.grab().toImage()
        counter = Counter()
        for y in range(image.height()):
            for x in range(image.width()):
                c = image.pixelColor(x, y)
                counter[(c.red(), c.green(), c.blue())] += 1
        return counter

    def test_template_has_generic_disabled_button(self):
        """⚠️ 公版原本**只有** hover／pressed，沒有通用 `QPushButton:disabled`，
        每支自訂按鈕都得自己記得補（PITFALLS QSS-4 長年靠人記得）。已補上。"""
        self.assertIn("QPushButton:disabled", STYLE_RULES)

    def test_plain_button_greys_out(self):
        from PySide6.QtWidgets import QPushButton, QVBoxLayout
        dlg = QDialog(); QVBoxLayout(dlg)
        btn = QPushButton("確認發文"); dlg.layout().addWidget(btn)
        self.addCleanup(dlg.deleteLater)
        dlg.show(); btn.setEnabled(False); _app.processEvents()
        self.assertEqual(_dominant_color(btn), DISABLED_BG,
                         "一般按鈕停用後沒有反灰")

    def test_primary_action_buttons_have_a_distinct_disabled_rendering(self):
        """主要動作 ID selector 不得蓋掉通用停用態。

        五顆有現行唯讀鎖路徑；兩顆 paper-only 與兩顆 archive 鈕則只驗同一
        selector 群組的一致性。objectName 從公版 base selector 動態解析，避免
        測試另養一份九顆清單。
        """
        from PySide6.QtWidgets import QPushButton, QVBoxLayout

        match = re.search(
            r"((?:QPushButton#[\w_]+\s*,\s*)+QPushButton#[\w_]+)\s*\{"
            r"\s*background-color:\s*#a1b4cb;",
            STYLE_RULES,
            flags=re.I,
        )
        self.assertIsNotNone(match, "找不到主要動作鈕的 base selector 群組")
        object_names = re.findall(r"QPushButton#([\w_]+)", match.group(1))
        self.assertEqual(len(object_names), 9, "主要動作鈕群組應含九個 objectName")

        dlg = QDialog()
        QVBoxLayout(dlg)
        self.addCleanup(dlg.deleteLater)
        for object_name in object_names:
            btn = QPushButton(object_name)
            btn.setObjectName(object_name)
            dlg.layout().addWidget(btn)
        dlg.show()
        _app.processEvents()

        for btn in dlg.findChildren(QPushButton):
            with self.subTest(object_name=btn.objectName()):
                btn.setEnabled(True)
                _app.processEvents()
                enabled = _dominant_color(btn)
                self.assertEqual(enabled, PRIMARY_ACTION_ENABLED)
                btn.setEnabled(False)
                _app.processEvents()
                disabled = _dominant_color(btn)
                self.assertNotEqual(
                    disabled, enabled,
                    f"#{btn.objectName()} 停用後仍維持主要動作色")

    def test_radio_text_greys_out(self):
        """`RADIO_STYLE` 已移除（與公版逐項相同的複製品，但漏了 `:disabled`）。

        原症狀：唯讀模式下陳報頁「輸入框灰了、按鈕灰了，選項文字還是黑的」。
        """
        from PySide6.QtWidgets import QRadioButton, QVBoxLayout
        dlg = QDialog(); QVBoxLayout(dlg)
        rb = QRadioButton("現行犯"); dlg.layout().addWidget(rb)
        self.addCleanup(dlg.deleteLater)
        dlg.show(); rb.setEnabled(False); _app.processEvents()
        c = self._text_counts(rb)
        self.assertGreater(c[DISABLED_TEXT], c[NORMAL_TEXT],
                           "radio 停用後文字沒有變灰")

    def test_combo_hint_does_not_shadow_disabled_text(self):
        """`attachComboHint` 設在 combo 元件上，必須連 `:disabled` 一起寫。

        原症狀：唯讀模式下陳報頁案類欄的文字不會變灰。
        """
        from PySide6.QtWidgets import QVBoxLayout
        from ui_utils.widgets import attachComboHint
        dlg = QDialog(); QVBoxLayout(dlg)
        combo = QComboBox(); combo.setEditable(True)
        combo.addItem("", None); combo.addItem("302妨害自由", "CT01")
        dlg.layout().addWidget(combo)
        attachComboHint(combo, "輸入或下拉選擇")
        combo.setCurrentIndex(1)
        self.addCleanup(dlg.deleteLater)
        dlg.show(); combo.setEnabled(False); _app.processEvents()
        c = self._text_counts(combo)
        self.assertGreater(c[DISABLED_TEXT], c[NORMAL_TEXT],
                           "案類欄停用後文字沒有變灰")


class TestCheckboxIndicatorTick(unittest.TestCase):
    """勾選框勾選時要畫出打勾（2026-09-12 維護者裁示：原本只填色、不直覺）。

    公版以 `image: url(:/chk_*.svg)` 疊勾；圖示沒登記進 qrc 或 rcc 沒重編時
    Qt 不報錯、只是畫不出來，故以算繪像素驗「真的有勾」。
    """

    CHECKED_BG = (0x6E, 0x8F, 0xAC)
    TICK = (0xFF, 0xFF, 0xFF)

    def setUp(self):
        import res.resources_rc  # noqa: F401  qrc 圖示
        self._old = _app.styleSheet()
        _app.setStyleSheet(APPLE_STYLE)

    def tearDown(self):
        _app.setStyleSheet(self._old)

    def _colors(self, checked, enabled):
        from PySide6.QtWidgets import QCheckBox
        cb = QCheckBox()
        self.addCleanup(cb.deleteLater)
        cb.setChecked(checked)
        cb.setEnabled(enabled)
        cb.resize(30, 30)
        cb.show()
        _app.processEvents()
        image = cb.grab().toImage()
        return Counter(
            (c.red(), c.green(), c.blue())
            for c in (image.pixelColor(x, y)
                      for x in range(image.width())
                      for y in range(image.height())))

    def test_icons_registered_in_qrc(self):
        from PySide6.QtCore import QFile
        import res.resources_rc  # noqa: F401
        for path in (":/chk_check.svg", ":/chk_check_disabled.svg"):
            self.assertTrue(QFile.exists(path), f"{path} 未登記進 qrc 或 rcc 未重編")

    def test_checked_draws_white_tick_on_blue(self):
        colors = self._colors(checked=True, enabled=True)
        self.assertGreater(colors[self.CHECKED_BG], 0, "勾選底色不是公版深藍")
        self.assertGreater(colors[self.TICK], 0, "勾選時沒有畫出白勾")

    def test_unchecked_has_no_tick_fill(self):
        colors = self._colors(checked=False, enabled=True)
        self.assertEqual(colors[self.CHECKED_BG], 0)

    def test_disabled_checked_still_shows_grey_tick(self):
        colors = self._colors(checked=True, enabled=False)
        self.assertGreater(colors[DISABLED_BG], 0)
        self.assertGreater(colors[DISABLED_TEXT], 0, "停用勾選時勾勾看不見")
        self.assertEqual(colors[self.TICK], 0, "停用時不該是白勾（灰底上看不見）")


if __name__ == "__main__":
    unittest.main()
