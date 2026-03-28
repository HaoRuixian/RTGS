"""Observation providers for realtime reflectometry processing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Protocol

import numpy as np

from core.reflectometry.models import ObservationRecord, ObservationRequest, ReceiverPosition, SnrUnit


class ObservationProvider(ABC):
    """Abstract observation provider."""

    @abstractmethod
    def fetch_observations(self, request: ObservationRequest) -> list[ObservationRecord]:
        """Load observations for the requested request."""


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
            timestamp=datetime.now(timezone.utc),
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


__all__ = [
    "CacheObservationProvider",
    "CacheReader",
    "ListObservationProvider",
    "ObservationProvider",
]
