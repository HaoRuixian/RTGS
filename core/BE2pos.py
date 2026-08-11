"""Broadcast-ephemeris orbit propagation helpers used by RTCM and RINEX positioning code."""

import numpy as np
import math
from core.global_config import get_global_config
# 常量定义
class Const:
    CLIGHT = 299792458.0      # 光速 [m/s]
    
    # GPS/Galileo/BeiDou (WGS84 / CGCS2000 近似)
    GM_WGS84 = 3.986005e14    # [m^3/s^2]
    WE_WGS84 = 7.2921151467e-5 # [rad/s]
    
    # GLONASS (PZ-90)
    GM_PZ90  = 3.9860044e14   # [m^3/s^2]
    WE_PZ90  = 7.292115e-5    # [rad/s]
    J2_PZ90  = 1082625.75e-9
    A_PZ90   = 6378136.0      # [m]

def brdc2state(eph_data, sys_type, t_obs_gpst):

    try:
        if sys_type == 'GLO':
            result = SatPos_brdc_glo(t_obs_gpst, eph_data)
        elif sys_type == 'SBS':
            result = SatPos_brdc_sbas(t_obs_gpst, eph_data)
        elif sys_type == 'C':
            result = SatPos_brdc_bds(t_obs_gpst, eph_data)
        else:
            result = SatPos_brdc(t_obs_gpst, eph_data)
        
        if result is None:
            return None
        
        return result
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def brdc2pos(eph_data, sys_type, t_obs_gpst):
    state = brdc2state(eph_data, sys_type, t_obs_gpst)
    if state is None:
        return None
    return state[0]

def check_t(t):
    """
    Repairs over- and underflow of GPS time.
    """
    half_week = 302400.0

    if t > half_week:
        return t - 2 * half_week
    if t < -half_week:
        return t + 2 * half_week
    return t


