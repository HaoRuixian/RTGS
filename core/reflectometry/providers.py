"""Observation providers for reflectometry input sources.

This module keeps the source adapters together so the reflectometry package
does not need a deep provider subpackage for a handful of lightweight loaders.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from core.geo_utils import get_freq
import numpy as np

from core.reflectometry.models import (
    ObservationRecord,
    ObservationRequest,
    ReceiverPosition,
    SnrUnit,
)

_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "station_id": ("station_id",),
    "timestamp": ("timestamp", "time", "utc_datetime"),
    "constellation": ("constellation", "sys", "system"),
    "satellite": ("satellite", "prn", "satellite_id"),
    "signal": ("signal", "signal_id", "frequency"),
    "snr": ("snr", "cno", "cn0"),
    "snr_unit": ("snr_unit",),
    "azimuth_deg": ("azimuth_deg", "azimuth", "az"),
    "elevation_deg": ("elevation_deg", "elevation", "el"),
    "pseudorange_m": ("pseudorange_m", "pseudorange"),
    "carrier_phase_cycles": ("carrier_phase_cycles", "carrier_phase", "phase"),
    "multipath_indicator": ("multipath_indicator", "multipath"),
}
_DEFAULT_CONSTELLATIONS = ("G", "R", "E", "C", "J", "S")
_DEFAULT_SIGNALS_BY_CONSTELLATION: dict[str, tuple[str, ...]] = {
    "G": ("1C", "2W", "5Q"),
    "R": ("1C", "2C", "3Q"),
    "E": ("1C", "5Q", "7Q", "8Q"),
    "C": ("1C", "2I", "5P", "6I", "7I"),
    "J": ("1C", "2L", "5Q", "6S"),
    "S": ("1C", "5Q"),
}


class ObservationProvider(ABC):
    """Abstract observation provider."""

    @abstractmethod
    def fetch_observations(self, request: ObservationRequest) -> list[ObservationRecord]:
        """Load observations for the requested time window."""


class CsvObservationProvider(ObservationProvider):
    """Load observations from CSV."""

    def __init__(self, path: str | Path, station_id: str, receiver_position: ReceiverPosition | None = None) -> None:
        self.path = Path(path)
        self.station_id = station_id
        self.receiver_position = receiver_position

    def fetch_observations(self, request: ObservationRequest) -> list[ObservationRecord]:
        pd = _import_pandas()
        frame = pd.read_csv(self.path)
        return _filter_records(
            dataframe_to_observations(frame, station_id=self.station_id, receiver_position=self.receiver_position),
            request,
        )


class JsonObservationProvider(ObservationProvider):
    """Load observations from JSON arrays or JSONL files."""

    def __init__(self, path: str | Path, station_id: str, receiver_position: ReceiverPosition | None = None) -> None:
        self.path = Path(path)
        self.station_id = station_id
        self.receiver_position = receiver_position

    def fetch_observations(self, request: ObservationRequest) -> list[ObservationRecord]:
        pd = _import_pandas()
        text = self.path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        payload = json.loads(text) if text.startswith("[") else [json.loads(line) for line in text.splitlines() if line.strip()]
        frame = pd.DataFrame(payload)
        return _filter_records(
            dataframe_to_observations(frame, station_id=self.station_id, receiver_position=self.receiver_position),
            request,
        )


class ParquetObservationProvider(ObservationProvider):
    """Load observations from a parquet dataset."""

    def __init__(self, path: str | Path, station_id: str, receiver_position: ReceiverPosition | None = None) -> None:
        self.path = Path(path)
        self.station_id = station_id
        self.receiver_position = receiver_position

    def fetch_observations(self, request: ObservationRequest) -> list[ObservationRecord]:
        pd = _import_pandas()
        frame = pd.read_parquet(self.path)
        return _filter_records(
            dataframe_to_observations(frame, station_id=self.station_id, receiver_position=self.receiver_position),
            request,
        )


class ListObservationProvider(ObservationProvider):
    """Serve observations from an in-memory list."""

    def __init__(self, observations: list[ObservationRecord]) -> None:
        self.observations = observations

    def fetch_observations(self, request: ObservationRequest) -> list[ObservationRecord]:
        return _filter_records(sorted(self.observations, key=lambda item: item.timestamp), request)


class CacheReader(Protocol):
    """Protocol for upstream RTCM cache readers."""

    def read_observations(self, request: ObservationRequest) -> Iterable[ObservationRecord | dict[str, Any]]:
        """Return observations for a requested time window."""


class CacheObservationProvider(ObservationProvider):
    """Adapter for in-memory caches or shared observation stores."""

    def __init__(
        self,
        reader: CacheReader | Callable[[ObservationRequest], Iterable[ObservationRecord | dict[str, Any]]],
        station_id: str,
        receiver_position: ReceiverPosition | None = None,
    ) -> None:
        self.reader = reader
        self.station_id = station_id
        self.receiver_position = receiver_position

    def fetch_observations(self, request: ObservationRequest) -> list[ObservationRecord]:
        raw_records = self.reader.read_observations(request) if hasattr(self.reader, "read_observations") else self.reader(request)
        records = [self._normalize(item) for item in raw_records]
        records = [item for item in records if _matches_request(item, request)]
        return sorted(records, key=lambda item: item.timestamp)

    def _normalize(self, item: ObservationRecord | dict[str, Any]) -> ObservationRecord:
        if isinstance(item, ObservationRecord):
            return item
        payload = dict(item)
        template_keys = asdict(self._template()).keys()
        return ObservationRecord(
            station_id=str(payload.get("station_id", self.station_id)),
            timestamp=_coerce_datetime(payload["timestamp"]),
            constellation=str(payload["constellation"]),
            satellite=str(payload["satellite"]),
            signal=str(payload["signal"]),
            snr=float(payload["snr"]),
            snr_unit=SnrUnit(str(payload.get("snr_unit", "db_hz")).lower()),
            azimuth_deg=_optional_float(payload.get("azimuth_deg")),
            elevation_deg=_optional_float(payload.get("elevation_deg")),
            pseudorange_m=_optional_float(payload.get("pseudorange_m")),
            carrier_phase_cycles=_optional_float(payload.get("carrier_phase_cycles")),
            multipath_indicator=_optional_float(payload.get("multipath_indicator")),
            receiver_position=self.receiver_position,
            environment_metadata=dict(payload.get("environment_metadata", {})),
            observation_metadata={key: value for key, value in payload.items() if key not in template_keys},
        )

    def _template(self) -> ObservationRecord:
        return ObservationRecord(
            station_id=self.station_id,
            timestamp=datetime.utcnow(),
            constellation="G",
            satellite="G00",
            signal="1C",
            snr=0.0,
        )

    @classmethod
    def from_gnss_ir_store(
        cls,
        store: Any,
        station_id: str,
        receiver_position: ReceiverPosition | None = None,
        timestamp_resolver: Callable[[Any], datetime] | None = None,
    ) -> "CacheObservationProvider":
        """Adapt the current UI rolling store without coupling the domain to it."""

        if timestamp_resolver is None:
            raise ValueError(
                "GnssIrStore samples only expose tow; provide timestamp_resolver(sample) "
                "to map them into absolute datetimes."
            )

        def reader(_: ObservationRequest) -> Iterable[dict[str, Any]]:
            for sample in store.get_series():
                yield {
                    "station_id": station_id,
                    "timestamp": timestamp_resolver(sample),
                    "constellation": str(sample.sys),
                    "satellite": str(sample.prn),
                    "signal": str(sample.signal_id),
                    "snr": float(sample.snr),
                    "snr_unit": "db_hz",
                    "azimuth_deg": float(sample.azimuth),
                    "elevation_deg": float(sample.elevation),
                    "pseudorange_m": float(getattr(sample, "pseudorange", 0.0) or 0.0),
                    "carrier_phase_cycles": float(getattr(sample, "phase", 0.0) or 0.0),
                }

        return cls(reader=reader, station_id=station_id, receiver_position=receiver_position)


class MockObservationProvider(ObservationProvider):
    """Generate deterministic GNSS-IR-like observations."""

    def __init__(
        self,
        station_id: str,
        receiver_position: ReceiverPosition | None = None,
        source_options: dict[str, object] | None = None,
        seed: int = 42,
    ) -> None:
        self.station_id = station_id
        self.receiver_position = receiver_position
        self.source_options = source_options or {}
        self.random = np.random.default_rng(seed)

    def fetch_observations(self, request: ObservationRequest) -> list[ObservationRecord]:
        start = request.start_time or datetime(2026, 3, 19, 0, 0, 0)
        end = request.end_time or (start + timedelta(hours=4))
        blocked_constellations = set(request.exclude_constellations)
        blocked_signals = set(request.exclude_signals)
        constellations = [
            item
            for item in (request.constellations or _DEFAULT_CONSTELLATIONS)
            if item not in blocked_constellations
        ]
        arc_count = int(self.source_options.get("arc_count", 4))
        samples_per_arc = int(self.source_options.get("samples_per_arc", 60))
        reflector_height = float(self.source_options.get("reflector_height_m", 4.0))
        noise_std = float(self.source_options.get("noise_std_db", 0.4))
        amplitude_db = float(self.source_options.get("amplitude_db", 2.4))
        trend_bias = float(self.source_options.get("trend_bias_db", 44.0))

        duration = (end - start).total_seconds()
        arc_spacing = duration / max(arc_count, 1)
        sampling = request.sampling_interval_seconds or 30.0

        if not constellations:
            return []

        records: list[ObservationRecord] = []
        for arc_index in range(arc_count):
            constellation = constellations[arc_index % len(constellations)]
            signal_candidates = list(request.signals or _DEFAULT_SIGNALS_BY_CONSTELLATION.get(constellation, ("1C",)))
            signal_candidates = [item for item in signal_candidates if item not in blocked_signals]
            signal_candidates = [item for item in signal_candidates if _signal_supported(constellation, item)]
            if not signal_candidates:
                continue
            signal = signal_candidates[arc_index % len(signal_candidates)]
            satellite = f"{constellation}{(arc_index % 16) + 1:02d}"
            _frequency_hz, wavelength = get_freq(signal, satellite)
            if wavelength <= 0.0:
                continue
            direction = 1.0 if arc_index % 2 == 0 else -1.0

            arc_start = start + timedelta(seconds=arc_index * arc_spacing)
            elevations = np.linspace(6.0, 26.0, samples_per_arc)
            if direction < 0:
                elevations = elevations[::-1]
            azimuth_start = 150.0 + 20.0 * (arc_index % 6)
            azimuths = azimuth_start + np.linspace(0.0, 12.0, samples_per_arc)
            sin_elevation = np.sin(np.deg2rad(elevations))
            spectral_phase = 2.0 * np.pi * self.random.uniform(0.0, 1.0)
            oscillation = amplitude_db * np.cos((4.0 * np.pi * reflector_height / wavelength) * sin_elevation + spectral_phase)
            trend = trend_bias + 3.0 * sin_elevation - 1.5 * np.square(sin_elevation)
            snr = trend + oscillation + self.random.normal(0.0, noise_std, samples_per_arc)

            for idx in range(samples_per_arc):
                timestamp = arc_start + timedelta(seconds=idx * sampling)
                phase = 100_000.0 + idx * 0.25 + math.sin(idx / 5.0)
                records.append(
                    ObservationRecord(
                        station_id=self.station_id,
                        timestamp=timestamp,
                        constellation=constellation,
                        satellite=satellite,
                        signal=signal,
                        snr=float(snr[idx]),
                        azimuth_deg=float(azimuths[idx] % 360.0),
                        elevation_deg=float(elevations[idx]),
                        pseudorange_m=23_000_000.0 + 50.0 * idx,
                        carrier_phase_cycles=float(phase),
                        multipath_indicator=float(abs(oscillation[idx]) / max(amplitude_db, 1e-6)),
                        receiver_position=self.receiver_position,
                    )
                )
        return sorted(records, key=lambda item: item.timestamp)


def dataframe_to_observations(
    frame,
    station_id: str,
    receiver_position: ReceiverPosition | None = None,
) -> list[ObservationRecord]:
    """Convert a dataframe into the canonical observation model."""
    required = ["timestamp", "constellation", "satellite", "signal", "snr"]
    missing = [name for name in required if _pick_column(frame, name) is None]
    if missing:
        raise ValueError(f"Observation file missing required columns: {missing}")

    records: list[ObservationRecord] = []
    for _, row in frame.iterrows():
        record_station = row.get(_pick_column(frame, "station_id") or "", station_id)
        records.append(
            ObservationRecord(
                station_id=str(record_station or station_id),
                timestamp=_parse_timestamp(row[_pick_column(frame, "timestamp") or "timestamp"]),
                constellation=str(row[_pick_column(frame, "constellation") or "constellation"]),
                satellite=str(row[_pick_column(frame, "satellite") or "satellite"]),
                signal=str(row[_pick_column(frame, "signal") or "signal"]),
                snr=float(row[_pick_column(frame, "snr") or "snr"]),
                snr_unit=SnrUnit(str(row.get(_pick_column(frame, "snr_unit") or "", "db_hz")).lower()),
                azimuth_deg=_optional_float(row.get(_pick_column(frame, "azimuth_deg") or "")),
                elevation_deg=_optional_float(row.get(_pick_column(frame, "elevation_deg") or "")),
                pseudorange_m=_optional_float(row.get(_pick_column(frame, "pseudorange_m") or "")),
                carrier_phase_cycles=_optional_float(row.get(_pick_column(frame, "carrier_phase_cycles") or "")),
                multipath_indicator=_optional_float(row.get(_pick_column(frame, "multipath_indicator") or "")),
                receiver_position=receiver_position,
            )
        )
    return sorted(records, key=lambda item: item.timestamp)


def _filter_records(records: list[ObservationRecord], request: ObservationRequest) -> list[ObservationRecord]:
    filtered = records
    if request.start_time is not None:
        filtered = [item for item in filtered if item.timestamp >= request.start_time]
    if request.end_time is not None:
        filtered = [item for item in filtered if item.timestamp <= request.end_time]
    if request.constellations:
        allowed = set(request.constellations)
        filtered = [item for item in filtered if item.constellation in allowed]
    if request.signals:
        allowed_signals = set(request.signals)
        filtered = [item for item in filtered if item.signal in allowed_signals]
    if request.exclude_constellations:
        blocked = set(request.exclude_constellations)
        filtered = [item for item in filtered if item.constellation not in blocked]
    if request.exclude_signals:
        blocked_signals = set(request.exclude_signals)
        filtered = [item for item in filtered if item.signal not in blocked_signals]
    return filtered


def _matches_request(item: ObservationRecord, request: ObservationRequest) -> bool:
    if request.start_time and item.timestamp < request.start_time:
        return False
    if request.end_time and item.timestamp > request.end_time:
        return False
    if request.constellations and item.constellation not in set(request.constellations):
        return False
    if request.signals and item.signal not in set(request.signals):
        return False
    if request.exclude_constellations and item.constellation in set(request.exclude_constellations):
        return False
    if request.exclude_signals and item.signal in set(request.exclude_signals):
        return False
    return True


def _pick_column(frame, logical_name: str) -> str | None:
    for candidate in _COLUMN_ALIASES[logical_name]:
        if candidate in frame.columns:
            return candidate
    return None


def _parse_timestamp(value: Any) -> datetime:
    pd = _import_pandas()
    parsed = pd.to_datetime(value, utc=False)
    if isinstance(parsed, pd.Timestamp):
        return parsed.to_pydatetime()
    raise ValueError(f"Failed to parse timestamp value: {value!r}")


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(float(value))
    return datetime.fromisoformat(str(value))


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        if bool(np.isnan(value)):
            return None
    except TypeError:
        pass
    except ValueError:
        pass
    return float(value)


def _signal_supported(constellation: str, signal: str) -> bool:
    _frequency_hz, wavelength = get_freq(signal, f"{constellation}00")
    return wavelength > 0.0


def _import_pandas():
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "pandas is required for tabular reflectometry providers (csv/json/parquet)."
        ) from exc
    return pd


__all__ = [
    "CacheObservationProvider",
    "CacheReader",
    "CsvObservationProvider",
    "JsonObservationProvider",
    "ListObservationProvider",
    "MockObservationProvider",
    "ObservationProvider",
    "ParquetObservationProvider",
    "dataframe_to_observations",
]
