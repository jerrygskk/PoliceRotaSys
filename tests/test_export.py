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
from lib.layout_model import Entry, Section, build_sheet
from lib.rota import make_group, rota_month

try:
    from export import pdf_writer
    HAS_QT = True
except ImportError:  # pragma: no cover - 取決於環境
    HAS_QT = False

UNIT = "○○分局○○派出所"
PAPER_REST = {6, 7, 13, 14, 19, 20}


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
    return build_sheet(UNIT, year, month, [rotate, fixed])


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

    def test_page_is_a3_landscape_fit_to_one_page(self):
        # ⚠️ openpyxl 的 PAPERSIZE_A3 是字串 '8'，但存檔再讀回來是 int 8。
        # 直接拿常數比對會得到 8 != '8' 的假失敗，兩邊都轉 int 才對得起來。
        self.assertEqual(
            int(self.ws.page_setup.paperSize), int(self.ws.PAPERSIZE_A3)
        )
        self.assertEqual(self.ws.page_setup.orientation, "landscape")
        self.assertTrue(self.ws.sheet_properties.pageSetUpPr.fitToPage)
        self.assertEqual(self.ws.page_setup.fitToWidth, 1)
        self.assertEqual(self.ws.page_setup.fitToHeight, 1)

    def test_title_is_in_the_first_cell(self):
        self.assertEqual(self.ws["A1"].value, self.sheet.title)

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
        column = self.sheet.blocks[1].columns[5]   # 員06，1 日在第 6 格（休）
        index = self.sheet.columns.index(column) + 1
        cell = self.ws.cell(row=xlsx_writer.ROW_FIRST_DAY, column=index)
        self.assertEqual(cell.value, "00")
        self.assertEqual(cell.font.color.rgb, "FFCC0000")

    def test_weekend_day_cells_are_red_in_the_date_column(self):
        third = self.ws.cell(row=xlsx_writer.ROW_FIRST_DAY + 2, column=1)
        self.assertEqual(third.value, "3")                  # 10/3 週六
        self.assertEqual(third.font.color.rgb, "FFCC0000")
        monday = self.ws.cell(row=xlsx_writer.ROW_FIRST_DAY + 4, column=1)
        self.assertEqual(monday.font.color.rgb, "FF000000")  # 10/5 週一

    def test_blank_section_cells_stay_empty(self):
        """⚠️ 固定番區留白供手填，renderer 不得代填。"""
        column = self.sheet.blocks[3].columns[0]
        index = self.sheet.columns.index(column) + 1
        for day in range(self.sheet.day_count):
            self.assertIsNone(
                self.ws.cell(row=xlsx_writer.ROW_FIRST_DAY + day, column=index).value
            )

    def test_blank_section_still_has_borders(self):
        """留白不等於沒有格線——手寫要有格子可以寫。"""
        column = self.sheet.blocks[3].columns[0]
        index = self.sheet.columns.index(column) + 1
        cell = self.ws.cell(row=xlsx_writer.ROW_FIRST_DAY, column=index)
        self.assertIsNotNone(cell.border.left.style)

    def test_fixed_group_code_is_written(self):
        column = self.sheet.blocks[3].columns[0]
        index = self.sheet.columns.index(column) + 1
        self.assertEqual(
            self.ws.cell(row=xlsx_writer.ROW_CODE, column=index).value, "21"
        )

    def test_member_names_are_written_vertically(self):
        """紙本上姓名是直書。"""
        column = self.sheet.blocks[1].columns[0]
        index = self.sheet.columns.index(column) + 1
        cell = self.ws.cell(row=xlsx_writer.ROW_NAME, column=index)
        self.assertEqual(cell.alignment.textRotation, 255)

    def test_shorter_month_produces_fewer_rows(self):
        path = str(self.dir / "feb.xlsx")
        xlsx_writer.write_sheet(sample_sheet(2025, 2), path)
        self.assertEqual(
            load_workbook(path).active.max_row,
            xlsx_writer.ROW_FIRST_DAY - 1 + 28,
        )


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
