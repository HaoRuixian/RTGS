#!/usr/bin/env python3
"""Launch the standalone RTCM batch converter window."""

from ui.rtcm_batch_converter import create_batch_application, main

__all__ = ["create_batch_application", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
