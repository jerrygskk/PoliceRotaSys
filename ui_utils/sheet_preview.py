"""
sheet_preview.py — 月表預覽（產生月表分頁）

⚠️ **不另寫畫表程式**：直接呼叫 PDF 那支 `export.pdf_writer.paint_sheet`，
預覽長什麼樣，印出來就長什麼樣（DEVELOPER §4「預覽是必要的，不是加分項」）。

做法是先把整張 A3 畫到一張固定大小的底圖上，再縮放到畫面。直接畫在元件上的話，
框線寬度是以「頁面像素」算的，元件一小框線就糊成一片。底圖只在換月表時重畫。

縮放（維護者 2026-09-16 要求）：
  - 預設＝左右填滿預覽區，上下超出就出直向捲軸（維護者 2026-09-16 裁示）
  - 最小＝整張月表完整塞進目前的預覽區（依預覽區的寬與高算）
  - 滾輪往上放大、往下縮小，以游標所在位置為中心；超出預覽區就出現捲軸
  - 最大＝底圖原始解析度（一個底圖像素對一個螢幕像素），再大字只會糊
  - 還沒動過滾輪時，視窗縮放一律維持左右填滿；動過之後維持同樣的放大倍率
  - 換月份回到預設（左右填滿、捲到最上面）
  - 放大後按住左鍵拖曳可上下左右移動畫面（游標變手掌）；完整顯示時沒東西可拖
"""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget

from export.pdf_writer import paint_sheet

# A3 橫式 420 × 297 mm；底圖寬度夠大，縮小後框線才細
_PAGE_W = 2800
_PAGE_H = round(_PAGE_W * 297 / 420)
_PAGE_MARGIN = 24          # 底圖四邊留白（對應 PDF 的 5mm 邊界，只求視覺相近）
_SHADOW = QColor("#d1d1d6")
_GAP = 8                   # 頁面與預覽區邊緣的留白（含陰影）
ZOOM_STEP = 1.15           # 滾輪一格的放大倍率


class _Canvas(QWidget):
    def __init__(self, preview):
        super().__init__()
        self._preview = preview

    def paintEvent(self, event):
        preview = self._preview
        painter = QPainter(self)
        try:
            if preview._image is None:
                painter.setPen(QColor("#8e8e93"))
                painter.drawText(self.rect(), Qt.AlignCenter, preview._empty_text)
                return
            w, h = _PAGE_W * preview._scale, _PAGE_H * preview._scale
            target = QRectF(max((self.width() - w) / 2, _GAP),
                            max((self.height() - h) / 2, _GAP), w, h)
            painter.fillRect(target.translated(3, 3), _SHADOW)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(target, preview._image)
        finally:
            painter.end()


