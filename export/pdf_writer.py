"""版面模型 → A3 橫式 .pdf（Qt 的 QPdfWriter）。

與 ``xlsx_writer`` 吃同一份 :class:`lib.layout_model.Sheet`，兩邊才會長一樣。

⚠️ **用 QPdfWriter 而不是 reportlab**：PySide6 已經在包裡，PDF 等於免費附贈；
多拉一個套件進來只是多一段開機解壓時間（CLAUDE.md §B 的封閉相依清單）。

⚠️ 匯出 PDF **不需要 QApplication**，但需要 QGuiApplication 才能量字。
本模組自己確保有一個（離線環境請設 ``QT_QPA_PLATFORM=offscreen``）。
"""
from __future__ import annotations

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPageLayout, QPageSize, QPainter, QPdfWriter

from lib.layout_model import RED, Sheet

RESOLUTION = 300          # dpi
MARGIN_MM = 8.0
FONT_FAMILY = "標楷體"

TITLE_POINT = 14
BODY_POINT = 8

# 版面比例：姓名欄與代碼欄佔固定寬度，其餘平分給日期格。
LABEL_RATIO = 0.085
CODE_RATIO = 0.030


def _ensure_app() -> None:
    if QGuiApplication.instance() is None:
        QGuiApplication([])


def _qcolor(color: str) -> QColor:
    return QColor("#cc0000") if color == RED else QColor("#000000")


def _page_rect(writer: QPdfWriter) -> QRectF:
    return QRectF(0, 0, writer.width(), writer.height())


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
        _paint(painter, writer, sheet)
    finally:
        painter.end()


def _paint(painter: QPainter, writer: QPdfWriter, sheet: Sheet) -> None:
    page = _page_rect(writer)
    rows = sheet.rows
    if not rows:
        return

    title_font = QFont(FONT_FAMILY, TITLE_POINT)
    title_font.setBold(True)
    painter.setFont(title_font)
    title_h = painter.fontMetrics().height() * 1.8
    painter.setPen(_qcolor("black"))
    painter.drawText(
        QRectF(page.left(), page.top(), page.width(), title_h),
        Qt.AlignCenter,
        sheet.title,
    )

    grid_top = page.top() + title_h
    row_h = (page.height() - title_h) / len(rows)
    label_w = page.width() * LABEL_RATIO
    code_w = page.width() * CODE_RATIO
    day_w = (page.width() - label_w - code_w) / sheet.day_count

    painter.setFont(QFont(FONT_FAMILY, BODY_POINT))
    for index, row in enumerate(rows):
        top = grid_top + index * row_h
        _paint_cell(painter, QRectF(page.left(), top, label_w, row_h),
                    row.label, row.label_color)
        _paint_cell(painter, QRectF(page.left() + label_w, top, code_w, row_h),
                    row.code, "black")
        for day, cell in enumerate(row.cells):
            rect = QRectF(
                page.left() + label_w + code_w + day * day_w, top, day_w, row_h
            )
            _paint_cell(painter, rect, cell.text, cell.color)


def _paint_cell(painter: QPainter, rect: QRectF, text: str, color: str) -> None:
    painter.setPen(QColor("#000000"))
    painter.drawRect(rect)
    if not text:
        return
    painter.setPen(_qcolor(color))
    painter.drawText(rect, Qt.AlignCenter, text)
