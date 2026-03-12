"""
Single Point Positioning (SPP) using pseudorange measurements.

Theory:
  SPP solves for 4 unknowns (X, Y, Z, clock_bias) using pseudorange observations.
  The observation equation is:
    P = ρ + dT·c + ε
  where:
    P: measured pseudorange (meters)
    ρ: geometric range from satellite to receiver (meters)
    dT: receiver clock bias (seconds)
    c: speed of light
    ε: measurement noise

  For each satellite i:
    P_i = sqrt((X_sat_i - X_rec)^2 + (Y_sat_i - Y_rec)^2 + (Z_sat_i - Z_rec)^2) + c·dT + ε_i

  We linearize and solve using Least Squares:
    x = (A^T·W·A)^(-1)·A^T·W·l
  where:
    A: design matrix (partial derivatives)
    W: weight matrix (optional: based on elevation angle)
    l: observation vector (pseudorange - computed ranges)

References:
  - GNSS Data Processing Vol. I & II by Teunissen & Montenbruck
  - Leick, A. GPS Satellite Surveying (3rd ed.), Wiley, 2004
"""

import math
import numpy as np
from typing import Dict, Optional, Tuple, List


from dataclasses import dataclass, field
from datetime import datetime
import logging

from core.geo_utils import ecef2lla, tropsphere_model, ionospheric_model, calculate_az_el, get_freq
from core.BE2pos import brdc2pos

from core.broadcast_ephemeris import get_var_ura
logger = logging.getLogger(__name__)
SYS_OFFSET_INDICES = {'R': 4, 'E': 5, 'C': 6, 'I': 7, 'J': 8}  # GPS, GLONASS, Galileo, BeiDou system clock bias indices in state vector

@dataclass
class PositioningResult:
    """SPP solution result."""
    timestamp: float  # GPS time of week (seconds)
    epoch_time: datetime  # Epoch datetime
    
    # Solution
    position_ecef: List[float]  # [X, Y, Z] in meters (ECEF)
    clock_bias: float  # Clock bias in meters (dt * c)
    clock_bias_seconds: float  # Clock bias in seconds
    
    # Accuracy metrics
    num_satellites: int  # Number of satellites used
    residuals: List[float]  # Observation residuals
    variance: float  # Variance of unit weight
    std_dev_north: float  # Standard deviation in North
    std_dev_east: float  # Standard deviation in East
    std_dev_up: float  # Standard deviation in Up
    std_dev_clock: float  # Standard deviation of clock bias
    
    # DOP values
    gdop: float  # Geometric DOP
    pdop: float  # Position DOP
    hdop: float  # Horizontal DOP
    vdop: float  # Vertical DOP
    tdop: float  # Time DOP
    
    # Receiver position in LLA
    latitude: float  # Degrees
    longitude: float  # Degrees
    height: float  # Meters
    
    # Quality indicators
    convergence: bool  # Whether solution converged
    solution_status: str  # 'Fixed', 'Uncertain', or 'No Fix'
    # time offsets for other GNSS systems (seconds relative to GPS)
    time_offsets: Dict[str, float] = field(default_factory=dict)

