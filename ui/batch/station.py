"""Station records used by the multi-station console.

The existing GUI modules use a legacy, UI-friendly stream dictionary while the
core configuration uses ``GlobalConfig``/``ConnectionSettings``.  This module
keeps the conversion in one place so every station owns a complete, serializable
configuration and can be sent to an isolated worker process.
"""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from core.global_config import GlobalConfig


def _connection_to_legacy(settings: dict[str, Any] | None) -> dict[str, Any]:
    values = dict(settings or {})
    source = values.pop("source_type", values.pop("source", "NTRIP Server"))
    if source == "Serial Port":
        values["port"] = values.get("serial_port", values.get("port", ""))
    values["source"] = source
    return values


def _legacy_to_connection(settings: dict[str, Any] | None, *, enabled: bool) -> dict[str, Any]:
    values = dict(settings or {})
    source = values.pop("source", values.pop("source_type", "NTRIP Server"))
    values["source_type"] = source
    values["enabled"] = bool(values.get("enabled", enabled))
    return values


def default_station_config() -> dict[str, Any]:
    """Return an independent copy of the normal RTGS configuration defaults."""
    return GlobalConfig().to_dict()


def load_station_config(path: str | Path) -> dict[str, Any]:
    """Load and normalize a station YAML configuration without touching globals."""
    with Path(path).open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError("Station configuration must be a YAML mapping")
    config = GlobalConfig()
    config.from_dict(raw)
    return config.to_dict()


@dataclass
class StationRecord:
    """A station definition plus live status reported by its worker process."""

    name: str
    mode: str = "Monitoring"
    config: dict[str, Any] = field(default_factory=default_station_config)
    config_path: str = ""
    station_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    status: str = "Stopped"
    stream_status: str = "Idle"
    message_count: int = 0
    epoch_count: int = 0
    satellite_count: int = 0
    receiver: str = ""
    antenna: str = ""
    position: str = ""
    last_error: str = ""
    last_update: str = ""
    _runtime: Any = field(default=None, repr=False, compare=False)

    @classmethod
    def from_yaml(cls, path: str | Path, *, name: str | None = None, mode: str = "Monitoring"):
        path = Path(path)
        config = load_station_config(path)
        station_name = name or str(config.get("obs_settings", {}).get("mountpoint") or path.stem)
        return cls(station_name, mode=mode, config=config, config_path=str(path))

    @property
    def is_running(self) -> bool:
        return self._runtime is not None and self.status not in {"Stopped", "Error"}

    def legacy_settings(self) -> dict[str, Any]:
        """Return the dictionary expected by ``ConfigDialog`` and old workers."""
        return {
            "OBS": _connection_to_legacy(self.config.get("obs_settings")),
            "EPH_ENABLED": bool(self.config.get("eph_settings", {}).get("enabled", False)),
            "EPH": _connection_to_legacy(self.config.get("eph_settings")),
            "SSR_ENABLED": bool(self.config.get("ssr_settings", {}).get("enabled", False)),
            "SSR": _connection_to_legacy(self.config.get("ssr_settings")),
            "BASE_ENABLED": bool(self.config.get("base_settings", {}).get("enabled", False)),
            "BASE": _connection_to_legacy(self.config.get("base_settings")),
            "APPROX_REC_POS": copy.deepcopy(self.config.get("approx_rec_pos")),
            "TARGET_SYSTEMS": list(self.config.get("target_systems") or []),
        }

    def update_from_legacy(self, values: dict[str, Any]) -> None:
        """Apply a ConfigDialog result to this station only."""
        self.config["obs_settings"] = _legacy_to_connection(values.get("OBS"), enabled=True)
        self.config["eph_settings"] = _legacy_to_connection(
            values.get("EPH"), enabled=bool(values.get("EPH_ENABLED"))
        )
        self.config["ssr_settings"] = _legacy_to_connection(
            values.get("SSR"), enabled=bool(values.get("SSR_ENABLED"))
        )
        self.config["base_settings"] = _legacy_to_connection(
            values.get("BASE"), enabled=bool(values.get("BASE_ENABLED"))
        )
        self.config["approx_rec_pos"] = copy.deepcopy(values.get("APPROX_REC_POS"))
        self.config["target_systems"] = list(values.get("TARGET_SYSTEMS") or [])

    def payload(self) -> dict[str, Any]:
        """Return a deep-copy payload safe to pass to multiprocessing."""
        return copy.deepcopy(self.config)

    def summary(self) -> dict[str, Any]:
        obs = self.config.get("obs_settings", {})
        return {
            "id": self.station_id,
            "name": self.name,
            "mode": self.mode,
            "config_path": self.config_path,
            "mountpoint": obs.get("mountpoint", ""),
            "host": obs.get("host", ""),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "station_id": self.station_id,
            "name": self.name,
            "mode": self.mode,
            "config_path": self.config_path,
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> StationRecord:
        config = values.get("config") or default_station_config()
        return cls(
            name=str(values.get("name") or "Station"),
            mode=str(values.get("mode") or "Monitoring"),
            config=config,
            config_path=str(values.get("config_path") or ""),
            station_id=str(values.get("station_id") or uuid.uuid4().hex[:10]),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
