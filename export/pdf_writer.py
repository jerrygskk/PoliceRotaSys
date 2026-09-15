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
)

from lib.layout_model import COL_MEMBER, RED, Sheet

RESOLUTION = 300          # dpi
MARGIN_MM = 8.0

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
TITLE_HEIGHT_RATIO = 0.55

# 字型：標楷體優先，找不到時依序退回。
# ⚠️ 不要只寫一支——沒有那支字型時 Qt 會靜默換成系統預設，字寬全走鐘。
FONT_FAMILIES = ("標楷體", "DFKai-SB", "Microsoft JhengHei", "Noto Sans CJK TC")

# 欄寬權重：日期／星期欄比姓名欄寬一點。
HEADER_COL_WEIGHT = 1.25
MEMBER_COL_WEIGHT = 1.0

# 標題列與姓名列佔整頁高度的比例。
TITLE_RATIO = 0.055
NAME_RATIO = 0.085
CODE_RATIO = 0.028


def _ensure_app() -> None:
    if QGuiApplication.instance() is None:
        QGuiApplication([])


def _qcolor(color: str) -> QColor:
    return QColor("#cc0000") if color == RED else QColor("#000000")


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
        _paint(painter, QRectF(0, 0, writer.width(), writer.height()), sheet)
    finally:
        painter.end()


def _paint(painter: QPainter, page: QRectF, sheet: Sheet) -> None:
    columns = sheet.columns
    if not columns:
        return

    title_h = page.height() * TITLE_RATIO
    name_h = page.height() * NAME_RATIO
    code_h = page.height() * CODE_RATIO
    body_h = page.height() - title_h - name_h - code_h
    row_h = body_h / sheet.day_count

    weights = [
        HEADER_COL_WEIGHT if column.kind != COL_MEMBER else MEMBER_COL_WEIGHT
        for column in columns
    ]
    unit_w = page.width() / sum(weights)

    painter.setFont(_font(title_h * TITLE_HEIGHT_RATIO, bold=True))
    painter.setPen(QColor("#000000"))
    painter.drawText(
        QRectF(page.left(), page.top(), page.width(), title_h),
        Qt.AlignCenter,
        sheet.title,
    )

    # 代碼格最窄的一欄決定字級，整張表才會一致。
    narrowest = unit_w * min(weights)
    body_px = min(row_h * BODY_HEIGHT_RATIO, narrowest * BODY_WIDTH_RATIO)
    painter.setFont(_font(body_px))

    x = page.left()
    for column, weight in zip(columns, weights):
        width = unit_w * weight
        header_rect = QRectF(x, page.top() + title_h, width, name_h)
        if column.kind == COL_MEMBER:
            _paint_vertical_header(painter, header_rect, column, body_px, width)
        else:
            _paint_cell(painter, header_rect, column.header, column.header_color)
        painter.setFont(_font(body_px))
        _paint_cell(
            painter,
            QRectF(x, page.top() + title_h + name_h, width, code_h),
            column.code,
            "black",
        )
        top = page.top() + title_h + name_h + code_h
        for day, cell in enumerate(column.cells):
            _paint_cell(
                painter,
                QRectF(x, top + day * row_h, width, row_h),
                cell.text,
                cell.color,
            )
        x += width


def _paint_cell(painter: QPainter, rect: QRectF, text: str, color: str) -> None:
    painter.setPen(QColor("#000000"))
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
    painter.setPen(QColor("#000000"))
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
