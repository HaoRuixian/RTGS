# ui/app_manager.py
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtCore import Signal, QObject
from PySide6.QtGui import QPalette, QColor, QFont

from ui.launch_screen import LaunchScreen
from ui.monitoring_module import MonitoringModule
from ui.positioning_module import PositioningModule
from ui.reflectometry_module import ReflectometryModule
from ui.refractometry_module import RefractometryModule


class AppManager(QObject):
    """
    Application manager - coordinates module lifecycle and switching
    """
    
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.launch_screen = None
        self.monitoring_window = None
        self.positioning_window = None
        self.reflectometry_window = None
        self.refractometry_window = None
        
        self.current_module = None
        
        self.apply_global_style()
    
    def apply_global_style(self):
        """Apply global application style"""
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
        font.setFamily("Microsoft YaHei")
        font.setPointSize(9)
        self.app.setFont(font)
    
    def show_launch_screen(self):
        """Show the launch screen"""
        self.close_all_modules()
        
        self.launch_screen = LaunchScreen()
        self.launch_screen.module_selected.connect(self.on_module_selected)
        self.launch_screen.show()
        
        self.current_module = 'launch'
    
    def on_module_selected(self, module_name):
        """Handle module selection"""
        if module_name == 'monitoring':
            self.show_monitoring_module()
        elif module_name == 'positioning':
            self.show_positioning_module()
        elif module_name == 'reflectometry':
            self.show_reflectometry_module()
        elif module_name == 'refractometry':
            self.show_refractometry_module()
    
    def show_monitoring_module(self):
        """Show the monitoring module"""
        if self.launch_screen:
            self.launch_screen.close()
            self.launch_screen = None
        
        if self.positioning_window:
            self.positioning_window.close()
            self.positioning_window = None
        if self.reflectometry_window:
            self.reflectometry_window.close()
            self.reflectometry_window = None
        
        if not self.monitoring_window:
            self.monitoring_window = MonitoringModule()
            self.monitoring_window.back_to_launcher.connect(self.show_launch_screen)
        
        self.monitoring_window.show()
        self.current_module = 'monitoring'
    
    def show_positioning_module(self):
        """Show the positioning module"""
        if self.launch_screen:
            self.launch_screen.close()
            self.launch_screen = None
        
        if self.monitoring_window:
            self.monitoring_window.close()
            self.monitoring_window = None
        if self.reflectometry_window:
            self.reflectometry_window.close()
            self.reflectometry_window = None
        
        if not self.positioning_window:
            self.positioning_window = PositioningModule()
            self.positioning_window.back_to_launcher.connect(self.show_launch_screen)
        
        self.positioning_window.show()
        self.current_module = 'positioning'
    
    def show_reflectometry_module(self):
        """Show the reflectometry module"""
        if self.launch_screen:
            self.launch_screen.close()
            self.launch_screen = None
        
        if self.monitoring_window:
            self.monitoring_window.close()
            self.monitoring_window = None
        if self.positioning_window:
            self.positioning_window.close()
            self.positioning_window = None
        if self.refractometry_window:
            self.refractometry_window.close()
            self.refractometry_window = None
        
        if not self.reflectometry_window:
            self.reflectometry_window = ReflectometryModule()
            self.reflectometry_window.back_to_launcher.connect(self.show_launch_screen)
        
        self.reflectometry_window.show()
        self.current_module = 'reflectometry'
    
    def show_refractometry_module(self):
        """Show the refractometry module"""
        if self.launch_screen:
            self.launch_screen.close()
            self.launch_screen = None
        
        if self.monitoring_window:
            self.monitoring_window.close()
            self.monitoring_window = None
        if self.positioning_window:
            self.positioning_window.close()
            self.positioning_window = None
        if self.reflectometry_window:
            self.reflectometry_window.close()
            self.reflectometry_window = None
        
        if not self.refractometry_window:
            self.refractometry_window = RefractometryModule()
            self.refractometry_window.back_to_launcher.connect(self.show_launch_screen)
        
        self.refractometry_window.show()
        self.current_module = 'refractometry'
    
    def close_all_modules(self):
        """Close all module windows"""
        if self.launch_screen:
            self.launch_screen.close()
            self.launch_screen = None
        if self.monitoring_window:
            self.monitoring_window.close()
            self.monitoring_window = None
        if self.positioning_window:
            self.positioning_window.close()
            self.positioning_window = None
        if self.reflectometry_window:
            self.reflectometry_window.close()
            self.reflectometry_window = None
        if self.refractometry_window:
            self.refractometry_window.close()
            self.refractometry_window = None
    
    def cleanup(self):
        """Clean up resources"""
        self.close_all_modules()