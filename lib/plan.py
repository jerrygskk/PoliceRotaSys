"""月計畫：建立、接續、載入、組版（DEVELOPER.md §3「配置怎麼來」）。

這是「產生月表」的核心，**不含任何 Qt**——分頁只負責把它包起來給人點。

三條路（維護者裁示，不得自行擴充）：

  規則沒變、人也沒動 → 接續上月，承辦人什麼都不用做
  人動了             → 從 1 日重設
  規則換版           → 從 1 日重設（程式強制，不給選接續）
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from lib import ruleset
from lib.db_utils import KEY_TITLE_FORMAT, get_setting
from lib.layout_model import (
    DEFAULT_TITLE_FORMAT,
    Entry,
    Section,
    Sheet,
    build_sheet,
    parse_note,
)
from lib.rota import MODE_BLANK, MODE_ROTATE, Group, month_days, rota_month

ORIGIN_CHAIN = "chain"
ORIGIN_RESET = "reset"


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


def previous_plan(
    conn: sqlite3.Connection, year: int, month: int
) -> sqlite3.Row | None:
    return get_plan(conn, *_prev_year_month(year, month))


def load_seeds(
    conn: sqlite3.Connection, plan_id: int
) -> dict[int, dict[int, int]]:
    """``{rv_group_id: {member_id: slot_seq}}``。"""
    out: dict[int, dict[int, int]] = {}
    for row in conn.execute(
        "SELECT rv_group_id, member_id, slot_seq FROM Month_Seed "
        "WHERE plan_id = ? ORDER BY rv_group_id, row_no",
        (plan_id,),
    ):
        out.setdefault(row["rv_group_id"], {})[row["member_id"]] = row["slot_seq"]
    return out


def _groups_by_name(conn: sqlite3.Connection, version_id: int) -> dict[str, Group]:
    return {g.name: g for g in ruleset.load_groups(conn, version_id)}


def _group_rows(conn: sqlite3.Connection, version_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM RV_Group WHERE version_id = ? ORDER BY sort_order, group_id",
        (version_id,),
    ).fetchall()


# --------------------------------------------------------------------------
# 能不能接續上月
# --------------------------------------------------------------------------

def chain_blocked_reason(
    conn: sqlite3.Connection, year: int, month: int, version_id: int
) -> str | None:
    """回傳不能接續的原因；可以接續時回 ``None``。

    判斷只有兩條：上月有沒有月表、是不是同一版規則。

    ⚠️ **「同一版規則」已經涵蓋了「槽位完全相同」**，因為規則版本啟用後就
    凍結，同一個 version_id 的槽位必然一模一樣。所以這裡不必再逐組比
    `slots_identical`——第一版寫了，但那段程式永遠不會執行到（測試抓到的）。

    反過來說，只要換了版就一律重設，即使新版的槽位其實沒變。這正是維護者
    定的規則：規則換版屬於「番號動了」，走重設是規則二的正常結果。
    `slots_identical` 仍留在 `lib.rota`，給日後需要跨版比對時用。
    """
    prev = previous_plan(conn, year, month)
    if prev is None:
        prev_y, prev_m = _prev_year_month(year, month)
        return f"{prev_y} 年 {prev_m} 月沒有月表可以接續"
    if prev["ruleset_version_id"] != version_id:
        return "規則已換版，需重新配置"
    return None


def can_chain(
    conn: sqlite3.Connection, year: int, month: int, version_id: int
) -> bool:
    return chain_blocked_reason(conn, year, month, version_id) is None


def chained_seeds(
    conn: sqlite3.Connection, year: int, month: int, version_id: int
) -> dict[int, dict[int, int]]:
    """把上月的配置推成本月的起始格位。"""
    reason = chain_blocked_reason(conn, year, month, version_id)
    if reason:
        raise PlanError(reason)

    prev = previous_plan(conn, year, month)
    prev_y, prev_m = _prev_year_month(year, month)
    days = month_days(prev_y, prev_m)

    by_id = {row["group_id"]: row for row in _group_rows(conn, version_id)}
    groups = _groups_by_name(conn, version_id)

    out: dict[int, dict[int, int]] = {}
    for group_id, seeds in load_seeds(conn, prev["plan_id"]).items():
        group = groups[by_id[group_id]["name"]]
        if group.mode == "fixed":
            out[group_id] = dict(seeds)
        else:
            out[group_id] = {
                member: (seq - 1 + days) % group.cycle_len + 1
                for member, seq in seeds.items()
            }
    return out


# --------------------------------------------------------------------------
# 建立與刪除
# --------------------------------------------------------------------------

def create_plan(
    conn: sqlite3.Connection,
    year: int,
    month: int,
    version_id: int,
    origin: str,
    seeds: dict[int, dict[int, int]],
) -> int:
    """建立月計畫。⚠️ 事實區只新增不修改——要重產請先 :func:`delete_plan`。"""
    if origin not in (ORIGIN_CHAIN, ORIGIN_RESET):
        raise PlanError(f"未知的來源：{origin}")
    if get_plan(conn, year, month) is not None:
        raise PlanError(f"{year} 年 {month} 月已經有月表了，要重產請先刪除")
    if not seeds:
        raise PlanError("沒有任何配對")

    _assert_seeds_complete(conn, version_id, seeds)

    cur = conn.execute(
        "INSERT INTO Month_Plan(year, month, ruleset_version_id, origin, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (year, month, version_id, origin, _now()),
    )
    plan_id = cur.lastrowid
    for group_id, members in seeds.items():
        conn.executemany(
            "INSERT INTO Month_Seed(plan_id, rv_group_id, member_id, row_no, "
            "slot_seq) VALUES (?, ?, ?, ?, ?)",
            [
                (plan_id, group_id, member_id, row_no, slot_seq)
                for row_no, (member_id, slot_seq) in enumerate(
                    members.items(), start=1
                )
            ],
        )
    conn.commit()
    return plan_id


def _assert_seeds_complete(
    conn: sqlite3.Connection, version_id: int, seeds: dict[int, dict[int, int]]
) -> None:
    """配對必須完整，且落在該版規則的群組與格位範圍內。

    擋兩種錯：

      **配錯** 指到不存在的群組、或超出格數的格位
      **沒配完** 有格位沒人，或整個群組一個人都沒有

    ⚠️ 「沒配完不准按確定」不只是畫面的事。按鈕反灰擋不住（CLAUDE.md §B），
    真正的 gate 要在資料進資料庫的這一道——漏了一格的月表，印出來那一欄
    就是空的，而承辦人不會知道是自己漏配還是程式壞了。
    """
    groups = {row["group_id"]: row for row in _group_rows(conn, version_id)}
    loaded = _groups_by_name(conn, version_id)

    for group_id, members in seeds.items():
        row = groups.get(group_id)
        if row is None:
            raise PlanError(f"群組 {group_id} 不屬於這一版規則")
        cycle_len = loaded[row["name"]].cycle_len
        for member_id, slot_seq in members.items():
            if not 1 <= slot_seq <= cycle_len:
                raise PlanError(
                    f"「{row['name']}」的格位 {slot_seq} 超出範圍"
                    f"（共 {cycle_len} 格）"
                )

    for group_id, row in groups.items():
        if row["mode"] == MODE_BLANK:
            continue          # 空白欄不配人
        cycle_len = loaded[row["name"]].cycle_len
        taken = set(seeds.get(group_id, {}).values())
        missing = sorted(set(range(1, cycle_len + 1)) - taken)
        if missing:
            shown = "、".join(str(seq) for seq in missing[:5])
            more = f" 等 {len(missing)} 格" if len(missing) > 5 else ""
            raise PlanError(f"「{row['name']}」還有格位沒配人：第 {shown} 格{more}")


def delete_plan(conn: sqlite3.Connection, year: int, month: int) -> None:
    """刪掉整筆月計畫（配對連帶清掉）。刪除是明確動作，不會不小心發生。"""
    plan = get_plan(conn, year, month)
    if plan is None:
        return
    conn.execute("DELETE FROM Month_Plan WHERE plan_id = ?", (plan["plan_id"],))
    conn.commit()


# --------------------------------------------------------------------------
# 組版
# --------------------------------------------------------------------------

def build_sheet_for(
    conn: sqlite3.Connection, year: int, month: int, unit_name: str
) -> Sheet:
    """把某個月的計畫組成版面模型。

    ⚠️ 只有 ``rotate`` 群組由程式填滿；``fixed`` 群組（固定番、幹部）整欄
    留白供手填，僅印姓名與其代碼（DEVELOPER §8）。

    ⚠️ X 軸是人名、Y 軸是日期——一位同仁一欄。
    """
    plan = get_plan(conn, year, month)
    if plan is None:
        raise PlanError(f"{year} 年 {month} 月還沒有月表")

    version_id = plan["ruleset_version_id"]
    seeds = load_seeds(conn, plan["plan_id"])
    loaded = _groups_by_name(conn, version_id)
    people = {
        row["member_id"]: (row["name"], bool(row["female"]))
        for row in conn.execute("SELECT member_id, name, female FROM Member")
    }

    sections: list[Section] = []
    blank_names: set[str] = set()
    for row in _group_rows(conn, version_id):
        group = loaded[row["name"]]
        members = seeds.get(row["group_id"], {})
        if group.mode == MODE_BLANK:
            # 有欄標題、有格線，格子全空供手寫。
            sections.append(
                Section(
                    name=row["name"],
                    entries=tuple(Entry(name=slot.code) for slot in group.slots),
                    header_before=bool(row["header_before"]),
                    note=parse_note(row["note"]),
                    weight=row["col_weight"],
                )
            )
            blank_names.add(row["name"])
            continue
        if group.mode == MODE_ROTATE:
            computed = rota_month(
                group,
                {str(member_id): seq for member_id, seq in members.items()},
                year,
                month,
            )
            entries = tuple(
                Entry(
                    name=people.get(member_id, ("?", False))[0],
                    female=people.get(member_id, ("?", False))[1],
                    slots=computed[str(member_id)],
                )
                for member_id in members
            )
        else:
            entries = tuple(
                Entry(
                    name=people.get(member_id, ("?", False))[0],
                    female=people.get(member_id, ("?", False))[1],
                    code=group.slots[seq - 1].code,
                )
                for member_id, seq in members.items()
            )
        sections.append(
            Section(
                name=row["name"],
                entries=entries,
                header_before=bool(row["header_before"]),
                weight=row["col_weight"],
            )
        )

    return build_sheet(
        unit_name, year, month, sections,
        blank_sections=frozenset(blank_names),
        title_format=get_setting(conn, KEY_TITLE_FORMAT, DEFAULT_TITLE_FORMAT),
    )
