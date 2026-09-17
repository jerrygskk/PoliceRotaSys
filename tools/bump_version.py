"""
進版工具：一次完成「改版號 + 產出 version_info.txt」（自 PoliceDocSys 搬入）。

用法：
    python tools/bump_version.py 0.1.1   # 版號一律自帶（從專案根目錄執行）

會做兩件事：
  1. 改寫 lib/version.py 的 __version__
  2. 產出 version_info.txt（exe 右鍵→內容→詳細資料的版本資訊，打包 --version-file 用）

⚠️ 進版一律用本工具，不要手改 lib/version.py，否則 version_info.txt 會與版號不同步。
進位與否由維護者決定；git tag v{版本} 仍須手動。
"""
import re
import sys
from pathlib import Path

# 顯示字串（要改產品名改這裡）
# ⚠️ public repo：不得寫入實際單位名稱，單位名稱由 App_Settings 的 unit_name 設定
COMPANY     = "勤休預定表產生器"
PRODUCT     = "勤休預定表產生器"
DESCRIPTION = "勤休預定表產生器"
COPYRIGHT   = "© 2026 PoliceRotaSys"
EXE_NAME    = "PoliceRotaSys.exe"

# 錨定 repo 根（本檔在 tools/ 之下），與當前工作目錄脫鉤
ROOT        = Path(__file__).resolve().parent.parent
VERSION_PY  = ROOT / "lib" / "version.py"
INFO_TXT    = ROOT / "version_info.txt"
_VER_RE     = re.compile(r'__version__\s*=\s*"([^"]*)"')


def read_current() -> str:
    m = _VER_RE.search(VERSION_PY.read_text(encoding="utf-8"))
    if not m:
        sys.exit("錯誤：無法於 lib/version.py 讀取版本號碼（__version__）。")
    return m.group(1)


def write_version(new: str) -> None:
    text = VERSION_PY.read_text(encoding="utf-8")
    text = _VER_RE.sub(f'__version__ = "{new}"', text, count=1)
    VERSION_PY.write_text(text, encoding="utf-8")


def render_info(version: str, product: str, exe_name: str) -> str:
    parts = [int(x) for x in version.split(".")]
    while len(parts) < 4:
        parts.append(0)
    vers = tuple(parts[:4])
    return f"""# UTF-8
# 由 bump_version.py 自動產生，請勿手改（用 bump_version.py 進版即可）
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vers},
    prodvers={vers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040404b0',
        [
          StringStruct('CompanyName', '{COMPANY}'),
          StringStruct('FileDescription', '{product}'),
          StringStruct('FileVersion', '{version}'),
          StringStruct('InternalName', '{exe_name}'),
          StringStruct('LegalCopyright', '{COPYRIGHT}'),
          StringStruct('OriginalFilename', '{exe_name}'),
          StringStruct('ProductName', '{product}'),
          StringStruct('ProductVersion', '{version}')
        ])
    ]),
    VarFileInfo([VarStruct('Translation', [1028, 1200])])
  ]
)
"""


def gen_info(version: str) -> None:
    INFO_TXT.write_text(render_info(version, PRODUCT, EXE_NAME), encoding="utf-8")


if __name__ == "__main__":
    current = read_current()
    print(f"目前版本號碼：v{current}")

    if len(sys.argv) < 2:
        sys.exit("請指定欲進版之版本號碼，如：python tools/bump_version.py 0.1.1")
    new = sys.argv[1].lstrip("v")
    if not re.fullmatch(r"\d+(\.\d+){1,3}", new):
        sys.exit(f"版本號碼格式不正確：{new}（如：0.1.1）")

    write_version(new)
    gen_info(new)
    print(f"已完成進版：v{current} → v{new}（已更新 lib/version.py 與 version_info.txt）")
