"""
版本號單一來源（single source of truth）。

所有需要顯示版本的地方都從這裡 import，不要各自寫死：
  from lib.version import __version__

⚠️ 不要手改：進版一律走 `python tools/bump_version.py <版號>`，
否則 version_info.txt 會與版號不同步。進位與否由維護者決定。
"""
__version__ = "1.0.0"
