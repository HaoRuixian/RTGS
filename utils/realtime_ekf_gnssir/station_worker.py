"""Realtime NTRIP worker feeding decoded epochs into EKF-GNSSIR."""

from __future__ import annotations

import csv
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Event, Lock, RLock, Thread
import time
from typing import Any, Callable, Iterable

from ._vendor import install_aliases

install_aliases()

from ._vendor.rt_ntrip_rinex_service.data_models import EpochObservation
from ._vendor.rt_ntrip_rinex_service.global_config import update_general_settings
from ._vendor.rt_ntrip_rinex_service.rtcm_handler import RTCMHandler
from ._vendor.rt_ntrip_rinex_service.service import (
    NtripSourceConfig,
    RTNtripRinexStation,
    _create_default_reader,
    _epoch_key_millis,
    _merge_epoch_data,
)

from core.reflectometry.config import ReflectorConfig, load_config
from core.reflectometry.models import ProcessingRunResult, ProductResult
from core.reflectometry.outputs import ResultSerializer
from core.reflectometry.rinex_batch import build_observation_records_from_epoch
from core.reflectometry.services.geometry import matches_reflection_zones
from core.reflectometry.services.realtime import RealtimeProcessor

from .config import StationConfig, StorageConfig, StreamConfig


_RTCM_GLOBAL_CONFIG_LOCK = Lock()


