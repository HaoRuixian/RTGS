from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.data_models import EpochObservation, SatelliteState, SignalData
from core.rt_ntrip_rinex import RTNtripRinexStation, _normalize_ntrip_user_agent, load_rt_rinex_config


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


class _FakeHandler:
    def __init__(self, mapping, approx_position=None):
        self._mapping = mapping
        self.last_station_coords = approx_position

    def process_message(self, msg):
        return self._mapping.get(msg)


def test_normalize_ntrip_user_agent_prefixes_non_ntrip_values():
    assert _normalize_ntrip_user_agent("RTGS RTRINEX/0.1") == "NTRIP RTGS RTRINEX/0.1"
    assert _normalize_ntrip_user_agent("NTRIP Python/GNSS-IR") == "NTRIP Python/GNSS-IR"
    assert _normalize_ntrip_user_agent("") == "NTRIP RTGS RTRINEX/0.1"


def test_load_rt_rinex_config_merges_defaults_and_resolves_relative_paths(tmp_path):
    config_path = tmp_path / "rt_config.yaml"
    config_path.write_text(
        """
defaults:
  ntrip:
    port: 2201
    reconnect_delay_seconds: 7
  rinex:
    sample_interval_seconds: auto
    split_enabled: false
    split_period_seconds: 3600
    daily_merge_min_interval_seconds: 15
    country_code: USA
    receiver_type: DEFAULT_RX
    antenna_type: DEFAULT_ANT_TYPE
stations:
  - name: BUAA01
    ntrip:
      host: caster.example.com
      mountpoint: BUAA01
      user: demo
      password: secret
    rinex:
      marker_name: BUAA01
      station_code: BUAA
      receiver_number: "01"
      approx_position: [1.0, 2.0, 3.0]
      antenna_model: HXCCGX611A
      antenna_type: HXCM
  - name: NBFH
    enabled: false
    ntrip:
      host: caster.example.com
      mountpoint: NBFH
    rinex:
      output_directory: output/nbfh
      station_code: NBFH
      receiver_number: "02"
      auto_detect_obs_types: false
      sys_obs_types:
        G: [C1C, L1C]
""",
        encoding="utf-8",
    )

    config = load_rt_rinex_config(config_path)

    assert config.config_path == config_path.resolve()
    assert len(config.stations) == 2

    first = config.stations[0]
    assert first.name == "BUAA01"
    assert first.enabled is True
    assert first.ntrip.port == 2201
    assert first.ntrip.reconnect_delay_seconds == 7
    assert first.rinex.output_directory == Path("/mnt/20t/RT_RINEX")
    assert first.rinex.sample_interval_seconds is None
    assert first.rinex.split_enabled is False
    assert first.rinex.daily_merge_min_interval_seconds == 15
    assert first.rinex.country_code == "USA"
    assert first.rinex.receiver_type == "DEFAULT_RX"
    assert first.rinex.antenna_model == "HXCCGX611A"
    assert first.rinex.antenna_type == "HXCM"
    assert first.rinex.approx_position == [1.0, 2.0, 3.0]

    second = config.stations[1]
    assert second.enabled is False
    assert second.rinex.output_directory == (tmp_path / "output/nbfh").resolve()
    assert second.rinex.auto_detect_obs_types is False
    assert second.rinex.sys_obs_types == {"G": ["C1C", "L1C"]}


