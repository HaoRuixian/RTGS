"""
RINEX Version 3.04 file writer for GNSS observation data.

This module provides functionality to write observation data in the RINEX 3.04 format
as defined by the International GNSS Service (IGS).

Standard format reference: https://files.igs.org/pub/data/format/rinex304.pdf
Author:  RuixianHao
Date:    2026-02-08
Email: vitamin_n@outlook.com
"""

import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional


LOGGER = logging.getLogger(__name__)


class RINEX3Writer:
    """
    Writer for RINEX 3.04 format observation files following standard specification.

    The writer keeps enough state to rewrite the header when the file closes so that
    TIME OF FIRST OBS/TIME OF LAST OBS and APPROX POSITION XYZ reflect the final run.
    """

    GNSS_SYSTEMS = {
        "G": "GPS",
        "R": "GLONASS",
        "E": "Galileo",
        "C": "BeiDou",
        "J": "QZSS",
        "S": "SBAS",
        "I": "IRNSS",
    }

    SNR_THRESHOLDS = [
        (12, 1),
        (17, 2),
        (23, 3),
        (29, 4),
        (35, 5),
        (41, 6),
        (47, 7),
        (53, 8),
        (float("inf"), 9),
    ]

    HEADER_CONTENT_WIDTH = 60
    HEADER_FIELD_WIDTH = 20
    OBS_TYPES_PER_HEADER_LINE = 13

    def __init__(
        self,
        filename: str,
        marker_name: str = "UNKNOWN",
        marker_number: str = "0",
        station_code: str = "RTGS",
        country_code: str = "CHN",
        receiver_number: str = "00",
        period: str = "01D",
        interval: str = "30S",
        datatype: str = "MO",
        filename_template: Optional[str] = None,
        file_time: Optional[datetime] = None,
        header_interval_seconds: Optional[float] = None,
        time_system: str = "GPS",
        antenna_number: str = "",
        receiver_serial: str = "",
        receiver_version: str = "",
    ):
        """
        Initialize RINEX3 writer.

        Args:
            filename: Output file path or output directory. If it does not end in
                ``.rnx`` a standard RINEX 3 long filename will be generated inside
                that directory.
            marker_name: Receiver/Station marker name (max 60 chars)
            marker_number: Receiver/Station marker number (max 20 chars)
            station_code: 4-character station code
            country_code: 3-character country/agency code
            receiver_number: 2-character receiver number
            period: Processing period string for filename (e.g. "01D", "01H")
            interval: Sampling interval string for filename/header (e.g. "30S", "01S")
            datatype: Type code for filename (usually "MO" for observations)
            filename_template: Optional Python format string used to create the
                final filename. Supported placeholders: ``station``, ``receiver``,
                ``country``, ``year_day``, ``hour_min``, ``period``, ``interval``,
                ``datatype``.
            file_time: UTC time used for long filename generation.
        """
        self.station_code = str(station_code)[:4].upper().ljust(4, "0")
        self.receiver_number = str(receiver_number)[:2].upper().ljust(2, "0")
        self.country_code = str(country_code)[:3].upper().ljust(3, " ")
        self.marker_name = str(marker_name)[:60]
        self.marker_number = str(marker_number)[:20]
        self.period = self._normalize_span_code(period, "01D")
        self.interval = self._normalize_span_code(interval, "01S")
        self.datatype = str(datatype)[:2].upper() or "MO"
        self.filename_template = filename_template
        self.file_time = file_time or datetime.utcnow()
        self.header_interval_seconds = (
            float(header_interval_seconds)
            if header_interval_seconds is not None
            else None
        )
        self.time_system = str(time_system or "GPS").strip().upper() or "GPS"
        self.antenna_number = self._format_a20(antenna_number).strip()
        self.receiver_serial = self._format_a20(receiver_serial if receiver_serial else receiver_number).strip()
        self.receiver_version = self._format_a20(receiver_version).strip()

        self.output_directory = "."
        if filename.lower().endswith(".rnx"):
            self.filename = filename
            self.output_directory = os.path.dirname(filename) or "."
        else:
            self.output_directory = filename or "."
            self.filename = self._build_output_path(self.file_time)

        self.file_handle = None
        self.header_written = False
        self.header_end_pos: Optional[int] = None

        self.sys_obs_types: Dict[str, List[str]] = {}
        self.first_epoch: Optional[datetime] = None
        self.last_epoch: Optional[datetime] = None

        self.receiver_type = "UNKNOWN"
        self.antenna_type = "UNKNOWN"
        self.approx_position = [0.0, 0.0, 0.0]
        self.antenna_delta = [0.0, 0.0, 0.0]

    @classmethod
    def _format_a20(cls, value: object) -> str:
        """Format one RINEX A20 header field."""
        text = str(value or "").strip()
        return text[: cls.HEADER_FIELD_WIDTH].ljust(cls.HEADER_FIELD_WIDTH)

    @classmethod
    def _format_a20_fields(cls, *values: object) -> str:
        """Format a RINEX 60-character content record from A20 fields."""
        return "".join(cls._format_a20(value) for value in values)[: cls.HEADER_CONTENT_WIDTH].ljust(
            cls.HEADER_CONTENT_WIDTH
        )

    @classmethod
    def _normalize_span_code(cls, code: str, fallback: str) -> str:
        """Normalize strings like '1S' to '01S' for long filename/header use."""
        text = str(code or "").strip().upper()
        match = re.match(r"^(\d{1,3})([SMHD])$", text)
        if not match:
            return fallback
        return f"{int(match.group(1)):02d}{match.group(2)}"

    @classmethod
    def format_interval_code(cls, seconds: float) -> str:
        """Format a sampling interval in seconds to a RINEX long-filename code."""
        secs = max(1, int(round(float(seconds))))
        if secs % 86400 == 0 and secs // 86400 <= 99:
            return f"{secs // 86400:02d}D"
        if secs % 3600 == 0 and secs // 3600 <= 99:
            return f"{secs // 3600:02d}H"
        if secs % 60 == 0 and secs // 60 <= 99:
            return f"{secs // 60:02d}M"
        if secs <= 99:
            return f"{secs:02d}S"
        return f"{min(99, secs // 60):02d}M"

    @classmethod
    def format_period_code(cls, seconds: float, fallback: str = "01D") -> str:
        """Format a file span to a standard long-filename period code when possible."""
        secs = max(1, int(round(float(seconds))))
        if secs % 86400 == 0 and secs // 86400 <= 99:
            return f"{secs // 86400:02d}D"
        if secs % 3600 == 0 and secs // 3600 <= 99:
            return f"{secs // 3600:02d}H"
        if secs % 60 == 0 and secs // 60 <= 99:
            return f"{secs // 60:02d}M"
        if secs <= 99:
            return f"{secs:02d}S"
        return cls._normalize_span_code(fallback, "01D")

    def _build_output_path(self, timestamp: datetime) -> str:
        """Build a standard RINEX 3 long filename inside the configured directory."""
        year_day = timestamp.strftime("%Y%j")
        hour_min = timestamp.strftime("%H%M")

        if self.filename_template:
            basename = self.filename_template.format(
                station=self.station_code,
                receiver=self.receiver_number,
                country=self.country_code,
                year_day=year_day,
                hour_min=hour_min,
                period=self.period,
                interval=self.interval,
                datatype=self.datatype,
            )
        else:
            basename = (
                f"{self.station_code}{self.receiver_number}{self.country_code}"
                f"_R_{year_day}{hour_min}_{self.period}_{self.interval}_{self.datatype}.rnx"
            )
        return os.path.join(self.output_directory or ".", basename)

    def open(self) -> bool:
        """Open file for writing."""
        try:
            os.makedirs(self.output_directory or ".", exist_ok=True)
            self.file_handle = open(self.filename, "w", encoding="utf-8")
            return True
        except OSError as exc:
            LOGGER.error("Cannot open RINEX file %s: %s", self.filename, exc)
            return False

    def close(self) -> None:
        """Rewrite the finalized header in place, then close the file."""
        if not self.file_handle:
            return

        if self.header_written and self.header_end_pos is not None:
            self._refresh_header()

        self.file_handle.close()
        self.file_handle = None

    def set_approx_position(self, coords: Optional[List[float]]) -> None:
        """Update APPROX POSITION XYZ using ECEF XYZ coordinates."""
        if coords is None or len(coords) < 3:
            return
        try:
            self.approx_position = [float(coords[0]), float(coords[1]), float(coords[2])]
        except (TypeError, ValueError):
            return

    def _write_header_line(self, content: str, label: str) -> None:
        """Write one strict 60+20 RINEX header line."""
        if not self.file_handle:
            return
        safe_content = (content or "")[: self.HEADER_CONTENT_WIDTH].ljust(self.HEADER_CONTENT_WIDTH)
        safe_label = (label or "")[:20]
        self.file_handle.write(f"{safe_content}{safe_label}\n")

    def _parse_interval_seconds(self) -> float:
        """Parse the filename/header interval code to seconds."""
        if self.header_interval_seconds is not None and self.header_interval_seconds > 0:
            return float(self.header_interval_seconds)

        text = str(self.interval or "").strip().upper()
        match = re.match(r"^(\d+(?:\.\d+)?)\s*([SMHD])$", text)
        if not match:
            try:
                value = float(text)
                return value if value > 0 else 1.0
            except (TypeError, ValueError):
                return 1.0

        value = float(match.group(1))
        unit = match.group(2)
        factors = {"S": 1.0, "M": 60.0, "H": 3600.0, "D": 86400.0}
        return value * factors[unit]

    def _format_obs_time_content(self, obs_time: datetime) -> str:
        """Format TIME OF FIRST/LAST OBS content to match RINEX 3.04 layout."""
        second_total = obs_time.second + obs_time.microsecond / 1e6
        return (
            f"  {obs_time.year:04d}    {obs_time.month:02d}    {obs_time.day:02d}"
            f"    {obs_time.hour:02d}    {obs_time.minute:02d}   {second_total:010.7f}"
            f"     {self.time_system[:12]:<12}"
        )

    def _write_header_block(self) -> None:
        """Write the current header state at the file start position."""
        now = datetime.utcnow()
        first_obs = self.first_epoch or self.file_time or now
        last_obs = self.last_epoch or self.first_epoch or self.file_time or now

        self._write_header_line(
            "     3.04           OBSERVATION DATA    M",
            "RINEX VERSION / TYPE",
        )

        date_text = now.strftime("%Y%m%d %H%M%S")
        pgm_content = f"{'GNSS_ToolBox':<20}{'RTGS':<20}{date_text} UTC"
        self._write_header_line(pgm_content, "PGM / RUN BY / DATE")

        self._write_header_line(self.marker_name, "MARKER NAME")
        self._write_header_line(f"{self.marker_number:<20}", "MARKER NUMBER")
        self._write_header_line(f"{'Automatic':<20}{'RTGS':<40}", "OBSERVER / AGENCY")
        self._write_header_line(
            self._format_a20_fields(self.receiver_serial, self.receiver_type, self.receiver_version),
            "REC # / TYPE / VERS",
        )
        self._write_header_line(
            self._format_a20_fields(self.antenna_number, self.antenna_type, ""),
            "ANT # / TYPE",
        )
        self._write_header_line(
            f"{self.approx_position[0]:14.4f}{self.approx_position[1]:14.4f}{self.approx_position[2]:14.4f}",
            "APPROX POSITION XYZ",
        )
        self._write_header_line(
            f"{self.antenna_delta[0]:14.4f}{self.antenna_delta[1]:14.4f}{self.antenna_delta[2]:14.4f}",
            "ANTENNA: DELTA H/E/N",
        )

        for system in sorted(self.sys_obs_types.keys()):
            obs_types = [str(code).strip().upper() for code in self.sys_obs_types[system] if code]
            if not obs_types:
                continue

            for idx in range(0, len(obs_types), self.OBS_TYPES_PER_HEADER_LINE):
                line_types = obs_types[idx : idx + self.OBS_TYPES_PER_HEADER_LINE]
                obs_str = "".join(f"{obs:>4}" for obs in line_types)
                if idx == 0:
                    content = f"{system}{len(obs_types):5d}{obs_str}"
                else:
                    content = f"{'':6}{obs_str}"
                self._write_header_line(content, "SYS / # / OBS TYPES")

        self._write_header_line("DBHZ", "SIGNAL STRENGTH UNIT")
        self._write_header_line(f"{self._parse_interval_seconds():10.3f}", "INTERVAL")
        self._write_header_line(self._format_obs_time_content(first_obs), "TIME OF FIRST OBS")
        self._write_header_line(self._format_obs_time_content(last_obs), "TIME OF LAST OBS")

        self._write_header_line("", "END OF HEADER")

    def _refresh_header(self) -> None:
        """Rewrite the header in place without disturbing the body."""
        if not self.file_handle:
            return

        current_pos = self.file_handle.tell()
        self.file_handle.seek(0)
        self._write_header_block()
        self.header_end_pos = self.file_handle.tell()
        self.file_handle.seek(max(current_pos, self.header_end_pos))
        self.file_handle.flush()

    def write_header(
        self,
        sys_obs_types: Optional[Dict[str, List[str]]] = None,
        marker_lat: Optional[float] = None,
        marker_lon: Optional[float] = None,
        marker_alt: Optional[float] = None,
        receiver_type: str = "UNKNOWN",
        antenna_type: str = "UNKNOWN",
        antenna_number: str = "",
        receiver_serial: str = "",
        receiver_version: str = "",
    ) -> bool:
        """
        Write the initial header block.

        The header is rewritten on close so first/last observation times and station
        coordinates can be updated after streaming finishes.
        """
        if not self.file_handle and not self.open():
            return False

        if sys_obs_types:
            cleaned: Dict[str, List[str]] = {}
            for system, codes in sys_obs_types.items():
                if not system:
                    continue
                key = str(system)[0].upper()
                normalized = []
                for code in codes or []:
                    obs_code = str(code).strip().upper()
                    if obs_code:
                        normalized.append(obs_code)
                if normalized:
                    cleaned[key] = normalized
            self.sys_obs_types = cleaned

        self.receiver_type = str(receiver_type or self.receiver_type)
        self.receiver_serial = self._format_a20(receiver_serial or self.receiver_serial).strip()
        self.receiver_version = self._format_a20(receiver_version or self.receiver_version).strip()
        self.antenna_type = self._format_a20(antenna_type or self.antenna_type).strip()
        self.antenna_number = self._format_a20(antenna_number or self.antenna_number).strip()

        if marker_lon is not None and marker_lat is not None and marker_alt is not None:
            self.set_approx_position([marker_lon, marker_lat, marker_alt])

        self._refresh_header()
        self.header_written = True
        return True

    def write_observation(self, epoch_time: datetime, satellites: Dict[str, object]) -> bool:
        """
        Write one observation epoch in RINEX 3.04 format.
        """
        if not self.file_handle or not self.header_written:
            return False

        try:
            if not self.first_epoch:
                self.first_epoch = epoch_time
            self.last_epoch = epoch_time

            sat_obs_list = self._prepare_observations(satellites)
            if not sat_obs_list:
                return True

            epoch_header = self._format_epoch_header(epoch_time, len(sat_obs_list))
            self.file_handle.write(epoch_header)

            for sat_data in sat_obs_list:
                self._write_satellite_observations(sat_data)

            self.file_handle.flush()
            return True
        except (OSError, TypeError, ValueError, AttributeError) as exc:
            LOGGER.exception("Error writing observation epoch: %s", exc)
            return False

    def _format_epoch_header(self, epoch_time: datetime, num_sats: int) -> str:
        """Format one RINEX epoch header line."""
        second_total = round(epoch_time.second + epoch_time.microsecond / 1e6, 7)
        if second_total >= 60.0:
            second_total = 59.9999999
        return (
            f"> {epoch_time.year:04d} {epoch_time.month:02d} {epoch_time.day:02d} "
            f"{epoch_time.hour:02d} {epoch_time.minute:02d} {second_total:10.7f}  0"
            f"{num_sats:3d}{'':21}\n"
        )

    def _prepare_observations(self, satellites: Dict[str, object]) -> List[Dict]:
        """Prepare per-satellite observation dictionaries sorted by system then PRN."""
        result: List[Dict] = []

        for sat_id, sat_state in satellites.items():
            if not sat_id or len(sat_id) < 2:
                continue

            system = sat_id[0]
            if system not in self.GNSS_SYSTEMS:
                continue

            try:
                prn = int(sat_id[1:])
            except ValueError:
                continue

            signals = getattr(sat_state, "signals", {})
            if not signals:
                continue

            obs_list: List[Dict] = []
            for sig_id, sig_data in signals.items():
                if getattr(sig_data, "pseudorange", None) is not None:
                    obs_list.append(
                        {"code": f"C{sig_id}", "value": sig_data.pseudorange, "lli": None, "snr": None}
                    )
                if getattr(sig_data, "phase", None) is not None:
                    obs_list.append(
                        {
                            "code": f"L{sig_id}",
                            "value": sig_data.phase,
                            "lli": getattr(sig_data, "half_cycle", 0),
                            "snr": self._get_snr_flag(sig_data),
                        }
                    )
                if getattr(sig_data, "doppler", None) is not None:
                    obs_list.append(
                        {"code": f"D{sig_id}", "value": sig_data.doppler, "lli": None, "snr": None}
                    )
                if getattr(sig_data, "snr", None) is not None:
                    obs_list.append(
                        {"code": f"S{sig_id}", "value": sig_data.snr, "lli": None, "snr": None}
                    )

            if obs_list:
                result.append({"sys": system, "prn": prn, "sat_id": sat_id, "observations": obs_list})

        result.sort(key=lambda item: (item["sys"], item["prn"]))
        return result

    def _get_snr_flag(self, sig_data: object) -> int:
        """Convert SNR in dB-Hz to the RINEX SSI flag range 1-9."""
        snr = getattr(sig_data, "snr", None)
        if snr is None:
            return 0

        try:
            snr_val = float(snr)
        except (TypeError, ValueError):
            return 0

        for threshold, flag in self.SNR_THRESHOLDS:
            if snr_val < threshold:
                return flag
        return 9

    @staticmethod
    def _format_lli_char(flag: object) -> str:
        """Format LLI flag character (0-9) or blank when unavailable."""
        if flag is None:
            return " "
        try:
            value = int(flag)
        except (TypeError, ValueError):
            return " "
        return str(value) if 0 <= value <= 9 else " "

    @staticmethod
    def _format_ssi_char(flag: object) -> str:
        """Format SSI character (1-9) or blank when unavailable."""
        if flag is None:
            return " "
        try:
            value = int(flag)
        except (TypeError, ValueError):
            return " "
        return str(value) if 1 <= value <= 9 else " "

    def _format_observation_field(self, obs_code: str, obs: Optional[Dict]) -> str:
        """Format one 16-character RINEX observation field."""
        if not obs or obs.get("value") is None:
            return " " * 16

        try:
            obs_val = float(obs["value"])
        except (TypeError, ValueError):
            return " " * 16

        value_str = f"{obs_val:14.3f}"
        if len(value_str) > 14:
            value_str = f"{obs_val:14.3E}"[:14]

        if obs_code and obs_code[0] == "L":
            lli_char = self._format_lli_char(obs.get("lli"))
            ssi_char = self._format_ssi_char(obs.get("snr"))
        else:
            lli_char = " "
            ssi_char = " "

        return f"{value_str}{lli_char}{ssi_char}"

    def _write_satellite_observations(self, sat_data: Dict) -> None:
        """
        Write one satellite record using the header-defined observation order.
        """
        if not self.file_handle:
            return

        system = sat_data["sys"]
        prn = sat_data["prn"]
        observations = sat_data["observations"]

        obs_dict: Dict[str, Dict] = {}
        for obs in observations or []:
            code = obs.get("code")
            if code:
                obs_dict[str(code).upper()] = obs

        expected_obs_codes = self.sys_obs_types.get(system, [])
        if not expected_obs_codes:
            return

        line_content = f"{system}{prn:02d}"
        for obs_code in expected_obs_codes:
            normalized_code = str(obs_code).strip().upper()
            line_content += self._format_observation_field(normalized_code, obs_dict.get(normalized_code))

        self.file_handle.write(line_content + "\n")


def save_epoch_to_rinex(
    filename: str,
    epoch_time: datetime,
    satellites: Dict[str, object],
    sys_obs_types: Dict[str, List[str]],
    marker_name: str = "UNKNOWN",
    marker_number: str = "0",
    append_mode: bool = False,
    rinex_options: Optional[Dict] = None,
) -> bool:
    """
    Convenience function to save one observation epoch to a RINEX file.
    """
    opts = rinex_options or {}
    writer = RINEX3Writer(filename, marker_name, marker_number, **opts)

    file_exists = os.path.exists(writer.filename) and os.path.getsize(writer.filename) > 0

    if file_exists and append_mode:
        try:
            writer.file_handle = open(writer.filename, "a", encoding="utf-8")
            writer.header_written = True
        except IOError:
            return False
    else:
        if not writer.open():
            return False
        if not writer.write_header(sys_obs_types=sys_obs_types):
            writer.close()
            return False

    success = writer.write_observation(epoch_time, satellites)

    if not append_mode or not file_exists:
        writer.close()
    else:
        writer.file_handle.flush()

    return success