class ProductHistory:
    """Bounded in-memory product history."""

    def __init__(self, max_items: int = 1000):
        self.max_items = max(1, int(max_items))
        self._items: list[dict[str, Any]] = []
        self._lock = RLock()

    def append_many(self, products: Iterable[ProductResult]) -> list[dict[str, Any]]:
        rows = [_product_to_dict(product) for product in products]
        if not rows:
            return []
        with self._lock:
            self._items.extend(rows)
            if len(self._items) > self.max_items:
                self._items = self._items[-self.max_items :]
        return rows

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._items[-1]) if self._items else None

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._items[-max(1, int(limit)) :]]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class RealtimeEkfStationWorker(Thread):
    """Single-station realtime EKF-GNSSIR worker."""

    def __init__(
        self,
        station: StationConfig,
        storage: StorageConfig,
        *,
        log_fn: Callable[[str, str], None] | None = None,
        reader_factory: Callable[[object], Iterable[tuple[bytes | None, object]]] | None = None,
        stream_connector: Callable[[NtripSourceConfig], object] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(name=f"RealtimeEkfGNSSIR-{station.name}", daemon=True)
        self.station = station
        self.storage = storage
        self.log_fn = log_fn or (lambda _source, message: print(message, flush=True))
        self.reader_factory = reader_factory or _create_default_reader
        self.stream_connector = stream_connector or RTNtripRinexStation._connect_ntrip_stream
        self.sleep_fn = sleep_fn
        self.stop_event = Event()
        self.status_lock = RLock()
        self.history = ProductHistory(station.runtime.max_product_history)

        self._stream = None
        self._handler: RTCMHandler | None = None
        self._eph_handler: RTCMHandler | None = None
        self._reflector_config: ReflectorConfig | None = None
        self._processor: RealtimeProcessor | None = None
        self._current_epoch: EpochObservation | None = None
        self._current_epoch_key: int | None = None
        self._known_product_keys: set[tuple[str, str, str]] = set()
        self._eph_thread: Thread | None = None
        self._eph_stream = None

        self._state = "created"
        self._eph_state = "disabled"
        self._last_error = ""
        self._last_eph_error = ""
        self._last_message_time: datetime | None = None
        self._last_eph_message_time: datetime | None = None
        self._last_epoch_time: datetime | None = None
        self._last_product_time: datetime | None = None
        self._bytes_received = 0
        self._messages_received = 0
        self._epochs_processed = 0
        self._observations_ingested = 0
        self._products_emitted = 0
        self._rh_initialized = False
        self._rh_initial_m: float | None = None
        self._rh_initial_arc_count = 0
        self._last_epoch_summary: dict[str, Any] = {}
        self._latest_skyplot: list[dict[str, Any]] = []
        self._latest_system_counts: dict[str, int] = {}
        self._latest_signal_counts: dict[str, int] = {}
        self._latest_record_samples: list[dict[str, Any]] = []
        self._last_filter_warning = "No epoch has been decoded yet"

    def stop(self) -> None:
        self.stop_event.set()
        stream = self._stream
        eph_stream = self._eph_stream
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        if eph_stream is not None:
            try:
                eph_stream.close()
            except Exception:
                pass

    def run(self) -> None:
        self._set_state("starting")
        try:
            self._load_reflectometry_processor()
            self._validate_stream_config()
            self._set_state("waiting")
            self._log("Worker started")
            self._start_ephemeris_worker()
            while not self.stop_event.is_set():
                try:
                    self._run_connection_cycle()
                except Exception as exc:
                    self._set_error(str(exc))
                    self._log(f"Stream error: {exc}")
                finally:
                    self._flush_pending_epoch()
                    self._close_stream()
                if self.stop_event.is_set():
                    break
                delay = max(0.5, float(self.station.obs_settings.reconnect_delay_seconds))
                self._set_state("reconnecting")
                self._log(f"Reconnect in {delay:.1f}s")
                self.sleep_fn(delay)
        except Exception as exc:
            self._set_error(str(exc))
            self._log(f"Worker failed: {exc}")
        finally:
            self._close_stream()
            self._close_eph_stream()
            self._set_state("stopped")
            self._log("Worker stopped")

    def snapshot(self) -> dict[str, Any]:
        with self.status_lock:
            latest = self.history.latest()
            return {
                "name": self.station.name,
                "enabled": self.station.enabled,
                "alive": self.is_alive(),
                "state": self._state,
                "host": self.station.obs_settings.host,
                "port": self.station.obs_settings.port,
                "mountpoint": self.station.obs_settings.mountpoint,
                "obs_settings": _stream_snapshot(self.station.obs_settings),
                "reflectometry_config": str(self.station.reflectometry_config),
                "last_error": self._last_error,
                "last_eph_error": self._last_eph_error,
                "last_message_time": _iso(self._last_message_time),
                "last_eph_message_time": _iso(self._last_eph_message_time),
                "last_epoch_time": _iso(self._last_epoch_time),
                "last_product_time": _iso(self._last_product_time),
                "bytes_received": self._bytes_received,
                "messages_received": self._messages_received,
                "epochs_processed": self._epochs_processed,
                "observations_ingested": self._observations_ingested,
                "products_emitted": self._products_emitted,
                "rh_initialized": self._rh_initialized,
                "rh_initial_m": self._rh_initial_m,
                "rh_initial_arc_count": self._rh_initial_arc_count,
                "latest_product": latest,
                "stream_health": self._stream_health_locked(),
                "ephemeris_stream": {
                    "enabled": _stream_enabled(self.station.eph_settings),
                    "state": self._eph_state,
                    "host": self.station.eph_settings.host,
                    "port": self.station.eph_settings.port,
                    "mountpoint": self.station.eph_settings.mountpoint,
                    "settings": _stream_snapshot(self.station.eph_settings),
                    "last_message_time": _iso(self._last_eph_message_time),
                    "last_error": self._last_eph_error,
                    "message_age_seconds": _age_seconds(datetime.now(timezone.utc), self._last_eph_message_time),
                },
                "epoch_summary": dict(self._last_epoch_summary),
                "skyplot": [dict(item) for item in self._latest_skyplot],
                "system_counts": dict(self._latest_system_counts),
                "signal_counts": dict(self._latest_signal_counts),
                "record_samples": [dict(item) for item in self._latest_record_samples],
                "initialization": self._build_initialization_status_locked(),
                "reflection_zones": _reflection_zones(self._reflector_config),
            }

    def products(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.history.list(limit)

    def _run_connection_cycle(self) -> None:
        ntrip = self._to_ntrip_source(self.station.obs_settings)
        endpoint = f"{ntrip.host}:{ntrip.port}/{ntrip.mountpoint}"
        self._set_state("connecting")
        self._log(f"Connecting to {endpoint}")
        self._stream = self.stream_connector(ntrip)
        self._handler = RTCMHandler(reference_utc=datetime.now(timezone.utc), compute_geometry=True)
        self._set_state("running")
        self._set_error("")
        self._log(f"Connected to {endpoint}")

        reader = self.reader_factory(self._stream)
        for raw, msg in reader:
            if self.stop_event.is_set():
                break
            self._consume_message(raw, msg)

        if not self.stop_event.is_set():
            self._log("Connection closed by remote peer")

    def _start_ephemeris_worker(self) -> None:
        if not _stream_enabled(self.station.eph_settings):
            self._set_eph_state("disabled")
            return
        self._eph_thread = Thread(target=self._run_ephemeris_loop, name=f"RealtimeEkfGNSSIR-Eph-{self.station.name}", daemon=True)
        self._eph_thread.start()

    def _run_ephemeris_loop(self) -> None:
        ntrip = self._to_ntrip_source(self.station.eph_settings)
        endpoint = f"{ntrip.host}:{ntrip.port}/{ntrip.mountpoint}"
        self._eph_handler = RTCMHandler(reference_utc=datetime.now(timezone.utc), compute_geometry=False)
        while not self.stop_event.is_set():
            try:
                self._set_eph_state("connecting")
                self._log(f"Connecting EPH stream to {endpoint}")
                self._eph_stream = self.stream_connector(ntrip)
                self._set_eph_state("running")
                self._set_eph_error("")
                reader = self.reader_factory(self._eph_stream)
                for raw, msg in reader:
                    if self.stop_event.is_set():
                        break
                    if msg is None or self._eph_handler is None:
                        continue
                    with self.status_lock:
                        self._last_eph_message_time = datetime.now(timezone.utc)
                    with _RTCM_GLOBAL_CONFIG_LOCK:
                        self._eph_handler.process_message(msg)
            except Exception as exc:
                self._set_eph_error(str(exc))
                self._log(f"EPH stream error: {exc}")
            finally:
                self._close_eph_stream()
            if self.stop_event.is_set():
                break
            delay = max(0.5, float(self.station.eph_settings.reconnect_delay_seconds))
            self._set_eph_state("reconnecting")
            self.sleep_fn(delay)

    def _consume_message(self, raw: bytes | None, msg: object) -> None:
        now = datetime.now(timezone.utc)
        with self.status_lock:
            self._last_message_time = now
            self._messages_received += 1
            if raw:
                self._bytes_received += len(raw)

        if msg is None or self._handler is None:
            return

        config = self._reflector_config
        if config is None:
            return

        with _RTCM_GLOBAL_CONFIG_LOCK:
            update_general_settings(
                {
                    "approx_rec_pos": _receiver_xyz(config),
                    "target_systems": _active_systems(config),
                }
            )
            epoch_data = self._handler.process_message(msg)

        if epoch_data is None:
            return

        epoch_key = _epoch_key_millis(epoch_data)
        if self._current_epoch is None:
            self._current_epoch = epoch_data
            self._current_epoch_key = epoch_key
            return
        if epoch_key == self._current_epoch_key:
            _merge_epoch_data(self._current_epoch, epoch_data)
            return

        completed_epoch = self._current_epoch
        self._current_epoch = epoch_data
        self._current_epoch_key = epoch_key
        self._handle_epoch(completed_epoch)

    def _flush_pending_epoch(self) -> None:
        if self._current_epoch is None:
            return
        epoch = self._current_epoch
        self._current_epoch = None
        self._current_epoch_key = None
        self._handle_epoch(epoch)

    def _handle_epoch(self, epoch_data: EpochObservation) -> None:
        config = self._reflector_config
        processor = self._processor
        if config is None or processor is None:
            return
        epoch_time = getattr(epoch_data, "utc_datetime", None)
        if epoch_time is None:
            return
        records = build_observation_records_from_epoch(
            epoch_data,
            station_id=config.station.station_id,
            timestamp=epoch_time,
            receiver_position=config.station.receiver_position,
            active_systems=set(_active_systems(config)),
            input_config=config.input,
        )
        epoch_summary = _summarize_epoch(
            epoch_data,
            records,
            geometry_config=config.geometry,
            processing_config=config.processing,
            input_signals=config.input.signals,
        )
        if not records:
            with self.status_lock:
                self._last_epoch_time = epoch_time
                self._epochs_processed += 1
                self._last_epoch_summary = epoch_summary
                self._latest_skyplot = epoch_summary.get("satellites", [])
                self._latest_system_counts = epoch_summary.get("system_counts", {})
                self._latest_signal_counts = epoch_summary.get("signal_counts", {})
                self._latest_record_samples = []
                self._last_filter_warning = epoch_summary.get("warning", "No reflectometry records passed filters")
            return

        result = processor.ingest(records, reference_time=epoch_time)
        self._capture_new_products(result)
        self._update_initialization_status()
        with self.status_lock:
            self._last_epoch_time = epoch_time
            self._epochs_processed += 1
            self._observations_ingested += len(records)
            self._last_epoch_summary = epoch_summary
            self._latest_skyplot = epoch_summary.get("satellites", [])
            self._latest_system_counts = epoch_summary.get("system_counts", {})
            self._latest_signal_counts = epoch_summary.get("signal_counts", {})
            self._latest_record_samples = _record_samples(records)
            self._last_filter_warning = ""

    def _capture_new_products(self, result: ProcessingRunResult) -> None:
        new_products: list[ProductResult] = []
        for product in result.products:
            key = (
                product.product_type.value,
                product.timestamp.isoformat(),
                f"{float(product.value):.12f}",
            )
            if key in self._known_product_keys:
                continue
            self._known_product_keys.add(key)
            new_products.append(product)
        if not new_products:
            return
        rows = self.history.append_many(new_products)
        self._persist_products(rows)
        with self.status_lock:
            self._products_emitted += len(rows)
            product_times = [_parse_iso(row.get("timestamp")) for row in rows]
            product_times = [item for item in product_times if item is not None]
            if product_times:
                self._last_product_time = max(product_times)

    def _persist_products(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        station_dir = self.storage.output_dir / self.station.name
        station_dir.mkdir(parents=True, exist_ok=True)
        if self.storage.write_jsonl:
            jsonl_path = station_dir / "products.jsonl"
            with jsonl_path.open("a", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        if self.storage.write_csv:
            csv_path = station_dir / "products.csv"
            write_header = not csv_path.exists()
            fields = [
                "station",
                "product_type",
                "timestamp",
                "value",
                "unit",
                "source_arc_count",
                "confidence",
                "active_arc_count",
                "sample_count",
                "covariance_m2",
                "innovation_rms",
                "rh_initial_m",
            ]
            with csv_path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                if write_header:
                    writer.writeheader()
                for row in rows:
                    metadata = row.get("metadata") or {}
                    writer.writerow(
                        {
                            "station": self.station.name,
                            "product_type": row.get("product_type"),
                            "timestamp": row.get("timestamp"),
                            "value": row.get("value"),
                            "unit": row.get("unit"),
                            "source_arc_count": row.get("source_arc_count"),
                            "confidence": row.get("confidence"),
                            "active_arc_count": metadata.get("active_arc_count"),
                            "sample_count": metadata.get("sample_count"),
                            "covariance_m2": metadata.get("covariance_m2"),
                            "innovation_rms": metadata.get("innovation_rms"),
                            "rh_initial_m": metadata.get("rh_initial_m"),
                        }
                    )

    def _load_reflectometry_processor(self) -> None:
        config = load_config(self.station.reflectometry_config)
        if str(config.ir.estimation_mode).lower() != "ekf":
            raise ValueError(
                f"{self.station.reflectometry_config} is not configured for ir.estimation_mode=ekf"
            )
        xyz = _receiver_xyz(config)
        if xyz is None:
            raise ValueError("station.receiver_position.x_m/y_m/z_m is required for realtime RTCM geometry")
        self._reflector_config = config
        self._processor = RealtimeProcessor(config)
        self._log(
            "Loaded reflectometry config "
            f"{self.station.reflectometry_config} with output interval "
            f"{config.ir.ekf.output_interval_seconds}s"
        )

    def _validate_stream_config(self) -> None:
        obs = self.station.obs_settings
        if not _is_ntrip(obs):
            raise ValueError(f"OBS source_type must be NTRIP Server for realtime EKF mode, got {obs.source_type!r}")
        if not obs.enabled:
            raise ValueError("OBS stream is disabled")
        if not obs.host or not obs.mountpoint:
            raise ValueError("OBS NTRIP host and mountpoint are required before starting this station")
        eph = self.station.eph_settings
        if eph.enabled and not _is_ntrip(eph):
            raise ValueError(f"EPH source_type must be NTRIP Server for realtime EKF mode, got {eph.source_type!r}")
        if eph.enabled and (not eph.host or not eph.mountpoint):
            raise ValueError("EPH NTRIP host and mountpoint are required when EPH stream is enabled")

    def _update_initialization_status(self) -> None:
        processor = self._processor
        ekf = getattr(processor, "ekf_processor", None) if processor is not None else None
        if ekf is None:
            return
        initialization = getattr(ekf, "rh_initialization", None)
        with self.status_lock:
            self._rh_initialized = bool(getattr(ekf, "rh_initialized", False))
            if initialization is not None:
                self._rh_initial_m = float(initialization.reflector_height_m)
                self._rh_initial_arc_count = int(initialization.arc_count)

    def _stream_health_locked(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        message_age = _age_seconds(now, self._last_message_time)
        epoch_age = _age_seconds(now, self._last_epoch_time)
        if self._last_error:
            label = "error"
        elif self._state in {"connecting", "running", "waiting"} and self._last_message_time is None:
            label = "waiting_stream"
        elif message_age is not None and message_age > 30.0:
            label = "stale_messages"
        elif self._last_epoch_time is None and self._messages_received > 0:
            label = "waiting_epoch"
        elif epoch_age is not None and epoch_age > 90.0:
            label = "stale_epoch"
        elif self._state == "running":
            label = "healthy"
        else:
            label = self._state
        return {
            "label": label,
            "message_age_seconds": message_age,
            "epoch_age_seconds": epoch_age,
            "last_filter_warning": self._last_filter_warning,
        }

    def _build_initialization_status_locked(self) -> dict[str, Any]:
        processor = self._processor
        ekf = getattr(processor, "ekf_processor", None) if processor is not None else None
        if ekf is None:
            return {
                "mode": "not_ekf",
                "rh_initialized": False,
                "waiting_reason": "EKF processor is not available",
                "arcs": [],
            }
        config = getattr(ekf, "config", None)
        required_lsp = int(getattr(config, "rh_init_min_samples", 0) or 0)
        required_arc = int(getattr(config, "init_min_samples", 0) or 0)
        arc_groups: dict[tuple[str, str], dict[str, Any]] = {}
        for arc_state in getattr(ekf, "arc_states", {}).values():
            detrended_count = len(getattr(arc_state, "detrended_samples", []) or [])
            sample_count = len(getattr(arc_state, "samples", []) or [])
            initialized = bool(getattr(arc_state, "initialized", False))
            key = getattr(arc_state, "key", ("", "", ""))
            group_key = _satellite_arc_key_from_tuple(key)
            group = arc_groups.setdefault(
                group_key,
                {
                    "arc": "-".join(item for item in group_key if item),
                    "constellation": group_key[0],
                    "satellite": group_key[1],
                    "signals": [],
                    "signal_count": 0,
                    "sample_count": 0,
                    "detrended_sample_count": 0,
                    "initialized": False,
                    "ready_lsp": False,
                    "last_timestamp": None,
                    "last_elevation_deg": None,
                    "direction": "unknown",
                },
            )
            signal = str(key[2]) if len(key) > 2 else ""
            if signal and signal not in group["signals"]:
                group["signals"].append(signal)
                group["signal_count"] = len(group["signals"])
            group["sample_count"] += sample_count
            group["detrended_sample_count"] = max(int(group["detrended_sample_count"]), detrended_count)
            group["initialized"] = bool(group["initialized"] or initialized)
            group["ready_lsp"] = bool(group["ready_lsp"] or (not initialized and required_lsp and detrended_count >= required_lsp))
            last_timestamp = _iso(getattr(arc_state, "last_timestamp", None))
            if last_timestamp and (not group["last_timestamp"] or last_timestamp > group["last_timestamp"]):
                group["last_timestamp"] = last_timestamp
                group["last_elevation_deg"] = _optional_float(getattr(arc_state, "last_elevation_deg", None))
                group["direction"] = _direction_label(getattr(arc_state, "direction_sign", None))
        arcs = list(arc_groups.values())
        for arc in arcs:
            arc["signals"] = ",".join(arc.get("signals") or [])
        ready_lsp_count = sum(1 for arc in arcs if arc.get("ready_lsp"))
        initialized_arc_count = sum(1 for arc in arcs if arc.get("initialized"))
        max_lsp_samples = max([0] + [int(arc.get("detrended_sample_count") or 0) for arc in arcs])
        arcs.sort(key=lambda item: item.get("last_timestamp") or "", reverse=True)
        rh_initialized = bool(getattr(ekf, "rh_initialized", False))
        waiting_reason = ""
        if rh_initialized:
            waiting_reason = "LSP initialization finished"
        elif self._last_message_time is None:
            waiting_reason = "No RTCM message has arrived"
        elif self._last_epoch_time is None:
            waiting_reason = "RTCM messages are arriving, but no complete observation epoch has been decoded"
        elif not self._latest_skyplot:
            waiting_reason = "Epochs are decoded, but azimuth/elevation geometry is missing"
        elif not self._latest_record_samples:
            waiting_reason = self._last_filter_warning or "No SNR records passed reflectometry filters"
        elif not arcs:
            waiting_reason = "Reflectometry records exist, waiting for EKF arc tracking"
        elif ready_lsp_count <= 0:
            waiting_reason = f"Waiting for one arc to reach {required_lsp} detrended samples"
        else:
            waiting_reason = "LSP candidates are ready, waiting for stable RH estimate"
        progress = 1.0 if rh_initialized else (min(1.0, max_lsp_samples / required_lsp) if required_lsp else 0.0)
        return {
            "mode": "ekf",
            "rh_initialized": rh_initialized,
            "rh_initial_m": self._rh_initial_m,
            "rh_initial_arc_count": self._rh_initial_arc_count,
            "required_lsp_samples": required_lsp,
            "required_arc_samples": required_arc,
            "max_lsp_samples": max_lsp_samples,
            "ready_lsp_arc_count": ready_lsp_count,
            "tracked_arc_count": len(arcs),
            "initialized_arc_count": initialized_arc_count,
            "progress": progress,
            "waiting_reason": waiting_reason,
            "arcs": arcs[:60],
        }

    def _set_state(self, state: str) -> None:
        with self.status_lock:
            self._state = state

    def _set_error(self, message: str) -> None:
        with self.status_lock:
            self._last_error = message

    def _set_eph_state(self, state: str) -> None:
        with self.status_lock:
            self._eph_state = state

    def _set_eph_error(self, message: str) -> None:
        with self.status_lock:
            self._last_eph_error = message

    def _log(self, message: str) -> None:
        self.log_fn(self.station.name, message)

    def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.close()
        except Exception:
            pass

    def _close_eph_stream(self) -> None:
        stream = self._eph_stream
        self._eph_stream = None
        if stream is None:
            return
        try:
            stream.close()
        except Exception:
            pass

    @staticmethod
    def _to_ntrip_source(config: StreamConfig) -> NtripSourceConfig:
        return NtripSourceConfig(
            host=config.host,
            port=int(config.port),
            mountpoint=config.mountpoint,
            user=config.user,
            password=config.password,
            user_agent=config.user_agent,
            connect_timeout_seconds=float(config.connect_timeout_seconds),
            reconnect_delay_seconds=float(config.reconnect_delay_seconds),
        )


def _product_to_dict(product: ProductResult) -> dict[str, Any]:
    data = ResultSerializer._normalize(asdict(product) if is_dataclass(product) else product)
    if isinstance(data, dict):
        _normalize_product_arc_metadata(data)
        return data
    return {"value": data}


def _normalize_product_arc_metadata(row: dict[str, Any]) -> None:
    metadata = row.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        row["metadata"] = metadata
    if "active_satellite_arc_count" not in metadata:
        metadata["active_satellite_arc_count"] = metadata.get("active_arc_count", row.get("source_arc_count"))


def _receiver_xyz(config: ReflectorConfig) -> list[float] | None:
    position = config.station.receiver_position
    xyz = [position.x_m, position.y_m, position.z_m]
    if any(value is None for value in xyz):
        return None
    return [float(value) for value in xyz]


def _active_systems(config: ReflectorConfig) -> list[str]:
    systems = [str(item).strip().upper()[0] for item in config.input.constellations if str(item).strip()]
    return systems or ["G", "R", "E", "C", "J", "S", "I"]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _satellite_arc_key_from_tuple(key: Any) -> tuple[str, str]:
    if not isinstance(key, tuple):
        key = tuple(key or ())
    constellation = str(key[0]) if len(key) > 0 else ""
    satellite = str(key[1]) if len(key) > 1 else ""
    return constellation, satellite


def _summarize_epoch(
    epoch_data: EpochObservation,
    records,
    *,
    geometry_config=None,
    processing_config=None,
    input_signals: list[str] | None = None,
) -> dict[str, Any]:
    satellites = getattr(epoch_data, "satellites", {}) or {}
    skyplot: list[dict[str, Any]] = []
    system_counts: dict[str, int] = {}
    signal_counts: dict[str, int] = {}
    geometric_count = 0
    snr_signal_count = 0
    reflection_zone_satellites: set[str] = set()
    for sat_key, sat_state in satellites.items():
        system = str(getattr(sat_state, "sys_id", str(sat_key)[0] if sat_key else ""))
        system_counts[system] = system_counts.get(system, 0) + 1
        azimuth = getattr(sat_state, "azimuth", getattr(sat_state, "az", None))
        elevation = getattr(sat_state, "elevation", getattr(sat_state, "el", None))
        signals = getattr(sat_state, "signals", {}) or {}
        positive_signals = 0
        for signal_id, signal in signals.items():
            snr = float(getattr(signal, "snr", 0.0) or 0.0)
            if snr <= 0.0:
                continue
            positive_signals += 1
            snr_signal_count += 1
            normalized = str(signal_id).strip().upper()
            signal_counts[normalized] = signal_counts.get(normalized, 0) + 1
        if azimuth is not None and elevation is not None:
            geometric_count += 1
            if geometry_config is not None and matches_reflection_zones(
                azimuth_deg=float(azimuth),
                elevation_deg=float(elevation),
                geometry_config=geometry_config,
                processing_config=processing_config,
            ):
                reflection_zone_satellites.add(str(sat_key))
            skyplot.append(
                {
                    "satellite": str(sat_key),
                    "system": system,
                    "azimuth_deg": float(azimuth),
                    "elevation_deg": float(elevation),
                    "signal_count": positive_signals,
                }
            )
    record_count = len(records or [])
    inversion_satellites: set[str] = set()
    inversion_arcs: set[tuple[str, str]] = set()
    for record in records or []:
        satellite = str(getattr(record, "satellite", "") or "").strip()
        constellation = str(getattr(record, "constellation", "") or "").strip()
        if satellite:
            inversion_satellites.add(satellite)
        inversion_arcs.add((constellation, satellite))
    warning = ""
    if not satellites:
        warning = "No satellites in decoded epoch"
    elif geometric_count <= 0:
        warning = "Decoded epoch has no azimuth/elevation; check ephemeris and receiver XYZ"
    elif snr_signal_count <= 0:
        warning = "Decoded epoch has no positive SNR values"
    elif record_count <= 0:
        include = ",".join(input_signals or [])
        warning = f"No records passed reflectometry filters; check constellations/signals/zones ({include})"
    return {
        "timestamp": _iso(getattr(epoch_data, "utc_datetime", None)),
        "satellite_count": len(satellites),
        "geometric_satellite_count": geometric_count,
        "snr_signal_count": snr_signal_count,
        "inversion_satellite_count": len(reflection_zone_satellites),
        "record_satellite_count": len(inversion_satellites),
        "inversion_arc_count": len(inversion_arcs),
        "record_count": record_count,
        "system_counts": system_counts,
        "signal_counts": signal_counts,
        "satellites": skyplot[:120],
        "warning": warning,
    }


def _record_samples(records, limit: int = 80) -> list[dict[str, Any]]:
    samples = []
    for record in list(records or [])[:limit]:
        samples.append(
            {
                "satellite": record.satellite,
                "constellation": record.constellation,
                "signal": record.signal,
                "snr": float(record.snr),
                "azimuth_deg": _optional_float(record.azimuth_deg),
                "elevation_deg": _optional_float(record.elevation_deg),
                "timestamp": _iso(record.timestamp),
            }
        )
    return samples


def _reflection_zones(config: ReflectorConfig | None) -> list[dict[str, Any]]:
    if config is None:
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


def _is_ntrip(config: StreamConfig) -> bool:
    return str(config.source_type or "").strip().lower() == "ntrip server"


def _stream_enabled(config: StreamConfig) -> bool:
    return bool(config.enabled and _is_ntrip(config) and config.host and config.mountpoint)


def _stream_snapshot(config: StreamConfig) -> dict[str, Any]:
    return {
        "source_type": config.source_type,
        "enabled": config.enabled,
        "host": config.host,
        "port": config.port,
        "mountpoint": config.mountpoint,
        "user": config.user,
        "password": config.password,
        "serial_port": config.serial_port,
        "baudrate": config.baudrate,
        "databits": config.databits,
        "stopbits": config.stopbits,
        "parity": config.parity,
        "flowctrl": config.flowctrl,
        "file_path": config.file_path,
        "replay_speed": config.replay_speed,
        "file_type": config.file_type,
        "final_results_only": config.final_results_only,
        "connect_timeout_seconds": config.connect_timeout_seconds,
        "reconnect_delay_seconds": config.reconnect_delay_seconds,
    }


def _age_seconds(now: datetime, value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0.0, (now - value.astimezone(timezone.utc)).total_seconds())


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _direction_label(value: Any) -> str:
    if value == 1:
        return "rising"
    if value == -1:
        return "setting"
    return "unknown"


__all__ = ["RealtimeEkfStationWorker", "ProductHistory"]
