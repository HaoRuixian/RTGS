"""RTGS 应用壳层，负责启动页和各功能模块窗口切换。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from ui.app.launch_screen import LaunchScreen
from ui.monitoring.module import MonitoringModule
from ui.positioning.module import PositioningModule
from ui.reflectometry.module import ReflectometryModule
from ui.refractometry.module import RefractometryModule


APP_FONT_FAMILY = "Microsoft YaHei"
APP_FONT_POINT_SIZE = 9
MODULE_WINDOW_ATTRS = (
    "monitoring_window",
    "positioning_window",
    "reflectometry_window",
    "refractometry_window",
)


class AppManager(QObject):
    """
    管理主应用的全局样式、启动页和各功能模块生命周期。

    Args:
        app: Qt 应用实例。
    """

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.launch_screen: LaunchScreen | None = None
        self.monitoring_window: MonitoringModule | None = None
        self.positioning_window: PositioningModule | None = None
        self.reflectometry_window: ReflectometryModule | None = None
        self.refractometry_window: RefractometryModule | None = None
        self.current_module: str | None = None

        self.apply_global_style()

    def apply_global_style(self) -> None:
        """
        应用全局 Qt 样式。

        这里集中维护应用级字体和调色板，避免各模块重复设置基础视觉风格。
        """
        self.app.setStyle("Fusion")
        palette = QPalette()

        palette.setColor(QPalette.ColorRole.Window, QColor(250, 250, 250))
        palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(245, 245, 245))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.Text, QColor(20, 20, 20))
        palette.setColor(QPalette.ColorRole.Button, QColor(245, 245, 245))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(52, 125, 255))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        self.app.setPalette(palette)

        font = self.app.font()
        font.setFamily(APP_FONT_FAMILY)
        font.setPointSize(APP_FONT_POINT_SIZE)
        self.app.setFont(font)

    def show_launch_screen(self) -> None:
        """关闭功能模块并显示启动页。"""
        self.close_all_modules()

        self.launch_screen = LaunchScreen()
        self.launch_screen.module_selected.connect(self.on_module_selected)
        self.launch_screen.show()
        self.current_module = "launch"

    def on_module_selected(self, module_name: str) -> None:
        """
        根据启动页选择打开对应模块。

        Args:
            module_name: 启动页发出的模块名称。
        """
        module_actions: dict[str, Callable[[], None]] = {
            "monitoring": self.show_monitoring_module,
            "positioning": self.show_positioning_module,
            "reflectometry": self.show_reflectometry_module,
            "refractometry": self.show_refractometry_module,
        }
        action = module_actions.get(module_name)
        if action is not None:
            action()

    def show_monitoring_module(self) -> None:
        """显示实时监测模块。"""
        self._show_module("monitoring", "monitoring_window", MonitoringModule)

    def show_positioning_module(self) -> None:
        """显示定位解算模块。"""
        self._show_module("positioning", "positioning_window", PositioningModule)

    def show_reflectometry_module(self) -> None:
        """显示 GNSS-IR 反射测量模块。"""
        self._show_module("reflectometry", "reflectometry_window", ReflectometryModule)

    def show_refractometry_module(self) -> None:
        """显示折射测量模块。"""
        self._show_module("refractometry", "refractometry_window", RefractometryModule)

    def close_all_modules(self) -> None:
        """关闭启动页和所有功能模块窗口。"""
        self._close_launch_screen()
        for attr_name in MODULE_WINDOW_ATTRS:
            self._close_window_attr(attr_name)

    def cleanup(self) -> None:
        """释放应用窗口资源。"""
        self.close_all_modules()

    def _show_module(
        self,
        module_name: str,
        attr_name: str,
        module_cls: type[QWidget],
    ) -> None:
        """显示一个功能模块，并关闭其它已打开模块。"""
        self._close_launch_screen()
        self._close_other_modules(except_attr=attr_name)

        window = getattr(self, attr_name)
        if window is None:
            window = module_cls()
            window.back_to_launcher.connect(self.show_launch_screen)
            setattr(self, attr_name, window)

        window.show()
        self.current_module = module_name

    def _close_launch_screen(self) -> None:
        """关闭启动页窗口。"""
        if self.launch_screen is not None:
            self.launch_screen.close()
            self.launch_screen = None

    def _close_other_modules(self, except_attr: str) -> None:
        """关闭除目标模块外的其它功能模块。"""
        for attr_name in MODULE_WINDOW_ATTRS:
            if attr_name != except_attr:
                self._close_window_attr(attr_name)

    def _close_window_attr(self, attr_name: str) -> None:
        """按属性名关闭并清空窗口引用。"""
        window = getattr(self, attr_name)
        if window is not None:
            window.close()
            setattr(self, attr_name, None)
