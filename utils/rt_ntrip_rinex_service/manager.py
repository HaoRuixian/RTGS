"""Runtime manager with config polling and daily merge scheduling."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import re
import threading
import time
from typing import Iterable

from .config_store import ConfigStore
from .merge_rinex_daily import merge_rinex_daily_files
from .service import (
    RTNtripRinexStation,
    RTStationConfig,
    _convert_utc_to_time_system,
    _normalize_station_folder_name,
)


class LogBuffer:
    def __init__(self, max_lines: int = 1000):
        self._records: deque[tuple[str, str]] = deque(maxlen=max(1, int(max_lines)))
        self._lock = threading.Lock()

    def write(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        source = self._infer_source(message)
        with self._lock:
            self._records.append((source, line))
        print(line, flush=True)

    def lines(self, limit: int = 200, source: str | None = None) -> list[str]:
        with self._lock:
            data = list(self._records)
        source_text = str(source or "").strip()
        if source_text and source_text.lower() != "all":
            data = [(item_source, line) for item_source, line in data if item_source == source_text]
        return [line for _item_source, line in data[-max(1, int(limit)) :]]

    def sources(self) -> list[str]:
        with self._lock:
            return sorted({source for source, _line in self._records if source})

    @staticmethod
    def _infer_source(message: str) -> str:
        match = re.match(r"^\[([^\]]+)\]", str(message or "").strip())
        if match:
            return match.group(1).strip()
        return "service"


class RuntimeManager:
    """Keeps workers in sync with YAML config and retries daily merges."""

    def __init__(
        self,
        store: ConfigStore,
        *,
        poll_seconds: int = 60,
        merge_poll_seconds: int = 300,
        station_names: Iterable[str] | None = None,
        log_buffer: LogBuffer | None = None,
    ):
        self.store = store
        self.poll_seconds = max(5, int(poll_seconds))
        self.merge_poll_seconds = max(30, int(merge_poll_seconds))
        self.station_names = {str(name).strip() for name in (station_names or []) if str(name).strip()}
        self.logs = log_buffer or LogBuffer()
        self._workers: dict[str, RTNtripRinexStation] = {}
        self._signatures: dict[str, str] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._reload_event = threading.Event()
        self._merge_event = threading.Event()
        self._reload_thread: threading.Thread | None = None
        self._merge_thread: threading.Thread | None = None
        self._last_config_mtime_ns = 0
        self._started = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self.reload_config(force=True)
        self._reload_thread = threading.Thread(target=self._reload_loop, name="RTRinexConfigPoller", daemon=True)
        self._merge_thread = threading.Thread(target=self._merge_loop, name="RTRinexDailyMerger", daemon=True)
        self._reload_thread.start()
        self._merge_thread.start()
        self.logs.write(f"Manager started; config is polled every {self.poll_seconds}s")

    def stop(self) -> None:
        self._stop_event.set()
        self._reload_event.set()
        self._merge_event.set()
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
            self._signatures.clear()
        for worker in workers:
            worker.stop()
        for worker in workers:
            worker.join(timeout=10.0)
        for thread in (self._reload_thread, self._merge_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=5.0)
        self.logs.write("Manager stopped")

    def trigger_reload(self) -> None:
        self._reload_event.set()

    def trigger_merge(self) -> None:
        self._merge_event.set()

    def reload_config(self, *, force: bool = False) -> None:
        try:
            current_mtime = self.store.get_mtime_ns()
            if not force and current_mtime == self._last_config_mtime_ns:
                return
            config = self.store.load_service_config()
            self._reconcile(config.stations)
            self._last_config_mtime_ns = self.store.get_mtime_ns()
        except Exception as exc:
            self.logs.write(f"Config reload failed: {exc}")

    def status(self) -> dict:
        with self._lock:
            workers = list(self._workers.values())
        return {
            "started": self._started and not self._stop_event.is_set(),
            "config_path": str(self.store.path),
            "poll_seconds": self.poll_seconds,
            "merge_poll_seconds": self.merge_poll_seconds,
            "stations": [worker.snapshot() for worker in workers],
        }

    def run_due_merges(self) -> list[dict]:
        results: list[dict] = []
        try:
            config = self.store.load_service_config()
        except Exception as exc:
            self.logs.write(f"Daily merge config load failed: {exc}")
            return [{"ok": False, "error": str(exc)}]

        for station in config.stations:
            if self.station_names and station.name not in self.station_names:
                continue
            if not station.enabled:
                continue
            results.extend(self._run_station_due_merges(station))
        return results

    def _reconcile(self, stations: list[RTStationConfig]) -> None:
        desired: dict[str, RTStationConfig] = {}
        for station in stations:
            if not station.enabled:
                continue
            if self.station_names and station.name not in self.station_names:
                continue
            desired[station.name] = station

        with self._lock:
            existing_names = set(self._workers)
            desired_names = set(desired)

            for name in sorted(existing_names - desired_names):
                self._stop_worker_locked(name, "removed or disabled")

            for name in sorted(desired_names):
                station = desired[name]
                signature = self.store.runtime_signature(station)
                worker = self._workers.get(name)
                if worker is None:
                    self._start_worker_locked(station, signature)
                    continue
                if self._signatures.get(name) != signature:
                    self._stop_worker_locked(name, "runtime config changed")
                    self._start_worker_locked(station, signature)
                    continue
                worker.update_runtime_config(station)

    def _start_worker_locked(self, station: RTStationConfig, signature: str) -> None:
        worker = RTNtripRinexStation(
            station,
            log_fn=self.logs.write,
            obs_types_persist_fn=self.store.persist_obs_types,
            approx_position_persist_fn=self.store.persist_approx_position,
        )
        self._workers[station.name] = worker
        self._signatures[station.name] = signature
        worker.start()
        self.logs.write(f"[{station.name}] Worker started")

    def _stop_worker_locked(self, name: str, reason: str) -> None:
        worker = self._workers.pop(name, None)
        self._signatures.pop(name, None)
        if worker is None:
            return
        self.logs.write(f"[{name}] Stopping worker: {reason}")
        worker.stop()
        worker.join(timeout=10.0)

    def _reload_loop(self) -> None:
        while not self._stop_event.is_set():
            self._reload_event.wait(timeout=self.poll_seconds)
            self._reload_event.clear()
            if self._stop_event.is_set():
                break
            self.reload_config()

    def _merge_loop(self) -> None:
        while not self._stop_event.is_set():
            self._merge_event.wait(timeout=self.merge_poll_seconds)
            self._merge_event.clear()
            if self._stop_event.is_set():
                break
            self.run_due_merges()

    def _run_station_due_merges(self, station: RTStationConfig) -> list[dict]:
        rinex_cfg = station.rinex
        if not (
            rinex_cfg.split_enabled
            and rinex_cfg.split_period_seconds is not None
            and int(rinex_cfg.split_period_seconds) < 86400
        ):
            return []

        station_folder = _normalize_station_folder_name(rinex_cfg.station_code, rinex_cfg.receiver_number)
        station_root = rinex_cfg.output_directory / station_folder
        if not station_root.exists():
            return []

        results: list[dict] = []
        for year_dir in sorted(path for path in station_root.iterdir() if path.is_dir() and path.name.isdigit()):
            for day_dir in sorted(path for path in year_dir.iterdir() if path.is_dir() and path.name.isdigit()):
                result = self._merge_day_if_due(station, day_dir)
                if result is not None:
                    results.append(result)
        return results

    def _merge_day_if_due(self, station: RTStationConfig, day_dir: Path) -> dict | None:
        rinex_cfg = station.rinex
        source_files = sorted(path for path in day_dir.iterdir() if path.is_file() and path.suffix.lower() == ".rnx")
        if not source_files:
            return None

        day_start = self._parse_day_directory(day_dir)
        if day_start is None:
            return None

        current_rinex_time = _convert_utc_to_time_system(datetime.now(timezone.utc), rinex_cfg.time_system)
        current_day_start = current_rinex_time.replace(hour=0, minute=0, second=0, microsecond=0)
        expected_count = max(1, (86400 + int(rinex_cfg.split_period_seconds) - 1) // int(rinex_cfg.split_period_seconds))
        complete_by_time = day_start < current_day_start
        complete_by_count = len(source_files) >= expected_count
        if not (complete_by_time or complete_by_count):
            return None

        output_dir = day_dir.parent
        if self._daily_output_is_fresh(output_dir, source_files, day_start, rinex_cfg.datatype):
            return None

        try:
            result = merge_rinex_daily_files(
                [day_dir],
                output_dir,
                marker_name=rinex_cfg.marker_name,
                receiver_type=rinex_cfg.receiver_type,
                station_code=rinex_cfg.station_code,
                receiver_number=rinex_cfg.receiver_number,
                country_code=rinex_cfg.country_code,
                antenna_type=rinex_cfg.antenna_type,
                antenna_number=str(rinex_cfg.antenna_model or rinex_cfg.antenna_number or "").strip(),
                datatype=rinex_cfg.datatype,
                output_interval_seconds=float(max(15, int(rinex_cfg.daily_merge_min_interval_seconds))),
                time_system=rinex_cfg.time_system,
            )
        except Exception as exc:
            self.logs.write(f"[{station.name}] Daily merge failed for {day_dir.name}: {exc}")
            return {"station": station.name, "day": day_dir.name, "ok": False, "error": str(exc)}

        output_files = [str(path) for path in result.output_files]
        if output_files:
            self.logs.write(
                f"[{station.name}] Daily merge wrote {Path(output_files[0]).name} from {len(result.source_files)} split file(s)"
            )
        else:
            self.logs.write(f"[{station.name}] Daily merge produced no output for {day_dir.name}")
        return {
            "station": station.name,
            "day": f"{day_dir.parent.name}/{day_dir.name}",
            "ok": bool(output_files),
            "source_count": len(result.source_files),
            "outputs": output_files,
        }

    @staticmethod
    def _parse_day_directory(day_dir: Path) -> datetime | None:
        year = day_dir.parent.name
        doy = day_dir.name
        try:
            if len(year) == 4 and len(doy) == 3 and year.isdigit() and doy.isdigit():
                return datetime.strptime(f"{year}{doy}", "%Y%j")
            if len(doy) == 7 and doy.isdigit():
                return datetime.strptime(doy, "%Y%j")
        except ValueError:
            return None
        return None

    @staticmethod
    def _daily_output_is_fresh(output_dir: Path, source_files: list[Path], day_start: datetime, datatype: str) -> bool:
        pattern = f"*_R_{day_start.strftime('%Y%j')}0000_01D_*_{datatype}.rnx"
        candidates = sorted(output_dir.glob(pattern))
        if not candidates:
            return False
        newest_source_mtime = max(path.stat().st_mtime for path in source_files)
        return any(candidate.stat().st_mtime >= newest_source_mtime for candidate in candidates)
