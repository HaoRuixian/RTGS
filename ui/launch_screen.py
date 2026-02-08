# ui/launch_screen.py
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QFrame, QSizePolicy)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QPalette, QPixmap
from pathlib import Path

from ui.style import get_app_stylesheet


class LaunchScreen(QMainWindow):
    """
    launch screen for module selection.
    """
    module_selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GNSS RT Monitor - Launch")
        self.resize(1000, 640)
        self.setup_ui()
        self.apply_stylesheet()

    def setup_ui(self):
        self.setStyleSheet(get_app_stylesheet())
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(20)

        # Left panel: application info / branding
        left_panel = QFrame()
        left_panel.setFixedWidth(360)
        left_panel.setStyleSheet("background: transparent;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(12)

        app_title = QLabel("GNSS RT Monitor")
        app_title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        app_title.setStyleSheet("color: #263238;")
        left_layout.addWidget(app_title)

        subtitle = QLabel("Real-time GNSS Processing and Geological applications")
        subtitle.setWordWrap(True)
        subtitle.setFont(QFont("Segoe UI", 10))
        subtitle.setStyleSheet("color: #455A64;")
        left_layout.addWidget(subtitle)

        left_layout.addSpacing(8)

        description = QLabel(
            "A professional-grade system for real-time GNSS monitoring,\n"
            "signal quality assessment, and reflectometry analysis.\n"
            "Designed for research and engineering workflows."
        )
        description.setWordWrap(True)
        description.setFont(QFont("Segoe UI", 9))
        description.setStyleSheet("color: #607D8B;")
        left_layout.addWidget(description)

        left_layout.addSpacing(12)

        # Add image in the middle of left panel
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Try to load image - adjust path as needed
        image_path = Path(__file__).parent.parent / "assets" / "logo.png"
        if image_path.exists():
            pixmap = QPixmap(str(image_path))
            # Scale image to fit (max 280x200)
            scaled_pixmap = pixmap.scaledToWidth(280, Qt.TransformationMode.SmoothTransformation)
            image_label.setPixmap(scaled_pixmap)
        else:
            # Placeholder if image not found
            image_label.setText("GNSS Logo\n(Place logo.png in assets folder)")
            image_label.setStyleSheet("color: #90A4AE; font-style: italic;")
        
        left_layout.addWidget(image_label)

        left_layout.addStretch()

        version = QLabel("Version 0.1")
        version.setFont(QFont("Segoe UI", 9))
        version.setStyleSheet("color: #90A4AE;")
        left_layout.addWidget(version)

        copyright = QLabel("© 2026 Ruixian Hao. All rights reserved.")
        copyright.setFont(QFont("Segoe UI", 9))
        copyright.setStyleSheet("color: #90A4AE;")
        left_layout.addWidget(copyright)

        main_layout.addWidget(left_panel)

        # ====== Right panel: module selection ======
        right_panel  = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(18)

        accent = "#1E88E5"

        self.monitoring_btn = self._make_card_button(
            "Monitoring",
            "Real-time GNSS signal monitoring, SNR plots and satellite tables.",
            accent
        )
        self.positioning_btn = self._make_card_button(
            "Positioning",
            "Real-time positioning, accuracy metrics and trajectory logging.",
            accent
        )
        self.reflectometry_btn = self._make_card_button(
            "Reflectometry",
            "Interferogram and spectral analysis for surface reflection studies.",
            accent
        )
        self.refractometry_btn = self._make_card_button(
            "Refractometry",
            "Real-time tropospheric and ionospheric parameter estimation.",
            accent
        )

        right_layout.addWidget(self.monitoring_btn)
        right_layout.addWidget(self.positioning_btn)
        right_layout.addWidget(self.reflectometry_btn)
        right_layout.addWidget(self.refractometry_btn)
        right_layout.addStretch()

        main_layout.addWidget(right_panel)

        # Connections
        self.monitoring_btn.clicked.connect(lambda: self.module_selected.emit('monitoring'))
        self.positioning_btn.clicked.connect(lambda: self.module_selected.emit('positioning'))
        self.reflectometry_btn.clicked.connect(lambda: self.module_selected.emit('reflectometry'))
        self.refractometry_btn.clicked.connect(lambda: self.module_selected.emit('refractometry'))

    def _make_card_button(self, title: str, subtitle: str, color: str) -> QPushButton:
        btn = QPushButton()
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setMinimumHeight(120)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #FFFFFF;
                border: 1px solid #CFD8DC;
                border-radius: 8px;
                padding: 14px;
                text-align: left;
            }}
            QPushButton:hover {{
                border: 1px solid {color};
            }}
            QPushButton:pressed {{
                background-color: #ECEFF1;
            }}
        """)

        layout = QVBoxLayout(btn)
        layout.setContentsMargins(6, 2, 6, 2)

        title_lbl = QLabel(title)
        title_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        title_lbl.setStyleSheet("color: #263238;")
        layout.addWidget(title_lbl)

        sub_lbl = QLabel(subtitle)
        sub_lbl.setWordWrap(True)
        sub_lbl.setFont(QFont("Segoe UI", 9))
        sub_lbl.setStyleSheet("color: #607D8B;")
        layout.addWidget(sub_lbl)

        return btn

    def apply_stylesheet(self):
        self.setStyleSheet(get_app_stylesheet())
