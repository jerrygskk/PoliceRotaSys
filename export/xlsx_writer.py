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
    column_weight,
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
# A3 橫式 1190.55 × 841.92 pt，四邊留 5mm：
#   可列印寬 ≈ 1162pt   可列印高 ≈ 813pt
# Excel 欄寬換算：pt = width × 7 × 0.75（見 _width_to_points）
# 列高同樣按天數分配，31 天與 28 天都要填滿整頁。
#
# 人數更多的單位自然會超出，那時才由 fitToPage 接手縮小。
# ⚠️ 邊界留 5mm 就好。openpyxl 預設左右各 0.75 吋（19mm），A3 橫式兩邊加起來
# 就吃掉 38mm，換算成欄寬是白白少掉一個多人的空間。5mm 是一般雷射印表機的
# 安全下限，再小會有印不到的風險。
MARGIN_INCH = 5.0 / 25.4

A3_W_PT = 1190.55
A3_H_PT = 841.92
_MARGIN_PT = MARGIN_INCH * 72
PRINTABLE_W_PT = A3_W_PT - 2 * _MARGIN_PT
PRINTABLE_H_PT = A3_H_PT - 2 * _MARGIN_PT

# ⚠️ **欄寬是按欄數分配的，不是固定值。**
#
# 派出所人員會調動，欄數每個月都可能不同。欄寬寫死的話：人多了會超出頁寬、
# 被 fitToPage 縮到看不清楚；人少了右邊留一大片空白。所以改成把可列印寬度
# 依權重分給各欄，人多自動變窄、人少自動變寬。
#
# 上下限是為了守住可讀性與美觀：
#   下限 3.8 → 約 20pt，兩位數代碼在 12pt 字下的最小可讀寬度
#   上限 13.0 → 人很少時不要讓格子胖到荒謬（手寫欄位寬一點無妨）
# 欄數多到連下限都排不下時（約 58 欄），才交給 fitToPage 整張縮。
MIN_COL_WIDTH = 3.8
MAX_COL_WIDTH = 13.0

# ⚠️ 欄寬權重在 lib/layout_model.column_weight，與 pdf_writer 共用——
# 兩邊用不同的權重，Excel 印出來就會跟 PDF 不一樣寬。

# ⚠️ **姓名列高度是算出來的，不能寫死。**
#
# 第一版寫死 62pt：三個字的姓名剛好，但「同仁專案臨檢」六個字直書就被切掉，
# 跨欄註記四行也只顯示得出兩行（「中班(17.18)」「限填1人」整個不見）。
# Excel 不會自動縮字，放不下就是切掉，而且**不會有任何警告**。
#
# 所以改成依實際內容算：取「最長的直書標題」與「註記行數」兩者所需高度的
# 較大者。
MIN_NAME_ROW_HEIGHT = 62
VERTICAL_LINE_RATIO = 1.35   # 直書一個字佔的高度 ÷ 字級
NOTE_FONT_SIZE = 9           # 註記字小一級，四行才排得下
NOTE_LINE_RATIO = 1.45
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


def name_row_height(sheet: Sheet) -> float:
    """姓名列要多高才放得下最長的直書標題與最多行的註記。"""
    longest = 0
    for column in sheet.columns:
        if column.kind != COL_TITLE and len(column.header) > 1:
            longest = max(longest, len(column.header))
    needed_header = longest * FONT_SIZE * VERTICAL_LINE_RATIO
    # 沒有小標題的空白欄，標題跨姓名列與代碼列，所以可用高度多了一列。
    needed_header -= CODE_ROW_HEIGHT if _has_spanning_header(sheet) else 0

    most_lines = max((len(b.note) for b in sheet.blocks), default=0)
    needed_note = most_lines * NOTE_FONT_SIZE * NOTE_LINE_RATIO

    return max(MIN_NAME_ROW_HEIGHT, needed_header, needed_note)


def _has_spanning_header(sheet: Sheet) -> bool:
    return any(
        column.kind == COL_BLANK and not column.code for column in sheet.columns
    )


