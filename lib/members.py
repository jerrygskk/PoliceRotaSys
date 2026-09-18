"""人員名單的資料存取（人員分頁與新增／修改彈窗共用）。

比照 PoliceDocSys 設定頁的人員管理：軟刪除（離職不真刪）、`sort_order` 手調順序。
⚠️ 這裡的順序只是名單與下拉的顯示順序，**不是**輪番的番號——誰站哪一格是
產月表時配的（DEVELOPER §3）。
"""
from __future__ import annotations

import sqlite3


def list_members(conn: sqlite3.Connection) -> list[tuple[int, str, bool, bool]]:
    """依 sort_order 回傳 [(member_id, name, active, female), ...]。"""
    rows = conn.execute(
        "SELECT member_id, name, active, female FROM Member "
        "ORDER BY sort_order, member_id"
    ).fetchall()
    return [(r[0], r[1], bool(r[2]), bool(r[3])) for r in rows]


def add_member(conn: sqlite3.Connection, name: str, female: bool, active: bool = True) -> int:
    """新增人員，排到最前（sort_order 取最小值 -1；空表為 1）。由呼叫端 commit。"""
    row = conn.execute("SELECT MIN(sort_order) FROM Member").fetchone()
    sort_order = (row[0] - 1) if row and row[0] is not None else 1
    cur = conn.execute(
        "INSERT INTO Member(name, active, female, sort_order) VALUES (?, ?, ?, ?)",
        (name, int(active), int(female), sort_order),
    )
    return cur.lastrowid


def update_member(conn: sqlite3.Connection, member_id: int, name: str,
                  female: bool, active: bool) -> None:
    """修改姓名／女警／在職。由呼叫端 commit。"""
    conn.execute(
        "UPDATE Member SET name = ?, female = ?, active = ? WHERE member_id = ?",
        (name, int(female), int(active), member_id),
    )


def save_order(conn: sqlite3.Connection, member_ids: list[int]) -> None:
    """把畫面上的順序寫回 sort_order（1 起連續整數）並 commit。"""
    conn.executemany(
        "UPDATE Member SET sort_order = ? WHERE member_id = ?",
        [(i, mid) for i, mid in enumerate(member_ids, start=1)],
    )
    conn.commit()


def parse_add_position(text: str, existing_count: int) -> tuple[bool, int | None]:
    """新增對話框「順序」欄位驗證（自 PoliceDocSys `_parseAddPosition` 照抄）。

    留空＝合法、回 (True, None)（套用預設行為：塞最前）。
    合法範圍 1～existing_count+1（新增後清單會變 existing_count+1 筆）。
    回傳 (is_valid, 0-based 目標索引或 None)；不合法回 (False, None)。
    """
    text = (text or "").strip()
    if text == "":
        return True, None
    if not text.isdigit():
        return False, None
    n = int(text)
    if not (1 <= n <= existing_count + 1):
        return False, None
    return True, n - 1


def parse_seq_move_target(text: str, row_count: int) -> int | None:
    """既有列「序號」欄編輯驗證（自 PoliceDocSys `_parseSeqMoveTarget` 照抄）。

    回傳 0-based 目標索引；不合法（非數字／超出 1~row_count）回 None。
    """
    text = (text or "").strip()
    if not text.isdigit():
        return None
    n = int(text)
    if not (1 <= n <= row_count):
        return None
    return n - 1