def SatPos_brdc(t, eph):
    """
    Compute satellite position and velocity from broadcast ephemeris

    Args:
        t : GPS time sow(s)

    Returns:
        sat_p: ECEF satellite position [m]
        sat_v: ECEF satellite velocity [m/s]
    """

    # ----- Unpack ephemeris -----
    M0        = eph['M0']
    roota     = eph['sqrtA']
    deltan    = eph['Delta_n']
    ecc       = eph['Eccentricity']
    omega     = eph['omega']
    cuc       = eph['Cuc']
    cus       = eph['Cus']
    crc       = eph['Crc']
    crs       = eph['Crs']
    i0        = eph['i0']
    idot      = eph['IDOT']
    cic       = eph['Cic']
    cis       = eph['Cis']
    Omega0    = eph['OMEGA0']
    Omegadot  = eph['OMEGA_DOT']
    toe       = eph['Toe']


    # ----- Start calculations -----
    A  = roota * roota
    tk = check_t(t - toe)

    n0 = math.sqrt(Const.GM_WGS84 / A**3)
    n  = n0 + deltan

    # Mean anomaly
    M = M0 + n * tk
    M = (M + 2*math.pi) % (2*math.pi)

    # ----- Eccentric Anomaly -----
    E = M
    for _ in range(10):
        E_old = E
        E = M + ecc * math.sin(E)
        dE = (E - E_old) % (2*math.pi)
        if abs(dE) < 1e-12:
            break

    E = (E + 2*math.pi) % (2*math.pi)

    # True anomaly
    v = math.atan2(math.sqrt(1 - ecc**2) * math.sin(E), math.cos(E) - ecc)

    # Corrected argument of latitude
    u0 = (v + omega) % (2*math.pi)
    u = u0 + cuc * math.cos(2*u0) + cus * math.sin(2*u0)

    # Corrected radius and inclination
    r = A*(1 - ecc * math.cos(E)) + crc * math.cos(2*u0) + crs * math.sin(2*u0)
    i = i0 + idot * tk + cic * math.cos(2*u0) + cis * math.sin(2*u0)

    # Corrected RAAN
    Omega = Omega0 + (Omegadot - Const.WE_WGS84) * tk - Const.WE_WGS84 * toe
    Omega = (Omega + 2*math.pi) % (2*math.pi)

    # ----- Position -----
    x1 = math.cos(u) * r
    y1 = math.sin(u) * r

    sat_p = np.zeros(3)

    sat_p[0] = x1 * math.cos(Omega) - y1 * math.cos(i) * math.sin(Omega)
    sat_p[1] = x1 * math.sin(Omega) + y1 * math.cos(i) * math.cos(Omega)
    sat_p[2] = y1 * math.sin(i)

    # ----- Velocity calculations -----
    e_help = 1.0 / (1 - ecc * math.cos(E))

    dot_v = (
        math.sqrt((1 + ecc) / (1 - ecc)) /
        (math.cos(E/2)**2) /
        (1 + math.tan(v/2)**2) *
        e_help * n
    )

    dot_u = dot_v + (-cuc * math.sin(2*u0) + cus * math.cos(2*u0)) * 2 * dot_v
    dot_om = Omegadot - Const.WE_WGS84
    dot_i  = idot + (-cic * math.sin(2*u0) + cis * math.cos(2*u0)) * 2 * dot_v
    dot_r  = A * ecc * math.sin(E) * e_help * n + (-crc * math.sin(2*u0) + crs * math.cos(2*u0)) * 2 * dot_v

    dot_x1 = dot_r * math.cos(u) - r * math.sin(u) * dot_u
    dot_y1 = dot_r * math.sin(u) + r * math.cos(u) * dot_u

    sat_v = np.zeros(3)

    sat_v[0] = (
        math.cos(Omega)*dot_x1
        - math.cos(i)*math.sin(Omega)*dot_y1
        - x1*math.sin(Omega)*dot_om
        - y1*math.cos(i)*math.cos(Omega)*dot_om
        + y1*math.sin(i)*math.sin(Omega)*dot_i
    )

    sat_v[1] = (
        math.sin(Omega)*dot_x1
        + math.cos(i)*math.cos(Omega)*dot_y1
        + x1*math.cos(Omega)*dot_om
        - y1*math.cos(i)*math.sin(Omega)*dot_om
        - y1*math.sin(i)*math.cos(Omega)*dot_i
    )

    sat_v[2] = math.sin(i) * dot_y1 + y1 * math.cos(i) * dot_i

    return sat_p, sat_v


