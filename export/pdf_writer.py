"""版面模型 → A3 橫式 .pdf（Qt 的 QPdfWriter）。

與 ``xlsx_writer`` 吃同一份 :class:`lib.layout_model.Sheet`，兩邊才會長一樣。

⚠️ **X 軸是人名（欄），Y 軸是日期（列）**。第一版做反了，見 layout_model 的說明。

⚠️ **用 QPdfWriter 而不是 reportlab**：PySide6 已經在包裡，PDF 等於免費附贈；
多拉一個套件進來只是多一段開機解壓時間（CLAUDE.md §B 的封閉相依清單）。

⚠️ 匯出 PDF 不需要完整的 QApplication，但**需要 QGuiApplication** 才能量字。
本模組自己確保有一個（離線環境請設 ``QT_QPA_PLATFORM=offscreen``）。
"""
from __future__ import annotations

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
)

from lib.layout_model import (
    BLUE,
    COL_BLANK,
    COL_MEMBER,
    COL_TITLE,
    RED,
    Sheet,
    column_weight,
)

RESOLUTION = 300          # dpi

# ⚠️ 框線要有明確寬度並把整張表**往內縮半個線寬**。
#
# 第一版用預設的 cosmetic pen 直接畫在 x=0／y=0，最外圈那條線有一半落在頁面
# 外被裁掉——標題欄因此整欄看不到框線（現場回報「格線自己不見」）。
BORDER_PX = 2.0
# ⚠️ 邊界留 5mm 就好——留太多等於把欄寬白白讓掉。5mm 是一般雷射印表機
# 的安全下限，再小會有印不到的風險。
MARGIN_MM = 5.0

# ⚠️ **字級由格子幾何算出來，不要寫死點數。**
#
# 第一版寫死 7pt，與格子大小無關。格子會隨人數變、字型換一支字寬就變，
# 字級不跟著走就會爆版——容器沒有標楷體，用替代字型看起來還好，換到
# 真的有標楷體的機器上就不是這麼回事。現場回報「慘不忍睹」。
#
# 一律用 setPixelSize（裝置單位），不用 setPointSize：QPdfWriter 是
# 300dpi 的繪圖裝置，用像素才算得準格子塞不塞得下。
BODY_HEIGHT_RATIO = 0.58   # 字高佔格高的比例
BODY_WIDTH_RATIO = 0.42    # 兩字寬的代碼要塞進格寬

# 字型：標楷體優先，找不到時依序退回。
# ⚠️ 不要只寫一支——沒有那支字型時 Qt 會靜默換成系統預設，字寬全走鐘。
FONT_FAMILIES = ("標楷體", "DFKai-SB", "Microsoft JhengHei", "Noto Sans CJK TC")

# ⚠️ 欄寬權重在 lib/layout_model.column_weight，兩個 renderer 共用。

# ⚠️ 沒有橫向標題列——標題是最左邊那一整欄直書（照紙本）。
NAME_RATIO = 0.085
CODE_RATIO = 0.028


def _ensure_app() -> None:
    if QGuiApplication.instance() is None:
        QGuiApplication([])


def _qcolor(color: str) -> QColor:
    if color == RED:
        return QColor("#cc0000")
    if color == BLUE:
        return QColor("#1f4e9c")
    return QColor("#000000")


def _font(pixel_size: float, bold: bool = False) -> QFont:
    font = QFont(FONT_FAMILIES[0])
    font.setFamilies(list(FONT_FAMILIES))
    font.setPixelSize(max(1, int(pixel_size)))
    font.setBold(bold)
    return font


def write_sheet(sheet: Sheet, path: str) -> None:
    """把版面模型畫成 A3 橫式單頁 PDF。"""
    _ensure_app()

    writer = QPdfWriter(path)
    writer.setResolution(RESOLUTION)
    writer.setPageSize(QPageSize(QPageSize.A3))
    writer.setPageOrientation(QPageLayout.Landscape)
    writer.setPageMargins(
        QMarginsF(MARGIN_MM, MARGIN_MM, MARGIN_MM, MARGIN_MM),
        QPageLayout.Millimeter,
    )
    writer.setTitle(sheet.title)

    painter = QPainter(writer)
    try:
        inset = BORDER_PX / 2
        page = QRectF(0, 0, writer.width(), writer.height()).adjusted(
            inset, inset, -inset, -inset
        )
        painter.setPen(QPen(QColor("#000000"), BORDER_PX))
        _paint(painter, page, sheet)
    finally:
        painter.end()


