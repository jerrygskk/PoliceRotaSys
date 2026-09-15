"""資料庫連線慣例與設定存取。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

# App_Settings 的 key（DEVELOPER.md §7）。
# ⚠️ 新增 key 時 DEVELOPER §7 的表要同步補一列。
KEY_UNIT_NAME = "unit_name"
KEY_OUTPUT_DIR = "output_dir"
KEY_TITLE_FORMAT = "sheet_title_format"
KEY_SCHEMA_VERSION = "schema_version"


def connect(db_path: str) -> sqlite3.Connection:
    """開連線。⚠️ 一定要開 foreign_keys——SQLite 預設是關的。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def opened(db_path: str):
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute(
        "SELECT value FROM App_Settings WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO App_Settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
