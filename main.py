"""Compatibility entry point for launching the RTGS desktop application."""

from gui_main import APPLICATION_NAME, APPLICATION_VERSION, create_application, main

__all__ = ["APPLICATION_NAME", "APPLICATION_VERSION", "create_application", "main"]


if __name__ == "__main__":
    main()
