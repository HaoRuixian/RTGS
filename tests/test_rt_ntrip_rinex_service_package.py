from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from utils.rt_ntrip_rinex_service.config_store import ConfigStore
from utils.rt_ntrip_rinex_service.data_models import EpochObservation, SatelliteState, SignalData
from utils.rt_ntrip_rinex_service.manager import LogBuffer, RuntimeManager
from utils.rt_ntrip_rinex_service.merge_rinex_daily import merge_rinex_daily_files
from utils.rt_ntrip_rinex_service.rinex3_writer import RINEX3Writer
from utils.rt_ntrip_rinex_service.service import PrefetchedSocketStream, RTNtripRinexStation, load_rt_rinex_config


def _signal(signal_id: str, pseudorange: float = 21000000.0) -> SignalData:
    return SignalData(
        signal_id=signal_id,
        pseudorange=pseudorange,
        phase=110000.0,
        snr=45.0,
        lock_time=0,
        half_cycle=0,
        doppler=-1234.5,
    )


def _epoch(epoch_time: datetime, satellite_defs: dict[str, dict[str, SignalData]]) -> EpochObservation:
    epoch = EpochObservation(gps_time=0.0, utc_datetime=epoch_time)
    for sat_id, signals in satellite_defs.items():
        sat_state = SatelliteState(sys_id=sat_id[0], prn=int(sat_id[1:]))
        sat_state.signals.update(signals)
        epoch.satellites[sat_id] = sat_state
    return epoch


def _satellite(signal_id: str, pseudorange: float) -> SatelliteState:
    sat_state = SatelliteState(sys_id="G", prn=1)
    sat_state.signals[signal_id] = _signal(signal_id, pseudorange)
    return sat_state


class _FakeHandler:
    def __init__(self, mapping):
        self._mapping = mapping
        self.last_station_coords = [11.0, 22.0, 33.0]
        self.last_antenna_descriptor = ""
        self.last_antenna_serial_number = ""
        self.last_receiver_type_descriptor = ""
        self.last_receiver_firmware_version = ""
        self.last_receiver_serial_number = ""

    def process_message(self, msg):
        return self._mapping.get(msg)


class _MetadataAfterOpenHandler(_FakeHandler):
    def process_message(self, msg):
        if msg == "desc":
            self.last_receiver_type_descriptor = "SEPT MOSAIC-X5"
            self.last_receiver_firmware_version = "4.14.4"
            self.last_receiver_serial_number = "4014259"
            self.last_antenna_descriptor = "LEIAR25.R4 NONE"
            self.last_antenna_serial_number = "725235"
            return None
        return super().process_message(msg)


class _FragmentedSocket:
    def __init__(self, payload: bytes, max_chunk: int = 1):
        self._payload = payload
        self._max_chunk = max_chunk
        self._offset = 0
        self.closed = False

    def recv(self, size: int) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        chunk_size = min(size, self._max_chunk, len(self._payload) - self._offset)
        chunk = self._payload[self._offset : self._offset + chunk_size]
        self._offset += chunk_size
        return chunk

    def close(self) -> None:
        self.closed = True


def _epoch_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith(">"):
            current = [line]
            blocks.append(current)
        elif current is not None:
            current.append(line)
    return blocks


def test_prefetched_socket_stream_read_accumulates_short_socket_reads():
    stream = PrefetchedSocketStream(_FragmentedSocket(b"cdef", max_chunk=1), b"ab")

    assert stream.read(6) == b"abcdef"


