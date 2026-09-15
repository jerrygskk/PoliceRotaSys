"""種子資料的**唯一來源**（DEVELOPER.md §6）。

沒有匯入機制——不從舊 Excel 讀資料。程式第一次開起來時，資料庫裡就備好
可以直接動手改的東西：

  - 人員：一份假名模板
  - 輪番設定：一份**草稿**（不是啟用版本）。給啟用版等於逼承辦人第一件事
    就是複製為草稿

⚠️ 種子姓名一律虛構。本專案是 public repo，見 tests/test_no_pii.py。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from lib.db_utils import KEY_OUTPUT_DIR, KEY_TITLE_FORMAT, KEY_UNIT_NAME
from lib.layout_model import DEFAULT_TITLE_FORMAT
from lib.rota import MODE_BLANK, blank_labels, expand_range

# ⚠️ 全部是虛構姓名，不得替換成真實同仁。
#
# 人數刻意等於預設草稿三個番組的總格數（20 + 8 + 6 = 34）——模板若配不滿
# 自己的預設規則，第一次開起來就會產出有空欄的月表，承辦人會以為程式壞了。
# 改動 SEED_GROUPS 時要回頭核對這個數字（tests/test_db.py 釘住）。
SEED_MEMBERS = (
    # 大輪番 20 人
    "王小明", "李小華", "張大同", "陳小美", "吳大雄", "林小芳",
    "黃志強", "劉淑芬", "蔡文彬", "楊雅婷", "許家豪", "鄭淑娟",
    "謝明哲", "郭美玲", "洪俊傑", "曾惠雯", "廖建宏", "何雅琪",
    "呂宗翰", "邱佩珊",
    # 固定番 8 人
    "徐立偉", "方怡君", "簡志遠", "馮秀琴", "潘冠廷",
    "葉宗霖", "翁美惠", "藍柏勳",
    # 幹部 6 人
    "孫振宇", "高淑貞", "范文傑", "石雅芬", "尤建德", "溫柏翰",
)

# 預設草稿：照現行紙本的區塊順序（DEVELOPER §8）。
#
# ⚠️ blank 模式的 range_expr 是**逗號分隔的字面欄標題**，不是範圍式。
# 那幾欄有標題有格線但格子全空，供承辦人手寫（紙本上是「休」「補」
# 「通補」那些），不配人也不算番號。
# 紙本上早／中／晚三欄的上方那段班別說明，逐行不同顏色，照抄。
# ⚠️ 內容提到的番號（1-5、16 等）與輪番規則綁在一起，換單位就不一樣，
# 所以它存在規則版本裡、跟著一起凍結，不是寫死在程式。
SEED_SHIFT_NOTE = (
    "blue|晚班:(1-5、16)\n"
    "red|早班:(8-12、15)\n"
    "black|中班(17.18)\n"
    "red|限填1人"
)

SEED_GROUPS = (
    # (名稱, 模式, 範圍式／欄標題, 休假格位, 左邊要不要放日期／星期欄, 註記)
    ("大輪番", "rotate", "1-20", (6, 7, 13, 14, 19, 20), True, ""),
    ("固定番", "fixed", "21-28", (), True, ""),
    ("同仁專案臨檢", "blank", "同仁專案臨檢", (), True, ""),
    ("班別", "blank", "早,中,晚", (), False, SEED_SHIFT_NOTE),
    ("幹部", "fixed", "A-F", (), False, ""),
    ("快打勤務", "blank", "快打勤務", (), False, ""),
)

DEFAULT_SETTINGS = {
    KEY_UNIT_NAME: "○○分局○○派出所",
    KEY_OUTPUT_DIR: "",
    KEY_TITLE_FORMAT: DEFAULT_TITLE_FORMAT,
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def seed_all(conn: sqlite3.Connection, ruleset_name: str = "輪番規則") -> None:
    """塞入種子資料。已經有資料就不重複塞，可重複執行。"""
    _seed_settings(conn)
    _seed_members(conn)
    _seed_draft(conn, ruleset_name)
    conn.commit()


def _seed_settings(conn: sqlite3.Connection) -> None:
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO App_Settings(key, value) VALUES (?, ?)",
            (key, value),
        )


def _seed_members(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM Member LIMIT 1").fetchone():
        return
    conn.executemany(
        "INSERT INTO Member(name, active, sort_order) VALUES (?, 1, ?)",
        [(name, i) for i, name in enumerate(SEED_MEMBERS, start=1)],
    )


def _slot_count(mode: str, expr: str) -> int:
    """⚠️ blank 模式的 expr 是字面欄標題，不能餵給 expand_range。"""
    return len(blank_labels(expr) if mode == MODE_BLANK else expand_range(expr))


def _seed_draft(conn: sqlite3.Connection, ruleset_name: str) -> None:
    if conn.execute("SELECT 1 FROM Ruleset_Version LIMIT 1").fetchone():
        return

    cur = conn.execute("INSERT INTO Ruleset(name) VALUES (?)", (ruleset_name,))
    ruleset_id = cur.lastrowid

    cur = conn.execute(
        "INSERT INTO Ruleset_Version"
        "(ruleset_id, draft_name, version_no, status, created_at, note) "
        "VALUES (?, ?, NULL, '草稿', ?, ?)",
        (ruleset_id, "預設範例", _now(), "程式內建的起始草稿，請改成貴單位的實際規則"),
    )
    version_id = cur.lastrowid

    for order, (name, mode, expr, rests, header, note) in enumerate(
        SEED_GROUPS, start=1
    ):
        cur = conn.execute(
            "INSERT INTO RV_Group"
            "(version_id, name, mode, range_expr, rest_code, header_before, "
            "note, sort_order) VALUES (?, ?, ?, ?, '00', ?, ?, ?)",
            (version_id, name, mode, expr, 1 if header else 0, note, order),
        )
        group_id = cur.lastrowid
        rest_set = set(rests)
        conn.executemany(
            "INSERT INTO RV_Slot(version_id, group_id, seq, is_rest, code_override) "
            "VALUES (?, ?, ?, ?, NULL)",
            [
                (version_id, group_id, seq, 1 if seq in rest_set else 0)
                for seq in range(1, _slot_count(mode, expr) + 1)
            ],
        )
