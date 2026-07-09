"""Helpers for building reflectometry observations from RINEX replay epochs."""

from __future__ import annotations

from datetime import datetime

from .config import InputConfig
from .models import ObservationRecord, ReceiverPosition
from .signal_utils import normalize_signal_id, signal_matches


def signal_enabled_for_reflectometry(
    constellation: str,
    signal: str,
    *,
    active_systems: set[str] | None = None,
    input_config: InputConfig | None = None,
) -> bool:
    constellation = str(constellation)
    signal = normalize_signal_id(signal)

    if active_systems is not None and constellation not in active_systems:
        return False

    if input_config is None:
        return True

    include_constellations = set(input_config.constellations)
    include_signals = set(input_config.signals)
    exclude_constellations = set(input_config.exclude_constellations)
    exclude_signals = set(input_config.exclude_signals)

    if include_constellations and constellation not in include_constellations:
        return False
    if constellation in exclude_constellations:
        return False
    if include_signals and not signal_matches(signal, include_signals):
        return False
    if signal_matches(signal, exclude_signals):
        return False
    return True


def build_observation_records_from_epoch(
    epoch_data,
    *,
    station_id: str,
    timestamp: datetime | None = None,
    receiver_position: ReceiverPosition | None = None,
    active_systems: set[str] | None = None,
    input_config: InputConfig | None = None,
) -> list[ObservationRecord]:
    observations: list[ObservationRecord] = []
    timestamp = getattr(epoch_data, "utc_datetime", None) or timestamp
    if timestamp is None:
        return observations

    satellites = getattr(epoch_data, "satellites", {}) or {}
    for sat_key, sat in satellites.items():
        constellation = str(getattr(sat, "sys_id", sat_key[0]))
        azimuth = getattr(sat, "azimuth", getattr(sat, "az", None))
        elevation = getattr(sat, "elevation", getattr(sat, "el", None))
        signals = getattr(sat, "signals", {}) or {}
        for signal_id, signal in signals.items():
            if not signal_enabled_for_reflectometry(
                constellation,
                normalize_signal_id(signal_id),
                active_systems=active_systems,
                input_config=input_config,
            ):
                continue

            snr = float(getattr(signal, "snr", 0.0) or 0.0)
            if snr <= 0.0:
                continue

            observations.append(
                ObservationRecord(
                    station_id=station_id,
                    timestamp=timestamp,
                    constellation=constellation,
                    satellite=str(sat_key),
                    signal=normalize_signal_id(signal_id),
                    snr=snr,
                    azimuth_deg=float(azimuth) if azimuth is not None else None,
                    elevation_deg=float(elevation) if elevation is not None else None,
                    pseudorange_m=_optional_float(getattr(signal, "pseudorange", None)),
                    carrier_phase_cycles=_optional_float(getattr(signal, "phase", None)),
                    receiver_position=receiver_position,
                    observation_metadata=_signal_metadata(signal),
                )
            )
    return observations


def _optional_float(value) -> float | None:
    if value is None:
        return None
    return float(value)


def _signal_metadata(signal) -> dict[str, float]:
    metadata: dict[str, float] = {}
    glonass_fcn = getattr(signal, "glonass_fcn", None)
    if glonass_fcn is not None:
        metadata["glonass_fcn"] = float(glonass_fcn)
    return metadata


__all__ = [
    "build_observation_records_from_epoch",
    "signal_enabled_for_reflectometry",
]
