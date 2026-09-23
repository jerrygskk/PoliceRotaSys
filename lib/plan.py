"""月表：建立、接續、載入、組版（DEVELOPER.md §3）。

這是「產生月表」的核心，**不含任何 Qt**——分頁只負責把它包起來給人點。

產生月表只有兩條路，畫面上就是兩顆鈕（維護者裁示，不做條件判斷）：

  接續上月  沿用上個月的規則與名單，番號從上月最後一天接著推
  自訂起始  選一份模板，承辦人自己指定 1 日的起始格位

⚠️ **月表一旦產生就跟設定區脫勾**：規則與姓名在產出當下複製成 ``snapshot``
存進去。之後改模板、改名字、刪人，都不會動到已經產生的月表；重印一律讀
快照，不重算、不回頭讀設定區。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from lib import template
from lib.db_utils import KEY_TITLE_FORMAT, get_setting
from lib.layout_model import (
    DEFAULT_TITLE_FORMAT,
    Entry,
    Section,
    Sheet,
    build_sheet,
    parse_note,
)
from lib.rota import (
    MODE_BLANK, MODE_ROTATE, Group, Slot, month_days, rota_month,
)

ORIGIN_CHAIN = "接續上月"
ORIGIN_CUSTOM = "自訂起始"


class PlanError(RuntimeError):
    """流程錯誤。訊息面向使用者，可直接顯示。"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _prev_year_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


# --------------------------------------------------------------------------
# 查詢
# --------------------------------------------------------------------------

def get_plan(conn: sqlite3.Connection, year: int, month: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM Month_Plan WHERE year = ? AND month = ?", (year, month)
    ).fetchone()