def SatPos_brdc_bds(t, eph):
    """
    Compute BeiDou satellite position and velocity from broadcast ephemeris.

    This follows BNC's t_ephBDS::position implementation: BeiDou uses its own
    gravitational constant/earth rotation rate, and GEO spacecraft use the
    additional 5 degree X-rotation plus earth-fixed Z-rotation.
    """

    try:
        M0        = eph['M0']
        roota     = eph['sqrtA']
        deltan    = eph['Delta_n']
        ecc       = eph['Eccentricity']
        omega     = eph['omega']
        cuc       = eph['Cuc']
        cus       = eph['Cus']
        crc       = eph['Crc']
        crs       = eph['Crs']
        i0        = eph['i0']
        idot      = eph['IDOT']
        cic       = eph['Cic']
        cis       = eph['Cis']
        Omega0    = eph['OMEGA0']
        Omegadot  = eph['OMEGA_DOT']
        toe       = eph['Toe']
    except KeyError:
        return None

    gm_bds = 398.6004418e12
    omega_bds = 7292115.0000e-11

    A = roota * roota
    if A <= 0.0:
        return None

    tk = check_t(t - toe)
    n0 = math.sqrt(gm_bds / A**3)
    n = n0 + deltan
    M = M0 + n * tk

    E = M
    for _ in range(100):
        E_old = E
        E = M + ecc * math.sin(E)
        if abs(E - E_old) * A <= 0.001:
            break
    else:
        return None

    v = math.atan2(math.sqrt(1.0 - ecc * ecc) * math.sin(E), math.cos(E) - ecc)
    u0 = v + omega
    sin2u0 = math.sin(2.0 * u0)
    cos2u0 = math.cos(2.0 * u0)
    r = A * (1.0 - ecc * math.cos(E)) + crc * cos2u0 + crs * sin2u0
    i = i0 + idot * tk + cic * cos2u0 + cis * sin2u0
    u = u0 + cuc * cos2u0 + cus * sin2u0
    xp = r * math.cos(u)
    yp = r * math.sin(u)

    tanv2 = math.tan(v / 2.0)
    dEdM = 1.0 / (1.0 - ecc * math.cos(E))
    dotv = (
        math.sqrt((1.0 + ecc) / (1.0 - ecc))
        / (math.cos(E / 2.0) ** 2)
        / (1.0 + tanv2 * tanv2)
        * dEdM
        * n
    )
    dotu = dotv + (-cuc * sin2u0 + cus * cos2u0) * 2.0 * dotv
    doti = idot + (-cic * sin2u0 + cis * cos2u0) * 2.0 * dotv
    dotr = A * ecc * math.sin(E) * dEdM * n + (-crc * sin2u0 + crs * cos2u0) * 2.0 * dotv
    dotx = dotr * math.cos(u) - r * math.sin(u) * dotu
    doty = dotr * math.sin(u) + r * math.cos(u) * dotu

    toesec = float(toe) - 14.0
    i_max_geo = math.radians(10.0)

    if i0 > i_max_geo:
        OM = Omega0 + (Omegadot - omega_bds) * tk - omega_bds * toesec
        sinom = math.sin(OM)
        cosom = math.cos(OM)
        sini = math.sin(i)
        cosi = math.cos(i)

        sat_p = np.array(
            [
                xp * cosom - yp * cosi * sinom,
                xp * sinom + yp * cosi * cosom,
                yp * sini,
            ],
            dtype=float,
        )

        dotom = Omegadot - Const.WE_WGS84
        sat_v = np.array(
            [
                cosom * dotx - cosi * sinom * doty - xp * sinom * dotom
                - yp * cosi * cosom * dotom + yp * sini * sinom * doti,
                sinom * dotx + cosi * cosom * doty + xp * cosom * dotom
                - yp * cosi * sinom * dotom - yp * sini * cosom * doti,
                sini * doty + yp * cosi * doti,
            ],
            dtype=float,
        )
        return sat_p, sat_v

    OM = Omega0 + Omegadot * tk - omega_bds * toesec
    ll = omega_bds * tk
    sinom = math.sin(OM)
    cosom = math.cos(OM)
    sini = math.sin(i)
    cosi = math.cos(i)

    x = xp * cosom - yp * cosi * sinom
    y = xp * sinom + yp * cosi * cosom
    z = yp * sini
    x1 = np.array([x, y, z], dtype=float)

    rx_angle = math.radians(-5.0)
    crx = math.cos(rx_angle)
    srx = math.sin(rx_angle)
    rx = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, crx, srx],
            [0.0, -srx, crx],
        ],
        dtype=float,
    )
    cll = math.cos(ll)
    sll = math.sin(ll)
    rz = np.array(
        [
            [cll, sll, 0.0],
            [-sll, cll, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=float,
    )
    sat_p = rz @ rx @ x1

    dotom = Omegadot
    vx = (
        cosom * dotx - cosi * sinom * doty - xp * sinom * dotom
        - yp * cosi * cosom * dotom + yp * sini * sinom * doti
    )
    vy = (
        sinom * dotx + cosi * cosom * doty + xp * cosom * dotom
        - yp * cosi * sinom * dotom - yp * sini * cosom * doti
    )
    vz = sini * doty + yp * cosi * doti
    v1 = np.array([vx, vy, vz], dtype=float)

    rdot_z = omega_bds * np.array(
        [
            [-sll, cll, 0.0],
            [-cll, -sll, 0.0],
            [0.0, 0.0, 0.0],
        ],
        dtype=float,
    )
    sat_v = rz @ rx @ v1 + rdot_z @ rx @ x1
    return sat_p, sat_v


def SatPos_brdc_glo(t_sow, eph):
    """
    计算 GLONASS 卫星位置 (RK4 积分)
    """
  
    try:
        pos = np.array([eph['X'], eph['Y'], eph['Z']]) * 1000.0
        vel = np.array([eph['Vx'], eph['Vy'], eph['Vz']]) * 1000.0
        acc = np.array([eph['Ax'], eph['Ay'], eph['Az']]) * 1000.0
        
        toe = eph['tb']  # Time of ephemeris (seconds within week)
        
        # 执行 Runge-Kutta 4 积分
        return runge_kutta_4(toe, pos, vel, acc, t_sow)
    except (KeyError, TypeError, ValueError):
        return None


def SatPos_brdc_sbas(t_sow, eph):
    """
    Compute SBAS GEO position from RTKLIB-style seph parameters.
    """

    try:
        pos = np.array(eph['pos'], dtype=float)
        vel = np.array(eph['vel'], dtype=float)
        acc = np.array(eph['acc'], dtype=float)
        t0 = float(eph.get('t0', eph.get('Toe', 0.0)))
    except (KeyError, TypeError, ValueError):
        return None

    dt = check_t(t_sow - t0)
    sat_p = pos + vel * dt + 0.5 * acc * dt * dt
    sat_v = vel + acc * dt
    return sat_p, sat_v

def runge_kutta_4(toe, pos, vel, acc, t_target):
    """
    RK4 轨道积分
    """
    t = toe
    h = 30.0 # 步长
    
    # 确定方向
    step_sign = 1 if (t_target - t) >= 0 else -1
    h = h * step_sign
    
    current_pos = pos.copy()
    current_vel = vel.copy()
    
    # 循环积分直到达到目标时间
    while True:
        # 检查是否是最后一步
        time_diff = t_target - t
        if (h > 0 and time_diff <= h) or (h < 0 and time_diff >= h):
            h = time_diff
            if abs(h) < 1e-9: # 极小时间差直接结束
                break
            is_last = True
        else:
            is_last = False
            
        # RK4 步骤
        # k1
        v1 = current_vel
        a1 = accel_pz90(current_pos, v1, acc)
        
        # k2
        x2 = current_pos + (h/2) * v1
        v2 = current_vel + (h/2) * a1
        a2 = accel_pz90(x2, v2, acc)
        
        # k3
        x3 = current_pos + (h/2) * v2
        v3 = current_vel + (h/2) * a2
        a3 = accel_pz90(x3, v3, acc)
        
        # k4
        x4 = current_pos + h * v3
        v4 = current_vel + h * a3
        a4 = accel_pz90(x4, v4, acc)
        
        # 更新状态
        current_pos = current_pos + (h/6) * (v1 + 2*v2 + 2*v3 + v4)
        current_vel = current_vel + (h/6) * (a1 + 2*a2 + 2*a3 + a4)
        
        t += h
        
        if is_last:
            break
            
    return current_pos, current_vel

def accel_pz90(r_vec, v_vec, acc_sl):
    """
    计算 GLONASS 卫星在 PZ-90 坐标系下的加速度
    """
    r_sq = np.sum(r_vec**2)
    r = math.sqrt(r_sq)
    
    x, y, z = r_vec
    vx, vy, vz = v_vec
    
    GM = Const.GM_PZ90
    C20 = -Const.J2_PZ90 # 注意 MATLAB 代码中 PZ90_C20 = -PZ90_J20
    a_earth = Const.A_PZ90
    omega = Const.WE_PZ90
    
    # 公共项
    term1 = -GM / r**3
    term2 = 1.5 * C20 * GM * (a_earth**2) / (r**5)
    term3 = 5.0 * (z**2) / (r**2)
    
    # 运动方程 (包含 J2 摄动和科里奥利力/离心力)
    ax = term1 * x + term2 * x * (1 - term3) + (omega**2) * x + 2 * omega * vy + acc_sl[0]
    ay = term1 * y + term2 * y * (1 - term3) + (omega**2) * y - 2 * omega * vx + acc_sl[1]
    az = term1 * z + term2 * z * (3 - term3)                                   + acc_sl[2]
    
    return np.array([ax, ay, az])
