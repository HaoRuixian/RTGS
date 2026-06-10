"""
Local compatibility patches for third-party pyrtcm limitations.

The installed pyrtcm build exposes the mainstream MSM tables but omits some
signals that are present in RTKLIB and in RTCM 3.04-era practice, such as:
  - GLONASS G3: 3I/3Q/3X
  - QZSS extended MSM signals
  - NavIC/IRNSS extended MSM signals

We patch these lookup tables at runtime before any RTCMReader instances are
created so downstream parsing can stay unchanged.
"""

GLONASS_EXTRA_SIG_MAP = {
    14: ("G3", "3I"),
    15: ("G3", "3Q"),
    16: ("G3", "3X"),
}

QZSS_EXTRA_SIG_MAP = {
    5: ("L1", "1E"),
    6: ("L1", "1Z"),
    7: ("L1", "1B"),
    12: ("LEX", "6E"),
    13: ("LEX", "6Z"),
    25: ("L5", "5D"),
    26: ("L5", "5P"),
    27: ("L5", "5Z"),
}

IRNSS_EXTRA_SIG_MAP = {
    2: ("L1", "1D"),
    3: ("L1", "1P"),
    4: ("L1", "1X"),
    8: ("S", "9A"),
    9: ("S", "9B"),
    10: ("S", "9C"),
    11: ("S", "9X"),
    23: ("L5", "5B"),
    24: ("L5", "5C"),
    25: ("L5", "5X"),
}


def _patch_prnsigmap_entry(rtcmtables, identity_prefix, extra_signal_map):
    entry = rtcmtables.PRNSIGMAP.get(identity_prefix)
    if not entry:
        return

    prn_map, sig_map = entry
    sig_map.update(extra_signal_map)
    rtcmtables.PRNSIGMAP[identity_prefix] = (prn_map, sig_map)


def patch_pyrtcm_glonass_g3():
    """
    Extend pyrtcm MSM signal tables for GLONASS/QZSS/NavIC.

    The function name is kept for backward compatibility with existing imports.
    The patch is idempotent and safe to call multiple times.
    """
    try:
        from pyrtcm import rtcmtables
    except Exception:
        return False

    rtcmtables.GLONASS_SIG_MAP.update(GLONASS_EXTRA_SIG_MAP)
    rtcmtables.QZSS_SIG_MAP.update(QZSS_EXTRA_SIG_MAP)
    rtcmtables.IRNSS_SIG_MAP.update(IRNSS_EXTRA_SIG_MAP)

    _patch_prnsigmap_entry(rtcmtables, "108", GLONASS_EXTRA_SIG_MAP)
    _patch_prnsigmap_entry(rtcmtables, "111", QZSS_EXTRA_SIG_MAP)
    _patch_prnsigmap_entry(rtcmtables, "113", IRNSS_EXTRA_SIG_MAP)

    return True
