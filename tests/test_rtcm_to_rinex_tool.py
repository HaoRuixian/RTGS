from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.data_models import EpochObservation, SatelliteState, SignalData
from core.gnss_time import GNSSTime
from core.mixed_gnss_reader import MixedGNSSReader
from core.rinex3_writer import RINEX3Writer
from core.rtcm_handler import RTCMHandler
from utils import rtcm_to_rinex
from utils.rtcm_to_rinex import ScanSummary


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


class _FakeRTCMMessage:
    def __init__(self, identity: str, **attrs):
        self.identity = identity
        for key, value in attrs.items():
            setattr(self, key, value)


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


def test_scan_rtcm_file_ignores_unreasonable_interval_outlier(tmp_path):
    input_path = tmp_path / "sample.rtcm"
    input_path.write_bytes(b"rtcm")

    epoch0 = datetime(2026, 3, 26, 0, 0, 0, tzinfo=timezone.utc)
    epoch1 = epoch0 + timedelta(seconds=1)
    epoch2 = epoch1 + timedelta(seconds=5940)
    epoch3 = epoch2 + timedelta(seconds=1)
    mapping = {
        "m0": _epoch(epoch0, {"G01": {"1C": _signal("1C", 21000000.0, 110000.0, 45.0)}}),
        "m1": _epoch(epoch1, {"G01": {"1C": _signal("1C", 21000001.0, 110001.0, 45.0)}}),
        "m2": _epoch(epoch2, {"G01": {"1C": _signal("1C", 21000002.0, 110002.0, 45.0)}}),
        "m3": _epoch(epoch3, {"G01": {"1C": _signal("1C", 21000003.0, 110003.0, 45.0)}}),
    }
    messages = [(b"", "m0"), (b"", "m1"), (b"", "m2"), (b"", "m3")]

    summary = rtcm_to_rinex.scan_rtcm_file(
        input_path,
        reader_factory=_reader_factory(messages),
        handler_factory=_handler_factory(mapping),
    )

    assert summary.interval_seconds == 1.0


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


def test_infer_reference_utc_from_bridge_style_filename():
    inferred = rtcm_to_rinex._infer_reference_utc(Path("jz_con_11060_210320.log"))

    assert inferred == datetime(2021, 3, 20, tzinfo=timezone.utc)


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


def test_rtcm_handler_prefers_latest_non_glonass_day_anchor():
    handler = RTCMHandler(reference_utc=datetime(2025, 10, 25, tzinfo=timezone.utc))
    handler.last_utc_by_system["R"] = datetime(2025, 10, 26, 0, 0, 12, tzinfo=timezone.utc)
    handler.last_utc_by_system["G"] = datetime(2025, 10, 25, 23, 59, 42, tzinfo=timezone.utc)

    assert handler._reference_utc_for_glonass_day() == datetime(2025, 10, 25, 23, 59, 42, tzinfo=timezone.utc)


def test_rtcm_handler_glonass_uses_utc_day_index_near_gps_midnight():
    anchor = datetime(2021, 3, 19, 23, 59, 42, tzinfo=timezone.utc)

    assert RTCMHandler._utc_day_of_week(anchor) == 5


def test_rtcm_handler_decodes_msm5_observations_with_scaled_doppler():
    handler = RTCMHandler(
        reference_utc=datetime(2026, 3, 26, tzinfo=timezone.utc),
        compute_geometry=False,
    )
    msg = _FakeRTCMMessage(
        "1075",
        DF004=345600000,
        NSat=1,
        NCell=1,
        PRN_01=3,
        DF397_01=70,
        ExtSatInfo_01=0,
        DF398_01=0.25,
        DF399_01=100,
        CELLPRN_01=3,
        CELLSIG_01="1C",
        DF400_01=0.0001,
        DF401_01=0.00012,
        DF402_01=7,
        DF420_01=1,
        DF403_01=45,
        DF404_01=0.25,
    )

    epoch = handler.process_message(msg)
    sig = epoch.satellites["G03"].signals["1C"]

    c = 299792458.0
    range_ms = c / 1000.0
    rough_range = (70.0 + 0.25) * range_ms
    l1_hz = 1575.42e6
    assert sig.pseudorange == pytest.approx(rough_range + 0.0001 * range_ms)
    assert sig.phase == pytest.approx((rough_range + 0.00012 * range_ms) * l1_hz / c)
    assert sig.snr == 45.0
    assert sig.lock_time == 7
    assert sig.half_cycle == 1
    assert sig.doppler == pytest.approx(-(100.0 + 0.25) * l1_hz / c)


