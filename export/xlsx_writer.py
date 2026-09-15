"""版面模型 → A3 橫式 .xlsx（openpyxl）。

與 ``pdf_writer`` 吃同一份 :class:`lib.layout_model.Sheet`，兩邊才會長一樣。

⚠️ **X 軸是人名（欄），Y 軸是日期（列）**。第一版做反了，見 layout_model 的說明。

⚠️ 這裡只負責「把版面模型畫出來」，不做任何排班判斷。要改番號怎麼算請去
``lib/rota.py``；要改表怎麼排請去 ``lib/layout_model.py``。
"""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.worksheet.page import PageMargins
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from lib.layout_model import (
    BLUE,
    COL_BLANK,
    COL_MEMBER,
    COL_TITLE,
    RED,
    Block,
    Sheet,
)

FONT_NAME = "標楷體"
FONT_SIZE = 12
TITLE_FONT_SIZE = 18

# ⚠️ 版面尺寸是**算出來的，不是猜的**——目標是自然尺寸剛好貼近 A3 橫式的
# 可列印區，讓 fitToPage 幾乎不用縮。
#
# 第一版沒算，欄寬加總超過頁寬、列高加總只有頁高的七成，結果是：Excel 依
# 寬度把整張表縮小（fitToPage **只會縮不會放**），字跟著變小，而下面留了
# 一大片空白。現場回報「字太小」。
#
# A3 橫式 1190.55 × 841.92 pt，四邊留 0.4 吋（28.8pt）：
#   可列印寬 ≈ 1133pt   可列印高 ≈ 784pt
# Excel 欄寬換算：pt = (7 × width + 5) × 0.75
#   日期／星期欄 4.2 → 25.8pt；姓名欄 5.0 → 30.0pt
# 列高同樣按天數分配，31 天與 28 天都要填滿整頁。
#
# 人數更多的單位自然會超出，那時才由 fitToPage 接手縮小。
MARGIN_INCH = 0.4

# A3 橫式 1190.55 × 841.92 pt，四邊留 0.4 吋（28.8pt）。
PRINTABLE_W_PT = 1190.55 - 2 * 28.8
PRINTABLE_H_PT = 841.92 - 2 * 28.8

# ⚠️ **欄寬是按欄數分配的，不是固定值。**
#
# 派出所人員會調動，欄數每個月都可能不同。欄寬寫死的話：人多了會超出頁寬、
# 被 fitToPage 縮到看不清楚；人少了右邊留一大片空白。所以改成把可列印寬度
# 依權重分給各欄，人多自動變窄、人少自動變寬。
#
# 上下限是為了守住可讀性與美觀：
#   下限 3.0 → 約 19.5pt，兩位數代碼在 12pt 字下的最小可讀寬度
#   上限 10.0 → 人很少時不要讓格子胖到荒謬（手寫欄位寬一點無妨）
# 欄數多到連下限都排不下時（約 58 欄），才交給 fitToPage 整張縮。
MIN_COL_WIDTH = 3.0
MAX_COL_WIDTH = 10.0

# 欄寬權重：日期／星期欄與標題欄比資料欄寬一點。
TITLE_COL_WEIGHT = 1.0
HEADER_COL_WEIGHT = 0.85
MEMBER_COL_WEIGHT = 1.0

NAME_ROW_HEIGHT = 62       # 姓名直書三個字要放得下
CODE_ROW_HEIGHT = 20

# ⚠️ 沒有橫向標題列——標題是**最左邊那一整欄直書**（照紙本）。
ROW_NAME = 1
ROW_CODE = 2
ROW_FIRST_DAY = 3

_RED = "FFCC0000"
_BLUE = "FF1F4E9C"
_BLACK = "FF000000"

_THIN = Side(style="thin", color=_BLACK)
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center")
# 姓名直書（Excel 的 textRotation 255 ＝ 直排）。
_VERTICAL = Alignment(horizontal="center", vertical="center", textRotation=255)
_NOTE = Alignment(horizontal="left", vertical="center", wrap_text=True)


def _width_to_points(width: float) -> float:
    """Excel 欄寬換算成點。pt = (7 × width + 5) × 0.75。"""
    return (7 * width + 5) * 0.75


def _points_to_width(points: float) -> float:
    return (points / 0.75 - 5) / 7


def _column_weight(kind: str) -> float:
    if kind == COL_TITLE:
        return TITLE_COL_WEIGHT
    if kind in (COL_MEMBER, COL_BLANK):
        return MEMBER_COL_WEIGHT
    return HEADER_COL_WEIGHT


def column_widths(sheet: Sheet) -> list[float]:
    """把可列印寬度依權重分給各欄，並夾在上下限之間。"""
    weights = [_column_weight(column.kind) for column in sheet.columns]
    per_weight = PRINTABLE_W_PT / sum(weights)
    return [
        min(MAX_COL_WIDTH, max(MIN_COL_WIDTH, _points_to_width(per_weight * w)))
        for w in weights
    ]


def day_row_height(day_count: int) -> float:
    """日期列高：把剩下的高度分給每一天，讓 28 天的月份也填滿整頁。"""
    body = PRINTABLE_H_PT - NAME_ROW_HEIGHT - CODE_ROW_HEIGHT
    return body / day_count


def fits_in_one_page(sheet: Sheet) -> bool:
    """欄數是否還排得下——False 表示要靠 fitToPage 整張縮小。"""
    return sum(_width_to_points(w) for w in column_widths(sheet)) <= PRINTABLE_W_PT + 1


