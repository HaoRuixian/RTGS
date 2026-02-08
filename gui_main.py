#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================
RTGS - RealTimeGNSS Studio
==========================

Main GUI Application for RTGS (Real-Time GNSS Studio).

Author:  RuixianHao
Date:    2026-02-08
Email:   vitamin_n@outlook.com

Copyright
© RuixianHao. All rights reserved.

Created for research and engineering purposes in the field of
real-time GNSS data processing and analysis.
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
