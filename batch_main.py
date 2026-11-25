#!/usr/bin/env python3
"""Launch the independent RTGS multi-station console."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from rtgs.infrastructure import configure_logging
from ui.batch.console import BatchConsole


def create_batch_application(argv: Sequence[str] | None = None) -> tuple[QApplication, BatchConsole]:
    configure_logging()
    app = QApplication.instance() or QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("RTGS Multi-Station Console")
    app.setApplicationVersion("0.1")
    window = BatchConsole()
    window.show()
    return app, window


def main() -> None:
    app, _window = create_batch_application()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
