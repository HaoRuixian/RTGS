"""Signal identifier normalization for reflectometry observations."""

from __future__ import annotations

from collections.abc import Iterable

_RINEX_OBSERVATION_PREFIXES = {"C", "L", "D", "S"}


def normalize_signal_id(signal: object) -> str:
    """Return the internal signal id used by RTGS, e.g. S1C/C1C -> 1C."""
    text = str(signal or "").strip().upper()
    if len(text) == 3 and text[0] in _RINEX_OBSERVATION_PREFIXES and text[1].isdigit():
        return text[1:]
    return text


def normalize_signal_ids(signals: Iterable[object] | None) -> set[str]:
    """Normalize a sequence of signal identifiers for config matching."""
    if not signals:
        return set()
    return {normalize_signal_id(item) for item in signals if normalize_signal_id(item)}


def signal_matches(signal: object, candidates: Iterable[object] | None) -> bool:
    """Return True when signal matches any candidate after RINEX-prefix normalization."""
    normalized_candidates = normalize_signal_ids(candidates)
    return bool(normalized_candidates) and normalize_signal_id(signal) in normalized_candidates


__all__ = ["normalize_signal_id", "normalize_signal_ids", "signal_matches"]
