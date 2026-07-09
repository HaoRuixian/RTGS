"""Module entrypoint for ``python -m core.reflectometry``."""

from __future__ import annotations

import argparse

from ..config_paths import default_ir_config_path, ensure_config_directories
from .config import dump_example_config, load_config


def build_parser() -> argparse.ArgumentParser:
    ensure_config_directories()
    parser = argparse.ArgumentParser(description="GNSS-IR realtime reflector subsystem")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate-config", help="Validate a YAML configuration file")
    validate_parser.add_argument("--config", required=True, help="Path to the YAML configuration file")

    dump_parser = subparsers.add_parser("dump-example-config", help="Write the bundled example YAML")
    dump_parser.add_argument("--output", default=str(default_ir_config_path()))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "dump-example-config":
        print(f"Example config written to: {dump_example_config(args.output)}")
        return 0
    if args.command == "validate-config":
        config = load_config(args.config)
        print(f"Config is valid for station {config.station.station_id}")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
