"""輪番模板的讀寫（DEVELOPER.md §3）。

模板就是**設定**：想改就改、想刪就刪，沒有草稿／啟用／版號這回事。

⚠️ 改模板**不會影響已經產生的月表**——月表在產出時就把當時的規則拷成
快照了（見 ``lib/plan.py``）。這也是這一版把「規則版本鎖死」整套拿掉的
理由：舊月表不再指著模板，鎖就沒有存在的必要。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from lib.rota import (
    MODE_BLANK, MODE_FIXED, MODE_ROTATE, MODES, Group, GroupError, Slot,
    blank_labels, expand_range, validate_groups,
)

# 欄寬權重由程式決定，不給使用者調（維護者裁示：屬於程式面的設定）。
# 輪番 1.1、固定番與幹部 1.2；手寫的空白欄暫用 1.2。
WEIGHT_BY_MODE = {MODE_ROTATE: 1.1, MODE_FIXED: 1.2, MODE_BLANK: 1.2}

MODE_LABELS = {MODE_ROTATE: "輪番", MODE_FIXED: "固定番", MODE_BLANK: "空白欄"}

# 群組名稱字數上限（維護者裁示 2026-09-16）。實測（微軟正黑體 14pt、125%、1440 寬）：
# 輪番群組的勤休卡片標題列 7 字以內版面不動，8～12 字擠窄左側模板卡片，
# 13 字以上把視窗撐寬。名稱也直書印在月表欄標題，太長那邊同樣擠不下。
MAX_GROUP_NAME_LEN = 7


class TemplateError(RuntimeError):
    """流程錯誤（名稱重複、格位不存在等）。訊息面向使用者，可直接顯示。"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# 模板
# --------------------------------------------------------------------------

def list_templates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """依建立順序回傳所有模板。"""
    return conn.execute(
        "SELECT * FROM Rota_Template ORDER BY template_id"
    ).fetchall()


def get_template(conn: sqlite3.Connection, template_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM Rota_Template WHERE template_id = ?", (template_id,)
    ).fetchone()
    if row is None:
        raise TemplateError("找不到該模板")
    return row


def default_template_name(conn: sqlite3.Connection) -> str:
    """新模板的預設名稱：模板1、模板2……取第一個還沒被用掉的。"""
    used = {row["name"] for row in list_templates(conn)}
    n = 1
    while f"模板{n}" in used:
        n += 1
    return f"模板{n}"


def _assert_unique_template_name(
    conn: sqlite3.Connection, name: str, template_id: int | None = None
) -> None:
    if not name:
        raise TemplateError("模板名稱不可空白")
    row = conn.execute(
        "SELECT template_id FROM Rota_Template WHERE name = ?", (name,)
    ).fetchone()
    if row is not None and row["template_id"] != template_id:
        raise TemplateError(f"已經有叫「{name}」的模板")


def create_template(conn: sqlite3.Connection, name: str, note: str = "") -> int:
    name = name.strip()
    _assert_unique_template_name(conn, name)
    cur = conn.execute(
        "INSERT INTO Rota_Template(name, created_at, note) VALUES (?, ?, ?)",
        (name, _now(), note),
    )
    conn.commit()
    return cur.lastrowid


def rename_template(conn: sqlite3.Connection, template_id: int, name: str) -> None:
    get_template(conn, template_id)
    name = name.strip()
    _assert_unique_template_name(conn, name, template_id)
    conn.execute(
        "UPDATE Rota_Template SET name = ? WHERE template_id = ?", (name, template_id)
    )
    conn.commit()


def copy_template(conn: sqlite3.Connection, template_id: int, name: str) -> int:
    """整份複製。要大改又想留原樣時用這個（畫面上的「複製一份」）。"""
    source = get_template(conn, template_id)
    new_id = create_template(conn, name, source["note"])
    for group in group_rows(conn, template_id):
        cur = conn.execute(
            "INSERT INTO T_Group(template_id, name, mode, range_expr, "
            "header_before, reverse_order, note, col_weight, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id, group["name"], group["mode"], group["range_expr"],
                group["header_before"], group["reverse_order"], group["note"],
                group["col_weight"], group["sort_order"],
            ),
        )
        conn.executemany(
            "INSERT INTO T_Slot(group_id, seq, is_rest, code_override) "
            "VALUES (?, ?, ?, ?)",
            [
                (cur.lastrowid, s["seq"], s["is_rest"], s["code_override"])
                for s in slot_rows(conn, group["group_id"])
            ],
        )
    conn.commit()
    return new_id