class SPPPositioner:
    """Single Point Positioning engine."""
    
    # Constants
    CLIGHT = 299792458.0  # Speed of light (m/s)
    
    # Default parameters (can be overridden by config)
    DEFAULT_WEIGHT_MODE = 'elevation'  # Options: 'equal', 'elevation', 'snr'
    DEFAULT_MIN_ELEVATION = 10.0  # Degrees
    DEFAULT_MIN_SATELLITES = 4
    DEFAULT_IONOSPHERE_OPT = 'IFLC'  # 'IFLC' or 'SINGLE'
    DEFAULT_TROPOSPHERE_MODEL = 'Sastamoinen'  # 'None', 'Sastamoinen', 'HMSL'
    
    MAX_ITERATIONS = 10
    CONVERGENCE_THRESHOLD = 1e-4  # meters
    
    def __init__(self, ephemeris_handler=None, config: Optional[Dict] = None):
        """
        Initialize SPP positioner.
        
        Args:
            ephemeris_handler: RTCMHandler instance for accessing ephemeris cache
            config: Dictionary with positioning configuration:
                - ionosphere_option: 'IFLC' or 'SINGLE'
                - troposphere_model: 'None', 'Sastamoinen', 'HMSL'
                - min_satellites: Minimum number of satellites (default: 4)
                - min_elevation: Minimum elevation angle in degrees (default: 10)
                - weight_mode: 'equal', 'elevation', or 'snr' (default: 'elevation')
                - gnss_systems: List of systems to use, e.g. ['G', 'R', 'E', 'C']
                - uncertain_std_pos: Standard deviation threshold for "uncertain" status (m)
                - fixed_std_pos: Standard deviation threshold for "fixed" status (m)
        """
        self.handler = ephemeris_handler
        self.last_solution = None
        self.logger = logging.getLogger(__name__)
        
        # Parse configuration
        if config is None:
            config = {}
        
        self.ionosphere_option = config.get('ionosphere_option', self.DEFAULT_IONOSPHERE_OPT)
        self.troposphere_model = config.get('troposphere_model', self.DEFAULT_TROPOSPHERE_MODEL)
        self.MIN_SATELLITES = config.get('min_satellites', self.DEFAULT_MIN_SATELLITES)
        self.MIN_ELEVATION = config.get('min_elevation', self.DEFAULT_MIN_ELEVATION)
        self.WEIGHT_MODE = config.get('weight_mode', self.DEFAULT_WEIGHT_MODE)
        self.gnss_systems = config.get('gnss_systems', ['G', 'R', 'E', 'C'])
        self.uncertain_std_pos = config.get('uncertain_std_pos', 5.0)
        self.fixed_std_pos = config.get('fixed_std_pos', 2.5)
        
        self.logger.info(f"SPP Positioner initialized with config:")
        self.logger.info(f"  Ionosphere: {self.ionosphere_option}")
        self.logger.info(f"  Troposphere: {self.troposphere_model}")
        self.logger.info(f"  Min elevation: {self.MIN_ELEVATION}°")
        self.logger.info(f"  Min satellites: {self.MIN_SATELLITES}")
        self.logger.info(f"  Weight mode: {self.WEIGHT_MODE}")
        self.logger.info(f"  GNSS systems: {self.gnss_systems}")

    def get_tgd_for_sys(self, sys, sat_key, sig_id):
        """
        获取不同系统的 TGD/BGD 修正 (单位: 米)
        """
        eph = self._fetch_ephemeris(sat_key)
        if not eph:
            return 0.0

        CLIGHT = 299792458.0
        
        try:
            # GPS (G) / QZSS (J)
            if sys in ['G', 'J']:
                # GPS 钟差参考的是 L1/L2 无电离层组合
                # 单频 L1 用户需要减去 TGD
                return float(eph.get('TGD', 0.0)) * CLIGHT
            
            # Galileo (E)
            elif sys == 'E':
                # Galileo 比较特殊，取决于你用的信号和星历类型
                # 默认：如果你用 E1 信号，通常参考 I/NAV 的 BGD_E1E5b
                # 如果你用 E5a 信号，通常参考 F/NAV 的 BGD_E1E5a 
                if sig_id.startswith('1'): # E1
                    # 优先获取 E1-E5b 的修正
                    bgd = eph.get('BGD_E1E5b') or eph.get('BGD_E5bE1') or 0.0
                    return float(bgd) * CLIGHT
                elif sig_id.startswith('5'): # E5a
                    bgd = eph.get('BGD_E1E5a') or eph.get('BGD_E5aE1') or 0.0
                    return float(bgd) * CLIGHT
                    
            # Beidou (C)
            elif sys == 'C':
                # 北斗钟差参考的是 B3 频点 (Band 6)
                # B1I (Band 2) 使用 TGD1
                # B2I (Band 7) 使用 TGD2
                # B1C (Band 1) 使用 TGD1 或特定的 ISC
                if sig_id.startswith('2'): # B1I (Band 2)
                    return float(eph.get('TGD1', 0.0)) * CLIGHT
                elif sig_id.startswith('7'): # B2I (Band 7)
                    return float(eph.get('TGD2', 0.0)) * CLIGHT
                elif sig_id.startswith('1'): # B1C (Band 1)
                    # 北斗三号 B1C 修正比较复杂，RTKLIB 针对不同版本有不同处理
                    # 这里暂取 TGD1 (BDS-3 某些星历 B1C 映射到 TGD1)
                    return float(eph.get('TGD1', 0.0)) * CLIGHT
                    
        except (ValueError, TypeError):
            return 0.0
            
        return 0.0

    def _calculate_ionospheric_delay(self, pos, azel, t, ion):
        iono_opt = self.ionosphere_option
        if iono_opt == "IFLC":
            return 0.0, 0.0
        elif iono_opt == "SINGLE":
            iono_delay_m, iono_var = ionospheric_model(pos, azel, t, ion)
            return iono_delay_m, iono_var
        else:
            # Default: no ionospheric correction
            return 0.0

    def calculate_prange(self, sat_key, pr_list, fcn=0):
        iono_opt = self.ionosphere_option
        sys = sat_key[0]
        
        # --- 1. 寻找 P1 和 P2 ---
        P1, P2 = 0.0, 0.0
        sig1_id, sig2_id = None, None
        
        # 逻辑简化：寻找主频和次频
        for sid, val in pr_list:
            if sid.startswith('1'): # L1/E1/B1
                sig1_id, P1 = sid, val
                break
        if sys == 'C' and not sig1_id: # 北斗 B1I 可能是 Band 2
            for sid, val in pr_list:
                if sid.startswith('2'):
                    sig1_id, P1 = sid, val
                    break

        if not sig1_id: return 0.0, 0.0

        # --- 2. 基础偏差修正 (DCB/Code Bias) ---
        # 这里应该调用一个 apply_code_bias 的函数，暂时略过但需注意
        # P1 += self.get_cbias(sat_key, sig1_id)

        # --- 3. 单频模式 ---
        if iono_opt != "IFLC":
            tgd = self.get_tgd_for_sys(sys, sat_key, sig1_id)
            # GLONASS 特殊处理
            if sys == 'R':
                f1, _ = get_freq(sig1_id, sat_key, fcn)
                f2_tmp, _ = get_freq("2C", sat_key, fcn) # 假设参考 G2
                gamma = (f1 / f2_tmp)**2
                return P1 - tgd / (gamma - 1.0), 0.3**2
            
            # GPS/BDS/GAL 一般直接减 TGD
            return P1 - tgd, 0.3**2

        # --- 4. 双频消电离层模式 (IFLC) ---
        for band in ['2', '5', '7', '6']:
            for sid, val in pr_list:
                if sid.startswith(band) and sid != sig1_id:
                    sig2_id, P2 = sid, val
                    break
            if sig2_id: break

        if not sig2_id:
            tgd = self.get_tgd_for_sys(sys, sat_key, sig1_id)
            return P1 - tgd, 0.3**2

        f1, _ = get_freq(sig1_id, sat_key, fcn)
        f2, _ = get_freq(sig2_id, sat_key, fcn)
        gamma = (f1 / f2)**2
        
        # IFLC 核心计算
        P_IF = (P2 - gamma * P1) / (1.0 - gamma)
        
        # 重要：北斗 IFLC 必须修正 TGD 组合项
        if sys == 'C':
            # 获取 B1I 的 TGD1 和 B2I 的 TGD2
            tgd1 = self.get_tgd_for_sys(sys, sat_key, '2C') # TGD_B1I
            tgd2 = self.get_tgd_for_sys(sys, sat_key, '7C') # TGD_B2I
            P_IF -= (tgd2 - gamma * tgd1) / (1.0 - gamma)

        # IFLC 方差放大系数为 3.0 (方差则是 9.0)
        return P_IF, (0.3 * 3.0)**2

    
    def _fetch_ephemeris(self, satellite_id: str) -> Optional[Dict]:
        """
        Robustly fetch broadcast ephemeris for a satellite from the provided handler.

        Supports passing either:
          - a `BroadcastEphemeris` instance (has `get_ephemeris`), or
          - an `RTCMHandler` instance with attribute `broadcast_eph`.
        """
        if self.handler is None:
            return None

        # If handler itself exposes get_ephemeris (e.g., BroadcastEphemeris)
        try:
            if hasattr(self.handler, 'get_ephemeris') and callable(getattr(self.handler, 'get_ephemeris')):
                return self.handler.get_ephemeris(satellite_id)
        except Exception:
            pass

        # If handler wraps BroadcastEphemeris as attribute `broadcast_eph`
        try:
            be = getattr(self.handler, 'broadcast_eph', None)
            if be is not None and hasattr(be, 'get_ephemeris') and callable(getattr(be, 'get_ephemeris')):
                return be.get_ephemeris(satellite_id)
        except Exception:
            pass

        # Fallbacks: handler may provide convenience method names
        try:
            if hasattr(self.handler, 'get_broadcast_eph_correction') and callable(getattr(self.handler, 'get_broadcast_eph_correction')):
                return self.handler.get_broadcast_eph_correction(satellite_id)
        except Exception:
            pass

        return None

    def _geodist(self, rs: np.ndarray, rr: np.ndarray) -> Tuple[Optional[float], Optional[np.ndarray]]:

        dr = rs - rr
        r2 = dr.dot(dr) 
        
        if np.linalg.norm(rs) < 6378137.0: # RE_WGS84
            return None, None
            
        r = np.sqrt(r2)
        if r <= 0:
            return None, None
            
        e = dr / r
        
        # Sagnac 
        #  OMGE * (xs*yr - ys*xr) / CLIGHT
        sagnac = 7.2921151467e-5 * (rs[0] * rr[1] - rs[1] * rr[0]) / self.CLIGHT
        
        return r + sagnac, e
    
    def var_err(self, sat_key: str, el: float) -> float:
        """
        计算伪距测量误差方差
        
        参数:
        opt: 配置字典, 包含 err (误差模型参数), eratio (码/相位误差比), ionoopt (电离层选项)
        obs: 观测数据字典, 包含 SNR (信噪比), Pstd (接收机自带的伪距标准差)
        el:  高度角 (弧度)
        sys: 系统 ID
        """
        fact = 1.0
        
        EFACT_GPS = 1.0
        EFACT_GLO = 1.5
        EFACT_SBS = 2.0
        EFACT_GAL = 1.0
        EFACT_CMP = 1.0
        EFACT_QZS = 1.0
        EFACT_IRN = 1.0

        # 1. 根据系统选择误差系数因子
        if sat_key[0] == 'G': fact = EFACT_GPS
        elif sat_key[0] == 'R': fact = EFACT_GLO
        elif sat_key[0] == 'S': fact = EFACT_SBS
        elif sat_key[0] == 'C': fact = EFACT_CMP
        elif sat_key[0] == 'E': fact = EFACT_GAL
        elif sat_key[0] == 'J': fact = EFACT_QZS
        elif sat_key[0] == 'I': fact = EFACT_IRN
        else: fact = EFACT_GPS

        # 3. 基础方差模型: var = a^2 + b^2 / sin(el)
        # opt['err'][1] 是常数项 a
        # opt['err'][2] 是高度角相关项 b
        err_a = 0.003
        err_b = 0.003
        try:
            varr = (err_a**2) + (err_b**2 / math.sin(el))
        except (ValueError, ZeroDivisionError):
            varr = err_a**2
        # 4. SNR (信噪比) 影响项 (如果配置了参数)
        # opt['err'][5] 是 snr_max, opt['err'][6] 是 snr 相关系数 c
        snr_max = 52.0
        snr_factor = 0.0
        if snr_factor > 0.0:
            # 注意: RTKLIB 内部 SNR 通常是以 0.25 dBHz 为单位的整数，这里假设传入的是实际 dBHz
            # 如果是 RTKLIB 原始数据，此处通常是 obs['SNR'][0] * 0.25
            snr_curr = obs['SNR'][0] 
            snr_diff = max(snr_max - snr_curr, 0)
            varr += (snr_factor**2) * math.pow(10, 0.1 * snr_diff)

        # 5. 应用码/相位误差比 (Code/Phase Error Ratio)
        # 伪距误差通常是相位误差的 100 倍左右
        #varr *= (opt['eratio'][0]**2)

        # 6. 接收机提供的测量标准差 (如果存在)
        # opt['err'][7] 是接收机 Pstd 的权重因子 d
        pstd_factor = 0.0
        if pstd_factor > 0.0 :
            varr += (pstd_factor * obs['Pstd'][0])**2

        # 7. 消电离层组合 (IFLC) 噪声放大
        # 双频组合会放大测量噪声，通常认为标准差放大 3 倍，方差放大 9 倍
        if self.ionosphere_option == "IFLC":
            varr *= (3.0**2)

        # 8. 最终乘上系统因子并返回
        return (fact**2) * varr
    def _compute_initial_position(self, epoch_obs: object) -> Optional[np.ndarray]:
        """
        Compute an initial approximate receiver position from satellite observations.
        Args:
            epoch_obs: EpochObservation object with satellite observations
            approx_position: an optional guess; typically ``None`` 

        Returns:
            Initial position estimate [X, Y, Z] in ECEF (meters), or ``None``
            if there is insufficient data to form a solution.
        """
        if not hasattr(epoch_obs, 'satellites') or len(epoch_obs.satellites) == 0:
            return None

        # Build observation list using whatever approximate position is available
        observations = self._extract_observations(epoch_obs, np.zeros(3))
        if observations is None or len(observations) == 0:
            return None

        # require at least four distinct satellites to solve for 4 unknowns
        unique_sats = {obs['sat_key'] for obs in observations}
        if len(unique_sats) < self.MIN_SATELLITES:
            return None

        # Prepare data arrays for LS
        sat_pos_arr = np.vstack([obs['sat_pos'] for obs in observations])
        pr_arr = np.array([obs['pseudorange'] for obs in observations])

        x0 = np.zeros(3)
        clk0 = 0.0

        # linearized iteration
        max_iter = 10
        tol = 1e-2
        c = float(self.CLIGHT)
        for _ in range(max_iter):
            n = len(observations)
            A = np.zeros((n, 4))
            b = np.zeros(n)
            for i in range(n):
                dr = sat_pos_arr[i] - x0
                rho = np.linalg.norm(dr)
                if rho <= 0:
                    rho = 1e-8
                A[i, :3] = -dr / rho
                A[i, 3] = 1.0
                b[i] = pr_arr[i] - (rho + clk0)
            try:
                dx, *_ = np.linalg.lstsq(A, b, rcond=None)
            except Exception:
                break
            x0 = x0 + dx[:3]
            clk0 = clk0 + dx[3]
            if np.linalg.norm(dx[:3]) < tol and abs(dx[3]) < tol:
                break

        initial_pos = x0

        # update satellite az/el for downstream processing
        try:
            for sat_key, satellite in epoch_obs.satellites.items():
                sat_pos = getattr(satellite, 'sat_pos_ecef', None)
                if sat_pos is None:
                    continue
                az, el = calculate_az_el(np.array(sat_pos, dtype=float), initial_pos)
                try:
                    satellite.azimuth = float(az)
                    satellite.elevation = float(el)
                except Exception:
                    pass
        except Exception:
            # non‑fatal
            pass

        return initial_pos
    
    def process_epoch(self, epoch_obs, approx_position: Optional[np.ndarray] = None) -> Optional[PositioningResult]:
        """
        Process one observation epoch and compute SPP solution.
        
        Args:
            epoch_obs: EpochObservation object with satellite observations
            approx_position: Approximate receiver position [X, Y, Z] in ECEF (meters)
                           If None or all zeros, will be computed automatically from satellite positions
        
        Returns:
            PositioningResult object if solution is valid, None otherwise
        """
        try:
            # make sure approx_position is a numeric numpy array to avoid
            # ambiguous truth values later (e.g. if it contains None)
            if approx_position is not None:
                try:
                    approx_position = np.array(approx_position, dtype=float)
                except Exception:
                    approx_position = None
            else:
                approx_position = np.array([0.0, 0.0, 0.0])

            self._update_satellite_positions(epoch_obs)
            
            solution = self._spp(epoch_obs, approx_position)
            
            if solution is not None:
                self.last_solution = solution
                return solution
            else:
                return None
                
        except Exception as e:
            # log full traceback to aid debugging of unexpected float/None errors
            self.logger.error(f"SPP processing error: {str(e)}", exc_info=True)
            return None
    
    def _update_satellite_positions(self, epoch_obs):
        for sat_key, satellite in epoch_obs.satellites.items():
            sigs = getattr(satellite, 'signals', None)
            if not sigs:
                continue

            # collect all valid pseudorange measurements from this satellite
            pr_list: List[Tuple[str, float, object]] = []
            for sig_id, signal in sigs.items():
                if signal is None:
                    continue
                pr = getattr(signal, 'pseudorange', None)
                if pr is not None and float(pr) > 0:
                    pr_list.append((sig_id, float(pr)))

            if not pr_list:
                continue


            t_rx = getattr(epoch_obs, 'gps_time', None)
            if t_rx is None:
                continue
            t_tx = t_rx - float(pr_list[0][1]) / self.CLIGHT #  transmit time


            eph = self._fetch_ephemeris(sat_key)
            if eph is None:
                continue
            af0 = eph.get('af0', 0.0)
            af1 = eph.get('af1', 0.0)
            af2 = eph.get('af2', 0.0)
            toc = eph.get('toc') or eph.get('Toc') or 0.0
            dt = t_tx - toc
            ts = dt
            for i in range(2):
                clock_bias = af0 + af1 * dt + af2 * dt**2
                dt = ts - clock_bias
            sat_clk_corr_s = af0 + af1 * dt + af2 * dt**2

            # Relativistic correction (for Keplerian systems)
            F_rel = -4.442807633e-10  # Relativistic correction factor
            rel_corr_s = 0.0
            try:
                sqrt_a = float(eph.get('sqrt_a') or eph.get('sqrtA') or 0.0)
                ecc = float(eph.get('e', 0.0))
                M0 = float(eph.get('M0', 0.0))
                delta_n = float(eph.get('delta_n', 0.0))
                toe = float(eph.get('toe') or eph.get('Toe') or 0.0)
                mu = 3.986005e14  # Earth's universal gravitational parameter (m^3/s^2)

                if sqrt_a > 0 and ecc >= 0:
                    A = sqrt_a ** 2
                    n0 = math.sqrt(mu / (A ** 3))
                    n = n0 + delta_n
                    
                    # Time from ephemeris epoch
                    tk = t_tx - toe
                    if tk > 302400:
                        tk -= 604800
                    elif tk < -302400:
                        tk += 604800
                    
                    # Mean anomaly
                    M = M0 + n * tk
                    
                    # Solve Kepler equation (Newton iteration)
                    E = M
                    for _ in range(10):
                        E_old = E
                        sin_E = math.sin(E)
                        cos_E = math.cos(E)
                        denom = 1.0 - ecc * cos_E
                        if abs(denom) < 1e-12:
                            break
                        E = E - (E - ecc * sin_E - M) / denom
                        if abs(E - E_old) < 1e-13:
                            break
                    
                    # Relativistic correction
                    rel_corr_s = F_rel * ecc * sqrt_a * math.sin(E)
            except Exception:
                rel_corr_s = 0.0
            sat_clk_corr_s -= rel_corr_s

            t_tx = t_tx - sat_clk_corr_s

            sys_type = sat_key[0]  # e.g., 'G' for GPS, 'R' for GLONASS
            if sys_type == 'R':
                sys_type = 'GLO'
            # avoid ambiguous truth value if eph happens to be a numpy array
            if eph is not None:
                # Convert to format expected by BE2pos
                eph_for_calc = {
                    'SatType': sys_type,
                    'PRN': eph.get('PRN'),
                }                    
                # Add system-specific fields
                if sys_type == 'GLO':
                    # GLONASS uses Cartesian coordinates
                    eph_for_calc.update({
                        'X': eph.get('X'),      # km
                        'Y': eph.get('Y'),      # km
                        'Z': eph.get('Z'),      # km
                        'Vx': eph.get('Vx'),    # km/s
                        'Vy': eph.get('Vy'),    # km/s
                        'Vz': eph.get('Vz'),    # km/s
                        'Ax': eph.get('Ax'),    # km/s²
                        'Ay': eph.get('Ay'),    # km/s²
                        'Az': eph.get('Az'),    # km/s²
                        'tb': eph.get('tb'),    # Time of ephemeris (seconds within week)
                        'tau_n': eph.get('tau_n'),
                        'gamma_n': eph.get('gamma_n'),
                    })
                else:
                    # GPS, Galileo, BeiDou use Keplerian parameters
                    eph_for_calc.update({
                        'Week': eph.get('week'),
                        'Toe': eph.get('toe'),
                        'sqrtA': eph.get('sqrt_a'),
                        'Eccentricity': eph.get('e'),
                        'M0': eph.get('M0'),
                        'omega': eph.get('omega'),
                        'i0': eph.get('i0'),
                        'OMEGA0': eph.get('Omega0'),
                        'Delta_n': eph.get('delta_n'),
                        'OMEGA_DOT': eph.get('Omega_dot'),
                        'IDOT': eph.get('idot'),
                        'Crs': eph.get('Crs'),
                        'Crc': eph.get('Crc'),
                        'Cus': eph.get('Cus'),
                        'Cuc': eph.get('Cuc'),
                        'Cis': eph.get('Cis'),
                        'Cic': eph.get('Cic'),
                        'af0': eph.get('af0'),
                        'af1': eph.get('af1'),
                        'af2': eph.get('af2'),
                        'Toc': eph.get('toc'),
                    })
                sat_pos = brdc2pos(eph_for_calc, sys_type, t_tx)
                # if ephemeris conversion fails we may get None back
                if sat_pos is None:
                    # stop the correction loop and mark this satellite invalid
                    rho = None
                    break
                var = get_var_ura(eph)

                epoch_obs.satellites[sat_key].sat_var = var  # satellite variance
                epoch_obs.satellites[sat_key].sat_pos_ecef = sat_pos  # update satellite position
                epoch_obs.satellites[sat_key].sat_clk_corr = sat_clk_corr_s # update satellite clock correction in seconds
    def _spp(self, epoch_obs, approx_position: Optional[np.ndarray] = None) -> Optional[PositioningResult]:
        NX = 4 + len(SYS_OFFSET_INDICES)
        x_curr = np.zeros(NX)  # [X,Y,Z, dtr_gps, dtr_glo, dtr_gal, ...] in meters
        x_curr[:3] = approx_position.copy()
        x_curr[3] = 0.0  # initial GPS clock bias guess (meters)

        MAXITR = self.MAX_ITERATIONS
        for i in range(MAXITR):
            res_data = self._estimate_range_res(i, epoch_obs, x_curr)
            if res_data is None:
                self.logger.debug("No valid observations.")
                break
            H, v, var = res_data

            nv = len(v)
            if nv < NX:
                self.logger.debug(f"Lack of valid satellites: ns={nv}")
                break

            # 3. 加权 (Weighting)
            sig = np.sqrt(var)
            v = v / sig
            H = H / sig[:, np.newaxis]  # 每行除以对应的标准差

            print(H)
            # 4. 最小二乘求解 dx = (H^T * H)^-1 * H^T * v
            try:
                # 使用 numpy 的 lstsq 或者直接计算正规方程
                # dx, residuals, rank, s = np.linalg.lstsq(H_weighted, v_weighted, rcond=None)
                # 1. 计算正规方程左侧 (9x43) @ (43x9) = (9x9)
                HTH = H.T @ H 
                Q = np.linalg.inv(HTH)
                dx = Q @ (H.T @ v)
            except np.linalg.LinAlgError:
                self.logger.debug("LSQ error: Matrix is singular.")
                break

            # 5. 更新状态量
            x_curr += dx

            # 6. 检查收敛 (位置更新量小于阈值，如 0.1mm)
            sol_stat = 0
            if np.linalg.norm(dx[:3]) < 1E-4:
                # 7. 验证解的可靠性 (等同于 RTKLIB 的 valsol)
                if self._validate_solution(v, nv, NX):
                    sol_stat = 1 # 找到有效解
                break
        
        if sol_stat == 1:
            # 8. 封装结果返回
            return self._finalize_result(epoch_obs, x_curr, Q, nv)
        
        return None

    def _validate_solution(self, v, nv, nx) -> bool:
        """ 简单的残差验证 (Chi-square test 简化版) """
        if nv <= nx:
            return False
        # 计算单位权标准差 (Standard deviation of unit weight)
        # v 已经是加权后的残差或者需要在这里结合 var 计算
        # 此处简化处理：
        vv = np.dot(v, v)
        sigma0_sq = vv / (nv - nx)
        if sigma0_sq > self.MAX_UNIT_VAR: # 预设一个阈值，如 30.0
            return False
        return True

    def _finalize_result(self, epoch_obs, x, Q, ns) -> PositioningResult:
        """ 整理最终的定位结果对象 """
        # 时间修正：GPS time - receiver clock bias
        t_rx = epoch_obs.gps_time
        # x[3] 是以米为单位的钟差，除以光速转为秒
        corrected_time = t_rx - (x[3] / self.CLIGHT)
        
        # 提取各个系统的钟偏 (s)
        # dtr 对应 [GPS, GLO, GAL, BDS, IRN, QZS]
        dtr = np.zeros(6)
        dtr[0] = x[3] / self.CLIGHT
        if len(x) > 4:
            # 根据 SYS_OFFSET_INDICES 依次提取
            # 注意：这里的逻辑需对应你在 _estimate_range_res 中 sys_idx 的设计
            # 假设 sys_idx 4=GLO, 5=GAL, 6=BDS...
            for i, idx in enumerate(range(4, len(x))):
                if i+1 < len(dtr):
                    dtr[i+1] = x[idx] / self.CLIGHT

        # 构建 PositioningResult
        res = PositioningResult(
            time=corrected_time,
            pos=x[:3],         # ECEF XYZ
            vel=np.zeros(3),   # SPP 通常不估算速度，或通过多普勒估算
            dtr=dtr,           # 各系统钟偏
            cov=Q[:3, :3],     # 位置协方差
            ns=ns,             # 使用卫星数
            stat=1             # 状态码
        )
        return res

        
    def _estimate_range_res(self, i, epoch_obs, x_curr
    ) -> Optional[List[Dict]]:
        """Build residuals, design matrix and variance for an SPP epoch.
        * Validate each satellite (system filtering, duplicates, elevation mask,
          etc.).
        * Compute geometric range and azimuth/elevation from the current
          receiver estimate ``x_curr``.
        * Apply all relevant corrections including satellite clock, relativistic
          term, tropo/iono models (according to the configured options), and
          system-specific time offsets (GLONASS/BeiDou/Galileo, etc.).
        * Form an observation dictionary for each usable satellite containing the
          residual, design matrix row and estimated variance.  These dictionaries
          are later consumed by ``_solve_least_squares()``.

        Parameters
        ----------
        i : int
            Iteration index (zero-based) of the outer nonlinear solver.  When
            ``i == 0`` only geometric quantities are computed; corrections are
            applied from the second iteration onwards.
        epoch_obs : object
            An ``EpochObservation`` instance containing ``satellites`` with
            associated signal measurements (pseudoranges, SNR, etc.).
        x_curr : numpy.ndarray
            Current state vector containing receiver position and clock bias
            (and optionally additional system offsets) in metres.  Only the
            first three elements (ECEF XYZ) and index 3 (GPS clock bias) are
            referenced here.

        Returns
        -------
        Optional[List[Dict]]
            A list of per-satellite observation dictionaries with keys ``'H'``,
            ``'v'`` and ``'var'``.  ``None`` is returned if the processing
            cannot proceed (e.g. missing time or position information).
        """
        cur_pos = x_curr[:3]
        dtr = x_curr[3]  # GPS clock bias in meters

        CLIGHT = self.CLIGHT
        
        try:
            # Step 1: Convert receiver position from ECEF to LLA for tropospheric model
            rec_lat_rad, rec_lon_rad, rec_h = ecef2lla(cur_pos)
            rec_lla = (rec_lat_rad, rec_lon_rad, rec_h)
            apply_tropo = True
        except Exception as e:
            self.logger.debug(f"Failed to convert receiver position to LLA: {e}")
            rec_lla = None
            apply_tropo = False

        # retrieve GPS receiver time from epoch observation
        t_rx = getattr(epoch_obs, 'gps_time', None)
        if t_rx is None:
            return None
        # ============================================
        # iterate through each satellite in the epoch
        # ============================================
        num_sats = len(epoch_obs.satellites)
        v_res = np.zeros(num_sats)  # residuals vector
        H = np.zeros((num_sats, len(x_curr)))  # design matrix
        var = np.zeros(num_sats)  # variance for pseudorange error
        indx = -1
        sys_mask = np.zeros(6, dtype=bool)  # mask for system offsets [GLO, GAL, BDS, IRN, QZS]
        for sat_key, satellite in epoch_obs.satellites.items():
            indx += 1
            sigs = getattr(satellite, 'signals', None)
            if not sigs:
                continue

            # Extract satellite system character
            sys_char = sat_key[0]

            # Collect all valid pseudorange measurements for this satellite
            pr_list = []
            for sig_id, signal in sigs.items():
                if signal is None:
                    continue
                pr = getattr(signal, 'pseudorange', None)
                if pr is not None and float(pr) > 0:
                    pr_list.append((sig_id, float(pr)))

            if not pr_list:
                continue

            # Get satellite position and clk (precomputed by _update_satellite_positions)
            sat_pos = getattr(satellite, 'sat_pos_ecef', None)
            sat_clk_corr_s = getattr(satellite, 'sat_clk_corr', 0.0)
            sat_var = getattr(satellite, 'sat_var', 0.0)
            if sat_pos is None:
                continue
            sat_pos = np.array(sat_pos, dtype=float)

            # ========================================
            # Geometric distance and elevation angle
            # ========================================
            rho, _ = self._geodist(sat_pos, cur_pos)
            if rho is None or rho <= 0:
                continue

            # Calculate azimuth and elevation
            try:
                az, el = calculate_az_el(sat_pos, cur_pos)

                el_rad = math.radians(float(el))
                az_rad = math.radians(float(az))
            except Exception:
                el = 0.0
                az = 0.0
                el_rad = 0.0
                az_rad = 0.0

            # Fetch ephemeris data
            eph = self._fetch_ephemeris(sat_key)
            if eph is None:
                continue

            if i > 0:
                # Check elevation mask
                #if el < self.MIN_ELEVATION:
                #    continue

                # Tropospheric delay
                tropo_delay_m = 0.0
                if apply_tropo and rec_lla is not None:
                    try:
                        azel = (az_rad, el_rad)
                        tropo_delay_m, trop_var = self._calculate_tropospheric_delay(self,rec_lla, azel)
                    except Exception as e:
                        self.logger.debug(f"Tropospheric delay failed for {sat_key}: {e}")
                        tropo_delay_m = 0.0
                        trop_var = 0.0
                # ionospheric delay
                ion = None # placeholder for ionospheric model parameters if needed
                t = t_rx - rho / CLIGHT
                iono_delay_m, iono_var = self._calculate_ionospheric_delay(self, rec_lla, azel, t, ion)
            else:
                iono_delay_m = 0.0
                iono_var = 0.0
                tropo_delay_m = 0.0
                trop_var = 0.0
            
            if sys_char != 'R':
                P, p_var = self.calculate_prange(sat_key, pr_list)
            else:
                fcn = eph.get('frequency_channel')
                P, p_var = self.calculate_prange(sat_key, pr_list, fcn)
            v_res[indx] = P - (rho + dtr - self.CLIGHT*sat_clk_corr_s + tropo_delay_m + iono_delay_m)  # residual
            var[indx] = p_var + sat_var + self.var_err(sat_key, el) + trop_var + iono_var # measurement variance + satellite variance + base error
            # design matrix
            e = (sat_pos - cur_pos) / rho
            
            for j in range(len(x_curr)):
                if j < 3:
                    H[indx,j] = -e[j]
                elif j == 3:
                    H[indx,j] = 1.0
                else:
                    H[indx,j] = 0.0
            
            # adjust residual for multi‑system time offset and mark column in H
            sys_idx = -1
            if sys_char == 'R': # GLONASS
                sys_idx = 4
                sys_mask[1] = True
            elif sys_char == 'E': # Galileo
                sys_idx = 5
                sys_mask[2] = True
            elif sys_char == 'C': # Beidou
                sys_idx = 6
                sys_mask[3] = True
            elif sys_char == 'I': # IRNS
                sys_idx = 7
                sys_mask[4] = True
            elif sys_char == 'J': # QZSS
                sys_idx = 8
                sys_mask[5] = True
            else:
                sys_mask[0] = True

            if sys_idx != -1 and sys_idx < len(x_curr):
                v_res[indx] -= x_curr[sys_idx]  # subtract estimated system clock offset
                H[indx,sys_idx] = 1.0      # enable corresponding column in design matrix
        

        v_list = v_res[:indx].tolist()
        H_list = H[:indx, :].tolist() if H.shape[0] == num_sats else H[:, :indx].T.tolist()
        var_list = var[:indx].tolist()

        num_clks = len(x_curr) - 3
        for icon in range(num_clks):
            if sys_mask[icon]: 
                continue 
                
            v_constraint = 0.0
            h_constraint = np.zeros(len(x_curr))
            h_constraint[icon + 3] = 1.0 
            var_constraint = 0.01
            
            # 现在可以 append 了，因为它们已经是 list 了
            v_list.append(v_constraint)
            H_list.append(h_constraint.tolist()) # H 的每一行也要转成 list 或保持 1D array
            var_list.append(var_constraint)

        # --- 3. 约束完成后，统一转回 NumPy 数组返回 ---
        v_res_final = np.array(v_list)
        H_final = np.array(H_list)
        var_final = np.array(var_list)

        return H_final, v_res_final, var_final

    def _calculate_tropospheric_delay(self, rec_lla_rad, azel_rad):
        """
        Calculate tropospheric delay based on configured model.
        
        Args:
            rec_lla_rad: (latitude_rad, longitude_rad, height_m)
            azel_rad: (azimuth_rad, elevation_rad)
        
        Returns:
            Tropospheric delay in meters (0.0 if model is 'None')
        """
        if self.troposphere_model == 'None' or self.troposphere_model is None:
            return 0.0, 0.0
        elif self.troposphere_model == 'Sastamoinen':
            # Use the standard Sastamoinen model with 70% humidity
            try:
                trop_delay, trop_var = tropsphere_model(rec_lla_rad, azel_rad, humi=0.7)
                return trop_delay, trop_var
            except Exception as e:
                self.logger.debug(f"Sastamoinen tropospheric model failed: {e}")
                return 0.0, 0.0
        elif self.troposphere_model == 'HMSL':
            # Simple height-based model: delay proportional to height above reference
            try:
                height_m = rec_lla_rad[2]
                trop_delay = max(0.0, 2.3 - 0.0001 * height_m) # 2.3 m at sea level, decreases with height
                trop_var = (0.5)**2 # assume a fixed variance for this simple model
                return trop_delay, trop_var
            except Exception as e:
                self.logger.debug(f"HMSL tropospheric model failed: {e}")
                return 0.0, 0.0
        else:
            self.logger.warning(f"Unknown troposphere model: {self.troposphere_model}")
            return 0.0, 0.0

    def _add_isb_constraints(self, obs_data, x_curr):
        """处理没看到的系统，防止矩阵求逆失败"""
        present_sys_indices = set()
        for obj in obs_data:
            indices = np.where(obj['H'][4:] == 1.0)[0]
            if len(indices) > 0:
                present_sys_indices.add(indices[0] + 4)

        # 检查每个 ISB 状态位 (4, 5, 6, 7...)
        for i in range(4, len(x_curr)):
            if i not in present_sys_indices:
                h_const = np.zeros(len(x_curr))
                h_const[i] = 1.0
                obs_data.append({
                    'sat': 'FIX',
                    'v': 0.0,
                    'H': h_const,
                    'var': 0.01**2, # 给一个很小的方差，强制该系统偏置趋于 0
                    'azel': (0, 0)
                })
        return obs_data

    
    def _solve_least_squares(
        self, observations: List[Dict], approx_position: np.ndarray, gps_time: float
    ) -> Optional[PositioningResult]:
        """
        Iterative least-squares solution for SPP.
        
        Solves the system:
          A·x = b
        where:
          A: Design matrix (n_sat x NX), each row contains the partial
             derivatives with respect to the three position components and
             one clock bias term plus additional columns for any multi-
             system time offsets (e.g. GLONASS‑GPS, Galileo‑GPS, etc.).
          x: State vector [ΔX, ΔY, ΔZ, dtr_gps, dtr_glo, dtr_gal, ...]
             (clock bias and offsets are in meters)
          b: Pseudorange residuals
        """
        # State vector length: 3 position components + 1 GPS clock bias +
        # one offset per additional system (GLONASS, Galileo, BeiDou, IRNSS).
        # This mirrors the C estpos routine where NX is typically 8.
        NX = 4 + len(SYS_OFFSET_INDICES)
        x_curr = np.zeros(NX)  # [ΔX, ΔY, ΔZ, dtr_gps, dtr_glo, dtr_gal, ...] in meters
        pos_curr = approx_position.copy()

        convergence = False

        # Parameters for robust estimation
        MAX_IRLS = 5
        BASE_SIGMA = 5.0  # baseline std dev (m) at zenith

        n_sat = len(observations)
        if n_sat < self.MIN_SATELLITES:
            return None

        # Precompute satellite data arrays
        sat_pos_arr = np.vstack([obs['sat_pos'] for obs in observations])
        pr_raw_arr = np.array([obs['raw_pseudorange'] for obs in observations])
        sat_clk_corr_arr = np.array([obs['sat_clock_correction_m'] for obs in observations])
        # Force float dtype to avoid object arrays (which trigger ambiguous-boolean
        # errors and ufunc loops that expect a "radians" method on each element).
        # ensure numeric values; None -> 0.0 to avoid float(None) errors
        el_arr = np.array([
            float(obs['elevation']) if obs.get('elevation') is not None else 0.0
            for obs in observations
        ], dtype=float)
        az_arr = np.array([
            float(obs['azimuth']) if obs.get('azimuth') is not None else 0.0
            for obs in observations
        ], dtype=float)

        # initial per-observation variance (elevation-based)
        sin_el = np.sin(np.radians(el_arr))
        sin_el[sin_el <= 1e-6] = 1e-6
        var_obs = (BASE_SIGMA ** 2) / (sin_el ** 2)
        W_diag = 1.0 / var_obs  # inverse variance

        for irls in range(MAX_IRLS):
            # ================================================================
            # Recompute tropospheric corrections for current position estimate
            # ================================================================
            pr_meas_arr = np.zeros(n_sat)
            try:
                # Get current receiver position in LLA
                pos_lla = ecef2lla(pos_curr)
                rec_lat = math.radians(pos_lla[0])
                rec_lon = math.radians(pos_lla[1])
                rec_h = pos_lla[2]
                rec_lla = (rec_lat, rec_lon, rec_h)
                
                # Recalculate pseudoranges with updated tropospheric delay
                for i in range(n_sat):
                    # Apply tropospheric correction based on configured model
                    tropo_delay = self._calculate_tropospheric_delay(
                        rec_lla, 
                        (math.radians(az_arr[i]), math.radians(el_arr[i]))
                    )
                    pr_meas_arr[i] = pr_raw_arr[i] - sat_clk_corr_arr[i] - tropo_delay
            except Exception as e:
                self.logger.debug(f"Tropospheric correction in iteration failed: {e}")
                # Fallback: use pseudoranges from observations (already have basic corrections)
                pr_meas_arr = np.array([obs['pseudorange'] for obs in observations])
            
            # build design matrix A and observation vector b for current estimate
            A = np.zeros((n_sat, NX))
            b = np.zeros(n_sat)
            for i in range(n_sat):
                dr = sat_pos_arr[i] - pos_curr
                rho = np.linalg.norm(dr)
                if rho > 0:
                    A[i, :3] = -dr / rho

                # GPS clock bias term (always present at index 3)
                A[i, 3] = 1.0

                # system-specific offset terms
                sys_char = observations[i]['sat_key'][0]
                if sys_char in SYS_OFFSET_INDICES:
                    idx = SYS_OFFSET_INDICES[sys_char]
                    # make sure idx < NX
                    if idx < NX:
                        A[i, idx] = 1.0
                        b[i] = pr_meas_arr[i] - (rho + x_curr[3] + x_curr[idx])
                    else:
                        # unknown system, fall back to GPS bias only
                        b[i] = pr_meas_arr[i] - (rho + x_curr[3])
                else:
                    # treat as GPS
                    b[i] = pr_meas_arr[i] - (rho + x_curr[3])

            # apply sqrt weights and solve via least squares (more stable than normal eq)
            w_sqrt = np.sqrt(W_diag)
            Aw = A * w_sqrt[:, np.newaxis]
            bw = b * w_sqrt
            try:
                # delta = least squares solution of Aw * delta = bw
                delta_x, *_ = np.linalg.lstsq(Aw, bw, rcond=None)
            except Exception as e:
                self.logger.error(f"Least squares failed: {e}")
                return None

            pos_curr = pos_curr + delta_x[:3]
            x_curr = x_curr + delta_x

            # compute residuals with updated state (including any system offsets)
            residuals = np.zeros(n_sat)
            for i in range(n_sat):
                rho = np.linalg.norm(sat_pos_arr[i] - pos_curr)
                sys_char = observations[i]['sat_key'][0]
                offset_term = 0.0
                if sys_char in SYS_OFFSET_INDICES and SYS_OFFSET_INDICES[sys_char] < NX:
                    offset_term = x_curr[SYS_OFFSET_INDICES[sys_char]]
                residuals[i] = pr_meas_arr[i] - (rho + x_curr[3] + offset_term)

            # compute weighted sum of squared residuals (SSR) for scale
            dof = max(1, n_sat - NX)
            SSR = np.sum((residuals ** 2) * W_diag)
            variance_uow = SSR / dof
            sigma = math.sqrt(variance_uow) if variance_uow > 0 else 1.0

            # Huber threshold
            k = 1.345 * sigma
            # robust weights: 1 for |r|<=k, else k/|r|
            abs_r = np.abs(residuals)
            huber_w = np.ones(n_sat)
            mask = abs_r > k
            huber_w[mask] = (k / abs_r[mask])

            # update W_diag and check for convergence of delta
            new_W_diag = (1.0 / var_obs) * huber_w
            if np.linalg.norm(new_W_diag - W_diag) < 1e-6:
                W_diag = new_W_diag
                convergence = np.linalg.norm(delta_x[:3]) < self.CONVERGENCE_THRESHOLD
                break
            W_diag = new_W_diag

        # final A matrix for covariance (same build as above)
        A_final = np.zeros((n_sat, NX))
        for i in range(n_sat):
            dr = sat_pos_arr[i] - pos_curr
            rho = np.linalg.norm(dr)
            if rho > 0:
                A_final[i, :3] = -dr / rho
            A_final[i, 3] = 1.0
            sys_char = observations[i]['sat_key'][0]
            if sys_char in SYS_OFFSET_INDICES and SYS_OFFSET_INDICES[sys_char] < NX:
                A_final[i, SYS_OFFSET_INDICES[sys_char]] = 1.0

        # compute final residuals incorporating offsets
        residuals_final = np.zeros(n_sat)
        for i in range(n_sat):
            rho = np.linalg.norm(sat_pos_arr[i] - pos_curr)
            sys_char = observations[i]['sat_key'][0]
            offset_term = 0.0
            if sys_char in SYS_OFFSET_INDICES and SYS_OFFSET_INDICES[sys_char] < NX:
                offset_term = x_curr[SYS_OFFSET_INDICES[sys_char]]
            residuals_final[i] = pr_meas_arr[i] - (rho + x_curr[3] + offset_term)

        SSR_final = np.sum((residuals_final ** 2) * W_diag)
        variance_uow = SSR_final / max(1, n_sat - NX)

        # covariance matrix: var_uow * inv(A^T W A)
        W_mat = np.diag(W_diag)
        AtWA_final = A_final.T @ W_mat @ A_final
        # regularize to avoid singular
        AtWA_final += 1e-12 * np.eye(NX)
        try:
            Q = np.linalg.inv(AtWA_final)  # geometry/information matrix inverse
            cov_matrix = variance_uow * Q
        except np.linalg.LinAlgError:
            self.logger.warning("Covariance inversion failed")
            Q = None
            cov_matrix = None

        # compute standard deviations in ECEF from covariance
        if cov_matrix is not None and cov_matrix.shape[0] >= 4:
            std_clock = math.sqrt(max(cov_matrix[3, 3], 0.0))
        else:
            std_clock = 0.0

        # Compute DOP values
        try:
            gdop, pdop, hdop, vdop, tdop = self._compute_dop(pos_curr, observations, cov_matrix, variance_uow)
        except Exception:
            gdop = pdop = hdop = vdop = tdop = 0.0
        
        # Convert ECEF to LLA (returns lat_rad, lon_rad, h)
        lla = ecef2lla(pos_curr)
        
        # Compute positional standard deviation (horizontal RMS)
        if cov_matrix is not None and cov_matrix.shape[0] >= 3:
            std_x = math.sqrt(max(cov_matrix[0, 0], 0.0))
            std_y = math.sqrt(max(cov_matrix[1, 1], 0.0))
            std_z = math.sqrt(max(cov_matrix[2, 2], 0.0))
            std_pos = math.sqrt(std_x**2 + std_y**2 + std_z**2)  # 3D position std
        else:
            std_pos = float('inf')
        
        # Determine solution status based on convergence and std dev thresholds
        if len(observations) < self.MIN_SATELLITES:
            solution_status = 'No Fix'
        elif convergence and std_pos <= self.fixed_std_pos:
            solution_status = 'Fixed'
        elif std_pos <= self.uncertain_std_pos:
            solution_status = 'Uncertain'
        else:
            solution_status = 'No Fix'
        
        # Extract LLA values (lla is already in radians)
        lat_rad = lla[0]
        lon_rad = lla[1]
        
        # Rotation matrix ECEF->ENU
        sl = math.sin(lat_rad)
        cl = math.cos(lat_rad)
        slon = math.sin(lon_rad)
        clon = math.cos(lon_rad)
        
        R = np.array([
            [-slon, clon, 0],
            [-sl*clon, -sl*slon, cl],
            [cl*clon, cl*slon, sl]
        ])
        
        cov_enu = R @ cov_matrix[:3, :3] @ R.T if cov_matrix is not None else np.zeros((3, 3))
        std_north = math.sqrt(max(cov_enu[0, 0], 0)) if cov_matrix is not None else 0.0
        std_east = math.sqrt(max(cov_enu[1, 1], 0)) if cov_matrix is not None else 0.0
        std_up = math.sqrt(max(cov_enu[2, 2], 0)) if cov_matrix is not None else 0.0
        
        return PositioningResult(
            timestamp=gps_time,
            epoch_time=datetime.utcnow(),
            position_ecef=pos_curr.tolist(),
            clock_bias=x_curr[3],
            clock_bias_seconds=x_curr[3] / self.CLIGHT,
            time_offsets={
                sys: x_curr[idx] / self.CLIGHT
                for sys, idx in SYS_OFFSET_INDICES.items()
                if idx < NX
            },
            num_satellites=len(observations),
            residuals=residuals_final,
            variance=variance_uow,
            std_dev_north=std_north,
            std_dev_east=std_east,
            std_dev_up=std_up,
            std_dev_clock=std_clock,
            gdop=gdop,
            pdop=pdop,
            hdop=hdop,
            vdop=vdop,
            tdop=tdop,
            latitude=math.degrees(lat_rad),
            longitude=math.degrees(lon_rad),
            height=lla[2],
            convergence=convergence,
            solution_status=solution_status,
        )
    
    def _compute_dop(self, position: np.ndarray, observations: List[Dict], cov_matrix: np.ndarray, variance_uow: float) -> Tuple:
        """
        Compute DOP (Dilution of Precision) values.
        
        Returns:
            (GDOP, PDOP, HDOP, VDOP, TDOP)
        """
        if cov_matrix is None:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        
        try:
            # Convert covariance matrix to geometry matrix inverse (unitless Q = Cov / variance_uow)
            if variance_uow > 0:
                Q = cov_matrix / variance_uow
            else:
                Q = cov_matrix * 0.0

            # GDOP = sqrt(trace(Q))
            trace = np.trace(Q)
            gdop = math.sqrt(trace) if trace > 0 else 0.0

            # PDOP = sqrt(Qxx + Qyy + Qzz)
            pdop_var = Q[0, 0] + Q[1, 1] + Q[2, 2]
            pdop = math.sqrt(pdop_var) if pdop_var > 0 else 0.0
            
            # Convert to ENU for HDOP/VDOP
            # ecef2lla returns (lat_rad, lon_rad, height)
            lat, lon, _ = ecef2lla(position)
            
            sl = math.sin(lat)
            cl = math.cos(lat)
            slon = math.sin(lon)
            clon = math.cos(lon)
            
            R = np.array([
                [-slon, clon, 0],
                [-sl*clon, -sl*slon, cl],
                [cl*clon, cl*slon, sl]
            ])
            
            cov_enu = R @ Q[:3, :3] @ R.T

            # HDOP = sqrt(Qee + Qnn)
            hdop_var = cov_enu[1, 1] + cov_enu[0, 0]
            hdop = math.sqrt(hdop_var) if hdop_var > 0 else 0.0

            # VDOP = sqrt(Quu)
            vdop_var = cov_enu[2, 2]
            vdop = math.sqrt(vdop_var) if vdop_var > 0 else 0.0

            # TDOP = sqrt(Qtt)
            tdop_var = Q[3, 3]
            tdop = math.sqrt(tdop_var) if tdop_var > 0 else 0.0
            
            return gdop, pdop, hdop, vdop, tdop
        except Exception as e:
            self.logger.warning(f"DOP computation failed: {str(e)}")
            return 0.0, 0.0, 0.0, 0.0, 0.0
