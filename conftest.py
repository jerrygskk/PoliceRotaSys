"""專案層 pytest 啟動設定（自 PoliceDocSys 搬入，只保留本專案用得到的部分）。"""
from __future__ import annotations

import os

import pytest


# 必須在任何測試模組 collection/import PySide6 前完成。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# --- 日期防呆的測試處置（PITFALLS TST-4）---------------------------------
# 實作在 tests/date_guard_shim.py，是 pytest 與 unittest 共用的唯一一份；
# unittest 跑法載不到本檔，由 tests/__init__.py 匯入同一支安裝。
from tests.date_guard_shim import OWN_TESTS as DATE_GUARD_OWN_TESTS   # noqa: E402
from tests.date_guard_shim import installAutoConfirm                  # noqa: E402


@pytest.fixture(autouse=True)
def _auto_confirm_date_guard(request, monkeypatch):
    if request.path.name in DATE_GUARD_OWN_TESTS:
        return
    installAutoConfirm(monkeypatch)