def delete_template(conn: sqlite3.Connection, template_id: int) -> None:
    """刪整份模板（群組與槽位連帶清掉）。

    ⚠️ 用過這份模板的月表**不受影響**，它們有自己的快照。
    """
    for group in group_rows(conn, template_id):
        conn.execute("DELETE FROM T_Slot WHERE group_id = ?", (group["group_id"],))
    conn.execute("DELETE FROM T_Group WHERE template_id = ?", (template_id,))
    conn.execute("DELETE FROM Rota_Template WHERE template_id = ?", (template_id,))
    conn.commit()


# --------------------------------------------------------------------------
# 載入成演算法用的 Group
# --------------------------------------------------------------------------

def load_groups(conn: sqlite3.Connection, template_id: int) -> list[Group]:
    """把一份模板讀成 :class:`lib.rota.Group`，供排班推算使用。

    ``code_override`` 在這裡套用——展開結果是預設，覆寫蓋掉它。
    """
    out: list[Group] = []
    for grow in group_rows(conn, template_id):
        codes = (
            blank_labels(grow["range_expr"])
            if grow["mode"] == MODE_BLANK
            else expand_range(grow["range_expr"])
        )
        slots = []
        for srow in slot_rows(conn, grow["group_id"]):
            seq = srow["seq"]
            if not 1 <= seq <= len(codes):
                raise TemplateError(
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
            raise TemplateError(
                f"「{grow['name']}」有 {len(slots)} 格，但範圍式應展開成 "
                f"{len(codes)} 格"
            )
        out.append(Group(name=grow["name"], mode=grow["mode"], slots=tuple(slots)))
    return out


# --------------------------------------------------------------------------
# 群組編輯（輪番設定分頁）
# --------------------------------------------------------------------------

def _group_row(conn: sqlite3.Connection, group_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM T_Group WHERE group_id = ?", (group_id,)
    ).fetchone()
    if row is None:
        raise TemplateError("找不到該群組")
    return row


def group_rows(conn: sqlite3.Connection, template_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM T_Group WHERE template_id = ? ORDER BY sort_order, group_id",
        (template_id,),
    ).fetchall()


def slot_rows(conn: sqlite3.Connection, group_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM T_Slot WHERE group_id = ? ORDER BY seq", (group_id,)
    ).fetchall()


def default_group_name(conn: sqlite3.Connection, template_id: int) -> str:
    """新群組的預設名稱：群組1、群組2……取第一個還沒被用掉的。"""
    used = {row["name"] for row in group_rows(conn, template_id)}
    n = 1
    while f"群組{n}" in used:
        n += 1
    return f"群組{n}"


def expand_codes(mode: str, expr: str) -> tuple[str, ...]:
    """依模式展開：空白欄是逗號分隔的欄標題，其餘是範圍式。語法錯誤 raise RangeError。"""
    if mode not in MODES:
        raise TemplateError(f"未知的模式：{mode}")
    return blank_labels(expr) if mode == MODE_BLANK else expand_range(expr)


def normalize_expr(mode: str, expr: str) -> str:
    """存檔前整理範圍式：去頭尾空白，英文一律轉大寫。

    ⚠️ 展開時本來就不分大小寫（``a-f`` 展開成 ``A``…``F``），但存進資料庫的
    範圍式若保留小寫，群組表就會顯示 ``a-f`` 而月表印 ``A``，兩邊對不起來。
    空白欄的範圍式是字面欄標題，照原樣保留，不轉大小寫。
    """
    expr = expr.strip()
    return expr if mode == MODE_BLANK else expr.upper()


def _regenerate_slots(conn: sqlite3.Connection, group_id: int, count: int) -> None:
    """重新展開槽位。⚠️ 已設好的休與自訂代碼一律清空（DEVELOPER §3）。"""
    conn.execute("DELETE FROM T_Slot WHERE group_id = ?", (group_id,))
    conn.executemany(
        "INSERT INTO T_Slot(group_id, seq, is_rest, code_override) "
        "VALUES (?, ?, 0, NULL)",
        [(group_id, seq) for seq in range(1, count + 1)],
    )


def _assert_unique_name(
    conn: sqlite3.Connection, template_id: int, name: str, group_id: int | None = None
) -> None:
    if not name:
        raise TemplateError("群組名稱不可空白")
    if len(name) > MAX_GROUP_NAME_LEN:
        raise TemplateError(f"群組名稱最多 {MAX_GROUP_NAME_LEN} 個字")
    row = conn.execute(
        "SELECT group_id FROM T_Group WHERE template_id = ? AND name = ?",
        (template_id, name),
    ).fetchone()
    if row is not None and row["group_id"] != group_id:
        raise TemplateError(f"已經有叫「{name}」的群組")


def add_group(
    conn: sqlite3.Connection, template_id: int, name: str, mode: str, expr: str,
    header_before: bool = True, note: str = "", reverse_order: bool = False,
) -> int:
    """新增群組並展開槽位，排到最後。"""
    get_template(conn, template_id)
    name = name.strip()
    expr = normalize_expr(mode, expr)
    _assert_unique_name(conn, template_id, name)
    codes = expand_codes(mode, expr)
    row = conn.execute(
        "SELECT MAX(sort_order) AS m FROM T_Group WHERE template_id = ?",
        (template_id,),
    ).fetchone()
    cur = conn.execute(
        "INSERT INTO T_Group(template_id, name, mode, range_expr, header_before, "
        "reverse_order, note, col_weight, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (template_id, name, mode, expr, int(header_before), int(reverse_order), note,
         WEIGHT_BY_MODE[mode], (row["m"] or 0) + 1),
    )
    group_id = cur.lastrowid
    _regenerate_slots(conn, group_id, len(codes))
    conn.commit()
    return group_id


