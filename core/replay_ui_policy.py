"""Policies for throttling GUI refresh during high-rate file replay."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Mapping, Any

from core.rinex_loader import read_rinex_observation_header


HIGH_RATE_REPLAY_THRESHOLD_HZ = 1.0
THROTTLED_GUI_INTERVAL_SECONDS = 0.5


def normalize_replay_speed(value: Any) -> float:
    """Return a positive replay speed multiplier."""
    try:
        replay_speed = float(value or 1.0)
    except (TypeError, ValueError):
        replay_speed = 1.0
    return replay_speed if replay_speed > 0.0 else 1.0


@lru_cache(maxsize=32)
def _read_interval_seconds(file_path: str) -> float | None:
    path = str(file_path or "").strip()
    if not path:
        return None
    try:
        metadata = read_rinex_observation_header(Path(path))
    except Exception:
        return None

    interval = metadata.interval_seconds
    if interval is None:
        return None
    try:
        interval_value = float(interval)
    except (TypeError, ValueError):
        return None
    return interval_value if interval_value > 0.0 else None


def estimate_effective_replay_period_seconds(settings: Mapping[str, Any] | None) -> float | None:
    """Estimate wall-clock spacing between replayed epochs."""
    settings = settings or {}
    source = str(settings.get("source", "") or "").strip()
    if source != "RINEX File":
        return None

    replay_speed = normalize_replay_speed(settings.get("replay_speed", 1.0))
    file_path = str(settings.get("file_path", "") or "").strip()
    interval_seconds = _read_interval_seconds(file_path) if file_path else None

    if interval_seconds is not None:
        return interval_seconds / replay_speed

    # Without a readable header, fall back to a conservative estimate so we still
    # protect the GUI when the user explicitly requests accelerated replay.
    if replay_speed > 1.0:
        return 1.0 / replay_speed
    return None


def is_high_rate_replay(
    settings: Mapping[str, Any] | None,
    threshold_hz: float = HIGH_RATE_REPLAY_THRESHOLD_HZ,
) -> bool:
    """Return True when file replay is expected to emit faster than the threshold."""
    if threshold_hz <= 0.0:
        threshold_hz = HIGH_RATE_REPLAY_THRESHOLD_HZ

    effective_period = estimate_effective_replay_period_seconds(settings)
    if effective_period is None:
        return False
    return effective_period < (1.0 / threshold_hz)


def choose_gui_refresh_interval(
    base_interval_seconds: float,
    settings: Mapping[str, Any] | None,
    throttled_interval_seconds: float = THROTTLED_GUI_INTERVAL_SECONDS,
) -> float:
    """Choose a GUI refresh interval that protects the UI during fast replay."""
    base_interval = max(0.0, float(base_interval_seconds))
    throttled_interval = max(base_interval, float(throttled_interval_seconds))
    if is_high_rate_replay(settings):
        return throttled_interval
    return base_interval
