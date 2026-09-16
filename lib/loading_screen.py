"""Lightweight startup progress window."""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from lib.resource_path import resource_path


class LoadingScreen(QWidget):
    """Show the product banner and progress for synchronous startup work."""

    WIN_W = 700
    WIN_H = 319
    BANNER_H = 279
    PROGRESS_H = 40

    def __init__(
        self,
        banner_path="res/buttons/banner.png",
        product_name="勤休預定表產生器",
    ):
        super().__init__()
        self.banner_path = banner_path
        self.product_name = product_name
        self._setup_ui()

    def _setup_ui(self):
        self.setFixedSize(self.WIN_W, self.WIN_H)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.banner_label = QLabel()
        self.banner_label.setFixedSize(self.WIN_W, self.BANNER_H)
        self.banner_label.setAlignment(Qt.AlignCenter)
        self.banner_label.setStyleSheet("background-color: #dde7f7;")

        banner_path = resource_path(self.banner_path)
        if os.path.exists(banner_path):
            pixmap = QPixmap(banner_path).scaled(
                self.WIN_W,
                self.BANNER_H,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
            self.banner_label.setPixmap(pixmap)
        else:
            self.banner_label.setText(self.product_name)
            self.banner_label.setStyleSheet(
                "background-color: #173b67; color: white; "
                "font-size: 22pt; font-weight: 700;"
            )
        layout.addWidget(self.banner_label)

        progress_widget = QWidget()
        progress_widget.setFixedHeight(self.PROGRESS_H)
        progress_widget.setStyleSheet("background-color: #dde7f7;")
        progress_layout = QVBoxLayout(progress_widget)
        progress_layout.setContentsMargins(20, 5, 20, 5)
        progress_layout.setSpacing(2)

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        self.status_label = QLabel("啟動中...")
        self.status_label.setStyleSheet("color: #173b67; font-size: 10pt;")
        self.pct_label = QLabel("0%")
        self.pct_label.setAlignment(Qt.AlignRight)
        self.pct_label.setStyleSheet(
            "color: #173b67; font-size: 10pt; font-weight: 600;"
        )
        row_layout.addWidget(self.status_label)
        row_layout.addWidget(self.pct_label)
        progress_layout.addWidget(row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                background-color: #b8cbe0;
                border-radius: 3px;
                border: none;
            }
            QProgressBar::chunk {
                background-color: #173b67;
                border-radius: 3px;
            }
            """
        )
        progress_layout.addWidget(self.progress_bar)
        layout.addWidget(progress_widget)

        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.move(
                available.x() + (available.width() - self.WIN_W) // 2,
                available.y() + (available.height() - self.WIN_H) // 2,
            )

    def setStep(self, desc, percent):
        """Update the current startup description and completion percentage."""
        percent = max(0, min(100, int(percent)))
        self.status_label.setText(desc)
        self.pct_label.setText(f"{percent}%")
        self.progress_bar.setValue(percent)

    def finishAndClose(self):
        """Close the startup window after synchronous loading finishes."""
        self.close()