def max_columns_per_page() -> int:
    """在最小欄寬下，一頁最多放得下幾欄。"""
    return int(PRINTABLE_W_PT // _width_to_points(MIN_COL_WIDTH))


def _argb(color: str) -> str:
    if color == RED:
        return _RED
    if color == BLUE:
        return _BLUE
    return _BLACK





def _setup_page(ws: Worksheet, sheet: Sheet) -> None:
    """A3 橫式、縮成一頁。

    ⚠️ 只設 ``page_setup`` 不夠——還要打開 ``sheetProperties.pageSetUpPr``
    的 fitToPage，否則 Excel 直接忽略縮放設定（PITFALLS XLS-2）。
    """
    ws.page_margins = PageMargins(
        left=MARGIN_INCH, right=MARGIN_INCH,
        top=MARGIN_INCH, bottom=MARGIN_INCH,
        header=0, footer=0,
    )
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True

    for index, width in enumerate(column_widths(sheet), start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


def _write_note(ws: Worksheet, first: int, block: Block) -> None:
    """區塊註記：跨該區塊所有欄的合併格，逐行不同顏色。

    ⚠️ openpyxl 一個儲存格只能有一種字型，**做不到一格內多色**。紙本上那段
    班別說明是逐行不同色的，所以在 xlsx 走 RichText（``CellRichText``），
    才能照抄顏色。
    """
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    from openpyxl.cell.text import InlineFont

    last = first + len(block.columns) - 1
    parts = []
    for i, line in enumerate(block.note):
        text = line.text if i == len(block.note) - 1 else line.text + "\n"
        parts.append(
            TextBlock(
                InlineFont(rFont=FONT_NAME, sz=FONT_SIZE, color=_argb(line.color)),
                text,
            )
        )
    cell = ws.cell(row=ROW_NAME, column=first, value=CellRichText(*parts))
    cell.alignment = _NOTE
    cell.border = _BORDER
    if last > first:
        ws.merge_cells(
            start_row=ROW_NAME, start_column=first,
            end_row=ROW_NAME, end_column=last,
        )


def _write_title_column(ws: Worksheet, index: int, sheet: Sheet) -> None:
    """最左邊那一整欄：直書標題，從姓名列一路合併到最後一天。"""
    last = ROW_FIRST_DAY - 1 + sheet.day_count
    cell = ws.cell(row=ROW_NAME, column=index, value=sheet.title)
    cell.font = Font(name=FONT_NAME, size=TITLE_FONT_SIZE, bold=True)
    cell.alignment = _VERTICAL
    cell.border = _BORDER
    ws.merge_cells(
        start_row=ROW_NAME, start_column=index, end_row=last, end_column=index
    )


def _write_column(
    ws: Worksheet, index: int, column, day_count: int, skip_name: bool = False
) -> None:
    """``skip_name`` 為真時不畫姓名列——那一格被區塊註記的合併格佔走了。"""
    if not skip_name:
        header = ws.cell(row=ROW_NAME, column=index, value=column.header or None)
        header.font = Font(
            name=FONT_NAME, size=FONT_SIZE,
            color=_argb(column.header_color), bold=True,
        )
        # ⚠️ 欄很窄，多字標題橫著放會被切掉（「快打勤務」「日期」都踩過）
        # ——只要超過一個字就直書。
        header.alignment = _VERTICAL if len(column.header) > 1 else _CENTER
        header.border = _BORDER

        # 沒有小標題的欄（同仁專案臨檢、快打勤務），標題跨姓名列與代碼列，
        # 照紙本的合併方式。
        if not column.code and column.kind in (COL_BLANK, COL_TITLE):
            ws.merge_cells(
                start_row=ROW_NAME, start_column=index,
                end_row=ROW_CODE, end_column=index,
            )
        else:
            code = ws.cell(row=ROW_CODE, column=index, value=column.code or None)
            code.font = Font(name=FONT_NAME, size=FONT_SIZE,
                             color=_argb(column.header_color))
            code.alignment = _CENTER
            code.border = _BORDER
    else:
        code = ws.cell(row=ROW_CODE, column=index, value=column.code or None)
        code.font = Font(name=FONT_NAME, size=FONT_SIZE, color=_RED)
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

    ws.row_dimensions[ROW_NAME].height = NAME_ROW_HEIGHT
    ws.row_dimensions[ROW_CODE].height = CODE_ROW_HEIGHT
    row_height = day_row_height(sheet.day_count)
    for day in range(sheet.day_count):
        ws.row_dimensions[ROW_FIRST_DAY + day].height = row_height

    index = 1
    for block in sheet.blocks:
        if block.note:
            _write_note(ws, index, block)
        for column in block.columns:
            if column.kind == COL_TITLE:
                _write_title_column(ws, index, sheet)
            else:
                _write_column(
                    ws, index, column, sheet.day_count, skip_name=bool(block.note)
                )
            index += 1

    # 凍結窗格：捲動時姓名列與最左邊的標題／日期欄留在畫面上。
    ws.freeze_panes = ws.cell(row=ROW_FIRST_DAY, column=4)
    wb.save(path)


def member_column_count(sheet: Sheet) -> int:
    """整張表有幾欄是人（測試與版面估算用）。"""
    return sum(1 for column in sheet.columns if column.kind == COL_MEMBER)
