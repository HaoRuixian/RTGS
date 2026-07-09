"""Configuration loading and persistence for realtime EKF-GNSSIR."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

import yaml


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
REFLECTOMETRY_CONFIG_WRITE_LOCK = RLock()


@dataclass(slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8090
    poll_seconds: float = 1.0


@dataclass(slots=True)
class StorageConfig:
    output_dir: Path
    write_jsonl: bool = True
    write_csv: bool = True


@dataclass(slots=True)
class StreamConfig:
    source_type: str = "NTRIP Server"
    enabled: bool = True
    host: str = ""
    port: int = 2101
    mountpoint: str = ""
    user: str = ""
    password: str = ""
    serial_port: str = "COM1"
    baudrate: int = 115200
    databits: int = 8
    stopbits: float = 1.0
    parity: str = "None"
    flowctrl: str = "None"
    file_path: str = ""
    replay_speed: float = 1.0
    file_type: str = "Auto Detect"
    final_results_only: bool = False
    user_agent: str = "NTRIP RTGS EKF-GNSSIR/0.1"
    connect_timeout_seconds: float = 15.0
    reconnect_delay_seconds: float = 5.0


NtripConfig = StreamConfig


@dataclass(slots=True)
class StationRuntimeConfig:
    auto_start: bool = False
    max_product_history: int = 1000


@dataclass(slots=True)
class StationConfig:
    name: str
    enabled: bool
    reflectometry_config: Path
    obs_settings: StreamConfig
    eph_settings: StreamConfig
    runtime: StationRuntimeConfig


@dataclass(slots=True)
class AppConfig:
    config_path: Path
    server: ServerConfig
    storage: StorageConfig
    stations: list[StationConfig]


class AppConfigStore:
    """Thread-safe YAML config store used by the service and Web API."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self._lock = RLock()

    def load_raw(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                raise FileNotFoundError(f"Config file not found: {self.path}")
            with self.path.open("r", encoding="utf-8") as handle:
                raw = yaml.safe_load(handle) or {}
            if not isinstance(raw, dict):
                raise ValueError("Config root must be a mapping")
            return raw

    def save_raw(self, raw: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(raw, handle, allow_unicode=True, sort_keys=False)

    def load(self) -> AppConfig:
        raw = self.load_raw()
        return parse_app_config(raw, self.path)

    def list_station_dicts(self) -> list[dict[str, Any]]:
        raw = self.load_raw()
        stations = raw.get("stations") or []
        if not isinstance(stations, list):
            return []
        return [deepcopy(item) for item in stations if isinstance(item, dict)]

    def upsert_station(self, payload: dict[str, Any], *, original_name: str | None = None) -> dict[str, Any]:
        station = sanitize_station_payload(payload)
        raw = self.load_raw()
        stations = raw.get("stations")
        if not isinstance(stations, list):
            stations = []
            raw["stations"] = stations

        target_name = (original_name or station["name"]).strip()
        new_name = station["name"].strip()
        if original_name and new_name != target_name:
            for item in stations:
                if not isinstance(item, dict):
                    continue
                item_name = str(item.get("name", "")).strip()
                if item_name == new_name and item_name != target_name:
                    raise ValueError(f"Station already exists: {new_name}")
        replaced = False
        for index, item in enumerate(stations):
            if isinstance(item, dict) and str(item.get("name", "")).strip() == target_name:
                stations[index] = station
                replaced = True
                break
        if not replaced:
            stations.append(station)
        self.save_raw(raw)
        return station

    def create_station(self, payload: dict[str, Any]) -> dict[str, Any]:
        station = sanitize_station_payload(payload)
        raw = self.load_raw()
        stations = raw.get("stations")
        if not isinstance(stations, list):
            stations = []
            raw["stations"] = stations

        name = station["name"].strip()
        for item in stations:
            if isinstance(item, dict) and str(item.get("name", "")).strip() == name:
                raise ValueError(f"Station already exists: {name}")
        stations.append(station)
        self.save_raw(raw)
        return station

    def delete_station(self, name: str) -> bool:
        raw = self.load_raw()
        stations = raw.get("stations")
        if not isinstance(stations, list):
            return False
        before = len(stations)
        raw["stations"] = [
            item for item in stations if not (isinstance(item, dict) and str(item.get("name", "")).strip() == name)
        ]
        removed = len(raw["stations"]) != before
        if removed:
            self.save_raw(raw)
        return removed


def parse_app_config(raw: dict[str, Any], config_path: str | Path) -> AppConfig:
    config_path = Path(config_path).resolve()
    base_dir = config_path.parent

    server_raw = raw.get("server") or {}
    storage_raw = raw.get("storage") or {}
    defaults_raw = _normalize_station_aliases(raw.get("defaults") or {})
    stations_raw = raw.get("stations") or []

    if not isinstance(stations_raw, list):
        raise ValueError("stations must be a list")

    stations: list[StationConfig] = []
    for station_raw in stations_raw:
        if not isinstance(station_raw, dict):
            continue
        merged = _deep_merge(defaults_raw, _normalize_station_aliases(station_raw))
        stations.append(_parse_station(merged, base_dir=base_dir))

    return AppConfig(
        config_path=config_path,
        server=ServerConfig(
            host=str(server_raw.get("host", "127.0.0.1") or "127.0.0.1"),
            port=int(server_raw.get("port", 8090) or 8090),
            poll_seconds=float(server_raw.get("poll_seconds", 1.0) or 1.0),
        ),
        storage=StorageConfig(
            output_dir=_resolve_path(storage_raw.get("output_dir", "../output/realtime_ekf_gnssir"), base_dir),
            write_jsonl=bool(storage_raw.get("write_jsonl", True)),
            write_csv=bool(storage_raw.get("write_csv", True)),
        ),
        stations=stations,
    )


def sanitize_station_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Station payload must be an object")
    payload = _normalize_station_aliases(payload)
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("Station name is required")

    obs_settings = _sanitize_stream_payload(payload.get("obs_settings"), default_enabled=True)
    eph_settings = _sanitize_stream_payload(payload.get("eph_settings"), default_enabled=False)
    runtime = payload.get("runtime") or {}
    station = {
        "name": name,
        "enabled": bool(payload.get("enabled", True)),
        "reflectometry_config": str(payload.get("reflectometry_config", "")).strip(),
        "obs_settings": obs_settings,
        "eph_settings": eph_settings,
        "runtime": {
            "auto_start": bool(runtime.get("auto_start", False)),
            "max_product_history": int(runtime.get("max_product_history", 1000) or 1000),
        },
    }
    if not station["reflectometry_config"]:
        raise ValueError("reflectometry_config is required")
    return station


def _parse_station(raw: dict[str, Any], *, base_dir: Path) -> StationConfig:
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ValueError("stations[].name is required")
    obs_raw = raw.get("obs_settings") or {}
    eph_raw = raw.get("eph_settings") or {}
    runtime_raw = raw.get("runtime") or {}
    return StationConfig(
        name=name,
        enabled=bool(raw.get("enabled", True)),
        reflectometry_config=_resolve_path(raw.get("reflectometry_config", ""), base_dir),
        obs_settings=_parse_stream(obs_raw, default_enabled=True),
        eph_settings=_parse_stream(eph_raw, default_enabled=False),
        runtime=StationRuntimeConfig(
            auto_start=bool(runtime_raw.get("auto_start", False)),
            max_product_history=int(runtime_raw.get("max_product_history", 1000) or 1000),
        ),
    )


def _normalize_station_aliases(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(raw or {})
    if not isinstance(normalized, dict):
        return {}
    if "obs_settings" not in normalized and isinstance(normalized.get("ntrip"), dict):
        normalized["obs_settings"] = deepcopy(normalized["ntrip"])
    if "eph_settings" not in normalized:
        if isinstance(normalized.get("ephemeris_ntrip"), dict):
            normalized["eph_settings"] = deepcopy(normalized["ephemeris_ntrip"])
        elif isinstance(normalized.get("eph_ntrip"), dict):
            normalized["eph_settings"] = deepcopy(normalized["eph_ntrip"])
    return normalized


def _sanitize_stream_payload(raw: Any, *, default_enabled: bool) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    source_type = str(raw.get("source_type", raw.get("source", "NTRIP Server")) or "NTRIP Server").strip()
    return {
        "source_type": source_type,
        "enabled": bool(raw.get("enabled", default_enabled)),
        "host": str(raw.get("host", "") or "").strip(),
        "port": _parse_int(raw.get("port", 2101), 2101),
        "mountpoint": str(raw.get("mountpoint", "") or "").strip(),
        "user": str(raw.get("user", "") or ""),
        "password": str(raw.get("password", "") or ""),
        "serial_port": str(raw.get("serial_port", "COM1") or "COM1"),
        "baudrate": _parse_int(raw.get("baudrate", 115200), 115200),
        "databits": _parse_int(raw.get("databits", 8), 8),
        "stopbits": _parse_float(raw.get("stopbits", 1.0), 1.0),
        "parity": str(raw.get("parity", "None") or "None"),
        "flowctrl": str(raw.get("flowctrl", "None") or "None"),
        "file_path": str(raw.get("file_path", "") or ""),
        "replay_speed": _parse_float(raw.get("replay_speed", 1.0), 1.0),
        "file_type": str(raw.get("file_type", "Auto Detect") or "Auto Detect"),
        "final_results_only": bool(raw.get("final_results_only", False)),
        "user_agent": _normalize_user_agent(raw.get("user_agent", "NTRIP RTGS EKF-GNSSIR/0.1")),
        "connect_timeout_seconds": _parse_float(raw.get("connect_timeout_seconds", 15.0), 15.0),
        "reconnect_delay_seconds": _parse_float(raw.get("reconnect_delay_seconds", 5.0), 5.0),
    }


def _parse_stream(raw: Any, *, default_enabled: bool) -> StreamConfig:
    sanitized = _sanitize_stream_payload(raw, default_enabled=default_enabled)
    return StreamConfig(**sanitized)


def _resolve_path(value: Any, base_dir: Path) -> Path:
    text = str(value or "").strip()
    if not text:
        return Path()
    path = Path(text)
    if path.is_absolute():
        return path
    candidates = [
        (base_dir / path).resolve(),
        (PROJECT_ROOT / path).resolve(),
        Path.cwd().joinpath(path).resolve(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _normalize_user_agent(value: Any) -> str:
    text = str(value or "").strip() or "NTRIP RTGS EKF-GNSSIR/0.1"
    if text.upper().startswith("NTRIP"):
        return text
    return f"NTRIP {text}"


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _parse_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base or {})
    for key, value in (overrides or {}).items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = deepcopy(value)
    return result


__all__ = [
    "AppConfig",
    "AppConfigStore",
    "NtripConfig",
    "ServerConfig",
    "StationConfig",
    "StationRuntimeConfig",
    "StorageConfig",
    "StreamConfig",
    "parse_app_config",
    "sanitize_station_payload",
]
