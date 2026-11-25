"""Offscreen integration tests for the installed-compatible GUI shell."""

from __future__ import annotations

import logging
import os

from gui_main import APPLICATION_NAME, APPLICATION_VERSION, create_application
from rtcm_batch_gui import create_batch_application


def test_application_shell_switches_between_all_workbenches() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app, manager = create_application([])
    try:
        app.processEvents()
        assert app.applicationName() == APPLICATION_NAME
        assert app.applicationVersion() == APPLICATION_VERSION
        assert manager.current_module == "launch"
        assert manager.launch_screen is not None and manager.launch_screen.isVisible()
        assert logging.getLogger("rtgs").handlers

        for module_name, show_method, attr_name in (
            ("monitoring", manager.show_monitoring_module, "monitoring_window"),
            ("positioning", manager.show_positioning_module, "positioning_window"),
            ("reflectometry", manager.show_reflectometry_module, "reflectometry_window"),
            ("refractometry", manager.show_refractometry_module, "refractometry_window"),
        ):
            show_method()
            app.processEvents()
            window = getattr(manager, attr_name)
            assert manager.current_module == module_name
            assert window is not None and window.isVisible()

        manager.show_launch_screen()
        app.processEvents()
        assert manager.current_module == "launch"
        assert manager.launch_screen is not None and manager.launch_screen.isVisible()
    finally:
        manager.cleanup()
        app.processEvents()


def test_batch_application_factory_reuses_qt_application() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app, window = create_batch_application([])
    try:
        app.processEvents()
        assert app.applicationName() == "RTGS RTCM Batch Converter"
        assert window.isVisible()
    finally:
        window.close()
        app.processEvents()
