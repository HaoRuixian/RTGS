"""
Handles RTCM stream parsing based on strict RTCM 10403.3 Payload Definitions.
Adapted for pyrtcm's flattened attribute structure.
"""
import numpy as np
import sys
import io
from contextlib import redirect_stderr
from datetime import datetime, timezone
from core.data_models import EpochObservation, SatelliteState, SignalData
from core.gnss_time import GNSSTime
from core.geo_utils import calculate_az_el, get_freq
import core.BE2pos as BE2pos 
from core.global_config import get_global_config, update_general_settings
from core.broadcast_ephemeris import get_shared_broadcast_ephemeris
from core.ssr import (
    SsrClockCorrection,
    SsrCorrectionStore,
    SsrOrbitCorrection,
    SsrPhaseBias,
    SsrPhaseBiasCorrection,
)
from core.unicore import UnicoreMessage
import threading
import math

# Global singleton instance
_shared_rtcm_handler = None


SSR_MESSAGE_DEFINITIONS = {
    "1057": {"kind": "orbit", "system": "G", "time": "DF385", "sat": "DF068", "iod": "DF071"},
    "1058": {"kind": "clock", "system": "G", "time": "DF385", "sat": "DF068"},
    "1059": {"kind": "code_bias", "system": "G", "time": "DF385", "sat": "DF068", "signal": "DF380"},
    "1060": {"kind": "combined", "system": "G", "time": "DF385", "sat": "DF068", "iod": "DF071"},
    "1061": {"kind": "ura", "system": "G", "time": "DF385", "sat": "DF068"},
    "1062": {"kind": "high_rate_clock", "system": "G", "time": "DF385", "sat": "DF068"},
    "1063": {"kind": "orbit", "system": "R", "time": "DF386", "sat": "DF384", "iod": "DF392"},
    "1064": {"kind": "clock", "system": "R", "time": "DF386", "sat": "DF384"},
    "1065": {"kind": "code_bias", "system": "R", "time": "DF386", "sat": "DF384", "signal": "DF381"},
    "1066": {"kind": "combined", "system": "R", "time": "DF386", "sat": "DF384", "iod": "DF392"},
    "1067": {"kind": "ura", "system": "R", "time": "DF386", "sat": "DF384"},
    "1068": {"kind": "high_rate_clock", "system": "R", "time": "DF386", "sat": "DF384"},
    "1240": {"kind": "orbit", "system": "E", "time": "DF458", "sat": "DF252", "iod": "DF459"},
    "1241": {"kind": "clock", "system": "E", "time": "DF458", "sat": "DF252"},
    "1242": {"kind": "code_bias", "system": "E", "time": "DF458", "sat": "DF252", "signal": "DF382"},
    "1243": {"kind": "combined", "system": "E", "time": "DF458", "sat": "DF252", "iod": "DF459"},
    "1244": {"kind": "ura", "system": "E", "time": "DF458", "sat": "DF252"},
    "1245": {"kind": "high_rate_clock", "system": "E", "time": "DF458", "sat": "DF252"},
    "1246": {"kind": "orbit", "system": "J", "time": "DF460", "sat": "DF429", "iod": "DF434"},
    "1247": {"kind": "clock", "system": "J", "time": "DF460", "sat": "DF429"},
    "1248": {"kind": "code_bias", "system": "J", "time": "DF460", "sat": "DF429", "signal": "DF461"},
    "1249": {"kind": "combined", "system": "J", "time": "DF460", "sat": "DF429", "iod": "DF434"},
    "1250": {"kind": "ura", "system": "J", "time": "DF460", "sat": "DF429"},
    "1251": {"kind": "high_rate_clock", "system": "J", "time": "DF460", "sat": "DF429"},
    "1252": {"kind": "orbit", "system": "S", "time": "DF462", "sat": "DF463", "iod": "DF469"},
    "1253": {"kind": "clock", "system": "S", "time": "DF462", "sat": "DF463"},
    "1254": {"kind": "code_bias", "system": "S", "time": "DF462", "sat": "DF463", "signal": "DF464"},
    "1255": {"kind": "combined", "system": "S", "time": "DF462", "sat": "DF463", "iod": "DF469"},
    "1256": {"kind": "ura", "system": "S", "time": "DF462", "sat": "DF463"},
    "1257": {"kind": "high_rate_clock", "system": "S", "time": "DF462", "sat": "DF463"},
    "1258": {"kind": "orbit", "system": "C", "time": "DF465", "sat": "DF488", "iod": "DF471"},
    "1259": {"kind": "clock", "system": "C", "time": "DF465", "sat": "DF488"},
    "1260": {"kind": "code_bias", "system": "C", "time": "DF465", "sat": "DF488", "signal": "DF467"},
    "1261": {"kind": "combined", "system": "C", "time": "DF465", "sat": "DF488", "iod": "DF471"},
    "1262": {"kind": "ura", "system": "C", "time": "DF465", "sat": "DF488"},
    "1263": {"kind": "high_rate_clock", "system": "C", "time": "DF465", "sat": "DF488"},
}


IGS_SSR_MESSAGE_DEFINITIONS = {
    21: {"kind": "orbit", "system": "G"},
    22: {"kind": "clock", "system": "G"},
    23: {"kind": "combined", "system": "G"},
    24: {"kind": "high_rate_clock", "system": "G"},
    25: {"kind": "code_bias", "system": "G"},
    26: {"kind": "phase_bias", "system": "G"},
    27: {"kind": "ura", "system": "G"},
    41: {"kind": "orbit", "system": "R"},
    42: {"kind": "clock", "system": "R"},
    43: {"kind": "combined", "system": "R"},
    44: {"kind": "high_rate_clock", "system": "R"},
    45: {"kind": "code_bias", "system": "R"},
    46: {"kind": "phase_bias", "system": "R"},
    47: {"kind": "ura", "system": "R"},
    61: {"kind": "orbit", "system": "E"},
    62: {"kind": "clock", "system": "E"},
    63: {"kind": "combined", "system": "E"},
    64: {"kind": "high_rate_clock", "system": "E"},
    65: {"kind": "code_bias", "system": "E"},
    66: {"kind": "phase_bias", "system": "E"},
    67: {"kind": "ura", "system": "E"},
    81: {"kind": "orbit", "system": "J"},
    82: {"kind": "clock", "system": "J"},
    83: {"kind": "combined", "system": "J"},
    84: {"kind": "high_rate_clock", "system": "J"},
    85: {"kind": "code_bias", "system": "J"},
    86: {"kind": "phase_bias", "system": "J"},
    87: {"kind": "ura", "system": "J"},
    101: {"kind": "orbit", "system": "C"},
    102: {"kind": "clock", "system": "C"},
    103: {"kind": "combined", "system": "C"},
    104: {"kind": "high_rate_clock", "system": "C"},
    105: {"kind": "code_bias", "system": "C"},
    106: {"kind": "phase_bias", "system": "C"},
    107: {"kind": "ura", "system": "C"},
    121: {"kind": "orbit", "system": "S"},
    122: {"kind": "clock", "system": "S"},
    123: {"kind": "combined", "system": "S"},
    124: {"kind": "high_rate_clock", "system": "S"},
    125: {"kind": "code_bias", "system": "S"},
    126: {"kind": "phase_bias", "system": "S"},
    127: {"kind": "ura", "system": "S"},
}


SSR_PHASE_BIAS_SYSTEMS = {
    "1265": "G",
    "1266": "R",
    "1267": "E",
    "1268": "J",
    "1269": "S",
    "1270": "C",
}


SSR_SIGNAL_RINEX_RTCM = {
    "G": {
        0: "1C", 1: "1P", 2: "1W", 5: "2C", 6: "2D", 7: "2S", 8: "2L", 9: "2X",
        10: "2P", 11: "2W", 14: "5I", 15: "5Q", 16: "5X", 17: "1S", 18: "1L", 19: "1X",
    },
    "R": {
        0: "1C", 1: "1P", 2: "2C", 3: "2P", 4: "4A", 5: "4B", 6: "4X",
        7: "6A", 8: "6B", 9: "6X", 10: "3I", 11: "3Q", 12: "3X",
    },
    "E": {
        0: "1A", 1: "1B", 2: "1C", 3: "1X", 4: "1Z", 5: "5I", 6: "5Q", 7: "5X",
        8: "7I", 9: "7Q", 10: "7X", 11: "8I", 12: "8Q", 13: "8X",
        14: "6A", 15: "6B", 16: "6C", 17: "6X", 18: "6Z",
    },
    "J": {
        0: "1C", 1: "1S", 2: "1L", 3: "2S", 4: "2L", 5: "2X", 6: "5I", 7: "5Q",
        8: "5X", 9: "6S", 10: "6L", 11: "6X", 12: "1X",
    },
    "S": {0: "1C", 1: "5I", 2: "5Q", 3: "5X"},
    "C": {
        0: "2I", 1: "2Q", 2: "2X", 3: "6I", 4: "6Q", 5: "6X", 6: "7I", 7: "7Q",
        8: "7X", 9: "1D", 10: "1P", 11: "1X", 12: "5D", 13: "5P", 14: "5X", 15: "1A",
        18: "6A",
    },
}

SSR_SIGNAL_RINEX_IGS = {
    "G": {
        0: "1C", 1: "1P", 2: "1W", 3: "1S", 4: "1L", 5: "2C", 6: "2D", 7: "2S",
        8: "2L", 10: "2P", 11: "2W", 14: "5I", 15: "5Q",
    },
    "R": {
        0: "1C", 1: "1P", 2: "2C", 3: "2P", 4: "4A", 5: "4B", 6: "6A", 7: "6B",
        8: "3I", 9: "3Q",
    },
    "E": {
        0: "1A", 1: "1B", 2: "1C", 5: "5I", 6: "5Q", 8: "7I", 9: "7Q",
        14: "6A", 15: "6B", 16: "6C",
    },
    "J": {
        0: "1C", 1: "1S", 2: "1L", 3: "2S", 4: "2L", 6: "5I", 7: "5Q",
        9: "6S", 10: "6L", 17: "6E",
    },
    "S": {0: "1C", 1: "5I", 2: "5Q"},
    "C": {
        0: "2I", 1: "2Q", 3: "6I", 4: "6Q", 6: "7I", 7: "7Q",
        9: "1D", 10: "1P", 12: "5D", 13: "5P", 15: "1A", 18: "6A",
    },
}


