"""資料庫結構的**唯一來源**（DEVELOPER.md §3）。

⚠️ 要改結構就改這裡，不要在別處手寫 CREATE TABLE。

三區分界是整個設計的重點：
  設定區      承辦人日常維護，可隨時改
  規則版本區  草稿可改，啟用即鎖死（由 trigger 擋，不靠程式自律）
  事實區      產出後只新增、不修改

規則版本的「不可修改」**不是靠程式自律**，是靠底下那幾條 trigger。
就算日後有人寫錯 code，資料庫層會直接 ABORT。
"""
from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

TABLES = (
    # ---- 設定區 ---------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS App_Settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS Member (
    member_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    active    INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0
)""",
    # ---- 規則版本區 -----------------------------------------------------
    """CREATE TABLE IF NOT EXISTS Ruleset (
    ruleset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL
)""",
    # status：'草稿' 可改可刪；'啟用' 鎖死。單向不可逆。
    # version_no：草稿為 NULL，啟用時才配號——草稿先占號會造成跳號。
    """CREATE TABLE IF NOT EXISTS Ruleset_Version (
    version_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ruleset_id   INTEGER NOT NULL REFERENCES Ruleset(ruleset_id),
    draft_name   TEXT,
    version_no   INTEGER,
    status       TEXT NOT NULL CHECK (status IN ('草稿','啟用')),
    created_at   TEXT NOT NULL,
    activated_at TEXT,
    note         TEXT
)""",
    """CREATE TABLE IF NOT EXISTS RV_Group (
    group_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES Ruleset_Version(version_id),
    name       TEXT NOT NULL,
    mode       TEXT NOT NULL CHECK (mode IN ('rotate','fixed','blank')),
    range_expr TEXT NOT NULL,
    rest_code  TEXT NOT NULL DEFAULT '00',
    -- 這個區塊左邊要不要再放一次日期／星期欄。現行紙本不是每個區塊都有
    -- （幹部與快打勤務前面就沒有），所以做成設定而不是寫死規則。
    header_before INTEGER NOT NULL DEFAULT 1,
    -- 跨整個區塊的註記，畫在姓名列的合併格裡。一行一筆「顏色|文字」。
    -- 內容會提到番號（例「早班:(8-12、15)」），所以跟著規則版本一起凍結。
    note       TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0
)""",
    # 循環格數不存欄位——它就是展開後的格數，存了會有兩份真相。
    """CREATE TABLE IF NOT EXISTS RV_Slot (
    version_id    INTEGER NOT NULL REFERENCES Ruleset_Version(version_id),
    group_id      INTEGER NOT NULL REFERENCES RV_Group(group_id),
    seq           INTEGER NOT NULL,
    is_rest       INTEGER NOT NULL DEFAULT 0,
    code_override TEXT,
    PRIMARY KEY (group_id, seq)
)""",
    # ---- 事實區 ---------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS Month_Plan (
    plan_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    year               INTEGER NOT NULL,
    month              INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    ruleset_version_id INTEGER NOT NULL REFERENCES Ruleset_Version(version_id),
    origin             TEXT NOT NULL CHECK (origin IN ('chain','reset')),
    created_at         TEXT NOT NULL,
    UNIQUE (year, month)
)""",
    # 存的是格位（slot_seq）而不是番號：休沒有番號，存番號就分不出
    # 「休在第 6 格還是第 7 格」，而這兩者隔天的結果完全不同。
    """CREATE TABLE IF NOT EXISTS Month_Seed (
    plan_id     INTEGER NOT NULL REFERENCES Month_Plan(plan_id) ON DELETE CASCADE,
    rv_group_id INTEGER NOT NULL REFERENCES RV_Group(group_id),
    member_id   INTEGER NOT NULL REFERENCES Member(member_id),
    row_no      INTEGER NOT NULL,
    slot_seq    INTEGER NOT NULL,
    PRIMARY KEY (plan_id, rv_group_id, member_id)
)""",
)

# 一個人不可同時在兩個番組（DEVELOPER §9 已排除的需求）。
INDEXES = (
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_month_seed_one_group_per_member
       ON Month_Seed (plan_id, member_id)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_month_seed_slot_taken_once
       ON Month_Seed (plan_id, rv_group_id, slot_seq)""",
)

_LOCK_MSG = "已啟用的規則不可修改"


def _lock_triggers(table: str, version_col: str = "version_id") -> tuple[str, ...]:
    """對 table 產生「非草稿即禁改禁刪」的兩條 trigger。"""
    guard = (
        f"WHEN (SELECT status FROM Ruleset_Version "
        f"WHERE version_id = OLD.{version_col}) <> '草稿'"
    )
    return (
        f"""CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update
BEFORE UPDATE ON {table} {guard}
BEGIN SELECT RAISE(ABORT, '{_LOCK_MSG}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete
BEFORE DELETE ON {table} {guard}
BEGIN SELECT RAISE(ABORT, '{_LOCK_MSG}'); END""",
    )


TRIGGERS = (
    *_lock_triggers("RV_Group"),
    *_lock_triggers("RV_Slot"),
    # 版本本身：啟用後不可刪，也不可改回草稿——否則鎖形同虛設。
    """CREATE TRIGGER IF NOT EXISTS trg_version_no_delete
BEFORE DELETE ON Ruleset_Version WHEN OLD.status <> '草稿'
BEGIN SELECT RAISE(ABORT, '已啟用的規則不可刪除'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_version_no_unlock
BEFORE UPDATE ON Ruleset_Version
WHEN OLD.status = '啟用' AND NEW.status <> '啟用'
BEGIN SELECT RAISE(ABORT, '啟用的規則不可改回草稿'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_version_frozen_fields
BEFORE UPDATE ON Ruleset_Version
WHEN OLD.status = '啟用'
 AND (NEW.version_no IS NOT OLD.version_no
      OR NEW.ruleset_id IS NOT OLD.ruleset_id
      OR NEW.activated_at IS NOT OLD.activated_at)
BEGIN SELECT RAISE(ABORT, '已啟用的規則不可修改'); END""",
    # 草稿最多 3 份（DEVELOPER §3）。所長要挑方案，但不必無限多份。
    """CREATE TRIGGER IF NOT EXISTS trg_draft_limit
BEFORE INSERT ON Ruleset_Version WHEN NEW.status = '草稿'
 AND (SELECT COUNT(*) FROM Ruleset_Version WHERE status = '草稿') >= 3
BEGIN SELECT RAISE(ABORT, '草稿最多 3 份，請先刪掉不要的'); END""",
    # 事實區只新增不修改：要重產就整筆刪掉重來，刪除是明確動作。
    """CREATE TRIGGER IF NOT EXISTS trg_month_plan_no_update
BEFORE UPDATE ON Month_Plan
BEGIN SELECT RAISE(ABORT, '月計畫不可修改，請刪除後重新產生'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_month_seed_no_update
BEFORE UPDATE ON Month_Seed
BEGIN SELECT RAISE(ABORT, '月計畫不可修改，請刪除後重新產生'); END""",
)


def create_all(conn: sqlite3.Connection) -> None:
    """建立（或補齊）所有結構。可重複執行。"""
    for statement in (*TABLES, *INDEXES, *TRIGGERS):
        conn.execute(statement)
    conn.execute(
        "INSERT OR IGNORE INTO App_Settings(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