def update_group(
    conn: sqlite3.Connection, group_id: int, name: str, mode: str, expr: str,
    header_before: bool, note: str, reverse_order: bool = False,
) -> bool:
    """修改群組。模式或範圍有變時重新展開槽位並回傳 True（休與自訂代碼已清空）。"""
    old = _group_row(conn, group_id)
    name = name.strip()
    expr = normalize_expr(mode, expr)
    _assert_unique_name(conn, old["template_id"], name, group_id)
    codes = expand_codes(mode, expr)
    reshaped = mode != old["mode"] or expr != old["range_expr"]
    weight = WEIGHT_BY_MODE[mode] if mode != old["mode"] else old["col_weight"]
    conn.execute(
        "UPDATE T_Group SET name = ?, mode = ?, range_expr = ?, header_before = ?, "
        "reverse_order = ?, note = ?, col_weight = ? WHERE group_id = ?",
        (name, mode, expr, int(header_before), int(reverse_order), note, weight, group_id),
    )
    if reshaped:
        _regenerate_slots(conn, group_id, len(codes))
    conn.commit()
    return reshaped


def delete_group(conn: sqlite3.Connection, group_id: int) -> None:
    _group_row(conn, group_id)
    conn.execute("DELETE FROM T_Slot WHERE group_id = ?", (group_id,))
    conn.execute("DELETE FROM T_Group WHERE group_id = ?", (group_id,))
    conn.commit()


def save_group_order(conn: sqlite3.Connection, group_ids: list[int]) -> None:
    """把畫面上的群組順序寫回 sort_order（1 起連續整數）。"""
    conn.executemany(
        "UPDATE T_Group SET sort_order = ? WHERE group_id = ?",
        [(i, gid) for i, gid in enumerate(group_ids, start=1)],
    )
    conn.commit()


def toggle_rest(conn: sqlite3.Connection, group_id: int, seq: int) -> bool:
    """切換某格是否為休，回傳切換後的狀態。只有輪番群組有休。"""
    group = _group_row(conn, group_id)
    if group["mode"] != MODE_ROTATE:
        raise TemplateError("只有輪番群組可以設定休")
    row = conn.execute(
        "SELECT is_rest FROM T_Slot WHERE group_id = ? AND seq = ?", (group_id, seq)
    ).fetchone()
    if row is None:
        raise TemplateError(f"第 {seq} 格不存在")
    new = 0 if row["is_rest"] else 1
    conn.execute(
        "UPDATE T_Slot SET is_rest = ? WHERE group_id = ? AND seq = ?",
        (new, group_id, seq),
    )
    conn.commit()
    return bool(new)


def set_code_override(
    conn: sqlite3.Connection, group_id: int, seq: int, code: str | None
) -> None:
    """自訂某格代碼；空白或與展開結果相同＝取消自訂（回到預設）。"""
    group = _group_row(conn, group_id)
    if group["mode"] == MODE_BLANK:
        raise TemplateError("空白欄沒有代碼可以自訂")
    codes = expand_codes(group["mode"], group["range_expr"])
    if not 1 <= seq <= len(codes):
        raise TemplateError(f"第 {seq} 格不存在")
    code = (code or "").strip()
    value = None if code in ("", codes[seq - 1]) else code
    conn.execute(
        "UPDATE T_Slot SET code_override = ? WHERE group_id = ? AND seq = ?",
        (value, group_id, seq),
    )
    conn.commit()


def check_template(conn: sqlite3.Connection, template_id: int) -> None:
    """「檢查規則」鈕：跨群組檢查（撞號、整組都是休、空範圍）。有問題 raise TemplateError。"""
    if not group_rows(conn, template_id):
        raise TemplateError("這份模板還沒有任何群組")
    try:
        validate_groups(load_groups(conn, template_id))
    except GroupError as exc:
        raise TemplateError(str(exc)) from exc
