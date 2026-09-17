# -*- coding: utf-8 -*-
"""PyInstaller 打包瘦身：把 Analysis 收進來、但本專案用不到的 binary／data 剔除。

自 PoliceDocSys `tools/pyi_prune.py` 搬入，排除清單照本專案實際需要調整。
由入庫的 `PoliceRotaSys.spec` 呼叫：

    from pyi_prune import EXCLUDES, prune
    prune(a)

⚠️ `--exclude-module` 只砍得掉 Python 模組，砍不掉 hook 以「binary」身分收進來的
DLL（`opengl32sw.dll`、`.qm` 語系檔等），那些只能在 spec 裡對 `a.binaries`／
`a.datas` 過濾，這支模組就是做這件事的唯一地方。

⚠️ 砍錯通常是**開機就壞**（DLL 缺相依），但 PDF 匯出、SVG 圖示這類要實際用到才會
發作。改清單後打包版要實際開起來，並手動匯出一次 Excel／PDF。
"""

import os

# 打包機器 PATH 上若有 Git for Windows，PyInstaller 會撿到 mingw64 的 OpenSSL
# （libcrypto-3-x64.dll／libssl-3-x64.dll，未壓縮約 6.8MB）混進來。Python 自己
# 的 libcrypto-3.dll 才是 hashlib 要用的那份，不受影響（PoliceDocSys 踩過）。
_BAD_SOURCE_DIRS = (
    r"\program files\git",
    r"\program files (x86)\git",
)

# 純 QWidget 程式用不到的 Qt 元件。
#
# ⚠️ 與 PoliceDocSys 不同：本專案**沒有 QtUiTools**（畫面一律程式碼排版，已拿掉
# loadUi），所以 Qt6OpenGL／Qt6OpenGLWidgets 不再是連結期相依，可以一起砍。
# 公文系統那邊有 UiTools，砍了會開機 ImportError，不要把這條抄回去。
_DROP_BASENAMES = {
    # 軟體 OpenGL 後備（20MB）：只有 QtQuick／QOpenGLWidget 或無顯示驅動的遠端桌面用得到
    "opengl32sw.dll",
    "qt6opengl.dll",
    "qt6openglwidgets.dll",
    # QML／Quick：從未 import
    "qt6quick.dll",
    "qt6quickwidgets.dll",
    "qt6qml.dll",
    "qt6qmlmodels.dll",
    "qt6qmlmeta.dll",
    "qt6qmlworkerscript.dll",
    "qt6virtualkeyboard.dll",
    # 用不到的影像格式。保留：qsvg／qsvgicon（勾選框、下拉箭頭、視窗圖示的命脈）、
    # qico（視窗圖示）；PNG 是 Qt6Gui 內建，啟動畫面 banner.png 不需要 plugin。
    # ⚠️ 本專案沒有任何 JPG，qjpeg 一併砍（2026-09-17）；日後加 JPG 圖檔要記得拿掉這行
    "qjpeg.dll",
    "qtiff.dll",
    "qwebp.dll",
    "qicns.dll",
    "qtga.dll",
    "qwbmp.dll",
    "qgif.dll",
    # PDF「閱讀」：`qpdf.dll` 是把 PDF 當圖檔讀的 plugin，也是 `Qt6Pdf.dll` 唯一的使用者。
    # ⚠️ 與匯出 PDF 無關：匯出走 QPdfWriter，在 Qt6Gui 裡，不經 Qt6Pdf.dll。
    "qpdf.dll",
    "qt6pdf.dll",
    # 網路：純本機程式，原始碼零網路使用。連同 tls／networkinformation 等 plugin 一起砍。
    "qt6network.dll",
    "qtuiotouchplugin.dll",
    # 備用平台外掛：正式執行一律走 qwindows.dll；測試跑原始碼，不跑這包 exe
    "qdirect2d.dll",
    "qoffscreen.dll",
    "qminimal.dll",
}

# 整個資料夾剔除（dest 路徑前綴，比對時統一小寫 + 正斜線）
_DROP_DEST_PREFIXES = (
    "pyside6/qml/",
    "pyside6/plugins/qmltooling/",
    "pyside6/plugins/virtualkeyboard/",
    "pyside6/plugins/platforminputcontexts/",
    "pyside6/plugins/tls/",
    "pyside6/plugins/networkinformation/",
    "pyside6/plugins/generic/",
)

# Qt 內建對話框的語系檔，只留繁中
_KEEP_LOCALES = ("zh_tw",)

#: spec 的 excludes：Python 綁定層（.pyd）要從這裡擋，DLL 才不會被 hook 帶進來
EXCLUDES = [
    "tkinter", "matplotlib", "numpy", "PIL",
    "PySide6.QtNetwork", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtPdf", "PySide6.QtUiTools",
    # ── 標準庫裡被連帶拉進來、本程式用不到的（2026-09-17 實測 29.9MB → 26.7MB）──
    # 網路／加密：程式完全不連網。ssl 會把 libssl-3.dll 帶進來；_hashlib 會把
    # libcrypto-3.dll（5.2MB）帶進來。hashlib 在 _hashlib 缺席時自動改用內建的
    # _sha2／_md5（編進 python312.dll），random 與 openpyxl 照常可用。
    "ssl", "_ssl", "_hashlib", "ftplib", "http.server", "socketserver", "webbrowser",
    # lzma／bz2：zipfile 只在讀寫這兩種壓縮法時才 import；xlsx 只用 deflate
    "lzma", "_lzma", "bz2", "_bz2", "tarfile",
    # defusedxml：openpyxl 的「讀取」防護，有裝就會 import 並一路拉進 xmlrpc／pydoc；
    # 本程式只寫 xlsx、不讀外部檔案，缺席時 openpyxl 改用標準 xml
    "defusedxml", "xmlrpc", "pydoc", "pydoc_data",
    "unittest",
]


def _norm(dest):
    return dest.replace("\\", "/").lower()


def _drop(dest, src):
    d = _norm(dest)
    s = (src or "").lower()
    if any(bad in s for bad in _BAD_SOURCE_DIRS):
        return "git-openssl"
    if os.path.basename(d) in _DROP_BASENAMES:
        return "unused-qt"
    if d.startswith(_DROP_DEST_PREFIXES):
        return "unused-qt"
    if "/translations/" in d and d.endswith(".qm"):
        if not any(loc in d for loc in _KEEP_LOCALES):
            return "locale"
    return None


def prune(a, verbose=True):
    """就地過濾 Analysis 的 binaries／datas，回傳 {原因: 剔除數}。"""
    stats = {}
    for attr in ("binaries", "datas"):
        kept = []
        for entry in getattr(a, attr):
            dest, src = entry[0], entry[1]
            reason = _drop(dest, src)
            if reason:
                stats[reason] = stats.get(reason, 0) + 1
                if verbose:
                    print(f"pyi_prune: drop [{reason}] {dest}")
            else:
                kept.append(entry)
        setattr(a, attr, kept)
    if verbose:
        total = sum(stats.values())
        detail = ", ".join(f"{k}={v}" for k, v in sorted(stats.items())) or "none"
        print(f"pyi_prune: removed {total} entries ({detail})")
    return stats
