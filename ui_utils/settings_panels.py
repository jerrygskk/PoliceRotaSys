"""
settings_panels.py — 設定面板公版（自 PoliceDocSys 搬入）

只保留共用外框：
  - _SettingsPanel   白卡片 QGroupBox，內建 isDirty／儲存鈕亮灰／reload 基準
  - _save_row        底部右對齊「儲存」鈕列

各設定面板（單位名稱、輸出資料夾等）繼承 _SettingsPanel 自行實作。
"""
import os

from PySide6.QtCore    import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox, QFrame, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QFileDialog, QSpinBox, QDoubleSpinBox, QAbstractSpinBox,
    QRadioButton, QButtonGroup,
)

from .ui_common import confirmBox, msgWarning

# ── 面板共用樣式 ───────────────────────────────────────────────────
# 白卡片＋標題浮框；子元件顏色皆明設（§2 雷：新 Widget 繼承全域深色會看不見）。
# :disabled 一律給灰（§2 雷：無 :disabled 不會變灰）。
_PANEL_SS = """
    QGroupBox {
        background-color: #ffffff;
        border: 1px solid #d1d1d6;
        border-radius: 10px;
        margin-top: 14px;
        padding-top: 8px;
        font-size: 14pt;
        font-weight: 600;
        color: #1c1c1e;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        background-color: #ffffff;
    }
    QGroupBox:disabled { color: #aeaeb2; }
    QLabel { color: #3a3a3c; background: transparent;
             font-size: 13pt; font-weight: 400; }
    QLabel:disabled { color: #c5c5c9; }
    QLineEdit {
        background-color: #ffffff; color: #000000;
        border: 1px solid #cccccc; border-radius: 4px; padding: 4px 8px;
        font-size: 13pt; font-weight: 400;
    }
    QLineEdit:focus { border: 1px solid #8fa8c8; }
    QLineEdit:disabled { background-color: #f2f2f7; color: #aeaeb2; }
    QComboBox {
        background-color: #ffffff; color: #000000;
        border: 1px solid #cccccc; border-radius: 4px; padding: 4px 8px;
        font-size: 13pt; font-weight: 400;
    }
    QComboBox:disabled { background-color: #f2f2f7; color: #aeaeb2; }
    QSpinBox, QDoubleSpinBox {
        background-color: #ffffff; color: #000000;
        border: 1px solid #cccccc; border-radius: 4px; padding: 4px 8px;
        font-size: 13pt; font-weight: 400;
    }
    QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #8fa8c8; }
    QSpinBox:disabled, QDoubleSpinBox:disabled {
        background-color: #f2f2f7; color: #aeaeb2;
    }
"""

_HINT_SS = "color: #8e8e93; font-size: 11pt; font-weight: 400;"
_ERR_BORDER_SS = ("border: 1px solid #e74c3c; border-radius: 4px; "
                  "padding: 4px 8px; font-size: 13pt; font-weight: 400;")

# 儲存鈕：比照全 app 主要動作鈕（送出／歸檔）的墨藍樣式（theme.py「送出按鈕」）
_SAVE_SS = """
    QPushButton {
        background-color: #a1b4cb; color: #ffffff;
        border: none; border-radius: 8px;
        padding: 8px 24px; font-weight: 600;
    }
    QPushButton:hover    { background-color: #4977b1; }
    QPushButton:pressed  { background-color: #39649a; }
    QPushButton:disabled { background-color: #d1d9e3; color: #ffffff; }
"""


def _save_row(layout, extra_left=None):
    """底部按鈕列：右對齊「儲存」，可選左側額外按鈕。回傳儲存鈕。
    左側額外鈕不設樣式，沿用 theme.py 通用 QPushButton（白底灰框）。
    儲存鈕平常反灰，有未存變更（isDirty）才亮起；存檔成功即回灰＝完成回饋，
    不另彈成功視窗。"""
    row = QHBoxLayout()
    if extra_left is not None:
        row.addWidget(extra_left)
    row.addStretch()
    btn_save = QPushButton("儲存")
    btn_save.setStyleSheet(_SAVE_SS)
    btn_save.setEnabled(False)
    # 面板嵌在頁面裡（非 Dialog），不設 default，避免頁上 Enter 誤觸存檔
    btn_save.setAutoDefault(False)
    btn_save.setDefault(False)
    row.addWidget(btn_save)
    layout.addLayout(row)
    return btn_save


class _SettingsPanel(QGroupBox):
    """系統設定四面板的共用基底。

    收斂原本各抄一份的 isDirty／_updateSaveBtn／reload 尾段（重設 dirty 基準）。
    子類別只需實作：
        _build()   建立 UI，並把儲存鈕存成 self._btn_save
        _values()  回傳「當前畫面值」（tuple 或 dict 皆可，供 != 比較）
        reload()   重讀 DB 值填入畫面，結尾呼叫 self._markLoaded()
    """

    def __init__(self, title, db_path, parent=None):
        super().__init__(title, parent)
        self.db_path = db_path
        self.setStyleSheet(_PANEL_SS)
        self._build()
        self.reload()

    def _markLoaded(self):
        """把 dirty 基準設為當前畫面值並更新儲存鈕（reload()/存檔成功後呼叫）。"""
        self._loaded = self._values()
        self._updateSaveBtn()

    def isDirty(self):
        """畫面值與最後載入/儲存值不同 → 有未存變更（切頁提示、儲存鈕亮灰用）。"""
        loaded = getattr(self, "_loaded", None)
        return loaded is not None and self._values() != loaded

    def _updateSaveBtn(self, *_):
        btn = getattr(self, "_btn_save", None)
        if not btn:
            return
        dirty = self.isDirty()
        # 存檔成功回灰前先取消按鈕焦點：停用「持有焦點的元件」時
        # Qt 會把焦點自動塞給 tab 順序的下一個輸入欄，游標會亂跳
        if not dirty and btn.hasFocus():
            btn.clearFocus()
        btn.setEnabled(dirty)
