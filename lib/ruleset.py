"""規則版本的讀寫與草稿↔啟用狀態機（DEVELOPER.md §3）。

狀態只有兩種：``草稿``（可改可刪）與 ``啟用``（鎖死）。單向不可逆。

⚠️ 「不可修改」的保證在 ``db_schema.py`` 的 trigger，不在這裡。本模組只是
讓正常流程好寫；就算有人繞過它直接下 SQL，資料庫層一樣會 ABORT。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from lib.db_schema import MAX_DRAFTS
from lib.rota import (
    MODE_BLANK, MODE_FIXED, MODE_ROTATE, MODES, Group, GroupError, Slot,
    blank_labels, expand_range, validate_groups,
)

DRAFT = "草稿"
ACTIVE = "啟用"
# 上限與 trigger 同一來源，見 lib/db_schema.py


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
            "(version_id, name, mode, range_expr, header_before, "
            "note, col_weight, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id, group["name"], group["mode"], group["range_expr"],
                group["header_before"], group["note"],
                group["col_weight"], group["sort_order"],
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
        raise RulesetError("這份草稿沒有任何群組，不能啟用")
    try:
        validate_groups(load_groups(conn, version_id))
    except GroupError as exc:
        raise RulesetError(f"這份草稿還有問題，不能啟用：{exc}") from exc

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


# --------------------------------------------------------------------------
# 草稿編輯（輪番設定分頁）
# --------------------------------------------------------------------------
#
# ⚠️ 「啟用版本不可改」由 db_schema 的 trigger 保證；這裡另外先查一次，
# 只是為了給使用者看得懂的訊息，不是唯一的防線。

# 欄寬權重由程式決定，不給使用者調（維護者裁示：屬於程式面的設定）。
# 輪番 1.1、固定番與幹部 1.2；手寫的空白欄暫用 1.2。
WEIGHT_BY_MODE = {MODE_ROTATE: 1.1, MODE_FIXED: 1.2, MODE_BLANK: 1.2}

MODE_LABELS = {MODE_ROTATE: "輪番", MODE_FIXED: "固定", MODE_BLANK: "空白欄"}


def _assert_draft(conn: sqlite3.Connection, version_id: int) -> None:
    row = conn.execute(
        "SELECT status FROM Ruleset_Version WHERE version_id = ?", (version_id,)
    ).fetchone()
    if row is None:
        raise RulesetError("找不到該版本")
    if row["status"] != DRAFT:
        raise RulesetError("已啟用的規則不可修改，請先複製為草稿")


def _group_row(conn: sqlite3.Connection, group_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM RV_Group WHERE group_id = ?", (group_id,)
    ).fetchone()
    if row is None:
        raise RulesetError("找不到該群組")
    return row


def rename_draft(conn: sqlite3.Connection, version_id: int, draft_name: str) -> None:
    _assert_draft(conn, version_id)
    draft_name = draft_name.strip()
    if not draft_name:
        raise RulesetError("草稿名稱不可空白")
    conn.execute(
        "UPDATE Ruleset_Version SET draft_name = ? WHERE version_id = ?",
        (draft_name, version_id),
    )
    conn.commit()


def group_rows(conn: sqlite3.Connection, version_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM RV_Group WHERE version_id = ? ORDER BY sort_order, group_id",
        (version_id,),
    ).fetchall()


def slot_rows(conn: sqlite3.Connection, group_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM RV_Slot WHERE group_id = ? ORDER BY seq", (group_id,)
    ).fetchall()


def default_group_name(conn: sqlite3.Connection, version_id: int) -> str:
    """新群組的預設名稱：群組1、群組2……取第一個還沒被用掉的。"""
    used = {row["name"] for row in group_rows(conn, version_id)}
    n = 1
    while f"群組{n}" in used:
        n += 1
    return f"群組{n}"


def expand_codes(mode: str, expr: str) -> tuple[str, ...]:
    """依模式展開：空白欄是逗號分隔的欄標題，其餘是範圍式。語法錯誤 raise RangeError。"""
    if mode not in MODES:
        raise RulesetError(f"未知的模式：{mode}")
    return blank_labels(expr) if mode == MODE_BLANK else expand_range(expr)


def _regenerate_slots(
    conn: sqlite3.Connection, version_id: int, group_id: int, count: int
) -> None:
    """重新展開槽位。⚠️ 已設好的休與自訂代碼一律清空（DEVELOPER §3）。"""
    conn.execute("DELETE FROM RV_Slot WHERE group_id = ?", (group_id,))
    conn.executemany(
        "INSERT INTO RV_Slot(version_id, group_id, seq, is_rest, code_override) "
        "VALUES (?, ?, ?, 0, NULL)",
        [(version_id, group_id, seq) for seq in range(1, count + 1)],
    )


def _assert_unique_name(
    conn: sqlite3.Connection, version_id: int, name: str, group_id: int | None = None
) -> None:
    if not name:
        raise RulesetError("群組名稱不可空白")
    row = conn.execute(
        "SELECT group_id FROM RV_Group WHERE version_id = ? AND name = ?",
        (version_id, name),
    ).fetchone()
    if row is not None and row["group_id"] != group_id:
        raise RulesetError(f"已經有叫「{name}」的群組")


def add_group(
    conn: sqlite3.Connection, version_id: int, name: str, mode: str, expr: str,
    header_before: bool = True, note: str = "",
) -> int:
    """新增群組並展開槽位，排到最後。"""
    _assert_draft(conn, version_id)
    name = name.strip()
    expr = expr.strip()
    _assert_unique_name(conn, version_id, name)
    codes = expand_codes(mode, expr)
    row = conn.execute(
        "SELECT MAX(sort_order) AS m FROM RV_Group WHERE version_id = ?", (version_id,)
    ).fetchone()
    cur = conn.execute(
        "INSERT INTO RV_Group(version_id, name, mode, range_expr, header_before, "
        "note, col_weight, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (version_id, name, mode, expr, int(header_before), note,
         WEIGHT_BY_MODE[mode], (row["m"] or 0) + 1),
    )
    group_id = cur.lastrowid
    _regenerate_slots(conn, version_id, group_id, len(codes))
    conn.commit()
    return group_id


def update_group(
    conn: sqlite3.Connection, group_id: int, name: str, mode: str, expr: str,
    header_before: bool, note: str,
) -> bool:
    """修改群組。模式或範圍有變時重新展開槽位並回傳 True（休與自訂代碼已清空）。"""
    old = _group_row(conn, group_id)
    version_id = old["version_id"]
    _assert_draft(conn, version_id)
    name = name.strip()
    expr = expr.strip()
    _assert_unique_name(conn, version_id, name, group_id)
    codes = expand_codes(mode, expr)
    reshaped = mode != old["mode"] or expr != old["range_expr"]
    weight = WEIGHT_BY_MODE[mode] if mode != old["mode"] else old["col_weight"]
    conn.execute(
        "UPDATE RV_Group SET name = ?, mode = ?, range_expr = ?, header_before = ?, "
        "note = ?, col_weight = ? WHERE group_id = ?",
        (name, mode, expr, int(header_before), note, weight, group_id),
    )
    if reshaped:
        _regenerate_slots(conn, version_id, group_id, len(codes))
    conn.commit()
    return reshaped


def delete_group(conn: sqlite3.Connection, group_id: int) -> None:
    _assert_draft(conn, _group_row(conn, group_id)["version_id"])
    conn.execute("DELETE FROM RV_Slot WHERE group_id = ?", (group_id,))
    conn.execute("DELETE FROM RV_Group WHERE group_id = ?", (group_id,))
    conn.commit()


def save_group_order(conn: sqlite3.Connection, group_ids: list[int]) -> None:
    """把畫面上的群組順序寫回 sort_order（1 起連續整數）。"""
    if group_ids:
        _assert_draft(conn, _group_row(conn, group_ids[0])["version_id"])
    conn.executemany(
        "UPDATE RV_Group SET sort_order = ? WHERE group_id = ?",
        [(i, gid) for i, gid in enumerate(group_ids, start=1)],
    )
    conn.commit()


def toggle_rest(conn: sqlite3.Connection, group_id: int, seq: int) -> bool:
    """切換某格是否為休，回傳切換後的狀態。只有輪番群組有休。"""
    group = _group_row(conn, group_id)
    _assert_draft(conn, group["version_id"])
    if group["mode"] != MODE_ROTATE:
        raise RulesetError("只有輪番群組可以設定休")
    row = conn.execute(
        "SELECT is_rest FROM RV_Slot WHERE group_id = ? AND seq = ?", (group_id, seq)
    ).fetchone()
    if row is None:
        raise RulesetError(f"第 {seq} 格不存在")
    new = 0 if row["is_rest"] else 1
    conn.execute(
        "UPDATE RV_Slot SET is_rest = ? WHERE group_id = ? AND seq = ?",
        (new, group_id, seq),
    )
    conn.commit()
    return bool(new)


def set_code_override(
    conn: sqlite3.Connection, group_id: int, seq: int, code: str | None
) -> None:
    """自訂某格代碼；空白或與展開結果相同＝取消自訂（回到預設）。"""
    group = _group_row(conn, group_id)
    _assert_draft(conn, group["version_id"])
    if group["mode"] == MODE_BLANK:
        raise RulesetError("空白欄沒有代碼可以自訂")
    codes = expand_codes(group["mode"], group["range_expr"])
    if not 1 <= seq <= len(codes):
        raise RulesetError(f"第 {seq} 格不存在")
    code = (code or "").strip()
    value = None if code in ("", codes[seq - 1]) else code
    conn.execute(
        "UPDATE RV_Slot SET code_override = ? WHERE group_id = ? AND seq = ?",
        (value, group_id, seq),
    )
    conn.commit()


def check_version(conn: sqlite3.Connection, version_id: int) -> None:
    """「檢查規則」鈕與啟用前：跨群組檢查（撞號、整組都是休、空範圍）。有問題 raise RulesetError。"""
    if not group_rows(conn, version_id):
        raise RulesetError("這份規則還沒有任何群組")
    try:
        validate_groups(load_groups(conn, version_id))
    except GroupError as exc:
        raise RulesetError(str(exc)) from exc