def test_rt_station_process_reader_writes_rotated_rinex_files(tmp_path):
    output_dir = tmp_path / "rinex"

    epoch0 = datetime(2026, 3, 26, 0, 0, 0, tzinfo=timezone.utc)
    epoch1 = datetime(2026, 3, 26, 0, 0, 1, tzinfo=timezone.utc)
    epoch2 = datetime(2026, 3, 26, 0, 1, 0, tzinfo=timezone.utc)
    mapping = {
        "g0": _epoch(epoch0, {"G01": {"1C": _signal("1C", 21000000.0, 110000.0, 45.0, -1234.5)}}),
        "r0": _epoch(epoch0, {"R03": {"1C": _signal("1C", 22000000.0, 120000.0, 42.0, -1134.5)}}),
        "g1": _epoch(epoch1, {"G01": {"1C": _signal("1C", 21000001.0, 110001.0, 46.0, -1233.5)}}),
        "g2": _epoch(epoch2, {"G02": {"1C": _signal("1C", 23000000.0, 130000.0, 44.0, -1034.5)}}),
    }
    messages = [(b"", "g0"), (b"", "r0"), (b"", "g1"), (b"", "g2")]

    config_path = tmp_path / "tool.yaml"
    config_path.write_text(
        """
stations:
  - name: TEST01
    ntrip:
      host: caster.example.com
      mountpoint: TEST01
    rinex:
      output_directory: rinex
      marker_name: TEST01
      station_code: TEST
      receiver_number: "01"
      country_code: CHN
      sample_interval_seconds: auto
      split_enabled: true
      split_period_seconds: 60
      antenna_model: HXCCGX611A
      antenna_type: HXCM
      approx_position: [1.0, 2.0, 3.0]
      receiver_type: TestReceiver
""",
        encoding="utf-8",
    )

    station = load_rt_rinex_config(config_path).stations[0]
    logs: list[str] = []
    worker = RTNtripRinexStation(
        station,
        log_fn=logs.append,
        handler_factory=lambda: _FakeHandler(mapping, approx_position=[11.0, 22.0, 33.0]),
    )

    worker.process_reader(messages)

    files = sorted((output_dir / "TEST01" / "2026" / "2026085").glob("*.rnx"))
    assert [path.name for path in files] == [
        "TEST01CHN_R_20260850000_01M_01S_MO.rnx",
        "TEST01CHN_R_20260850001_01M_01S_MO.rnx",
    ]

    first_text = files[0].read_text(encoding="utf-8")
    second_text = files[1].read_text(encoding="utf-8")

    assert "MARKER NAME" in first_text
    assert "TEST01" in first_text
    assert "APPROX POSITION XYZ" in first_text
    assert "11.0000" in first_text
    assert "22.0000" in first_text
    assert "33.0000" in first_text
    assert "HXCCGX611A" in first_text
    assert "HXCM" in first_text
    assert "> 2026 03 26 00 00 18.0000000  0  2" in first_text
    assert "G01" in first_text
    assert "R03" in first_text
    assert "> 2026 03 26 00 00 19.0000000  0  1" in first_text
    assert "> 2026 03 26 00 01 18.0000000  0  1" in second_text
    assert "G02" in second_text

    assert any("Opened TEST01CHN_R_20260850000_01M_01S_MO.rnx" in line for line in logs)
    assert any("Opened TEST01CHN_R_20260850001_01M_01S_MO.rnx" in line for line in logs)
    assert any("Detected sample interval: 1s" in line for line in logs)


def test_rt_station_process_reader_keeps_single_file_when_split_disabled(tmp_path):
    output_dir = tmp_path / "rinex"

    epoch0 = datetime(2026, 3, 26, 0, 0, 0, tzinfo=timezone.utc)
    epoch1 = datetime(2026, 3, 26, 0, 1, 0, tzinfo=timezone.utc)
    mapping = {
        "g0": _epoch(epoch0, {"G01": {"1C": _signal("1C", 21000000.0, 110000.0, 45.0)}}),
        "g1": _epoch(epoch1, {"G02": {"1C": _signal("1C", 23000000.0, 130000.0, 44.0)}}),
    }
    messages = [(b"", "g0"), (b"", "g1")]

    config_path = tmp_path / "tool.yaml"
    config_path.write_text(
        """
stations:
  - name: TEST02
    ntrip:
      host: caster.example.com
      mountpoint: TEST02
    rinex:
      output_directory: rinex
      marker_name: TEST02
      station_code: TEST
      receiver_number: "02"
      country_code: CHN
      sample_interval_seconds: auto
      split_enabled: false
      antenna_model: HXCCGX611A
      antenna_type: HXCM
      receiver_type: TestReceiver
""",
        encoding="utf-8",
    )

    station = load_rt_rinex_config(config_path).stations[0]
    worker = RTNtripRinexStation(
        station,
        log_fn=lambda *_args, **_kwargs: None,
        handler_factory=lambda: _FakeHandler(mapping),
    )

    worker.process_reader(messages)

    files = sorted((output_dir / "TEST02" / "2026").glob("*.rnx"))
    assert len(files) == 1

    text = files[0].read_text(encoding="utf-8")
    assert "> 2026 03 26 00 00 18.0000000  0  1" in text
    assert "> 2026 03 26 00 01 18.0000000  0  1" in text
    assert "HXCCGX611A" in text and "HXCM" in text


