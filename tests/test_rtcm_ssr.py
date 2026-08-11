from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from pyrtcm import crc2bytes

from core.mixed_gnss_reader import MixedGNSSReader, RawRTCMMessage
from core.rtcm_handler import RTCMHandler


class FakeRTCMMessage:
    def __init__(self, identity: str, **attrs):
        self.identity = identity
        for key, value in attrs.items():
            setattr(self, key, value)


def _unsigned_bits(value: int, width: int) -> str:
    return format(value & ((1 << width) - 1), f"0{width}b")


def _signed_bits(value: int, width: int) -> str:
    if value < 0:
        value = (1 << width) + value
    return _unsigned_bits(value, width)


def _rtcm_frame(payload_bits: str) -> bytes:
    payload_bits += "0" * (-len(payload_bits) % 8)
    payload = int(payload_bits, 2).to_bytes(len(payload_bits) // 8, "big")
    frame_without_crc = b"\xd3" + len(payload).to_bytes(2, "big") + payload
    return frame_without_crc + crc2bytes(frame_without_crc)


def _igs_ssr_gps_combined_frame() -> bytes:
    payload_bits = "".join(
        (
            _unsigned_bits(4076, 12),
            _unsigned_bits(3, 3),
            _unsigned_bits(23, 8),  # IM23 GPS combined orbit and clock
            _unsigned_bits(100, 20),
            _unsigned_bits(1, 4),
            _unsigned_bits(0, 1),
            _unsigned_bits(4, 4),
            _unsigned_bits(12, 16),
            _unsigned_bits(1, 4),
            _unsigned_bits(0, 1),
            _unsigned_bits(1, 6),
            _unsigned_bits(1, 6),
            _unsigned_bits(7, 8),
            _signed_bits(10000, 22),   # 1.0 m
            _signed_bits(5000, 20),    # 2.0 m
            _signed_bits(-7500, 20),   # -3.0 m
            _signed_bits(10000, 21),   # 0.01 m/s
            _signed_bits(5000, 19),    # 0.02 m/s
            _signed_bits(-7500, 19),   # -0.03 m/s
            _signed_bits(5000, 22),    # 0.5 m
            _signed_bits(2000, 21),    # 0.002 m/s
            _signed_bits(-25000, 27),  # -0.0005 m/s^2
        )
    )
    return _rtcm_frame(payload_bits)


def _igs_ssr_bds_combined_frame() -> bytes:
    payload_bits = "".join(
        (
            _unsigned_bits(4076, 12),
            _unsigned_bits(3, 3),
            _unsigned_bits(103, 8),  # IM103 BDS combined orbit and clock
            _unsigned_bits(100, 20),
            _unsigned_bits(1, 4),
            _unsigned_bits(0, 1),
            _unsigned_bits(4, 4),
            _unsigned_bits(12, 16),
            _unsigned_bits(1, 4),
            _unsigned_bits(0, 1),
            _unsigned_bits(1, 6),
            _unsigned_bits(6, 6),
            _unsigned_bits(7, 8),
            _signed_bits(10000, 22),
            _signed_bits(5000, 20),
            _signed_bits(-7500, 20),
            _signed_bits(10000, 21),
            _signed_bits(5000, 19),
            _signed_bits(-7500, 19),
            _signed_bits(5000, 22),
            _signed_bits(2000, 21),
            _signed_bits(-25000, 27),
        )
    )
    return _rtcm_frame(payload_bits)


def _ssr_gps_phase_bias_frame(*, igs: bool = False) -> bytes:
    prefix = (
        _unsigned_bits(4076, 12) + _unsigned_bits(3, 3) + _unsigned_bits(26, 8)
        if igs
        else _unsigned_bits(1265, 12)
    )
    payload_bits = "".join(
        (
            prefix,
            _unsigned_bits(100, 20),
            _unsigned_bits(1, 4),
            _unsigned_bits(0, 1),
            _unsigned_bits(4, 4),
            _unsigned_bits(12, 16),
            _unsigned_bits(1, 4),
            _unsigned_bits(1, 1),
            _unsigned_bits(1, 1),
            _unsigned_bits(1, 6),
            _unsigned_bits(1, 6),
            _unsigned_bits(2, 5),
            _unsigned_bits(128, 9),
            _signed_bits(-4, 8),
            _unsigned_bits(0, 5),  # GPS 1C
            _unsigned_bits(1, 1),
            _unsigned_bits(2, 2),
            _unsigned_bits(3, 4),
            _signed_bits(1234, 20),
            _unsigned_bits(11 if igs else 11, 5),  # GPS 2W
            _unsigned_bits(1, 1),
            _unsigned_bits(1, 2),
            _unsigned_bits(7, 4),
            _signed_bits(-2500, 20),
        )
    )
    return _rtcm_frame(payload_bits)


def test_rtcm_handler_parses_gps_combined_ssr_corrections():
    handler = RTCMHandler(compute_geometry=False)
    msg = FakeRTCMMessage(
        "1060",
        DF385=100.0,
        DF391=1,
        DF388=0,
        DF375=0,
        DF413=4,
        DF414=12,
        DF415=1,
        DF387=1,
        DF068_01=1,
        DF071_01=7,
        DF365_01=1000.0,
        DF366_01=2000.0,
        DF367_01=-3000.0,
        DF368_01=10.0,
        DF369_01=20.0,
        DF370_01=-30.0,
        DF376_01=500.0,
        DF377_01=2.0,
        DF378_01=-0.5,
    )

    handler.process_message(msg)

    orbit = handler.ssr_corrections.get_orbit("G01")
    clock = handler.ssr_corrections.get_clock("G01")
    assert orbit is not None
    assert clock is not None
    assert orbit.delta_radial_m == pytest.approx(1.0)
    assert orbit.delta_along_track_m == pytest.approx(2.0)
    assert orbit.delta_cross_track_m == pytest.approx(-3.0)
    assert orbit.dot_delta_radial_mps == pytest.approx(0.01)
    assert orbit.iod == 7
    assert clock.delta_clock_m == pytest.approx(0.5)
    assert clock.delta_clock_rate_mps == pytest.approx(0.002)
    assert clock.delta_clock_accel_mps2 == pytest.approx(-0.0005)


def test_rtcm_handler_parses_non_gps_ssr_satellite_fields():
    handler = RTCMHandler(compute_geometry=False)

    handler.process_message(
        FakeRTCMMessage(
            "1064",
            DF386=120.0,
            DF391=1,
            DF388=0,
            DF413=4,
            DF414=12,
            DF415=1,
            DF387=1,
            DF384_01=7,
            DF376_01=250.0,
            DF377_01=0.0,
            DF378_01=0.0,
        )
    )
    handler.process_message(
        FakeRTCMMessage(
            "1240",
            DF458=130.0,
            DF391=1,
            DF388=0,
            DF375=0,
            DF413=4,
            DF414=12,
            DF415=1,
            DF387=1,
            DF252_01=11,
            DF459_01=9,
            DF365_01=100.0,
            DF366_01=0.0,
            DF367_01=0.0,
            DF368_01=0.0,
            DF369_01=0.0,
            DF370_01=0.0,
        )
    )
    handler.process_message(
        FakeRTCMMessage(
            "1258",
            DF465=140.0,
            DF391=1,
            DF388=0,
            DF375=0,
            DF413=4,
            DF414=12,
            DF415=1,
            DF387=1,
            DF488_01=6,
            DF471_01=5,
            DF365_01=200.0,
            DF366_01=0.0,
            DF367_01=0.0,
            DF368_01=0.0,
            DF369_01=0.0,
            DF370_01=0.0,
        )
    )

    assert handler.ssr_corrections.get_clock("R07").delta_clock_m == pytest.approx(0.25)
    assert handler.ssr_corrections.get_orbit("E11").delta_radial_m == pytest.approx(0.1)
    assert handler.ssr_corrections.get_orbit("C06").delta_radial_m == pytest.approx(0.2)


def test_rtcm_handler_converts_standard_glonass_ssr_epoch_with_precise_model():
    handler = RTCMHandler(reference_utc=datetime(2026, 3, 26, tzinfo=timezone.utc), compute_geometry=False)
    handler.process_message(
        FakeRTCMMessage(
            "1064",
            DF386=3 * 3600 + 12,
            DF391=1,
            DF388=0,
            DF413=4,
            DF414=12,
            DF415=1,
            DF387=1,
            DF384_01=7,
            DF376_01=250.0,
            DF377_01=0.0,
            DF378_01=0.0,
        )
    )

    assert handler.ssr_corrections.get_clock("R07").epoch_time == pytest.approx(4 * 86400 + 30)


def test_rtcm_handler_maps_ssr_code_bias_signal_ids_to_rinex_codes():
    handler = RTCMHandler(compute_geometry=False)
    handler.process_message(
        FakeRTCMMessage(
            "1260",
            DF465=140.0,
            DF391=1,
            DF388=0,
            DF413=4,
            DF414=12,
            DF415=1,
            DF387=1,
            DF488_01=6,
            DF379_01=1,
            DF467_01_01=3,
            DF383_01_01=1.25,
        )
    )

    assert handler.ssr_corrections.get_code_biases("C06") == {"6I": pytest.approx(1.25)}
    assert RTCMHandler._ssr_signal_to_rinex("C", 12, igs=True) == "5D"


def test_rtcm_handler_parses_igs_ssr_4076_combined_message():
    handler = RTCMHandler(compute_geometry=False)
    raw = _igs_ssr_gps_combined_frame()

    handler.process_message(RawRTCMMessage(raw=raw, identity="4076"))

    orbit = handler.ssr_corrections.get_orbit("G01")
    clock = handler.ssr_corrections.get_clock("G01")
    assert orbit is not None
    assert clock is not None
    assert orbit.epoch_time == pytest.approx(100.0)
    assert orbit.delta_radial_m == pytest.approx(1.0)
    assert orbit.delta_along_track_m == pytest.approx(2.0)
    assert orbit.delta_cross_track_m == pytest.approx(-3.0)
    assert orbit.dot_delta_radial_mps == pytest.approx(0.01)
    assert orbit.iod == 7
    assert clock.delta_clock_m == pytest.approx(0.5)
    assert clock.delta_clock_rate_mps == pytest.approx(0.002)
    assert clock.delta_clock_accel_mps2 == pytest.approx(-0.0005)


def test_rtcm_handler_parses_cas_igs_ssr_bds_combined_message():
    handler = RTCMHandler(compute_geometry=False)

    handler.process_message(RawRTCMMessage(raw=_igs_ssr_bds_combined_frame(), identity="4076"))

    orbit = handler.ssr_corrections.get_orbit("C06")
    clock = handler.ssr_corrections.get_clock("C06")
    assert orbit is not None
    assert clock is not None
    assert orbit.epoch_time == pytest.approx(114.0)
    assert orbit.iod == 7
    assert orbit.delta_radial_m == pytest.approx(1.0)
    assert clock.delta_clock_m == pytest.approx(0.5)


def test_mixed_reader_preserves_unsupported_igs_ssr_4076_frame():
    raw = _igs_ssr_gps_combined_frame()
    reader = MixedGNSSReader(io.BytesIO(raw))

    parsed_raw, msg = reader.read()

    assert parsed_raw == raw
    assert isinstance(msg, RawRTCMMessage)
    assert msg.identity == "4076"


@pytest.mark.parametrize("igs", [False, True])
def test_rtcm_handler_decodes_integer_phase_bias_metadata(igs):
    handler = RTCMHandler(compute_geometry=False)
    raw = _ssr_gps_phase_bias_frame(igs=igs)
    identity = "4076" if igs else "1265"

    handler.process_message(RawRTCMMessage(raw=raw, identity=identity))

    correction = handler.ssr_corrections.get_phase_biases("G01", time_sow=100.0)
    assert correction is not None
    assert correction.provider_id == 12
    assert correction.solution_id == 1
    assert correction.dispersive_consistency is True
    assert correction.mw_consistency is True
    assert correction.yaw_angle_deg == pytest.approx(90.0)
    assert correction.yaw_rate_deg_s == pytest.approx(-4 * 180.0 / 8192.0)
    assert correction.biases["1C"].bias_m == pytest.approx(0.1234)
    assert correction.biases["1C"].integer_indicator is True
    assert correction.biases["1C"].wide_lane_indicator == 2
    assert correction.biases["1C"].discontinuity_counter == 3
    assert correction.biases["2W"].bias_m == pytest.approx(-0.25)
    assert correction.biases["2W"].discontinuity_counter == 7


def test_mixed_reader_preserves_standard_ssr_phase_bias_frame():
    raw = _ssr_gps_phase_bias_frame(igs=False)
    reader = MixedGNSSReader(io.BytesIO(raw))

    parsed_raw, msg = reader.read()

    assert parsed_raw == raw
    assert isinstance(msg, RawRTCMMessage)
    assert msg.identity == "1265"
