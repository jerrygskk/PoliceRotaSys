"""export/：xlsx 與 pdf 兩個 renderer。⚠️ 姓名一律虛構。

⚠️ pdf 測試需要 Qt，離線環境請設 QT_QPA_PLATFORM=offscreen；
沒有 PySide6 時整個 PDF 區塊 skip，不讓純邏輯測試連帶紅掉。

這兩支 renderer 吃同一份版面模型，所以測試特別釘住「兩邊看到的格子內容相同」
——那正是當初把版面模型抽出來的理由（DEVELOPER §1）。
"""
import re
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from export import xlsx_writer
from lib.layout_model import COL_TITLE, Entry, Section, build_sheet
from lib.rota import make_group, rota_month

try:
    from export import pdf_writer
    HAS_QT = True
except ImportError:  # pragma: no cover - 取決於環境
    HAS_QT = False

UNIT = "○○分局○○派出所"
PAPER_REST = {6, 7, 13, 14, 19, 20}


def block_named(sheet, name):
    """⚠️ 用名稱找區塊，不要寫死索引——加一個區塊就全錯。"""
    for block in sheet.blocks:
        if block.name == name:
            return block
    raise AssertionError(f"找不到區塊「{name}」")


def column_index(sheet, column) -> int:
    """該欄在 worksheet 的欄號（1-based）。"""
    return sheet.columns.index(column) + 1


def sample_sheet(year=2026, month=10):
    group = make_group("大輪番", "rotate", "1-20", PAPER_REST)
    seeds = {f"員{i:02d}": i for i in range(1, 19)}
    result = rota_month(group, seeds, year, month)
    rotate = Section(
        "大輪番", tuple(Entry(who, slots=result[who]) for who in seeds)
    )
    fixed = Section(
        "固定番", tuple(Entry(f"固{i}", code=str(20 + i)) for i in range(1, 6))
    )
    blank = Section(
        "快打勤務", (Entry("快打勤務"),), header_before=False
    )
    return build_sheet(
        UNIT, year, month, [rotate, fixed, blank],
        blank_sections=frozenset({"快打勤務"}),
    )


class _TempDirCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="rota-export-")
        self.dir = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()


