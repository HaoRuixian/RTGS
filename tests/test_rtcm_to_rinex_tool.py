from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.data_models import EpochObservation, SatelliteState, SignalData
from core.gnss_time import GNSSTime
from core.mixed_gnss_reader import MixedGNSSReader
from core.rtcm_handler import RTCMHandler
from utils import rtcm_to_rinex


def _signal(signal_id: str, pseudorange: float, phase: float, snr: float, doppler: float = 0.0) -> SignalData:
    return SignalData(
        signal_id=signal_id,
        pseudorange=pseudorange,
        phase=phase,
        snr=snr,
        lock_time=0,
        half_cycle=0,
        doppler=doppler,
    )


def _epoch(epoch_time: datetime, satellite_defs: dict[str, dict[str, SignalData]]) -> EpochObservation:
    epoch = EpochObservation(gps_time=0.0, utc_datetime=epoch_time)
    for sat_id, signals in satellite_defs.items():
        sat_state = SatelliteState(sys_id=sat_id[0], prn=int(sat_id[1:]))
        sat_state.signals.update(signals)
        epoch.satellites[sat_id] = sat_state
    return epoch


class _FakeReader:
    def __init__(self, _stream, messages):
        self._messages = list(messages)

    def __iter__(self):
        return iter(self._messages)


class _FakeHandler:
    def __init__(self, mapping, approx_position=None):
        self._mapping = mapping
        self.last_station_coords = approx_position

    def process_message(self, msg):
        return self._mapping.get(msg)


def _reader_factory(messages):
    return lambda stream: _FakeReader(stream, messages)


def _handler_factory(mapping, approx_position=None):
    return lambda: _FakeHandler(mapping, approx_position)


def test_iter_merged_epochs_merges_same_timestamp_messages():
    epoch0 = datetime(2026, 3, 26, 0, 0, 0, tzinfo=timezone.utc)
    epoch1 = epoch0 + timedelta(seconds=30)
    mapping = {
        "g0": _epoch(epoch0, {"G01": {"1C": _signal("1C", 21000000.0, 110000.0, 45.0)}}),
        "r0": _epoch(epoch0, {"R03": {"1C": _signal("1C", 22000000.0, 120000.0, 42.0)}}),
        "g1": _epoch(epoch1, {"G02": {"1C": _signal("1C", 23000000.0, 130000.0, 44.0)}}),
    }

    epochs = list(
        rtcm_to_rinex._iter_merged_epochs(
            [(b"", "g0"), (b"", "r0"), (b"", "g1")],
            _FakeHandler(mapping),
        )
    )

    assert len(epochs) == 2
    assert set(epochs[0].satellites.keys()) == {"G01", "R03"}
    assert set(epochs[1].satellites.keys()) == {"G02"}


def test_scan_rtcm_file_detects_obs_types_and_interval(tmp_path):
    input_path = tmp_path / "sample.rtcm"
    input_path.write_bytes(b"rtcm")

    epoch0 = datetime(2026, 3, 26, 0, 0, 0, tzinfo=timezone.utc)
    epoch1 = epoch0 + timedelta(seconds=30)
    mapping = {
        "g0": _epoch(epoch0, {"G01": {"1C": _signal("1C", 21000000.0, 110000.0, 45.0)}}),
        "r0": _epoch(epoch0, {"R03": {"2P": _signal("2P", 22000000.0, 120000.0, 42.0)}}),
        "g1": _epoch(epoch1, {"G02": {"1C": _signal("1C", 23000000.0, 130000.0, 44.0)}}),
    }
    messages = [(b"", "g0"), (b"", "r0"), (b"", "g1")]

    summary = rtcm_to_rinex.scan_rtcm_file(
        input_path,
        reader_factory=_reader_factory(messages),
        handler_factory=_handler_factory(mapping, approx_position=[1.0, 2.0, 3.0]),
    )

    assert summary.epoch_count == 2
    assert summary.interval_seconds == 30.0
    assert summary.approx_position == [1.0, 2.0, 3.0]
    assert summary.sys_obs_types["G"] == ["C1C", "L1C", "D1C", "S1C"]
    assert summary.sys_obs_types["R"] == ["C2P", "L2P", "D2P", "S2P"]