# Excel 欄寬單位換算。
#
# ⚠️ **每欄不要再加 5px 的 padding。**
#
# 常見的公式寫成 `pixels = width × MDW + 5`，那是 Excel UI 顯示「8.43
# (64 像素)」時的算法。**實際版面佔的寬度是 `width × MDW`**——那 5px 在
# Excel 把「可見字元數」換算成儲存值的時候就已經算進去了。
#
# 第一版每欄多加 5px，48 欄就多算了 240px ≈ 64mm：程式以為排滿 410mm，
# Excel 實際只排了 346mm，預覽列印上左右各留了一大片白。現場回報「每格
# 寬度太小」就是這個。
#
# 是拿維護者的預覽列印截圖反推出來的：表格實際佔 346mm，而 48 欄的
# Σwidth × 7px = 1309px = 346mm，剛好吻合。
MAX_DIGIT_WIDTH_PX = 7      # Calibri 11 的最大數字寬（openpyxl 的預設字型）
PX_TO_PT = 0.75             # 96 dpi → 72 pt


def _width_to_points(width: float) -> float:
    return width * MAX_DIGIT_WIDTH_PX * PX_TO_PT


def _points_to_width(points: float) -> float:
    return points / (MAX_DIGIT_WIDTH_PX * PX_TO_PT)


def column_widths(sheet: Sheet) -> list[float]:
    """把可列印寬度依權重分給各欄，並夾在上下限之間。

    ⚠️ **夾到上下限的欄，差額要還給其他欄。**
    第一版夾完就算了，結果窄欄被夾寬時總寬會超出頁寬——40 人時就這樣多出
    3.6pt、整張表被 fitToPage 白白縮小一次。這裡改成反覆重分配：每輪把已經
    夾住的欄固定下來，剩下的寬度再按權重分給還沒夾住的欄，直到穩定。
    """
    weights = [column_weight(column) for column in sheet.columns]
    widths: list[float | None] = [None] * len(weights)

    remaining_pt = PRINTABLE_W_PT
    while True:
        free = [i for i, w in enumerate(widths) if w is None]
        if not free:
            break
        total_weight = sum(weights[i] for i in free)
        per_weight = remaining_pt / total_weight
        clamped = False
        for i in free:
            ideal = _points_to_width(per_weight * weights[i])
            bounded = min(MAX_COL_WIDTH, max(MIN_COL_WIDTH, ideal))
            if bounded != ideal:
                widths[i] = bounded
                remaining_pt -= _width_to_points(bounded)
                clamped = True
        if not clamped:
            for i in free:
                widths[i] = _points_to_width(per_weight * weights[i])
            break

    return [w for w in widths]


def day_row_height(day_count: int, name_height: float = MIN_NAME_ROW_HEIGHT) -> float:
    """日期列高：把剩下的高度分給每一天，讓 28 天的月份也填滿整頁。"""
    body = PRINTABLE_H_PT - name_height - CODE_ROW_HEIGHT
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
    ws.print_options.horizontalCentered = True
    ws.print_options.verticalCentered = True

    # ⚠️ **放得下就固定 100%，不要交給 fitToPage。**
    #
    # 「調整成 1 頁寬 1 頁高」在算頁面分割時比實際保守：現場實測，表格自然
    # 尺寸 410 × 287mm、可列印區也是 410 × 287mm，關掉 fitToPage 用 100%
    # 印出來是紮紮實實的 1/1，但開著 fitToPage 它仍然縮了一級——上下貼滿、
    # **左右白掉一大片**。維護者回報「左右留的空間有點多」就是這個。
    #
    # 欄數真的超出容量時才讓它接手，那時縮小是應該的。
    if fits_in_one_page(sheet):
        ws.sheet_properties.pageSetUpPr.fitToPage = False
        ws.page_setup.fitToWidth = None
        ws.page_setup.fitToHeight = None
        ws.page_setup.scale = 100
    else:
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 1

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
                InlineFont(
                    rFont=FONT_NAME, sz=NOTE_FONT_SIZE, color=_argb(line.color)
                ),
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

    name_height = name_row_height(sheet)
    ws.row_dimensions[ROW_NAME].height = name_height
    ws.row_dimensions[ROW_CODE].height = CODE_ROW_HEIGHT
    row_height = day_row_height(sheet.day_count, name_height)
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

    # ⚠️ 不設凍結窗格（維護者裁示）。這是一張要列印的表，不是拿來捲動看的；
    # 凍結線在畫面上多一條橫槓，反而干擾。
    wb.save(path)


def member_column_count(sheet: Sheet) -> int:
    """整張表有幾欄是人（測試與版面估算用）。"""
    return sum(1 for column in sheet.columns if column.kind == COL_MEMBER)
