"""Utilities for stream configuration dictionaries."""

from __future__ import annotations

from collections.abc import Mapping


def stream_source(settings: Mapping[str, object] | None, default: str = "NTRIP Server") -> str:
    """Return the configured source type from legacy or global settings."""
    if not settings:
        return default
    source = settings.get("source") or settings.get("source_type") or default
    return str(source)


def stream_port(settings: Mapping[str, object] | None) -> str:
    """Return the active port field for NTRIP or serial stream settings."""
    if not settings:
        return ""
    source = stream_source(settings)
    if source == "Serial Port":
        return str(settings.get("serial_port") or settings.get("port") or "")
    return str(settings.get("port") or "")


def is_realtime_stream_configured(settings: Mapping[str, object] | None) -> bool:
    """Return True when a stream has enough settings to start live input."""
    if not settings:
        return False
    source = stream_source(settings)
    if source == "NTRIP Server":
        return bool(str(settings.get("host") or "").strip())
    if source == "Serial Port":
        return bool(stream_port(settings).strip())
    return False


def is_file_stream_configured(settings: Mapping[str, object] | None) -> bool:
    """Return True when a file-backed stream has a selected input path."""
    if not settings:
        return False
    return stream_source(settings) in {"RINEX File", "File"} and bool(
        str(settings.get("file_path") or "").strip()
    )
