"""
Geometry utilities for GNSS coordinate transformations and orbit calculations.

Includes:
  - Coordinate system conversions (ECEF, LLA, ENU)
  - Azimuth/Elevation calculations
  - Tropospheric delay modeling (Saastamoinen)
  - Frequency lookups for GNSS signals
"""
import numpy as np
import math

# WGS84 Constants
CLIGHT = 299792458.0       # Speed of light

def get_freq(sig_id: str, sat_key: str, fcn: int = 0):
    """
    Get frequency and wavelength based on Signal ID and Satellite Key.
    
    Args:
        sig_id: Signal ID (e.g., "1C", "2W")
        sat_key: Satellite Key (e.g., "G14", "R01")
        fcn: Frequency Channel Number (Required for GLONASS, -7 to +6)
    
    Returns:
        (frequency_Hz, wavelength_m)
    """
    # 1. Define base frequencies
    # GPS / QZSS
    gps_freq = {"1": 1575.42e6, "2": 1227.60e6, "5": 1176.45e6, "6": 1278.75e6}
    # Galileo
    gal_freq = {"1": 1575.42e6, "5": 1176.45e6, "7": 1207.14e6, "8": 1191.795e6, "6": 1278.75e6}
    # BDS
    bds_freq = {"1": 1575.42e6, "2": 1561.098e6, "5": 1176.45e6, "7": 1207.140e6, "8": 1191.795e6, "6": 1268.52e6}
    # SBAS
    sbas_freq = {"1": 1575.42e6, "5": 1176.45e6}
    # IRNSS / NavIC
    irnss_freq = {"1": 1575.42e6, "5": 1176.45e6, "9": 2492.028e6}
    
    sys = sat_key[0]
    band = sig_id[0]
    freq = None

    if sys in ["G", "J"]:
        freq = gps_freq.get(band)
    elif sys == "E":
        freq = gal_freq.get(band)
    elif sys == "C":
        freq = bds_freq.get(band)
    elif sys == "S":
        freq = sbas_freq.get(band)
    elif sys == "I":
        freq = irnss_freq.get(band)
    elif sys == "R":
        # GLONASS FDMA/CDMA
        # G1 = 1602 + 0.5625 * k
        # G2 = 1246 + 0.4375 * k
        # G3 = 1202.025 MHz (no FCN spacing)
        if band == "1":
            freq = 1602.0e6 + 0.5625e6 * fcn
        elif band == "2":
            freq = 1246.0e6 + 0.4375e6 * fcn
        elif band == "3":
            freq = 1202.025e6

    if freq is None:
        return 0.0, 0.0

    return freq, CLIGHT / freq

# -----------------------------------------------------
# Coordinate Transformations
# -----------------------------------------------------

def ecef2lla(pos):
    """
    Convert ECEF XYZ to Lat, Lon, Alt (WGS84).
    
    Args:
        pos: [x, y, z] in meters (ECEF)
    
    Returns:
        Tuple of (latitude_rad, longitude_rad, altitude_m)
    """
    x, y, z = pos[0], pos[1], pos[2]
    a = 6378137.0  # WGS84 semi-major axis
    e2 = 6.69437999014e-3  # WGS84 eccentricity squared
    
    b = a * math.sqrt(1 - e2)
    ep = math.sqrt((a**2 - b**2) / b**2)
    p = math.sqrt(x**2 + y**2)
    
    if p == 0:
        # Pole case
        if z >= 0:
            return math.pi/2, 0.0, z - b
        else:
            return -math.pi/2, 0.0, -z - b

    th = math.atan2(a*z, b*p)
    lon = math.atan2(y, x)
    lat = math.atan2(z + ep*ep*b*(math.sin(th)**3),
                     p - e2*a*(math.cos(th)**3))
    
    # Altitude calculation using more stable method
    N = a / math.sqrt(1 - e2 * math.sin(lat)**2)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    
    # Use sin-based formula when latitude is steep, cos-based when flat
    if abs(sin_lat) > abs(cos_lat):
        alt = z / sin_lat - N * (1 - e2)
    else:
        if cos_lat != 0:
            alt = p / cos_lat - N
        else:
            # Fallback if exactly at pole
            alt = abs(z) - b
    
    return lat, lon, alt

def rot_ecef2enu(lat, lon):
    """
    Generate Rotation Matrix from ECEF to ENU.
    """
    sl = math.sin(lat)
    cl = math.cos(lat)
    slon = math.sin(lon)
    clon = math.cos(lon)

    R = np.array([
        [-slon,        clon,        0],
        [-sl*clon, -sl*slon,    cl],
        [ cl*clon,  cl*slon,    sl]
    ])
    return R

def ecef2enu(sat_pos, rec_pos):
    """
    Convert satellite position to ENU coordinates relative to receiver.
    """
    # Difference vector in ECEF
    diff = np.array(sat_pos) - np.array(rec_pos)
    
    # Get Receiver Geodetic Lat/Lon
    lat, lon, _ = ecef2lla(rec_pos)
    
    # Get Rotation Matrix
    R = rot_ecef2enu(lat, lon)
    
    # Rotate
    enu = R @ diff
    return enu

