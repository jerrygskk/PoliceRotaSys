# -*- mode: python ; coding: utf-8 -*-
# 打包設定（已入庫，是原始碼不是產物）。build 一律：
#
#     python -m PyInstaller --clean --noconfirm PoliceRotaSys.spec
#
# 排除清單的唯一來源是 tools/pyi_prune.py，不要在這裡另開清單。
# 說明見 DEVELOPER.md「打包」與 PITFALLS.md PKG 組。
import os
import sys

sys.path.insert(0, os.path.join(SPECPATH, "tools"))
from pyi_prune import EXCLUDES, prune


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
prune(a)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PoliceRotaSys",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    version="version_info.txt",
)