def test_rt_station_process_reader_merges_completed_split_day_to_daily(tmp_path):
    output_root = tmp_path / "rinex"

    epoch0 = datetime(2026, 3, 26, 0, 0, 12, tzinfo=timezone.utc)
    epoch1 = datetime(2026, 3, 26, 0, 0, 13, tzinfo=timezone.utc)
    epoch2 = datetime(2026, 3, 26, 12, 0, 12, tzinfo=timezone.utc)
    mapping = {
        "g0": _epoch(epoch0, {"G01": {"1C": _signal("1C", 21000000.0, 110000.0, 45.0)}}),
        "g1": _epoch(epoch1, {"G01": {"1C": _signal("1C", 21000001.0, 110001.0, 46.0)}}),
        "g2": _epoch(epoch2, {"G02": {"1C": _signal("1C", 23000000.0, 130000.0, 44.0)}}),
    }
    messages = [(b"", "g0"), (b"", "g1"), (b"", "g2")]

    config_path = tmp_path / "tool.yaml"
    config_path.write_text(
        """
stations:
  - name: TEST03
    ntrip:
      host: caster.example.com
      mountpoint: TEST03
    rinex:
      output_directory: rinex
      marker_name: TEST03
      station_code: TEST
      receiver_number: "03"
      country_code: CHN
      sample_interval_seconds: auto
      split_enabled: true
      split_period_seconds: 43200
      daily_merge_min_interval_seconds: 15
      antenna_model: HXCCGX611A
      antenna_type: HXCM
      receiver_type: TestReceiver
""",
        encoding="utf-8",
    )

    station = load_rt_rinex_config(config_path).stations[0]
    logs: list[str] = []
    worker = RTNtripRinexStation(
        station,
        log_fn=logs.append,
        handler_factory=lambda: _FakeHandler(mapping, approx_position=[11.0, 22.0, 33.0]),
    )

    worker.process_reader(messages)

    split_dir = output_root / "TEST03" / "2026" / "2026085"
    yearly_dir = output_root / "TEST03" / "2026"
    split_files = sorted(split_dir.glob("*.rnx"))
    daily_files = sorted(yearly_dir.glob("*_01D_15S_MO.rnx"))

    assert len(split_files) == 2
    assert len(daily_files) == 1

    daily_text = daily_files[0].read_text(encoding="utf-8")
    assert "HXCCGX611A" in daily_text
    assert "HXCM" in daily_text
    assert "INTERVAL" in daily_text and "15.000" in daily_text
    assert "> 2026 03 26 00 00 30.0000000  0  1" in daily_text
    assert "> 2026 03 26 12 00 30.0000000  0  1" in daily_text
    assert any("Merged 2 split file(s) into" in line for line in logs)


def test_rt_station_hourly_split_uses_period_boundary_in_configured_time_system(tmp_path):
    output_root = tmp_path / "rinex"

    epoch0 = datetime(2026, 3, 26, 5, 52, 0, tzinfo=timezone.utc)
    epoch1 = datetime(2026, 3, 26, 5, 52, 1, tzinfo=timezone.utc)
    epoch2 = datetime(2026, 3, 26, 6, 0, 0, tzinfo=timezone.utc)
    mapping = {
        "g0": _epoch(epoch0, {"G01": {"1C": _signal("1C", 21000000.0, 110000.0, 45.0)}}),
        "g1": _epoch(epoch1, {"G01": {"1C": _signal("1C", 21000001.0, 110001.0, 46.0)}}),
        "g2": _epoch(epoch2, {"G02": {"1C": _signal("1C", 23000000.0, 130000.0, 44.0)}}),
    }
    messages = [(b"", "g0"), (b"", "g1"), (b"", "g2")]

    config_path = tmp_path / "tool.yaml"
    config_path.write_text(
        """
stations:
  - name: TEST04
    ntrip:
      host: caster.example.com
      mountpoint: TEST04
    rinex:
      output_directory: rinex
      marker_name: TEST04
      station_code: TEST
      receiver_number: "04"
      country_code: CHN
      sample_interval_seconds: auto
      split_enabled: true
      split_period_seconds: 3600
      time_system: UTC
      antenna_model: HXCCGX611A
      antenna_type: HXCM
      receiver_type: TestReceiver
""",
        encoding="utf-8",
    )

    station = load_rt_rinex_config(config_path).stations[0]
    worker = RTNtripRinexStation(
        station,
        log_fn=lambda *_args, **_kwargs: None,
        handler_factory=lambda: _FakeHandler(mapping),
    )

    worker.process_reader(messages)

    files = sorted((output_root / "TEST04" / "2026" / "2026085").glob("*.rnx"))
    assert [path.name for path in files] == [
        "TEST04CHN_R_20260850500_01H_01S_MO.rnx",
        "TEST04CHN_R_20260850600_01H_01S_MO.rnx",
    ]