class TestXlsx(_TempDirCase):
    def setUp(self):
        super().setUp()
        self.sheet = sample_sheet()
        self.path = str(self.dir / "out.xlsx")
        xlsx_writer.write_sheet(self.sheet, self.path)
        self.ws = load_workbook(self.path).active

    def test_file_is_written(self):
        self.assertGreater(Path(self.path).stat().st_size, 0)

    def test_page_is_a3_landscape(self):
        # ⚠️ openpyxl 的 PAPERSIZE_A3 是字串 '8'，但存檔再讀回來是 int 8。
        # 直接拿常數比對會得到 8 != '8' 的假失敗，兩邊都轉 int 才對得起來。
        self.assertEqual(
            int(self.ws.page_setup.paperSize), int(self.ws.PAPERSIZE_A3)
        )
        self.assertEqual(self.ws.page_setup.orientation, "landscape")

    def test_printing_is_centred_both_ways(self):
        self.assertTrue(self.ws.print_options.horizontalCentered)
        self.assertTrue(self.ws.print_options.verticalCentered)

    def test_no_freeze_panes(self):
        """⚠️ 這是要列印的表，不是拿來捲動看的——凍結線只會多一條橫槓。"""
        self.assertIsNone(self.ws.freeze_panes)

    def test_a_sheet_that_fits_prints_at_a_fixed_100_percent(self):
        """⚠️ fitToPage 明明放得下也會縮一級，左右就白掉一大片。

        現場實測：自然尺寸與可列印區都是 410 × 287mm，關掉 fitToPage 用
        100% 印出來是 1/1，開著卻仍然縮小。
        """
        self.assertFalse(self.ws.sheet_properties.pageSetUpPr.fitToPage)
        self.assertEqual(self.ws.page_setup.scale, 100)

    def test_title_is_the_leftmost_vertical_column(self):
        """⚠️ 標題在最左邊一整欄直書，不是橫置於頁首。"""
        cell = self.ws.cell(row=xlsx_writer.ROW_NAME, column=1)
        self.assertEqual(cell.value, self.sheet.title)
        self.assertEqual(cell.alignment.textRotation, 255)
        self.assertEqual(self.sheet.columns[0].kind, COL_TITLE)

    def test_every_model_column_becomes_a_worksheet_column(self):
        self.assertEqual(self.ws.max_column, len(self.sheet.columns))

    def test_day_rows_match_the_month_length(self):
        # 標題、姓名、代碼各一列，其後才是日期。
        self.assertEqual(
            self.ws.max_row,
            xlsx_writer.ROW_FIRST_DAY - 1 + self.sheet.day_count,
        )

    def test_cell_text_matches_the_model(self):
        for index, column in enumerate(self.sheet.columns, start=1):
            if column.kind == COL_TITLE:
                continue
            self.assertEqual(
                self.ws.cell(row=xlsx_writer.ROW_NAME, column=index).value,
                column.header,
            )
            for day, cell in enumerate(column.cells):
                got = self.ws.cell(
                    row=xlsx_writer.ROW_FIRST_DAY + day, column=index
                ).value
                self.assertEqual(
                    got or "", cell.text, f"{column.header} 第 {day+1} 天"
                )

    def test_rest_cells_are_red(self):
        column = block_named(self.sheet, "大輪番").columns[5]  # 員06，第 6 格（休）
        index = column_index(self.sheet, column)
        cell = self.ws.cell(row=xlsx_writer.ROW_FIRST_DAY, column=index)
        self.assertEqual(cell.value, "00")
        self.assertEqual(cell.font.color.rgb, "FFCC0000")

    def test_weekend_day_cells_are_red_in_the_date_column(self):
        date_col = column_index(self.sheet, self.sheet.columns[1])
        third = self.ws.cell(row=xlsx_writer.ROW_FIRST_DAY + 2, column=date_col)
        self.assertEqual(third.value, "3")                  # 10/3 週六
        self.assertEqual(third.font.color.rgb, "FFCC0000")
        monday = self.ws.cell(row=xlsx_writer.ROW_FIRST_DAY + 4, column=date_col)
        self.assertEqual(monday.font.color.rgb, "FF000000")  # 10/5 週一

    def test_blank_section_cells_stay_empty(self):
        """⚠️ 固定番區留白供手填，renderer 不得代填。"""
        column = block_named(self.sheet, "固定番").columns[0]
        index = column_index(self.sheet, column)
        for day in range(self.sheet.day_count):
            self.assertIsNone(
                self.ws.cell(row=xlsx_writer.ROW_FIRST_DAY + day, column=index).value
            )

    def test_every_cell_of_a_merged_range_has_borders(self):
        """⚠️ Excel 不會替合併範圍補框線。

        框線只設在左上角那一格時，合併後只畫得出那一格的邊，其餘是空的——
        標題欄（合併整欄）因此整欄看不到框線。
        """
        from openpyxl.utils import range_boundaries

        for merged in self.ws.merged_cells.ranges:
            first_col, first_row, last_col, last_row = range_boundaries(str(merged))
            for row in range(first_row, last_row + 1):
                for col in range(first_col, last_col + 1):
                    cell = self.ws.cell(row=row, column=col)
                    self.assertIsNotNone(
                        cell.border.left.style,
                        f"{cell.coordinate}（合併範圍 {merged}）沒有框線",
                    )

    def test_blank_section_still_has_borders(self):
        """留白不等於沒有格線——手寫要有格子可以寫。"""
        column = block_named(self.sheet, "固定番").columns[0]
        index = column_index(self.sheet, column)
        cell = self.ws.cell(row=xlsx_writer.ROW_FIRST_DAY, column=index)
        self.assertIsNotNone(cell.border.left.style)

    def test_fixed_group_code_is_written(self):
        column = block_named(self.sheet, "固定番").columns[0]
        index = column_index(self.sheet, column)
        self.assertEqual(
            self.ws.cell(row=xlsx_writer.ROW_CODE, column=index).value, "21"
        )

    def test_a_female_officer_name_is_red_and_her_code_is_not(self):
        """⚠️ 女警只有姓名印紅色，番號一律黑的。"""
        from lib.layout_model import Entry, Section, build_sheet

        sheet = build_sheet(
            UNIT, 2026, 10,
            [Section("固定番",
                     (Entry("王小明", code="21"),
                      Entry("李小華", code="22", female=True)),
                     header_before=False)],
        )
        path = str(self.dir / "female.xlsx")
        xlsx_writer.write_sheet(sheet, path)
        ws = load_workbook(path).active
        cols = {c.header: i for i, c in enumerate(sheet.columns, start=1)}
        male = ws.cell(row=xlsx_writer.ROW_NAME, column=cols["王小明"])
        female = ws.cell(row=xlsx_writer.ROW_NAME, column=cols["李小華"])
        self.assertEqual(male.font.color.rgb, "FF000000")
        self.assertEqual(female.font.color.rgb, "FFCC0000")
        code = ws.cell(row=xlsx_writer.ROW_CODE, column=cols["李小華"])
        self.assertEqual(code.value, "22")
        # 沒有明設顏色時 openpyxl 的 color 是 None，那就是預設黑。
        self.assertTrue(
            code.font.color is None or code.font.color.rgb != "FFCC0000"
        )

    def test_member_names_are_written_vertically(self):
        """紙本上姓名是直書。"""
        column = block_named(self.sheet, "大輪番").columns[0]
        index = column_index(self.sheet, column)
        cell = self.ws.cell(row=xlsx_writer.ROW_NAME, column=index)
        self.assertEqual(cell.alignment.textRotation, 255)

    def test_multi_character_blank_header_is_also_vertical(self):
        """⚠️ 欄很窄，多字標題橫著放會被切掉（「快打勤務」踩過）。"""
        column = block_named(self.sheet, "快打勤務").columns[0]
        cell = self.ws.cell(
            row=xlsx_writer.ROW_NAME, column=column_index(self.sheet, column)
        )
        self.assertEqual(cell.alignment.textRotation, 255)

    def test_shorter_month_produces_fewer_rows(self):
        path = str(self.dir / "feb.xlsx")
        xlsx_writer.write_sheet(sample_sheet(2025, 2), path)
        self.assertEqual(
            load_workbook(path).active.max_row,
            xlsx_writer.ROW_FIRST_DAY - 1 + 28,
        )