def test_rtcm_handler_decodes_msm6_extended_fields_without_doppler():
    handler = RTCMHandler(
        reference_utc=datetime(2026, 3, 26, tzinfo=timezone.utc),
        compute_geometry=False,
    )
    msg = _FakeRTCMMessage(
        "1126",
        DF427=345600000,
        NSat=1,
        NCell=1,
        PRN_01=7,
        DF397_01=71,
        DF398_01=0.5,
        CELLPRN_01=7,
        CELLSIG_01="2I",
        DF405_01=0.00002,
        DF406_01=0.00003,
        DF407_01=120,
        DF420_01=0,
        DF408_01=42.5,
    )

    epoch = handler.process_message(msg)
    sig = epoch.satellites["C07"].signals["2I"]

    c = 299792458.0
    range_ms = c / 1000.0
    rough_range = (71.0 + 0.5) * range_ms
    b1_hz = 1561.098e6
    assert sig.pseudorange == pytest.approx(rough_range + 0.00002 * range_ms)
    assert sig.phase == pytest.approx((rough_range + 0.00003 * range_ms) * b1_hz / c)
    assert sig.snr == 42.5
    assert sig.lock_time == 120
    assert sig.doppler == 0.0


def test_rtcm_handler_uses_glonass_msm5_frequency_channel():
    handler = RTCMHandler(
        reference_utc=datetime(2026, 3, 26, tzinfo=timezone.utc),
        compute_geometry=False,
    )
    msg = _FakeRTCMMessage(
        "1085",
        DF034=43200000,
        NSat=1,
        NCell=1,
        PRN_01=8,
        DF397_01=70,
        DF419_01=10,
        DF398_01=0.0,
        DF399_01=-250,
        CELLPRN_01=8,
        CELLSIG_01="1C",
        DF400_01=0.00002,
        DF401_01=0.00003,
        DF402_01=4,
        DF420_01=0,
        DF403_01=39,
        DF404_01=0.5,
    )

    epoch = handler.process_message(msg)
    sig = epoch.satellites["R08"].signals["1C"]

    c = 299792458.0
    glo_l1_hz = 1602.0e6 + 0.5625e6 * 3
    assert sig.doppler == pytest.approx(-(-250.0 + 0.5) * glo_l1_hz / c)


def test_utc_to_gps_file_datetime_adds_gps_offset():
    utc_epoch = datetime(2025, 10, 25, 0, 0, 12)

    assert rtcm_to_rinex._utc_to_gps_file_datetime(utc_epoch) == datetime(2025, 10, 25, 0, 0, 30)


def test_select_aligned_epoch_time_uses_gps_time_scale():
    aligned = rtcm_to_rinex._select_aligned_epoch_time(
        datetime(2026, 3, 26, 0, 0, 12),
        5.0,
        alignment_time_system="GPS",
        return_time_system="GPS",
    )
    not_aligned = rtcm_to_rinex._select_aligned_epoch_time(
        datetime(2026, 3, 26, 0, 0, 10),
        5.0,
        alignment_time_system="GPS",
        return_time_system="GPS",
    )

    assert aligned == datetime(2026, 3, 26, 0, 0, 30)
    assert not_aligned is None


def test_rinex_writer_uses_header_interval_override():
    writer = RINEX3Writer("dummy.rnx", interval="01S", header_interval_seconds=0.5)

    assert writer._parse_interval_seconds() == 0.5


