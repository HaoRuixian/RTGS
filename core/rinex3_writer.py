"""
RINEX Version 3.04 file writer for GNSS observation data.

This module provides functionality to write observation data in the RINEX 3.04 format
as defined by the International GNSS Service (IGS).

Standard format reference: https://files.igs.org/pub/data/format/rinex304.pdf

File naming convention:
{4-char station code}{country}{YYYYDDD+HHMM}{period}{interval}{datatype}.rnx
Example: SCOA00FRA_R_20230010000_01D_30S_MO.rnx
"""

from datetime import datetime
from typing import Dict, List, Optional
import os
import re


class RINEX3Writer:
    """
    Writer for RINEX 3.04 format observation files following standard specification.

    Standard RINEX 3.04 format with proper header structure, epoch format,
    and observation record formatting.
    """

    # GNSS System identifiers
    GNSS_SYSTEMS = {
        "G": "GPS",
        "R": "GLONASS",
        "E": "Galileo",
        "C": "BeiDou",
        "J": "QZSS",
        "S": "SBAS",
        "I": "IRNSS",
    }

    # SNR mapping to 1-9 scale based on dB-Hz thresholds
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
    ):
        """
        Initialize RINEX3 writer.

        Args:
            filename: Output file path. If it does not end in .rnx the writer will
                auto-generate a name using station/country and time. A custom
                template may also be provided via :paramref:`filename_template`.
            marker_name: Receiver/Station marker name (max 60 chars)
            marker_number: Receiver/Station marker number (max 20 chars)
            station_code: 4-character station code (used when auto-generating names)
            country_code: 3-character country/agency code (used when auto-generating names)
            receiver_number: 2-character receiver number (used when auto-generating names, default "00")
            period: Processing period string for filename (e.g. "01D", "01H")
            interval: Sampling interval string (e.g. "30S", "1S")
            datatype: Type code for filename (usually "MO" for observations)
            filename_template: Optional Python format string used to create the
                final filename. Supported placeholders: ``station``, ``receiver``, ``country``,
                ``year_day``, ``hour_min``, ``period``, ``interval``, ``datatype``.
        """
        self.station_code = str(station_code)[:4].upper().ljust(4, "0")
        self.receiver_number = str(receiver_number)[:2].upper().ljust(2, "0")
        self.country_code = str(country_code)[:3].upper().ljust(3, " ")
        self.marker_name = str(marker_name)[:60]
        self.marker_number = str(marker_number)[:20]
        self.period = str(period)
        self.interval = str(interval)
        self.datatype = str(datatype)
        self.filename_template = filename_template

        # Auto-generate filename if not explicitly provided with .rnx suffix
        if not filename.endswith(".rnx"):
            now = datetime.utcnow()
            year_day = now.strftime("%Y%j")
            hour_min = now.strftime("%H%M")
            if self.filename_template:
                filename = self.filename_template.format(
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
                # Standard RINEX 3.04 format:
                # {station(4)}{receiver(2)}{country(3)}_R_{YYYYDDD}{HHMM}_{period}_{interval}_{datatype}.rnx
                filename = (
                    f"{self.station_code}{self.receiver_number}{self.country_code}"
                    f"_R_{year_day}{hour_min}_{self.period}_{self.interval}_{self.datatype}.rnx"
                )

        self.filename = filename
        self.file_handle = None
        self.header_written = False

        # Track observation types per system (used for header)
        self.sys_obs_types: Dict[str, List[str]] = {}
        self.first_epoch: Optional[datetime] = None
        self.last_epoch: Optional[datetime] = None
        self.num_satellites = 0

    def open(self) -> bool:
        """Open file for writing."""
        try:
            os.makedirs(os.path.dirname(self.filename) or ".", exist_ok=True)
            self.file_handle = open(self.filename, "w", encoding="utf-8")
            return True
        except IOError as e:
            print(f"Cannot open RINEX file {self.filename}: {e}")
            return False

    def close(self) -> None:
        """Close the file."""
        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None

    def _write_header_line(self, content: str, label: str) -> None:
        """Write a RINEX header line using strict 60+20 column layout."""
        if not self.file_handle:
            return
        safe_content = (content or "")[: self.HEADER_CONTENT_WIDTH].ljust(self.HEADER_CONTENT_WIDTH)
        safe_label = (label or "")[:20]
        self.file_handle.write(f"{safe_content}{safe_label}\n")

    def _parse_interval_seconds(self) -> float:
        """Parse configured interval string (e.g., 30S, 1M) to seconds."""
        text = str(self.interval or "").strip().upper()
        match = re.match(r"^(\d+(?:\.\d+)?)\s*([SMHD])$", text)
        if not match:
            try:
                val = float(text)
                return val if val > 0 else 30.0
            except Exception:
                return 30.0

        value = float(match.group(1))
        unit = match.group(2)
        factors = {"S": 1.0, "M": 60.0, "H": 3600.0, "D": 86400.0}
        return value * factors[unit]

    def write_header(
        self,
        sys_obs_types: Optional[Dict[str, List[str]]] = None,
        marker_lat: Optional[float] = None,
        marker_lon: Optional[float] = None,
        marker_alt: Optional[float] = None,
        receiver_type: str = "UNKNOWN",
        antenna_type: str = "UNKNOWN",
    ) -> bool:
        """
        Write RINEX 3.04 header following standard format.

        Args:
            sys_obs_types: Dict mapping system to observation types
                          e.g., {'G': ['C1C', 'L1C', 'D1C', 'S1C']}
            marker_lat: Receiver latitude in degrees (optional)
            marker_lon: Receiver longitude in degrees (optional)
            marker_alt: Receiver altitude in meters (optional)
            receiver_type: Type of receiver
            antenna_type: Type of antenna

        Returns:
            True if successful
        """
        if not self.file_handle:
            if not self.open():
                return False

        if sys_obs_types:
            cleaned: Dict[str, List[str]] = {}
            for sys, codes in sys_obs_types.items():
                if not sys:
                    continue
                key = str(sys)[0].upper()
                normalized = []
                for code in codes or []:
                    c = str(code).strip().upper()
                    if c:
                        normalized.append(c)
                if normalized:
                    cleaned[key] = normalized
            self.sys_obs_types = cleaned

        now = datetime.utcnow()

        # RINEX VERSION / TYPE
        self._write_header_line(
            "     3.04           OBSERVATION DATA    M",
            "RINEX VERSION / TYPE",
        )

        # PGM / RUN BY / DATE
        date_text = now.strftime("%Y%m%d %H%M%S")
        pgm_content = f"{'GNSS_ToolBox':<20}{'RTGS':<20}{date_text} UTC"
        self._write_header_line(pgm_content, "PGM / RUN BY / DATE")

        # COMMENT
        self._write_header_line("SNR is mapped to RINEX snr flag value [1-9]", "COMMENT")
        self._write_header_line("LX:     < 12dBHz -> 1; 12-17dBHz -> 2; 18-23dBHz -> 3", "COMMENT")
        self._write_header_line("       24-29dBHz -> 4; 30-35dBHz -> 5; 36-41dBHz -> 6", "COMMENT")
        self._write_header_line("       42-47dBHz -> 7; 48-53dBHz -> 8; >= 54dBHz -> 9", "COMMENT")

        # Basic station/receiver metadata
        self._write_header_line(self.marker_name, "MARKER NAME")
        self._write_header_line(self.marker_number, "MARKER NUMBER")
        self._write_header_line(f"{'Automatic':<20}{'RTGS':<40}", "OBSERVER / AGENCY")

        rec_number = (self.receiver_number or "")[:20]
        rec_type = str(receiver_type or "UNKNOWN")[:20]
        self._write_header_line(f"{rec_number:<20}{rec_type:<20}{'':<20}", "REC # / TYPE / VERS")

        ant_type = str(antenna_type or "UNKNOWN")[:40]
        self._write_header_line(f"{'':<20}{ant_type:<40}", "ANT # / TYPE")

        # Position fields keep legacy input semantics (marker_lon/lat/alt) but enforce strict formatting.
        x = float(marker_lon) if marker_lon is not None else 0.0
        y = float(marker_lat) if marker_lat is not None else 0.0
        z = float(marker_alt) if marker_alt is not None else 0.0
        self._write_header_line(f"{x:14.4f}{y:14.4f}{z:14.4f}", "APPROX POSITION XYZ")

        self._write_header_line(f"{0.0:14.4f}{0.0:14.4f}{0.0:14.4f}", "ANTENNA: DELTA H/E/N")

        # SYS / # / OBS TYPES
        for system in sorted(self.sys_obs_types.keys()):
            obs_types = [str(code).strip().upper() for code in self.sys_obs_types[system] if code]
            num_types = len(obs_types)
            if num_types == 0:
                continue

            for idx in range(0, num_types, self.OBS_TYPES_PER_HEADER_LINE):
                line_types = obs_types[idx : idx + self.OBS_TYPES_PER_HEADER_LINE]
                obs_str = "".join(f"{obs:>4}" for obs in line_types)
                if idx == 0:
                    content = f"{system}{num_types:5d}{obs_str}"
                else:
                    content = f"{'':6}{obs_str}"
                self._write_header_line(content, "SYS / # / OBS TYPES")

        self._write_header_line("DBHZ", "SIGNAL STRENGTH UNIT")

        interval_sec = self._parse_interval_seconds()
        self._write_header_line(f"{interval_sec:10.3f}", "INTERVAL")

        tof = self.first_epoch or now
        tof_sec = tof.second + tof.microsecond / 1e6
        tof_content = (
            f"{tof.year:6d}{tof.month:6d}{tof.day:6d}{tof.hour:6d}"
            f"{tof.minute:6d}{tof_sec:13.7f}     GPS"
        )
        self._write_header_line(tof_content, "TIME OF FIRST OBS")

        tol = self.last_epoch or now
        tol_sec = tol.second + tol.microsecond / 1e6
        tol_content = (
            f"{tol.year:6d}{tol.month:6d}{tol.day:6d}{tol.hour:6d}"
            f"{tol.minute:6d}{tol_sec:13.7f}     GPS"
        )
        self._write_header_line(tol_content, "TIME OF LAST OBS")

        self._write_header_line(f"{0:6d}", "RCV CLOCK OFFS APPL")

        # END OF HEADER must appear at the end of header section.
        self._write_header_line("", "END OF HEADER")

        self.header_written = True
        self.file_handle.flush()
        return True

    def write_observation(self, epoch_time: datetime, satellites: Dict[str, object]) -> bool:
        """
        Write one epoch of observation data in standard RINEX format.

        Epoch format: "> YYYY MM DD HH MM SS.SSSSSSS F N"
        where F is special event flag (0=normal) and N is number of satellites

        Args:
            epoch_time: UTC datetime of the epoch
            satellites: Dictionary of satellites {sat_id: satellite_state}

        Returns:
            True if successful
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

            num_sats = len(sat_obs_list)
            epoch_header = self._format_epoch_header(epoch_time, num_sats)
            self.file_handle.write(epoch_header)

            for sat_data in sat_obs_list:
                self._write_satellite_observations(sat_data)

            self.file_handle.flush()
            return True

        except Exception as e:
            print(f"Error writing observation epoch: {e}")
            return False

    def _format_epoch_header(self, epoch_time: datetime, num_sats: int) -> str:
        """
        Format epoch header line in standard RINEX 3.04 format.

        Format: "> YYYY MM DD HH MM SS.SSSSSSS F N"
        F = special event flag (0=normal)
        N = number of satellites in epoch
        """
        second_total = epoch_time.second + epoch_time.microsecond / 1e6
        return (
            f"> {epoch_time.year:04d} {epoch_time.month:02d} {epoch_time.day:02d} "
            f"{epoch_time.hour:02d} {epoch_time.minute:02d} {second_total:10.7f}  0 {num_sats:3d}\n"
        )

    def _prepare_observations(self, satellites: Dict[str, object]) -> List[Dict]:
        """
        Prepare and sort satellite observations for the epoch.

        Each satellite may carry multiple signals. For every signal we generate up to
        four RINEX observation entries: code (C), phase (L), doppler (D) and signal
        strength (S). The key used in ``SatelliteState.signals`` is the raw
        signal identifier (e.g. "1C", "2W"), so we prepend the corresponding
        observation class letter.

        Returns:
            List of satellite observation dicts sorted by system then PRN
        """
        result: List[Dict] = []

        for sat_id, sat_state in satellites.items():
            if not sat_id or len(sat_id) < 2:
                continue

            sys = sat_id[0]
            if sys not in self.GNSS_SYSTEMS:
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
                        {
                            "code": f"C{sig_id}",
                            "value": sig_data.pseudorange,
                            "lli": None,
                            "snr": None,
                        }
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
                        {
                            "code": f"D{sig_id}",
                            "value": sig_data.doppler,
                            "lli": None,
                            "snr": None,
                        }
                    )

                if getattr(sig_data, "snr", None) is not None:
                    obs_list.append(
                        {
                            "code": f"S{sig_id}",
                            "value": sig_data.snr,
                            "lli": None,
                            "snr": None,
                        }
                    )

            if obs_list:
                result.append(
                    {
                        "sys": sys,
                        "prn": prn,
                        "sat_id": sat_id,
                        "observations": obs_list,
                    }
                )

        result.sort(key=lambda x: (x["sys"], x["prn"]))
        return result

    def _get_obs_codes_for_system(self, system: str) -> List[str]:
        """Get observation codes for a specific system from header."""
        return self.sys_obs_types.get(system, [])

    def _extract_observation_value(self, sig_data: object, code: str) -> Optional[float]:
        """Extract observation value based on code type."""
        if not code:
            return None

        obs_type = code[0]
        if obs_type == "C":
            return getattr(sig_data, "pseudorange", None)
        if obs_type == "L":
            return getattr(sig_data, "phase", None)
        if obs_type == "D":
            return getattr(sig_data, "doppler", None)
        if obs_type == "S":
            return getattr(sig_data, "snr", None)
        return None

    def _get_snr_flag(self, sig_data: object) -> int:
        """
        Convert SNR (in dB-Hz) to RINEX 1-9 scale flag.

        Thresholds:
        <12 -> 1, 12-17 -> 2, 18-23 -> 3, 24-29 -> 4, 30-35 -> 5,
        36-41 -> 6, 42-47 -> 7, 48-53 -> 8, >=54 -> 9
        """
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
        """Format LLI flag character (0-9) or blank if unavailable."""
        if flag is None:
            return " "
        try:
            value = int(flag)
        except (TypeError, ValueError):
            return " "
        return str(value) if 0 <= value <= 9 else " "

    @staticmethod
    def _format_ssi_char(flag: object) -> str:
        """Format SSI/SNR flag character (1-9) or blank if unavailable."""
        if flag is None:
            return " "
        try:
            value = int(flag)
        except (TypeError, ValueError):
            return " "
        return str(value) if 1 <= value <= 9 else " "

    def _format_observation_field(self, obs_code: str, obs: Optional[Dict]) -> str:
        """Format one 16-character observation field."""
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
        Write one satellite record in RINEX 3.04 observation section.

        Observations are written strictly in the order declared in header
        "SYS / # / OBS TYPES" for that GNSS system. Missing observations are
        represented by 16 blanks.
        """
        if not self.file_handle:
            return

        sys = sat_data["sys"]
        prn = sat_data["prn"]
        observations = sat_data["observations"]

        obs_dict: Dict[str, Dict] = {}
        for obs in observations or []:
            code = obs.get("code")
            if code:
                obs_dict[str(code).upper()] = obs

        expected_obs_codes = self.sys_obs_types.get(sys, [])
        if not expected_obs_codes:
            return

        sat_id = f"{sys}{prn:02d}"
        line_content = sat_id

        for obs_code in expected_obs_codes:
            normalized_code = str(obs_code).strip().upper()
            line_content += self._format_observation_field(
                normalized_code,
                obs_dict.get(normalized_code),
            )

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
    Convenience function to save an observation epoch to RINEX file.

    Args:
        filename: Output RINEX file path
        epoch_time: UTC datetime of epoch
        satellites: Dictionary of satellite observation states
        sys_obs_types: Dictionary of observation types per system
        marker_name: Station marker name
        marker_number: Station marker number
        append_mode: If True, append to existing file

    Returns:
        True if successful
    """
    opts = rinex_options or {}
    writer = RINEX3Writer(filename, marker_name, marker_number, **opts)

    file_exists = os.path.exists(filename) and os.path.getsize(filename) > 0

    if file_exists and append_mode:
        # Append to existing file
        try:
            writer.file_handle = open(filename, "a", encoding="utf-8")
            writer.header_written = True
        except IOError:
            return False
    else:
        # Create new file
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