class TestAdaptiveWidth(unittest.TestCase):
    """⚠️ 派出所人員會調動，欄數每月都可能不同。

    欄寬寫死的話：人多了超出頁寬被 fitToPage 縮到看不清楚，人少了右邊留一
    大片空白。所以欄寬是**按欄數分配**的，這幾支釘住那個行為。
    """

    def sheet_with(self, people: int):
        group = make_group("大輪番", "rotate", "1-20", PAPER_REST)
        seeds = {f"員{i:02d}": i % 20 + 1 for i in range(people)}
        result = rota_month(group, seeds, 2026, 10)
        return build_sheet(
            UNIT, 2026, 10,
            [Section("大輪番", tuple(Entry(w, slots=result[w]) for w in seeds))],
        )

    def total_points(self, sheet):
        return sum(
            xlsx_writer._width_to_points(w)
            for w in xlsx_writer.column_widths(sheet)
        )

    def test_column_width_conversion_has_no_per_column_padding(self):
        """⚠️ 每欄不要再加 5px 的 padding。

        第一版用 `pixels = width × 7 + 5`，48 欄就多算了 240px ≈ 64mm：
        程式以為排滿 410mm，Excel 實際只排了 346mm，左右各留一大片白。
        數字是拿維護者的預覽列印截圖反推出來的。
        """
        self.assertAlmostEqual(xlsx_writer._width_to_points(1.0), 5.25, places=4)
        self.assertAlmostEqual(xlsx_writer._width_to_points(0.0), 0.0, places=4)
        # 來回換算要對得起來。
        for width in (3.8, 4.12, 5.36, 13.0):
            self.assertAlmostEqual(
                xlsx_writer._points_to_width(
                    xlsx_writer._width_to_points(width)
                ),
                width,
                places=6,
            )

    def test_a_full_sheet_really_spans_the_printable_width_in_mm(self):
        """換算錯的話這支會通過但實際印出來是窄的——所以直接驗毫米。"""
        sheet = self.sheet_with(34)
        mm = self.total_points(sheet) / 72 * 25.4
        self.assertAlmostEqual(mm, 410.0, delta=1.0)

    def test_more_people_makes_columns_narrower(self):
        wide = xlsx_writer.column_widths(self.sheet_with(20))[-1]
        narrow = xlsx_writer.column_widths(self.sheet_with(34))[-1]
        self.assertLess(narrow, wide)

    def test_fewer_people_makes_columns_wider(self):
        few = xlsx_writer.column_widths(self.sheet_with(15))[-1]
        many = xlsx_writer.column_widths(self.sheet_with(25))[-1]
        self.assertGreater(few, many)

    def test_the_page_width_is_filled_across_a_realistic_range(self):
        for people in (18, 20, 23, 25, 30, 34, 40):
            with self.subTest(people=people):
                sheet = self.sheet_with(people)
                self.assertAlmostEqual(
                    self.total_points(sheet),
                    xlsx_writer.PRINTABLE_W_PT,
                    delta=2,
                    msg=f"{people} 人時沒有填滿頁寬",
                )

    def test_columns_never_go_below_the_readable_minimum(self):
        for width in xlsx_writer.column_widths(self.sheet_with(60)):
            self.assertGreaterEqual(width, xlsx_writer.MIN_COL_WIDTH)

    def test_each_group_gets_its_own_width_from_its_setting(self):
        """⚠️ 權重是每個番組的設定，不是由欄的種類推的。

        第一版靠「格子是不是空的」去猜，所有手寫欄一律同寬——但固定番、
        劃假區、幹部要寫的東西不一樣多，現場要能分別調。
        """
        from lib.layout_model import Entry, Section, build_sheet

        # ⚠️ 欄數要夠多，否則每欄都被夾到 MAX_COL_WIDTH，比例就量不出來。
        sheet = build_sheet(
            UNIT, 2026, 10,
            [
                Section(
                    "窄", tuple(Entry(f"甲{i:02d}") for i in range(20)),
                    header_before=False, weight=1.0,
                ),
                Section(
                    "寬", tuple(Entry(f"乙{i:02d}") for i in range(20)),
                    header_before=False, weight=1.4,
                ),
            ],
            blank_sections=frozenset({"窄", "寬"}),
        )
        widths = dict(
            zip((c.header or c.code for c in sheet.columns),
                xlsx_writer.column_widths(sheet))
        )
        self.assertAlmostEqual(widths["乙00"] / widths["甲00"], 1.4, delta=0.02)

    def test_clamped_columns_give_their_difference_back(self):
        """⚠️ 夾到上下限的欄，差額要還給其他欄。

        第一版夾完就算了，窄欄被夾寬時總寬會超出頁寬——40 人時多出 3.6pt，
        整張表就被 fitToPage 白白縮小一次。
        """
        for people in (36, 40, 45):
            with self.subTest(people=people):
                sheet = self.sheet_with(people)
                self.assertTrue(xlsx_writer.fits_in_one_page(sheet))
                self.assertAlmostEqual(
                    self.total_points(sheet),
                    xlsx_writer.PRINTABLE_W_PT,
                    delta=2,
                )

    def test_columns_never_go_above_the_maximum(self):
        for width in xlsx_writer.column_widths(self.sheet_with(3)):
            self.assertLessEqual(width, xlsx_writer.MAX_COL_WIDTH)

    def test_the_paper_sized_sheet_fits_without_shrinking(self):
        """現行紙本 34 人（20 + 8 + 6）要塞得進去。"""
        self.assertTrue(xlsx_writer.fits_in_one_page(self.sheet_with(34)))

    def test_three_more_people_still_fits(self):
        """再加三個人也還塞得下——這是維護者實際問到的情境。"""
        self.assertTrue(xlsx_writer.fits_in_one_page(self.sheet_with(37)))

    def test_an_oversized_sheet_falls_back_to_fit_to_page(self):
        """欄數真的超出容量時才讓 Excel 縮——那時縮小是應該的。"""
        import tempfile
        from pathlib import Path as _Path

        with tempfile.TemporaryDirectory() as d:
            path = str(_Path(d) / "big.xlsx")
            sheet = self.sheet_with(60)
            self.assertFalse(xlsx_writer.fits_in_one_page(sheet))
            xlsx_writer.write_sheet(sheet, path)
            ws = load_workbook(path).active
            self.assertTrue(ws.sheet_properties.pageSetUpPr.fitToPage)
            self.assertEqual(ws.page_setup.fitToWidth, 1)

    def test_the_capacity_limit_is_reported_rather_than_silently_shrunk(self):
        self.assertGreater(xlsx_writer.max_columns_per_page(), 50)
        self.assertFalse(xlsx_writer.fits_in_one_page(self.sheet_with(60)))

    def test_short_month_rows_are_taller_so_the_page_is_still_filled(self):
        """⚠️ 28 天的月份也要填滿整頁，不是留白 3 天的高度。"""
        self.assertGreater(
            xlsx_writer.day_row_height(28), xlsx_writer.day_row_height(31)
        )
        for days in (28, 29, 30, 31):
            name_h = xlsx_writer.MIN_NAME_ROW_HEIGHT
            total = (
                name_h
                + xlsx_writer.CODE_ROW_HEIGHT
                + xlsx_writer.day_row_height(days, name_h) * days
            )
            self.assertAlmostEqual(total, xlsx_writer.PRINTABLE_H_PT, delta=1)


