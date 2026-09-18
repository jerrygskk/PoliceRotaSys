"""從程式內說明的濃縮母本產生兩頁 PDF 快速指引。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QGuiApplication,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
    QRawFont,
)

from lib.theme import (
    CARD_BORDER_COLOR,
    HELP_INFO_BACKGROUND_COLOR,
    HELP_INFO_TEXT_COLOR,
    HELP_MUTED_TEXT_COLOR,
    HELP_RULE_COLOR,
    HELP_WARNING_BACKGROUND_COLOR,
    HELP_WARNING_TEXT_COLOR,
    TEXT_COLOR,
)
from ui_utils.help_content import QUICKSTART_PAGES

RESOLUTION = 300
MARGIN_MM = 14.0
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "Quick_Start.pdf"
FONT_FAMILIES = (
    "Microsoft JhengHei",
    "Microsoft JhengHei UI",
    "Noto Sans CJK TC",
    "Noto Sans TC",
    "PingFang TC",
)
FOOTER_TEXT = "完整操作說明：請點各分頁右上角的「？」。"


def _all_text() -> str:
    parts = ["勤休預定表產生器", "快速指引", "用途", "關鍵步驟", "提示", FOOTER_TEXT]
    for page in QUICKSTART_PAGES:
        parts.extend((page["title"], page["subtitle"]))
        for card in page["cards"]:
            parts.extend((card["title"], card["purpose"], card["tip"]))
            parts.extend(card["steps"])
    return "".join(parts)


def _supports_all_text(family: str, text: str) -> bool:
    raw_font = QRawFont.fromFont(QFont(family))
    return raw_font.isValid() and all(
        character.isspace() or raw_font.supportsCharacter(ord(character))
        for character in set(text)
    )


def _select_font_family(text: str) -> str:
    installed = set(QFontDatabase.families())
    for family in FONT_FAMILIES:
        if family in installed and _supports_all_text(family, text):
            return family
    for family in QFontDatabase.families():
        if _supports_all_text(family, text):
            return family
    raise RuntimeError("找不到能完整顯示快速指引文字的中文字型")


def _font(family: str, point_size: float, *, bold: bool = False) -> QFont:
    font = QFont(family)
    # QPdfWriter 是 300 dpi 繪圖裝置；固定用裝置像素，讓量字與實際繪製一致。
    font.setPixelSize(max(1, round(point_size * RESOLUTION / 72)))
    font.setBold(bold)
    return font


def _text_height(font: QFont, width: float, text: str) -> float:
    flags = Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop
    bounds = QFontMetricsF(font).boundingRect(QRectF(0, 0, width, 10000), flags, text)
    return bounds.height()


def _draw_text(
    painter: QPainter,
    rect: QRectF,
    text: str,
    font: QFont,
    color: QColor,
    flags: Qt.AlignmentFlag = Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
) -> None:
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(rect, flags, text)


def _draw_header(
    painter: QPainter,
    page_rect: QRectF,
    page: dict[str, object],
    page_number: int,
    family: str,
) -> float:
    """頁首：每一行的高度都用量到的字高，不寫死 y 位移。

    ⚠️ 寫死位移與框高會裁掉字：27pt 的標楷／正黑在 300dpi 下上下伸出的部分
    比想像的多，原本固定 92px 的框把「首次設定」上下都切掉，還壓到副標。
    """
    pad_x = 56.0
    pad_y = 40.0
    kicker_font = _font(family, 13, bold=True)
    title_font = _font(family, 26, bold=True)
    subtitle_font = _font(family, 11.5)

    text_width = page_rect.width() - 2 * pad_x - 170      # 右上角留給頁碼
    kicker_h = _text_height(kicker_font, text_width, "勤休預定表產生器  快速指引")
    title_h = _text_height(title_font, text_width, page["title"])
    subtitle_h = _text_height(subtitle_font, page_rect.width() - 2 * pad_x, page["subtitle"])
    header_height = pad_y + kicker_h + 16 + title_h + 12 + subtitle_h + pad_y

    header = QRectF(page_rect.left(), page_rect.top(), page_rect.width(), header_height)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(TEXT_COLOR))
    painter.drawRoundedRect(header, 28, 28)

    left = header.left() + pad_x
    y = header.top() + pad_y
    _draw_text(painter, QRectF(left, y, text_width, kicker_h),
               "勤休預定表產生器  快速指引", kicker_font, QColor(Qt.white))
    y += kicker_h + 16
    _draw_text(painter, QRectF(left, y, text_width, title_h),
               page["title"], title_font, QColor(Qt.white))
    y += title_h + 12
    _draw_text(painter, QRectF(left, y, header.width() - 2 * pad_x, subtitle_h),
               page["subtitle"], subtitle_font, QColor(HELP_INFO_BACKGROUND_COLOR))

    _draw_text(
        painter,
        QRectF(header.right() - pad_x - 140, header.top() + pad_y, 140, kicker_h),
        f"{page_number}/2",
        kicker_font,
        QColor(Qt.white),
        Qt.AlignRight | Qt.AlignTop,
    )
    return header.bottom()


_CARD_PAD_X = 42.0
_CARD_PAD_Y = 30.0
_TIP_PAD = 22.0


def _card_layout(card: dict[str, object], width: float, family: str) -> dict[str, float]:
    """量出一張卡片各段落的高度。卡片高度照內容長，不平均分配整頁。

    ⚠️ 平均分配會讓每張卡片中間空一大塊、提示條被壓在底部（第一版就是這樣）。
    """
    content_width = width - 2 * _CARD_PAD_X
    steps_text = "\n".join(f"{number}. {step}" for number, step in enumerate(card["steps"], 1))
    title = _text_height(_font(family, 17, bold=True), content_width, card["title"])
    purpose = _text_height(_font(family, 11.5), content_width, card["purpose"])
    label = _text_height(_font(family, 10.5, bold=True), content_width, "關鍵步驟")
    steps = _text_height(_font(family, 11.5), content_width, steps_text)
    tip_text = _text_height(_font(family, 10.5), content_width - 2 * _TIP_PAD, card["tip"])
    tip = tip_text + 2 * _TIP_PAD
    height = (_CARD_PAD_Y + title + 10 + purpose + 18 + label + 8 + steps
              + 18 + tip + _CARD_PAD_Y)
    return {
        "steps_text": steps_text, "title": title, "purpose": purpose, "label": label,
        "steps": steps, "tip": tip, "height": height,
    }


def _draw_card(
    painter: QPainter,
    rect: QRectF,
    card: dict[str, object],
    family: str,
    layout: dict[str, float],
) -> None:
    painter.setPen(QPen(QColor(CARD_BORDER_COLOR), 3))
    painter.setBrush(QColor(Qt.white))
    painter.drawRoundedRect(rect, 24, 24)

    content_width = rect.width() - 2 * _CARD_PAD_X
    left = rect.left() + _CARD_PAD_X
    y = rect.top() + _CARD_PAD_Y

    _draw_text(painter, QRectF(left, y, content_width, layout["title"]),
               card["title"], _font(family, 17, bold=True), QColor(TEXT_COLOR))
    y += layout["title"] + 10
    _draw_text(painter, QRectF(left, y, content_width, layout["purpose"]),
               card["purpose"], _font(family, 11.5), QColor(TEXT_COLOR))
    y += layout["purpose"] + 18
    _draw_text(painter, QRectF(left, y, content_width, layout["label"]),
               "關鍵步驟", _font(family, 10.5, bold=True), QColor(HELP_INFO_TEXT_COLOR))
    y += layout["label"] + 8
    _draw_text(painter, QRectF(left, y, content_width, layout["steps"]),
               layout["steps_text"], _font(family, 11.5), QColor(TEXT_COLOR))
    y += layout["steps"] + 18

    tip_rect = QRectF(left, y, content_width, layout["tip"])
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(HELP_WARNING_BACKGROUND_COLOR))
    painter.drawRoundedRect(tip_rect, 14, 14)
    _draw_text(
        painter,
        tip_rect.adjusted(_TIP_PAD, _TIP_PAD, -_TIP_PAD, -_TIP_PAD),
        card["tip"],
        _font(family, 10.5),
        QColor(HELP_WARNING_TEXT_COLOR),
    )


def _draw_page(
    painter: QPainter,
    page_rect: QRectF,
    page: dict[str, object],
    page_number: int,
    family: str,
) -> None:
    cards = page["cards"]
    header_bottom = _draw_header(painter, page_rect, page, page_number, family)
    footer_height = 105.0
    content_top = header_bottom + 40
    content_bottom = page_rect.bottom() - footer_height - 24

    layouts = [_card_layout(card, page_rect.width(), family) for card in cards]
    natural = sum(item["height"] for item in layouts)
    available = content_bottom - content_top
    # 剩餘空間平均分給卡片之間的間距（上限 120），版面才不會整頁靠上、底下空一大塊；
    # 內容太長時先縮間距，仍放不下才報錯。
    gaps = max(len(cards) - 1, 1)
    gap = min(120.0, max(18.0, (available - natural) / gaps))
    if natural + gap * (len(cards) - 1) > available:
        raise RuntimeError(f"快速指引第 {page_number} 頁內容超出版面，請精簡文字")

    y = content_top
    for card, layout in zip(cards, layouts):
        _draw_card(
            painter,
            QRectF(page_rect.left(), y, page_rect.width(), layout["height"]),
            card,
            family,
            layout,
        )
        y += layout["height"] + gap

    painter.setPen(QPen(QColor(HELP_RULE_COLOR), 2))
    painter.drawLine(
        page_rect.left(), page_rect.bottom() - footer_height,
        page_rect.right(), page_rect.bottom() - footer_height,
    )
    _draw_text(
        painter,
        QRectF(
            page_rect.left(), page_rect.bottom() - footer_height + 26,
            page_rect.width(), footer_height - 26,
        ),
        FOOTER_TEXT,
        _font(family, 10.5),
        QColor(HELP_MUTED_TEXT_COLOR),
        Qt.AlignHCenter | Qt.AlignTop,
    )


def generate_pdf(output_path: Path) -> tuple[str, int]:
    if len(QUICKSTART_PAGES) != 2:
        raise RuntimeError("快速指引內容必須固定為兩頁")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_family = _select_font_family(_all_text())

    writer = QPdfWriter(str(output_path))
    writer.setResolution(RESOLUTION)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageOrientation(QPageLayout.Portrait)
    writer.setPageMargins(
        QMarginsF(MARGIN_MM, MARGIN_MM, MARGIN_MM, MARGIN_MM),
        QPageLayout.Millimeter,
    )
    writer.setTitle("勤休預定表產生器快速指引")
    writer.setCreator("PoliceRotaSys")

    painter = QPainter(writer)
    if not painter.isActive():
        raise RuntimeError(f"無法建立 PDF：{output_path}")
    try:
        page_rect = QRectF(0, 0, writer.width(), writer.height())
        _draw_page(painter, page_rect, QUICKSTART_PAGES[0], 1, font_family)
        if not writer.newPage():
            raise RuntimeError("無法建立快速指引第 2 頁")
        _draw_page(painter, page_rect, QUICKSTART_PAGES[1], 2, font_family)
    finally:
        painter.end()

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(f"PDF 未成功寫入：{output_path}")
    return font_family, output_path.stat().st_size


def verify_pdf(output_path: Path) -> int:
    # QtPdf 是產生工具的開發期驗證相依，不可移入產品 runtime 模組。
    from PySide6.QtPdf import QPdfDocument

    document = QPdfDocument()
    error = document.load(str(output_path))
    if error != QPdfDocument.Error.None_:
        raise RuntimeError(f"QtPdf 無法載入快速指引：{error}")
    page_count = document.pageCount()
    if page_count != 2:
        raise RuntimeError(f"快速指引頁數錯誤：預期 2 頁，實際 {page_count} 頁")
    return page_count


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="產生兩頁 PDF 快速指引")
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="輸出路徑（預設：docs/Quick_Start.pdf）",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    try:
        font_family, size = generate_pdf(args.output.resolve())
        page_count = verify_pdf(args.output.resolve())
    except Exception as error:
        print(f"產生快速指引失敗：{error}", file=sys.stderr)
        return 1
    finally:
        del app

    print(
        f"已產生 {args.output.resolve()}（{page_count} 頁，{size} bytes，字型：{font_family}）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
