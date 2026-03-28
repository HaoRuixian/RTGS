"""
Configuration module Monitor.
"""

# NTRIP Caster Settings
#================================ EPH =====================================

# --------- BRDC -----------
EPH_HOST = "ntrip.data.gnss.ga.gov.au"
EPH_PORT = 2101
EPH_MOUNTPOINT = "BCEP00BKG0"
EPH_USER = "hrx"
EPH_PASSWORD= "Hao20030801@"


# ================================= MSM =====================================
# --------- BRST ------------
NTRIP_HOST = "8.140.235.117"
NTRIP_PORT = 2101
MOUNTPOINT = "NBFH"
USER = "adminHRX"
PASSWORD = "hao20030801"

# Receiver Approximate Position (ECEF X, Y, Z in meters)
# Can be updated dynamically if RTCM 1005/1006 is received.
APPROX_REC_POS = [-2890959.0587, 4725854.8085, 3150024.8212]  # Example coordinates

# GNSS System Filters (G=GPS, R=GLONASS, E=Galileo, C=Beidou)
TARGET_SYSTEMS = ['G','R','E','C']