#!/usr/bin/env python3
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

import os
import sys
from collections.abc import Sequence

# Qt's GTK platform theme reads the deprecated GNOME xsettings ``antialiasing``
# key on some Ubuntu installations and aborts the process when that key is
# absent.  RTGS supplies its own Fusion palette, so the generic Qt theme is a
# suitable Linux default.  Keep an explicit user choice intact.
if sys.platform.startswith("linux") and not os.environ.get("QT_QPA_PLATFORMTHEME"):
    os.environ["QT_QPA_PLATFORMTHEME"] = "generic"

from PySide6.QtWidgets import QApplication

from rtgs.infrastructure import configure_logging
from ui.app.manager import AppManager

APPLICATION_NAME = "RTGS - RealTimeGNSS Studio"
APPLICATION_VERSION = "0.1"


def create_application(argv: Sequence[str] | None = None) -> tuple[QApplication, AppManager]:
    """Create the desktop application without entering the Qt event loop."""
    configure_logging()
    app = QApplication.instance() or QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName(APPLICATION_NAME)
    app.setApplicationVersion(APPLICATION_VERSION)

    manager = AppManager(app)
    manager.show_launch_screen()
    return app, manager


def main() -> None:
    app, _manager = create_application()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
