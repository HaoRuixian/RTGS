"""Shared GNSS color helpers used by the active PySide6 UI modules."""

from __future__ import annotations

SYSTEM_COLORS = {
    "G": "#5E8C61",
    "R": "#B05E5E",
    "E": "#5B84B1",
    "C": "#8E77A4",
    "J": "#C48D4D",
    "S": "#7F8C8D",
    "I": "#3E8E7E",
}

SIGNAL_COLORS = {
    "1": {
        ("C", "S", "A", "D"): "#4A90E2",
        ("W", "P", "Y"): "#34495E",
        ("L", "X", "Z"): "#85ADDB",
        ("I", "B", "E"): "#A9C1D9",
        (): "#5D8AA8",
    },
    "2": {
        ("C", "I"): "#D96459",
        ("W", "P", "Y"): "#8C4646",
        ("L", "S", "X"): "#E39E82",
        ("Q",): "#F2C1B0",
        (): "#C06C84",
    },
    "5": {
        ("Q", "X"): "#73956F",
        ("I", "D", "A"): "#4A6741",
        ("P",): "#9CB380",
        ("B", "C", "Z"): "#C5D1B3",
        (): "#86A697",
    },
    "6": {
        ("I", "S"): "#7D6E83",
        ("Q", "L"): "#B0A4B5",
        ("X", "E", "Z"): "#5E548E",
        (): "#9B89B3",
    },
    "7": {
        ("Q",): "#D4A373",
        ("I", "D"): "#E9C46A",
        ("X", "P", "Z"): "#B5838D",
        ("A", "B"): "#F4E1D2",
        (): "#CCAC93",
    },
    "9": {
        ("A",): "#2A9D8F",
        ("B", "C"): "#52B69A",
        ("X",): "#76C893",
        (): "#95D5B2",
    },
}

DEFAULT_SYSTEM_COLOR = "#555555"
DEFAULT_SIGNAL_COLOR = "#95A5A6"


def _detect_band(signal_code: str) -> str:
    for band in ("1", "2", "5", "6", "7", "8", "9"):
        if band in signal_code:
            return "7" if band == "8" else band
    return "1"


def _detect_suffix(signal_code: str) -> str:
    for char in signal_code:
        if char.isalpha():
            return char
    return ""


def get_sys_color(sys_char: str) -> str:
    """Return the display color for a GNSS constellation identifier."""

    return SYSTEM_COLORS.get(str(sys_char).upper(), DEFAULT_SYSTEM_COLOR)


def get_signal_color(sig_code: str) -> str:
    """Return the display color for a signal identifier such as ``1C`` or ``5Q``."""

    code = str(sig_code).upper()
    band = _detect_band(code)
    suffix = _detect_suffix(code)
    palette = SIGNAL_COLORS.get(band, {})
    for suffixes, color in palette.items():
        if suffix in suffixes:
            return color
    return palette.get((), DEFAULT_SIGNAL_COLOR)


__all__ = ["SIGNAL_COLORS", "SYSTEM_COLORS", "get_signal_color", "get_sys_color"]
