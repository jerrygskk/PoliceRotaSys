"""建立 README 公開截圖專用資料庫。

資料庫只含匿名單位、虛構姓名與動態相鄰月份。輸出先在同一資料夾完成，
最後才以 ``os.replace`` 原子替換，避免建置中斷留下半套資料庫。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib import db_schema, db_seed, plan
from lib.db_utils import KEY_UNIT_NAME, connect, set_setting

ROOT_DATABASE = REPO_ROOT / "dbfile.db"
CANDIDATE_MARKER_KEY = "screenshot_candidate"
CANDIDATE_MARKER_VALUE = "PoliceRotaSys-public-demo-v1"
CANDIDATE_DIGEST_KEY = "screenshot_candidate_sha256"
DISPLAY_YEAR_KEY = "screenshot_display_year"
DISPLAY_MONTH_KEY = "screenshot_display_month"
ANONYMOUS_UNIT = "○○分局○○派出所"
INACTIVE_FAKE_NAME = "周小安"

_DIGEST_QUERIES = {
    "settings": (
        "SELECT key, value FROM App_Settings WHERE key <> ? ORDER BY key",
        (CANDIDATE_DIGEST_KEY,),
    ),
    "members": (
        "SELECT member_id, name, active, female, sort_order "
        "FROM Member ORDER BY member_id",
        (),
    ),
    "templates": (
        "SELECT template_id, name, created_at, note "
        "FROM Rota_Template ORDER BY template_id",
        (),
    ),
    "groups": (
        "SELECT group_id, template_id, name, mode, range_expr, header_before, "
        "col_weight, reverse_order, code_position, note, sort_order "
        "FROM T_Group ORDER BY group_id",
        (),
    ),
    "slots": (
        "SELECT group_id, seq, is_rest, code_override "
        "FROM T_Slot ORDER BY group_id, seq",
        (),
    ),
    "month_plans": (
        "SELECT plan_id, year, month, origin, created_at, snapshot "
        "FROM Month_Plan ORDER BY plan_id",
        (),
    ),
}


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def validate_output_path(output: Path, *, force: bool = False) -> Path:
    """驗證輸出安全界線；正式資料庫在任何情況都禁止。"""
    output = Path(output).expanduser().resolve()
    if _same_path(output, ROOT_DATABASE):
        raise ValueError("拒絕寫入專案根目錄的正式資料庫 dbfile.db")
    if not output.parent.is_dir():
        raise ValueError(f"輸出資料夾不存在：{output.parent}")
    if output.exists() and not force:
        raise FileExistsError(f"輸出已存在，若要覆寫請加 --force：{output}")
    if output.is_dir():
        raise ValueError(f"輸出路徑是資料夾：{output}")
    return output


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def screenshot_months(today: date | None = None) -> tuple[tuple[int, int], tuple[int, int]]:
    """回傳（基準月、展示月）；展示月固定為執行當時的下個月。"""
    today = today or date.today()
    return (today.year, today.month), _next_month(today.year, today.month)


def candidate_digest(conn) -> str:
    """計算候選庫公開內容的穩定 SHA-256；排除儲存雜湊本身的設定列。"""
    payload = {
        name: [list(row) for row in conn.execute(sql, params).fetchall()]
        for name, (sql, params) in _DIGEST_QUERIES.items()
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _complete_seeds(conn, template_id: int) -> dict[int, dict[int, int]]:
    members = [row["member_id"] for row in plan.active_members(conn)]
    offset = 0
    seeds: dict[int, dict[int, int]] = {}
    for row, group in plan.pairable_groups(conn, template_id):
        group_members = members[offset:offset + group.cycle_len]
        if len(group_members) != group.cycle_len:
            raise RuntimeError("公開截圖假名人數不足，無法填滿示範模板")
        seeds[row["group_id"]] = {
            member_id: seq for seq, member_id in enumerate(group_members, start=1)
        }
        offset += group.cycle_len
    return seeds


def _populate_database(path: Path) -> dict:
    conn = connect(str(path))
    try:
        db_schema.create_all(conn)
        db_seed.seed_all(conn, template_name="公開截圖範例")
        set_setting(conn, KEY_UNIT_NAME, ANONYMOUS_UNIT)
        set_setting(conn, CANDIDATE_MARKER_KEY, CANDIDATE_MARKER_VALUE)

        conn.execute(
            "INSERT INTO Member(name, active, female, sort_order) VALUES (?, 0, 0, ?)",
            (INACTIVE_FAKE_NAME, 5),
        )
        template_id = conn.execute(
            "SELECT template_id FROM Rota_Template ORDER BY template_id LIMIT 1"
        ).fetchone()[0]
        conn.execute(
            "UPDATE Rota_Template SET note = ? WHERE template_id = ?",
            ("公開截圖專用的虛構輪番模板", template_id),
        )
        conn.commit()

        base_month, display_month = screenshot_months()
        set_setting(conn, DISPLAY_YEAR_KEY, str(display_month[0]))
        set_setting(conn, DISPLAY_MONTH_KEY, str(display_month[1]))
        plan.create_plan(
            conn, base_month[0], base_month[1], template_id,
            _complete_seeds(conn, template_id),
        )
        plan.create_chained_plan(conn, display_month[0], display_month[1])

        digest = candidate_digest(conn)
        set_setting(conn, CANDIDATE_DIGEST_KEY, digest)

        return {
            "output": str(path),
            "unit": ANONYMOUS_UNIT,
            "members": conn.execute("SELECT COUNT(*) FROM Member").fetchone()[0],
            "inactive_members": 1,
            "templates": 1,
            "months": [base_month, display_month],
            "display_month": display_month,
            "digest": digest,
        }
    finally:
        conn.close()


def _build_database(output: Path, *, force: bool) -> dict:
    output = validate_output_path(output, force=force)
    fd, temp_name = tempfile.mkstemp(
        dir=output.parent, prefix=f".{output.name}.", suffix=".tmp"
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        summary = _populate_database(temp_path)
        os.replace(temp_path, output)
        summary["output"] = str(output)
        return summary
    finally:
        if temp_path.exists():
            temp_path.unlink()


def build_database(output: Path) -> dict:
    """建立全新候選資料庫；既有輸出必須由 CLI 明確指定 ``--force``。"""
    return _build_database(Path(output), force=False)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="建立 README 公開截圖候選資料庫")
    parser.add_argument("output", type=Path, help="候選 SQLite 資料庫輸出路徑")
    parser.add_argument("--force", action="store_true", help="覆寫既有候選資料庫")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = _build_database(args.output, force=args.force)
    except (FileExistsError, OSError, RuntimeError, ValueError) as exc:
        print(f"錯誤：{exc}")
        return 1

    months = "、".join(f"{year - 1911} 年 {month} 月" for year, month in summary["months"])
    print(f"已建立公開截圖候選資料庫：{summary['output']}")
    print(
        f"摘要：匿名單位 1 個、虛構人員 {summary['members']} 人"
        f"（離職 {summary['inactive_members']} 人）、模板 {summary['templates']} 份、"
        f"月表 {months}"
    )
    print(f"內容指紋（SHA-256）：{summary['digest']}")
    print("提醒：入庫前仍須執行個資檢查，並逐張人工目視所有公開截圖。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
