"""Runtime manager for the standalone realtime EKF-GNSSIR service."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from threading import Event, RLock, Thread
import time
from typing import Any, Iterable
from uuid import uuid4

from ._vendor import install_aliases

install_aliases()

import yaml

from core.geo_utils import ecef2lla
from core.reflectometry.config import config_to_dict, load_config

from .config import AppConfig, AppConfigStore, StationConfig
from .station_worker import RealtimeEkfStationWorker


class RuntimeLogBuffer:
    """Small in-memory log ring buffer for the Web UI."""

    def __init__(self, max_lines: int = 2000):
        self.max_lines = max(1, int(max_lines))
        self._lines: deque[dict[str, str]] = deque(maxlen=self.max_lines)
        self._lock = RLock()

    def write(self, source: str, message: str | None = None) -> None:
        if message is None:
            message = source
            source = "system"
        row = {
            "time": datetime.now(timezone.utc).isoformat(),
            "source": str(source or "system"),
            "message": str(message),
        }
        with self._lock:
            self._lines.append(row)

    def lines(self, limit: int = 200, *, source: str = "") -> list[dict[str, str]]:
        with self._lock:
            rows = list(self._lines)
        if source:
            rows = [row for row in rows if row.get("source") == source]
        return rows[-max(1, int(limit)) :]

    def sources(self) -> list[str]:
        with self._lock:
            return sorted({row["source"] for row in self._lines})


class RealtimeEkfRuntimeManager:
    """Own the loaded config and all station worker lifecycles."""

    def __init__(
        self,
        store: AppConfigStore,
        *,
        station_names: Iterable[str] | None = None,
        poll_seconds: float | None = None,
        auto_start: bool = True,
    ) -> None:
        self.store = store
        self.station_filter = {str(name) for name in (station_names or []) if str(name)}
        self.poll_seconds = poll_seconds
        self.auto_start = bool(auto_start)
        self.logs = RuntimeLogBuffer()
        self._lock = RLock()
        self._stop_event = Event()
        self._monitor_thread: Thread | None = None
        self._started_at: datetime | None = None
        self._config: AppConfig | None = None
        self._config_mtime: float | None = None
        self._workers: dict[str, RealtimeEkfStationWorker] = {}

    def start(self) -> None:
        with self._lock:
            if self._monitor_thread is not None and self._monitor_thread.is_alive():
                return
            self._stop_event.clear()
            self._started_at = datetime.now(timezone.utc)
            self.reload_config(force=True)
            if self.auto_start:
                self._start_auto_workers_locked()
            self._monitor_thread = Thread(target=self._monitor_loop, name="RealtimeEkfGNSSIR-Monitor", daemon=True)
            self._monitor_thread.start()
            self.logs.write("system", "Runtime manager started")

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            worker.stop()
        for worker in workers:
            worker.join(timeout=5)
        with self._lock:
            self._workers.clear()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=2)
        self.logs.write("system", "Runtime manager stopped")

    def reload_config(self, *, force: bool = False) -> AppConfig:
        mtime = _safe_mtime(self.store.path)
        with self._lock:
            if not force and self._config is not None and mtime == self._config_mtime:
                return self._config
            config = self.store.load()
            self._config = config
            self._config_mtime = mtime
            self.logs.write("system", f"Config loaded: {self.store.path}")
            self._stop_removed_or_disabled_locked()
            return config

    def status(self) -> dict[str, Any]:
        with self._lock:
            config = self._config or self.store.load()
            configured = {station.name: station for station in self._filtered_stations(config.stations)}
            names = sorted(set(configured.keys()) | set(self._workers.keys()))
            stations = []
            for name in names:
                worker = self._workers.get(name)
                if worker is not None:
                    snapshot = worker.snapshot()
                else:
                    station = configured.get(name)
                    snapshot = self._station_idle_snapshot(station) if station is not None else {"name": name}
                stations.append(snapshot)
            return {
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "config_path": str(self.store.path),
                "storage_output_dir": str(config.storage.output_dir),
                "station_count": len(configured),
                "running_count": sum(1 for worker in self._workers.values() if worker.is_alive()),
                "stations": stations,
            }

    def stations_config(self) -> list[dict[str, Any]]:
        with self._lock:
            config = self._config or self.store.load()
            return [_station_config_to_dict(station) for station in self._filtered_stations(config.stations)]

    def start_station(self, name: str) -> dict[str, Any]:
        config = self.reload_config(force=True)
        with self._lock:
            station = self._find_station(config, name)
            if station is None:
                raise KeyError(f"Unknown station: {name}")
            if not station.enabled:
                raise ValueError(f"Station is disabled: {name}")
            existing = self._workers.get(station.name)
            if existing is not None and existing.is_alive():
                return existing.snapshot()
            if existing is not None:
                existing.stop()
                existing.join(timeout=5)
            worker = RealtimeEkfStationWorker(station, config.storage, log_fn=self.logs.write)
            self._workers[station.name] = worker
            worker.start()
            self.logs.write(station.name, "Start requested")
            return worker.snapshot()

    def stop_station(self, name: str) -> dict[str, Any]:
        with self._lock:
            worker = self._workers.get(name)
        if worker is None:
            return {"name": name, "state": "stopped", "alive": False}
        worker.stop()
        worker.join(timeout=5)
        snapshot = worker.snapshot()
        with self._lock:
            if not worker.is_alive():
                self._workers.pop(name, None)
        self.logs.write(name, "Stop requested")
        return snapshot

    def restart_station(self, name: str) -> dict[str, Any]:
        self.stop_station(name)
        return self.start_station(name)

    def products(
        self,
        name: str,
        limit: int | None = 200,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            worker = self._workers.get(name)
        rows = self._read_persisted_products(name)
        if worker is not None:
            memory_limit = max(1_000_000, int(limit or 0)) if limit is not None else 1_000_000
            rows = _merge_product_rows(rows, worker.products(memory_limit))
        rows = _filter_product_rows(rows, start=start, end=end)
        rows.sort(key=lambda item: _product_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc))
        if limit is not None:
            rows = rows[-max(1, int(limit)) :]
        return rows

    def reflectometry_config(self, name: str) -> dict[str, Any]:
        config = self.reload_config(force=True)
        station = self._find_station(config, name)
        if station is None:
            raise KeyError(f"Unknown station: {name}")
        path = station.reflectometry_config
        raw = _read_yaml(path)
        parsed = config_to_dict(load_config(path))
        return {
            "station": name,
            "path": str(path),
            "raw": raw,
            "parsed": parsed,
            "yaml_text": path.read_text(encoding="utf-8"),
        }

    def update_reflectometry_config(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload
        if isinstance(payload, dict) and "yaml_text" in payload:
            loaded = yaml.safe_load(str(payload.get("yaml_text") or "")) or {}
            if not isinstance(loaded, dict):
                raise ValueError("Reflectometry YAML root must be an object")
            raw = loaded
        elif isinstance(payload, dict) and "config" in payload:
            raw = payload["config"]
        if not isinstance(raw, dict):
            raise ValueError("Reflectometry config payload must be an object")
        config = self.reload_config(force=True)
        station = self._find_station(config, name)
        if station is None:
            raise KeyError(f"Unknown station: {name}")
        path = station.reflectometry_config
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(raw, handle, allow_unicode=True, sort_keys=False)
        load_config(path)
        worker = self._workers.get(name)
        if worker is not None and worker.is_alive():
            self.logs.write(name, "Reflectometry config saved; restart the station to apply changes")
        else:
            self.logs.write(name, "Reflectometry config saved")
        return self.reflectometry_config(name)

    def run_rinex_postprocess(
        self,
        name: str,
        *,
        observation_file: tuple[str, bytes],
        ephemeris_file: tuple[str, bytes] | None,
        ephemeris_file_type: str = "Auto Detect",
        use_rinex_position: bool = False,
    ) -> dict[str, Any]:
        config = self.reload_config(force=True)
        station = self._find_station(config, name)
        if station is None:
            raise KeyError(f"Unknown station: {name}")
        if not observation_file or not observation_file[1]:
            raise ValueError("RINEX observation file is required")
        if ephemeris_file is None or not ephemeris_file[1]:
            raise ValueError("RINEX/SP3 ephemeris file is required for GNSS-IR geometry")

        from core.rinex_loader import FileEphemerisProvider, RinexObservationReader, read_rinex_observation_header
        from core.reflectometry.outputs import ResultSerializer
        from core.reflectometry.providers import ListObservationProvider
        from core.reflectometry.rinex_batch import build_observation_records_from_epoch
        from core.reflectometry.services.batch import BatchProcessor

        job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        job_dir = config.storage.output_dir / station.name / "postprocess" / job_id
        upload_dir = job_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        obs_path = _write_upload(upload_dir, observation_file[0], observation_file[1], fallback="observation.rnx")
        eph_path = _write_upload(upload_dir, ephemeris_file[0], ephemeris_file[1], fallback="ephemeris.rnx")
        self.logs.write(name, f"RINEX postprocess started: {job_id}")

        runtime_config = deepcopy(load_config(station.reflectometry_config))
        runtime_config.logging.console = False
        runtime_config.logging.rotating_file = False
        runtime_config.output.output_dir = str(job_dir / "results")
        metadata = read_rinex_observation_header(obs_path)
        receiver_xyz = _receiver_xyz_from_config(runtime_config)
        used_rinex_position = False
        if receiver_xyz is not None:
            _apply_receiver_xyz(runtime_config, receiver_xyz)
        if use_rinex_position and metadata.has_nonzero_approx_position:
            receiver_xyz = [float(value) for value in metadata.approx_position_ecef or ()]
            _apply_receiver_xyz(runtime_config, receiver_xyz)
            used_rinex_position = True
        if receiver_xyz is None and metadata.has_nonzero_approx_position:
            receiver_xyz = [float(value) for value in metadata.approx_position_ecef or ()]
            _apply_receiver_xyz(runtime_config, receiver_xyz)
            used_rinex_position = True
        if receiver_xyz is None:
            raise ValueError("Receiver ECEF XYZ is required in station config or RINEX APPROX POSITION XYZ")

        ephemeris_provider = FileEphemerisProvider.from_file(eph_path, file_type=ephemeris_file_type)
        self.logs.write(name, f"Ephemeris loaded for postprocess: {ephemeris_provider.kind}")
        active_systems = set(_active_systems_for_reflectometry(runtime_config))
        reader = RinexObservationReader(obs_path)
        observations = []
        epoch_count = 0
        for epoch in reader.iter_epochs(
            ephemeris_provider=ephemeris_provider,
            receiver_position_ecef=receiver_xyz,
            target_systems=list(active_systems),
        ):
            epoch_count += 1
            observations.extend(
                build_observation_records_from_epoch(
                    epoch,
                    station_id=runtime_config.station.station_id,
                    receiver_position=runtime_config.station.receiver_position,
                    active_systems=active_systems,
                    input_config=runtime_config.input,
                )
            )

        if not observations:
            raise ValueError("No reflectometry observations were extracted from the uploaded RINEX files")

        self.logs.write(name, f"RINEX extracted {len(observations)} reflectometry observations from {epoch_count} epochs")
        processor = BatchProcessor(config=runtime_config, provider=ListObservationProvider(observations))
        result = processor.run()
        if not result.products:
            raise ValueError(
                f"RINEX parsed {epoch_count} epochs and {len(observations)} reflectometry observations, "
                "but no water-level products were generated. Check ephemeris time coverage, reflection-zone "
                "azimuth/elevation limits, SNR signals, and EKF initialization sample thresholds."
            )
        written = processor.write_outputs(result)
        result_dict = ResultSerializer.to_dict(result)
        payload = {
            "ok": True,
            "job_id": job_id,
            "station": name,
            "output_dir": str(job_dir),
            "observation_file": obs_path.name,
            "ephemeris_file": eph_path.name,
            "rinex_version": metadata.version,
            "rinex_time_system": metadata.time_system,
            "rinex_interval_seconds": metadata.interval_seconds,
            "used_rinex_position": used_rinex_position,
            "receiver_position_ecef": receiver_xyz,
            "epoch_count": epoch_count,
            "observation_count": len(observations),
            "product_count": len(result.products),
            "arc_solution_count": len(result.arc_solutions),
            "products": result_dict.get("products", []),
            "arc_solutions": result_dict.get("arc_solutions", [])[:250],
            "metadata": result_dict.get("metadata", {}),
            "written_files": [str(path) for path in written],
        }
        (job_dir / "job_summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        self.logs.write(name, f"RINEX postprocess completed: {job_id}, {len(result.products)} products")
        return payload

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                config = self.reload_config(force=False)
                if self.auto_start:
                    with self._lock:
                        self._start_auto_workers_locked(config)
            except Exception as exc:
                self.logs.write("system", f"Monitor error: {exc}")
            self._stop_event.wait(self._poll_seconds())

    def _poll_seconds(self) -> float:
        with self._lock:
            if self.poll_seconds is not None:
                return max(0.2, float(self.poll_seconds))
            if self._config is not None:
                return max(0.2, float(self._config.server.poll_seconds))
        return 1.0

    def _start_auto_workers_locked(self, config: AppConfig | None = None) -> None:
        config = config or self._config
        if config is None:
            return
        for station in self._filtered_stations(config.stations):
            if not station.enabled or not station.runtime.auto_start:
                continue
            worker = self._workers.get(station.name)
            if worker is not None and worker.is_alive():
                continue
            worker = RealtimeEkfStationWorker(station, config.storage, log_fn=self.logs.write)
            self._workers[station.name] = worker
            worker.start()
            self.logs.write(station.name, "Auto-started")

    def _stop_removed_or_disabled_locked(self) -> None:
        config = self._config
        if config is None:
            return
        allowed = {station.name for station in self._filtered_stations(config.stations) if station.enabled}
        for name, worker in list(self._workers.items()):
            if name in allowed:
                continue
            worker.stop()
            worker.join(timeout=5)
            self._workers.pop(name, None)
            self.logs.write(name, "Stopped because station was removed or disabled")

    def _find_station(self, config: AppConfig, name: str) -> StationConfig | None:
        for station in self._filtered_stations(config.stations):
            if station.name == name:
                return station
        return None

    def _filtered_stations(self, stations: Iterable[StationConfig]) -> list[StationConfig]:
        selected = list(stations)
        if self.station_filter:
            selected = [station for station in selected if station.name in self.station_filter]
        return selected

    def _station_idle_snapshot(self, station: StationConfig | None) -> dict[str, Any]:
        if station is None:
            return {"state": "unknown", "alive": False}
        return {
            "name": station.name,
            "enabled": station.enabled,
            "alive": False,
            "state": "idle",
            "host": station.obs_settings.host,
            "port": station.obs_settings.port,
            "mountpoint": station.obs_settings.mountpoint,
            "obs_settings": _stream_config_to_dict(station.obs_settings),
            "reflectometry_config": str(station.reflectometry_config),
            "last_error": "",
            "last_eph_error": "",
            "last_message_time": None,
            "last_eph_message_time": None,
            "last_epoch_time": None,
            "last_product_time": None,
            "bytes_received": 0,
            "messages_received": 0,
            "epochs_processed": 0,
            "observations_ingested": 0,
            "products_emitted": 0,
            "rh_initialized": False,
            "rh_initial_m": None,
            "rh_initial_arc_count": 0,
            "latest_product": None,
            "stream_health": {
                "label": "idle",
                "message_age_seconds": None,
                "epoch_age_seconds": None,
                "last_filter_warning": "",
            },
            "ephemeris_stream": {
                "enabled": bool(station.eph_settings.enabled),
                "state": "idle" if station.eph_settings.enabled else "disabled",
                "host": station.eph_settings.host,
                "port": station.eph_settings.port,
                "mountpoint": station.eph_settings.mountpoint,
                "settings": _stream_config_to_dict(station.eph_settings),
                "last_message_time": None,
                "last_error": "",
                "message_age_seconds": None,
            },
            "epoch_summary": {},
            "skyplot": [],
            "system_counts": {},
            "signal_counts": {},
            "record_samples": [],
            "initialization": {
                "mode": "ekf",
                "rh_initialized": False,
                "waiting_reason": "Station is idle",
                "progress": 0.0,
                "arcs": [],
            },
            "reflection_zones": _idle_reflection_zones(station.reflectometry_config),
        }

    def _read_persisted_products(self, name: str) -> list[dict[str, Any]]:
        with self._lock:
            config = self._config or self.store.load()
            path = config.storage.output_dir / name / "products.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        if isinstance(row, dict):
                            _normalize_product_arc_metadata(row)
                            rows.append(deepcopy(row))
                    except Exception:
                        continue
        except OSError:
            return []
        return rows


def _station_config_to_dict(station: StationConfig) -> dict[str, Any]:
    data = asdict(station)
    data["reflectometry_config"] = str(station.reflectometry_config)
    return data


def _stream_config_to_dict(stream: Any) -> dict[str, Any]:
    return dict(asdict(stream))


def _safe_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Reflectometry config root must be a mapping: {path}")
    return raw


def _idle_reflection_zones(path: Path) -> list[dict[str, Any]]:
    try:
        config = load_config(path)
    except Exception:
        return []
    zones = []
    for zone in getattr(config.geometry, "reflection_zones", []) or []:
        zones.append(
            {
                "name": zone.name,
                "min_elevation_deg": float(zone.min_elevation_deg),
                "max_elevation_deg": float(zone.max_elevation_deg),
                "azimuth_windows": [[float(item[0]), float(item[1])] for item in zone.azimuth_windows],
            }
        )
    return zones


def _merge_product_rows(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for rows in groups:
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            key = (
                str(row.get("product_type") or ""),
                str(row.get("timestamp") or ""),
                str(row.get("value", "")),
            )
            if key == ("", "", ""):
                continue
            merged[key] = deepcopy(row)
    return list(merged.values())


def _filter_product_rows(
    rows: list[dict[str, Any]],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    if start is None and end is None:
        return list(rows)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        timestamp = _product_timestamp(row)
        if timestamp is None:
            continue
        if start is not None and timestamp < start:
            continue
        if end is not None and timestamp > end:
            continue
        filtered.append(row)
    return filtered


def _product_timestamp(row: dict[str, Any]) -> datetime | None:
    value = row.get("timestamp")
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        timestamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _normalize_product_arc_metadata(row: dict[str, Any]) -> None:
    metadata = row.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        row["metadata"] = metadata
    if "active_satellite_arc_count" not in metadata:
        metadata["active_satellite_arc_count"] = metadata.get("active_arc_count", row.get("source_arc_count"))


def _sanitize_upload_filename(filename: str, fallback: str) -> str:
    text = str(filename or "").replace("\\", "/").split("/")[-1].strip()
    text = "".join(char if char.isalnum() or char in "._-+" else "_" for char in text)
    text = text.strip("._")
    return text or fallback


def _write_upload(directory: Path, filename: str, data: bytes, *, fallback: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _sanitize_upload_filename(filename, fallback)
    stem = path.stem or Path(fallback).stem
    suffix = path.suffix or Path(fallback).suffix
    counter = 1
    while path.exists():
        path = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    path.write_bytes(data)
    return path


def _receiver_xyz_from_config(config: Any) -> list[float] | None:
    position = getattr(getattr(config, "station", None), "receiver_position", None)
    if position is None:
        return None
    xyz = [getattr(position, "x_m", None), getattr(position, "y_m", None), getattr(position, "z_m", None)]
    if any(value is None for value in xyz):
        return None
    return [float(value) for value in xyz]


def _apply_receiver_xyz(config: Any, xyz: list[float]) -> None:
    position = config.station.receiver_position
    position.x_m = float(xyz[0])
    position.y_m = float(xyz[1])
    position.z_m = float(xyz[2])
    latitude_rad, longitude_rad, height_m = ecef2lla([position.x_m, position.y_m, position.z_m])
    position.latitude_deg = math.degrees(float(latitude_rad))
    position.longitude_deg = math.degrees(float(longitude_rad))
    position.height_m = float(height_m)


def _active_systems_for_reflectometry(config: Any) -> list[str]:
    systems = []
    for item in getattr(getattr(config, "input", None), "constellations", []) or []:
        text = str(item).strip().upper()
        if text:
            systems.append(text[0])
    return systems or ["G", "R", "E", "C", "J", "S", "I"]


__all__ = ["RealtimeEkfRuntimeManager", "RuntimeLogBuffer"]