class SheetPreview(QScrollArea):
    """顯示一張月表；沒有月表時顯示提示文字。滾輪縮放。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = None
        self._empty_text = ""
        self._zoom = 1.0           # 相對於「完整塞進預覽區」的倍率
        self._scale = 1.0          # 底圖像素 → 畫面像素
        self._drag_from = None     # 拖曳起點（游標位置, 橫捲軸值, 直捲軸值）
        self._fit_width = True     # 還沒用滾輪縮放過：一直維持左右填滿
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(200)
        self._canvas = _Canvas(self)
        self.setWidget(self._canvas)

    # ── 內容 ────────────────────────────────────────────────────
    def setSheet(self, sheet, empty_text=""):
        """sheet=None 時清空預覽並顯示 empty_text。換月表一律回到完整顯示。"""
        self._empty_text = empty_text
        if sheet is None:
            self._image = None
        else:
            image = QImage(_PAGE_W, _PAGE_H, QImage.Format_RGB32)
            image.fill(Qt.white)
            painter = QPainter(image)
            try:
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setRenderHint(QPainter.TextAntialiasing)
                page = QRectF(0, 0, _PAGE_W, _PAGE_H).adjusted(
                    _PAGE_MARGIN, _PAGE_MARGIN, -_PAGE_MARGIN, -_PAGE_MARGIN)
                paint_sheet(painter, page, sheet)
            finally:
                painter.end()
            self._image = image
        self.resetZoom()

    def resetZoom(self):
        """回到預設：左右填滿、捲到最上面。"""
        self._fit_width = True
        self._zoom = self.widthZoom()
        self._layoutCanvas()
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)

    def hasSheet(self):
        return self._image is not None

    # ── 縮放 ────────────────────────────────────────────────────
    def fitScale(self):
        """整張月表完整塞進目前預覽區的比例（依預覽區的寬與高）。"""
        vp = self.viewport().size()
        return max(min((vp.width() - 2 * _GAP) / _PAGE_W,
                       (vp.height() - 2 * _GAP) / _PAGE_H), 0.01)

    def widthZoom(self):
        """左右填滿預覽區的倍率（相對於完整塞進）。

        ⚠️ 上下超出會冒出直向捲軸、預覽區變窄，要扣掉捲軸寬再算，否則左右會多出
        一截、連橫向捲軸也跑出來。
        """
        vp = self.viewport().size()
        bar_w = 0 if self.verticalScrollBar().isVisible() else self.style().pixelMetric(
            self.style().PixelMetric.PM_ScrollBarExtent)
        width_scale = (vp.width() - bar_w - 2 * _GAP) / _PAGE_W
        return min(max(width_scale / self.fitScale(), 1.0), self.maxZoom())

    def maxZoom(self):
        """放大上限：一個底圖像素對一個螢幕像素。"""
        dpr = self.devicePixelRatioF() or 1.0
        return max(1.0, (1.0 / dpr) / self.fitScale())

    def zoom(self):
        return self._zoom

    def setZoom(self, zoom, anchor=None):
        """設定倍率（夾在 1 與上限之間）；anchor 是預覽區內的點，縮放後維持在同一位置。"""
        # ⚠️ 任何明確縮放都要先關掉「維持左右填滿」：縮小讓直向捲軸消失時預覽區會變寬，
        # 觸發 resizeEvent；旗標還開著的話會把倍率彈回左右填滿（測試抓到的）。
        self._fit_width = False
        zoom = min(max(zoom, 1.0), self.maxZoom())
        if self._image is None or abs(zoom - self._zoom) < 1e-9:
            self._zoom = zoom
            return
        hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
        if anchor is None:
            anchor = QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        # 游標底下那一點在頁面上的相對位置，縮放後捲回同一個相對位置
        old_scale = self._scale
        page_x = (hbar.value() + anchor.x() - _GAP) / (_PAGE_W * old_scale)
        page_y = (vbar.value() + anchor.y() - _GAP) / (_PAGE_H * old_scale)
        self._zoom = zoom
        self._layoutCanvas()
        hbar.setValue(round(page_x * _PAGE_W * self._scale + _GAP - anchor.x()))
        vbar.setValue(round(page_y * _PAGE_H * self._scale + _GAP - anchor.y()))

    def _layoutCanvas(self):
        self._scale = self.fitScale() * self._zoom
        vp = self.viewport().size()
        if self._image is None:
            size = vp
        else:
            size = QSize(max(round(_PAGE_W * self._scale) + 2 * _GAP, vp.width()),
                         max(round(_PAGE_H * self._scale) + 2 * _GAP, vp.height()))
        self._canvas.resize(size)
        self._canvas.update()
        self._updateCursor()

    def canPan(self):
        """畫面大於預覽區（有捲軸）時才能拖。"""
        return (self._image is not None
                and (self.horizontalScrollBar().maximum() > 0
                     or self.verticalScrollBar().maximum() > 0))

    def _updateCursor(self):
        if self._drag_from is not None:
            self.viewport().setCursor(Qt.ClosedHandCursor)
        elif self.canPan():
            self.viewport().setCursor(Qt.OpenHandCursor)
        else:
            self.viewport().unsetCursor()

    # ── 事件 ────────────────────────────────────────────────────
    def wheelEvent(self, event):
        if self._image is None:
            return super().wheelEvent(event)
        steps = event.angleDelta().y() / 120
        if steps:
            self.setZoom(self._zoom * (ZOOM_STEP ** steps), event.position())
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.canPan():
            self._drag_from = (event.position(), self.horizontalScrollBar().value(),
                               self.verticalScrollBar().value())
            self._updateCursor()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_from is None:
            return super().mouseMoveEvent(event)
        start, h, v = self._drag_from
        delta = event.position() - start
        # 手掌拖曳：畫面跟著游標走，所以捲軸往反方向動
        self.horizontalScrollBar().setValue(round(h - delta.x()))
        self.verticalScrollBar().setValue(round(v - delta.y()))
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_from is not None and event.button() == Qt.LeftButton:
            self._drag_from = None
            self._updateCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit_width:
            self._zoom = self.widthZoom()
        self._zoom = min(max(self._zoom, 1.0), self.maxZoom())
        self._layoutCanvas()
