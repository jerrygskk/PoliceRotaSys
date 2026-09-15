"""規則版本的讀寫與草稿↔啟用狀態機（DEVELOPER.md §3）。

狀態只有兩種：``草稿``（可改可刪）與 ``啟用``（鎖死）。單向不可逆。

⚠️ 「不可修改」的保證在 ``db_schema.py`` 的 trigger，不在這裡。本模組只是
讓正常流程好寫；就算有人繞過它直接下 SQL，資料庫層一樣會 ABORT。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from lib.rota import MODE_BLANK, Group, Slot, blank_labels, expand_range

DRAFT = "草稿"
ACTIVE = "啟用"
MAX_DRAFTS = 3


class RulesetError(RuntimeError):
    """流程錯誤（草稿超量、重複啟用等）。訊息面向使用者。"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# 查詢
# --------------------------------------------------------------------------

def list_versions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """草稿在前、啟用版本依版號由新到舊。"""
    return conn.execute(
        "SELECT * FROM Ruleset_Version "
        "ORDER BY CASE status WHEN ? THEN 0 ELSE 1 END, "
        "         version_no DESC, version_id DESC",
        (DRAFT,),
    ).fetchall()


def drafts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM Ruleset_Version WHERE status = ? ORDER BY version_id",
        (DRAFT,),
    ).fetchall()


def latest_active(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """★ 最新 = 啟用中版號最大者。

    ⚠️ **用算的，不存 is_latest 欄位**。存欄位的話每次發新版都要記得關掉舊
    的 flag，漏關一次就有兩個「最新」，不報錯、極難發現。
    """
    return conn.execute(
        "SELECT * FROM Ruleset_Version WHERE status = ? "
        "ORDER BY version_no DESC LIMIT 1",
        (ACTIVE,),
    ).fetchone()


# --------------------------------------------------------------------------
# 草稿
# --------------------------------------------------------------------------

def _assert_draft_room(conn: sqlite3.Connection) -> None:
    if len(drafts(conn)) >= MAX_DRAFTS:
        raise RulesetError(f"草稿最多 {MAX_DRAFTS} 份，請先刪掉不要的")


def create_draft(
    conn: sqlite3.Connection, ruleset_id: int, draft_name: str, note: str = ""
) -> int:
    _assert_draft_room(conn)
    cur = conn.execute(
        "INSERT INTO Ruleset_Version"
        "(ruleset_id, draft_name, version_no, status, created_at, note) "
        "VALUES (?, ?, NULL, ?, ?, ?)",
        (ruleset_id, draft_name, DRAFT, _now(), note),
    )
    conn.commit()
    return cur.lastrowid


def copy_to_draft(
    conn: sqlite3.Connection, version_id: int, draft_name: str
) -> int:
    """把既有版本（通常是已啟用的）複製成新草稿。

    這是「改已啟用規則」的唯一途徑——啟用版本本身動不了。
    """
    source = conn.execute(
        "SELECT * FROM Ruleset_Version WHERE version_id = ?", (version_id,)
    ).fetchone()
    if source is None:
        raise RulesetError("找不到要複製的版本")

    new_id = create_draft(conn, source["ruleset_id"], draft_name)
    for group in conn.execute(
        "SELECT * FROM RV_Group WHERE version_id = ? ORDER BY sort_order",
        (version_id,),
    ).fetchall():
        cur = conn.execute(
            "INSERT INTO RV_Group"
            "(version_id, name, mode, range_expr, rest_code, header_before, "
            "sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                new_id, group["name"], group["mode"], group["range_expr"],
                group["rest_code"], group["header_before"], group["sort_order"],
            ),
        )
        new_group_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO RV_Slot"
            "(version_id, group_id, seq, is_rest, code_override) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (new_id, new_group_id, s["seq"], s["is_rest"], s["code_override"])
                for s in conn.execute(
                    "SELECT * FROM RV_Slot WHERE group_id = ? ORDER BY seq",
                    (group["group_id"],),
                ).fetchall()
            ],
        )
    conn.commit()
    return new_id


