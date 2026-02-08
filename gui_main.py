#!/usr/bin/env python3
"""
RTGS - RealTimeGNSS Studio
Main GUI Application Entry Point
"""

import sys
from PySide6.QtWidgets import QApplication
from ui.app_manager import AppManager

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RTGS - RealTimeGNSS Studio")
    app.setApplicationVersion("0.1")

    manager = AppManager(app)
    manager.show_launch_screen()  

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
