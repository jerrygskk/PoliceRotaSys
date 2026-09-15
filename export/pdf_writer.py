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
FONT_FAMILY = "標楷體"

TITLE_POINT = 14
BODY_POINT = 7

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

    title_font = QFont(FONT_FAMILY, TITLE_POINT)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.setPen(QColor("#000000"))
    painter.drawText(
        QRectF(page.left(), page.top(), page.width(), title_h),
        Qt.AlignCenter,
        sheet.title,
    )

    body_font = QFont(FONT_FAMILY, BODY_POINT)
    painter.setFont(body_font)

    x = page.left()
    for column, weight in zip(columns, weights):
        width = unit_w * weight
        _paint_cell(
            painter,
            QRectF(x, page.top() + title_h, width, name_h),
            column.header,
            column.header_color,
            vertical=column.kind == COL_MEMBER,
        )
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


def _paint_cell(
    painter: QPainter,
    rect: QRectF,
    text: str,
    color: str,
    vertical: bool = False,
) -> None:
    painter.setPen(QColor("#000000"))
    painter.drawRect(rect)
    if not text:
        return
    painter.setPen(_qcolor(color))
    if vertical:
        _draw_vertical(painter, rect, text)
    else:
        painter.drawText(rect, Qt.AlignCenter, text)


def _draw_vertical(painter: QPainter, rect: QRectF, text: str) -> None:
    """姓名直書：一個字一列由上往下。

    ⚠️ 不要用 ``painter.rotate()`` 把整串字轉 90°——那是「橫書躺著」，不是直書，
    紙本上的姓名是正的字疊下來。
    """
    metrics = painter.fontMetrics()
    line_h = metrics.height()
    total = line_h * len(text)
    top = rect.top() + max(0.0, (rect.height() - total) / 2)
    for index, char in enumerate(text):
        painter.drawText(
            QRectF(rect.left(), top + index * line_h, rect.width(), line_h),
            Qt.AlignCenter,
            char,
        )
