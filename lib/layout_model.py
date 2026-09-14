"""版面模型：把排班結果攤成一張「幾列幾欄、每格什麼字什麼顏色」的純資料。

⚠️ 本模組**零相依**——不 import Qt、不 import openpyxl、不 import 資料庫。

這是刻意設計的中間層（DEVELOPER.md §1）：xlsx 與 pdf 兩個 renderer 吃同一份
版面定義，Excel 印出來和 PDF 才會長一樣。也因為它是純資料，「版面對不對」
可以在無 GUI 環境自動驗證，不必每次都上機用眼睛看。

版面照現行紙本（DEVELOPER.md §8）：
  - A3 橫式單頁，標題直書置左
  - 三個區塊上下堆疊，⚠️ 每個區塊前後都重複日期列與星期列
  - 只有輪番區由程式填滿；固定番與休假打勤務兩區留白供手填
  - 休與週六日印紅色
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field

from lib.rota import Slot

BLACK = "black"
RED = "red"

WEEKDAY_LABELS = ("一", "二", "三", "四", "五", "六", "日")
SATURDAY = 5
SUNDAY = 6

ROW_DATE = "date"
ROW_WEEKDAY = "weekday"
ROW_MEMBER = "member"


@dataclass(frozen=True)
class Cell:
    text: str = ""
    color: str = BLACK


@dataclass(frozen=True)
class Row:
    kind: str
    label: str = ""          # 姓名，或「日期」「星期」
    code: str = ""           # 固定番／幹部的代碼，印在姓名旁
    label_color: str = BLACK
    cells: tuple[Cell, ...] = ()


@dataclass(frozen=True)
class Block:
    """一個橫幅區塊。``name`` 為空字串者是重複的日期／星期標頭。"""

    name: str
    rows: tuple[Row, ...]

    @property
    def is_header(self) -> bool:
        return not self.name


@dataclass(frozen=True)
class Sheet:
    title: str
    year: int                # 西元
    month: int
    day_count: int
    blocks: tuple[Block, ...]

    @property
    def rows(self) -> tuple[Row, ...]:
        return tuple(row for block in self.blocks for row in block.rows)


@dataclass(frozen=True)
class Entry:
    """區塊裡的一列。

    ``slots`` 有值時由程式填滿（輪番區）；``None`` 表示整列留白供手填。
    """

    name: str
    code: str = ""
    slots: tuple[Slot, ...] | None = None


@dataclass(frozen=True)
class Section:
    name: str
    entries: tuple[Entry, ...] = field(default_factory=tuple)


def roc_year(year: int) -> int:
    """西元轉民國。"""
    return year - 1911


def sheet_title(unit_name: str, year: int, month: int) -> str:
    return f"{unit_name} {roc_year(year)} 年 {month} 月份輪番休預訂計畫表"


def is_weekend(year: int, month: int, day: int) -> bool:
    return calendar.weekday(year, month, day) in (SATURDAY, SUNDAY)


def _day_color(year: int, month: int, day: int) -> str:
    return RED if is_weekend(year, month, day) else BLACK


def date_row(year: int, month: int, day_count: int) -> Row:
    return Row(
        kind=ROW_DATE,
        label="日期",
        cells=tuple(
            Cell(str(day), _day_color(year, month, day))
            for day in range(1, day_count + 1)
        ),
    )


def weekday_row(year: int, month: int, day_count: int) -> Row:
    return Row(
        kind=ROW_WEEKDAY,
        label="星期",
        cells=tuple(
            Cell(
                WEEKDAY_LABELS[calendar.weekday(year, month, day)],
                _day_color(year, month, day),
            )
            for day in range(1, day_count + 1)
        ),
    )


def _header_block(year: int, month: int, day_count: int) -> Block:
    return Block(
        name="",
        rows=(
            date_row(year, month, day_count),
            weekday_row(year, month, day_count),
        ),
    )


def _member_row(entry: Entry, day_count: int, rest_code: str) -> Row:
    if entry.slots is None:
        cells = tuple(Cell() for _ in range(day_count))
    else:
        if len(entry.slots) != day_count:
            raise ValueError(
                f"「{entry.name}」有 {len(entry.slots)} 天的資料，"
                f"但這個月是 {day_count} 天"
            )
        cells = tuple(
            Cell(rest_code, RED) if slot.is_rest else Cell(slot.code, BLACK)
            for slot in entry.slots
        )
    return Row(kind=ROW_MEMBER, label=entry.name, code=entry.code, cells=cells)


def build_sheet(
    unit_name: str,
    year: int,
    month: int,
    sections: list[Section],
    rest_code: str = "00",
) -> Sheet:
    """組出整張表。``year`` 為**西元**，標題自動轉民國。

    ⚠️ 每個區塊前後都插入日期／星期標頭，這是紙本既有的設計不是冗餘——
    A3 很寬，沒有重複標頭就得拿尺對格子。
    """
    if not sections:
        raise ValueError("至少要有一個區塊")
    day_count = calendar.monthrange(year, month)[1]

    blocks: list[Block] = [_header_block(year, month, day_count)]
    for section in sections:
        blocks.append(
            Block(
                name=section.name,
                rows=tuple(
                    _member_row(entry, day_count, rest_code)
                    for entry in section.entries
                ),
            )
        )
        blocks.append(_header_block(year, month, day_count))

    return Sheet(
        title=sheet_title(unit_name, year, month),
        year=year,
        month=month,
        day_count=day_count,
        blocks=tuple(blocks),
    )