def test_convert_rtcm_file_to_rinex_decimates_to_requested_interval(tmp_path):
    input_path = tmp_path / "sample.rtcm"
    input_path.write_bytes(b"rtcm")
    output_dir = tmp_path / "out"

    epoch0 = datetime(2026, 3, 26, 0, 0, 0, tzinfo=timezone.utc)
    epochs = [
        _epoch(epoch0 + timedelta(seconds=offset), {"G01": {"1C": _signal("1C", 21000000.0 + offset, 110000.0, 45.0)}})
        for offset in (12, 17, 27, 32)
    ]
    mapping = {f"m{idx}": epoch for idx, epoch in enumerate(epochs)}
    messages = [(b"", key) for key in mapping.keys()]

    summary = ScanSummary(
        input_path=input_path,
        epoch_count=len(epochs),
        first_epoch=epoch0.replace(tzinfo=None),
        last_epoch=(epoch0 + timedelta(seconds=15)).replace(tzinfo=None),
        interval_seconds=5.0,
        sys_obs_types={"G": ["C1C", "L1C", "D1C", "S1C"]},
        approx_position=[11.0, 22.0, 33.0],
    )

    result = rtcm_to_rinex.convert_rtcm_file_to_rinex(
        input_path,
        output_path=output_dir,
        station_code="TEST",
        receiver_number="00",
        country_code="CHN",
        interval_seconds=15.0,
        summary=summary,
        reader_factory=_reader_factory(messages),
        handler_factory=_handler_factory(mapping, approx_position=[11.0, 22.0, 33.0]),
    )

    assert result.output_path.exists()
    assert result.written_epoch_count == 2

    text = result.output_path.read_text(encoding="utf-8")
    assert text.count("\n> ") == 2
    assert "> 2026 03 26 00 00 30.0000000  0  1" in text
    assert "> 2026 03 26 00 00 45.0000000  0  1" in text


def test_build_arg_parser_help_contains_simple_examples(monkeypatch):
    monkeypatch.setattr(rtcm_to_rinex.sys, "argv", ["rtcm_to_rinex"])
    help_text = rtcm_to_rinex.build_arg_parser().format_help()

    assert "usage: rtcm_to_rinex" in help_text
    assert "Examples:" in help_text
    assert "rtcm_to_rinex sample.rtcm3 -o output" in help_text
    assert "-d YYYY-MM-DD" in help_text
    assert "-s SITE" in help_text
    assert "--station-code" not in help_text


def test_build_arg_parser_accepts_new_and_legacy_option_names():
    original_argv = list(rtcm_to_rinex.sys.argv)
    rtcm_to_rinex.sys.argv = ["rtcm_to_rinex"]
    try:
        parser = rtcm_to_rinex.build_arg_parser()
    finally:
        rtcm_to_rinex.sys.argv = original_argv

    new_args = parser.parse_args(
        [
            "sample.rtcm3",
            "-s",
            "F9P0",
            "-n",
            "F9P",
            "-r",
            "F9P",
            "-a",
            "HXCM",
            "-i",
            "15",
            "-p",
            "01D",
            "-d",
            "2025-10-25",
            "--xyz",
            "1",
            "2",
            "3",
            "--num",
            "01",
            "--country",
            "CHN",
        ]
    )

    legacy_args = parser.parse_args(
        [
            "sample.rtcm3",
            "--station-code",
            "F9P0",
            "--marker-name",
            "F9P",
            "--receiver-type",
            "F9P",
            "--antenna-type",
            "HXCM",
            "--interval",
            "15",
            "--period",
            "01D",
            "--reference-date",
            "2025-10-25",
            "--approx-position",
            "1",
            "2",
            "3",
            "--receiver-number",
            "01",
            "--country-code",
            "CHN",
        ]
    )

    assert new_args.station_code == legacy_args.station_code == "F9P0"
    assert new_args.marker_name == legacy_args.marker_name == "F9P"
    assert new_args.receiver_type == legacy_args.receiver_type == "F9P"
    assert new_args.antenna_type == legacy_args.antenna_type == "HXCM"
    assert new_args.interval == legacy_args.interval == 15.0
    assert new_args.period == legacy_args.period == "01D"
    assert new_args.reference_date == legacy_args.reference_date == "2025-10-25"
    assert new_args.approx_position == legacy_args.approx_position == [1.0, 2.0, 3.0]
    assert new_args.receiver_number == legacy_args.receiver_number == "01"
    assert new_args.country_code == legacy_args.country_code == "CHN"
