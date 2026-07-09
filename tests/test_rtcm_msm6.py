from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from pyrtcm import RTCMReader, crc2bytes

from core.mixed_gnss_reader import MixedGNSSReader
from core.geo_utils import get_freq
from core.pyrtcm_compat import patch_pyrtcm_glonass_g3
from core.rinex3_writer import RINEX3Writer
from core.rt_ntrip_rinex import _detect_sys_obs_types_from_satellites as detect_core_obs_types
from core.rtcm_handler import RTCMHandler as CoreRTCMHandler
from utils import rtcm_to_rinex
from utils.realtime_ekf_gnssir._vendor.rt_ntrip_rinex_service.rtcm_handler import (
    RTCMHandler as VendoredRTCMHandler,
)
from utils.realtime_ekf_gnssir._vendor.rt_ntrip_rinex_service.mixed_gnss_reader import (
    MixedGNSSReader as VendoredMixedGNSSReader,
)
from utils.realtime_ekf_gnssir._vendor.rt_ntrip_rinex_service.service import (
    _detect_sys_obs_types_from_satellites as detect_vendored_obs_types,
)
from utils.rt_ntrip_rinex_service.mixed_gnss_reader import MixedGNSSReader as ServiceMixedGNSSReader
from utils.rt_ntrip_rinex_service.rtcm_handler import RTCMHandler as ServiceRTCMHandler
from utils.rt_ntrip_rinex_service.service import (
    _detect_sys_obs_types_from_satellites as detect_service_obs_types,
)
from ui.monitoring.formatting import format_optional_observation


MSM6_CASES = (
    ("1076", "G03", "1C"),
    ("1086", "R03", "1C"),
    ("1096", "E03", "1C"),
    ("1106", "S122", "1C"),
    ("1116", "J03", "1C"),
    ("1126", "C03", "2I"),
    ("1136", "I03", "1D"),
)

RTCM_HANDLER_TYPES = (CoreRTCMHandler, ServiceRTCMHandler, VendoredRTCMHandler)
OBS_TYPE_DETECTORS = (detect_core_obs_types, detect_service_obs_types, detect_vendored_obs_types)
MIXED_READER_TYPES = (MixedGNSSReader, ServiceMixedGNSSReader, VendoredMixedGNSSReader)


class _FragmentedReadStream:
    def __init__(self, payload: bytes, max_chunk: int = 1):
        self._payload = payload
        self._max_chunk = max_chunk
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        if size is None or size < 0:
            size = len(self._payload) - self._offset
        chunk_size = min(size, self._max_chunk, len(self._payload) - self._offset)
        chunk = self._payload[self._offset : self._offset + chunk_size]
        self._offset += chunk_size
        return chunk


def _unsigned_bits(value: int, width: int) -> str:
    return format(value & ((1 << width) - 1), f"0{width}b")


