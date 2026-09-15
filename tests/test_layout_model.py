"""lib/layout_model.py 的單元測試。⚠️ 姓名一律虛構。"""
import unittest

from lib.layout_model import (
    BLACK,
    COL_DATE,
    COL_MEMBER,
    COL_WEEKDAY,
    RED,
    Entry,
    Section,
    build_sheet,
    is_weekend,
    roc_year,
    sheet_title,
)
from lib.rota import make_group, rota_month


def block_named(sheet, name):
    """⚠️ 用名稱找區塊，不要寫死索引——加一個區塊就全錯。"""
    for block in sheet.blocks:
        if block.name == name:
            return block
    raise AssertionError(f"找不到區塊「{name}」")


def header_blocks(sheet):
    return [b for b in sheet.blocks if b.is_header and b.columns[0].kind != "title"]

PAPER_REST = {6, 7, 13, 14, 19, 20}
UNIT = "○○分局○○派出所"


def paper_group():
    return make_group("大輪番", "rotate", "1-20", PAPER_REST)


def rotate_section(year=2026, month=10, seeds=None):
    seeds = seeds or {"王小明": 12, "李小華": 13}
    result = rota_month(paper_group(), seeds, year, month)
    return Section(
        name="大輪番",
        entries=tuple(Entry(name=who, slots=result[who]) for who in seeds),
    )


def blank_section():
    return Section(
        name="固定番",
        entries=(Entry(name="張大同", code="21"), Entry(name="陳小美", code="22")),
    )


class TestTitle(unittest.TestCase):
    def test_roc_conversion(self):
        self.assertEqual(roc_year(2026), 115)

    def test_title_uses_roc_year(self):
        self.assertIn("115 年 10 月", sheet_title(UNIT, 2026, 10))

    def test_title_carries_unit_name(self):
        """單位名稱來自設定，不可寫死（DEVELOPER §7）。"""
        self.assertTrue(sheet_title("甲所", 2026, 10).startswith("甲所"))


class TestWeekend(unittest.TestCase):
    def test_saturday_and_sunday(self):
        self.assertTrue(is_weekend(2026, 10, 3))   # 六
        self.assertTrue(is_weekend(2026, 10, 4))   # 日
        self.assertFalse(is_weekend(2026, 10, 5))  # 一


class TestBuildSheet(unittest.TestCase):
    def setUp(self):
        self.sheet = build_sheet(UNIT, 2026, 10, [rotate_section(), blank_section()])

    def test_day_count_follows_the_calendar(self):
        self.assertEqual(self.sheet.day_count, 31)
        self.assertEqual(build_sheet(UNIT, 2025, 2, [rotate_section(2025, 2)]).day_count, 28)

    def test_title_is_the_leftmost_column(self):
        """⚠️ 標題在最左邊一整欄直書，不是橫置於頁首。"""
        first = self.sheet.columns[0]
        self.assertEqual(first.kind, "title")
        self.assertEqual(first.header, self.sheet.title)

    def test_header_repeats_between_blocks_and_at_the_end(self):
        """⚠️ 紙本既有設計：A3 很寬，沒有重複標頭就得拿尺對格子。"""
        self.assertEqual(len(header_blocks(self.sheet)), 3)
        self.assertTrue(self.sheet.blocks[-1].is_header)

    def test_every_column_has_one_cell_per_day(self):
        for column in self.sheet.columns:
            self.assertEqual(len(column.cells), 31, column.header)

    def test_rest_cells_print_rest_in_red(self):
        column = block_named(self.sheet, "大輪番").columns[0]  # 王小明
        self.assertEqual(column.cells[1].text, "休")
        self.assertEqual(column.cells[1].color, RED)

    def test_duty_cells_are_black(self):
        column = block_named(self.sheet, "大輪番").columns[0]
        self.assertEqual(column.cells[0].text, "12")
        self.assertEqual(column.cells[0].color, BLACK)

    def test_weekend_rows_are_red_in_both_header_columns(self):
        date, weekday = header_blocks(self.sheet)[0].columns
        self.assertEqual(date.kind, COL_DATE)
        self.assertEqual(weekday.kind, COL_WEEKDAY)
        self.assertEqual(date.cells[2].color, RED)      # 10/3 週六
        self.assertEqual(weekday.cells[2].text, "六")
        self.assertEqual(weekday.cells[2].color, RED)
        self.assertEqual(date.cells[4].color, BLACK)    # 10/5 週一

    def test_blank_section_columns_are_empty_but_still_sized(self):
        """⚠️ 固定番與幹部區刻意留白供手填，程式不要自作聰明去填。"""
        block = block_named(self.sheet, "固定番")
        for column in block.columns:
            self.assertEqual(len(column.cells), 31)
            self.assertTrue(all(cell.text == "" for cell in column.cells))

    def test_blank_section_columns_keep_their_code(self):
        self.assertEqual(block_named(self.sheet, "固定番").columns[0].code, "21")

    def test_member_columns_are_marked_as_such(self):
        self.assertTrue(
            all(col.kind == COL_MEMBER
                for col in block_named(self.sheet, "大輪番").columns)
        )


class TestAxisOrientation(unittest.TestCase):
    """⚠️ X 軸是人名（欄）、Y 軸是日期（列）。第一版做反了，這支釘住它。"""

    def setUp(self):
        self.sheet = build_sheet(UNIT, 2026, 10, [rotate_section(), blank_section()])

    def test_each_member_is_one_column(self):
        names = [
            col.header for col in self.sheet.columns if col.kind == COL_MEMBER
        ]
        self.assertEqual(names, ["王小明", "李小華", "張大同", "陳小美"])

    def test_each_column_runs_down_the_days_of_the_month(self):
        column = block_named(self.sheet, "大輪番").columns[0]
        self.assertEqual(len(column.cells), self.sheet.day_count)

    def test_the_date_column_counts_from_one_to_the_month_length(self):
        date = header_blocks(self.sheet)[0].columns[0]
        self.assertEqual(date.cells[0].text, "1")
        self.assertEqual(date.cells[-1].text, "31")


class TestBuildSheetErrors(unittest.TestCase):
    def test_no_sections_rejected(self):
        with self.assertRaisesRegex(ValueError, "至少要有一個區塊"):
            build_sheet(UNIT, 2026, 10, [])

    def test_wrong_day_count_rejected(self):
        """拿 10 月（31 天）的資料去組 11 月（30 天）必須擋下來。"""
        section = rotate_section(2026, 10)
        with self.assertRaisesRegex(ValueError, "30 天"):
            build_sheet(UNIT, 2026, 11, [section])


class TestPaperFidelity(unittest.TestCase):
    """整張表與紙本對照（115 年 10 月）。"""

    PAPER_ROW = [
        "12", "休", "休", "15", "16", "17", "18", "休", "休",
        "01", "02", "03", "04", "05", "休", "休", "08",
    ]

    def test_first_column_text_matches_paper(self):
        sheet = build_sheet(UNIT, 2026, 10, [rotate_section(seeds={"王小明": 12})])
        column = block_named(sheet, "大輪番").columns[0]
        self.assertEqual(
            [cell.text for cell in column.cells[: len(self.PAPER_ROW)]],
            self.PAPER_ROW,
        )

    def test_rest_days_are_the_only_red_cells_in_a_member_column(self):
        sheet = build_sheet(UNIT, 2026, 10, [rotate_section(seeds={"王小明": 12})])
        column = block_named(sheet, "大輪番").columns[0]
        for cell in column.cells:
            self.assertEqual(cell.color == RED, cell.text == "休")


if __name__ == "__main__":
    unittest.main()