def _paint(painter: QPainter, page: QRectF, sheet: Sheet) -> None:
    columns = sheet.columns
    if not columns:
        return

    name_h = page.height() * NAME_RATIO
    code_h = page.height() * CODE_RATIO
    body_h = page.height() - name_h - code_h
    row_h = body_h / sheet.day_count

    weight_of = column_weight
    weights = [weight_of(column) for column in columns]
    unit_w = page.width() / sum(weights)

    # ⚠️ **字級由資料欄決定，不要被最窄的那一欄拖下去。**
    #
    # 第一版拿「所有欄裡最窄的」算字級——那是日期／星期欄（權重最小），
    # 結果整張表的字都被那兩欄壓小。現場回報「PDF 字太小」就是這個。
    # 日期／星期欄自己用自己的字級（它們只放一兩個字）。
    data_weights = [
        weight_of(column)
        for column in columns
        if column.kind in (COL_MEMBER, COL_BLANK)
    ] or weights
    body_px = min(
        row_h * BODY_HEIGHT_RATIO, unit_w * min(data_weights) * BODY_WIDTH_RATIO
    )
    header_px = min(
        row_h * BODY_HEIGHT_RATIO,
        unit_w * min(weights) * BODY_WIDTH_RATIO,
    )

    x = page.left()
    for block in sheet.blocks:
        block_w = sum(
            unit_w * weight_of(column) for column in block.columns
        )
        if block.note:
            _paint_note(
                painter, QRectF(x, page.top(), block_w, name_h), block.note, body_px
            )

        for column in block.columns:
            width = unit_w * weight_of(column)
            if column.kind == COL_TITLE:
                _paint_title_column(
                    painter, QRectF(x, page.top(), width, page.height()),
                    sheet.title, body_px,
                )
                x += width
                continue

            cell_px = (
                header_px
                if column.kind not in (COL_MEMBER, COL_BLANK)
                else body_px
            )
            painter.setFont(_font(cell_px))
            if not block.note:
                header_rect = QRectF(x, page.top(), width, name_h)
                # 沒有小標題的欄（同仁專案臨檢、快打勤務），標題跨姓名列與
                # 代碼列，照紙本的合併方式。
                if not column.code and column.kind == COL_BLANK:
                    header_rect = QRectF(x, page.top(), width, name_h + code_h)
                # ⚠️ 欄很窄，多字標題橫著放會被切掉（「快打勤務」「日期」都
                # 踩過）——只要超過一個字就直書。
                if len(column.header) > 1:
                    _paint_vertical_header(
                        painter, header_rect, column, body_px, width
                    )
                else:
                    _paint_cell(
                        painter, header_rect, column.header, column.header_color
                    )
                if column.code or column.kind != COL_BLANK:
                    painter.setFont(_font(cell_px))
                    _paint_cell(
                        painter,
                        QRectF(x, page.top() + name_h, width, code_h),
                        column.code,
                        column.header_color,
                    )
            else:
                _paint_cell(
                    painter,
                    QRectF(x, page.top() + name_h, width, code_h),
                    column.code,
                    RED,
                )

            painter.setFont(_font(cell_px))
            top = page.top() + name_h + code_h
            for day, cell in enumerate(column.cells):
                _paint_cell(
                    painter,
                    QRectF(x, top + day * row_h, width, row_h),
                    cell.text,
                    cell.color,
                )
            x += width


def _paint_note(painter: QPainter, rect: QRectF, note, body_px: float) -> None:
    """區塊註記：跨整個區塊的合併格，逐行不同顏色（照紙本）。"""
    painter.setPen(_border_pen())
    painter.drawRect(rect)
    if not note:
        return
    line_h = rect.height() / max(1, len(note))
    usable = rect.width() * 0.92

    # ⚠️ 字級要依**最長那一行**縮，只看行高會讓長行右邊被切掉
    # （「晚班:(1-5、16)」的收尾括號就這樣不見過）。
    size = min(body_px, line_h * 0.62)
    longest = max(note, key=lambda line: len(line.text)).text
    while size > 4:
        painter.setFont(_font(size))
        if painter.fontMetrics().horizontalAdvance(longest) <= usable:
            break
        size -= 0.5
    painter.setFont(_font(size))

    for index, line in enumerate(note):
        painter.setPen(_qcolor(line.color))
        painter.drawText(
            QRectF(
                rect.left() + rect.width() * 0.04,
                rect.top() + index * line_h,
                rect.width() * 0.92,
                line_h,
            ),
            int(Qt.AlignLeft | Qt.AlignVCenter),
            line.text,
        )


def _paint_title_column(
    painter: QPainter, rect: QRectF, title: str, body_px: float
) -> None:
    """最左邊那一整欄：直書標題，跨全高。"""
    painter.setPen(_border_pen())
    painter.drawRect(rect)
    if not title:
        return
    per_char = min(rect.width() * 0.8, rect.height() / max(1, len(title)))
    painter.setFont(_font(min(body_px * 1.3, per_char * 0.9), bold=True))
    metrics = painter.fontMetrics()
    line_h = max(metrics.height(), per_char * 0.95)
    top = rect.top() + max(0.0, (rect.height() - line_h * len(title)) / 2)
    for index, char in enumerate(title):
        painter.drawText(
            QRectF(rect.left(), top + index * line_h, rect.width(), line_h),
            Qt.AlignCenter,
            char,
        )


def _border_pen() -> QPen:
    return QPen(QColor("#000000"), BORDER_PX)


def _paint_cell(painter: QPainter, rect: QRectF, text: str, color: str) -> None:
    painter.setPen(_border_pen())
    painter.drawRect(rect)
    if not text:
        return
    painter.setPen(_qcolor(color))
    painter.drawText(rect, Qt.AlignCenter, text)


def _paint_vertical_header(
    painter: QPainter, rect: QRectF, column, body_px: float, width: float
) -> None:
    """姓名直書：一個字一列由上往下。

    ⚠️ 不要用 ``painter.rotate()`` 把整串字轉 90°——那是「橫書躺著」，不是直書，
    紙本上的姓名是正的字疊下來。

    ⚠️ 字級要**依姓名長度縮**：三個字放得下不代表四個字也放得下，
    而複姓或原住民姓名在警察單位不算少見。
    """
    painter.setPen(_border_pen())
    painter.drawRect(rect)
    text = column.header
    if not text:
        return

    per_char = min(width * 0.72, rect.height() / max(1, len(text)))
    painter.setFont(_font(min(body_px * 1.15, per_char * 0.82)))
    metrics = painter.fontMetrics()
    line_h = max(metrics.height(), per_char * 0.9)
    total = line_h * len(text)
    top = rect.top() + max(0.0, (rect.height() - total) / 2)

    painter.setPen(_qcolor(column.header_color))
    for index, char in enumerate(text):
        painter.drawText(
            QRectF(rect.left(), top + index * line_h, rect.width(), line_h),
            Qt.AlignCenter,
            char,
        )
