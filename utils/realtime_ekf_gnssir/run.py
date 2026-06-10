"""Run the package directly from this folder without installation."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


PACKAGE_NAME = "realtime_ekf_gnssir"


def _load_local_package() -> None:
    if PACKAGE_NAME in sys.modules:
        return
    package_dir = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        package_dir / "__init__.py",
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {PACKAGE_NAME} from {package_dir}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)


def main() -> int:
    _load_local_package()
    from realtime_ekf_gnssir.__main__ import main as package_main

    return package_main()


if __name__ == "__main__":
    raise SystemExit(main())