def test_main_converts_rtcm_file_to_rinex_with_fake_pipeline(tmp_path, monkeypatch):
    input_path = tmp_path / "sample.rtcm"
    input_path.write_bytes(b"rtcm")
    output_dir = tmp_path / "out"

    epoch0 = datetime(2026, 3, 26, 0, 0, 0, tzinfo=timezone.utc)
    epoch1 = epoch0 + timedelta(seconds=30)
    mapping = {
        "g0": _epoch(epoch0, {"G01": {"1C": _signal("1C", 21000000.0, 110000.0, 45.0, -1234.5)}}),
        "r0": _epoch(epoch0, {"R03": {"1C": _signal("1C", 22000000.0, 120000.0, 42.0, -1134.5)}}),
        "g1": _epoch(epoch1, {"G02": {"1C": _signal("1C", 23000000.0, 130000.0, 44.0, -1034.5)}}),
    }
    messages = [(b"", "g0"), (b"", "r0"), (b"", "g1")]

    monkeypatch.setattr(rtcm_to_rinex, "MixedGNSSReader", _reader_factory(messages))
    monkeypatch.setattr(rtcm_to_rinex, "RTCMHandler", _handler_factory(mapping, approx_position=[11.0, 22.0, 33.0]))

    exit_code = rtcm_to_rinex.main(
        [
            str(input_path),
            "-o",
            str(output_dir),
            "--station-code",
            "TEST",
            "--country-code",
            "CHN",
            "--receiver-number",
            "01",
        ]
    )

    assert exit_code == 0

    output_files = list(output_dir.glob("*.rnx"))
    assert len(output_files) == 1

    text = output_files[0].read_text(encoding="utf-8")
    assert "RINEX VERSION / TYPE" in text
    assert "SYS / # / OBS TYPES" in text
    assert "APPROX POSITION XYZ" in text
    assert "> 2026 03 26 00 00 18.0000000  0  2" in text
    assert "G01" in text
    assert "R03" in text
    assert "> 2026 03 26 00 00 48.0000000  0  1" in text
    assert "G02" in text


def test_infer_reference_utc_from_input_filename():
    inferred = rtcm_to_rinex._infer_reference_utc(Path("20251025.dat"))

    assert inferred == datetime(2025, 10, 25, tzinfo=timezone.utc)


def test_mixed_gnss_reader_ignores_truncated_tail_frame():
    stream = (
        b"#HEADER\r\n"
        + bytes([0xD3, 0x00, 0x03, 0x01, 0x02])
    )

    reader = MixedGNSSReader(__import__("io").BytesIO(stream))

    assert list(reader) == []


def test_mixed_gnss_reader_read_bytes_allows_zero_length():
    reader = MixedGNSSReader(__import__("io").BytesIO(b"abc"))

    assert reader._read_bytes(0) == b""


def test_scan_rtcm_file_uses_reference_date_in_filename(tmp_path, monkeypatch):
    input_path = tmp_path / "20251025.dat"
    input_path.write_bytes(b"")
    captured: list[datetime | None] = []

    class _CapturingHandler:
        def __init__(self, reference_utc=None):
            captured.append(reference_utc)
            self.last_station_coords = None

        def process_message(self, msg):
            return None

    monkeypatch.setattr(rtcm_to_rinex, "RTCMHandler", _CapturingHandler)

    summary = rtcm_to_rinex.scan_rtcm_file(
        input_path,
        reader_factory=lambda stream: [],
    )

    assert summary.epoch_count == 0
    assert captured == [datetime(2025, 10, 25, tzinfo=timezone.utc)]


def test_rtcm_handler_resolves_week_rollover_near_gps_boundary():
    handler = RTCMHandler(reference_utc=datetime(2025, 10, 25, tzinfo=timezone.utc))
    handler.last_utc_by_system["G"] = datetime(2025, 10, 25, 23, 59, 42, tzinfo=timezone.utc)

    resolved_week = handler._resolve_gps_week("G", 15.0, 2389)
    resolved_utc = GNSSTime.gps_to_utc_datetime(resolved_week, 15.0)

    assert resolved_utc == datetime(2025, 10, 25, 23, 59, 57, tzinfo=timezone.utc)


def test_utc_to_gps_file_datetime_adds_gps_offset():
    utc_epoch = datetime(2025, 10, 25, 0, 0, 12)

    assert rtcm_to_rinex._utc_to_gps_file_datetime(utc_epoch) == datetime(2025, 10, 25, 0, 0, 30)
