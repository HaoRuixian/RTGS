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
"""
# --------- GR01 -----------
NTRIP_HOST = "8.140.235.117"
NTRIP_PORT = 2101
MOUNTPOINT = "GR01"
USER = "HRX"
PASSWORD = "hao20030801"

# Receiver Approximate Position (ECEF X, Y, Z in meters)
# Can be updated dynamically if RTCM 1005/1006 is received.
APPROX_REC_POS = [ 0, 0, 0 ]  # Example coordinates

# GNSS System Filters (G=GPS, R=GLONASS, E=Galileo, C=Beidou)
TARGET_SYSTEMS = ['G','R','E','C']
"""
# --------- BRST ------------
NTRIP_HOST = "ntrip.data.gnss.ga.gov.au"
NTRIP_PORT = 2101
MOUNTPOINT = "BRST00FRA0"
USER = "hrx"
PASSWORD = "Hao20030801@"

# Receiver Approximate Position (ECEF X, Y, Z in meters)
# Can be updated dynamically if RTCM 1005/1006 is received.
APPROX_REC_POS = [ 10, 10, 10 ]  # Example coordinates

# GNSS System Filters (G=GPS, R=GLONASS, E=Galileo, C=Beidou)
TARGET_SYSTEMS = ['G','R','E','C']


"""
# --------- SC02 ------------
NTRIP_HOST = "ntrip.earthscope.org"
NTRIP_PORT = 2101
MOUNTPOINT = "SC02_RTCM3P3"
USER = "keen_bell"
PASSWORD = "NpwPoUk73wbRE7DS"

# Receiver Approximate Position (ECEF X, Y, Z in meters)
# Can be updated dynamically if RTCM 1005/1006 is received.
APPROX_REC_POS = [ 0, 0, 0 ]  # Example coordinates

# GNSS System Filters (G=GPS, R=GLONASS, E=Galileo, C=Beidou)
TARGET_SYSTEMS = ['G',
                  'R',
                  'E',
                  'C']
"""