def delete_draft(conn: sqlite3.Connection, version_id: int) -> None:
    """刪草稿。啟用版本會被 trigger 擋下來。"""
    conn.execute("DELETE FROM RV_Slot WHERE version_id = ?", (version_id,))
    conn.execute("DELETE FROM RV_Group WHERE version_id = ?", (version_id,))
    conn.execute(
        "DELETE FROM Ruleset_Version WHERE version_id = ?", (version_id,)
    )
    conn.commit()


# --------------------------------------------------------------------------
# 啟用
# --------------------------------------------------------------------------

def next_version_no(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT MAX(version_no) AS n FROM Ruleset_Version WHERE status = ?",
        (ACTIVE,),
    ).fetchone()
    return (row["n"] or 0) + 1


def activate(conn: sqlite3.Connection, version_id: int) -> int:
    """把草稿啟用並配版號。回傳配到的版號。

    ⚠️ 版號在**這一刻**才配，不是建立草稿時。草稿先占號的話，所長只挑一個、
    其餘刪掉，版號就會跳號（v1 之後直接 v4），半年後看到會以為漏了版本。
    """
    row = conn.execute(
        "SELECT status FROM Ruleset_Version WHERE version_id = ?", (version_id,)
    ).fetchone()
    if row is None:
        raise RulesetError("找不到該版本")
    if row["status"] != DRAFT:
        raise RulesetError("這個版本已經啟用了")
    if not conn.execute(
        "SELECT 1 FROM RV_Group WHERE version_id = ? LIMIT 1", (version_id,)
    ).fetchone():
        raise RulesetError("這份草稿沒有任何番組，不能啟用")

    version_no = next_version_no(conn)
    conn.execute(
        "UPDATE Ruleset_Version SET status = ?, version_no = ?, activated_at = ? "
        "WHERE version_id = ?",
        (ACTIVE, version_no, _now(), version_id),
    )
    conn.commit()
    return version_no


# --------------------------------------------------------------------------
# 載入成演算法用的 Group
# --------------------------------------------------------------------------

def load_groups(conn: sqlite3.Connection, version_id: int) -> list[Group]:
    """把某一版規則讀成 :class:`lib.rota.Group`，供排班推算使用。

    ``code_override`` 在這裡套用——展開結果是預設，覆寫蓋掉它。
    """
    out: list[Group] = []
    for grow in conn.execute(
        "SELECT * FROM RV_Group WHERE version_id = ? ORDER BY sort_order, group_id",
        (version_id,),
    ).fetchall():
        codes = (
            blank_labels(grow["range_expr"])
            if grow["mode"] == MODE_BLANK
            else expand_range(grow["range_expr"])
        )
        slots = []
        for srow in conn.execute(
            "SELECT * FROM RV_Slot WHERE group_id = ? ORDER BY seq",
            (grow["group_id"],),
        ).fetchall():
            seq = srow["seq"]
            if not 1 <= seq <= len(codes):
                raise RulesetError(
                    f"「{grow['name']}」的第 {seq} 格超出範圍式 "
                    f"{grow['range_expr']} 的長度"
                )
            slots.append(
                Slot(
                    seq=seq,
                    code=srow["code_override"] or codes[seq - 1],
                    is_rest=bool(srow["is_rest"]),
                )
            )
        if len(slots) != len(codes):
            raise RulesetError(
                f"「{grow['name']}」有 {len(slots)} 格，但範圍式應展開成 "
                f"{len(codes)} 格"
            )
        out.append(Group(name=grow["name"], mode=grow["mode"], slots=tuple(slots)))
    return out


def group_rest_code(conn: sqlite3.Connection, group_id: int) -> str:
    row = conn.execute(
        "SELECT rest_code FROM RV_Group WHERE group_id = ?", (group_id,)
    ).fetchone()
    return row["rest_code"] if row else "00"
