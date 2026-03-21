from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
    QSizePolicy,
    QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QPixmap, QPainter, QIcon
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtSvg import QSvgRenderer
from ui.responsive import adaptive_window_size, window_ui_scale


ICONS = {
    "monitoring": '''<svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
    </svg>''',
    "positioning": '''<svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        <circle cx="12" cy="10" r="2"/>
    </svg>''',
    "reflectometry": '''<svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M2 19h20" opacity="0.3"/>
        <path d="M3 5l9 11 9-11"/>
        <path d="M12 16v5" stroke-dasharray="2 2"/>
    </svg>''',
    "refractometry": '''<svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M2 8h20" opacity="0.2"/>
        <path d="M2 16h20" opacity="0.2"/>
        <path d="M5 3l4 5 2 8 5 5"/>
    </svg>''',
}

WINDOW_ICON_SVG = '''
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="12" cy="12" r="3" fill="#00A0FF"/>
    <path d="M12 2C17.5228 2 22 6.47715 22 12C22 17.5228 17.5228 22 12 22" stroke="#00A0FF" stroke-width="2" stroke-linecap="round" opacity="0.3"/>
    <path d="M12 5C15.866 5 19 8.13401 19 12C19 15.866 15.866 19 12 19" stroke="#00A0FF" stroke-width="2" stroke-linecap="round" opacity="0.6"/>
    <path d="M12 8C14.2091 8 16 9.79086 16 12C16 14.2091 14.2091 16 12 16" stroke="#00A0FF" stroke-width="2" stroke-linecap="round"/>
</svg>
'''


