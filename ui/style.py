from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette

def get_app_stylesheet():
    """
    深度优化的蓝色系学术风格样式表。
    重点：深蓝色调、彻底覆盖白块、重构选项卡样式。
    """
    palette = QApplication.palette()
    base_color = palette.color(QPalette.ColorRole.Window)
    is_dark = base_color.lightness() < 128

    if is_dark:
        # --- 深海蓝色调 (Professional Dark Blue) ---
        bg_main    = "#0F121A"  # 极深蓝黑（主背景）
        bg_card    = "#1C212D"  # 深灰蓝（卡片/容器）
        bg_input   = "#161A23"  # 略深的输入框
        bg_hover   = "#2D3446"  # 悬停色
        border     = "#2F374A"  # 边框色
        fg_main    = "#E2E8F0"  # 主文字（冷白）
        fg_muted   = "#94A3B8"  # 辅助文字（灰蓝）
        accent     = "#3B82F6"  # 科技蓝 (Primary Blue)
        selection  = "#1E3A8A"  # 选中深蓝色
        # 绘图区专用色
        plot_bg    = "#0B0E14"
    else:
        # --- 专业浅蓝色调 (Clean Academic Light) ---
        bg_main    = "#F8FAFC"
        bg_card    = "#FFFFFF"
        bg_input   = "#F1F5F9"
        bg_hover   = "#E2E8F0"
        border     = "#CBD5E1"
        fg_main    = "#0F172A"
        fg_muted   = "#64748B"
        accent     = "#2563EB"
        selection  = "#DBEAFE"
        plot_bg    = "#FFFFFF"

    # 通用变量
    radius = "6px"
    font_stack = "Inter, 'Segoe UI', Roboto, 'Helvetica Neue', Arial"

    stylesheet = f"""
    /* 全局背景重置，防止任何地方露白 */
    QWidget {{
        background-color: {bg_main};
        color: {fg_main};
        font-family: {font_stack};
        font-size: 13px;
        outline: none;
    }}

    QAbstractScrollArea, QGraphicsView, QScrollArea {{
        background-color: {plot_bg};
        border: 1px solid {border};
        border-radius: {radius};
    }}

    /* 面板容器 */
    QFrame#Panel, QFrame#Container {{
        background-color: {bg_card};
        border: 1px solid {border};
        border-radius: {radius};
    }}

    /* 按钮 - 增强对比度 */
    QPushButton {{
        background-color: {bg_input};
        border: 1px solid {border};
        color: {fg_main};
        padding: 6px 15px;
        border-radius: {radius};
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {bg_hover};
        border-color: {accent};
    }}
    QPushButton:pressed {{
        background-color: {accent};
        color: white;
    }}
    QPushButton:default {{
        border: 2px solid {accent};
    }}

    /* 输入控件 */
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
        background-color: {bg_input};
        border: 1px solid {border};
        border-radius: {radius};
        padding: 5px 8px;
        selection-background-color: {accent};
    }}
    QLineEdit:focus, QComboBox:focus {{
        border: 1px solid {accent};
    }}

    /* 选项卡 (QTabBar) - 重构为卡片点击感 */
    QTabWidget::pane {{
        border: 1px solid {border};
        top: -1px; /* 让边框与标签融合 */
        background-color: {bg_card};
        border-radius: {radius};
    }}
    QTabBar::tab {{
        background-color: {bg_main};
        color: {fg_muted};
        padding: 8px 20px;
        margin-right: 4px;
        border: 1px solid {border};
        border-bottom: none;
        border-top-left-radius: {radius};
        border-top-right-radius: {radius};
    }}
    QTabBar::tab:selected {{
        background-color: {bg_card};
        color: {accent};
        font-weight: bold;
        border-bottom: 2px solid {bg_card}; /* 掩盖下边框 */
    }}
    QTabBar::tab:hover:not(:selected) {{
        background-color: {bg_hover};
    }}

    /* 表格与表头 - 专业数据感 */
    QHeaderView::section {{
        background-color: {bg_input};
        color: {fg_muted};
        padding: 6px;
        border: none;
        border-right: 1px solid {border};
        border-bottom: 1px solid {border};
        font-weight: bold;
    }}
    QTableWidget {{
        gridline-color: {border};
        background-color: {bg_card};
        alternate-background-color: {bg_input};
        selection-background-color: {selection};
    }}

    /* 滚动条 - 简约化 */
    QScrollBar:vertical {{
        border: none;
        background: {bg_main};
        width: 10px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: {border};
        min-height: 25px;
        border-radius: 5px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {fg_muted};
    }}

    /* 菜单与下拉框弹出层 - 强制深色 */
    QMenu, QComboBox QAbstractItemView {{
        background-color: {bg_card};
        border: 1px solid {border};
        padding: 4px;
    }}
    QMenu::item:selected {{
        background-color: {accent};
        color: white;
        border-radius: 4px;
    }}

    /* 分隔条 */
    QSplitter::handle {{
        background-color: {border};
    }}
    QSplitter::handle:horizontal {{
        width: 1px;
    }}
    QSplitter::handle:vertical {{
        height: 1px;
    }}

    /* 状态栏 */
    QStatusBar {{
        background-color: {bg_input};
        color: {fg_muted};
        border-top: 1px solid {border};
    }}
    
    /* 解决坐标轴文字在深色模式下的显示 */
    QLabel {{
        background-color: transparent;
        color: {fg_main};
        padding: 2px;
    }}

    QLabel[class="status"] {{
        background-color: {bg_hover};
        border: 1px solid {border};
        border-radius: 10px;
        padding: 2px 10px;
        font-weight: bold;
        font-size: 11px;
    }}
    """
    return stylesheet