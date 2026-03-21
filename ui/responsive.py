from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication


@dataclass(frozen=True)
class ScreenProfile:
    width: int
    height: int
    ui_scale: float
    tag: str


def _available_geometry(window=None) -> QRect | None:
    app = QGuiApplication.instance()
    if app is None:
        return None

    screen = None
    if window is not None:
        try:
            handle = window.windowHandle()
            if handle is not None and handle.screen() is not None:
                screen = handle.screen()
        except Exception:
            screen = None
        if screen is None:
            try:
                screen = window.screen()
            except Exception:
                screen = None

    if screen is None:
        screen = app.primaryScreen()
    if screen is None:
        return None
    return screen.availableGeometry()


def detect_screen_profile(width: int, height: int) -> ScreenProfile:
    if width <= 1366 or height <= 768:
        return ScreenProfile(width=width, height=height, ui_scale=0.90, tag="720p")
    if width <= 1920 or height <= 1080:
        return ScreenProfile(width=width, height=height, ui_scale=0.97, tag="1080p")
    if width <= 2560 or height <= 1440:
        return ScreenProfile(width=width, height=height, ui_scale=1.0, tag="2k")
    if width <= 3200 or height <= 1800:
        return ScreenProfile(width=width, height=height, ui_scale=1.0, tag="3k")
    return ScreenProfile(width=width, height=height, ui_scale=1.0, tag="4k+")


def compute_ui_scale(width: int, height: int | None = None) -> float:
    height = 0 if height is None else int(height)
    return detect_screen_profile(int(width), height).ui_scale


def window_ui_scale(window) -> float:
    geometry = _available_geometry(window)
    if geometry is None:
        return compute_ui_scale(window.width(), window.height())
    return compute_ui_scale(geometry.width(), geometry.height())


def adaptive_window_size(
    window,
    target: Tuple[int, int],
    minimum: Tuple[int, int],
    max_fill_w: float = 0.92,
    max_fill_h: float = 0.90,
) -> None:
    geometry = _available_geometry(window)
    if geometry is None:
        window.resize(*target)
        window.setMinimumSize(*minimum)
        return

    screen_w = max(1, geometry.width())
    screen_h = max(1, geometry.height())

    wanted_w = min(int(screen_w * max_fill_w), int(target[0]))
    wanted_h = min(int(screen_h * max_fill_h), int(target[1]))
    wanted_w = max(860, wanted_w)
    wanted_h = max(560, wanted_h)

    min_w = min(int(minimum[0]), max(820, int(screen_w * 0.68)))
    min_h = min(int(minimum[1]), max(520, int(screen_h * 0.68)))

    final_w = max(wanted_w, min_w)
    final_h = max(wanted_h, min_h)
    final_w = min(final_w, screen_w)
    final_h = min(final_h, screen_h)

    window.setMinimumSize(min_w, min_h)
    window.resize(final_w, final_h)
    _center_to_available_geometry(window, geometry)


def _center_to_available_geometry(window, geometry: QRect) -> None:
    frame = window.frameGeometry()
    frame.moveCenter(geometry.center())
    window.move(frame.topLeft())
