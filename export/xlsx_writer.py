"""版面模型 → A3 橫式 .xlsx（openpyxl）。

與 ``pdf_writer`` 吃同一份 :class:`lib.layout_model.Sheet`，兩邊才會長一樣。

⚠️ 這裡只負責「把版面模型畫出來」，不做任何排班判斷。要改番號怎麼算請去
``lib/rota.py``；要改表怎麼排請去 ``lib/layout_model.py``。
"""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from lib.layout_model import RED, ROW_MEMBER, Sheet

PAPER_A3 = "A3"
FONT_NAME = "標楷體"
FONT_SIZE = 10
TITLE_FONT_SIZE = 14

# 欄寬：第 1 欄放姓名、第 2 欄放代碼，其餘 31 欄是日期格。
LABEL_COL_WIDTH = 12
CODE_COL_WIDTH = 5
DAY_COL_WIDTH = 3.2
ROW_HEIGHT = 18

_RED = "FFCC0000"
_BLACK = "FF000000"

_THIN = Side(style="thin", color=_BLACK)
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center")


def _argb(color: str) -> str:
    return _RED if color == RED else _BLACK


def _setup_page(ws: Worksheet, day_count: int) -> None:
    """A3 橫式、單頁。

    ⚠️ ``fitToHeight = False`` 不夠——還要把 ``sheetProperties.pageSetUpPr``
    的 fitToPage 打開，否則 Excel 不會理會縮放設定。
    """
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True

    ws.column_dimensions["A"].width = LABEL_COL_WIDTH
    ws.column_dimensions["B"].width = CODE_COL_WIDTH
    for index in range(3, 3 + day_count):
        ws.column_dimensions[get_column_letter(index)].width = DAY_COL_WIDTH


def _write_title(ws: Worksheet, sheet: Sheet) -> int:
    ws.cell(row=1, column=1, value=sheet.title).font = Font(
        name=FONT_NAME, size=TITLE_FONT_SIZE, bold=True
    )
    ws.merge_cells(
        start_row=1, start_column=1, end_row=1, end_column=2 + sheet.day_count
    )
    ws.cell(row=1, column=1).alignment = _CENTER
    ws.row_dimensions[1].height = 26
    return 2


def _write_row(ws: Worksheet, excel_row: int, row, day_count: int) -> None:
    ws.row_dimensions[excel_row].height = ROW_HEIGHT

    label = ws.cell(row=excel_row, column=1, value=row.label)
    label.font = Font(name=FONT_NAME, size=FONT_SIZE, color=_argb(row.label_color))
    label.alignment = _CENTER
    label.border = _BORDER

    code = ws.cell(row=excel_row, column=2, value=row.code or None)
    code.font = Font(name=FONT_NAME, size=FONT_SIZE)
    code.alignment = _CENTER
    code.border = _BORDER

    for offset in range(day_count):
        cell_model = row.cells[offset]
        cell = ws.cell(row=excel_row, column=3 + offset, value=cell_model.text or None)
        cell.font = Font(
            name=FONT_NAME, size=FONT_SIZE, color=_argb(cell_model.color)
        )
        cell.alignment = _CENTER
        cell.border = _BORDER


def write_sheet(sheet: Sheet, path: str) -> None:
    """把版面模型寫成 xlsx。"""
    wb = Workbook()
    ws = wb.active
    ws.title = f"{sheet.month}月"

    _setup_page(ws, sheet.day_count)
    excel_row = _write_title(ws, sheet)

    for block in sheet.blocks:
        for row in block.rows:
            _write_row(ws, excel_row, row, sheet.day_count)
            excel_row += 1

    # 凍結窗格：捲動時姓名欄與標題留在畫面上。
    ws.freeze_panes = "C3"
    wb.save(path)


def member_row_count(sheet: Sheet) -> int:
    """整張表有幾列是人（測試與版面估算用）。"""
    return sum(1 for row in sheet.rows if row.kind == ROW_MEMBER)
