"""lib/layout_model.py 的單元測試。⚠️ 姓名一律虛構。"""
import unittest

from lib.layout_model import (
    BLACK,
    RED,
    ROW_DATE,
    ROW_MEMBER,
    ROW_WEEKDAY,
    Entry,
    Section,
    build_sheet,
    is_weekend,
    roc_year,
    sheet_title,
)
from lib.rota import make_group, rota_month

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

    def test_header_repeats_before_and_after_every_block(self):
        """⚠️ 紙本既有設計：A3 很寬，沒有重複標頭就得拿尺對格子。"""
        kinds = [b.is_header for b in self.sheet.blocks]
        self.assertEqual(kinds, [True, False, True, False, True])

    def test_every_row_has_one_cell_per_day(self):
        for row in self.sheet.rows:
            self.assertEqual(len(row.cells), 31, row.label)

    def test_rest_cells_are_red_double_zero(self):
        row = self.sheet.blocks[1].rows[0]      # 王小明，1 日在第 12 格
        self.assertEqual(row.cells[1].text, "00")
        self.assertEqual(row.cells[1].color, RED)

    def test_duty_cells_are_black(self):
        row = self.sheet.blocks[1].rows[0]
        self.assertEqual(row.cells[0].text, "12")
        self.assertEqual(row.cells[0].color, BLACK)

    def test_weekend_columns_are_red_in_both_header_rows(self):
        header = self.sheet.blocks[0]
        date, weekday = header.rows
        self.assertEqual(date.kind, ROW_DATE)
        self.assertEqual(weekday.kind, ROW_WEEKDAY)
        self.assertEqual(date.cells[2].color, RED)      # 10/3 週六
        self.assertEqual(weekday.cells[2].text, "六")
        self.assertEqual(weekday.cells[2].color, RED)
        self.assertEqual(date.cells[4].color, BLACK)    # 10/5 週一

    def test_blank_section_rows_are_empty_but_still_sized(self):
        """⚠️ 固定番與幹部區刻意留白供手填，程式不要自作聰明去填。"""
        block = self.sheet.blocks[3]
        self.assertEqual(block.name, "固定番")
        for row in block.rows:
            self.assertEqual(len(row.cells), 31)
            self.assertTrue(all(cell.text == "" for cell in row.cells))

    def test_blank_section_rows_keep_their_code(self):
        self.assertEqual(self.sheet.blocks[3].rows[0].code, "21")

    def test_member_rows_are_marked_as_such(self):
        self.assertTrue(
            all(row.kind == ROW_MEMBER for row in self.sheet.blocks[1].rows)
        )

    def test_custom_rest_code_is_honoured(self):
        sheet = build_sheet(UNIT, 2026, 10, [rotate_section()], rest_code="休")
        self.assertEqual(sheet.blocks[1].rows[0].cells[1].text, "休")


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
        "12", "00", "00", "15", "16", "17", "18", "00", "00",
        "01", "02", "03", "04", "05", "00", "00", "08",
    ]

    def test_first_row_text_matches_paper(self):
        sheet = build_sheet(UNIT, 2026, 10, [rotate_section(seeds={"王小明": 12})])
        row = sheet.blocks[1].rows[0]
        self.assertEqual(
            [cell.text for cell in row.cells[: len(self.PAPER_ROW)]],
            self.PAPER_ROW,
        )

    def test_rest_days_are_the_only_red_cells_in_a_member_row(self):
        sheet = build_sheet(UNIT, 2026, 10, [rotate_section(seeds={"王小明": 12})])
        row = sheet.blocks[1].rows[0]
        for cell in row.cells:
            self.assertEqual(cell.color == RED, cell.text == "00")


if __name__ == "__main__":
    unittest.main()
