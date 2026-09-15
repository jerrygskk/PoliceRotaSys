"""測試套件。

⚠️ 這個檔案是必要的，不要刪。少了它，`python -m unittest discover -s tests -t .`
會因為 tests 不是可匯入的套件而整包失敗（PoliceDocSys 的 TST-4 是同一類問題）。
"""

# 日期防呆的測試處置（PITFALLS TST-4）：unittest 跑法載不到根 conftest.py，
# 在此安裝同一份遮蔽，否則以非今日日期送出的測試會卡在確認框。
from tests.date_guard_shim import installAutoConfirm as _installAutoConfirm

_installAutoConfirm()
