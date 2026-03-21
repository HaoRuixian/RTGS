"""Module entrypoint for ``python -m core.reflectometry``."""

from __future__ import annotations

import argparse
from pathlib import Path

from core.reflectometry.config import DEFAULT_CONFIG_YAML, dump_example_config, load_config
from core.reflectometry.services.batch import BatchProcessor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GNSS-IR reflector subsystem")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a reflector batch job")
    run_parser.add_argument("--config", required=True, help="Path to the YAML configuration file")
    run_parser.add_argument("--no-write", action="store_true", help="Skip writing CSV/JSON outputs")

    validate_parser = subparsers.add_parser("validate-config", help="Validate a YAML configuration file")
    validate_parser.add_argument("--config", required=True, help="Path to the YAML configuration file")

    dump_parser = subparsers.add_parser("dump-example-config", help="Write the bundled example YAML")
    dump_parser.add_argument("--output", default="core/reflectometry/mock_reflectometry.yaml")

    demo_parser = subparsers.add_parser("mock-demo", help="Run the bundled mock demo configuration")
    demo_parser.add_argument("--output-dir", default="output/reflectometry_demo")
    demo_parser.add_argument("--config-out", default="output/reflectometry_demo/mock_reflectometry.yaml")
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
    if args.command == "mock-demo":
        config_path = Path(args.config_out)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        demo_yaml = DEFAULT_CONFIG_YAML.replace("output/reflectometry", args.output_dir.replace("\\", "/"))
        config_path.write_text(demo_yaml, encoding="utf-8")
        config = load_config(config_path)
        processor = BatchProcessor(config)
        result = processor.run()
        written = processor.write_outputs(result)
        print(f"Mock demo complete: {len(result.arc_solutions)} arc solutions, {len(result.products)} products")
        for path in written:
            print(path)
        return 0
    if args.command == "run":
        config = load_config(args.config)
        processor = BatchProcessor(config)
        result = processor.run()
        print(f"Arc solutions: {len(result.arc_solutions)}")
        print(f"Products: {len(result.products)}")
        print(f"Successful arcs: {sum(item.success for item in result.arc_solutions)}")
        if not args.no_write:
            for path in processor.write_outputs(result):
                print(path)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