def test_detected_observation_types_are_persisted_and_reused(tmp_path):
    config_path = tmp_path / "service.yaml"
    config_path.write_text(
        """
stations:
  - name: TEST11
    ntrip:
      host: caster.example.com
      mountpoint: TEST11
    rinex:
      output_directory: rinex
      marker_name: TEST11
      station_code: TEST
      receiver_number: "11"
      country_code: CHN
      sample_interval_seconds: auto
      split_enabled: false
      auto_detect_obs_types: true
      receiver_type: TestReceiver
      antenna_type: TestAntenna
""",
        encoding="utf-8",
    )
    store = ConfigStore(config_path)
    epoch0 = datetime(2026, 3, 26, 0, 0, 0, tzinfo=timezone.utc)
    epoch1 = datetime(2026, 3, 26, 0, 0, 1, tzinfo=timezone.utc)
    epoch2 = datetime(2026, 3, 26, 0, 0, 2, tzinfo=timezone.utc)
    epoch3 = datetime(2026, 3, 26, 0, 0, 3, tzinfo=timezone.utc)
    mapping = {
        "g0": _epoch(epoch0, {"G01": {"1C": _signal("1C")}}),
        "g1": _epoch(epoch1, {"G01": {"1C": _signal("1C", 21000001.0)}}),
        "g2": _epoch(epoch2, {"G01": {"1C": _signal("1C", 21000002.0)}}),
        "g3": _epoch(epoch3, {"G01": {"5X": _signal("5X", 23000000.0)}}),
    }
    station = load_rt_rinex_config(config_path).stations[0]
    logs: list[str] = []
    worker = RTNtripRinexStation(
        station,
        log_fn=logs.append,
        handler_factory=lambda: _FakeHandler(mapping),
        obs_types_persist_fn=store.persist_obs_types,
        approx_position_persist_fn=store.persist_approx_position,
    )

    worker.process_reader([(b"", "g0"), (b"", "g1"), (b"", "g2"), (b"", "g3")])

    raw = store.load_raw()
    rinex = raw["stations"][0]["rinex"]
    assert rinex["auto_detect_obs_types"] is False
    assert rinex["sys_obs_types"]["G"] == ["C1C", "L1C", "D1C", "S1C"]
    assert rinex["approx_position"] == [11.0, 22.0, 33.0]
    assert any("Observation types detected and written to config" in line for line in logs)
    assert any("Approx position detected and written to config" in line for line in logs)
    assert any("Ignoring new observation type" in line for line in logs)

    files = sorted((tmp_path / "rinex" / "TEST11" / "2026").glob("*.rnx"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "C1C" in text
    assert "C5X" not in text


def test_station_buffers_late_same_epoch_messages_before_writing(tmp_path):
    config_path = tmp_path / "service.yaml"
    config_path.write_text(
        """
stations:
  - name: TEST14
    ntrip:
      host: caster.example.com
      mountpoint: TEST14
    rinex:
      output_directory: rinex
      marker_name: TEST14
      station_code: TEST
      receiver_number: "14"
      country_code: CHN
      sample_interval_seconds: 1
      split_enabled: false
      auto_detect_obs_types: false
      sys_obs_types:
        G: [C1C, L1C, D1C, S1C]
        R: [C1C, L1C, D1C, S1C]
      receiver_type: TestReceiver
      antenna_type: TestAntenna
""",
        encoding="utf-8",
    )
    epoch0 = datetime(2026, 3, 26, 0, 0, 0, tzinfo=timezone.utc)
    epoch1 = datetime(2026, 3, 26, 0, 0, 1, tzinfo=timezone.utc)
    epoch2 = datetime(2026, 3, 26, 0, 0, 2, tzinfo=timezone.utc)
    mapping = {
        "g0": _epoch(epoch0, {"G01": {"1C": _signal("1C", 21000000.0)}}),
        "g1": _epoch(epoch1, {"G02": {"1C": _signal("1C", 22000000.0)}}),
        "r0_late": _epoch(epoch0, {"R03": {"1C": _signal("1C", 23000000.0)}}),
        "g2": _epoch(epoch2, {"G03": {"1C": _signal("1C", 24000000.0)}}),
    }
    station = load_rt_rinex_config(config_path).stations[0]
    worker = RTNtripRinexStation(
        station,
        log_fn=lambda *_args: None,
        handler_factory=lambda: _FakeHandler(mapping),
    )

    worker.process_reader([(b"", "g0"), (b"", "g1"), (b"", "r0_late"), (b"", "g2")])

    files = sorted((tmp_path / "rinex" / "TEST14" / "2026").glob("*.rnx"))
    assert len(files) == 1
    blocks = _epoch_blocks(files[0].read_text(encoding="utf-8"))
    assert len(blocks) == 3
    assert "18.0000000" in blocks[0][0]
    assert any(line.startswith("G01") for line in blocks[0])
    assert any(line.startswith("R03") for line in blocks[0])
    assert "19.0000000" in blocks[1][0]
    assert "20.0000000" in blocks[2][0]


def test_writer_accepts_receiver_metadata_for_a20_header_fields(tmp_path):
    output = tmp_path / "header.rnx"
    writer = RINEX3Writer(str(output), receiver_number="01")
    assert writer.open()
    assert writer.write_header(
        sys_obs_types={"G": ["C1C", "L1C", "D1C", "S1C"]},
        receiver_type="SEPT MOSAIC-X5",
        receiver_serial="4014259",
        receiver_version="4.14.4",
        antenna_type="LEIAR25.R4 NONE",
        antenna_number="725235",
    )
    writer.close()

    lines = output.read_text(encoding="utf-8").splitlines()
    receiver_line = next(line for line in lines if line[60:80].strip() == "REC # / TYPE / VERS")
    antenna_line = next(line for line in lines if line[60:80].strip() == "ANT # / TYPE")

    assert receiver_line[:20].strip() == "4014259"
    assert receiver_line[20:40].strip() == "SEPT MOSAIC-X5"
    assert receiver_line[40:60].strip() == "4.14.4"
    assert antenna_line[:20].strip() == "725235"
    assert antenna_line[20:40].strip() == "LEIAR25.R4 NONE"


def test_station_uses_rtcm_1033_metadata_when_opening_rinex_writer(tmp_path):
    config_path = tmp_path / "service.yaml"
    config_path.write_text(
        """
stations:
  - name: TEST15
    ntrip:
      host: caster.example.com
      mountpoint: TEST15
    rinex:
      output_directory: rinex
      marker_name: TEST15
      station_code: TEST
      receiver_number: "15"
      country_code: CHN
      sample_interval_seconds: 1
      split_enabled: false
      auto_detect_obs_types: true
      receiver_type: ConfigReceiver
      antenna_type: ConfigAntenna
""",
        encoding="utf-8",
    )
    epoch0 = datetime(2026, 3, 26, 0, 0, 0, tzinfo=timezone.utc)
    epoch1 = datetime(2026, 3, 26, 0, 0, 1, tzinfo=timezone.utc)
    epoch2 = datetime(2026, 3, 26, 0, 0, 2, tzinfo=timezone.utc)
    mapping = {
        "g0": _epoch(epoch0, {"G01": {"1C": _signal("1C", 21000000.0)}}),
        "g1": _epoch(epoch1, {"G01": {"1C": _signal("1C", 21000001.0)}}),
        "g2": _epoch(epoch2, {"G01": {"1C": _signal("1C", 21000002.0)}}),
    }
    handler = _FakeHandler(mapping)
    handler.last_receiver_type_descriptor = "SEPT MOSAIC-X5"
    handler.last_receiver_firmware_version = "4.14.4"
    handler.last_receiver_serial_number = "4014259"
    handler.last_antenna_descriptor = "LEIAR25.R4 NONE"
    handler.last_antenna_serial_number = "725235"
    station = load_rt_rinex_config(config_path).stations[0]
    worker = RTNtripRinexStation(
        station,
        log_fn=lambda *_args: None,
        handler_factory=lambda: handler,
    )

    worker.process_reader([(b"", "g0"), (b"", "g1"), (b"", "g2")])

    files = sorted((tmp_path / "rinex" / "TEST15" / "2026").glob("*.rnx"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "4014259" in text
    assert "SEPT MOSAIC-X5" in text
    assert "4.14.4" in text
    assert "725235" in text
    assert "LEIAR25.R4 NONE" in text


def test_station_refreshes_rinex_header_when_1033_arrives_after_writer_open(tmp_path):
    config_path = tmp_path / "service.yaml"
    config_path.write_text(
        """
stations:
  - name: TEST16
    ntrip:
      host: caster.example.com
      mountpoint: TEST16
    rinex:
      output_directory: rinex
      marker_name: TEST16
      station_code: TEST
      receiver_number: "16"
      country_code: CHN
      sample_interval_seconds: 1
      split_enabled: false
      auto_detect_obs_types: true
      receiver_type: ConfigReceiver
      antenna_type: ConfigAntenna
""",
        encoding="utf-8",
    )
    epoch0 = datetime(2026, 3, 26, 0, 0, 0, tzinfo=timezone.utc)
    epoch1 = datetime(2026, 3, 26, 0, 0, 1, tzinfo=timezone.utc)
    epoch2 = datetime(2026, 3, 26, 0, 0, 2, tzinfo=timezone.utc)
    mapping = {
        "g0": _epoch(epoch0, {"G01": {"1C": _signal("1C", 21000000.0)}}),
        "g1": _epoch(epoch1, {"G01": {"1C": _signal("1C", 21000001.0)}}),
        "g2": _epoch(epoch2, {"G01": {"1C": _signal("1C", 21000002.0)}}),
    }
    handler = _MetadataAfterOpenHandler(mapping)
    station = load_rt_rinex_config(config_path).stations[0]
    worker = RTNtripRinexStation(
        station,
        log_fn=lambda *_args: None,
        handler_factory=lambda: handler,
    )

    worker.process_reader([(b"", "g0"), (b"", "g1"), (b"", "g2"), (b"", "desc")])

    files = sorted((tmp_path / "rinex" / "TEST16" / "2026").glob("*.rnx"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "4014259" in text
    assert "SEPT MOSAIC-X5" in text
    assert "4.14.4" in text
    assert "725235" in text
    assert "LEIAR25.R4 NONE" in text


def test_daily_merge_scheduler_merges_previous_day_even_when_split_count_is_incomplete(tmp_path):
    config_path = tmp_path / "service.yaml"
    config_path.write_text(
        """
stations:
  - name: TEST12
    ntrip:
      host: caster.example.com
      mountpoint: TEST12
    rinex:
      output_directory: rinex
      marker_name: TEST12
      station_code: TEST
      receiver_number: "12"
      country_code: CHN
      sample_interval_seconds: auto
      split_enabled: true
      split_period_seconds: 3600
      daily_merge_min_interval_seconds: 15
      auto_detect_obs_types: true
      receiver_type: TestReceiver
      antenna_type: TestAntenna
""",
        encoding="utf-8",
    )
    store = ConfigStore(config_path)
    epoch0 = datetime(2026, 3, 26, 0, 0, 12, tzinfo=timezone.utc)
    epoch1 = datetime(2026, 3, 26, 0, 0, 13, tzinfo=timezone.utc)
    epoch2 = datetime(2026, 3, 26, 1, 0, 12, tzinfo=timezone.utc)
    mapping = {
        "g0": _epoch(epoch0, {"G01": {"1C": _signal("1C")}}),
        "g1": _epoch(epoch1, {"G01": {"1C": _signal("1C", 21000001.0)}}),
        "g2": _epoch(epoch2, {"G02": {"1C": _signal("1C", 22000000.0)}}),
    }
    station = load_rt_rinex_config(config_path).stations[0]
    worker = RTNtripRinexStation(
        station,
        log_fn=lambda *_args: None,
        handler_factory=lambda: _FakeHandler(mapping),
        obs_types_persist_fn=store.persist_obs_types,
        approx_position_persist_fn=store.persist_approx_position,
    )

    worker.process_reader([(b"", "g0"), (b"", "g1"), (b"", "g2")])

    yearly_dir = tmp_path / "rinex" / "TEST12" / "2026"
    split_dir = yearly_dir / "085"
    assert split_dir.exists()
    assert not (yearly_dir / "2026085").exists()

    for path in yearly_dir.glob("*_01D_15S_MO.rnx"):
        path.unlink()

    manager = RuntimeManager(store, log_buffer=LogBuffer(max_lines=20))
    results = manager.run_due_merges()

    assert any(item.get("ok") for item in results)
    daily_files = sorted(yearly_dir.glob("*_01D_15S_MO.rnx"))
    assert len(daily_files) == 1
    assert "INTERVAL" in daily_files[0].read_text(encoding="utf-8")


def test_split_directory_uses_gps_day_and_three_digit_doy(tmp_path):
    config_path = tmp_path / "service.yaml"
    config_path.write_text(
        """
stations:
  - name: TEST13
    ntrip:
      host: caster.example.com
      mountpoint: TEST13
    rinex:
      output_directory: rinex
      marker_name: TEST13
      station_code: TEST
      receiver_number: "13"
      country_code: CHN
      sample_interval_seconds: auto
      split_enabled: true
      split_period_seconds: 3600
      auto_detect_obs_types: true
      receiver_type: TestReceiver
      antenna_type: TestAntenna
""",
        encoding="utf-8",
    )
    epoch0 = datetime(2026, 3, 25, 23, 59, 42, tzinfo=timezone.utc)
    epoch1 = datetime(2026, 3, 25, 23, 59, 43, tzinfo=timezone.utc)
    mapping = {
        "g0": _epoch(epoch0, {"G01": {"1C": _signal("1C")}}),
        "g1": _epoch(epoch1, {"G01": {"1C": _signal("1C", 21000001.0)}}),
    }
    station = load_rt_rinex_config(config_path).stations[0]
    worker = RTNtripRinexStation(
        station,
        log_fn=lambda *_args: None,
        handler_factory=lambda: _FakeHandler(mapping),
    )

    worker.process_reader([(b"", "g0"), (b"", "g1")])

    yearly_dir = tmp_path / "rinex" / "TEST13" / "2026"
    files = sorted((yearly_dir / "085").glob("*.rnx"))
    assert [path.name for path in files] == ["TEST13CHN_R_20260850000_01H_01S_MO.rnx"]
    assert not (yearly_dir / "2026085").exists()
    assert not (yearly_dir / "084").exists()


def test_daily_merge_buckets_output_by_gps_day(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    writer = RINEX3Writer(
        str(source_dir / "part.rnx"),
        marker_name="TEST",
        station_code="TEST",
        receiver_number="00",
        country_code="CHN",
        period="01H",
        interval="01S",
        header_interval_seconds=1.0,
        time_system="UTC",
        file_time=datetime(2026, 3, 25, 23, 0, 0),
    )
    assert writer.open()
    assert writer.write_header(
        sys_obs_types={"G": ["C1C", "L1C", "D1C", "S1C"]},
        receiver_type="TestReceiver",
        antenna_type="TestAntenna",
    )
    assert writer.write_observation(datetime(2026, 3, 25, 23, 59, 42), {"G01": _satellite("1C", 21000000.0)})
    assert writer.write_observation(datetime(2026, 3, 25, 23, 59, 43), {"G01": _satellite("1C", 21000001.0)})
    writer.close()

    output_dir = tmp_path / "daily"
    result = merge_rinex_daily_files(
        [source_dir],
        output_dir,
        marker_name="TEST",
        receiver_type="TestReceiver",
        station_code="TEST",
        receiver_number="00",
        country_code="CHN",
        antenna_type="TestAntenna",
        time_system="GPS",
    )

    assert len(result.output_files) == 1
    assert result.output_files[0].name.startswith("TEST00CHN_R_20260850000_01D_01S_MO")
    text = result.output_files[0].read_text(encoding="utf-8")
    assert "TIME OF FIRST OBS" in text and "GPS" in text
    assert "> 2026 03 26 00 00  0.0000000" in text


def test_log_buffer_filters_by_source():
    logs = LogBuffer(max_lines=10)
    logs.write("[TEST11] Worker started")
    logs.write("[TEST12] Worker started")
    logs.write("[web] GET /api/status")

    filtered = logs.lines(source="TEST11")
    assert len(filtered) == 1
    assert "[TEST11]" in filtered[0]
    assert all("[TEST12]" in line for line in logs.lines(source="TEST12"))
    assert all("[web]" in line for line in logs.lines(source="web"))
    assert len(logs.lines(source="")) == 3
    assert logs.sources() == ["TEST11", "TEST12", "web"]
