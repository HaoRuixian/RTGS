import math
import threading
import time

import pytest

from core.global_config import GlobalConfig
from core.positioning_models import PositioningMode, SolutionStatus
from core.native_rtk import (
    NativeRTKRunner,
    build_rtk_engine_config,
    find_rtkrcv,
    parse_rtk_engine_solution,
    redact_sensitive_text,
)


ROVER = {
    "source_type": "NTRIP Server",
    "host": "rover.example.com",
    "port": "2101",
    "mountpoint": "ROVER",
    "user": "rover-user",
    "password": "rover-pass",
}

BASE = {
    "source_type": "NTRIP Server",
    "host": "base.example.com",
    "port": "2101",
    "mountpoint": "BASE",
    "user": "base-user",
    "password": "base-pass",
    "enabled": True,
}


def test_single_base_config_enables_multignss_ar_and_rtcm_position():
    config = build_rtk_engine_config(
        ROVER,
        BASE,
        {"enabled": False},
        {
            "rtk_type": "single_base",
            "rtk_rover_format": "ubx",
            "rtk_base_format": "rtcm3",
            "rtk_frequency": "l1+l2+l5",
            "rtk_ar_mode": "fix-and-hold",
            "rtk_glonass_ar_mode": "autocal",
            "rtk_bds_ar": True,
            "rtk_base_position_source": "rtcm",
            "gnss_systems": ["G", "R", "E", "C"],
        },
        40123,
    )

    assert "inpstr1-type       =ntripcli" in config
    assert "inpstr2-type       =ntripcli" in config
    assert "inpstr1-format     =ubx" in config
    assert "inpstr2-format     =rtcm3" in config
    assert "pos1-frequency     =l1+l2+l5" in config
    assert "pos1-navsys        =45" in config
    assert "pos2-armode         =fix-and-hold" in config
    assert "pos2-gloarmode      =autocal" in config
    assert "pos2-bdsarmode      =on" in config
    assert "ant2-postype       =rtcm" in config
    assert "inpstr2-nmeareq    =off" in config
    assert "outstr1-path       =:40123" in config


def test_network_config_uses_receiver_position_for_vrs_gga():
    config = build_rtk_engine_config(
        ROVER,
        BASE,
        {"enabled": False},
        {
            "rtk_type": "network",
            "rtk_network_protocol": "VRS",
            "rtk_gga_mode": "auto",
            "rtk_gga_position": [0.0, 0.0, 0.0],
            "rtk_gga_cycle_ms": 3000,
            "gnss_systems": ["G", "C"],
        },
        40124,
        approx_rec_pos=[-2171646.234, 4385696.114, 4076742.303],
    )

    assert "inpstr2-nmeareq    =latlon" in config
    assert "misc-nmeacycle     =3000" in config
    latitude_line = next(line for line in config.splitlines() if line.startswith("inpstr2-nmealat"))
    longitude_line = next(line for line in config.splitlines() if line.startswith("inpstr2-nmealon"))
    latitude = float(latitude_line.split("=", 1)[1])
    longitude = float(longitude_line.split("=", 1)[1])
    assert 39.0 < latitude < 41.0
    assert 115.0 < longitude < 117.0


@pytest.mark.parametrize(
    ("quality", "expected_status", "label"),
    [
        (1, SolutionStatus.FIXED, "RTK Fixed"),
        (2, SolutionStatus.UNCERTAIN, "RTK Float"),
        (4, SolutionStatus.UNCERTAIN, "DGPS/DGNSS"),
        (5, SolutionStatus.UNCERTAIN, "Single"),
    ],
)
def test_solution_parser_maps_rtk_quality_age_ratio_and_velocity(quality, expected_status, label):
    line = (
        f"2427,345600.000,39.123456789,116.123456789,50.1234,{quality},18,"
        "0.0100,0.0090,0.0200,0,0,0,0.50,4.2,1.1,2.2,3.3,0,0,0,0,0,0"
    )
    solution = parse_rtk_engine_solution(
        line,
        reference_ecef=[-2171646.234, 4385696.114, 4076742.303],
    )

    assert solution is not None
    assert solution.mode == PositioningMode.RTK
    assert solution.status == expected_status
    assert label in solution.solution_source
    assert solution.differential_age_s == pytest.approx(0.5)
    assert solution.ambiguity_ratio == pytest.approx(4.2)
    assert solution.velocity_north == pytest.approx(1.1)
    assert solution.velocity_east == pytest.approx(2.2)
    assert solution.velocity_up == pytest.approx(3.3)
    assert math.isnan(solution.hdop)
    assert solution.has_reference_position is True


def test_parser_ignores_headers_and_malformed_lines():
    assert parse_rtk_engine_solution("% GPST,latitude") is None
    assert parse_rtk_engine_solution("not,a,solution") is None
    assert parse_rtk_engine_solution("2427,1,100,10,0,1,10,0,0,0,0,0,0,0,3") is None


def test_credentials_are_redacted_from_rtk_engine_messages():
    message = "stream rover-user:p@ssword@caster.example.com:2101/MOUNT failed"
    redacted = redact_sensitive_text(message)
    assert "p@ssword" not in redacted
    assert "rover-user:***@caster.example.com:2101/MOUNT" in redacted


def test_global_config_round_trip_preserves_base_stream_and_rtk_options():
    config = GlobalConfig()
    config.update_settings(
        "BASE",
        {
            "enabled": True,
            "source_type": "NTRIP Server",
            "host": "caster.example.com",
            "mountpoint": "VRS3",
            "data_format": "RTCM3",
        },
    )
    config.update_positioning_settings({"rtk_type": "network", "rtk_network_protocol": "MAC"})

    restored = GlobalConfig()
    restored.from_dict(config.to_dict())

    assert restored.base_settings.enabled is True
    assert restored.base_settings.mountpoint == "VRS3"
    assert restored.get_connection_settings("BASE").data_format == "RTCM3"
    assert restored.get_positioning_settings()["rtk_type"] == "network"
    assert restored.get_positioning_settings()["rtk_network_protocol"] == "MAC"


try:
    _RTKRCV = find_rtkrcv()
except FileNotFoundError:
    _RTKRCV = None


@pytest.mark.skipif(_RTKRCV is None, reason="rtkrcv is not available")
def test_native_runner_starts_solution_server_and_stops_responsively():
    runner = NativeRTKRunner(
        {"source_type": "TCP Client", "tcp_path": "127.0.0.1:45991", "data_format": "RTCM3"},
        {
            "source_type": "TCP Client",
            "tcp_path": "127.0.0.1:45992",
            "data_format": "RTCM3",
            "enabled": True,
        },
        {"enabled": False},
        {"rtk_type": "single_base", "gnss_systems": ["G", "R", "E", "C"]},
        executable=_RTKRCV,
        startup_timeout=4.0,
    )
    connected = threading.Event()
    errors = []

    def log(message):
        if message == "RTK solution stream connected":
            connected.set()

    def run():
        try:
            runner.run(lambda _solution: None, log_callback=log)
        except Exception as exc:  # pragma: no cover - assertion reports subprocess output
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    assert connected.wait(3.0)
    started = time.monotonic()
    runner.stop()
    thread.join(3.0)

    assert not thread.is_alive()
    assert time.monotonic() - started < 3.0
    assert errors == []
