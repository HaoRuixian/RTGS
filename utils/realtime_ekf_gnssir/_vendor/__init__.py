"""Vendored runtime dependencies for the standalone service package."""

from __future__ import annotations

from importlib import import_module
import sys


def install_aliases() -> None:
    """Expose vendored packages under their historical import names.

    The EKF-GNSSIR algorithm modules were originally developed as
    ``core.reflectometry``. Keeping that import name available lets the copied
    algorithm package run unchanged while the whole application still lives in
    this standalone directory.
    """

    core_pkg = import_module(f"{__name__}.core")
    sys.modules.setdefault("core", core_pkg)


__all__ = ["install_aliases"]