def calculate_az_el(sat_ecef, rec_ecef):
    """
    Calculate Azimuth and Elevation. 
    
    Args: sat_ecef: Satellite position [x, y, z] (meters) 
    rec_ecef: Receiver position [x, y, z] (meters) 
    Returns: tuple: (Azimuth [deg], Elevation [deg]) or (0, 0) if error 
    """

    if sat_ecef is None or rec_ecef is None:
        return 0.0, 0.0

    if np.all(np.array(rec_ecef) == 0):
        return 0.0, 0.0

    # ENU vector: [E, N, U]
    e, n, u = ecef2enu(sat_ecef, rec_ecef)

    # ---- Azimuth ----
    az = math.degrees(math.atan2(e, n))  # atan2(E, N)
    if az < 0:
        az += 360.0

    # ---- Elevation ----
    rnorm = math.sqrt(e*e + n*n + u*u)
    el = math.degrees(math.asin(u / rnorm))

    return az, el


def tropsphere_model(pos, azel, humi=0.7):
    """
    Saastamoinen troposphere model (standard atmosphere).
    
    Computes tropospheric delay using the Saastamoinen model with standard
    atmosphere assumptions.

    Parameters
    ----------
    pos : tuple
        Receiver position (lat_rad, lon_rad, height_m)
        - lat_rad, lon_rad in radians
        - height_m in meters
    azel : tuple
        (azimuth_rad, elevation_rad)
        - azimuth in radians (0~2π)
        - elevation in radians (-π/2~π/2)
    humi : float
        Relative humidity (0~1, default 0.7)

    Returns
    -------
    delay : float
        Tropospheric delay in meters
    """
    lat, lon, h = pos
    az, el = azel

    # Validity check
    if h < -100.0 or h > 1e4 or el <= 0:
        return 0.0, 0.0

    # -------------------------
    # Standard atmosphere
    # -------------------------
    hgt = max(h, 0.0)

    pres = 1013.25 * (1.0 - 2.2557e-5 * hgt) ** 5.2568
    temp = 15.0 - 6.5e-3 * hgt + 273.16
    e = 6.108 * humi * math.exp((17.15 * temp - 4684.0) / (temp - 38.45))

    # -------------------------
    # Saastamoinen model
    # -------------------------
    z = math.pi / 2.0 - el  # zenith angle

    trph = (
        0.0022768 * pres
        / (1.0 - 0.00266 * math.cos(2.0 * lat) - 0.00028 * hgt / 1e3)
        / math.cos(z)
    )

    trpw = (
        0.002277
        * (1255.0 / temp + 0.05)
        * e
        / math.cos(z)
    )

    return trph + trpw, (0.3/(math.sin(el) + 0.1))**2  # delay in meters, variance estimate

def ionospheric_model(pos, azel, t, ion):
    # 常数定义
    CLIGHT = 299792458.0
    PI = 3.1415926535897932
    
    # 2004/1/1 默认参数 (如果输入参数为空时使用)
    ION_DEFAULT = [
        0.1118E-07, -0.7451E-08, -0.5961E-07,  0.1192E-06,
        0.1167E+06, -0.2294E+06, -0.1311E+06,  0.1049E+07
    ]

    # 1. 基础检查
    # 如果高度低于-1000米或卫星仰角小于等于0，不计算延迟
    if pos[2] < -1E3 or azel[1] <= 0:
        return 0.0
    
    # 如果参数全为0，使用默认参数
    if all(abs(x) < 1e-20 for x in ion):
        ion = ION_DEFAULT

    # 2. 地心角 (Earth centered angle) 单位: semi-circle (半周)
    # azel[1]/PI 是将弧度转为半周
    psi = 0.0137 / (azel[1] / PI + 0.11) - 0.022

    # 3. 穿刺点(IPP)的纬度 (Subionospheric latitude)
    phi = pos[0] / PI + psi * math.cos(azel[0])
    if phi > 0.416:
        phi = 0.416
    elif phi < -0.416:
        phi = -0.416

    # 4. 穿刺点(IPP)的经度 (Subionospheric longitude)
    lam = pos[1] / PI + psi * math.sin(azel[0]) / math.cos(phi * PI)

    # 5. 地磁纬度 (Geomagnetic latitude)
    phi += 0.064 * math.cos((lam - 1.617) * PI)

    # 6. 当地时间 (Local time)
    # t_gps_sec 是当前 GPS 周内秒
    tt = 43200.0 * lam + t
    tt -= math.floor(tt / 86400.0) * 86400.0  # 限制在 [0, 86400)

    # 7. 倾斜因子 (Slant factor)
    f = 1.0 + 16.0 * math.pow(0.53 - azel[1] / PI, 3.0)

    # 8. 计算振幅 (amp) 和 周期 (per)
    amp = ion[0] + phi * (ion[1] + phi * (ion[2] + phi * ion[3]))
    per = ion[4] + phi * (ion[5] + phi * (ion[6] + phi * ion[7]))
    
    amp = max(amp, 0.0)
    per = max(per, 72000.0)

    # 9. 计算相位 x
    x = 2.0 * PI * (tt - 50400.0) / per

    # 10. 计算延迟 (米)
    # 如果在白天 (|x| < 1.57 即 pi/2)，使用余弦模型
    # 如果在黑夜，固定延迟为 5ns (5E-9)
    if abs(x) < 1.57:
        # 使用泰勒展开近似 cos(x)
        cos_x = 1.0 + x * x * (-0.5 + x * x / 24.0)
        ion_delay_sec = 5E-9 + amp * cos_x
    else:
        ion_delay_sec = 5E-9

    return CLIGHT * f * ion_delay_sec
