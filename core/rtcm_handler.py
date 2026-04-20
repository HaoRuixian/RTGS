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
import threading
import math

# Global singleton instance
_shared_rtcm_handler = None

class RTCMHandler:
    def __init__(self, reference_utc=None, compute_geometry=True):
        self.broadcast_eph = get_shared_broadcast_ephemeris()
        self.lock = threading.Lock()
        self.last_gps_week = None  # Track GPS week for continuity
        self.last_station_coords = None  # Store coordinates from 1005/1006 messages
        self.reference_utc = self._normalize_reference_utc(reference_utc)
        self.last_utc_by_system = {}
        self.compute_geometry = bool(compute_geometry)

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
            if msg_id == "1019":
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
                if hasattr(msg, "DF025"):
                    try:
                        coords = [float(msg.DF025), float(msg.DF026), float(msg.DF027)]
                        self.last_station_coords = coords
                    except (ValueError, TypeError):
                        pass
            
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
                
            # --- RTCM 10403.3 Standard: SSR Messages (1057-1062 GPS, 1063-1068 GLONASS) ---
            # GPS SSR Messages
            elif msg_id == "1057":
                return self._handle_gps_ssr_orbit(msg, epoch_data)
            elif msg_id == "1058":
                return self._handle_gps_ssr_clock(msg, epoch_data)
            elif msg_id == "1059":
                return self._handle_gps_ssr_code_bias(msg, epoch_data)
            elif msg_id == "1060":
                return self._handle_gps_ssr_combined(msg, epoch_data)
            elif msg_id == "1061":
                return self._handle_gps_ssr_ura(msg, epoch_data)
            elif msg_id == "1062":
                return self._handle_gps_ssr_high_rate_clock(msg, epoch_data)
            # GLONASS SSR Messages
            elif msg_id == "1063":
                return self._handle_glo_ssr_orbit(msg, epoch_data)
            elif msg_id == "1064":
                return self._handle_glo_ssr_clock(msg, epoch_data)
            elif msg_id == "1065":
                return self._handle_glo_ssr_code_bias(msg, epoch_data)
            elif msg_id == "1066":
                return self._handle_glo_ssr_combined(msg, epoch_data)
            elif msg_id == "1067":
                return self._handle_glo_ssr_ura(msg, epoch_data)
            elif msg_id == "1068":
                return self._handle_glo_ssr_high_rate_clock(msg, epoch_data)
            
        except (ValueError, AttributeError, TypeError, KeyError):
            # Silently skip messages with parsing errors
            pass
        
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
            Parse RTCM 3.2 MSM7 observation message.
            If epoch_data is provided, adds observations to it; otherwise creates new one.
            """
            # Constants
            CLIGHT = 299792458.0
            RANGE_MS = CLIGHT / 1000.0

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
                # GLONASS: DF034 gives milliseconds of day (0..86400e3). Defined as UTC(SU)+3h
                # Convert to seconds-of-week by using the latest non-GLONASS epoch as the
                # day anchor. This keeps offline file conversion coherent across UTC day
                # boundaries where GPS-like systems may already have advanced the timeline.
                day_anchor = self._reference_utc_for_glonass_day()
                day_index = self._utc_day_of_week(day_anchor)
                # Subtract 3 hours to convert UTC(SU)+3h -> UTC seconds-of-day
                seconds_of_day = (epoch_time_s) - 3 * 3600.0
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
            max_cells = 64
            n_cell_found = 0

            for i in range(1, max_cells + 1):
                idx = f"{i:02d}"
                attr = f"CELLPRN_{idx}"
                if hasattr(msg, attr):
                    try:
                        prn = int(getattr(msg, attr))
                        cell_prn_map[i] = prn
                        unique_prns.add(prn)
                        n_cell_found = i
                    except ValueError: continue
                else: break

            if n_cell_found == 0: return None

            sorted_prns = sorted(unique_prns)
            prn_to_sat_idx = {prn: f"{k + 1:02d}" for k, prn in enumerate(sorted_prns)}
            sat_data_cache = {}

            # ------------------------------ Process Satellites (Parse Observations) -------
            for i in range(1, n_cell_found + 1):
                if i not in cell_prn_map: continue

                idx = f"{i:02d}"
                raw_prn = cell_prn_map[i]
                sat_idx = prn_to_sat_idx[raw_prn]
                prn = self._normalize_satellite_number(sys_id, raw_prn)
                sat_key = f"{sys_id}{prn:02d}"

                # Create SatelliteState (but don't calculate position yet)
                if sat_key not in epoch_data.satellites:
                    sat_state = SatelliteState(sys_id, prn)
                    epoch_data.satellites[sat_key] = sat_state
                else:
                    sat_state = epoch_data.satellites[sat_key]

                # Parse Signal Data (Frequency lookup needs refining for GLONASS later)
                try:
                    sig_id = str(getattr(msg, f"CELLSIG_{idx}"))
                except AttributeError: continue
                
                # GLONASS FCN lookup from shared BroadcastEphemeris
                fcn = 0
                if sys_id == 'R':
                    eph_for_fcn = self.broadcast_eph.get_ephemeris(sat_key)
                    if eph_for_fcn:
                        # prefer standardized key name, fallback to older variants if present
                        fcn = eph_for_fcn.get('frequency_channel', eph_for_fcn.get('FreqChannel', 0))

                freq, _ = get_freq(sig_id, sat_key, fcn)

                # --- Extract Observations (Range, Phase, Doppler, etc.) ---
                if raw_prn not in sat_data_cache:
                    rng_int = getattr(msg, f"DF397_{sat_idx}", None)
                    rng_mod = getattr(msg, f"DF398_{sat_idx}", 0)
                    rate_rough = getattr(msg, f"DF399_{sat_idx}", None)

                    r_sat = 0.0
                    if rng_int is not None and rng_int != 255:
                        r_sat = rng_int * RANGE_MS + rng_mod  * RANGE_MS

                    rr_sat = 0.0
                    if msm_variant in (5, 7) and rate_rough is not None and rate_rough != -8192:
                        rr_sat = rate_rough

                    sat_data_cache[raw_prn] = {"r": r_sat, "rr": rr_sat}

                rough_range = sat_data_cache[raw_prn]["r"]
                rough_rate = sat_data_cache[raw_prn]["rr"]

                uses_extended_signal_fields = msm_variant in (6, 7)
                pr_attr = "DF405" if uses_extended_signal_fields else "DF400"
                cp_attr = "DF406" if uses_extended_signal_fields else "DF401"
                lock_attr = "DF407" if uses_extended_signal_fields else "DF402"
                snr_attr = "DF408" if uses_extended_signal_fields else "DF403"

                pr_fine = getattr(msg, f"{pr_attr}_{idx}", None)
                pseudorange = 0.0
                if rough_range != 0.0 and pr_fine is not None:
                    if uses_extended_signal_fields and pr_fine == -524288:
                        pr_fine = None
                if rough_range != 0.0 and pr_fine is not None:
                    pseudorange = rough_range + pr_fine  * RANGE_MS

                cp_fine = getattr(msg, f"{cp_attr}_{idx}", None)
                carrier_phase = 0.0
                if rough_range != 0.0 and cp_fine is not None:
                    if uses_extended_signal_fields and cp_fine == -8388608:
                        cp_fine = None
                if rough_range != 0.0 and cp_fine is not None:
                    ph_m = rough_range + cp_fine  * RANGE_MS
                    if freq > 0:
                        carrier_phase = ph_m * freq / CLIGHT

                rr_fine = getattr(msg, f"DF404_{idx}", None)
                doppler = 0.0
                if (
                    msm_variant in (5, 7)
                    and rough_rate != -8192
                    and rr_fine is not None
                    and rr_fine != -16384
                ):
                    total_rate = rough_rate + rr_fine * 0.0001
                    if freq > 0:
                        doppler = -total_rate * freq / CLIGHT

                snr = getattr(msg, f"{snr_attr}_{idx}", 0)
                lock_time = getattr(msg, f"{lock_attr}_{idx}", 0)
                half_cycle = getattr(msg, f"DF420_{idx}", 0)

                if pseudorange != 0 or carrier_phase != 0 or snr > 0:
                    obs = SignalData(
                        signal_id=sig_id,
                        pseudorange=float(pseudorange),
                        phase=float(carrier_phase),
                        snr=float(snr),
                        lock_time=int(lock_time),
                        half_cycle=int(half_cycle),
                        doppler=float(doppler),
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
