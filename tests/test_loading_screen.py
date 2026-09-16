import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from lib.loading_screen import LoadingScreen
from lib.resource_path import resource_path


_app = QApplication.instance() or QApplication([])


def test_loading_screen_renders_banner_at_fixed_size():
    loading = LoadingScreen()
    expected = QPixmap(resource_path("res/buttons/banner.png")).scaled(
        700,
        279,
        Qt.IgnoreAspectRatio,
        Qt.SmoothTransformation,
    )

    actual = loading.banner_label.pixmap()
    assert loading.size().width() == 700
    assert loading.size().height() == 319
    assert loading.banner_label.size().width() == 700
    assert loading.banner_label.size().height() == 279
    assert actual is not None
    assert actual.toImage() == expected.toImage()
    loading.close()


def test_loading_screen_missing_banner_shows_product_name():
    loading = LoadingScreen(
        banner_path="missing-banner.png",
        product_name="勤休預定表產生器",
    )

    assert loading.banner_label.text() == "勤休預定表產生器"
    assert loading.windowFlags() & Qt.FramelessWindowHint
    assert not (loading.windowFlags() & Qt.WindowStaysOnTopHint)
    loading.close()


def test_loading_screen_updates_visible_progress_state():
    loading = LoadingScreen()

    loading.setStep("建立主視窗...", 80)

    assert loading.status_label.text() == "建立主視窗..."
    assert loading.pct_label.text() == "80%"
    assert loading.progress_bar.value() == 80
    loading.close()
