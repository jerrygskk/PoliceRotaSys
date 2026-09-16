"""資料庫結構的**唯一來源**（DEVELOPER.md §3）。

⚠️ 要改結構就改這裡，不要在別處手寫 CREATE TABLE。

兩區分界是整個設計的重點：

  設定區    輪番模板與人員名單，承辦人隨時可改、可刪
  月表區    每個月一筆，產出時把當時的規則與名單**拷一份**存進去

⚠️ **月表不參照設定區**：規則與姓名都是拷進 snapshot 的整塊 JSON。
改模板、改名字、刪人都不會動到已經產生的月表——歷史正確性靠快照，
不靠把設定鎖死。這是刻意拿掉舊版「規則版本／草稿／啟用／鎖死 trigger」
那一整套的理由：指標拆掉之後，鎖就沒有存在的必要了。

⚠️ 月表可改也可刪（承辦人排下個月本來就會邊排邊調）。誤改誤刪靠備份救，
不靠資料庫擋——硬擋只會逼使用者走「刪掉重產」這條更容易出錯的路。
"""
from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

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
    -- 女警。勾選後名字在 xlsx 與 pdf 都印紅色。
    female    INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0
)""",
    # 輪番模板。可存多份讓所長挑，數量不設上限。
    """CREATE TABLE IF NOT EXISTS Rota_Template (
    template_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT ''
)""",
    """CREATE TABLE IF NOT EXISTS T_Group (
    group_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL REFERENCES Rota_Template(template_id),
    name        TEXT NOT NULL,
    mode        TEXT NOT NULL CHECK (mode IN ('rotate','fixed','blank')),
    range_expr  TEXT NOT NULL,
    -- 這個區塊左邊要不要再放一次日期／星期欄。現行紙本不是每個區塊都有
    -- （幹部與快打勤務前面就沒有），所以做成設定而不是寫死規則。
    header_before INTEGER NOT NULL DEFAULT 1,
    -- 這個區塊每欄的相對寬度。手寫欄要留得下筆跡，所以比輪番欄寬。
    -- 由程式依模式決定，不給使用者調（維護者裁示）。
    col_weight  REAL NOT NULL DEFAULT 1.0,
    -- 跨整個區塊的註記，畫在姓名列的合併格裡。一行一筆文字。
    note        TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0
)""",
    # 循環格數不存欄位——它就是展開後的格數，存了會有兩份真相。
    """CREATE TABLE IF NOT EXISTS T_Slot (
    group_id      INTEGER NOT NULL REFERENCES T_Group(group_id),
    seq           INTEGER NOT NULL,
    is_rest       INTEGER NOT NULL DEFAULT 0,
    code_override TEXT,
    PRIMARY KEY (group_id, seq)
)""",
    # ---- 月表區 ---------------------------------------------------------
    # snapshot：當月的規則與姓名順序的完整副本（JSON）。
    # ⚠️ 存姓名字串而不是 member_id——存 id 等於沒脫勾，改名或刪人會讓
    # 去年的月表跟著變，而且印出來看不出錯。
    # ⚠️ 起始格位存的是格位（slot_seq）而不是番號：休沒有番號，存番號就分不出
    # 「休在第 6 格還是第 7 格」，而這兩者隔天的結果完全不同。
    """CREATE TABLE IF NOT EXISTS Month_Plan (
    plan_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    year       INTEGER NOT NULL,
    month      INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    origin     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    snapshot   TEXT NOT NULL,
    UNIQUE (year, month)
)""",
)

INDEXES = (
    """CREATE INDEX IF NOT EXISTS ix_t_group_template
       ON T_Group (template_id, sort_order)""",
)


def create_all(conn: sqlite3.Connection) -> None:
    """建立（或補齊）所有結構。可重複執行。"""
    for statement in (*TABLES, *INDEXES):
        conn.execute(statement)
    conn.execute(
        "INSERT OR IGNORE INTO App_Settings(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