class ModuleCard(QPushButton):
    def __init__(self, title, description, icon_key, accent_color="#2196F3"):
        super().__init__()
        self._base_width = 520
        self._base_height = 120
        self._accent_color = accent_color

        self.setFixedSize(self._base_width, self._base_height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(20)

        self.icon_widget = QSvgWidget()
        self.icon_widget.setFixedSize(45, 45)
        svg_data = ICONS[icon_key].format(color=accent_color)
        self.icon_widget.load(svg_data.encode("utf-8"))

        icon_bg = QFrame()
        icon_bg.setFixedSize(70, 70)
        icon_bg.setStyleSheet(f"background-color: {accent_color}10; border-radius: 15px;")
        icon_bg_layout = QVBoxLayout(icon_bg)
        icon_bg_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_bg_layout.addWidget(self.icon_widget)
        layout.addWidget(icon_bg)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(5)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.title_label = QLabel(title)
        self.desc_label = QLabel(description)
        self.desc_label.setWordWrap(True)

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.desc_label)
        layout.addLayout(text_layout)

        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(20)
        self.shadow.setXOffset(0)
        self.shadow.setYOffset(6)
        self.shadow.setColor(QColor(0, 0, 0, 25))
        self.setGraphicsEffect(self.shadow)

        self.apply_scale(1.0)
        self._set_style(False)

    def apply_scale(self, scale: float) -> None:
        width = max(360, int(self._base_width * scale))
        height = max(88, int(self._base_height * scale))
        self.setFixedSize(width, height)
        self.title_label.setStyleSheet(
            f"font-size: {max(12, int(17 * scale))}px; font-weight: 700; color: #263238; background: transparent;"
        )
        self.desc_label.setStyleSheet(
            f"font-size: {max(9, int(12 * scale))}px; color: #546E7A; background: transparent; line-height: 140%;"
        )

    def _set_style(self, hovered):
        border_color = self._accent_color if hovered else "#ECEFF1"
        bg_color = "#FFFFFF" if not hovered else "#FAFDFF"
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 16px;
                text-align: left;
            }}
        """
        )

    def enterEvent(self, event):
        self._set_style(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_style(False)
        super().leaveEvent(event)


class LaunchScreen(QMainWindow):
    module_selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RTGS - Launch")
        adaptive_window_size(self, target=(1280, 820), minimum=(980, 620))
        self.setStyleSheet("background-color: #F8F9FA;")
        self.set_window_icon(WINDOW_ICON_SVG)
        self.module_cards = []
        self.setup_ui()

    def set_window_icon(self, svg_str):
        renderer = QSvgRenderer(svg_str.encode("utf-8"))
        pixmap = QPixmap(256, 256)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        self.setWindowIcon(QIcon(pixmap))

        import ctypes

        myappid = "mycompany.myproduct.subproduct.version"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.left_panel = QFrame()
        self.left_panel.setFixedWidth(380)
        self.left_panel.setStyleSheet(
            """
            QFrame {
                background-color: #1A1C1E;
                border-right: 1px solid #2C2E30;
            }
            QLabel { color: #E3E2E6; background: transparent; }
        """
        )

        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(50, 80, 50, 50)
        self.left_layout.setSpacing(0)

        self.app_title = QLabel("RTGS")
        self.app_title.setStyleSheet("color: #FFFFFF; letter-spacing: 3px;")
        self.left_layout.addWidget(self.app_title)

        self.left_layout.addSpacing(5)

        self.subtitle = QLabel("Real-Time GNSS Studio")
        self.subtitle.setStyleSheet("color: #00A0FF;")
        self.left_layout.addWidget(self.subtitle)

        self.left_layout.addSpacing(30)

        line = QFrame()
        line.setFixedWidth(40)
        line.setFixedHeight(3)
        line.setStyleSheet("background-color: #00A0FF; border-radius: 1px;")
        self.left_layout.addWidget(line)

        self.left_layout.addSpacing(30)

        self.desc = QLabel(
            "Professional-grade suite for multi-constellation "
            "GNSS data processing, signal analysis, and "
            "atmospheric research."
        )
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("color: #A8AAB2; line-height: 160%;")
        self.left_layout.addWidget(self.desc)

        self.left_layout.addSpacing(25)

        self.author_label = QLabel("Developer: Ruixian Hao\nEmail: vitamin_n@outlook.com")
        self.author_label.setStyleSheet("color: #E3E2E6;")
        self.left_layout.addWidget(self.author_label)

        self.left_layout.addStretch()

        self.version_info = QLabel("VERSION 0.1.0-ALPHA")
        self.version_info.setStyleSheet("color: #44474E; letter-spacing: 1px;")
        self.left_layout.addWidget(self.version_info)

        self.left_layout.addSpacing(8)

        self.copyright_info = QLabel("(c) 2026 Ruixian Hao.\nAll Rights Reserved.")
        self.copyright_info.setWordWrap(True)
        self.copyright_info.setStyleSheet("color: #44474E; line-height: 130%;")
        self.left_layout.addWidget(self.copyright_info)

        main_layout.addWidget(self.left_panel)

        right_container = QWidget()
        self.right_layout = QVBoxLayout(right_container)
        self.right_layout.setContentsMargins(60, 0, 60, 0)
        self.right_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.header_text = QLabel("Select Workbench")
        self.header_text.setStyleSheet("font-size: 22px; font-weight: 600; color: #1A1C1E; margin-bottom: 30px;")
        self.right_layout.addWidget(self.header_text)

        modules = [
            ("monitoring", "Signal Quality Monitoring", "Real-time observation of SNR/CNR, constellation health.", "#0064D2"),
            ("positioning", "Precise Positioning", "High-precision RTK/PPP solutions with multi-frequency fusion.", "#0064D2"),
            ("reflectometry", "GNSS-Reflectometry", "Analysis of surface-reflected signals for environmental sensing.", "#0064D2"),
            ("refractometry", "GNSS-Refractometry", "Tropospheric and ionospheric delay modeling and ZTD estimation.", "#0064D2"),
        ]

        for mod_id, title, desc, color in modules:
            btn = ModuleCard(title, desc, mod_id, color)
            btn.clicked.connect(lambda chk, m=mod_id: self.module_selected.emit(m))
            self.module_cards.append(btn)
            self.right_layout.addWidget(btn)
            self.right_layout.addSpacing(15)

        main_layout.addWidget(right_container)
        self._apply_compact_scale()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_compact_scale()

    def _apply_compact_scale(self) -> None:
        scale = window_ui_scale(self)

        self.left_panel.setFixedWidth(max(280, int(380 * scale)))
        self.left_layout.setContentsMargins(
            max(24, int(50 * scale)),
            max(28, int(80 * scale)),
            max(24, int(50 * scale)),
            max(20, int(50 * scale)),
        )
        self.right_layout.setContentsMargins(
            max(24, int(60 * scale)),
            0,
            max(24, int(60 * scale)),
            0,
        )
        self.app_title.setFont(QFont("Segoe UI", max(26, int(42 * scale)), QFont.Weight.Bold))
        self.subtitle.setFont(QFont("Segoe UI", max(10, int(14 * scale)), QFont.Weight.Light))
        self.desc.setFont(QFont("Segoe UI", max(9, int(11 * scale))))
        self.author_label.setFont(QFont("Segoe UI", max(7, int(9 * scale)), QFont.Weight.DemiBold))
        self.version_info.setFont(QFont("Consolas", max(7, int(9 * scale))))
        self.copyright_info.setFont(QFont("Segoe UI", max(7, int(8 * scale))))
        self.header_text.setStyleSheet(
            f"font-size: {max(15, int(22 * scale))}px; font-weight: 600; color: #1A1C1E; margin-bottom: 30px;"
        )
        for card in self.module_cards:
            card.apply_scale(scale)
