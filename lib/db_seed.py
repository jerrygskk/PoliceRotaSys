"""種子資料的**唯一來源**（DEVELOPER.md §6）。

沒有匯入機制——不從舊 Excel 讀資料。程式第一次開起來時，資料庫裡就備好
可以直接動手改的東西：

  - 人員：一份假名名單
  - 輪番設定：一份可以直接改的模板

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
# 人數刻意等於預設模板三個群組的總格數（20 + 8 + 6 = 34）——模板若配不滿
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

# 預設模板：照現行紙本的區塊順序（DEVELOPER §8）。
#
# ⚠️ blank 模式的 range_expr 是**逗號分隔的字面欄標題**，不是範圍式。
# 那幾欄有標題有格線但格子全空，供承辦人手寫（紙本上是「休」「補」
# 「通補」那些），不配人也不算番號。
# 模板裡先標幾位女警，讓承辦人一開起來就看得到「紅字＝女警」這件事。
# ⚠️ 全部是虛構姓名。
SEED_FEMALE = frozenset({"李小華", "陳小美", "方怡君"})

# 紙本上早／中／晚三欄的上方那段班別說明，一行一筆純文字。
# ⚠️ 內容提到的番號（1-5、16 等）與輪番規則綁在一起，換單位就不一樣，
# 所以它存在模板裡，並隨月表一起拷進快照，不是寫死在程式。
SEED_SHIFT_NOTE = (
    "晚班:(1-5、16)\n"
    "早班:(8-12、15)\n"
    "中班(17.18)\n"
    "限填1人"
)

# 欄寬權重由維護者指定：輪番 1.1、固定番 1.2、劃假 1.4、幹部 1.2。
# ⚠️ 同仁專案臨檢與快打勤務維護者沒指名，暫用 1.2（同屬手寫欄），待確認。
SEED_GROUPS = (
    # (名稱, 模式, 範圍式／欄標題, 休假格位, 左邊要不要放日期／星期欄,
    #  註記, 欄寬權重)
    ("大輪番", "rotate", "1-20", (6, 7, 13, 14, 19, 20), True, "", 1.1),
    ("固定番", "fixed", "21-28", (), True, "", 1.2),
    ("同仁專案臨檢", "blank", "同仁專案臨檢", (), True, "", 1.2),
    ("劃假", "blank", "早,中,晚", (), False, SEED_SHIFT_NOTE, 1.4),
    ("幹部", "fixed", "A-F", (), False, "", 1.2),
    ("快打勤務", "blank", "快打勤務", (), False, "", 1.2),
)

DEFAULT_SETTINGS = {
    KEY_UNIT_NAME: "○○分局○○派出所",
    KEY_OUTPUT_DIR: "",
    KEY_TITLE_FORMAT: DEFAULT_TITLE_FORMAT,
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def seed_all(conn: sqlite3.Connection, template_name: str = "預設範例") -> None:
    """塞入種子資料。已經有資料就不重複塞，可重複執行。"""
    _seed_settings(conn)
    _seed_members(conn)
    _seed_template(conn, template_name)
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
        "INSERT INTO Member(name, active, female, sort_order) VALUES (?, 1, ?, ?)",
        [
            (name, 1 if name in SEED_FEMALE else 0, i)
            for i, name in enumerate(SEED_MEMBERS, start=1)
        ],
    )


def _slot_count(mode: str, expr: str) -> int:
    """⚠️ blank 模式的 expr 是字面欄標題，不能餵給 expand_range。"""
    return len(blank_labels(expr) if mode == MODE_BLANK else expand_range(expr))


def _seed_template(conn: sqlite3.Connection, template_name: str) -> None:
    if conn.execute("SELECT 1 FROM Rota_Template LIMIT 1").fetchone():
        return

    cur = conn.execute(
        "INSERT INTO Rota_Template(name, created_at, note) VALUES (?, ?, ?)",
        (template_name, _now(), "程式內建的起始模板，請改成貴單位的實際規則"),
    )
    template_id = cur.lastrowid

    for order, (name, mode, expr, rests, header, note, weight) in enumerate(
        SEED_GROUPS, start=1
    ):
        cur = conn.execute(
            "INSERT INTO T_Group"
            "(template_id, name, mode, range_expr, header_before, "
            "note, col_weight, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (template_id, name, mode, expr, 1 if header else 0, note, weight, order),
        )
        group_id = cur.lastrowid
        rest_set = set(rests)
        conn.executemany(
            "INSERT INTO T_Slot(group_id, seq, is_rest, code_override) "
            "VALUES (?, ?, ?, NULL)",
            [
                (group_id, seq, 1 if seq in rest_set else 0)
                for seq in range(1, _slot_count(mode, expr) + 1)
            ],
        )
