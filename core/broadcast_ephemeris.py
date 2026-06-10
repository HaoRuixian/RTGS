"""
Broadcast ephemeris management for supported GNSS constellations.

Handles RTCM message parsing and ephemeris parameter extraction/caching for
GPS, GLONASS, Galileo, BeiDou, QZSS, IRNSS/NavIC, and SBAS.
"""

import math
import threading
from core.gnss_time import GNSSTime
from core.mixed_gnss_reader import getbitu
from typing import Dict, Optional, Tuple


class BroadcastEphemeris:
    """
    Unified Broadcast Ephemeris handler for all GNSS constellations.
    Manages ephemeris parameter extraction, caching, and access.
    """
    
    def __init__(self):
        """Initialize ephemeris cache and locks."""
        self.cache = {}  # Key: "G01", "R02", "E03", "C04", etc.
        self.lock = threading.Lock()
        self.last_updated = {}  # Track last update time for each satellite

    def _align_gps_week(self, raw_week: int) -> int:
        """
        Expand a truncated GNSS week number to the nearest current GPS week.
        """
        current_week = GNSSTime.current_gps_week()
        week = int(raw_week)
        while week < current_week - 512:
            week += 1024
        while week > current_week + 512:
            week -= 1024
        return week

    @staticmethod
    def _getbits(buff: bytes, pos: int, length: int) -> int:
        """Extract signed bits using RTKLIB's two's-complement convention."""
        value = getbitu(buff, pos, length)
        if length <= 0:
            return 0
        if value & (1 << (length - 1)):
            value -= 1 << length
        return value

    @staticmethod
    def _normalize_gps_sow(week: int, sow: float) -> Tuple[int, float]:
        """Normalize GPS week and seconds-of-week after +/- day adjustments."""
        gps_week_seconds = 7 * 24 * 3600
        sow = float(sow)
        while sow < 0.0:
            sow += gps_week_seconds
            week -= 1
        while sow >= gps_week_seconds:
            sow -= gps_week_seconds
            week += 1
        return week, sow
    
    # ========================================================================
    # GPS Ephemeris (Message 1019)
    # ========================================================================
    
    def extract_gps_ephemeris(self, msg) -> Optional[Dict]:
        """
        Extract GPS ephemeris parameters from RTCM message 1019.
        Reference: RTCM 10403.3 Table 3.5-21
        
        Args:
            msg: pyrtcm message object with DF attributes
            
        Returns:
            Dictionary with all GPS ephemeris parameters, or None on error
        """
        try:
            prn = int(msg.DF009)
            sat_key = f"G{prn:02d}"
            
            eph = {
                'system': 'GPS',
                'satellite_id': sat_key,
                'PRN': prn,
                
                # Time parameters
                'week': int(msg.DF076) + 2048,  # GPS Week Number (with continuity)
                'toe': float(msg.DF093),         # Time of Ephemeris (seconds)
                'toc': float(msg.DF081),         # Time of Clock (seconds)
                'iode': int(msg.DF071),          # Issue of Data, Ephemeris
                
                # Keplerian Orbital Parameters
                'a': float(msg.DF092) ** 2,      # Semi-major axis (m)
                'sqrt_a': float(msg.DF092),      # Square root of semi-major axis
                'e': float(msg.DF090),           # Eccentricity (dimensionless)
                'M0': float(msg.DF088) * math.pi,  # Mean Anomaly at reference time (rad)
                'omega': float(msg.DF099) * math.pi,  # Argument of Perigee (rad)
                'Omega0': float(msg.DF095) * math.pi,  # Longitude of Ascending Node (rad)
                'i0': float(msg.DF097) * math.pi,  # Inclination Angle (rad)
                'delta_n': float(msg.DF087) * math.pi,  # Mean Motion Difference (rad/s)
                'Omega_dot': float(msg.DF100) * math.pi,  # Rate of Right Ascension (rad/s)
                'idot': float(msg.DF079) * math.pi,  # Rate of Inclination (rad/s)
                
                # Harmonic Perturbation Coefficients
                'Crs': float(msg.DF086),         # Amplitude of Sine Harmonic Correction to Orbital Radius (m)
                'Crc': float(msg.DF098),         # Amplitude of Cosine Harmonic Correction to Orbital Radius (m)
                'Cus': float(msg.DF091),         # Amplitude of Sine Harmonic Correction to Argument of Latitude (rad)
                'Cuc': float(msg.DF089),         # Amplitude of Cosine Harmonic Correction to Argument of Latitude (rad)
                'Cis': float(msg.DF096),         # Amplitude of Sine Harmonic Correction to Inclination (rad)
                'Cic': float(msg.DF094),         # Amplitude of Cosine Harmonic Correction to Inclination (rad)
                
                # Clock correction coefficients
                'af0': float(msg.DF084),         # SV Clock Bias (seconds)
                'af1': float(msg.DF083),         # SV Clock Drift (s/s)
                'af2': float(msg.DF082),         # SV Clock Drift Rate (s/s²)
                
                # Physical Corrections
                'TGD': float(msg.DF101),         # Group Delay Differential (seconds)
                
                # Health and accuracy
                'health': int(msg.DF102),        # SV Health (6 bits)
                'ura': int(msg.DF077),           # SV Accuracy (User Range Accuracy Index)
                
                # Optional: Fit Interval and L2P flag
                'fit_interval': getattr(msg, 'DF137', None),
                'l2_p_data_flag': int(getattr(msg, 'DF103', 0)) if hasattr(msg, 'DF103') else 0,
                'code_on_l2': self._parse_code_on_l2(int(getattr(msg, 'DF078', 0))),
            }
            
            return eph
            
        except (AttributeError, ValueError) as e:
            return None
    
    # ========================================================================
    # GLONASS Ephemeris (Message 1020)
    # ========================================================================
    
    def extract_glonass_ephemeris(self, msg) -> Optional[Dict]:
        """
        Extract GLONASS ephemeris parameters from RTCM message 1020.
        Reference: RTCM 10403.3 Table 3.5-25/26
        
        Args:
            msg: pyrtcm message object with DF attributes
            
        Returns:
            Dictionary with all GLONASS ephemeris parameters, or None on error
        """
        try:
            prn = int(msg.DF038)
            sat_key = f"R{prn:02d}"
            
            # Parse frequency channel
            freq_chn = int(msg.DF040) - 7  # Table 3.4-6: DF value 7 = channel 0
            
            # Parse time parameters
            tb_seconds = float(msg.DF110) * 15 * 60.0 - 3 * 60 * 60
            
            # Parse tk (time within 15-minute frame)
            # DF107 is 12 bits: hhhhh mmmmm s
            tk_raw = int(msg.DF107)
            tk_h = (tk_raw >> 7) & 0x1F
            tk_m = (tk_raw >> 1) & 0x3F
            tk_s = (tk_raw & 0x01) * 30
            tk_seconds = tk_h * 3600 + tk_m * 60 + tk_s - 3 * 60 * 60
            
            eph = {
                'system': 'GLONASS',
                'satellite_id': sat_key,
                'PRN': prn,
                'slot_number': prn,
                'frequency_channel': freq_chn,
                
                # Time parameters (in seconds within day)
                'tb': tb_seconds + GNSSTime.gps_day_of_week() * 24*3600,                # Time of Ephemeris (Tb in seconds of day)
                'tk': tk_seconds + GNSSTime.gps_day_of_week() * 24*3600,                # Time within 15-minute frame
                'tb_seconds': tb_seconds,        # Reference time
                
                # Cartesian State Vector (Position and Velocity in km and km/s)
                'X': float(msg.DF112),           # Satellite X coordinate (km)
                'Y': float(msg.DF115),           # Satellite Y coordinate (km)
                'Z': float(msg.DF118),           # Satellite Z coordinate (km)
                'Vx': float(msg.DF111),          # Satellite X velocity (km/s)
                'Vy': float(msg.DF114),          # Satellite Y velocity (km/s)
                'Vz': float(msg.DF117),          # Satellite Z velocity (km/s)
                
                # Acceleration (due to solar/lunar perturbations in km/s²)
                'Ax': float(msg.DF113),          # Satellite X acceleration (km/s²)
                'Ay': float(msg.DF116),          # Satellite Y acceleration (km/s²)
                'Az': float(msg.DF119),          # Satellite Z acceleration (km/s²)
                
                # Clock correction parameters
                'tau_n': float(msg.DF124),       # SV Clock Bias (seconds)
                'gamma_n': float(msg.DF121),     # Relative Frequency Offset (dimensionless)
                'delta_tau_n': float(getattr(msg, 'DF125', 0)),  # GLONASS-M only
                
                # Health status
                'health': int(msg.DF104),        # Satellite Health (0=healthy, non-zero=unhealthy)
                'health_available': int(msg.DF105),  # Health Available Flag (0=not available, 1=available)
                
                # Additional flags
                'Bn': int(getattr(msg, 'DF108', 0)),     # Status of Bn parameter
                'P1': int(getattr(msg, 'DF106', 0)),     # GLONASS P1 parameter
                'P2': int(getattr(msg, 'DF109', 0)),     # GLONASS P2 parameter
                'P3': int(getattr(msg, 'DF120', 0)),     # GLONASS P3 parameter
                'P4': int(getattr(msg, 'DF127', 0)),     # GLONASS P4 parameter

                'is_glonass_m' : int(getattr(msg, 'DF130', 0)), # 0=GLONASS, 1=GLONASS-M
                'tau_gps': float(getattr(msg, "DF135", 0.0))
            }
            
            return eph
            
        except (AttributeError, ValueError):
            return None
    
    # ========================================================================
    # Galileo Ephemeris (Messages 1045/1046)
    # ========================================================================
    
    def extract_galileo_ephemeris(self, msg) -> Optional[Dict]:
        """
        Extract Galileo ephemeris parameters from RTCM messages 1045/1046.
        Reference: RTCM 10403.3 Table 3.5-31/32
        
        Args:
            msg: pyrtcm message object with DF attributes
            
        Returns:
            Dictionary with all Galileo ephemeris parameters, or None on error
        """
        try:
            prn = int(msg.DF252)
            sat_key = f"E{prn:02d}"
            
            eph = {
                'system': 'Galileo',
                'satellite_id': sat_key,
                'PRN': prn,
                
                # Time parameters
                'week': int(msg.DF289) + 1024,   # Galileo Week Number (aligned to GPS)
                'toe': float(msg.DF304),         # Time of Ephemeris (seconds)
                'toc': float(msg.DF293),         # Time of Clock (seconds)
                'iod_nav': int(msg.DF290),       # Issue of Data, Navigation (IODnav)
                
                # Keplerian Orbital Parameters
                'a': float(msg.DF303) ** 2,      # Semi-major axis (m)
                'sqrt_a': float(msg.DF303),      # Square root of semi-major axis
                'e': float(msg.DF301),           # Eccentricity
                'M0': float(msg.DF299) * math.pi,  # Mean Anomaly (rad)
                'omega': float(msg.DF310) * math.pi,  # Argument of Perigee (rad)
                'Omega0': float(msg.DF306) * math.pi,  # Longitude of Ascending Node (rad)
                'i0': float(msg.DF308) * math.pi,  # Inclination (rad)
                'delta_n': float(msg.DF298) * math.pi,  # Mean Motion Difference (rad/s)
                'Omega_dot': float(msg.DF311) * math.pi,  # Rate of Right Ascension (rad/s)
                'idot': float(msg.DF292) * math.pi,  # Rate of Inclination (rad/s)
                
                # Harmonic Perturbation Coefficients
                'Crs': float(msg.DF297),         # Amplitude of Sine Harmonic Correction (m)
                'Crc': float(msg.DF309),         # Amplitude of Cosine Harmonic Correction (m)
                'Cus': float(msg.DF302),         # Amplitude of Sine Harmonic Correction (rad)
                'Cuc': float(msg.DF300),         # Amplitude of Cosine Harmonic Correction (rad)
                'Cis': float(msg.DF307),         # Amplitude of Sine Harmonic Correction (rad)
                'Cic': float(msg.DF305),         # Amplitude of Cosine Harmonic Correction (rad)
                
                # Clock correction coefficients
                'af0': float(msg.DF296),         # SV Clock Bias (seconds)
                'af1': float(msg.DF295),         # SV Clock Drift (s/s)
                'af2': float(msg.DF294),         # SV Clock Drift Rate (s/s²)
                                
                # Health and accuracy
                'health' : int(getattr(msg, 'DF315', 0)),  # Satellite Health Status
                
                # Additional Galileo-specific parameters
                'E5a_dvs': int(getattr(msg, 'DF316', 0)),  # E5a Data Validity Status
                'E5b_dvs': int(getattr(msg, 'DF317', 0)),  # E5b Data Validity Status
                'E1_dvs': int(getattr(msg, 'DF318', 0)),   # E1 Data Validity Status
            }
            if msg.identity == '1045':
                eph['SISA'] = int(msg.DF291)    # Signal in Space Accuracy Index
                eph['BGD_E5aE1'] = float(msg.DF312)  # Bias Group Delay E5a-E1 (seconds)
            elif msg.identity == '1046':
                eph['SISA'] = int(msg.DF286)    # Signal in Space Accuracy Index
                eph['BGD_E5aE1'] = float(msg.DF312)  # Bias Group Delay E5a-E1 (seconds)
                eph['BGD_E5bE1'] = float(msg.DF313)  # Bias Group Delay E5b-E1 (seconds)
            return eph
            
        except (AttributeError, ValueError):
            return None
    
    # ========================================================================
    # BeiDou Ephemeris (Message 1042)
    # ========================================================================
    
    def extract_bds_ephemeris(self, msg) -> Optional[Dict]:
        """
        Extract BeiDou ephemeris parameters from RTCM message 1042.
        Reference: RTCM 10403.3 Table 3.5-40/41
        
        Args:
            msg: pyrtcm message object with DF attributes
            
        Returns:
            Dictionary with all BeiDou ephemeris parameters, or None on error
        """
        try:
            if not hasattr(msg, "DF488"):
                return None
            
            prn = int(msg.DF488)
            sat_key = f"C{prn:02d}"
            
            # BeiDou Week starts Jan 1, 2006. Offset from GPS Week is 1356 weeks.
            bds_week = int(msg.DF489)
            gps_week_aligned = bds_week + 1356
            bds_toe = float(msg.DF505)
            bds_toc = float(msg.DF493)
            gps_toe_week, gps_toe = self._normalize_gps_sow(gps_week_aligned, bds_toe + 14.0)
            gps_toc_week, gps_toc = self._normalize_gps_sow(gps_week_aligned, bds_toc + 14.0)
            
            eph = {
                'system': 'BeiDou',
                'satellite_id': sat_key,
                'PRN': prn,
                
                # Time parameters
                'week': gps_toe_week,            # GPS week after RTKLIB bdt2gpst conversion
                'bds_week': bds_week,            # BeiDou Week Number
                'toe': gps_toe,                  # Time of Ephemeris in GPST seconds-of-week
                'toc': gps_toc,                  # Time of Clock in GPST seconds-of-week
                'toe_week': gps_toe_week,
                'toc_week': gps_toc_week,
                'bds_toe': bds_toe,              # Raw BDT Time of Ephemeris (seconds)
                'bds_toc': bds_toc,              # Raw BDT Time of Clock (seconds)
                'aode': int(msg.DF492),          # Age of Data, Ephemeris
                'aodc': int(msg.DF497),          # Age of Data, Clock
                
                # Keplerian Orbital Parameters
                'a': float(msg.DF504) ** 2,      # Semi-major axis (m)
                'sqrt_a': float(msg.DF504),      # Square root of semi-major axis
                'e': float(msg.DF502),           # Eccentricity
                'M0': float(msg.DF500) * math.pi,  # Mean Anomaly (rad) [CRITICAL: multiply by π]
                'omega': float(msg.DF511) * math.pi,  # Argument of Perigee (rad)
                'Omega0': float(msg.DF507) * math.pi,  # Longitude of Ascending Node (rad)
                'i0': float(msg.DF509) * math.pi,  # Inclination (rad)
                'delta_n': float(msg.DF499) * math.pi,  # Mean Motion Difference (rad/s)
                'Omega_dot': float(msg.DF512) * math.pi,  # Rate of Right Ascension (rad/s)
                'idot': float(msg.DF491) * math.pi,  # Rate of Inclination (rad/s)
                
                # Harmonic Perturbation Coefficients
                'Crs': float(msg.DF498),         # Amplitude of Sine Harmonic Correction (m)
                'Crc': float(msg.DF510),         # Amplitude of Cosine Harmonic Correction (m)
                'Cus': float(msg.DF503),         # Amplitude of Sine Harmonic Correction (rad)
                'Cuc': float(msg.DF501),         # Amplitude of Cosine Harmonic Correction (rad)
                'Cis': float(msg.DF508),         # Amplitude of Sine Harmonic Correction (rad)
                'Cic': float(msg.DF506),         # Amplitude of Cosine Harmonic Correction (rad)
                
                # Clock correction coefficients
                'af0': float(msg.DF496),         # SV Clock Bias (seconds)
                'af1': float(msg.DF495),         # SV Clock Drift (s/s)
                'af2': float(msg.DF494),         # SV Clock Drift Rate (s/s²)
                
                # Physical Corrections (Group Delays)
                'TGD1': float(msg.DF513),        # Group Delay Differential B1-B3 (seconds)
                'TGD2': float(msg.DF514),        # Group Delay Differential B2-B3 (seconds)
                
                # Health and accuracy
                'ura': int(msg.DF490),          # User Range Accuracy Index
                'health': int(msg.DF515),        # Satellite Health Status
            }
            
            return eph
            
        except (AttributeError, ValueError):
            return None

    # ========================================================================
    # QZSS Ephemeris (Message 1044)
    # ========================================================================

    def extract_qzss_ephemeris(self, msg) -> Optional[Dict]:
        """
        Extract QZSS ephemeris parameters from RTCM message 1044.
        """
        try:
            slot = int(msg.DF429)
            sat_key = f"J{slot:02d}"
            prn = slot + 192

            eph = {
                'system': 'QZSS',
                'satellite_id': sat_key,
                'PRN': prn,
                'slot_number': slot,
                'week': self._align_gps_week(int(msg.DF452)),
                'toe': float(msg.DF442),
                'toc': float(msg.DF430),
                'iode': int(msg.DF434),
                'iodc': int(msg.DF456),
                'a': float(msg.DF441) ** 2,
                'sqrt_a': float(msg.DF441),
                'e': float(msg.DF439),
                'M0': float(msg.DF437) * math.pi,
                'omega': float(msg.DF448) * math.pi,
                'Omega0': float(msg.DF444) * math.pi,
                'i0': float(msg.DF446) * math.pi,
                'delta_n': float(msg.DF436) * math.pi,
                'Omega_dot': float(msg.DF449) * math.pi,
                'idot': float(msg.DF450) * math.pi,
                'Crs': float(msg.DF435),
                'Crc': float(msg.DF447),
                'Cus': float(msg.DF440),
                'Cuc': float(msg.DF438),
                'Cis': float(msg.DF445),
                'Cic': float(msg.DF443),
                'af0': float(msg.DF433),
                'af1': float(msg.DF432),
                'af2': float(msg.DF431),
                'TGD': float(msg.DF455),
                'health': int(msg.DF454),
                'ura': int(msg.DF453),
                'fit_interval': 4 if int(getattr(msg, 'DF457', 0)) else 2,
                'code_on_l2': self._parse_code_on_l2(int(getattr(msg, 'DF451', 0))),
            }
            return eph
        except (AttributeError, ValueError):
            return None

    # ========================================================================
    # IRNSS / NavIC Ephemeris (Message 1041)
    # ========================================================================

    def extract_irnss_ephemeris(self, msg) -> Optional[Dict]:
        """
        Extract IRNSS/NavIC ephemeris parameters from RTCM message 1041.
        """
        try:
            prn = int(msg.DF516)
            sat_key = f"I{prn:02d}"

            health_flags = 0
            if hasattr(msg, 'DF527'):
                health_flags |= int(msg.DF527) << 1
            if hasattr(msg, 'DF528'):
                health_flags |= int(msg.DF528)

            eph = {
                'system': 'IRNSS',
                'satellite_id': sat_key,
                'PRN': prn,
                'week': self._align_gps_week(int(msg.DF517)),
                'toe': float(msg.DF537),
                'toc': float(msg.DF522),
                'iode': int(msg.DF525),
                'iodc': int(msg.DF525),
                'a': float(msg.DF539) ** 2,
                'sqrt_a': float(msg.DF539),
                'e': float(msg.DF538),
                'M0': float(msg.DF536) * math.pi,
                'omega': float(msg.DF541) * math.pi,
                'Omega0': float(msg.DF540) * math.pi,
                'i0': float(msg.DF543) * math.pi,
                'delta_n': float(msg.DF524) * math.pi,
                'Omega_dot': float(msg.DF542) * math.pi,
                'idot': float(msg.DF535) * math.pi,
                'Crs': float(msg.DF534),
                'Crc': float(msg.DF533),
                'Cus': float(msg.DF530),
                'Cuc': float(msg.DF529),
                'Cis': float(msg.DF532),
                'Cic': float(msg.DF531),
                'af0': float(msg.DF518),
                'af1': float(msg.DF519),
                'af2': float(msg.DF520),
                'TGD': float(msg.DF523),
                'ura': int(msg.DF521),
                'health': health_flags,
                'l5_flag': int(getattr(msg, 'DF527', 0)),
                's_flag': int(getattr(msg, 'DF528', 0)),
            }
            return eph
        except (AttributeError, ValueError):
            return None

    # ========================================================================
    # SBAS Raw Navigation (RTKLIB sbsmsg_t / Type 9)
    # ========================================================================

    def extract_sbas_ephemeris(self, msg) -> Optional[Dict]:
        """
        Extract SBAS GEO navigation parameters from a raw SBAS message.

        The input message mirrors RTKLIB's ``sbsmsg_t`` and is currently fed by
        UBX-RXM-SFRBX decoding in the serial pipeline.
        """
        try:
            if getattr(msg, "sbas_type", None) != 9:
                return None

            prn = int(msg.prn)
            sat_key = f"S{prn:02d}"
            frame = bytes(msg.msg)
            week = int(msg.week)
            tow = int(msg.tow)

            # RTKLIB decode_sbstype9(): reference epoch within the nearest day.
            t = getbitu(frame, 22, 13) * 16 - tow % 86400
            if t <= -43200:
                t += 86400
            elif t > 43200:
                t -= 86400

            t0_week, t0_sow = self._normalize_gps_sow(week, tow + t)

            sva = getbitu(frame, 35, 4)
            svh = 1 if sva == 15 else 0

            eph = {
                'system': 'SBAS',
                'satellite_id': sat_key,
                'PRN': prn,
                'week': t0_week,
                'toe': float(t0_sow),
                'toc': float(t0_sow),
                't0': float(t0_sow),
                'tof': float(tow),
                'sva': int(sva),
                'ura': int(sva),
                'health': int(svh),
                'svh': int(svh),
                'pos': [
                    self._getbits(frame, 39, 30) * 0.08,
                    self._getbits(frame, 69, 30) * 0.08,
                    self._getbits(frame, 99, 25) * 0.4,
                ],
                'vel': [
                    self._getbits(frame, 124, 17) * 0.000625,
                    self._getbits(frame, 141, 17) * 0.000625,
                    self._getbits(frame, 158, 18) * 0.004,
                ],
                'acc': [
                    self._getbits(frame, 176, 10) * 0.0000125,
                    self._getbits(frame, 186, 10) * 0.0000125,
                    self._getbits(frame, 196, 10) * 0.0000625,
                ],
                'af0': self._getbits(frame, 206, 12) * (2 ** -31),
                'af1': self._getbits(frame, 218, 8) * (2 ** -40),
                'af2': 0.0,
                'source': getattr(msg, 'source', 'SBAS RAW'),
            }
            return eph
        except (AttributeError, TypeError, ValueError):
            return None
    
    # ========================================================================
    # Cache Management
    # ========================================================================
    
    def cache_ephemeris(self, eph_dict: Dict, time_key: str = 'toe') -> bool:
        """
        Cache ephemeris data with thread-safe updates.
        
        Args:
            eph_dict: Ephemeris dictionary from extract_*_ephemeris()
            time_key: Which time field to use for checking updates ('toe', 'tb', etc.)
            
        Returns:
            True if updated, False if already cached with same time
        """
        if not eph_dict or 'satellite_id' not in eph_dict:
            return False
        
        sat_id = eph_dict['satellite_id']
        new_time = eph_dict.get(time_key)
        
        with self.lock:
            if sat_id in self.cache:
                old_eph = self.cache[sat_id]
                old_time = old_eph.get(time_key)
                if old_time == new_time:
                    return False  # No update
            
            self.cache[sat_id] = eph_dict
            self.last_updated[sat_id] = self._get_timestamp()
            return True
    
    def get_ephemeris(self, satellite_id: str) -> Optional[Dict]:
        """
        Get cached ephemeris for a satellite.
        
        Args:
            satellite_id: e.g., "G01", "R02", "E03", "C04"
            
        Returns:
            Ephemeris dictionary or None if not cached
        """
        with self.lock:
            return self.cache.get(satellite_id, None)
    
    def get_all_ephemeris(self, system: Optional[str] = None) -> Dict:
        """
        Get all cached ephemeris, optionally filtered by system.
        
        Args:
            system: constellation name or prefix, e.g. 'GPS', 'QZSS', 'I', or None
            
        Returns:
            Dictionary of satellite_id -> ephemeris_dict
        """
        with self.lock:
            if system is None:
                return self.cache.copy()
            
            # Filter by system prefix
            prefix_map = {
                'GPS': 'G',
                'GLONASS': 'R',
                'GALILEO': 'E',
                'BEIDOU': 'C',
                'QZSS': 'J',
                'IRNSS': 'I',
                'NAVIC': 'I',
                'SBAS': 'S',
            }
            prefix = prefix_map.get(str(system).upper(), str(system)[0].upper())
            return {k: v for k, v in self.cache.items() if k[0] == prefix}
    
    def clear_cache(self, satellite_id: Optional[str] = None):
        """
        Clear ephemeris cache.
        
        Args:
            satellite_id: Clear specific satellite, or None to clear all
        """
        with self.lock:
            if satellite_id:
                self.cache.pop(satellite_id, None)
                self.last_updated.pop(satellite_id, None)
            else:
                self.cache.clear()
                self.last_updated.clear()
    
    # ========================================================================
    # Parameter Access Methods
    # ========================================================================
    
    
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    @staticmethod
    def _parse_code_on_l2(code_bits: int) -> str:
        """
        Parse GPS code on L2 field (2 bits).
        
        Args:
            code_bits: DF078 value (2 bits)
            
        Returns:
            String description of L2 code
        """
        code_mapping = {
            0: 'Reserved',
            1: 'P code on L2',
            2: 'C/A code on L2',
            3: 'L2C on L2',
        }
        return code_mapping.get(code_bits, 'Unknown')
    
    @staticmethod
    def _get_timestamp() -> float:
        """Get current timestamp for tracking updates."""
        import time
        return time.time()
    
    def print_ephemeris(self, satellite_id: str, verbose: bool = False):
        """
        Print ephemeris information for a satellite.
        
        Args:
            satellite_id: e.g., "G01", "R02", "E03"
            verbose: If True, print all parameters; if False, only key parameters
        """
        eph = self.get_ephemeris(satellite_id)
        if not eph:
            print(f"{satellite_id}: No ephemeris cached")
            return
        
        system = eph.get('system')
        print(f"\n=== {system} Ephemeris: {satellite_id} ===")
        
        # Common parameters
        print(f"Week: {eph.get('week')}, TOE: {eph.get('toe')}s")
        print(f"Health: {eph.get('health')}, IODE/IOD: {eph.get('iode') or eph.get('iod_nav')}")
        
        if system == 'GLONASS':
            # GLONASS-specific
            pos = self.get_state_vector(satellite_id)
            if pos:
                print(f"Position: X={pos[0]:.2f}km, Y={pos[1]:.2f}km, Z={pos[2]:.2f}km")
                print(f"Velocity: Vx={pos[3]:.4f}km/s, Vy={pos[4]:.4f}km/s, Vz={pos[5]:.4f}km/s")
            print(f"Frequency Channel: {eph.get('frequency_channel')}")
        else:
            # GPS/Galileo/BeiDou
            orb = self.get_orbital_parameters(satellite_id)
            if orb:
                print(f"a={orb['semi_major_axis']/1e6:.4f}Mm, e={orb['eccentricity']:.6f}")
                print(f"i0={math.degrees(orb['inclination']):.2f}°, Ω0={math.degrees(orb['longitude_ascending_node']):.2f}°")
        
        clk = self.get_clock_parameters(satellite_id)
        if clk:
            print(f"Clock: af0={clk['af0']*1e9:.3f}ns, af1={clk['af1']*1e12:.3f}ns/s")
        
        if verbose:
            print("\nAll parameters:")
            for key, value in eph.items():
                if key not in ['system', 'satellite_id']:
                    print(f"  {key}: {value}")


