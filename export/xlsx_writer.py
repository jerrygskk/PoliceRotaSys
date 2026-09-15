"""版面模型 → A3 橫式 .xlsx（openpyxl）。

與 ``pdf_writer`` 吃同一份 :class:`lib.layout_model.Sheet`，兩邊才會長一樣。

⚠️ **X 軸是人名（欄），Y 軸是日期（列）**。第一版做反了，見 layout_model 的說明。

⚠️ 這裡只負責「把版面模型畫出來」，不做任何排班判斷。要改番號怎麼算請去
``lib/rota.py``；要改表怎麼排請去 ``lib/layout_model.py``。
"""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from lib.layout_model import COL_MEMBER, RED, Sheet

FONT_NAME = "標楷體"
FONT_SIZE = 10
TITLE_FONT_SIZE = 14

HEADER_COL_WIDTH = 5.5     # 日期／星期欄
MEMBER_COL_WIDTH = 5.0     # 姓名欄
TITLE_ROW_HEIGHT = 26
NAME_ROW_HEIGHT = 46       # 姓名直書，要高一點
ROW_HEIGHT = 16

ROW_TITLE = 1
ROW_NAME = 2
ROW_CODE = 3
ROW_FIRST_DAY = 4

_RED = "FFCC0000"
_BLACK = "FF000000"

_THIN = Side(style="thin", color=_BLACK)
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center")
# 姓名直書（Excel 的 textRotation 255 ＝ 直排）。
_VERTICAL = Alignment(horizontal="center", vertical="center", textRotation=255)


def _argb(color: str) -> str:
    return _RED if color == RED else _BLACK





def _setup_page(ws: Worksheet, sheet: Sheet) -> None:
    """A3 橫式、縮成一頁。

    ⚠️ 只設 ``page_setup`` 不夠——還要打開 ``sheetProperties.pageSetUpPr``
    的 fitToPage，否則 Excel 直接忽略縮放設定（PITFALLS XLS-2）。
    """
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True

    for index, column in enumerate(sheet.columns, start=1):
        ws.column_dimensions[get_column_letter(index)].width = (
            MEMBER_COL_WIDTH if column.kind == COL_MEMBER else HEADER_COL_WIDTH
        )


def _write_title(ws: Worksheet, sheet: Sheet, column_count: int) -> None:
    cell = ws.cell(row=ROW_TITLE, column=1, value=sheet.title)
    cell.font = Font(name=FONT_NAME, size=TITLE_FONT_SIZE, bold=True)
    cell.alignment = _CENTER
    ws.merge_cells(
        start_row=ROW_TITLE, start_column=1,
        end_row=ROW_TITLE, end_column=column_count,
    )
    ws.row_dimensions[ROW_TITLE].height = TITLE_ROW_HEIGHT


def _write_column(ws: Worksheet, index: int, column, day_count: int) -> None:
    header = ws.cell(row=ROW_NAME, column=index, value=column.header)
    header.font = Font(
        name=FONT_NAME, size=FONT_SIZE, color=_argb(column.header_color), bold=True
    )
    header.alignment = _VERTICAL if column.kind == COL_MEMBER else _CENTER
    header.border = _BORDER

    code = ws.cell(row=ROW_CODE, column=index, value=column.code or None)
    code.font = Font(name=FONT_NAME, size=FONT_SIZE)
    code.alignment = _CENTER
    code.border = _BORDER

    for day in range(day_count):
        model = column.cells[day]
        cell = ws.cell(row=ROW_FIRST_DAY + day, column=index, value=model.text or None)
        cell.font = Font(name=FONT_NAME, size=FONT_SIZE, color=_argb(model.color))
        cell.alignment = _CENTER
        cell.border = _BORDER


def write_sheet(sheet: Sheet, path: str) -> None:
    """把版面模型寫成 xlsx。"""
    wb = Workbook()
    ws = wb.active
    ws.title = f"{sheet.month}月"

    columns = sheet.columns
    _setup_page(ws, sheet)
    _write_title(ws, sheet, len(columns))

    ws.row_dimensions[ROW_NAME].height = NAME_ROW_HEIGHT
    ws.row_dimensions[ROW_CODE].height = ROW_HEIGHT
    for day in range(sheet.day_count):
        ws.row_dimensions[ROW_FIRST_DAY + day].height = ROW_HEIGHT

    for index, column in enumerate(columns, start=1):
        _write_column(ws, index, column, sheet.day_count)

    # 凍結窗格：捲動時標題列與最左邊的日期欄留在畫面上。
    ws.freeze_panes = ws.cell(row=ROW_FIRST_DAY, column=3)
    wb.save(path)


def member_column_count(sheet: Sheet) -> int:
    """整張表有幾欄是人（測試與版面估算用）。"""
    return sum(1 for column in sheet.columns if column.kind == COL_MEMBER)