def list_plans(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """由新到舊。"""
    return conn.execute(
        "SELECT plan_id, year, month, origin, created_at FROM Month_Plan "
        "ORDER BY year DESC, month DESC"
    ).fetchall()


def previous_plan(
    conn: sqlite3.Connection, year: int, month: int
) -> sqlite3.Row | None:
    return get_plan(conn, *_prev_year_month(year, month))


def load_snapshot(conn: sqlite3.Connection, year: int, month: int) -> dict:
    """讀某月的快照。找不到月表就 raise。"""
    plan = get_plan(conn, year, month)
    if plan is None:
        raise PlanError(f"{year - 1911} 年 {month} 月還沒有月表")
    return json.loads(plan["snapshot"])


# --------------------------------------------------------------------------
# 快照
# --------------------------------------------------------------------------
#
# ⚠️ 快照存的是「當時長什麼樣」，不是「去哪裡查」：
#   * 姓名存字串，不存 member_id——存 id 就等於沒脫勾，改名或刪人會讓舊月表
#     跟著變，而且印出來看不出錯
#   * 代碼存展開並套用自訂後的結果，不存範圍式——範圍式要再展開一次才知道
#     長怎樣，而展開規則日後可能改
#   * 起始格位存格位不存番號：休沒有番號，存番號就分不出「休在第 6 格還是
#     第 7 格」，而這兩者隔天的結果完全不同

def _group_to_snapshot(row: sqlite3.Row, group: Group) -> dict:
    return {
        "name": group.name,
        "mode": group.mode,
        "header_before": bool(row["header_before"]),
        "reverse_order": bool(row["reverse_order"]),
        "code_position": row["code_position"],
        "col_weight": row["col_weight"],
        "note": row["note"],
        "slots": [
            {"seq": s.seq, "code": s.code, "is_rest": s.is_rest} for s in group.slots
        ],
        "members": [],
    }


def snapshot_to_group(data: dict) -> Group:
    """把快照裡的一個群組還原成排班演算法用的 :class:`lib.rota.Group`。"""
    return Group(
        name=data["name"],
        mode=data["mode"],
        slots=tuple(
            Slot(seq=s["seq"], code=s["code"], is_rest=s["is_rest"])
            for s in data["slots"]
        ),
    )


def build_snapshot(
    conn: sqlite3.Connection, template_id: int, seeds: dict[int, dict[int, int]]
) -> dict:
    """依模板與配對另存一份快照。``seeds`` 是 ``{group_id: {member_id: slot_seq}}``。"""
    tpl = template.get_template(conn, template_id)
    rows = template.group_rows(conn, template_id)
    groups = {g.name: g for g in template.load_groups(conn, template_id)}
    people = {
        row["member_id"]: (row["name"], bool(row["female"]))
        for row in conn.execute("SELECT member_id, name, female FROM Member")
    }

    out = {"template_name": tpl["name"], "groups": []}
    for row in rows:
        group = groups[row["name"]]
        data = _group_to_snapshot(row, group)
        for member_id, slot_seq in seeds.get(row["group_id"], {}).items():
            name, female = people.get(member_id, ("?", False))
            data["members"].append(
                {"name": name, "female": female, "slot_seq": slot_seq}
            )
        out["groups"].append(data)
    return out


# --------------------------------------------------------------------------
# 建立
# --------------------------------------------------------------------------

def _insert_plan(
    conn: sqlite3.Connection, year: int, month: int, origin: str, snapshot: dict,
    overwrite: bool = False,
) -> int:
    """寫入一個月的月表。overwrite=True 時先刪掉該月既有的月表。

    ⚠️ 刪舊與寫新在**同一個交易**裡：驗證都在呼叫這裡之前做完，這裡只剩兩條 SQL，
    中途出錯整筆回滾，不會出現「舊的刪了、新的沒寫進去」。
    """
    if get_plan(conn, year, month) is not None:
        if not overwrite:
            raise PlanError(f"{year - 1911} 年 {month} 月已經有月表了")
        conn.execute("DELETE FROM Month_Plan WHERE year = ? AND month = ?", (year, month))
    cur = conn.execute(
        "INSERT INTO Month_Plan(year, month, origin, created_at, snapshot) "
        "VALUES (?, ?, ?, ?, ?)",
        (year, month, origin, _now(),
         json.dumps(snapshot, ensure_ascii=False)),
    )
    conn.commit()
    return cur.lastrowid


def create_plan(
    conn: sqlite3.Connection,
    year: int,
    month: int,
    template_id: int,
    seeds: dict[int, dict[int, int]],
    overwrite: bool = False,
) -> int:
    """「自訂起始」：用一份模板加承辦人指定的起始格位建立月表。

    overwrite=True＝覆蓋該月既有月表（畫面先確認過；過去月份另外提醒）。
    """
    if not seeds:
        raise PlanError("沒有任何配對")
    _assert_seeds_complete(conn, template_id, seeds)
    snapshot = build_snapshot(conn, template_id, seeds)
    return _insert_plan(conn, year, month, ORIGIN_CUSTOM, snapshot, overwrite)


def chain_blocked_reason(
    conn: sqlite3.Connection, year: int, month: int
) -> str | None:
    """不能接續的原因；可以接續時回 ``None``。

    ⚠️ 只剩一條：上個月有沒有月表。規則變沒變不在這裡判斷——接續就是沿用
    上月那份快照，規則要換就走「自訂起始」（維護者裁示：給兩顆鈕就好，
    不做條件判斷）。
    """
    if previous_plan(conn, year, month) is None:
        prev_y, prev_m = _prev_year_month(year, month)
        return f"{prev_y - 1911} 年 {prev_m} 月沒有月表可以接續"   # 畫面一律民國
    return None


def can_chain(conn: sqlite3.Connection, year: int, month: int) -> bool:
    return chain_blocked_reason(conn, year, month) is None


def chained_snapshot(conn: sqlite3.Connection, year: int, month: int) -> dict:
    """把上月的快照推成本月的：規則與名單原封不動，起始格位往後推一個月。"""
    reason = chain_blocked_reason(conn, year, month)
    if reason:
        raise PlanError(reason)

    prev_y, prev_m = _prev_year_month(year, month)
    days = month_days(prev_y, prev_m)
    snapshot = load_snapshot(conn, prev_y, prev_m)

    for data in snapshot["groups"]:
        if data["mode"] != MODE_ROTATE:
            continue          # 固定番不隨日期前進
        cycle_len = len(data["slots"])
        for member in data["members"]:
            member["slot_seq"] = (member["slot_seq"] - 1 + days) % cycle_len + 1
    return snapshot


def create_chained_plan(
    conn: sqlite3.Connection, year: int, month: int, overwrite: bool = False
) -> int:
    """「接續上月」：番號從上月最後一天接著推，承辦人什麼都不用輸入。"""
    return _insert_plan(
        conn, year, month, ORIGIN_CHAIN, chained_snapshot(conn, year, month), overwrite
    )


def _assert_seeds_complete(
    conn: sqlite3.Connection, template_id: int, seeds: dict[int, dict[int, int]]
) -> None:
    """配對必須完整，且落在該模板的群組與格位範圍內。

    擋兩種錯：

      **配錯** 指到不存在的群組、或超出格數的格位
      **沒配完** 有格位沒人，或整個群組一個人都沒有

    ⚠️ 「沒配完不准按確定」不只是畫面的事。按鈕反灰擋不住（AGENTS.md §B），
    真正的 gate 要在資料進資料庫的這一道——漏了一格的月表，印出來那一欄
    就是空的，而承辦人不會知道是自己漏配還是程式壞了。
    """
    groups = {row["group_id"]: row for row in template.group_rows(conn, template_id)}
    loaded = {g.name: g for g in template.load_groups(conn, template_id)}

    for group_id, members in seeds.items():
        row = groups.get(group_id)
        if row is None:
            raise PlanError(f"群組 {group_id} 不屬於這份模板")
        cycle_len = loaded[row["name"]].cycle_len
        for slot_seq in members.values():
            if not 1 <= slot_seq <= cycle_len:
                raise PlanError(
                    f"「{row['name']}」的欄位 {slot_seq} 超出範圍"
                    f"（共 {cycle_len} 格）"
                )

    # ⚠️ 同一人不可同時在兩個群組（DEVELOPER §9 已排除的需求）。原本靠
    # Month_Seed 的唯一索引擋，改存快照後資料庫擋不到了，改在這裡擋。
    seen: dict[int, str] = {}
    for group_id, members in seeds.items():
        for member_id in members:
            if member_id in seen:
                raise PlanError(
                    f"同一人同時被排進「{seen[member_id]}」與"
                    f"「{groups[group_id]['name']}」"
                )
            seen[member_id] = groups[group_id]["name"]

    for group_id, row in groups.items():
        if row["mode"] == MODE_BLANK:
            continue          # 空白欄不配人
        cycle_len = loaded[row["name"]].cycle_len
        taken = set(seeds.get(group_id, {}).values())
        missing = sorted(set(range(1, cycle_len + 1)) - taken)
        if missing:
            shown = "、".join(str(seq) for seq in missing[:5])
            more = f" 等 {len(missing)} 格" if len(missing) > 5 else ""
            raise PlanError(f"「{row['name']}」還有番號沒配人：第 {shown} 格{more}")


# --------------------------------------------------------------------------
# 配對彈窗的預填（不寫資料庫，只算出建議的配對給畫面填入）
# --------------------------------------------------------------------------

def active_members(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """在職人員，依人員分頁的顯示順序。配對彈窗的下拉只列這些人。"""
    return conn.execute(
        "SELECT member_id, name, female FROM Member WHERE active = 1 "
        "ORDER BY sort_order, member_id"
    ).fetchall()


def pairable_groups(conn: sqlite3.Connection, template_id: int) -> list[tuple[sqlite3.Row, Group]]:
    """要配人的群組（空白欄不配人），依模板順序。"""
    loaded = {g.name: g for g in template.load_groups(conn, template_id)}
    return [
        (row, loaded[row["name"]])
        for row in template.group_rows(conn, template_id)
        if row["mode"] != MODE_BLANK
    ]


def _prefill_from_snapshot(
    conn: sqlite3.Connection, snapshot: dict, template_id: int
) -> tuple[dict[int, dict[int, int]], list[str]]:
    """把一份快照的番號套到模板上。回傳 ``(配對, 沒辦法沿用的群組名稱)``。

    ⚠️ 只沿用**名稱相同、且每格代碼與休完全一樣**的群組。格數一樣但休移了位，
    番號就完全不能沿用——硬套的話月表印出來看不出錯。對不上的群組整組留空，
    名稱回傳給畫面告訴承辦人。

    人用**姓名**對回目前的在職名單：快照裡存的是姓名，離職或改名的人對不到，
    那一格就留空讓承辦人補。
    """
    source = {data["name"]: data for data in snapshot["groups"]}
    by_name = {row["name"]: row["member_id"] for row in active_members(conn)}

    seeds: dict[int, dict[int, int]] = {}
    skipped: list[str] = []
    used: set[int] = set()
    for row, group in pairable_groups(conn, template_id):
        data = source.get(row["name"])
        if data is None or snapshot_to_group(data).slots != group.slots:
            skipped.append(row["name"])
            continue
        members: dict[int, int] = {}
        for member in data["members"]:
            member_id = by_name.get(member["name"])
            if member_id is None or member_id in used:
                continue
            members[member_id] = member["slot_seq"]
            used.add(member_id)
        seeds[row["group_id"]] = members
    return seeds, skipped


def prefill_from_previous(
    conn: sqlite3.Connection, year: int, month: int, template_id: int
) -> tuple[dict[int, dict[int, int]], list[str]]:
    """「接續上月底填入」：把上月推到本月 1 日的番號，套到這份模板上。"""
    return _prefill_from_snapshot(conn, chained_snapshot(conn, year, month), template_id)


def prefill_from_month(
    conn: sqlite3.Connection, year: int, month: int, template_id: int
) -> tuple[dict[int, dict[int, int]], list[str]]:
    """修改已產生的月份：配對彈窗填入這個月現有的番號（不往後推）。"""
    return _prefill_from_snapshot(conn, load_snapshot(conn, year, month), template_id)


def delete_plan(conn: sqlite3.Connection, year: int, month: int) -> None:
    """刪掉整筆月表。刪除是明確動作，不會不小心發生。"""
    plan = get_plan(conn, year, month)
    if plan is None:
        return
    conn.execute("DELETE FROM Month_Plan WHERE plan_id = ?", (plan["plan_id"],))
    conn.commit()


# --------------------------------------------------------------------------
# 組版
# --------------------------------------------------------------------------

def _ordered(data: dict, entries) -> tuple:
    """反向排序（右往左）的群組把欄位左右顛倒；左側日期欄由 build_sheet 另外放，不受影響。

    ⚠️ 快照裡沒有這個鍵時視為不反向（`.get`），不要改成 `data["reverse_order"]`。
    """
    entries = tuple(entries)
    return entries[::-1] if data.get("reverse_order") else entries


def build_sheet_for(
    conn: sqlite3.Connection, year: int, month: int, unit_name: str
) -> Sheet:
    """把某個月的月表組成版面模型。

    ⚠️ **全部讀快照**，不碰模板也不碰人員名單——改設定不會讓舊月表變樣。

    ⚠️ 只有 ``rotate`` 群組由程式填滿；``fixed`` 群組（固定番、幹部）整欄
    留白供手填，僅印姓名與其代碼（DEVELOPER §8）。

    ⚠️ X 軸是人名、Y 軸是日期——一位同仁一欄。
    """
    snapshot = load_snapshot(conn, year, month)

    sections: list[Section] = []
    blank_names: set[str] = set()
    for data in snapshot["groups"]:
        group = snapshot_to_group(data)
        members = data["members"]
        if group.mode == MODE_BLANK:
            # 有欄標題、有格線，格子全空供手寫。
            sections.append(
                Section(
                    name=group.name,
                    entries=_ordered(data, [Entry(name=slot.code) for slot in group.slots]),
                    header_before=data["header_before"],
                    note=parse_note(data["note"]),
                    weight=data["col_weight"],
                )
            )
            blank_names.add(group.name)
            continue
        if group.mode == MODE_ROTATE:
            computed = rota_month(
                group,
                {str(i): m["slot_seq"] for i, m in enumerate(members)},
                year,
                month,
            )
            entries = tuple(
                Entry(
                    name=member["name"],
                    female=member["female"],
                    slots=computed[str(i)],
                )
                for i, member in enumerate(members)
            )
        else:
            entries = tuple(
                Entry(
                    name=member["name"],
                    female=member["female"],
                    code=group.slots[member["slot_seq"] - 1].code,
                    # 舊快照沒有這個鍵：一律當成名字下方
                    code_above=data.get("code_position") == "above",
                )
                for member in members
            )
        sections.append(
            Section(
                name=group.name,
                entries=_ordered(data, entries),
                header_before=data["header_before"],
                weight=data["col_weight"],
            )
        )

    return build_sheet(
        unit_name, year, month, sections,
        blank_sections=frozenset(blank_names),
        title_format=get_setting(conn, KEY_TITLE_FORMAT, DEFAULT_TITLE_FORMAT),
    )
