"""Thread-safe YAML config storage for the RT NTRIP RINEX service."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

import yaml

from .service import (
    MultiStationRTRinexConfig,
    RTStationConfig,
    load_rt_rinex_config,
)


DEFAULT_CONFIG: dict[str, Any] = {
    "defaults": {
        "enabled": True,
        "ntrip": {
            "port": 2101,
            "user_agent": "NTRIP RTGS RTRINEX/0.2",
            "connect_timeout_seconds": 15,
            "reconnect_delay_seconds": 5,
        },
        "rinex": {
            "output_directory": "./output/rt_rinex",
            "sample_interval_seconds": "auto",
            "split_enabled": True,
            "split_period_seconds": 3600,
            "daily_merge_min_interval_seconds": 15,
            "country_code": "CHN",
            "datatype": "MO",
            "receiver_type": "UNKNOWN",
            "antenna_type": "UNKNOWN",
            "antenna_model": "",
            "marker_number": "0",
            "time_system": "GPS",
            "auto_detect_obs_types": True,
            "align_tolerance_seconds": 0.001,
            "header_refresh_seconds": 60,
            "fsync_interval_seconds": 0,
        },
    },
    "stations": [],
}


class ConfigStore:
    """Owns reading and atomically writing the service YAML config."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self._lock = threading.RLock()
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write_raw_unlocked(copy.deepcopy(DEFAULT_CONFIG))

    def load_service_config(self) -> MultiStationRTRinexConfig:
        with self._lock:
            return load_rt_rinex_config(self.path)

    def load_raw(self) -> dict[str, Any]:
        with self._lock:
            with self.path.open("r", encoding="utf-8") as handle:
                raw = yaml.safe_load(handle) or {}
            if not isinstance(raw, dict):
                raise ValueError("Top-level config must be a YAML mapping")
            raw.setdefault("defaults", {})
            raw.setdefault("stations", [])
            if not isinstance(raw["stations"], list):
                raise ValueError("stations must be a list")
            return raw

    def save_raw(self, raw: dict[str, Any]) -> None:
        with self._lock:
            self._validate_raw(raw)
            self._write_raw_unlocked(raw)

    def get_mtime_ns(self) -> int:
        with self._lock:
            return self.path.stat().st_mtime_ns if self.path.exists() else 0

    def list_station_dicts(self) -> list[dict[str, Any]]:
        return list(self.load_raw().get("stations") or [])

    def upsert_station(self, station: dict[str, Any], *, original_name: str | None = None) -> dict[str, Any]:
        cleaned = self._normalize_station_payload(station)
        target_name = str(original_name or cleaned["name"]).strip()
        with self._lock:
            raw = self.load_raw()
            stations = raw.setdefault("stations", [])
            replaced = False
            for idx, existing in enumerate(stations):
                if str((existing or {}).get("name") or "").strip() == target_name:
                    stations[idx] = cleaned
                    replaced = True
                    break
            if not replaced:
                if any(str((item or {}).get("name") or "").strip() == cleaned["name"] for item in stations):
                    raise ValueError(f"Station already exists: {cleaned['name']}")
                stations.append(cleaned)
            self._write_raw_unlocked(raw)
        return cleaned

    def delete_station(self, name: str) -> bool:
        station_name = str(name or "").strip()
        if not station_name:
            raise ValueError("Station name is required")
        with self._lock:
            raw = self.load_raw()
            stations = raw.setdefault("stations", [])
            kept = [item for item in stations if str((item or {}).get("name") or "").strip() != station_name]
            removed = len(kept) != len(stations)
            if removed:
                raw["stations"] = kept
                self._write_raw_unlocked(raw)
            return removed

    def persist_obs_types(self, station_name: str, sys_obs_types: dict[str, list[str]]) -> None:
        normalized = self._normalize_sys_obs_types(sys_obs_types)
        if not normalized:
            return
        with self._lock:
            raw = self.load_raw()
            for station in raw.get("stations") or []:
                if str((station or {}).get("name") or "").strip() != station_name:
                    continue
                rinex = station.setdefault("rinex", {})
                rinex["sys_obs_types"] = normalized
                rinex["auto_detect_obs_types"] = False
                self._write_raw_unlocked(raw)
                return
            raise KeyError(f"Station not found: {station_name}")

    def persist_approx_position(self, station_name: str, approx_position: list[float]) -> None:
        normalized = self._normalize_position(approx_position)
        if normalized is None:
            return
        with self._lock:
            raw = self.load_raw()
            for station in raw.get("stations") or []:
                if str((station or {}).get("name") or "").strip() != station_name:
                    continue
                rinex = station.setdefault("rinex", {})
                existing = self._normalize_position(rinex.get("approx_position"))
                if existing is not None and all(abs(a - b) <= 0.0001 for a, b in zip(existing, normalized)):
                    return
                rinex["approx_position"] = normalized
                self._write_raw_unlocked(raw)
                return
            raise KeyError(f"Station not found: {station_name}")

    def config_fingerprint(self) -> str:
        raw = self.load_raw()
        return json.dumps(raw, sort_keys=True, ensure_ascii=True, default=str)

    @staticmethod
    def runtime_signature(station: RTStationConfig) -> str:
        payload = {
            "name": station.name,
            "enabled": station.enabled,
            "ntrip": {
                "host": station.ntrip.host,
                "port": station.ntrip.port,
                "mountpoint": station.ntrip.mountpoint,
                "user": station.ntrip.user,
                "password": station.ntrip.password,
                "user_agent": station.ntrip.user_agent,
                "connect_timeout_seconds": station.ntrip.connect_timeout_seconds,
                "reconnect_delay_seconds": station.ntrip.reconnect_delay_seconds,
            },
            "rinex": {
                "output_directory": str(station.rinex.output_directory),
                "marker_name": station.rinex.marker_name,
                "marker_number": station.rinex.marker_number,
                "station_code": station.rinex.station_code,
                "receiver_number": station.rinex.receiver_number,
                "country_code": station.rinex.country_code,
                "receiver_type": station.rinex.receiver_type,
                "antenna_type": station.rinex.antenna_type,
                "antenna_model": station.rinex.antenna_model,
                "antenna_number": station.rinex.antenna_number,
                "datatype": station.rinex.datatype,
                "filename_template": station.rinex.filename_template,
                "sample_interval_seconds": station.rinex.sample_interval_seconds,
                "split_enabled": station.rinex.split_enabled,
                "split_period_seconds": station.rinex.split_period_seconds,
                "daily_merge_min_interval_seconds": station.rinex.daily_merge_min_interval_seconds,
                "time_system": station.rinex.time_system,
                "align_tolerance_seconds": station.rinex.align_tolerance_seconds,
            },
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)

    def _write_raw_unlocked(self, raw: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(
            raw,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        finally:
            tmp_path = Path(tmp_name)
            if tmp_path.exists():
                tmp_path.unlink()

    @classmethod
    def _validate_raw(cls, raw: dict[str, Any]) -> None:
        if not isinstance(raw, dict):
            raise ValueError("Config must be a mapping")
        stations = raw.get("stations")
        if not isinstance(stations, list):
            raise ValueError("stations must be a list")
        seen: set[str] = set()
        for station in stations:
            cleaned = cls._normalize_station_payload(station)
            name = cleaned["name"]
            if name in seen:
                raise ValueError(f"Duplicate station name: {name}")
            seen.add(name)

    @classmethod
    def _normalize_station_payload(cls, station: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(station, dict):
            raise ValueError("Station must be a mapping")
        cleaned = copy.deepcopy(station)
        name = str(cleaned.get("name") or "").strip()
        if not name:
            raise ValueError("Station name is required")
        cleaned["name"] = name
        cleaned["enabled"] = bool(cleaned.get("enabled", True))

        ntrip = cleaned.setdefault("ntrip", {})
        rinex = cleaned.setdefault("rinex", {})
        if not isinstance(ntrip, dict):
            raise ValueError(f"Station {name}: ntrip must be a mapping")
        if not isinstance(rinex, dict):
            raise ValueError(f"Station {name}: rinex must be a mapping")
        if not str(ntrip.get("host") or "").strip():
            raise ValueError(f"Station {name}: ntrip.host is required")
        if not str(ntrip.get("mountpoint") or "").strip():
            raise ValueError(f"Station {name}: ntrip.mountpoint is required")

        ntrip["host"] = str(ntrip["host"]).strip()
        ntrip["mountpoint"] = str(ntrip["mountpoint"]).strip()
        ntrip["port"] = int(ntrip.get("port", 2101) or 2101)
        if "user" in ntrip:
            ntrip["user"] = str(ntrip.get("user") or "")
        if "password" in ntrip:
            ntrip["password"] = str(ntrip.get("password") or "")

        if "station_code" in rinex:
            rinex["station_code"] = str(rinex.get("station_code") or name[:4]).strip().upper()
        if "receiver_number" in rinex:
            rinex["receiver_number"] = str(rinex.get("receiver_number") or "00").strip().upper()
        rinex["time_system"] = "GPS"
        if "sys_obs_types" in rinex:
            rinex["sys_obs_types"] = cls._normalize_sys_obs_types(rinex.get("sys_obs_types"))
        if "approx_position" in rinex:
            normalized_position = cls._normalize_position(rinex.get("approx_position"))
            if normalized_position is not None:
                rinex["approx_position"] = normalized_position
        return cleaned

    @staticmethod
    def _normalize_sys_obs_types(raw: Any) -> dict[str, list[str]]:
        cleaned: dict[str, list[str]] = {}
        for system, codes in (raw or {}).items():
            key = str(system or "")[:1].upper()
            if not key:
                continue
            normalized_codes = []
            for code in codes or []:
                text = str(code or "").strip().upper()
                if text and text not in normalized_codes:
                    normalized_codes.append(text)
            if normalized_codes:
                cleaned[key] = normalized_codes
        return cleaned

    @staticmethod
    def _normalize_position(raw: Any) -> list[float] | None:
        if raw is None:
            return None
        if not isinstance(raw, (list, tuple)) or len(raw) < 3:
            return None
        try:
            return [float(raw[0]), float(raw[1]), float(raw[2])]
        except (TypeError, ValueError):
            return None
