"""Verify that an RTGS wheel is complete and contains no credential-bearing YAML."""

from __future__ import annotations

import argparse
import configparser
import io
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

REQUIRED_PACKAGE_PREFIXES = ("core/", "rtgs/", "ui/", "utils/")
REQUIRED_MODULES = ("gui_main.py", "main.py", "rtcm_batch_gui.py")
REQUIRED_RESOURCE_PATHS = (
    "utils/realtime_ekf_gnssir/static/app.js",
    "utils/realtime_ekf_gnssir/static/index.html",
    "utils/realtime_ekf_gnssir/static/styles.css",
    "utils/rt_ntrip_rinex_service/static/app.css",
    "utils/rt_ntrip_rinex_service/static/app.js",
    "utils/rt_ntrip_rinex_service/static/index.html",
)
REQUIRED_GUI_SCRIPTS = {
    "rtgs": "gui_main:main",
    "rtgs-rtcm-batch": "ui.rtcm_batch_converter:main",
}
SENSITIVE_KEYS = {"api_key", "password", "secret", "token", "user", "username"}
SAFE_CREDENTIAL_VALUES = {
    "",
    "<password>",
    "<redacted>",
    "<user>",
    "change_me",
    "your_password",
    "your_user",
    "your_username",
}


class WheelVerificationError(ValueError):
    """Raised when a wheel violates the RTGS release contract."""


@dataclass(frozen=True, slots=True)
class WheelVerificationReport:
    """Summary of a successfully verified wheel."""

    path: Path
    file_count: int
    python_file_count: int
    yaml_file_count: int


def verify_wheel(path: str | Path) -> WheelVerificationReport:
    """Validate package contents, entry points, and YAML credential safety."""
    wheel_path = Path(path)
    if wheel_path.suffix != ".whl" or not wheel_path.is_file():
        raise WheelVerificationError(f"Wheel does not exist: {wheel_path}")

    issues: list[str] = []
    with zipfile.ZipFile(wheel_path) as archive:
        names = set(archive.namelist())
        for prefix in REQUIRED_PACKAGE_PREFIXES:
            if not any(name.startswith(prefix) and name.endswith(".py") for name in names):
                issues.append(f"missing Python package prefix: {prefix}")
        for module_name in REQUIRED_MODULES:
            if module_name not in names:
                issues.append(f"missing compatibility module: {module_name}")
        for resource_path in REQUIRED_RESOURCE_PATHS:
            if resource_path not in names:
                issues.append(f"missing package resource: {resource_path}")

        forbidden = sorted(
            name
            for name in names
            if name.startswith("ui/legacy/") or name.endswith((".pyc", ".pyo"))
        )
        if forbidden:
            issues.append(f"forbidden archived/bytecode files: {', '.join(forbidden[:5])}")

        entry_points_name = next(
            (name for name in names if name.endswith(".dist-info/entry_points.txt")),
            None,
        )
        if entry_points_name is None:
            issues.append("missing wheel entry_points.txt")
        else:
            issues.extend(_entry_point_issues(archive.read(entry_points_name)))

        yaml_names = sorted(
            name for name in names if PurePosixPath(name).suffix.lower() in {".yaml", ".yml"}
        )
        for yaml_name in yaml_names:
            issues.extend(_yaml_credential_issues(yaml_name, archive.read(yaml_name)))

    if issues:
        raise WheelVerificationError("; ".join(issues))
    return WheelVerificationReport(
        path=wheel_path,
        file_count=len(names),
        python_file_count=sum(name.endswith(".py") for name in names),
        yaml_file_count=len(yaml_names),
    )


def _entry_point_issues(payload: bytes) -> list[str]:
    parser = configparser.ConfigParser()
    parser.read_file(io.StringIO(payload.decode("utf-8")))
    scripts: Mapping[str, str] = parser["gui_scripts"] if parser.has_section("gui_scripts") else {}
    return [
        f"invalid GUI entry point {name!r}: expected {expected!r}"
        for name, expected in REQUIRED_GUI_SCRIPTS.items()
        if scripts.get(name) != expected
    ]


def _yaml_credential_issues(name: str, payload: bytes) -> list[str]:
    try:
        document = yaml.safe_load(payload.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        return [f"invalid YAML resource {name}: {exc}"]

    unsafe_paths: list[str] = []
    _collect_unsafe_credentials(document, path=name, output=unsafe_paths)
    return [f"credential-bearing YAML field: {path}" for path in unsafe_paths]


def _collect_unsafe_credentials(value: Any, *, path: str, output: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in SENSITIVE_KEYS and not _is_safe_credential_value(child):
                output.append(child_path)
            _collect_unsafe_credentials(child, path=child_path, output=output)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _collect_unsafe_credentials(child, path=f"{path}[{index}]", output=output)


def _is_safe_credential_value(value: Any) -> bool:
    if value is None:
        return True
    normalized = str(value).strip().lower()
    return normalized in SAFE_CREDENTIAL_VALUES or (
        normalized.startswith("${") and normalized.endswith("}")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path, help="Wheel file to verify")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = verify_wheel(args.wheel)
    except WheelVerificationError as exc:
        print(f"wheel verification failed: {exc}")
        return 1
    print(
        f"wheel verification passed: {report.file_count} files, "
        f"{report.python_file_count} Python files, {report.yaml_file_count} YAML files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
