"""Regression tests for the standalone realtime EKF-GNSSIR worker."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from utils.realtime_ekf_gnssir.config import (
    StationConfig,
    StationRuntimeConfig,
    StorageConfig,
    StreamConfig,
)
from utils.realtime_ekf_gnssir._vendor.core.reflectometry.config import load_config
from utils.realtime_ekf_gnssir._vendor.core.reflectometry.services.ekf import (
    EkfPoint,
    EkfReflectometryProcessor,
)
from utils.realtime_ekf_gnssir._vendor.core.reflectometry.services.realtime import RealtimeProcessor
from utils.realtime_ekf_gnssir.station_worker import RealtimeEkfStationWorker
from utils.realtime_ekf_gnssir.runtime import _normalize_receiver_position_payload
from utils.realtime_ekf_gnssir._vendor.rt_ntrip_rinex_service.rtcm_handler import RTCMHandler
from tests.reflectometry.helpers import generate_synthetic_observations


def _blank_coordinate_config(tmp_path: Path) -> Path:
    source = Path("utils/realtime_ekf_gnssir/config/ir/SC02.yaml")
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    raw["station"]["receiver_position"] = {
        "latitude_deg": None,
        "longitude_deg": None,
        "height_m": None,
        "x_m": None,
        "y_m": None,
        "z_m": None,
    }
    path = tmp_path / "SC02.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _worker(tmp_path: Path, config_path: Path) -> RealtimeEkfStationWorker:
    station = StationConfig(
        name="SC02",
        enabled=True,
        reflectometry_config=config_path,
        obs_settings=StreamConfig(host="example.test", mountpoint="SC02"),
        eph_settings=StreamConfig(enabled=False),
        runtime=StationRuntimeConfig(max_product_history=20),
    )
    storage = StorageConfig(output_dir=tmp_path / "output")
    return RealtimeEkfStationWorker(station, storage, log_fn=lambda *_args: None)


def test_blank_coordinates_wait_for_rtcm_instead_of_blocking_start(tmp_path):
    worker = _worker(tmp_path, _blank_coordinate_config(tmp_path))

    worker._load_reflectometry_processor()

    assert worker._reflector_config is not None
    assert worker._processor is None
    status = worker.snapshot()
    assert status["receiver_position"]["status"] == "waiting_rtcm"
    assert status["initialization"]["mode"] == "waiting_coordinate"


def test_rtcm_coordinates_are_persisted_and_activate_processor(tmp_path):
    config_path = _blank_coordinate_config(tmp_path)
    worker = _worker(tmp_path, config_path)
    worker._load_reflectometry_processor()
    xyz = [-2304502.5391, -3547587.4650, 4757297.2854]

    applied = worker._apply_rtcm_receiver_position(xyz, message_type="1006")

    assert applied is True
    assert worker._processor is not None
    persisted = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    position = persisted["station"]["receiver_position"]
    assert [position["x_m"], position["y_m"], position["z_m"]] == pytest.approx(xyz)
    assert position["latitude_deg"] == pytest.approx(48.546253, abs=1e-5)
    assert position["longitude_deg"] == pytest.approx(-123.007637, abs=1e-5)
    status = worker.snapshot()["receiver_position"]
    assert status["source"] == "rtcm_1006"
    assert status["status"] == "ready"


@pytest.mark.parametrize("message_type", ["1005", "1006"])
def test_rtcm_coordinate_messages_flow_through_decoder_to_worker(tmp_path, message_type):
    config_path = _blank_coordinate_config(tmp_path)
    worker = _worker(tmp_path, config_path)
    worker._load_reflectometry_processor()
    worker._handler = RTCMHandler(compute_geometry=False)
    message = SimpleNamespace(
        identity=message_type,
        DF025=-2304502.5391,
        DF026=-3547587.4650,
        DF027=4757297.2854,
        DF028=0.1234,
    )

    worker._consume_message(None, message)

    assert worker._processor is not None
    status = worker.snapshot()["receiver_position"]
    assert status["source"] == f"rtcm_{message_type}"
    assert status["rtcm_message_type"] == message_type


def test_reflectometry_ingest_uses_configured_sampling_interval(tmp_path):
    worker = _worker(tmp_path, Path("utils/realtime_ekf_gnssir/config/ir/SC02.yaml").resolve())
    worker._load_reflectometry_processor()
    start = datetime(2026, 6, 21, 0, 0, 0, tzinfo=timezone.utc)

    accepted = [
        worker._should_ingest_reflectometry_epoch(start + timedelta(seconds=offset))
        for offset in range(31)
    ]

    assert [index for index, value in enumerate(accepted) if value] == [0, 15, 30]
    snapshot = worker.snapshot()
    assert snapshot["sampling"]["interval_seconds"] == 15
    assert snapshot["sampling"]["skipped_epochs"] == 28


def test_initialization_status_requires_elevation_span_not_only_sample_count(tmp_path):
    worker = _worker(tmp_path, Path("utils/realtime_ekf_gnssir/config/ir/SC02.yaml").resolve())
    worker._load_reflectometry_processor()
    start = datetime(2026, 6, 21, 0, 0, 0, tzinfo=timezone.utc)
    samples = [
        (start + timedelta(seconds=15 * index), 1.0, 0.1000 + index * 0.00005)
        for index in range(20)
    ]
    arc = SimpleNamespace(
        key=("G", "G03", "1C"),
        wavelength_m=0.1902936728,
        detrended_samples=samples,
        samples=[object()] * 20,
        initialized=False,
        last_timestamp=samples[-1][0],
        last_elevation_deg=5.8,
        direction_sign=1,
    )
    ekf = SimpleNamespace(
        config=SimpleNamespace(
            rh_init_min_samples=20,
            init_min_samples=20,
            rh_init_cycles=2.0,
            rh_init_max_height_m=6.0,
        ),
        ir_config=SimpleNamespace(min_reflector_height=3.0, max_reflector_height=9.0),
        rh=5.0,
        rh_initialized=False,
        arc_states={arc.key: arc},
    )
    worker._processor = SimpleNamespace(ekf_processor=ekf)
    worker._last_message_time = samples[-1][0]
    worker._last_epoch_time = samples[-1][0]
    worker._latest_skyplot = [{"satellite": "G03"}]
    worker._latest_record_samples = [{"satellite": "G03"}]

    initialization = worker.snapshot()["initialization"]

    assert initialization["ready_lsp_arc_count"] == 0
    assert initialization["progress"] < 0.1
    assert initialization["arcs"][0]["lsp_cycle_progress"] < 0.1
    assert initialization["arcs"][0]["lsp_required_sin_span"] == pytest.approx(
        2.0 * arc.wavelength_m / (2.0 * 6.0)
    )
    assert "高度角跨度" in initialization["waiting_reason"]


def test_web_config_accepts_all_blank_coordinates_as_rtcm_auto_mode():
    raw = {
        "station": {
            "receiver_position": {
                "x_m": None,
                "y_m": "",
                "z_m": None,
                "latitude_deg": 48.0,
                "longitude_deg": -123.0,
                "height_m": 10.0,
            }
        }
    }

    _normalize_receiver_position_payload(raw)

    position = raw["station"]["receiver_position"]
    assert position["source"] == "rtcm_auto"
    assert all(position[key] is None for key in ("x_m", "y_m", "z_m", "latitude_deg", "longitude_deg", "height_m"))


def test_web_config_rejects_partial_coordinates():
    raw = {"station": {"receiver_position": {"x_m": 1.0, "y_m": None, "z_m": 2.0}}}

    with pytest.raises(ValueError, match="all three be blank or all three be set"):
        _normalize_receiver_position_payload(raw)


def test_sc02_matlab_aligned_no_tide_ekf_initializes_and_emits(tmp_path):
    worker = _worker(tmp_path, Path("utils/realtime_ekf_gnssir/config/ir/SC02.yaml").resolve())
    worker._load_reflectometry_processor()
    config = worker._reflector_config
    processor = worker._processor
    assert config is not None and processor is not None
    assert config.ir.ekf.rh_init_min_arcs >= 3
    assert config.ir.ekf.rh_init_min_height_m == pytest.approx(4.0)
    assert config.ir.ekf.rh_init_max_height_m == pytest.approx(6.0)
    observations = generate_synthetic_observations(
        station_id=config.station.station_id,
        receiver_position=config.station.receiver_position,
        constellations=("G",),
        signals=("1C",),
        arc_count=4,
        samples_per_arc=160,
        reflector_height_m=5.2,
        noise_std_db=0.03,
        amplitude_db=3.0,
        sampling_interval_seconds=15.0,
    )

    for index in range(0, len(observations), 40):
        chunk = observations[index : index + 40]
        processor.ingest(chunk, reference_time=chunk[-1].timestamp)

    ekf = processor.ekf_processor
    assert ekf is not None
    assert ekf.rh_initialization is not None
    assert ekf.rh_initialization.reflector_height_m == pytest.approx(5.2, abs=0.15)
    assert ekf.outputs
    assert ekf.rh == pytest.approx(5.2, abs=0.5)


def test_first_realtime_product_is_emitted_immediately_after_initialization():
    config = load_config(Path("utils/realtime_ekf_gnssir/config/ir/NBFH.yaml"))
    ekf = EkfReflectometryProcessor(
        config.ir,
        config.products,
        station_id=config.station.station_id,
        sampling_interval_seconds=config.input.sampling_interval,
    )
    initialized_at = datetime(2026, 6, 30, 12, 34, 17, tzinfo=timezone.utc)
    ekf.rh_initialized = True
    ekf.rh = 8.1
    ekf.points.append(
        EkfPoint(
            timestamp=initialized_at,
            reflector_height_m=ekf.rh,
            covariance_m2=0.01,
            active_arc_count=1,
            active_frequency_arc_count=1,
            active_satellite_arc_count=1,
        )
    )

    output = ekf._maybe_emit_output(initialized_at)

    assert output is not None
    assert output.timestamp == initialized_at
    assert output.window_end == initialized_at
    assert output.sample_count == 1


def test_nb01_uses_matlab_no_tide_sampling_and_noise_parameters():
    config = load_config(Path("utils/realtime_ekf_gnssir/config/ir/NBFH.yaml"))

    assert config.input.sampling_interval == pytest.approx(15.0)
    assert config.ir.ekf.q_rh == pytest.approx(1e-5)
    assert config.ir.ekf.measurement_variance == pytest.approx(0.15698)
    assert config.ir.ekf.rh_init_min_samples == 20
    assert config.ir.ekf.max_time_gap_seconds >= 45.0


def test_nb01_matlab_aligned_ekf_recovers_reflector_height_and_outputs_on_init():
    config = load_config(Path("utils/realtime_ekf_gnssir/config/ir/NBFH.yaml"))
    observations = generate_synthetic_observations(
        station_id=config.station.station_id,
        receiver_position=config.station.receiver_position,
        constellations=("G",),
        signals=("1C",),
        arc_count=6,
        samples_per_arc=160,
        reflector_height_m=8.15,
        noise_std_db=0.03,
        amplitude_db=3.0,
        sampling_interval_seconds=config.input.sampling_interval,
    )
    realtime = RealtimeProcessor(config)
    products_on_initialization = []
    was_initialized = False

    for index in range(0, len(observations), 20):
        chunk = observations[index : index + 20]
        result = realtime.ingest(chunk, reference_time=chunk[-1].timestamp)
        is_initialized = bool(realtime.ekf_processor and realtime.ekf_processor.rh_initialized)
        if is_initialized and not was_initialized:
            products_on_initialization = list(result.products)
        was_initialized = is_initialized

    ekf = realtime.ekf_processor
    assert ekf is not None
    assert ekf.rh_initialization is not None
    assert ekf.rh_initialization.reflector_height_m == pytest.approx(8.15, abs=0.1)
    assert ekf.rh == pytest.approx(8.15, abs=0.25)
    assert products_on_initialization