def _getbitu(buff: bytes, pos: int, length: int) -> int:
    bits = 0
    for index in range(pos, pos + length):
        bits = (bits << 1) | ((buff[index // 8] >> (7 - index % 8)) & 1)
    return bits


def _getbits(buff: bytes, pos: int, length: int) -> int:
    value = _getbitu(buff, pos, length)
    sign_bit = 1 << (length - 1)
    if value & sign_bit:
        value -= 1 << length
    return value


class _BitReader:
    def __init__(self, data: bytes, start_bit: int, end_bit: int) -> None:
        self.data = data
        self.pos = start_bit
        self.end_bit = end_bit

    def unsigned(self, length: int) -> int:
        if self.pos + length > self.end_bit:
            raise ValueError("SSR message ended before all fields were decoded")
        value = _getbitu(self.data, self.pos, length)
        self.pos += length
        return value

    def signed(self, length: int, scale: float) -> float:
        if self.pos + length > self.end_bit:
            raise ValueError("SSR message ended before all fields were decoded")
        value = _getbits(self.data, self.pos, length)
        self.pos += length
        return float(value) * scale


class RTCMHandler:
    def __init__(self, reference_utc=None, compute_geometry=True):
        self.broadcast_eph = get_shared_broadcast_ephemeris()
        self.ssr_corrections = SsrCorrectionStore()
        self.lock = threading.Lock()
        self.last_gps_week = None  # Track GPS week for continuity
        self.last_station_coords = None  # Store coordinates from 1005/1006 messages
        self.reference_utc = self._normalize_reference_utc(reference_utc)
        self.last_utc_by_system = {}
        self.compute_geometry = bool(compute_geometry)
        self.last_reference_station_id = None
        self.last_antenna_descriptor = ""
        self.last_antenna_serial_number = ""
        self.last_receiver_type_descriptor = ""
        self.last_receiver_firmware_version = ""
        self.last_receiver_serial_number = ""

    @staticmethod
    def _normalize_reference_utc(reference_utc):
        if reference_utc is None:
            return None
        if isinstance(reference_utc, datetime):
            if reference_utc.tzinfo is None:
                return reference_utc.replace(tzinfo=timezone.utc)
            return reference_utc.astimezone(timezone.utc)
        return None

    def _resolve_gps_week(self, sys_id: str, gps_seconds: float, default_week: int) -> int:
        """Pick the GPS week nearest to the system's recent timeline."""
        anchor = self.last_utc_by_system.get(sys_id) or self.reference_utc
        if anchor is None:
            anchor = datetime.utcnow().replace(tzinfo=timezone.utc)

        candidate_weeks = [default_week - 1, default_week, default_week + 1]
        best_week = min(
            candidate_weeks,
            key=lambda week: abs((GNSSTime.gps_to_utc_datetime(week, gps_seconds) - anchor).total_seconds()),
        )
        return best_week

    def _reference_utc_for_glonass_day(self):
        """Prefer a recent non-GLONASS epoch when resolving GLONASS day-of-week offline."""
        for sys_id in ("G", "E", "C", "J", "I", "S"):
            anchor = self.last_utc_by_system.get(sys_id)
            if anchor is not None:
                return anchor

        for sys_id, anchor in self.last_utc_by_system.items():
            if sys_id != "R" and anchor is not None:
                return anchor

        return self.reference_utc

    @staticmethod
    def _utc_day_of_week(utc_dt):
        """Return UTC day-of-week with GPS-style numbering (0=Sunday..6=Saturday)."""
        anchor = utc_dt
        if anchor is None:
            anchor = datetime.utcnow().replace(tzinfo=timezone.utc)
        elif anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        else:
            anchor = anchor.astimezone(timezone.utc)
        return anchor.isoweekday() % 7

    @staticmethod
    def _normalize_satellite_number(sys_id: str, prn: int) -> int:
        """
        Normalize constellation-specific RTCM PRN numbering to display keys.

        QZSS MSM uses actual PRNs 193-202 in pyrtcm, while downstream code and
        RINEX formatting expect J01-J10 style identifiers.
        """
        if sys_id == 'J' and prn >= 193:
            return prn - 192
        return prn

    @staticmethod
    def _is_scaled_msm_sentinel(value, sentinel_value: float) -> bool:
        """Return True when a pyrtcm-scaled MSM field carries its invalid value."""
        if value is None:
            return True
        try:
            return math.isclose(float(value), sentinel_value, rel_tol=0.0, abs_tol=1e-12)
        except (TypeError, ValueError):
            return True

    # Time conversions delegated to core.gnss_time.GNSSTime

    def process_message(self, msg, epoch_data=None):
        """
        Main entry point for RTCM message processing.
        Includes error handling for pyrtcm parsing issues.
        
        Note: Unsupported or partially defined message types may fail during parsing.
        These are silently skipped without error output and will not affect epoch processing.
        """
        try:
            # Suppress stderr during attribute access to avoid printing errors from 
            # unsupported RTCM message types with incomplete third-party definitions
            with redirect_stderr(io.StringIO()):
                msg_id = msg.identity
        except (ValueError, AttributeError, TypeError):
            # pyrtcm parsing error (e.g., negative shift count for unsupported DF fields)
            # Gracefully skip this message and return current epoch data
            return epoch_data

        try:
            # --- Ephemeris Processing ---
            if isinstance(msg, UnicoreMessage) or getattr(msg, "protocol", None) == "UNICORE":
                return self._handle_unicore_obs(msg)
            elif msg_id == "1019":
                self._handle_gps_eph(msg)
            elif msg_id == "1020":
                self._handle_glo_eph(msg)
            elif msg_id == "1044":
                self._handle_qzs_eph(msg)
            elif msg_id in ["1045", "1046"]:
                self._handle_gal_eph(msg)
            elif msg_id == "1041":
                self._handle_irnss_eph(msg)
            elif msg_id in ["1042", "63"]:  # 1042 is standard BDS
                self._handle_bds_eph(msg)
            elif str(msg_id).startswith("SBAS_RAW"):
                self._handle_sbas_raw(msg)
                
            # --- MSM Observations ---
            elif msg_id[:3] in ["107", "108", "109", "110", "111", "112", "113"]:
                return self._handle_msm_obs(msg, epoch_data)
                
            # --- Station Coordinates ---
            elif msg_id in ["1005", "1006"]:
                # Store station coordinates for monitoring module to use.
                # Will only update global config if monitoring mode is active.
                try:
                    coords = [
                        float(getattr(msg, "DF025")),
                        float(getattr(msg, "DF026")),
                        float(getattr(msg, "DF027")),
                    ]
                except (AttributeError, ValueError, TypeError):
                    coords = None
                if coords is not None and all(math.isfinite(value) for value in coords):
                    self.last_station_coords = coords

            # --- Station receiver/antenna descriptors ---
            elif msg_id in ["1007", "1008", "1033"]:
                self._handle_station_descriptor(msg)
            
            # --- RTCM 10403.3 Standard: Network RTK Correction Messages (1015-1017, 1037-1039) ---
            # These provide ionospheric and geometric corrections between reference stations
            elif msg_id == "1015":
                return self._handle_gps_iono_correction_diff(msg, epoch_data)
            elif msg_id == "1016":
                return self._handle_gps_geometric_correction_diff(msg, epoch_data)
            elif msg_id == "1017":
                return self._handle_gps_combined_correction_diff(msg, epoch_data)
            elif msg_id == "1037":
                return self._handle_glo_iono_correction_diff(msg, epoch_data)
            elif msg_id == "1038":
                return self._handle_glo_geometric_correction_diff(msg, epoch_data)
            elif msg_id == "1039":
                return self._handle_glo_combined_correction_diff(msg, epoch_data)
            
            # --- RTCM 10403.3 Standard: GLONASS Code-Phase Biases (Message 1230) ---
            # Note: Message 1230 is GLONASS L1/L2 Code-Phase Biases, NOT ionospheric correction
            elif msg_id == "1230":
                return self._handle_glo_code_phase_bias(msg, epoch_data)

            elif msg_id == "4076":
                return self._handle_igs_ssr_message(msg, epoch_data)

            elif msg_id in SSR_PHASE_BIAS_SYSTEMS:
                return self._handle_ssr_phase_bias_message(msg, epoch_data)

            elif msg_id in SSR_MESSAGE_DEFINITIONS:
                return self._handle_ssr_message(msg, epoch_data)
            
        except (ValueError, AttributeError, TypeError, KeyError):
            # Silently skip messages with parsing errors
            pass
        
        return epoch_data

    @staticmethod
    def _extract_rtcm_text(msg, counter_attr, char_prefix):
        """Extract a grouped RTCM character field as a decoded text value.

        ``pyrtcm`` normally exposes ``CHA`` groups as ``DF030_01``...
        ``DF030_N`` strings.  Older releases and a few compatible readers may
        expose an ungrouped string, bytes, or integer character codes instead;
        accept all of those representations so 1033 metadata is not silently
        discarded.
        """
        try:
            count = int(getattr(msg, counter_attr, 0) or 0)
        except (TypeError, ValueError):
            count = 0

        def _decode_char(value):
            if value is None:
                return ""
            if isinstance(value, bytes):
                return value.decode("latin-1", errors="replace")
            if isinstance(value, int):
                try:
                    return chr(value) if 0 <= value <= 0xFF else str(value)
                except (TypeError, ValueError):
                    return str(value)
            return str(value)

        # Some parsers concatenate character fields onto the base attribute.
        direct_value = getattr(msg, char_prefix, None)
        if isinstance(direct_value, (str, bytes)) and count <= 0:
            return _decode_char(direct_value).strip()
        if isinstance(direct_value, (list, tuple)) and count <= 0:
            return "".join(_decode_char(value) for value in direct_value).strip()

        chars = []
        for idx in range(1, max(0, count) + 1):
            value = getattr(msg, f"{char_prefix}_{idx:02d}", None)
            if value is None:
                # Be tolerant of readers that do not zero-pad group indices.
                value = getattr(msg, f"{char_prefix}_{idx}", None)
            if value is not None:
                chars.append(_decode_char(value))

        # If the counter is missing or wrong, a direct value is still more
        # useful than returning an empty descriptor.
        if not chars and direct_value is not None:
            if isinstance(direct_value, (list, tuple)):
                chars.extend(_decode_char(value) for value in direct_value)
            else:
                chars.append(_decode_char(direct_value))
        return "".join(chars).strip()

    def _handle_station_descriptor(self, msg) -> None:
        """Capture RTCM 1007/1008/1033 metadata for RINEX header records."""
        try:
            self.last_reference_station_id = int(getattr(msg, "DF003"))
        except (TypeError, ValueError, AttributeError):
            pass

        antenna_descriptor = self._extract_rtcm_text(msg, "DF029", "DF030")
        if antenna_descriptor:
            self.last_antenna_descriptor = antenna_descriptor

        antenna_serial = self._extract_rtcm_text(msg, "DF032", "DF033")
        if antenna_serial:
            self.last_antenna_serial_number = antenna_serial

        receiver_type = self._extract_rtcm_text(msg, "DF227", "DF228")
        if receiver_type:
            self.last_receiver_type_descriptor = receiver_type

        receiver_firmware = self._extract_rtcm_text(msg, "DF229", "DF230")
        if receiver_firmware:
            self.last_receiver_firmware_version = receiver_firmware

        receiver_serial = self._extract_rtcm_text(msg, "DF231", "DF232")
        if receiver_serial:
            self.last_receiver_serial_number = receiver_serial

    def _handle_unicore_obs(self, msg):
        """Convert a decoded Unicore raw-observation log into an epoch."""
        config = get_global_config()
        target_systems = getattr(config, "target_systems", None)
        epoch_data = msg.to_epoch(target_systems=target_systems)
        epoch_time = getattr(epoch_data, "utc_datetime", None)
        if epoch_time is not None:
            for sys_id in {sat_key[0] for sat_key in epoch_data.satellites.keys() if sat_key}:
                self.last_utc_by_system[sys_id] = epoch_time
        return epoch_data

    def _update_cache(self, key, new_eph, time_tag_key='toe'):
        """Update ephemeris cache using shared BroadcastEphemeris."""
        self.broadcast_eph.cache_ephemeris(new_eph, time_key=time_tag_key)
    
    def apply_station_coordinates(self):
        """
        Apply stored station coordinates (from 1005/1006 messages) to global config.
        This method should only be called from the monitoring module.
        
        Returns:
            Coordinates list [X, Y, Z] if available and applied, None otherwise.
        """
        if self.last_station_coords is not None:
            try:
                update_general_settings({'approx_rec_pos': self.last_station_coords})
                return self.last_station_coords
            except Exception:
                pass
        return None

    # -------------------------------------------------------------------------
    # GPS Parsing (Msg 1019)
    # -------------------------------------------------------------------------
    def _handle_gps_eph(self, msg):
        """
        Parse RTCM 1019 - GPS Broadcast Ephemeris.
        Reference: RTCM 10403.3 Table 3.5-21
        """
        eph = self.broadcast_eph.extract_gps_ephemeris(msg)
        if eph:
            self.broadcast_eph.cache_ephemeris(eph, time_key='toe')

    # -------------------------------------------------------------------------
    # Galileo Parsing (Msg 1045/1046)
    # -------------------------------------------------------------------------
    def _handle_gal_eph(self, msg):
        """
        Parse RTCM 1045/1046 - Galileo Broadcast Ephemeris.
        Reference: RTCM 10403.3 Table 3.5-31/32
        """
        eph = self.broadcast_eph.extract_galileo_ephemeris(msg)
        if eph:
            self.broadcast_eph.cache_ephemeris(eph, time_key='toe')

    # -------------------------------------------------------------------------
    # GLONASS Parsing (Msg 1020)
    # -------------------------------------------------------------------------
    def _handle_glo_eph(self, msg):
        """
        Parse RTCM 1020 - GLONASS Broadcast Ephemeris.
        Reference: RTCM 10403.3 Table 3.5-25/26
        """
        eph = self.broadcast_eph.extract_glonass_ephemeris(msg)
        if eph:
            self.broadcast_eph.cache_ephemeris(eph, time_key='tb')
            
    # -------------------------------------------------------------------------
    # BeiDou Parsing (Msg 1042)
    # -------------------------------------------------------------------------
    def _handle_bds_eph(self, msg):
        """
        Parse RTCM 1042 - BeiDou Broadcast Ephemeris.
        Reference: RTCM 10403.3 Table 3.5-40/41
        """
        eph = self.broadcast_eph.extract_bds_ephemeris(msg)
        if eph:
            self.broadcast_eph.cache_ephemeris(eph, time_key='toe')

    def _handle_qzs_eph(self, msg):
        """Parse RTCM 1044 - QZSS Broadcast Ephemeris."""
        eph = self.broadcast_eph.extract_qzss_ephemeris(msg)
        if eph:
            self.broadcast_eph.cache_ephemeris(eph, time_key='toe')

    def _handle_irnss_eph(self, msg):
        """Parse RTCM 1041 - IRNSS/NavIC Broadcast Ephemeris."""
        eph = self.broadcast_eph.extract_irnss_ephemeris(msg)
        if eph:
            self.broadcast_eph.cache_ephemeris(eph, time_key='toe')

    def _handle_sbas_raw(self, msg):
        """Parse SBAS raw navigation frames and cache GEO ephemeris (seph)."""
        eph = self.broadcast_eph.extract_sbas_ephemeris(msg)
        if eph:
            self.broadcast_eph.cache_ephemeris(eph, time_key='t0')

    def _handle_msm_obs(self, msg, epoch_data=None):
            """
            Parse RTCM 3.2 MSM observation messages.
            If epoch_data is provided, adds observations to it; otherwise creates new one.
            """
            # Constants
            CLIGHT = 299792458.0
            RANGE_MS = CLIGHT / 1000.0
            FINE_CODE_INVALID_MS = -(2 ** -10)
            FINE_PHASE_INVALID_MS = -(2 ** -8)
            FINE_RATE_INVALID_MPS = -16384 * 0.0001

            msg_id = msg.identity
            sys_prefix = msg_id[:3]

            sys_config = {
                "107": {"sys": "G", "time_df": "DF004", "type": "GPS"},
                "108": {"sys": "R", "time_df": "DF034", "type": "GLO"},
                "109": {"sys": "E", "time_df": "DF248", "type": "GAL"},
                "110": {"sys": "S", "time_df": "DF004", "type": "SBS"},
                "111": {"sys": "J", "time_df": "DF428", "type": "QZS"},
                "112": {"sys": "C", "time_df": "DF427", "type": "BDS"},
                "113": {"sys": "I", "time_df": "DF546", "type": "IRN"},
            }

            if sys_prefix not in sys_config:
                return None

            cfg = sys_config[sys_prefix]
            sys_id = cfg["sys"]
            sys_type = cfg["type"] # Used for BE2pos
            msm_variant = int(str(msg_id)[-1]) if str(msg_id)[-1].isdigit() else 7
            if msm_variant not in (1, 2, 3, 4, 5, 6, 7):
                return epoch_data

            has_code = msm_variant in (1, 3, 4, 5, 6, 7)
            has_phase = msm_variant in (2, 3, 4, 5, 6, 7)
            has_snr = msm_variant in (4, 5, 6, 7)
            has_doppler = msm_variant in (5, 7)
            uses_extended_signal_fields = msm_variant in (6, 7)

            config = get_global_config()
            if sys_id not in config.target_systems:
                return None

            # Epoch Time (provided in milliseconds per system definitions)
            time_attr = cfg["time_df"]
            if not hasattr(msg, time_attr):
                return None
            raw_ms = int(getattr(msg, time_attr))
            epoch_time_s = raw_ms / 1000.0

            # Determine GPS week and seconds-of-week corresponding to this epoch
            # Default: assume current GPS week and align seconds-of-week, adjust per system
            GPS_WEEK_SECONDS = 7 * 24 * 3600
            current_gps_week = GNSSTime.current_gps_week(self.reference_utc)

            if sys_id in ['G', 'J', 'S', 'I']:
                # GPS TOW: directly seconds within GPS week
                gps_seconds = epoch_time_s % GPS_WEEK_SECONDS

            elif sys_id == 'C':
                # BeiDou TOW (BDT): field is milliseconds since BDS week start.
                # BDS TOW is typically 14s less than GPS TOW for same epoch.
                # Convert by adding 14s and assume current GPS week.
                gps_seconds = (epoch_time_s + 14.0) % GPS_WEEK_SECONDS

            elif sys_id == 'E':
                # Galileo TOW (GST): treat as seconds-of-week and align to current GPS week
                gps_seconds = epoch_time_s % GPS_WEEK_SECONDS

            elif sys_id == 'R':
                # GLONASS MSM time is the composite DF416 day-of-week plus DF034
                # milliseconds-of-day. DF416=7 means unknown, in which case the
                # latest non-GLONASS epoch remains the safest day anchor.
                try:
                    transmitted_day = int(getattr(msg, "DF416", 7))
                except (TypeError, ValueError):
                    transmitted_day = 7
                has_transmitted_day = 0 <= transmitted_day <= 6
                if has_transmitted_day:
                    day_index = transmitted_day
                else:
                    day_index = self._utc_day_of_week(self._reference_utc_for_glonass_day())
                # Subtract 3 hours to convert UTC(SU)+3h -> UTC seconds-of-day
                seconds_of_day = (epoch_time_s) - 3 * 3600.0
                # During 00:00-03:00 GLONASS time, UTC is still on the
                # previous day. DF416 has already advanced, so carry the
                # subtraction into the transmitted day-of-week as well.
                if has_transmitted_day and seconds_of_day < 0.0:
                    day_index = (day_index - 1) % 7
                # Ensure within 0..86400 range
                seconds_of_day = seconds_of_day % (24 * 3600)
                gps_seconds = (day_index * 24 * 3600) + seconds_of_day + 18

            else:
                # Fallback: treat as seconds-of-week in current GPS week
                gps_seconds = epoch_time_s % GPS_WEEK_SECONDS

            gps_week = self._resolve_gps_week(sys_id, gps_seconds, current_gps_week)

            # Align gps_seconds to current week boundary if there is large discrepancy
            # Ensure 0 <= gps_seconds < GPS_WEEK_SECONDS
            epoch_time = gps_seconds % GPS_WEEK_SECONDS

            # Convert to UTC datetime
            utc_datetime = GNSSTime.gps_to_utc_datetime(gps_week, gps_seconds)
            self.last_utc_by_system[sys_id] = utc_datetime
            
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=epoch_time, utc_datetime=utc_datetime)
            else:
                epoch_data.gps_time = epoch_time
                epoch_data.utc_datetime = utc_datetime

            # ------------------------------ Cell Parsing -------------------------------
            cell_prn_map = {}
            unique_prns = set()
            n_cell_found = int(getattr(msg, "NCell", 0) or 0)
            max_cells = max(n_cell_found, 64)

            for i in range(1, max_cells + 1):
                idx = f"{i:02d}"
                attr = f"CELLPRN_{idx}"
                if hasattr(msg, attr):
                    try:
                        prn = int(getattr(msg, attr))
                        cell_prn_map[i] = prn
                        unique_prns.add(prn)
                        n_cell_found = max(n_cell_found, i)
                    except ValueError:
                        continue
                elif i > n_cell_found:
                    break

            if n_cell_found == 0:
                return None

            prn_to_sat_idx = {}
            n_sat_found = int(getattr(msg, "NSat", 0) or 0)
            for sat_num in range(1, n_sat_found + 1):
                sat_idx = f"{sat_num:02d}"
                try:
                    prn_to_sat_idx[int(getattr(msg, f"PRN_{sat_idx}"))] = sat_idx
                except (AttributeError, TypeError, ValueError):
                    continue
            if not prn_to_sat_idx:
                sorted_prns = sorted(unique_prns)
                prn_to_sat_idx = {prn: f"{k + 1:02d}" for k, prn in enumerate(sorted_prns)}

            sat_data_cache = {}

            # ------------------------------ Process Satellites (Parse Observations) -------
            for i in range(1, n_cell_found + 1):
                if i not in cell_prn_map: continue

                idx = f"{i:02d}"
                raw_prn = cell_prn_map[i]
                sat_idx = prn_to_sat_idx.get(raw_prn)
                if sat_idx is None:
                    continue
                prn = self._normalize_satellite_number(sys_id, raw_prn)
                sat_key = f"{sys_id}{prn:02d}"

                # Create SatelliteState (but don't calculate position yet)
                if sat_key not in epoch_data.satellites:
                    sat_state = SatelliteState(sys_id, prn)
                    epoch_data.satellites[sat_key] = sat_state
                else:
                    sat_state = epoch_data.satellites[sat_key]

                # --- Extract satellite-level MSM data shared by all cells for this PRN ---
                if raw_prn not in sat_data_cache:
                    rng_int = getattr(msg, f"DF397_{sat_idx}", None)
                    rng_mod = getattr(msg, f"DF398_{sat_idx}", 0.0)
                    rate_rough = getattr(msg, f"DF399_{sat_idx}", None)

                    rough_range = None
                    if rng_int is not None and int(rng_int) != 255:
                        rough_range = (float(rng_int) + float(rng_mod or 0.0)) * RANGE_MS

                    rough_rate = None
                    if has_doppler and rate_rough is not None and int(rate_rough) != -8192:
                        rough_rate = float(rate_rough)

                    glonass_fcn = None
                    if sys_id == 'R' and hasattr(msg, f"DF419_{sat_idx}"):
                        try:
                            df419_value = int(getattr(msg, f"DF419_{sat_idx}"))
                            if 0 <= df419_value <= 13:
                                glonass_fcn = df419_value - 7
                        except (TypeError, ValueError):
                            glonass_fcn = None

                    sat_data_cache[raw_prn] = {
                        "r": rough_range,
                        "rr": rough_rate,
                        "fcn": glonass_fcn,
                    }

                rough_range = sat_data_cache[raw_prn]["r"]
                rough_rate = sat_data_cache[raw_prn]["rr"]

                # Parse Signal Data (Frequency lookup needs refining for GLONASS later)
                try:
                    sig_id = str(getattr(msg, f"CELLSIG_{idx}"))
                except AttributeError: continue
                
                # GLONASS FCN lookup from MSM5/7 satellite data, then shared ephemeris.
                fcn = sat_data_cache[raw_prn].get("fcn")
                if sys_id == 'R':
                    if fcn is None:
                        eph_for_fcn = self.broadcast_eph.get_ephemeris(sat_key)
                        if eph_for_fcn:
                            # prefer standardized key name, fallback to older variants if present
                            fcn = eph_for_fcn.get('frequency_channel', eph_for_fcn.get('FreqChannel', 0))
                    if fcn is None:
                        fcn = 0
                else:
                    fcn = 0

                freq, _ = get_freq(sig_id, sat_key, fcn)

                # --- Extract Observations (Range, Phase, Doppler, etc.) ---
                pr_attr = "DF405" if uses_extended_signal_fields else "DF400"
                cp_attr = "DF406" if uses_extended_signal_fields else "DF401"
                lock_attr = "DF407" if uses_extended_signal_fields else "DF402"
                snr_attr = "DF408" if uses_extended_signal_fields else "DF403"

                pr_fine = getattr(msg, f"{pr_attr}_{idx}", None)
                pseudorange = 0.0
                if (
                    has_code
                    and rough_range is not None
                    and not self._is_scaled_msm_sentinel(pr_fine, FINE_CODE_INVALID_MS)
                ):
                    pseudorange = rough_range + float(pr_fine) * RANGE_MS

                cp_fine = getattr(msg, f"{cp_attr}_{idx}", None)
                carrier_phase = 0.0
                if (
                    has_phase
                    and rough_range is not None
                    and not self._is_scaled_msm_sentinel(cp_fine, FINE_PHASE_INVALID_MS)
                ):
                    ph_m = rough_range + float(cp_fine) * RANGE_MS
                    if freq > 0:
                        carrier_phase = ph_m * freq / CLIGHT

                rr_fine = getattr(msg, f"DF404_{idx}", None)
                doppler = None
                if (
                    has_doppler
                    and rough_rate is not None
                    and not self._is_scaled_msm_sentinel(rr_fine, FINE_RATE_INVALID_MPS)
                ):
                    total_rate = rough_rate + float(rr_fine)
                    if freq > 0:
                        doppler = -total_rate * freq / CLIGHT

                snr = float(getattr(msg, f"{snr_attr}_{idx}", 0.0) or 0.0) if has_snr else 0.0
                lock_time = int(getattr(msg, f"{lock_attr}_{idx}", 0) or 0) if has_phase else 0
                half_cycle = int(getattr(msg, f"DF420_{idx}", 0) or 0) if has_phase else 0

                if pseudorange != 0 or carrier_phase != 0 or snr > 0:
                    obs = SignalData(
                        signal_id=sig_id,
                        pseudorange=float(pseudorange),
                        phase=float(carrier_phase),
                        snr=float(snr),
                        lock_time=lock_time,
                        half_cycle=half_cycle,
                        doppler=None if doppler is None else float(doppler),
                    )
                    sat_state.signals[sig_id] = obs

            if not self.compute_geometry:
                return epoch_data


            # ================================================================
            # Post-processing: Calculate Satellite Positions using Emission Time
            # ================================================================
            # For each satellite, compute the signal transmission time from its pseudorange,
            # then use the emission time (reception_time - transmission_time) to compute position
            
            for sat_key, sat_state in epoch_data.satellites.items():
                if not sat_state.signals:
                    # No observations for this satellite, skip position calculation
                    continue
                
                # Find the best pseudorange estimate (typically from C1C, C1S, C1L, C1X, C1P, C1W, C1Z, etc.)
                best_pseudorange = None
                signal_priority = ['C1C', 'C1S', 'C1L', 'C1X', 'C1P', 'C1W', 'C1Z', '1C']
                
                for sig_id in signal_priority:
                    if sig_id in sat_state.signals:
                        if sat_state.signals[sig_id].pseudorange > 0:
                            best_pseudorange = sat_state.signals[sig_id].pseudorange
                            break
                
                # If no code observation found, try to estimate from phase if available
                if best_pseudorange is None:
                    for sig_id, sig_data in sat_state.signals.items():
                        if sig_data.pseudorange > 0:
                            best_pseudorange = sig_data.pseudorange
                            break
                
                if best_pseudorange is None or best_pseudorange == 0:
                    # Cannot compute emission time without pseudorange
                    continue
                
                # Calculate signal transmission time
                transmission_time = best_pseudorange / CLIGHT
                
                # Calculate emission time (reception_time - transmission_time)
                emission_time = epoch_time - transmission_time
                
                # Wrap emission time to be within current GPS week if needed
                GPS_WEEK_SECONDS = 7 * 24 * 3600
                emission_time = emission_time % GPS_WEEK_SECONDS
                
                # Get ephemeris and calculate position using emission time
                eph_data = self.broadcast_eph.get_ephemeris(sat_key)
                if eph_data:
                    # Convert to format expected by BE2pos
                    eph_for_calc = {
                        'SatType': sys_type,
                        'PRN': eph_data.get('PRN'),
                    }
                    
                    # Add system-specific fields
                    if sys_type == 'GLO':
                        # GLONASS uses Cartesian coordinates
                        eph_for_calc.update({
                            'X': eph_data.get('X'),      # km
                            'Y': eph_data.get('Y'),      # km
                            'Z': eph_data.get('Z'),      # km
                            'Vx': eph_data.get('Vx'),    # km/s
                            'Vy': eph_data.get('Vy'),    # km/s
                            'Vz': eph_data.get('Vz'),    # km/s
                            'Ax': eph_data.get('Ax'),    # km/s²
                            'Ay': eph_data.get('Ay'),    # km/s²
                            'Az': eph_data.get('Az'),    # km/s²
                            'tb': eph_data.get('tb'),    # Time of ephemeris (seconds within week)
                            'tau_n': eph_data.get('tau_n'),
                            'gamma_n': eph_data.get('gamma_n'),
                        })
                    elif sys_type == 'SBS':
                        eph_for_calc.update({
                            't0': eph_data.get('t0', eph_data.get('toe')),
                            'pos': eph_data.get('pos'),
                            'vel': eph_data.get('vel'),
                            'acc': eph_data.get('acc'),
                            'af0': eph_data.get('af0', 0.0),
                            'af1': eph_data.get('af1', 0.0),
                            'af2': eph_data.get('af2', 0.0),
                            'Toc': eph_data.get('toc', eph_data.get('t0')),
                        })
                    else:
                        # GPS, Galileo, BeiDou use Keplerian parameters
                        eph_for_calc.update({
                            'Week': eph_data.get('week'),
                            'Toe': eph_data.get('toe'),
                            'sqrtA': eph_data.get('sqrt_a'),
                            'Eccentricity': eph_data.get('e'),
                            'M0': eph_data.get('M0'),
                            'omega': eph_data.get('omega'),
                            'i0': eph_data.get('i0'),
                            'OMEGA0': eph_data.get('Omega0'),
                            'Delta_n': eph_data.get('delta_n'),
                            'OMEGA_DOT': eph_data.get('Omega_dot'),
                            'IDOT': eph_data.get('idot'),
                            'Crs': eph_data.get('Crs'),
                            'Crc': eph_data.get('Crc'),
                            'Cus': eph_data.get('Cus'),
                            'Cuc': eph_data.get('Cuc'),
                            'Cis': eph_data.get('Cis'),
                            'Cic': eph_data.get('Cic'),
                            'af0': eph_data.get('af0'),
                            'af1': eph_data.get('af1'),
                            'af2': eph_data.get('af2'),
                            'Toc': eph_data.get('toc'),
                        })
                    
                    # Calculate Satellite Position using EMISSION TIME
                    sat_pos = BE2pos.brdc2pos(eph_for_calc, sys_type, emission_time)
                    
                    if sat_pos is not None:
                        # Store Position
                        sat_state.sat_pos_ecef = sat_pos.tolist()
                        
                        # Calculate Azimuth / Elevation
                        rec_pos = config.approx_rec_pos
                        if rec_pos and not np.all(np.array(rec_pos) == 0):
                            az, el = calculate_az_el(sat_pos, rec_pos)
                            sat_state.azimuth = az
                            sat_state.elevation = el
            
            # ================================================================
            # Store reference to broadcast ephemeris for later access
            # ================================================================
            # Applications can access via: handler.broadcast_eph.get_ephemeris(sat_key)
            
            return epoch_data


    # =========================================================================
    # RTCM 10403.3 Compliant Correction Handlers
    # =========================================================================
    # Note: All handlers use correct message IDs from RTCM 10403.3 standard
    # Message 1230: GLONASS L1/L2 Code-Phase Biases (NOT ionospheric correction)
    
    def _handle_glo_code_phase_bias(self, msg, epoch_data):
        """
        Parse RTCM 1230 - GLONASS L1 and L2 Code-Phase Biases.
        Reference: RTCM 10403.3 Table 3.5-109
        Note: This message is NOT part of SSR and is NOT ionospheric correction.
        It provides code-phase bias information specific to GLONASS signals.
        """
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
                
            # Message 1230 structure per RTCM standard:
            # - Header with message type and common fields
            # - Per-satellite code-phase bias data
            #
            # This is a GLONASS-specific message that is NOT standardized 
            # in the same way as GPS/GLONASS SSR messages
            
            pass  # Implementation depends on specific pyrtcm structure for msg 1230
            
        except (AttributeError, ValueError):
            pass
        
        return epoch_data
    
    # =========================================================================
    # Network RTK Correction Messages (Messages 1015-1017, 1037-1039)
    # =========================================================================
    
    def _handle_gps_iono_correction_diff(self, msg, epoch_data):
        """
        Parse RTCM 1015 - GPS Ionospheric Correction Differences.
        Reference: RTCM 10403.3 Table 3.5-17 and 3.5-18
        Uses DF fields: DF002, DF059, DF072, DF065, DF066, DF060, DF061, DF067, DF068, DF074, DF075, DF069
        """
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            from core.data_models import IonosphericCorrection
            
            num_sats = getattr(msg, 'DF067', 0)
            
            for i in range(num_sats):
                sat_id_attr = f'DF068_{i:02d}'
                if hasattr(msg, sat_id_attr):
                    sat_prn = int(getattr(msg, sat_id_attr))
                    sat_key = f"G{sat_prn:02d}"
                    
                    # Ionospheric Correction Difference in meters (DF069, resolution 0.5mm)
                    iono_diff = 0.0
                    if hasattr(msg, f'DF069_{i:02d}'):
                        iono_diff = float(getattr(msg, f'DF069_{i:02d}')) * 0.0005  # 0.5mm scale
                    
                    iono_corr = IonosphericCorrection(
                        satellite_id=sat_key,
                        stec=iono_diff,
                        stec_rate=None,
                        quality_indicator=int(getattr(msg, f'DF074_{i:02d}', 0)) if hasattr(msg, f'DF074_{i:02d}') else 0
                    )
                    epoch_data.ionospheric_corrections[sat_key] = iono_corr
            
            return epoch_data
            
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_gps_geometric_correction_diff(self, msg, epoch_data):
        """
        Parse RTCM 1016 - GPS Geometric Correction Differences.
        Reference: RTCM 10403.3 Table 3.5-17 and 3.5-19
        Uses DF fields: Header + DF068, DF074, DF075, DF070, DF071
        """
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            num_sats = getattr(msg, 'DF067', 0)
            
            # Geometric corrections are typically  processed along with ionospheric
            # Store in a separate dict for geometric/tropospheric corrections
            if not hasattr(epoch_data, 'geometric_corrections'):
                epoch_data.geometric_corrections = {}
            
            for i in range(num_sats):
                sat_id_attr = f'DF068_{i:02d}'
                if hasattr(msg, sat_id_attr):
                    sat_prn = int(getattr(msg, sat_id_attr))
                    sat_key = f"G{sat_prn:02d}"
                    
                    # Geometric Correction Difference in meters (DF070, resolution 0.5mm)
                    geom_diff = 0.0
                    if hasattr(msg, f'DF070_{i:02d}'):
                        geom_diff = float(getattr(msg, f'DF070_{i:02d}')) * 0.0005  # 0.5mm scale
                    
                    epoch_data.geometric_corrections[sat_key] = {
                        'geometric_diff': geom_diff,
                        'IODE': int(getattr(msg, f'DF071_{i:02d}', 0)) if hasattr(msg, f'DF071_{i:02d}') else 0
                    }
            
            return epoch_data
            
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_gps_combined_correction_diff(self, msg, epoch_data):
        """
        Parse RTCM 1017 - GPS Combined Geometric and Ionospheric Correction Differences.
        Reference: RTCM 10403.3 Table 3.5-17 and 3.5-20
        Combines data from messages 1015 and 1016
        """
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            from core.data_models import IonosphericCorrection
            
            num_sats = getattr(msg, 'DF067', 0)
            
            if not hasattr(epoch_data, 'geometric_corrections'):
                epoch_data.geometric_corrections = {}
            
            for i in range(num_sats):
                sat_id_attr = f'DF068_{i:02d}'
                if hasattr(msg, sat_id_attr):
                    sat_prn = int(getattr(msg, sat_id_attr))
                    sat_key = f"G{sat_prn:02d}"
                    
                    # Geometric Correction (DF070)
                    geom_diff = 0.0
                    if hasattr(msg, f'DF070_{i:02d}'):
                        geom_diff = float(getattr(msg, f'DF070_{i:02d}')) * 0.0005
                    
                    # Ionospheric Correction (DF069)
                    iono_diff = 0.0
                    if hasattr(msg, f'DF069_{i:02d}'):
                        iono_diff = float(getattr(msg, f'DF069_{i:02d}')) * 0.0005
                    
                    # Store both corrections
                    iono_corr = IonosphericCorrection(
                        satellite_id=sat_key,
                        stec=iono_diff,
                        stec_rate=None,
                        quality_indicator=0
                    )
                    epoch_data.ionospheric_corrections[sat_key] = iono_corr
                    
                    epoch_data.geometric_corrections[sat_key] = {
                        'geometric_diff': geom_diff,
                        'IODE': int(getattr(msg, f'DF071_{i:02d}', 0)) if hasattr(msg, f'DF071_{i:02d}') else 0
                    }
            
            return epoch_data
            
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_glo_iono_correction_diff(self, msg, epoch_data):
        """
        Parse RTCM 1037 - GLONASS Ionospheric Correction Differences.
        Reference: RTCM 10403.3, similar structure to GPS 1015
        """
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            from core.data_models import IonosphericCorrection
            
            # Similar to message 1015 but for GLONASS
            num_sats = getattr(msg, 'DF234', 0)  # GLONASS data entries field
            
            for i in range(num_sats):
                sat_id_attr = f'DF038_{i:02d}'  # GLONASS Satellite ID
                if hasattr(msg, sat_id_attr):
                    sat_slot = int(getattr(msg, sat_id_attr))
                    sat_key = f"R{sat_slot:02d}"
                    
                    # GLONASS Ionospheric Correction (DF237)
                    iono_diff = 0.0
                    if hasattr(msg, f'DF237_{i:02d}'):
                        iono_diff = float(getattr(msg, f'DF237_{i:02d}')) * 0.0005
                    
                    iono_corr = IonosphericCorrection(
                        satellite_id=sat_key,
                        stec=iono_diff,
                        stec_rate=None,
                        quality_indicator=0
                    )
                    epoch_data.ionospheric_corrections[sat_key] = iono_corr
            
            return epoch_data
            
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_glo_geometric_correction_diff(self, msg, epoch_data):
        """
        Parse RTCM 1038 - GLONASS Geometric Correction Differences.
        """
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            if not hasattr(epoch_data, 'geometric_corrections'):
                epoch_data.geometric_corrections = {}
            
            num_sats = getattr(msg, 'DF234', 0)
            
            for i in range(num_sats):
                sat_id_attr = f'DF038_{i:02d}'
                if hasattr(msg, sat_id_attr):
                    sat_slot = int(getattr(msg, sat_id_attr))
                    sat_key = f"R{sat_slot:02d}"
                    
                    # GLONASS Geometric Correction (DF238)
                    geom_diff = 0.0
                    if hasattr(msg, f'DF238_{i:02d}'):
                        geom_diff = float(getattr(msg, f'DF238_{i:02d}')) * 0.0005
                    
                    epoch_data.geometric_corrections[sat_key] = {
                        'geometric_diff': geom_diff,
                        'IOD': int(getattr(msg, f'DF239_{i:02d}', 0)) if hasattr(msg, f'DF239_{i:02d}') else 0
                    }
            
            return epoch_data
            
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_glo_combined_correction_diff(self, msg, epoch_data):
        """
        Parse RTCM 1039 - GLONASS Combined Geometric and Ionospheric Correction Differences.
        """
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            from core.data_models import IonosphericCorrection
            
            if not hasattr(epoch_data, 'geometric_corrections'):
                epoch_data.geometric_corrections = {}
            
            num_sats = getattr(msg, 'DF234', 0)
            
            for i in range(num_sats):
                sat_id_attr = f'DF038_{i:02d}'
                if hasattr(msg, sat_id_attr):
                    sat_slot = int(getattr(msg, sat_id_attr))
                    sat_key = f"R{sat_slot:02d}"
                    
                    # Geometric Correction (DF238)
                    geom_diff = 0.0
                    if hasattr(msg, f'DF238_{i:02d}'):
                        geom_diff = float(getattr(msg, f'DF238_{i:02d}')) * 0.0005
                    
                    # Ionospheric Correction (DF237)
                    iono_diff = 0.0
                    if hasattr(msg, f'DF237_{i:02d}'):
                        iono_diff = float(getattr(msg, f'DF237_{i:02d}')) * 0.0005
                    
                    iono_corr = IonosphericCorrection(
                        satellite_id=sat_key,
                        stec=iono_diff,
                        stec_rate=None,
                        quality_indicator=0
                    )
                    epoch_data.ionospheric_corrections[sat_key] = iono_corr
                    
                    epoch_data.geometric_corrections[sat_key] = {
                        'geometric_diff': geom_diff,
                        'IOD': int(getattr(msg, f'DF239_{i:02d}', 0)) if hasattr(msg, f'DF239_{i:02d}') else 0
                    }
            
            return epoch_data
            
        except (AttributeError, ValueError):
            return epoch_data

    # =========================================================================
    # SSR Messages
    # =========================================================================

    @staticmethod
    def _get_group_attr(msg, attr_name: str, *indices, default=None):
        """Read pyrtcm grouped attributes while tolerating 0- or 1-based fakes."""
        candidates = []
        if indices:
            candidates.append("_".join([attr_name] + [f"{idx:02d}" for idx in indices]))
            zero_based = tuple(max(0, int(idx) - 1) for idx in indices)
            candidates.append("_".join([attr_name] + [f"{idx:02d}" for idx in zero_based]))
        candidates.append(attr_name)

        for candidate in candidates:
            if hasattr(msg, candidate):
                return getattr(msg, candidate)
        return default

    @staticmethod
    def _to_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _mm_to_m(value) -> float:
        """Convert pyrtcm SSR millimetre-domain fields to meters."""
        return RTCMHandler._to_float(value) * 0.001

    @staticmethod
    def _ssr_ura_to_value(ura: int | float) -> float:
        try:
            raw = int(ura)
        except (TypeError, ValueError):
            return 0.0
        if raw == 0:
            return 0.0
        if raw >= 63:
            return 5.5
        urac = raw >> 3
        urav = raw & 7
        return (math.pow(3.0, urac) * (1.0 + urav / 4.0) - 1.0) / 1000.0

    def _ssr_epoch_time(self, msg, definition: dict) -> float:
        raw_time = self._to_float(getattr(msg, definition["time"], 0.0))
        system = definition["system"]
        if system == "C":
            return (raw_time + 14.0) % (7 * 24 * 3600)
        if system == "R":
            day_anchor = self._reference_utc_for_glonass_day()
            day_index = self._utc_day_of_week(day_anchor)
            seconds_of_day = raw_time - 3.0 * 3600.0 + GNSSTime.LEAP_SECONDS
            day_offset = math.floor(seconds_of_day / 86400.0)
            seconds_of_day = seconds_of_day % 86400.0
            day_index = (day_index + int(day_offset)) % 7
            return day_index * 86400.0 + seconds_of_day
        return raw_time

    def _igs_ssr_epoch_time(self, raw_time: float, system: str) -> float:
        if system == "C":
            return (raw_time + 14.0) % (7 * 24 * 3600)
        if system == "R":
            return (raw_time + GNSSTime.LEAP_SECONDS) % (7 * 24 * 3600)
        return raw_time % (7 * 24 * 3600)

    @staticmethod
    def _satellite_id(system: str, prn: int) -> str:
        if system == "J" and prn >= 193:
            prn -= 192
        return f"{system}{int(prn):02d}"

    @staticmethod
    def _ssr_signal_to_rinex(system: str, signal_id, *, igs: bool = False) -> str:
        try:
            raw_id = int(signal_id)
        except (TypeError, ValueError):
            return str(signal_id)
        mapping = SSR_SIGNAL_RINEX_IGS if igs else SSR_SIGNAL_RINEX_RTCM
        return mapping.get(system, {}).get(raw_id, str(raw_id))

    def _handle_ssr_message(self, msg, epoch_data=None):
        definition = SSR_MESSAGE_DEFINITIONS.get(str(getattr(msg, "identity", "")))
        if not definition:
            return epoch_data

        kind = definition["kind"]
        if kind in {"orbit", "combined"}:
            self._cache_ssr_orbit(msg, definition)
        if kind in {"clock", "combined", "high_rate_clock"}:
            self._cache_ssr_clock(msg, definition)
        if kind == "code_bias":
            self._cache_ssr_code_biases(msg, definition)
        if kind == "ura":
            self._cache_ssr_ura(msg, definition)
        return epoch_data

    def _cache_ssr_orbit(self, msg, definition: dict) -> None:
        epoch_time = self._ssr_epoch_time(msg, definition)
        count = self._to_int(getattr(msg, "DF387", 0))
        for index in range(1, count + 1):
            prn = self._to_int(self._get_group_attr(msg, definition["sat"], index))
            if prn <= 0:
                continue
            sat_id = self._satellite_id(definition["system"], prn)
            correction = SsrOrbitCorrection(
                satellite_id=sat_id,
                epoch_time=epoch_time,
                iod=self._to_int(self._get_group_attr(msg, definition.get("iod", ""), index, default=0)),
                update_interval=self._to_int(getattr(msg, "DF391", 0)),
                iod_ssr=self._to_int(getattr(msg, "DF413", 0)),
                provider_id=self._to_int(getattr(msg, "DF414", 0)),
                solution_id=self._to_int(getattr(msg, "DF415", 0)),
                datum=self._to_int(getattr(msg, "DF375", 0)),
                delta_radial_m=self._mm_to_m(self._get_group_attr(msg, "DF365", index)),
                delta_along_track_m=self._mm_to_m(self._get_group_attr(msg, "DF366", index)),
                delta_cross_track_m=self._mm_to_m(self._get_group_attr(msg, "DF367", index)),
                dot_delta_radial_mps=self._mm_to_m(self._get_group_attr(msg, "DF368", index)),
                dot_delta_along_track_mps=self._mm_to_m(self._get_group_attr(msg, "DF369", index)),
                dot_delta_cross_track_mps=self._mm_to_m(self._get_group_attr(msg, "DF370", index)),
            )
            self.ssr_corrections.update_orbit(correction)

    def _cache_ssr_clock(self, msg, definition: dict) -> None:
        epoch_time = self._ssr_epoch_time(msg, definition)
        count = self._to_int(getattr(msg, "DF387", 0))
        is_high_rate = definition["kind"] == "high_rate_clock"
        for index in range(1, count + 1):
            prn = self._to_int(self._get_group_attr(msg, definition["sat"], index))
            if prn <= 0:
                continue
            sat_id = self._satellite_id(definition["system"], prn)
            correction = SsrClockCorrection(
                satellite_id=sat_id,
                epoch_time=epoch_time,
                update_interval=self._to_int(getattr(msg, "DF391", 0)),
                iod_ssr=self._to_int(getattr(msg, "DF413", 0)),
                provider_id=self._to_int(getattr(msg, "DF414", 0)),
                solution_id=self._to_int(getattr(msg, "DF415", 0)),
            )
            if is_high_rate:
                correction.high_rate_clock_m = self._mm_to_m(self._get_group_attr(msg, "DF390", index))
                self.ssr_corrections.update_high_rate_clock(correction)
            else:
                correction.delta_clock_m = self._mm_to_m(self._get_group_attr(msg, "DF376", index))
                correction.delta_clock_rate_mps = self._mm_to_m(self._get_group_attr(msg, "DF377", index))
                correction.delta_clock_accel_mps2 = self._mm_to_m(self._get_group_attr(msg, "DF378", index))
                self.ssr_corrections.update_clock(correction)

    def _cache_ssr_code_biases(self, msg, definition: dict) -> None:
        count = self._to_int(getattr(msg, "DF387", 0))
        signal_attr = definition.get("signal")
        if not signal_attr:
            return
        for sat_index in range(1, count + 1):
            prn = self._to_int(self._get_group_attr(msg, definition["sat"], sat_index))
            if prn <= 0:
                continue
            bias_count = self._to_int(self._get_group_attr(msg, "DF379", sat_index))
            biases = {}
            for bias_index in range(1, bias_count + 1):
                signal_id = self._get_group_attr(msg, signal_attr, sat_index, bias_index)
                if signal_id is None:
                    continue
                biases[self._ssr_signal_to_rinex(definition["system"], signal_id)] = self._to_float(
                    self._get_group_attr(msg, "DF383", sat_index, bias_index)
                )
            if biases:
                self.ssr_corrections.update_code_biases(
                    self._satellite_id(definition["system"], prn),
                    biases,
                )

    def _cache_ssr_ura(self, msg, definition: dict) -> None:
        count = self._to_int(getattr(msg, "DF387", 0))
        for index in range(1, count + 1):
            prn = self._to_int(self._get_group_attr(msg, definition["sat"], index))
            if prn <= 0:
                continue
            self.ssr_corrections.update_ura(
                self._satellite_id(definition["system"], prn),
                self._ssr_ura_to_value(self._get_group_attr(msg, "DF389", index)),
            )

    def _handle_igs_ssr_message(self, msg, epoch_data=None):
        raw = getattr(msg, "raw", None)
        if raw is None:
            raw = getattr(msg, "payload", None)
        if raw is None:
            return epoch_data
        raw = bytes(raw)
        if len(raw) < 9:
            return epoch_data

        payload_len = ((raw[1] & 0x03) << 8) | raw[2]
        payload_end_bit = (3 + payload_len) * 8
        reader = _BitReader(raw, 24, payload_end_bit)
        rtcm_type = reader.unsigned(12)
        if rtcm_type != 4076:
            return epoch_data
        reader.unsigned(3)  # IGS SSR version
        subtype = reader.unsigned(8)
        definition = IGS_SSR_MESSAGE_DEFINITIONS.get(subtype)
        if definition is None:
            return epoch_data

        kind = definition["kind"]
        if kind == "orbit":
            self._cache_igs_ssr_orbit(reader, definition)
        elif kind == "clock":
            self._cache_igs_ssr_clock(reader, definition, is_high_rate=False)
        elif kind == "combined":
            self._cache_igs_ssr_combined(reader, definition)
        elif kind == "high_rate_clock":
            self._cache_igs_ssr_clock(reader, definition, is_high_rate=True)
        elif kind == "code_bias":
            self._cache_igs_ssr_code_biases(reader, definition)
        elif kind == "phase_bias":
            self._cache_raw_ssr_phase_biases(reader, definition, igs=True)
        elif kind == "ura":
            self._cache_igs_ssr_ura(reader, definition)
        return epoch_data

    def _handle_ssr_phase_bias_message(self, msg, epoch_data=None):
        raw = getattr(msg, "raw", None)
        if raw is None:
            return epoch_data
        raw = bytes(raw)
        if len(raw) < 9:
            return epoch_data
        payload_len = ((raw[1] & 0x03) << 8) | raw[2]
        reader = _BitReader(raw, 24, (3 + payload_len) * 8)
        message_number = str(reader.unsigned(12))
        system = SSR_PHASE_BIAS_SYSTEMS.get(message_number)
        if system is not None:
            self._cache_raw_ssr_phase_biases(
                reader,
                {"kind": "phase_bias", "system": system},
                igs=False,
            )
        return epoch_data

    def _read_igs_ssr_header(self, reader: _BitReader, system: str, *, has_datum: bool = False) -> dict:
        raw_epoch = float(reader.unsigned(20))
        header = {
            "epoch_time": self._igs_ssr_epoch_time(raw_epoch, system),
            "update_interval": reader.unsigned(4),
            "multiple_message": reader.unsigned(1),
            "iod_ssr": reader.unsigned(4),
            "provider_id": reader.unsigned(16),
            "solution_id": reader.unsigned(4),
        }
        if has_datum:
            header["datum"] = reader.unsigned(1)
        header["count"] = reader.unsigned(6)
        return header

    def _cache_igs_ssr_orbit(self, reader: _BitReader, definition: dict) -> None:
        system = definition["system"]
        header = self._read_igs_ssr_header(reader, system, has_datum=True)
        for _ in range(header["count"]):
            prn = reader.unsigned(6)
            correction = SsrOrbitCorrection(
                satellite_id=self._satellite_id(system, prn),
                epoch_time=header["epoch_time"],
                iod=reader.unsigned(8),
                update_interval=header["update_interval"],
                iod_ssr=header["iod_ssr"],
                provider_id=header["provider_id"],
                solution_id=header["solution_id"],
                datum=header.get("datum", 0),
                delta_radial_m=reader.signed(22, 1.0 / 10000.0),
                delta_along_track_m=reader.signed(20, 1.0 / 2500.0),
                delta_cross_track_m=reader.signed(20, 1.0 / 2500.0),
                dot_delta_radial_mps=reader.signed(21, 1.0 / 1000000.0),
                dot_delta_along_track_mps=reader.signed(19, 1.0 / 250000.0),
                dot_delta_cross_track_mps=reader.signed(19, 1.0 / 250000.0),
            )
            self.ssr_corrections.update_orbit(correction)

    def _cache_igs_ssr_clock(self, reader: _BitReader, definition: dict, *, is_high_rate: bool) -> None:
        system = definition["system"]
        header = self._read_igs_ssr_header(reader, system)
        for _ in range(header["count"]):
            prn = reader.unsigned(6)
            correction = SsrClockCorrection(
                satellite_id=self._satellite_id(system, prn),
                epoch_time=header["epoch_time"],
                update_interval=header["update_interval"],
                iod_ssr=header["iod_ssr"],
                provider_id=header["provider_id"],
                solution_id=header["solution_id"],
            )
            if is_high_rate:
                correction.high_rate_clock_m = reader.signed(22, 1.0 / 10000.0)
                self.ssr_corrections.update_high_rate_clock(correction)
            else:
                correction.delta_clock_m = reader.signed(22, 1.0 / 10000.0)
                correction.delta_clock_rate_mps = reader.signed(21, 1.0 / 1000000.0)
                correction.delta_clock_accel_mps2 = reader.signed(27, 1.0 / 50000000.0)
                self.ssr_corrections.update_clock(correction)

    def _cache_igs_ssr_combined(self, reader: _BitReader, definition: dict) -> None:
        system = definition["system"]
        header = self._read_igs_ssr_header(reader, system, has_datum=True)
        for _ in range(header["count"]):
            prn = reader.unsigned(6)
            sat_id = self._satellite_id(system, prn)
            iod = reader.unsigned(8)
            orbit = SsrOrbitCorrection(
                satellite_id=sat_id,
                epoch_time=header["epoch_time"],
                iod=iod,
                update_interval=header["update_interval"],
                iod_ssr=header["iod_ssr"],
                provider_id=header["provider_id"],
                solution_id=header["solution_id"],
                datum=header.get("datum", 0),
                delta_radial_m=reader.signed(22, 1.0 / 10000.0),
                delta_along_track_m=reader.signed(20, 1.0 / 2500.0),
                delta_cross_track_m=reader.signed(20, 1.0 / 2500.0),
                dot_delta_radial_mps=reader.signed(21, 1.0 / 1000000.0),
                dot_delta_along_track_mps=reader.signed(19, 1.0 / 250000.0),
                dot_delta_cross_track_mps=reader.signed(19, 1.0 / 250000.0),
            )
            clock = SsrClockCorrection(
                satellite_id=sat_id,
                epoch_time=header["epoch_time"],
                update_interval=header["update_interval"],
                iod_ssr=header["iod_ssr"],
                provider_id=header["provider_id"],
                solution_id=header["solution_id"],
                delta_clock_m=reader.signed(22, 1.0 / 10000.0),
                delta_clock_rate_mps=reader.signed(21, 1.0 / 1000000.0),
                delta_clock_accel_mps2=reader.signed(27, 1.0 / 50000000.0),
            )
            self.ssr_corrections.update_orbit(orbit)
            self.ssr_corrections.update_clock(clock)

    def _cache_igs_ssr_code_biases(self, reader: _BitReader, definition: dict) -> None:
        system = definition["system"]
        header = self._read_igs_ssr_header(reader, system)
        for _ in range(header["count"]):
            prn = reader.unsigned(6)
            bias_count = reader.unsigned(5)
            biases = {}
            for _ in range(bias_count):
                signal_id = reader.unsigned(5)
                biases[self._ssr_signal_to_rinex(system, signal_id, igs=True)] = reader.signed(14, 1.0 / 100.0)
            if biases:
                self.ssr_corrections.update_code_biases(self._satellite_id(system, prn), biases)

    def _cache_raw_ssr_phase_biases(self, reader: _BitReader, definition: dict, *, igs: bool) -> None:
        system = definition["system"]
        raw_epoch = float(reader.unsigned(20 if igs or system != "R" else 17))
        if not igs and system == "R":
            day_anchor = self._reference_utc_for_glonass_day()
            day_index = self._utc_day_of_week(day_anchor)
            seconds_of_day = raw_epoch - 3.0 * 3600.0 + GNSSTime.LEAP_SECONDS
            day_offset = math.floor(seconds_of_day / 86400.0)
            seconds_of_day %= 86400.0
            epoch_time = ((day_index + int(day_offset)) % 7) * 86400.0 + seconds_of_day
        else:
            epoch_time = self._igs_ssr_epoch_time(raw_epoch, system)
        header = {
            "epoch_time": epoch_time,
            "update_interval": reader.unsigned(4),
            "multiple_message": reader.unsigned(1),
            "iod_ssr": reader.unsigned(4),
            "provider_id": reader.unsigned(16),
            "solution_id": reader.unsigned(4),
            "dispersive_consistency": bool(reader.unsigned(1)),
            "mw_consistency": bool(reader.unsigned(1)),
        }
        sat_bits = 6 if igs else (4 if system == "J" else 5 if system == "R" else 6)
        count = reader.unsigned(6 if igs or system != "J" else 4)
        for _ in range(count):
            prn = reader.unsigned(sat_bits)
            bias_count = reader.unsigned(5)
            yaw_angle = reader.unsigned(9) / 256.0 * 180.0
            yaw_rate = reader.signed(8, 180.0 / 8192.0)
            biases = {}
            for _ in range(bias_count):
                signal_id = reader.unsigned(5)
                signal_name = self._ssr_signal_to_rinex(system, signal_id, igs=igs)
                bias = SsrPhaseBias(
                    signal_id=signal_name,
                    integer_indicator=bool(reader.unsigned(1)),
                    wide_lane_indicator=reader.unsigned(2),
                    discontinuity_counter=reader.unsigned(4),
                    bias_m=reader.signed(20, 0.0001),
                )
                biases[signal_name] = bias
            if not biases:
                continue
            self.ssr_corrections.update_phase_biases(
                SsrPhaseBiasCorrection(
                    satellite_id=self._satellite_id(system, prn),
                    epoch_time=header["epoch_time"],
                    update_interval=header["update_interval"],
                    iod_ssr=header["iod_ssr"],
                    provider_id=header["provider_id"],
                    solution_id=header["solution_id"],
                    dispersive_consistency=header["dispersive_consistency"],
                    mw_consistency=header["mw_consistency"],
                    yaw_angle_deg=yaw_angle,
                    yaw_rate_deg_s=yaw_rate,
                    biases=biases,
                )
            )

    def _cache_igs_ssr_ura(self, reader: _BitReader, definition: dict) -> None:
        system = definition["system"]
        header = self._read_igs_ssr_header(reader, system)
        for _ in range(header["count"]):
            prn = reader.unsigned(6)
            self.ssr_corrections.update_ura(
                self._satellite_id(system, prn),
                self._ssr_ura_to_value(reader.unsigned(6)),
            )
    
    # =========================================================================
    # SSR Messages (1057-1068) - State Space Representation
    # =========================================================================
    
    def _handle_gps_ssr_orbit(self, msg, epoch_data):
        """
        Parse RTCM 1057 - SSR GPS Orbit Correction.
        Reference: RTCM 10403.3 Table 3.5-37/38
        """
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            from core.data_models import SatelliteClockCorrection
            
            num_sats = getattr(msg, 'DF387', 0)
            
            for i in range(num_sats):
                sat_prn = int(getattr(msg, f'DF068_{i:02d}', 0))
                sat_key = f"G{sat_prn:02d}"
                
                # Orbit corrections (scales per RTCM standard)
                delta_radial = float(getattr(msg, f'DF365_{i:02d}', 0)) * 0.0001  # 0.1mm scale
                delta_along = float(getattr(msg, f'DF366_{i:02d}', 0)) * 0.0004  # 0.4mm scale
                delta_cross = float(getattr(msg, f'DF367_{i:02d}', 0)) * 0.0004  # 0.4mm scale
                
                corr = SatelliteClockCorrection(
                    satellite_id=sat_key,
                    delta_clock=0.0,
                    delta_radial=delta_radial,
                    delta_along_track=delta_along,
                    delta_cross_track=delta_cross
                )
                epoch_data.satellite_clock_corrections[sat_key] = corr
            
            return epoch_data
            
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_gps_ssr_clock(self, msg, epoch_data):
        """
        Parse RTCM 1058 - SSR GPS Clock Correction.
        Reference: RTCM 10403.3 Table 3.5-39/40
        """
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            from core.data_models import SatelliteClockCorrection
            
            num_sats = getattr(msg, 'DF387', 0)
            
            for i in range(num_sats):
                sat_prn = int(getattr(msg, f'DF068_{i:02d}', 0))
                sat_key = f"G{sat_prn:02d}"
                
                # Clock corrections (DF376-378 with 0.1mm scale for C0)
                delta_c0 = float(getattr(msg, f'DF376_{i:02d}', 0)) * 0.0001  # 0.1mm
                delta_c1 = float(getattr(msg, f'DF377_{i:02d}', 0)) * 0.000001  # 0.001mm/s
                delta_c2 = float(getattr(msg, f'DF378_{i:02d}', 0)) * 0.00000002  # 0.00002mm/s²
                
                corr = SatelliteClockCorrection(
                    satellite_id=sat_key,
                    delta_clock=delta_c0,
                    delta_clock_rate=delta_c1,
                    delta_clock_accel=delta_c2
                )
                epoch_data.satellite_clock_corrections[sat_key] = corr
            
            return epoch_data
            
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_gps_ssr_code_bias(self, msg, epoch_data):
        """
        Parse RTCM 1059 - SSR GPS Code Bias.
        Reference: RTCM 10403.3 Table 3.5-41/42/43
        """
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            from core.data_models import SatelliteBiasCorrection
            
            num_sats = getattr(msg, 'DF387', 0)
            
            for i in range(num_sats):
                sat_prn = int(getattr(msg, f'DF068_{i:02d}', 0))
                sat_key = f"G{sat_prn:02d}"
                
                num_codes = int(getattr(msg, f'DF379_{i:02d}', 0))
                
                code_biases_dict = {}
                for j in range(num_codes):
                    signal_id = int(getattr(msg, f'DF380_{i:02d}_{j:02d}', 0))
                    bias_value = float(getattr(msg, f'DF383_{i:02d}_{j:02d}', 0)) * 0.01  # 0.01m scale
                    code_biases_dict[signal_id] = bias_value
                
                corr = SatelliteBiasCorrection(
                    satellite_id=sat_key,
                    code_biases=code_biases_dict,
                    phase_biases={}
                )
                epoch_data.satellite_bias_corrections[sat_key] = corr
            
            return epoch_data
            
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_gps_ssr_combined(self, msg, epoch_data):
        """
        Parse RTCM 1060 - SSR GPS Combined Orbit and Clock Correction.
        Reference: RTCM 10403.3 Table 3.5-44/45
        """
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            from core.data_models import SatelliteClockCorrection
            
            num_sats = getattr(msg, 'DF387', 0)
            
            for i in range(num_sats):
                sat_prn = int(getattr(msg, f'DF068_{i:02d}', 0))
                sat_key = f"G{sat_prn:02d}"
                
                # Combined orbit and clock data
                delta_radial = float(getattr(msg, f'DF365_{i:02d}', 0)) * 0.0001
                delta_along = float(getattr(msg, f'DF366_{i:02d}', 0)) * 0.0004
                delta_cross = float(getattr(msg, f'DF367_{i:02d}', 0)) * 0.0004
                delta_c0 = float(getattr(msg, f'DF376_{i:02d}', 0)) * 0.0001
                delta_c1 = float(getattr(msg, f'DF377_{i:02d}', 0)) * 0.000001
                delta_c2 = float(getattr(msg, f'DF378_{i:02d}', 0)) * 0.00000002
                
                corr = SatelliteClockCorrection(
                    satellite_id=sat_key,
                    delta_clock=delta_c0,
                    delta_clock_rate=delta_c1,
                    delta_clock_accel=delta_c2,
                    delta_radial=delta_radial,
                    delta_along_track=delta_along,
                    delta_cross_track=delta_cross
                )
                epoch_data.satellite_clock_corrections[sat_key] = corr
            
            return epoch_data
            
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_gps_ssr_ura(self, msg, epoch_data):
        """
        Parse RTCM 1061 - SSR GPS URA (User Range Accuracy).
        Reference: RTCM 10403.3 Table 3.5-46/47
        """
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            # URA values are typically stored in a separate dictionary
            if not hasattr(epoch_data, 'ssr_ura'):
                epoch_data.ssr_ura = {}
            
            num_sats = getattr(msg, 'DF387', 0)
            
            for i in range(num_sats):
                sat_prn = int(getattr(msg, f'DF068_{i:02d}', 0))
                sat_key = f"G{sat_prn:02d}"
                
                ura_value = int(getattr(msg, f'DF389_{i:02d}', 0))
                epoch_data.ssr_ura[sat_key] = ura_value
            
            return epoch_data
            
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_gps_ssr_high_rate_clock(self, msg, epoch_data):
        """
        Parse RTCM 1062 - SSR GPS High Rate Clock Correction.
        Reference: RTCM 10403.3 Table 3.5-48/49
        """
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            from core.data_models import SatelliteClockCorrection
            
            num_sats = getattr(msg, 'DF387', 0)
            
            for i in range(num_sats):
                sat_prn = int(getattr(msg, f'DF068_{i:02d}', 0))
                sat_key = f"G{sat_prn:02d}"
                
                # High rate clock correction (DF390)
                delta_clock_hr = float(getattr(msg, f'DF390_{i:02d}', 0)) * 0.0001  # 0.1mm scale
                
                corr = SatelliteClockCorrection(
                    satellite_id=sat_key,
                    delta_clock=delta_clock_hr
                )
                epoch_data.satellite_clock_corrections[sat_key] = corr
            
            return epoch_data
            
        except (AttributeError, ValueError):
            return epoch_data
    
    # GLONASS SSR Message Handlers (1063-1068) follow similar patterns
    # with GLONASS-specific satellite identifiers and data fields
    
    def _handle_glo_ssr_orbit(self, msg, epoch_data):
        """Parse RTCM 1063 - SSR GLONASS Orbit Correction."""
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            # Similar to GPS 1057 but with GLONASS-specific fields
            return epoch_data
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_glo_ssr_clock(self, msg, epoch_data):
        """Parse RTCM 1064 - SSR GLONASS Clock Correction."""
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            # Similar to GPS 1058 but with GLONASS-specific fields
            return epoch_data
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_glo_ssr_code_bias(self, msg, epoch_data):
        """Parse RTCM 1065 - SSR GLONASS Code Bias."""
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            # Similar to GPS 1059 but with GLONASS-specific fields
            return epoch_data
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_glo_ssr_combined(self, msg, epoch_data):
        """Parse RTCM 1066 - SSR GLONASS Combined Orbit and Clock."""
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            # Similar to GPS 1060 but with GLONASS-specific fields
            return epoch_data
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_glo_ssr_ura(self, msg, epoch_data):
        """Parse RTCM 1067 - SSR GLONASS URA."""
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            # Similar to GPS 1061 but with GLONASS-specific fields
            return epoch_data
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_glo_ssr_high_rate_clock(self, msg, epoch_data):
        """Parse RTCM 1068 - SSR GLONASS High Rate Clock Correction."""
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            # Similar to GPS 1062 but with GLONASS-specific fields
            return epoch_data
        except (AttributeError, ValueError):
            return epoch_data
    
    def _handle_glo_ssr_high_rate_clock(self, msg, epoch_data):
        """Parse RTCM 1068 - SSR GLONASS High Rate Clock Correction."""
        try:
            if epoch_data is None:
                epoch_data = EpochObservation(gps_time=0.0)
            
            # Similar to GPS 1062 but with GLONASS-specific fields
            return epoch_data
        except (AttributeError, ValueError):
            return epoch_data
    
    # =========================================================================
    # Public Methods for Accessing Correction Parameters
    # =========================================================================
    def get_ephemeris(self, satellite_id):
        """Return cached broadcast ephemeris for one satellite."""
        return self.broadcast_eph.get_ephemeris(satellite_id)

    def get_all_ephemeris(self, system=None):
        """Return cached broadcast ephemerides, optionally filtered by constellation."""
        return self.broadcast_eph.get_all_ephemeris(system)

    def get_ssr_snapshot(self):
        """Return a thread-safe snapshot of cached SSR corrections."""
        return self.ssr_corrections.snapshot()

    def get_broadcast_eph_correction(self, satellite_id):
        """
        Get broadcast ephemeris correction parameters for a specific satellite.
        
        Args:
            satellite_id: e.g., "G01", "E02", "C03"
            
        Returns:
            BroadcastEphemerisCorrections object or None if not available
        """
        if hasattr(self, 'broadcast_eph_cache'):
            return self.broadcast_eph_cache.get(satellite_id)
        return None
    
    def get_all_broadcast_eph_corrections(self):
        """
        Get all broadcast ephemeris corrections currently cached.
        
        Returns:
            Dictionary of satellite_id -> BroadcastEphemerisCorrections
        """
        if hasattr(self, 'broadcast_eph_cache'):
            return self.broadcast_eph_cache.copy()
        return {}
    
    def get_tgd_correction(self, satellite_id):
        """
        Convenience method to get TGD (Total Group Delay) correction for a satellite.
        
        Args:
            satellite_id: e.g., "G01", "C02"
            
        Returns:
            TGD value in meters, or None if not available
        """
        corr = self.get_broadcast_eph_correction(satellite_id)
        if corr:
            return corr.TGD or corr.TGD1 or corr.TGD2
        return None
    
    def get_bgd_correction(self, satellite_id):
        """
        Convenience method to get BGD (Bias Group Delay) correction for a satellite.
        
        Args:
            satellite_id: e.g., "E02"
            
        Returns:
            BGD value in meters, or None if not available
        """
        corr = self.get_broadcast_eph_correction(satellite_id)
        if corr:
            return corr.BGD_E1E5a or corr.BGD_E1E5b
        return None
    
    def apply_ionospheric_correction(self, pseudorange, sig_id, stec_value):
        """
        Apply ionospheric STEC correction to pseudorange.
        
        Args:
            pseudorange: Original pseudorange in meters
            sig_id: Signal identifier (e.g., "1C", "1X")
            stec_value: Slant Total Electron Content in TECu
            
        Returns:
            Corrected pseudorange in meters
        """
        if stec_value is None:
            return pseudorange
        
        # Ionospheric delay ~0.1017 * STEC (m/TECu) for TEC model
        iono_delay = 0.1017 * stec_value
        
        # Dual frequency signals have different corrections
        # This is a simplified model; actual implementation depends on signal and frequency
        return pseudorange - iono_delay
    
    def apply_tropospheric_correction(self, pseudorange, elevation_angle, tropo_corr):
        """
        Apply tropospheric correction to pseudorange using slant delay.
        
        Args:
            pseudorange: Original pseudorange in meters
            elevation_angle: Elevation angle of satellite in radians
            tropo_corr: TroposphericCorrection object
            
        Returns:
            Corrected pseudorange in meters
        """
        if tropo_corr is None or tropo_corr.ztd_wet is None:
            return pseudorange
        
        # Calculate mapping function (simplified)
        # More accurate models (Niell, VMF1, etc.) can be used
        sin_el = math.sin(elevation_angle)
        if sin_el <= 0:
            return pseudorange
        
        # Simplified wet delay mapping: ztd_wet / sin(elevation)
        tropo_delay = tropo_corr.ztd_wet / sin_el
        
        return pseudorange - tropo_delay



def get_shared_handler():
    """Return a shared RTCMHandler instance (singleton).

    Use this to ensure ephemeris cache and parsing state are shared across
    monitoring/positioning/logging modules when they run together.
    """
    global _shared_rtcm_handler
    if _shared_rtcm_handler is None:
        _shared_rtcm_handler = RTCMHandler()
    return _shared_rtcm_handler
