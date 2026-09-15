"""排班演算法：範圍式展開、槽位推算、跨群組驗證。

⚠️ 本模組**零相依**——不 import Qt、不 import 資料庫，只吃參數、吐結果。
所以測它不必準備資料庫，也不必有 GUI 環境。改動時請維持這個性質。

核心概念（詳見 DEVELOPER.md §2、§3）：

  番號用列印頁數那種範圍寫法定義（``1-20``、``21-25``、``A-F``），
  展開成一串**槽位**；每位同仁錯開一格，每過一天往後推一格，
  跑完最後一格回到第 1 格。

  「休」不是特例，它就是槽位序列裡的一個值。

年份一律用**西元**。民國換算是呈現層的事，不在本模組。
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass

# 天干十字。地支或其他序列若日後要支援，加在這裡即可。
CJK_STEMS = "甲乙丙丁戊己庚辛壬癸"

KIND_NUM = "num"
KIND_ALPHA = "alpha"
KIND_CJK = "cjk"

ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class RangeError(ValueError):
    """範圍式語法錯誤。訊息直接面向使用者，可原樣顯示在欄位旁。"""


class GroupError(ValueError):
    """跨群組的邏輯錯誤（撞號等）。按「檢查規則」或「啟用」時才驗得出來。"""


@dataclass(frozen=True)
class Slot:
    """展開後的一格。``seq`` 為 1-based。"""

    seq: int
    code: str
    is_rest: bool


@dataclass(frozen=True)
class Group:
    """一個群組。``slots`` 的長度即循環格數，不另存。"""

    name: str
    mode: str  # 'rotate' 輪番 / 'fixed' 固定
    slots: tuple[Slot, ...]

    @property
    def cycle_len(self) -> int:
        return len(self.slots)


# --------------------------------------------------------------------------
# 範圍式
# --------------------------------------------------------------------------

def detect_kind(expr: str) -> str:
    """由輸入判斷型態，不給人選（DEVELOPER §3）。

    判斷只看出現了哪一類字元；混用會在 ``expand_range`` 被擋下。
    """
    body = expr.replace("-", "").replace(",", "").replace(" ", "")
    if not body:
        raise RangeError("範圍不可為空")
    if all(c.isdigit() for c in body):
        return KIND_NUM
    if all(c in ALPHA for c in body.upper()):
        return KIND_ALPHA
    if all(c in CJK_STEMS for c in body):
        return KIND_CJK
    raise RangeError("範圍不可混用數字、英文與天干")


def _ordinal(token: str, kind: str) -> int:
    """把單一端點轉成可比大小的序數。"""
    if kind == KIND_NUM:
        return int(token)
    if len(token) != 1:
        raise RangeError(f"「{token}」不是單一字元；英文與天干只支援單一字元")
    if kind == KIND_ALPHA:
        return ALPHA.index(token.upper())
    return CJK_STEMS.index(token)


def _render(value: int, kind: str, digits: int) -> str:
    if kind == KIND_NUM:
        return str(value).zfill(digits)
    if kind == KIND_ALPHA:
        return ALPHA[value]
    return CJK_STEMS[value]


def _segments(expr: str, kind: str) -> list[tuple[int, int]]:
    """切出各段的 (起, 迄) 序數，逐段檢查語法。"""
    out: list[tuple[int, int]] = []
    for raw in expr.split(","):
        part = raw.strip()
        if not part:
            raise RangeError("範圍有空的段落（是不是多打了逗號？）")
        if "-" in part:
            bits = part.split("-")
            if len(bits) != 2 or not all(b.strip() for b in bits):
                raise RangeError(f"「{part}」不是合法的範圍寫法")
            lo = _ordinal(bits[0].strip(), kind)
            hi = _ordinal(bits[1].strip(), kind)
            if lo > hi:
                raise RangeError(f"「{part}」的起迄相反了")
        else:
            lo = hi = _ordinal(part, kind)
        out.append((lo, hi))
    return out


def expand_range(expr: str) -> tuple[str, ...]:
    """把範圍式展開成代碼序列。

    ``'1-20'`` → ``('01', '02', ..., '20')``；位數由範圍最大值決定。
    ``'A-F'`` → ``('A', ..., 'F')``。

    語法錯誤一律 raise :class:`RangeError`，訊息可直接顯示給使用者。
    """
    kind = detect_kind(expr)
    segments = _segments(expr, kind)

    seen: set[int] = set()
    values: list[int] = []
    for lo, hi in segments:
        for value in range(lo, hi + 1):
            if value in seen:
                code = _render(value, kind, len(str(hi)))
                raise RangeError(f"「{code}」在範圍裡出現了兩次")
            seen.add(value)
            values.append(value)

    digits = len(str(max(values))) if kind == KIND_NUM else 1
    return tuple(_render(value, kind, digits) for value in values)


def build_slots(codes: tuple[str, ...], rest_seqs: set[int] = frozenset()) -> tuple[Slot, ...]:
    """把代碼序列組成槽位；``rest_seqs`` 是 1-based 的休假格位。"""
    for seq in rest_seqs:
        if not 1 <= seq <= len(codes):
            raise RangeError(f"休假格位 {seq} 超出範圍（共 {len(codes)} 格）")
    return tuple(
        Slot(seq=i, code=code, is_rest=i in rest_seqs)
        for i, code in enumerate(codes, start=1)
    )


MODE_ROTATE = "rotate"
MODE_FIXED = "fixed"
MODE_BLANK = "blank"
MODES = (MODE_ROTATE, MODE_FIXED, MODE_BLANK)


def blank_labels(expr: str) -> tuple[str, ...]:
    """``blank`` 群組的欄標題：逗號分隔的字面文字，不是範圍式。

    紙本上「同仁專案臨檢／請假」的早／中／晚、以及「快打勤務」都屬於這類——
    有欄標題、有格線，但**格子全空供手寫**，不配人也不算番號。
    """
    labels = tuple(part.strip() for part in expr.split(",") if part.strip())
    if not labels:
        raise RangeError("空白欄至少要有一個欄標題")
    return labels


def make_group(
    name: str, mode: str, expr: str, rest_seqs: set[int] = frozenset()
) -> Group:
    if mode not in MODES:
        raise ValueError(f"未知的模式：{mode}")
    if mode != MODE_ROTATE and rest_seqs:
        raise ValueError(f"{mode} 群組沒有輪休格位")
    if mode == MODE_BLANK:
        return Group(
            name=name,
            mode=mode,
            slots=tuple(
                Slot(seq=i, code=label, is_rest=False)
                for i, label in enumerate(blank_labels(expr), start=1)
            ),
        )
    return Group(name=name, mode=mode, slots=build_slots(expand_range(expr), rest_seqs))


# --------------------------------------------------------------------------
# 驗證
# --------------------------------------------------------------------------

def validate_expr(expr: str) -> None:
    """離開欄位時的語法驗證（DEVELOPER §3「兩層驗證」）。

    只驗這個欄位自己的事；撞號要等所有群組填完，由
    :func:`validate_groups` 負責。
    """
    expand_range(expr)


def validate_groups(groups: list[Group]) -> None:
    """按「檢查規則」或「啟用」時的跨群組驗證。"""
    seen: dict[str, str] = {}
    for group in groups:
        if not group.slots:
            raise GroupError(f"「{group.name}」的範圍是空的")
        if group.mode == MODE_ROTATE and all(s.is_rest for s in group.slots):
            raise GroupError(f"「{group.name}」每一格都是休，沒有人會上班")
        if group.mode == MODE_BLANK:
            # 空白欄的標題不是番號，不參與撞號檢查。
            continue
        for slot in group.slots:
            owner = seen.get(slot.code)
            if owner is not None:
                raise GroupError(
                    f"代碼「{slot.code}」同時出現在「{owner}」與「{group.name}」"
                )
            seen[slot.code] = group.name


# --------------------------------------------------------------------------
# 排班推算
# --------------------------------------------------------------------------

def slot_on_day(group: Group, seed_seq: int, day: int) -> Slot:
    """某人在該月第 ``day`` 天站在哪一格。``seed_seq`` 是他 1 日的格位。

    輪番群組每天往後推一格；固定番不隨日期前進（DEVELOPER §2）。
    """
    if not 1 <= seed_seq <= group.cycle_len:
        raise ValueError(f"起始格位 {seed_seq} 超出範圍（共 {group.cycle_len} 格）")
    if day < 1:
        raise ValueError("日期從 1 起算")
    if group.mode != MODE_ROTATE:
        return group.slots[seed_seq - 1]
    index = (seed_seq - 1 + (day - 1)) % group.cycle_len
    return group.slots[index]


def month_days(year: int, month: int) -> int:
    """該月天數。``year`` 為**西元**。"""
    return calendar.monthrange(year, month)[1]


def rota_month(
    group: Group, seeds: dict[str, int], year: int, month: int
) -> dict[str, tuple[Slot, ...]]:
    """推算整個月。

    ``seeds`` 是 ``{人員識別: 1 日的格位}``；回傳
    ``{人員識別: (第1天, 第2天, ...)}``。

    人員識別用什麼由呼叫端決定（member_id 或姓名皆可）——本模組不認識「人」，
    只認識識別字串，所以不必為了測試準備人員資料。
    """
    days = month_days(year, month)
    return {
        who: tuple(slot_on_day(group, seed, day) for day in range(1, days + 1))
        for who, seed in seeds.items()
    }


def chain_seeds(
    group: Group, seeds: dict[str, int], prev_month_days: int
) -> dict[str, int]:
    """把上月的 1 日格位推成本月的 1 日格位（「接續上月」）。

    固定番不隨日期前進，格位原樣沿用。
    """
    if group.mode != MODE_ROTATE:
        return dict(seeds)
    return {
        who: (seed - 1 + prev_month_days) % group.cycle_len + 1
        for who, seed in seeds.items()
    }


def slots_identical(a: Group, b: Group) -> bool:
    """兩組的展開槽位是否完全相同——格數、每格代碼、每格是否為休。

    「接續上月填入」只在這個函式回 True 時可用（DEVELOPER §4）。
    ⚠️ 不是只比格數：休從第 6、7 格移到第 5、6 格時格數一樣，
    但配對完全不能沿用。
    """
    return a.slots == b.slots
