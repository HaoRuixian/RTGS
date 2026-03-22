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
        self._base_width = 500
        self._base_height = 96
        self._accent_color = accent_color

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)

        self.icon_widget = QSvgWidget()
        self.icon_widget.setFixedSize(26, 26)
        svg_data = ICONS[icon_key].format(color=accent_color)
        self.icon_widget.load(svg_data.encode("utf-8"))

        icon_bg = QFrame()
        icon_bg.setFixedSize(48, 48)
        icon_bg.setStyleSheet(
            f"background-color: {accent_color}12; border: 1px solid {accent_color}22; border-radius: 12px;"
        )
        icon_bg_layout = QVBoxLayout(icon_bg)
        icon_bg_layout.setContentsMargins(0, 0, 0, 0)
        icon_bg_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_bg_layout.addWidget(self.icon_widget)
        layout.addWidget(icon_bg)

        # 文本区域
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")

        self.desc_label = QLabel(description)
        self.desc_label.setObjectName("cardDesc")
        self.desc_label.setWordWrap(True)

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.desc_label)
        layout.addLayout(text_layout, 1)

        # 右侧箭头提示
        self.arrow_label = QLabel("›")
        self.arrow_label.setStyleSheet(
            f"font-size: 22px; font-weight: 600; color: {accent_color}; background: transparent;"
        )
        self.arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.arrow_label.setFixedWidth(20)
        layout.addWidget(self.arrow_label)

        # 阴影更轻一些
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(16)
        self.shadow.setXOffset(0)
        self.shadow.setYOffset(4)
        self.shadow.setColor(QColor(0, 0, 0, 18))
        self.setGraphicsEffect(self.shadow)

        self.apply_scale(1.0)
        self._set_style(False)

    def apply_scale(self, scale: float) -> None:
        height = max(82, int(self._base_height * scale))
        self.setFixedHeight(height)

        self.title_label.setStyleSheet(
            f"font-size: {max(12, int(15 * scale))}px; "
            f"font-weight: 650; color: #1F2933; background: transparent;"
        )
        self.desc_label.setStyleSheet(
            f"font-size: {max(9, int(11 * scale))}px; "
            f"color: #6B7280; background: transparent; line-height: 135%;"
        )
        self.arrow_label.setStyleSheet(
            f"font-size: {max(18, int(22 * scale))}px; font-weight: 600; "
            f"color: {self._accent_color}; background: transparent;"
        )

    def _set_style(self, hovered):
        border_color = f"{self._accent_color}" if hovered else "#E6EBF0"
        bg_color = "#F8FBFF" if hovered else "#FFFFFF"
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 14px;
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
        adaptive_window_size(self, target=(900, 560), minimum=(800, 560))
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

        # =========================
        # 左侧信息栏
        # =========================
        self.left_panel = QFrame()
        self.left_panel.setFixedWidth(320)
        self.left_panel.setStyleSheet(
            """
            QFrame {
                background-color: #16181B;
                border-right: 1px solid #262A2F;
            }
            QLabel {
                background: transparent;
                color: #E5E7EB;
            }
            """
        )

        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(32, 34, 32, 28)
        self.left_layout.setSpacing(0)

        self.app_title = QLabel("RTGS")
        self.app_title.setStyleSheet("color: #FFFFFF; letter-spacing: 2px;")
        self.left_layout.addWidget(self.app_title)

        self.left_layout.addSpacing(4)

        self.subtitle = QLabel("Real-Time GNSS Studio")
        self.subtitle.setStyleSheet("color: #2EA8FF;")
        self.left_layout.addWidget(self.subtitle)

        self.left_layout.addSpacing(18)

        line = QFrame()
        line.setFixedSize(36, 3)
        line.setStyleSheet("background-color: #2EA8FF; border-radius: 1px;")
        self.left_layout.addWidget(line)

        self.left_layout.addSpacing(18)

        self.desc = QLabel(
            "Integrated platform for GNSS monitoring, positioning, "
            "reflectometry and atmospheric analysis."
        )
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("color: #98A2B3; line-height: 150%;")
        self.left_layout.addWidget(self.desc)

        self.left_layout.addSpacing(18)

        self.left_layout.addStretch()

        self.author_label = QLabel("Ruixian Hao | vitamin_n@outlook.com")
        self.author_label.setStyleSheet("color: #C9D1D9;")
        self.left_layout.addWidget(self.author_label)

        self.left_layout.addSpacing(6)

        self.version_info = QLabel("VERSION 0.1.0-ALPHA")
        self.version_info.setStyleSheet("color: #667085; letter-spacing: 1px;")
        self.left_layout.addWidget(self.version_info)

        self.left_layout.addSpacing(4)

        self.copyright_info = QLabel("© 2026 Ruixian Hao")
        self.copyright_info.setStyleSheet("color: #4B5563;")
        self.left_layout.addWidget(self.copyright_info)

        main_layout.addWidget(self.left_panel)

        # =========================
        # 右侧工作台区域
        # =========================
        right_container = QWidget()
        right_container.setStyleSheet("background-color: #F5F7FA;")
        self.right_layout = QVBoxLayout(right_container)
        self.right_layout.setContentsMargins(36, 26, 36, 26)
        self.right_layout.setSpacing(0)

        self.header_text = QLabel("Workbench")
        self.header_text.setStyleSheet(
            "font-size: 22px; font-weight: 700; color: #111827;"
        )
        self.right_layout.addWidget(self.header_text)

        self.right_layout.addSpacing(6)

        self.header_subtext = QLabel(
            "Choose a processing module to enter the corresponding GNSS workspace."
        )
        self.header_subtext.setStyleSheet(
            "font-size: 12px; color: #6B7280; margin-bottom: 16px;"
        )
        self.right_layout.addWidget(self.header_subtext)

        self.cards_container = QVBoxLayout()
        self.cards_container.setSpacing(10)

        modules = [
            ("monitoring", "Signal Quality Monitoring",
            "Real-time observation of SNR/CNR, constellation health.", "#0064D2"),
            ("positioning", "Precise Positioning",
            "High-precision RTK/PPP solutions with multi-frequency fusion.", "#0064D2"),
            ("reflectometry", "GNSS-Reflectometry",
            "Surface-reflected signal analysis for sea level, snow depth and environmental sensing.", "#0064D2"),
            ("refractometry", "GNSS-Refractometry",
            "Tropospheric and ionospheric delay modeling with ZTD estimation.", "#0064D2"),
        ]

        for mod_id, title, desc, color in modules:
            btn = ModuleCard(title, desc, mod_id, color)
            btn.clicked.connect(lambda chk, m=mod_id: self.module_selected.emit(m))
            self.module_cards.append(btn)
            self.cards_container.addWidget(btn)

        self.right_layout.addLayout(self.cards_container)
        self.right_layout.addStretch()

        main_layout.addWidget(right_container, 1)

        self._apply_compact_scale()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_compact_scale()

    def _apply_compact_scale(self) -> None:
        scale = window_ui_scale(self)

        self.left_panel.setFixedWidth(max(260, int(320 * scale)))

        self.left_layout.setContentsMargins(
            max(20, int(32 * scale)),
            max(20, int(34 * scale)),
            max(20, int(32 * scale)),
            max(18, int(28 * scale)),
        )

        self.right_layout.setContentsMargins(
            max(20, int(36 * scale)),
            max(18, int(26 * scale)),
            max(20, int(36 * scale)),
            max(18, int(26 * scale)),
        )

        self.app_title.setFont(QFont("Segoe UI", max(24, int(34 * scale)), QFont.Weight.Bold))
        self.subtitle.setFont(QFont("Segoe UI", max(10, int(13 * scale)), QFont.Weight.Medium))
        self.desc.setFont(QFont("Segoe UI", max(9, int(10 * scale))))
        self.author_label.setFont(QFont("Segoe UI", max(8, int(9 * scale)), QFont.Weight.Medium))
        self.version_info.setFont(QFont("Consolas", max(7, int(8 * scale))))
        self.copyright_info.setFont(QFont("Segoe UI", max(7, int(8 * scale))))

        self.header_text.setStyleSheet(
            f"font-size: {max(17, int(22 * scale))}px; font-weight: 700; color: #111827;"
        )
        self.header_subtext.setStyleSheet(
            f"font-size: {max(10, int(12 * scale))}px; color: #6B7280; margin-bottom: 16px;"
        )

        for card in self.module_cards:
            card.apply_scale(scale)
