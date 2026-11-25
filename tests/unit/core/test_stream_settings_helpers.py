"""Tests for legacy-compatible stream configuration helpers."""

from __future__ import annotations

import pytest

from core.stream_settings import (
    is_file_stream_configured,
    is_realtime_stream_configured,
    stream_port,
    stream_source,
)


@pytest.mark.unit
def test_stream_source_supports_current_and_legacy_keys() -> None:
    assert stream_source({"source": "Serial Port"}) == "Serial Port"
    assert stream_source({"source_type": "RINEX File"}) == "RINEX File"
    assert stream_source(None) == "NTRIP Server"
    assert stream_source({}, default="File") == "File"


@pytest.mark.unit
def test_stream_port_uses_source_specific_field() -> None:
    assert stream_port({"source": "Serial Port", "serial_port": "COM4", "port": 2101}) == "COM4"
    assert stream_port({"source": "NTRIP Server", "port": 2101}) == "2101"
    assert stream_port(None) == ""


@pytest.mark.unit
@pytest.mark.parametrize(
    "settings, expected",
    [
        ({"source": "NTRIP Server", "host": "caster.example"}, True),
        ({"source": "NTRIP Server", "host": "  "}, False),
        ({"source": "Serial Port", "serial_port": "/dev/ttyUSB0"}, True),
        ({"source": "Serial Port", "serial_port": ""}, False),
        ({"source": "RINEX File", "file_path": "data.obs"}, False),
        (None, False),
    ],
)
def test_realtime_configuration_requires_source_specific_address(settings, expected) -> None:
    assert is_realtime_stream_configured(settings) is expected


@pytest.mark.unit
@pytest.mark.parametrize("source", ["RINEX File", "File"])
def test_file_configuration_accepts_both_compatible_source_names(source: str) -> None:
    assert is_file_stream_configured({"source": source, "file_path": "data.obs"}) is True
    assert is_file_stream_configured({"source": source, "file_path": "  "}) is False


@pytest.mark.unit
def test_file_configuration_rejects_live_or_missing_settings() -> None:
    assert is_file_stream_configured({"source": "NTRIP Server", "file_path": "data.obs"}) is False
    assert is_file_stream_configured(None) is False