def _build_msm6_frame(
    message_id: str,
    *,
    glonass_day: int = 5,
    glonass_milliseconds: int = 43_200_000,
) -> bytes:
    """Build a one-satellite, one-signal MSM6 frame from RTCM 10403.3 fields."""
    prefix = message_id[:3]
    time_bits = []
    if prefix == "108":
        time_bits.extend((_unsigned_bits(glonass_day, 3), _unsigned_bits(glonass_milliseconds, 27)))
    else:
        time_bits.append(_unsigned_bits(345_600_000, 30))

    payload_bits = "".join(
        (
            _unsigned_bits(int(message_id), 12),
            _unsigned_bits(42, 12),
            *time_bits,
            _unsigned_bits(0, 1),  # DF393 multiple message bit
            _unsigned_bits(0, 3),  # DF409 IODS
            _unsigned_bits(0, 7),
            _unsigned_bits(0, 2),  # DF411 clock steering
            _unsigned_bits(0, 2),  # DF412 external clock
            _unsigned_bits(0, 1),  # DF417 smoothing type
            _unsigned_bits(0, 3),  # DF418 smoothing interval
            _unsigned_bits(1 << (64 - 3), 64),  # satellite mask ID 3
            _unsigned_bits(1 << (32 - 2), 32),  # signal mask ID 2
            _unsigned_bits(1, 1),  # one active cell
            _unsigned_bits(70, 8),  # DF397 integer milliseconds
            _unsigned_bits(256, 10),  # DF398 = 0.25 ms
            _unsigned_bits(1000, 20),  # DF405 = 1000 * 2^-29 ms
            _unsigned_bits(2000, 24),  # DF406 = 2000 * 2^-31 ms
            _unsigned_bits(120, 10),  # DF407 extended lock indicator
            _unsigned_bits(1, 1),  # DF420 half-cycle ambiguity
            _unsigned_bits(680, 10),  # DF408 = 42.5 dB-Hz
        )
    )
    payload_bits += "0" * (-len(payload_bits) % 8)
    payload = int(payload_bits, 2).to_bytes(len(payload_bits) // 8, "big")
    frame_without_crc = b"\xd3" + len(payload).to_bytes(2, "big") + payload
    return frame_without_crc + crc2bytes(frame_without_crc)


def _rtcm_text_attrs(counter_attr: str, char_prefix: str, value: str) -> dict[str, object]:
    attrs: dict[str, object] = {counter_attr: len(value)}
    for idx, char in enumerate(value, start=1):
        attrs[f"{char_prefix}_{idx:02d}"] = char
    return attrs


class _FakeRTCMMessage:
    def __init__(self, identity: str, **attrs):
        self.identity = identity
        for key, value in attrs.items():
            setattr(self, key, value)


@pytest.mark.parametrize(("message_id", "satellite_id", "signal_id"), MSM6_CASES)
def test_rtcm_handler_decodes_real_msm6_frames(message_id, satellite_id, signal_id):
    patch_pyrtcm_glonass_g3()
    message = RTCMReader.parse(_build_msm6_frame(message_id))
    handler = CoreRTCMHandler(
        reference_utc=datetime(2026, 6, 22, tzinfo=timezone.utc),
        compute_geometry=False,
    )

    epoch = handler.process_message(message)

    signal = epoch.satellites[satellite_id].signals[signal_id]
    speed_of_light = 299_792_458.0
    range_ms = speed_of_light / 1000.0
    expected_rough_range = (70.0 + 0.25) * range_ms
    signal_frequency, _ = get_freq(signal_id, satellite_id)
    assert signal.pseudorange == pytest.approx(expected_rough_range + (1000 * 2**-29) * range_ms)
    assert signal.phase == pytest.approx(
        (expected_rough_range + (2000 * 2**-31) * range_ms) * signal_frequency / speed_of_light
    )
    assert signal.snr == 42.5
    assert signal.lock_time == 120
    assert signal.half_cycle == 1
    assert signal.doppler is None


def test_msm6_rinex_observations_omit_doppler_value():
    message = RTCMReader.parse(_build_msm6_frame("1076"))
    epoch = CoreRTCMHandler(
        reference_utc=datetime(2026, 6, 22, tzinfo=timezone.utc),
        compute_geometry=False,
    ).process_message(message)

    prepared = RINEX3Writer("unused.rnx")._prepare_observations(epoch.satellites)
    observation_codes = [item["code"] for item in prepared[0]["observations"]]

    assert observation_codes == ["C1C", "L1C", "S1C"]


@pytest.mark.parametrize("detector", OBS_TYPE_DETECTORS)
def test_msm6_auto_detected_rinex_header_omits_doppler_type(detector):
    message = RTCMReader.parse(_build_msm6_frame("1076"))
    epoch = CoreRTCMHandler(
        reference_utc=datetime(2026, 6, 22, tzinfo=timezone.utc),
        compute_geometry=False,
    ).process_message(message)

    assert detector(epoch.satellites)["G"] == ["C1C", "L1C", "S1C"]


def test_msm6_offline_rinex_header_detection_omits_doppler_type():
    message = RTCMReader.parse(_build_msm6_frame("1076"))
    epoch = CoreRTCMHandler(
        reference_utc=datetime(2026, 6, 22, tzinfo=timezone.utc),
        compute_geometry=False,
    ).process_message(message)

    assert rtcm_to_rinex._detect_sys_obs_types([epoch])["G"] == ["C1C", "L1C", "S1C"]


def test_msm6_missing_doppler_formats_as_blank_for_monitoring():
    message = RTCMReader.parse(_build_msm6_frame("1076"))
    epoch = CoreRTCMHandler(
        reference_utc=datetime(2026, 6, 22, tzinfo=timezone.utc),
        compute_geometry=False,
    ).process_message(message)
    signal = epoch.satellites["G03"].signals["1C"]

    assert format_optional_observation(signal.doppler, precision=3) == ""
    assert format_optional_observation(0.0, precision=3) == "0.000"


def test_mixed_reader_passes_msm6_frame_to_observation_handler():
    frame = _build_msm6_frame("1076")
    raw, message = MixedGNSSReader(io.BytesIO(frame)).read()

    epoch = CoreRTCMHandler(
        reference_utc=datetime(2026, 6, 22, tzinfo=timezone.utc),
        compute_geometry=False,
    ).process_message(message)

    assert raw == frame
    assert message.identity == "1076"
    assert epoch.satellites["G03"].signals["1C"].snr == 42.5


@pytest.mark.parametrize("reader_type", MIXED_READER_TYPES)
def test_mixed_reader_accumulates_short_reads_before_parsing_rtcm(reader_type):
    frame = _build_msm6_frame("1076")

    raw, message = reader_type(_FragmentedReadStream(frame, max_chunk=1)).read()

    assert raw == frame
    assert message.identity == "1076"


@pytest.mark.parametrize("handler_type", RTCM_HANDLER_TYPES)
def test_glonass_msm6_uses_transmitted_day_of_week(handler_type):
    message = RTCMReader.parse(_build_msm6_frame("1086", glonass_day=5))
    handler = handler_type(
        reference_utc=datetime(2026, 6, 25, tzinfo=timezone.utc),  # Thursday
        compute_geometry=False,
    )

    epoch = handler.process_message(message)

    assert epoch.utc_datetime == datetime(2026, 6, 26, 9, 0, tzinfo=timezone.utc)
    assert epoch.gps_time == pytest.approx(5 * 86_400 + 32_418)


@pytest.mark.parametrize("handler_type", RTCM_HANDLER_TYPES)
def test_glonass_msm6_rolls_transmitted_day_back_before_utc_midnight(handler_type):
    message = RTCMReader.parse(
        _build_msm6_frame(
            "1086",
            glonass_day=3,  # Wednesday in GLONASS time (UTC+3)
            glonass_milliseconds=(4 * 60 + 12) * 1000,
        )
    )
    handler = handler_type(
        reference_utc=datetime(2026, 6, 30, 21, 4, 12, tzinfo=timezone.utc),  # Tuesday UTC
        compute_geometry=False,
    )

    epoch = handler.process_message(message)

    assert epoch.utc_datetime == datetime(2026, 6, 30, 21, 4, 12, tzinfo=timezone.utc)
    assert epoch.gps_time == pytest.approx(2 * 86_400 + (21 * 3600 + 4 * 60 + 30))


@pytest.mark.parametrize("handler_type", RTCM_HANDLER_TYPES)
def test_rtcm_handler_captures_1033_receiver_and_antenna_metadata(handler_type):
    attrs = {"DF003": 4}
    attrs.update(_rtcm_text_attrs("DF029", "DF030", "LEIAR25.R4 NONE"))
    attrs.update(_rtcm_text_attrs("DF032", "DF033", "725235"))
    attrs.update(_rtcm_text_attrs("DF227", "DF228", "SEPT MOSAIC-X5"))
    attrs.update(_rtcm_text_attrs("DF229", "DF230", "4.14.4"))
    attrs.update(_rtcm_text_attrs("DF231", "DF232", "4014259"))

    handler = handler_type(compute_geometry=False)
    handler.process_message(_FakeRTCMMessage("1033", **attrs))

    assert handler.last_reference_station_id == 4
    assert handler.last_antenna_descriptor == "LEIAR25.R4 NONE"
    assert handler.last_antenna_serial_number == "725235"
    assert handler.last_receiver_type_descriptor == "SEPT MOSAIC-X5"
    assert handler.last_receiver_firmware_version == "4.14.4"
    assert handler.last_receiver_serial_number == "4014259"
