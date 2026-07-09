"""GNSS 观测、卫星状态和修正参数的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

SignalMap = dict[str, "SignalData"]
SatelliteMap = dict[str, "SatelliteState"]


@dataclass
class SignalData:
    """
    单个频点/信号的观测值。

    Args:
        signal_id: 信号标识，例如 ``1C``、``2W``。
        snr: 信噪比，单位 dB-Hz。
        phase: 载波相位，单位 cycle。
        pseudorange: 伪距，单位 m。
        lock_time: 锁定时间指示值。
        half_cycle: 半周模糊度标记。
        doppler: 多普勒观测值。
    """

    signal_id: str
    snr: float
    phase: float
    pseudorange: float
    lock_time: int
    half_cycle: int
    doppler: float | None


@dataclass
class SatelliteState:
    """单颗卫星在一个历元内的状态和信号观测。"""

    sys_id: str
    prn: int
    azimuth: float | None = None
    elevation: float | None = None
    sat_pos_ecef: list[float] | None = None
    signals: SignalMap = field(default_factory=dict)


@dataclass
class IonosphericCorrection:
    """电离层修正参数，主要表示 STEC。"""

    satellite_id: str
    stec: float
    stec_rate: float | None = None
    signal_id: str | None = None
    quality_indicator: int = 0


@dataclass
class TroposphericCorrection:
    """对流层修正参数，包含干/湿延迟及其变化率。"""

    ztd_hydro: float | None = None
    ztd_wet: float | None = None
    ztd_rate_hydro: float | None = None
    ztd_rate_wet: float | None = None
    quality_indicator: int = 0


@dataclass
class SatelliteBiasCorrection:
    """卫星码偏差和相位偏差修正。"""

    satellite_id: str
    code_biases: dict[str, float] = field(default_factory=dict)
    phase_biases: dict[str, float] = field(default_factory=dict)
    yaw_angle: float | None = None
    yaw_rate: float | None = None


@dataclass
class SatelliteClockCorrection:
    """卫星钟差和轨道改正参数。"""

    satellite_id: str
    delta_clock: float = 0.0
    delta_clock_rate: float = 0.0
    delta_clock_accel: float = 0.0
    delta_radial: float = 0.0
    delta_radial_rate: float = 0.0
    delta_along_track: float = 0.0
    delta_along_track_rate: float = 0.0
    delta_cross_track: float = 0.0
    delta_cross_track_rate: float = 0.0


@dataclass
class BroadcastEphemerisCorrections:
    """
    广播星历中携带的物理修正参数。

    这些字段直接对应 RTCM/RINEX 专业含义，因此保持原始缩写命名。
    """

    satellite_id: str
    TGD: float | None = None
    TGD1: float | None = None
    TGD2: float | None = None
    ISC_L1CA: float | None = None
    ISC_L1C: float | None = None
    ISC_L5I: float | None = None
    ISC_L5Q: float | None = None
    BGD_E1E5a: float | None = None
    BGD_E1E5b: float | None = None
    SISA: int | None = None
    URAI: int | None = None
    SatHealth: int | None = None
    FitInterval: int | None = None
    AODE: int | None = None
    AODC: int | None = None


@dataclass
class EpochObservation:
    """单个历元内的全部观测和修正数据。"""

    gps_time: float
    satellites: SatelliteMap = field(default_factory=dict)
    utc_datetime: datetime | None = None
    ionospheric_corrections: dict[str, IonosphericCorrection] = field(default_factory=dict)
    tropospheric_correction: TroposphericCorrection | None = None
    satellite_bias_corrections: dict[str, SatelliteBiasCorrection] = field(default_factory=dict)
    satellite_clock_corrections: dict[str, SatelliteClockCorrection] = field(default_factory=dict)
    broadcast_eph_corrections: dict[str, BroadcastEphemerisCorrections] = field(default_factory=dict)
    gps_glonass_time_bias: float | None = None
    gps_galileo_time_bias: float | None = None
    gps_bds_time_bias: float | None = None