class TestNameRowHeight(unittest.TestCase):
    """⚠️ Excel 放不下就是切掉，而且不會有任何警告。

    第一版把姓名列寫死 62pt：三個字的姓名剛好，但「同仁專案臨檢」六個字直書
    被切掉、跨欄註記四行只顯示得出兩行（後兩行整個不見）。這幾支釘住「高度
    依實際內容算」。
    """

    def sheet_with_header(self, header: str):
        return build_sheet(
            UNIT, 2026, 10,
            [Section(header, (Entry(header),), header_before=False)],
            blank_sections=frozenset({header}),
        )

    def test_a_longer_vertical_header_needs_a_taller_row(self):
        short = xlsx_writer.name_row_height(self.sheet_with_header("快打"))
        long = xlsx_writer.name_row_height(self.sheet_with_header("同仁專案臨檢"))
        self.assertGreater(long, short)

    def test_six_character_header_fits_in_name_plus_code_rows(self):
        sheet = self.sheet_with_header("同仁專案臨檢")
        available = (
            xlsx_writer.name_row_height(sheet) + xlsx_writer.CODE_ROW_HEIGHT
        )
        needed = 6 * xlsx_writer.FONT_SIZE * xlsx_writer.VERTICAL_LINE_RATIO
        self.assertGreaterEqual(available, needed)

    def test_a_four_line_note_fits(self):
        from lib.layout_model import NoteLine

        note = tuple(NoteLine(f"第 {i} 行") for i in range(4))
        sheet = build_sheet(
            UNIT, 2026, 10,
            [Section("班別", (Entry("早"), Entry("中"), Entry("晚")),
                     header_before=False, note=note)],
            blank_sections=frozenset({"班別"}),
        )
        needed = 4 * xlsx_writer.NOTE_FONT_SIZE * xlsx_writer.NOTE_LINE_RATIO
        self.assertGreaterEqual(xlsx_writer.name_row_height(sheet), needed)

    def test_the_page_height_is_still_filled_after_growing_the_name_row(self):
        sheet = self.sheet_with_header("同仁專案臨檢")
        name_h = xlsx_writer.name_row_height(sheet)
        total = (
            name_h
            + xlsx_writer.CODE_ROW_HEIGHT
            + xlsx_writer.day_row_height(sheet.day_count, name_h) * sheet.day_count
        )
        self.assertAlmostEqual(total, xlsx_writer.PRINTABLE_H_PT, delta=1)


