"""版面模型：把排班結果攤成一張「幾列幾欄、每格什麼字什麼顏色」的純資料。

⚠️ 本模組**零相依**——不 import Qt、不 import openpyxl、不 import 資料庫。

這是刻意設計的中間層（DEVELOPER.md §1）：xlsx 與 pdf 兩個 renderer 吃同一份
版面定義，Excel 印出來和 PDF 才會長一樣。也因為它是純資料，「版面對不對」
可以在無 GUI 環境自動驗證，不必每次都上機用眼睛看。

⚠️ **軸向：日期是「列」，同仁是「欄」**（DEVELOPER.md §8）。

    第一版做反了——日期當欄、姓名當列。會搞錯是因為紙本是旋轉 90° 掃描的，
    掃描件上看起來像橫的東西，在原始 Excel 裡是直的。改之前先確認軸向。

版面照現行紙本：
  - A3 橫式單頁，⚠️ **標題在最左邊一整欄直書**（跨全高），不是橫置於頁首
  - 三個區塊**左右並排**，⚠️ 日期／星期欄在每個區塊之間重複
  - 只有輪番區由程式填滿；固定番與休假打勤務兩區留白供手填
  - 休與週六日印紅色
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field

from lib.rota import Slot

BLACK = "black"
RED = "red"
BLUE = "blue"

NOTE_COLORS = {BLACK, RED, BLUE}

WEEKDAY_LABELS = ("一", "二", "三", "四", "五", "六", "日")
SATURDAY = 5
SUNDAY = 6

COL_TITLE = "title"
COL_DATE = "date"
COL_WEEKDAY = "weekday"
COL_MEMBER = "member"
COL_BLANK = "blank"


@dataclass(frozen=True)
class Cell:
    text: str = ""
    color: str = BLACK


@dataclass(frozen=True)
class Column:
    """一欄。``cells`` 依序對應該月的每一天。"""

    kind: str
    header: str = ""          # 姓名，或「日期」「星期」
    code: str = ""            # 固定番／幹部的代碼，印在姓名下
    header_color: str = BLACK
    weight: float = 1.0       # 相對欄寬，來自所屬群組的設定
    cells: tuple[Cell, ...] = ()

    @property
    def is_header(self) -> bool:
        return self.kind in (COL_DATE, COL_WEEKDAY)


# 欄寬權重。⚠️ 放在版面模型裡是刻意的——兩個 renderer 必須用同一份，
# 否則 Excel 印出來跟 PDF 會不一樣寬。
#
# ⚠️ **每個群組的權重是設定（`RV_Group.col_weight`），不是由欄的種類推的。**
# 第一版靠「格子是不是空的」去猜，結果所有手寫欄一律同寬——但固定番、劃假區、
# 幹部要寫的東西不一樣多，現場要能分別調。
WEIGHT_TITLE = 1.0
WEIGHT_HEADER = 1.0      # 日期／星期
WEIGHT_DEFAULT = 1.0     # 群組沒指定時


def column_weight(column: "Column") -> float:
    if column.kind == COL_TITLE:
        return WEIGHT_TITLE
    if column.kind in (COL_DATE, COL_WEEKDAY):
        return WEIGHT_HEADER
    return column.weight


@dataclass(frozen=True)
class NoteLine:
    """註記的一行。紙本上那段班別說明是逐行不同顏色的，照抄。"""

    text: str
    color: str = BLACK


def parse_note(raw: str) -> tuple[NoteLine, ...]:
    """把設定裡的註記文字解析成逐行的 :class:`NoteLine`。

    格式：一行一筆，``顏色|文字``；顏色省略時為黑色。例如::

        blue|晚班:(1-5、16)
        red|早班:(8-12、15)
        black|中班(17.18)
        red|限填1人
    """
    lines: list[NoteLine] = []
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        head, sep, rest = line.partition("|")
        if sep and head.strip() in NOTE_COLORS:
            lines.append(NoteLine(rest.strip(), head.strip()))
        else:
            lines.append(NoteLine(line, BLACK))
    return tuple(lines)


@dataclass(frozen=True)
class Block:
    """一個左右並排的區塊。``name`` 為空者是重複的日期／星期欄。

    ``note`` 有值時要畫成**一個跨該區塊所有欄的合併格**，放在姓名列
    （紙本上早／中／晚三欄上方那段班別說明就是這樣，逐行不同顏色）。
    """

    name: str
    columns: tuple[Column, ...]
    note: tuple[NoteLine, ...] = ()

    @property
    def is_header(self) -> bool:
        return not self.name


@dataclass(frozen=True)
class Sheet:
    title: str
    year: int                 # 西元
    month: int
    day_count: int
    blocks: tuple[Block, ...]

    @property
    def columns(self) -> tuple[Column, ...]:
        return tuple(col for block in self.blocks for col in block.columns)


@dataclass(frozen=True)
class Entry:
    """區塊裡的一欄（一位同仁）。

    ``slots`` 有值時由程式填滿（輪番區）；``None`` 表示整欄留白供手填。
    """

    name: str
    code: str = ""
    slots: tuple[Slot, ...] | None = None
    # 女警：姓名印紅色（維護者要求，xlsx 與 pdf 一致）。
    female: bool = False


@dataclass(frozen=True)
class Section:
    name: str
    entries: tuple[Entry, ...] = field(default_factory=tuple)
    # 這個區塊左邊要不要再放一次日期／星期欄。現行紙本不是每個區塊都有。
    header_before: bool = True
    # 跨整個區塊的註記（逐行帶顏色），畫在姓名列的合併格裡。
    note: tuple[NoteLine, ...] = ()
    # 這個區塊每欄的相對寬度（RV_Group.col_weight）。
    weight: float = WEIGHT_DEFAULT


def roc_year(year: int) -> int:
    """西元轉民國。"""
    return year - 1911


# 標題格式。⚠️ 現場用語會調（「輪休預定表」「輪番休預訂計畫表」各單位不同），
# 所以做成 App_Settings 的 sheet_title_format，這裡只是預設值。
DEFAULT_TITLE_FORMAT = "{unit} {roc} 年 {month} 月份輪休預定表"


def sheet_title(
    unit_name: str, year: int, month: int, fmt: str = DEFAULT_TITLE_FORMAT
) -> str:
    return fmt.format(unit=unit_name, roc=roc_year(year), month=month, year=year)


def is_weekend(year: int, month: int, day: int) -> bool:
    return calendar.weekday(year, month, day) in (SATURDAY, SUNDAY)


def _day_color(year: int, month: int, day: int) -> str:
    return RED if is_weekend(year, month, day) else BLACK


def date_column(year: int, month: int, day_count: int) -> Column:
    return Column(
        kind=COL_DATE,
        header="日期",
        cells=tuple(
            Cell(str(day), _day_color(year, month, day))
            for day in range(1, day_count + 1)
        ),
    )


def weekday_column(year: int, month: int, day_count: int) -> Column:
    return Column(
        kind=COL_WEEKDAY,
        header="星期",
        cells=tuple(
            Cell(
                WEEKDAY_LABELS[calendar.weekday(year, month, day)],
                _day_color(year, month, day),
            )
            for day in range(1, day_count + 1)
        ),
    )


def title_column(title: str, day_count: int) -> Column:
    """最左邊那一整欄：直書標題，跨全高。"""
    return Column(
        kind=COL_TITLE,
        header=title,
        cells=tuple(Cell() for _ in range(day_count)),
    )


def _header_block(year: int, month: int, day_count: int) -> Block:
    return Block(
        name="",
        columns=(
            date_column(year, month, day_count),
            weekday_column(year, month, day_count),
        ),
    )


# 休的格子一律印「休」（維護者裁示：印 00 不知所云）。
REST_TEXT = "休"


def _member_column(
    entry: Entry,
    day_count: int,
    kind: str = COL_MEMBER,
    weight: float = WEIGHT_DEFAULT,
) -> Column:
    if entry.slots is None:
        cells = tuple(Cell() for _ in range(day_count))
    else:
        if len(entry.slots) != day_count:
            raise ValueError(
                f"「{entry.name}」有 {len(entry.slots)} 天的資料，"
                f"但這個月是 {day_count} 天"
            )
        cells = tuple(
            Cell(REST_TEXT, RED) if slot.is_rest else Cell(slot.code, BLACK)
            for slot in entry.slots
        )
    return Column(
        kind=kind, header=entry.name, code=entry.code,
        header_color=RED if entry.female else BLACK,
        weight=weight, cells=cells,
    )


def build_sheet(
    unit_name: str,
    year: int,
    month: int,
    sections: list[Section],
    blank_sections: frozenset[str] = frozenset(),
    title_format: str = DEFAULT_TITLE_FORMAT,
) -> Sheet:
    """組出整張表。``year`` 為**西元**，標題自動轉民國。

    ⚠️ 每個區塊左右都插入日期／星期欄，這是紙本既有的設計不是冗餘——
    A3 很寬，沒有重複標頭就得拿尺對格子。
    """
    if not sections:
        raise ValueError("至少要有一個區塊")
    day_count = calendar.monthrange(year, month)[1]

    title = sheet_title(unit_name, year, month, title_format)
    blocks: list[Block] = [
        Block(name="", columns=(title_column(title, day_count),)),
    ]
    for section in sections:
        if section.header_before:
            blocks.append(_header_block(year, month, day_count))
        is_blank = section.name in blank_sections
        kind = COL_BLANK if is_blank else COL_MEMBER
        columns = tuple(
            _member_column(entry, day_count, kind, section.weight)
            for entry in section.entries
        )
        if is_blank and section.note:
            # 有註記的空白區塊：註記佔掉姓名列（合併格），
            # 各欄的小標題（早／中／晚）移到代碼列。
            columns = tuple(
                Column(
                    kind=col.kind, header="", code=col.header,
                    header_color=col.header_color,
                    weight=col.weight, cells=col.cells,
                )
                for col in columns
            )
        blocks.append(
            Block(name=section.name, columns=columns, note=section.note)
        )
    # 最右邊一定再放一次，紙本如此。
    blocks.append(_header_block(year, month, day_count))

    return Sheet(
        title=title,
        year=year,
        month=month,
        day_count=day_count,
        blocks=tuple(blocks),
    )
