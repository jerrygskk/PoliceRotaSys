"""版面模型 → A3 橫式 .pdf（Qt 的 QPdfWriter）。

與 ``xlsx_writer`` 吃同一份 :class:`lib.layout_model.Sheet`，兩邊才會長一樣。

⚠️ **X 軸是人名（欄），Y 軸是日期（列）**。第一版做反了，見 layout_model 的說明。

⚠️ **用 QPdfWriter 而不是 reportlab**：PySide6 已經在包裡，PDF 等於免費附贈；
多拉一個套件進來只是多一段開機解壓時間（CLAUDE.md §B 的封閉相依清單）。

⚠️ 匯出 PDF 不需要完整的 QApplication，但**需要 QGuiApplication** 才能量字。
本模組自己確保有一個（離線環境請設 ``QT_QPA_PLATFORM=offscreen``）。
"""
from __future__ import annotations

from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QGuiApplication,
    QPageLayout,
    QPageSize,
    QPainter,
    QPainterPath,
    QPdfWriter,
    QPen,
)

from lib.layout_model import (
    BLACK,
    BLUE,
    COL_BLANK,
    COL_MEMBER,
    COL_TITLE,
    RED,
    Sheet,
    column_weight,
    GAP_CHAR,
    GAP_SCALE,
    header_spans_code_row,
    vertical_pieces,
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
BODY_HEIGHT_RATIO = 0.58   # 標題欄與註記仍用舊估算（維護者：這兩處不動）
BODY_WIDTH_RATIO = 0.42

# ⚠️ **格子裡的字要盡量大**（維護者 2026-09-16：老人家眼睛不好，佔滿 80～90%，
# 以不切字為主）。舊寫法用固定比例估，數字與「休」只佔格寬約四成。
# 改為**實際量這張表會出現的字的筆畫範圍**（tightBoundingRect），放大到最寬、
# 最高的那個字剛好佔格子的 FILL_RATIO，並以筆畫中心對齊格子中心畫。
# Excel 另有自己的比例（xlsx_writer），兩邊不強求一致。
# 幹部／固定番代號與名字之間，比一般字縫多留的距離（行高的比例；維護者嫌太擠）
CODE_EXTRA_GAP = 0.12
FILL_RATIO = 0.70
# 輪番區塊每天格子裡的番號數字再小一級（「休」仍用 FILL_RATIO）：滿版一整片數字看起來太壓迫（維護者 2026-09-17）
BODY_FILL_RATIO = 0.60   # 0.85、0.75 都太擠（維護者 2026-09-17：兩位數番號黏在一起）
_REF_PX = 200              # 量字用的參考字級，實際字級依比例換算

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


# 純半形字串（番號 01、日期 12、代碼 21、標題的 115）改用 Tahoma：標楷體的數字
# 字距鬆散，放大後兩位數會黏在一起（維護者 2026-09-17 要求試）。中英混排的註記不換。
DIGIT_FAMILY = "Tahoma"


def _for_text(font: QFont, text: str) -> QFont:
    if not (text.isascii() and text.strip()):
        return font
    digit = QFont(font)
    digit.setFamilies([DIGIT_FAMILY, *FONT_FAMILIES])
    return digit


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
        paint_sheet(painter, page, sheet)
    finally:
        painter.end()


def paint_sheet(painter: QPainter, page: QRectF, sheet: Sheet) -> None:
    """把整張月表畫進 ``page`` 這個矩形。

    PDF 與畫面上的預覽**共用這一支**（``ui_utils/sheet_preview.py``）：預覽長什麼樣，
    印出來就長什麼樣，不另寫一份畫表程式。字級全部由格子幾何算出，所以畫在
    任何大小的矩形上都成立。
    """
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
    # 標題欄與註記維持舊估算（維護者：這兩處先不動）
    base_px = min(
        row_h * BODY_HEIGHT_RATIO, unit_w * min(data_weights) * BODY_WIDTH_RATIO
    )

    # 每天的格子：依實際會出現的字量出來。同類欄共用一個字級，整張表看起來才一致；
    # 格寬取該類最窄的欄，最窄的放得下，其他欄就放得下。
    data_cols = [c for c in columns if c.kind in (COL_MEMBER, COL_BLANK)]
    head_cols = [c for c in columns if c.kind not in (COL_MEMBER, COL_BLANK, COL_TITLE)]
    body_px = _fit_px(
        {cell.text for c in data_cols for cell in c.cells} | {"休", "00"},
        unit_w * min(data_weights), row_h, BODY_FILL_RATIO,
    )
    # 「休」等中文維持 FILL_RATIO，只有番號數字縮到 BODY_FILL_RATIO（維護者 2026-09-17）
    body_texts = {cell.text for c in data_cols for cell in c.cells} | {"休"}
    body_cjk_px = _fit_px(
        {t for t in body_texts if t and not t.isascii()},
        unit_w * min(data_weights), row_h,
    )
    header_px = _fit_px(
        {cell.text for c in head_cols for cell in c.cells} | {"00"},
        unit_w * min((weight_of(c) for c in head_cols), default=min(weights)), row_h,
    )
    # 直書姓名：所有人名共用同一組字寬基準與最窄的人名欄寬，並排時字才一樣大
    member_cols = [c for c in columns if c.kind == COL_MEMBER and len(c.header) > 1]
    name_basis = (
        (_ink_size({ch for c in member_cols for ch in c.header}),
         unit_w * min(weight_of(c) for c in member_cols))
        if member_cols else None
    )
    code_cols = [c for c in columns if c.code]
    code_px = _fit_px(
        {c.code for c in code_cols},
        unit_w * min((weight_of(c) for c in code_cols), default=min(weights)), code_h,
    )

    x = page.left()
    for block in sheet.blocks:
        block_w = sum(
            unit_w * weight_of(column) for column in block.columns
        )
        if block.note:
            _paint_note(
                painter, QRectF(x, page.top(), block_w, name_h), block.note, base_px
            )

        for column in block.columns:
            width = unit_w * weight_of(column)
            if column.kind == COL_TITLE:
                _paint_title_column(
                    painter, QRectF(x, page.top(), width, page.height()),
                    sheet.title, base_px,
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
                # 代碼列沒東西的欄，標題跨姓名列與代碼列合併（規則與 Excel 共用）
                merged = header_spans_code_row(column)
                if merged:
                    header_rect = QRectF(x, page.top(), width, name_h + code_h)
                # ⚠️ 欄很窄，多字標題橫著放會被切掉（「快打勤務」「日期」都
                # 踩過）——只要超過一個字就直書。
                # 固定番／幹部的人名欄：代碼與姓名同一格（代碼橫排在名字上方或下方）
                if len(column.header) > 1 or (column.kind == COL_MEMBER and column.code):
                    _paint_vertical_header(
                        painter, header_rect, column, width,
                        name_basis if column.kind == COL_MEMBER else None)
                else:
                    painter.setFont(_font(_fit_px(
                        {column.header}, width, header_rect.height())))
                    _paint_cell(
                        painter, header_rect, column.header, column.header_color
                    )
                if not merged:
                    painter.setFont(_font(code_px))
                    # ⚠️ 只有姓名跟著女警變紅，番號一律黑的。
                    _paint_cell(
                        painter,
                        QRectF(x, page.top() + name_h, width, code_h),
                        column.code,
                        "black",
                    )
            else:
                painter.setFont(_font(code_px))
                _paint_cell(
                    painter,
                    QRectF(x, page.top() + name_h, width, code_h),
                    column.code,
                    RED,
                )

            painter.setFont(_font(cell_px))
            top = page.top() + name_h + code_h
            for day, cell in enumerate(column.cells):
                if column.kind in (COL_MEMBER, COL_BLANK):
                    painter.setFont(_font(
                        body_cjk_px if cell.text and not cell.text.isascii() else cell_px))
                _paint_cell(
                    painter,
                    QRectF(x, top + day * row_h, width, row_h),
                    cell.text,
                    cell.color,
                )
            x += width


def _paint_note(painter: QPainter, rect: QRectF, note, body_px: float) -> None:
    """區塊註記：跨整個區塊的合併格，一行一筆純文字（一律黑字）。"""
    painter.setPen(_border_pen())
    painter.drawRect(rect)
    if not note:
        return
    line_h = rect.height() / max(1, len(note))
    usable = rect.width() * 0.92

    # ⚠️ 字級要依**最長那一行**縮，只看行高會讓長行右邊被切掉
    # （「晚班:(1-5、16)」的收尾括號就這樣不見過）。
    size = min(body_px, line_h * 0.62)
    longest = max(note, key=len)
    while size > 4:
        painter.setFont(_font(size))
        if painter.fontMetrics().horizontalAdvance(longest) <= usable:
            break
        size -= 0.5
    painter.setFont(_font(size))

    painter.setPen(_qcolor(BLACK))
    for index, line in enumerate(note):
        _draw_in_rect(
            painter,
            QRectF(
                rect.left() + rect.width() * 0.04,
                rect.top() + index * line_h,
                rect.width() * 0.92,
                line_h,
            ),
            line, centered=False,
        )


def _draw_text(painter: QPainter, origin: QPointF, text: str) -> None:
    """把字轉成外框路徑再填色，不用 drawText。

    ⚠️ 標楷體（DFKai-SB）是要靠字型微調指令才會把筆畫擺對位置的字型。drawText 會把
    字型子集嵌進 PDF，交給看的人的閱讀器去畫；不跑微調的閱讀器（Chrome／Edge
    內建、QtPdf 預覽）會把「日」「星」整個擠到格子左邊（2026-09-17 實測，程式量到
    的位置是對的，只有 PDF 看起來歪）。轉成路徑就由 Qt 算好外框，任何閱讀器都一樣；
    代價是 PDF 裡的字不能選取搜尋，列印用的表不需要。
    """
    path = QPainterPath()
    path.addText(origin, painter.font(), text)
    color = painter.pen().color()
    painter.fillPath(path, color)
    if painter.font().bold():
        # 標楷體沒有粗體字形，drawText 是程式加粗；路徑要自己描邊補回來
        painter.strokePath(path, QPen(color, painter.font().pixelSize() / 30))


def _draw_in_rect(painter: QPainter, rect: QRectF, text: str, centered: bool = True) -> None:
    """取代 drawText(rect, 置中／靠左＋垂直置中)，走 _draw_text。"""
    metrics = QFontMetricsF(painter.font())
    x = rect.center().x() - metrics.horizontalAdvance(text) / 2 if centered else rect.left()
    baseline = rect.center().y() + (metrics.ascent() - metrics.descent()) / 2
    _draw_text(painter, QPointF(x, baseline), text)


def _paint_title_column(
    painter: QPainter, rect: QRectF, title: str, body_px: float
) -> None:
    """最左邊那一整欄：直書標題，跨全高。"""
    painter.setPen(_border_pen())
    painter.drawRect(rect)
    if not title:
        return
    # 數字（115、9）橫排佔一行，中文一字一行（vertical_pieces）
    pieces = vertical_pieces(title)
    per_char = min(rect.width() * 0.8, rect.height() / max(1, len(pieces)))
    px = min(body_px * 1.3, per_char * 0.9)
    painter.setFont(_font(px, bold=True))
    widest = max(QFontMetricsF(_for_text(painter.font(), p)).horizontalAdvance(p) for p in pieces)
    if widest > rect.width() * 0.8:
        px *= rect.width() * 0.8 / widest
        painter.setFont(_font(px, bold=True))
    metrics = painter.fontMetrics()
    line_h = max(metrics.height(), per_char * 0.95)
    top = rect.top() + max(0.0, (rect.height() - line_h * len(pieces)) / 2)
    base = painter.font()
    for index, piece in enumerate(pieces):
        painter.setFont(_for_text(base, piece))
        _draw_in_rect(
            painter, QRectF(rect.left(), top + index * line_h, rect.width(), line_h), piece)


def _border_pen() -> QPen:
    return QPen(QColor("#000000"), BORDER_PX)


# 量過的筆畫範圍快取：{字串: (left, top, right, bottom)}，以 _REF_PX 字級、基線原點為準
_INK_CACHE: dict[str, tuple[float, float, float, float] | None] = {}


def _ink_rect(text: str) -> tuple[float, float, float, float] | None:
    """實際把字畫出來、掃描墨跡，取得筆畫範圍（相對基線原點，_REF_PX 字級）。

    ⚠️ 不要用 ``QFontMetricsF.tightBoundingRect``：標楷體的中文字它回傳的是整個
    字框，不是筆畫——「休」量到 200 實際 165、「一」實際只有 28 高也量成整框。
    用那個數字放大，中文字會偏小、置中也偏下（實測踩過）。數字它量得準，中文不準。
    """
    if text in _INK_CACHE:
        return _INK_CACHE[text]
    size = _REF_PX * (len(text) + 2)
    origin_x, origin_y = _REF_PX, _REF_PX * 2
    image = QImage(size, _REF_PX * 3, QImage.Format_Grayscale8)
    image.fill(255)
    painter = QPainter(image)
    painter.setFont(_for_text(_font(_REF_PX), text))
    painter.setPen(QColor("#000000"))
    painter.drawText(QPointF(origin_x, origin_y), text)
    painter.end()

    stride = image.bytesPerLine()
    data = bytes(image.constBits())
    width = image.width()
    blank = b"\xff" * width
    top = bottom = None
    left, right = width, -1
    for y in range(image.height()):
        row = data[y * stride:y * stride + width]
        if row == blank:
            continue
        if top is None:
            top = y
        bottom = y
        stripped = row.lstrip(b"\xff")
        left = min(left, width - len(stripped))
        right = max(right, len(row.rstrip(b"\xff")) - 1)
    result = (None if top is None else
              (left - origin_x, top - origin_y, right + 1 - origin_x, bottom + 1 - origin_y))
    _INK_CACHE[text] = result
    return result


def _ink_size(texts) -> tuple[float, float]:
    """一組字的筆畫範圍（寬、高取各自最大，_REF_PX 字級）。空字串略過。"""
    width = height = 0.0
    for text in texts:
        box = _ink_rect(text) if text else None
        if box:
            width = max(width, box[2] - box[0])
            height = max(height, box[3] - box[1])
    return width, height


def _fit_px(texts, box_w: float, box_h: float, ratio: float = FILL_RATIO) -> float:
    """讓 texts 裡最寬、最高的字，筆畫剛好佔格子 ratio 的字級（像素）。"""
    width, height = _ink_size(texts)
    if width <= 0 or height <= 0:
        return max(1.0, box_h * 0.5)
    return _REF_PX * min(ratio * box_w / width, ratio * box_h / height)


def _draw_centered(
    painter: QPainter, rect: QRectF, text: str, center_y: float | None = None
) -> None:
    """左右以**字寬**置中、上下以**筆畫**置中畫字。

    ⚠️ 不要用 drawText(rect, AlignCenter)：那是用字型的行高置中，字級放大到佔滿
    八成五時，筆畫會偏上或偏下而壓到框線。
    ⚠️ 左右不要用筆畫中心：每個中文字筆畫偏左偏右不同（「尤」「翰」），逐字對齊
    筆畫中心，直書的名字會左右歪來歪去（維護者 2026-09-17）。字型設計時字就擺在
    字寬正中，照字寬置中才整齊。
    center_y：直書整串共用的筆畫中心（_REF_PX 字級），同理避免上下各字高低不一。
    """
    box = _ink_rect(text)
    if box is None:
        return
    base = painter.font()
    painter.setFont(_for_text(base, text))
    scale = base.pixelSize() / _REF_PX
    advance = QFontMetricsF(painter.font()).horizontalAdvance(text)
    ink_cy = ((box[1] + box[3]) / 2 if center_y is None else center_y) * scale
    _draw_text(painter, QPointF(rect.center().x() - advance / 2, rect.center().y() - ink_cy), text)
    painter.setFont(base)


def _shared_center_y(texts) -> float:
    """一組中文字共用的上下筆畫中心（_REF_PX 字級）。"""
    boxes = [box for box in map(_ink_rect, texts) if box]
    if not boxes:
        return 0.0
    return (min(b[1] for b in boxes) + max(b[3] for b in boxes)) / 2


def _paint_cell(painter: QPainter, rect: QRectF, text: str, color: str) -> None:
    painter.setPen(_border_pen())
    painter.drawRect(rect)
    if not text:
        return
    painter.setPen(_qcolor(color))
    _draw_centered(painter, rect, text)


def _paint_vertical_header(
    painter: QPainter, rect: QRectF, column, width: float, basis=None
) -> None:
    """姓名直書：一個字一列由上往下。

    ⚠️ 不要用 ``painter.rotate()`` 把整串字轉 90°——那是「橫書躺著」，不是直書，
    紙本上的姓名是正的字疊下來。

    ⚠️ 字級**以欄寬為主**（維護者：左右佔滿八成五）；名字長到上下放不下時才縮，
    保證不切字。三個字放得下不代表四個字也放得下，複姓或原住民姓名不算少見。

    basis=((字寬, 字高), 欄寬)：人名欄傳入共用基準，所有姓名同一個字級（每個名字
    各算的話，筆畫瘦的名字會被放得比較大，並排大小不一）。空白欄標題不傳，各自算。

    ⚠️ 固定番／幹部：代碼（21、A）**橫排**佔一行，放名字下方或上方（``code_above``，
    維護者 2026-09-16）。代碼一律黑字，只有姓名跟著女警變紅。
    """
    painter.setPen(_border_pen())
    painter.drawRect(rect)
    text = column.header
    if not text:
        return

    if basis is not None:
        (char_w, char_h), width = basis
    else:
        char_w, char_h = _ink_size(set(text))
    if char_w <= 0 or char_h <= 0:
        return
    line_gap = 1.15            # 每個字佔的高度 ÷ 筆畫高度（字與字之間留一點縫）
    code = column.code if column.kind == COL_MEMBER else ""
    lines = [(char, column.header_color) for char in text]
    if code:
        lines.insert(0 if column.code_above else len(lines), (code, BLACK))
    by_width = _REF_PX * FILL_RATIO * width / char_w
    # 空白行（日期、星期中間）只佔 GAP_SCALE 行高
    weights = [GAP_SCALE if piece == GAP_CHAR else 1.0 for piece, _ in lines]
    by_height = _REF_PX * FILL_RATIO * rect.height() / (char_h * line_gap * sum(weights))
    name_px = min(by_width, by_height)
    code_px = name_px
    if code:
        code_w, _ = _ink_size({code})
        if code_w > 0:
            code_px = min(name_px, _REF_PX * FILL_RATIO * width / code_w)

    line_h = char_h * name_px / _REF_PX * line_gap
    if code:
        # 代號那行只佔自己筆畫的高度：英文字母、數字比中文矮，照中文行高排會跟
        # 名字離太遠（維護者 2026-09-17：幹部那格「貌合神離」）
        _, code_h = _ink_size({code})
        ink = (code_h * code_px) / (char_h * name_px)   # 代號筆畫高 ÷ 中文筆畫高
        weights[[piece for piece, _ in lines].index(code)] = min(
            1.0, (ink + line_gap - 1) / line_gap + CODE_EXTRA_GAP)  # 縫照留再多一點
    name_cy = _shared_center_y({char for char in text if char != GAP_CHAR})
    y = rect.top() + (rect.height() - line_h * sum(weights)) / 2
    for (piece, color), weight in zip(lines, weights):
        if piece == GAP_CHAR:
            y += line_h * weight
            continue
        painter.setFont(_font(code_px if piece == code and color == BLACK and code else name_px))
        painter.setPen(_qcolor(color))
        _draw_centered(
            painter, QRectF(rect.left(), y, rect.width(), line_h * weight), piece,
            None if piece == code and code else name_cy)
        y += line_h * weight