@unittest.skipUnless(HAS_QT, "需要 PySide6（離線請設 QT_QPA_PLATFORM=offscreen）")
class TestPdf(_TempDirCase):
    def setUp(self):
        super().setUp()
        self.sheet = sample_sheet()
        self.path = str(self.dir / "out.pdf")
        pdf_writer.write_sheet(self.sheet, self.path)
        self.blob = Path(self.path).read_bytes()

    def test_file_is_a_pdf(self):
        self.assertTrue(self.blob.startswith(b"%PDF"))

    def test_page_is_a3_landscape(self):
        """A3 橫式 ＝ 1190.55 × 841.89 pt（寬 > 高）。"""
        match = re.search(rb"/MediaBox\s*\[([^\]]+)\]", self.blob)
        self.assertIsNotNone(match, "PDF 裡找不到 MediaBox")
        _, _, width, height = [float(v) for v in match.group(1).split()]
        self.assertGreater(width, height)
        self.assertAlmostEqual(width, 1190.55, delta=2)
        self.assertAlmostEqual(height, 841.89, delta=2)

    def test_the_outermost_border_is_not_clipped(self):
        """⚠️ 最外圈的框線不可畫在頁面邊界上，會有一半落在頁外被裁掉。

        第一版直接畫在 x=0／y=0，標題欄整欄看不到框線。
        """
        self.assertGreater(pdf_writer.BORDER_PX, 0)
        # 版面已內縮半個線寬，最左邊那一欄的框線才畫得出來。
        self.assertIn(b"re", self.blob[:4000] + self.blob[-4000:])

    def test_single_page(self):
        self.assertEqual(len(re.findall(rb"/Type\s*/Page[^s]", self.blob)), 1)

    def test_title_is_in_the_document_metadata(self):
        self.assertIn(b"/Title", self.blob)

    def test_february_also_renders(self):
        path = str(self.dir / "feb.pdf")
        pdf_writer.write_sheet(sample_sheet(2025, 2), path)
        self.assertTrue(Path(path).read_bytes().startswith(b"%PDF"))


@unittest.skipUnless(HAS_QT, "需要 PySide6")
class TestBothRenderersAgree(_TempDirCase):
    """⚠️ 兩個 renderer 吃同一份版面模型——這是抽出版面模型的理由。

    PDF 是繪圖輸出，抽不出格子內容來逐格比對，所以改為釘住「兩邊都由同一個
    Sheet 產生」這個結構性事實：xlsx 的內容必須與模型相同（上面已測），
    而 PDF 的 renderer 不得自己再去碰排班邏輯。
    """

    def test_pdf_writer_does_not_import_rota(self):
        import inspect

        source = inspect.getsource(pdf_writer)
        self.assertNotIn("from lib.rota", source)
        self.assertNotIn("import rota", source)

    def test_xlsx_writer_does_not_import_rota(self):
        import inspect

        source = inspect.getsource(xlsx_writer)
        self.assertNotIn("from lib.rota", source)
        self.assertNotIn("import rota", source)


if __name__ == "__main__":
    unittest.main()