# Module-level singleton for global access
_shared_broadcast_ephemeris = None

def get_var_ura(eph: Optional[Dict]) -> Optional[float]:
    """Get User Range Accuracy (URA) variance (m^2) for a satellite."""
    if not eph:
        return None
    
    sys = eph.get('system')
    
    # ---------------------------------------------------------
    # GPS / BeiDou / QZSS / IRNSS (URA indx)
    # ---------------------------------------------------------
    if sys in ['GPS', 'BeiDou', 'QZSS', 'IRNSS']:
        ura_index = eph.get('ura')
        if ura_index is None:
            return 30.0 ** 2 # (30m std)
        
        ura_table = [
            2.4, 3.4, 4.85, 6.85, 9.65, 13.65, 24.0, 48.0, 96.0, 
            192.0, 384.0, 768.0, 1536.0, 3072.0, 6144.0
        ]
        
        if 0 <= ura_index <= 14:
            std = ura_table[int(ura_index)]
        else:
            std = 6144.0 # low accuracy
            
        return std ** 2
    
    # ---------------------------------------------------------
    # Galileo (SISA indx)
    # ---------------------------------------------------------
    elif sys == 'Galileo':
        sisa = eph.get('SISA')
        if sisa is None:
            return 30.0 ** 2
            
        if sisa <= 49:
            std = sisa * 0.01
        elif sisa <= 74:
            std = 0.5 + (sisa - 50) * 0.02
        elif sisa <= 99:
            std = 1.0 + (sisa - 75) * 0.04
        elif sisa <= 125:
            std = 2.0 + (sisa - 100) * 0.16
        else:
            std = 500.0 # NAPA (No Accuracy Prediction Available)
            
        return std ** 2
    
    # ---------------------------------------------------------
    # GLONASS (通常电文不直接给 URA 指数)
    # ---------------------------------------------------------
    elif sys == 'GLONASS':
        # GLONASS 广播星历通常不包含 URA 索引
        # RTKLIB 通常根据其频率或健康状况给一个经验方差
        # 默认给定一个比 GPS 稍大的标准差 (例如 5.0m - 10.0m)
        return 10.0 ** 2
        
    return 30.0 ** 2 # 最终默认方差
def get_shared_broadcast_ephemeris() -> BroadcastEphemeris:
    """
    Get or create singleton broadcast ephemeris instance.
    
    Returns:
        Shared BroadcastEphemeris instance
    """
    global _shared_broadcast_ephemeris
    if _shared_broadcast_ephemeris is None:
        _shared_broadcast_ephemeris = BroadcastEphemeris()
    return _shared_broadcast_ephemeris
