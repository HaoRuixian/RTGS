from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QFrame, QSizePolicy, QGraphicsDropShadowEffect)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QColor, QPixmap, QPainter, QPen, QBrush, QIcon
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtSvg import QSvgRenderer
from pathlib import Path

# --- SVG ---
ICONS = {
    # Monitoring
    "monitoring": '''<svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
    </svg>''',
    
    # Positioning
    "positioning": '''<svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        <circle cx="12" cy="10" r="2"/>
    </svg>''',
    
    # Reflectometry
    "reflectometry": '''<svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M2 19h20" opacity="0.3"/> 
        <path d="M3 5l9 11 9-11"/>
        <path d="M12 16v5" stroke-dasharray="2 2"/>
    </svg>''',
    
    # Refractometry
    "refractometry": '''<svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M2 8h20" opacity="0.2"/>
        <path d="M2 16h20" opacity="0.2"/>
        <path d="M5 3l4 5 2 8 5 5"/>
    </svg>'''
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
        self.setFixedSize(520, 120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(20)

        # 左侧图标 (使用 QSvgWidget)
        self.icon_widget = QSvgWidget()
        self.icon_widget.setFixedSize(45, 45)
        # 将 SVG 字符串中的颜色替换为当前主题色
        svg_data = ICONS[icon_key].format(color=accent_color)
        self.icon_widget.load(svg_data.encode('utf-8'))
        
        # 图标容器（带圆角背景）
        icon_bg = QFrame()
        icon_bg.setFixedSize(70, 70)
        icon_bg.setStyleSheet(f"background-color: {accent_color}10; border-radius: 15px;")
        icon_bg_layout = QVBoxLayout(icon_bg)
        icon_bg_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_bg_layout.addWidget(self.icon_widget)
        layout.addWidget(icon_bg)

        # 文字区
        text_layout = QVBoxLayout()
        text_layout.setSpacing(5)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-size: 17px; font-weight: 700; color: #263238; background: transparent;")
        
        self.desc_label = QLabel(description)
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("font-size: 12px; color: #546E7A; background: transparent; line-height: 140%;")
        
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.desc_label)
        layout.addLayout(text_layout)
        
        self.accent_color = accent_color
        self._set_style(False)

        # 阴影
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(20)
        self.shadow.setXOffset(0)
        self.shadow.setYOffset(6)
        self.shadow.setColor(QColor(0, 0, 0, 25))
        self.setGraphicsEffect(self.shadow)

    def _set_style(self, hovered):
        border_color = self.accent_color if hovered else "#ECEFF1"
        bg_color = "#FFFFFF" if not hovered else "#FAFDFF"
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 16px;
                text-align: left;
            }}
        """)

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
        self.resize(1100, 720)
        self.setStyleSheet("background-color: #F8F9FA;")
        self.set_window_icon(WINDOW_ICON_SVG)
        
        self.setStyleSheet("background-color: #F8F9FA;")
        self.setup_ui()

    def set_window_icon(self, svg_str):
        """将 SVG 字符串转换为窗口图标"""
        renderer = QSvgRenderer(svg_str.encode('utf-8'))
        
        # 创建一个 256x256 的高清 Pixmap
        pixmap = QPixmap(256, 256)
        pixmap.fill(Qt.GlobalColor.transparent) # 设置背景透明
        
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        
        # 设置为窗口图标
        self.setWindowIcon(QIcon(pixmap))
        
        # 如果是 Windows 系统，还需要设置 App User Model ID 才能在任务栏显示独立图标
        import ctypes
        myappid = 'mycompany.myproduct.subproduct.version' # 随便起个唯一名字
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)


    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- 左侧品牌面板 ---
        left_panel = QFrame()
        left_panel.setFixedWidth(380)
        left_panel.setStyleSheet("""
            QFrame {
                background-color: #1A1C1E; 
                border-right: 1px solid #2C2E30;
            }
            QLabel { color: #E3E2E6; background: transparent; }
        """)
        
        left_layout = QVBoxLayout(left_panel)
        # 增加边距，特别是顶部边距，让内容沉下来
        left_layout.setContentsMargins(50, 80, 50, 50)
        left_layout.setSpacing(0) # 间距通过 addSpacing 精确控制
        
        # 1. 标题区
        app_title = QLabel("RTGS")
        app_title.setFont(QFont("Segoe UI", 42, QFont.Weight.Bold))
        app_title.setStyleSheet("color: #FFFFFF; letter-spacing: 3px;")
        left_layout.addWidget(app_title)

        left_layout.addSpacing(5) # 精确控制标题和副标题间距

        subtitle = QLabel("Real-Time GNSS Studio")
        subtitle.setFont(QFont("Segoe UI", 14, QFont.Weight.Light))
        subtitle.setStyleSheet("color: #00A0FF;") # 赋予一个主题色，更有活力
        left_layout.addWidget(subtitle)

        left_layout.addSpacing(30)
        
        # 装饰线
        line = QFrame()
        line.setFixedWidth(40)
        line.setFixedHeight(3)
        line.setStyleSheet("background-color: #00A0FF; border-radius: 1px;")
        left_layout.addWidget(line)

        left_layout.addSpacing(30)

        # 2. 描述区
        desc = QLabel(
            "Professional-grade suite for multi-constellation "
            "GNSS data processing, signal analysis, and "
            "atmospheric research."
        )
        desc.setWordWrap(True)
        desc.setFont(QFont("Segoe UI", 11))
        desc.setStyleSheet("color: #A8AAB2; line-height: 160%;")
        left_layout.addWidget(desc)

        left_layout.addSpacing(25)

        # 作者信息
        author_label = QLabel("Developer: Ruixian Hao\nEmail: vitamin_n@outlook.com")
        author_label.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        author_label.setStyleSheet("color: #E3E2E6;")
        left_layout.addWidget(author_label)

        # 伸缩空间：将后面的内容推到底部
        left_layout.addStretch()

        # 3. 底部信息区 (版本与版权)
        # 版本号
        version_info = QLabel("VERSION 0.1.0-ALPHA")
        version_info.setFont(QFont("Consolas", 9)) # 使用等宽字体更有极客感
        version_info.setStyleSheet("color: #44474E; letter-spacing: 1px;")
        left_layout.addWidget(version_info)
        
        left_layout.addSpacing(8)

        # 版权声明
        copyright_info = QLabel("© 2026 Ruixian Hao.\nAll Rights Reserved.")
        copyright_info.setWordWrap(True)
        copyright_info.setFont(QFont("Segoe UI", 8))
        copyright_info.setStyleSheet("color: #44474E; line-height: 130%;")
        left_layout.addWidget(copyright_info)
        
        main_layout.addWidget(left_panel)
        

        # --- 右侧功能区 ---
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(60, 0, 60, 0)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        header_text = QLabel("Select Workbench")
        header_text.setStyleSheet("font-size: 22px; font-weight: 600; color: #1A1C1E; margin-bottom: 30px;")
        right_layout.addWidget(header_text)


        modules = [
            ("monitoring", "Signal Quality Monitoring", 
             "Real-time observation of SNR/CNR, constellation health.", "#0064D2"),
            ("positioning", "Precise Positioning", 
             "High-precision RTK/PPP solutions with multi-frequency fusion.", "#0064D2"),
            ("reflectometry", "GNSS-Reflectometry", 
             "Analysis of surface-reflected signals for environmental sensing.", "#0064D2"),
            ("refractometry", "GNSS-Refractometry", 
             "Tropospheric and ionospheric delay modeling and ZTD estimation.", "#0064D2")
        ]

        for mod_id, title, desc, color in modules:
            btn = ModuleCard(title, desc, mod_id, color)
            btn.clicked.connect(lambda chk, m=mod_id: self.module_selected.emit(m))
            right_layout.addWidget(btn)
            right_layout.addSpacing(15)

        main_layout.addWidget(right_container)