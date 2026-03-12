GNSS RTCM Epoch Time Handling
=============================

This document summarizes how epoch/time fields from RTCM MSM/DF fields are interpreted
and converted to UTC within the RTGS codebase. It reflects decisions implemented in
`core/rtcm_handler.py` and uses `core/gnss_time.GNSSTime` for GPS↔UTC conversion.

DF fields and semantics
-----------------------
- DF004 GPS Epoch Time (TOW)
  - Units: milliseconds (0..604,799,999)
  - Range: milliseconds since the start of the GPS week (Sunday 00:00:00 UTC/GPS)
  - Conversion: treat as GPS seconds-of-week (divide by 1000).

- DF427 BeiDou Epoch Time (TOW)
  - Units: milliseconds (0..604,799,999)
  - Measured from the start of the BeiDou week (BDT)
  - Note: The BeiDou TOW value is typically 14 seconds less than the GPS TOW for the same epoch.
  - Conversion: convert to seconds, add +14.0 s to align to GPS seconds-of-week, then map to current GPS week.

- DF248 Galileo Epoch Time (TOW)
  - Units: milliseconds (0..604,799,999)
  - Measured from the start of the Galileo week (GST)
  - Conversion: treat as seconds-of-week and align to current GPS week.

- DF034 GLONASS Epoch Time (tk)
  - Units: milliseconds (0..86,400,999)
  - Defined as UTC(SU) + 3.0 hours in the GLONASS ICD (i.e., time-of-day with a +3h offset)
  - Conversion: divide by 1000 to seconds-of-day, subtract 3 hours to convert to UTC seconds-of-day,
    then add current GPS day-of-week * 86400 to form seconds-of-week (mapped to current GPS week).

Implementation notes (current code)
-----------------------------------
- The handler assumes the epoch belongs to the current GPS week (real-time streams).
  - For GPS/BDS/GAL: we map the system TOW to `gps_seconds` within [0, 604800) and use
    `GNSSTime.current_gps_week()` as `gps_week`.
  - For BDS specifically, we add +14 seconds to the BDT TOW before alignment.
  - For GLONASS, DF034 is treated as milliseconds-of-day; the code uses `GNSSTime.gps_day_of_week()`
    to determine which day in the current GPS week to assign the observation to.

- After computing `gps_week` and `gps_seconds`, we call
  `GNSSTime.gps_to_utc_datetime(gps_week, gps_seconds)` to obtain a timezone-aware UTC datetime.

Caveats and improvements
------------------------
- Week rollovers: the current logic assumes observations are near "now" and uses the current GPS week.
  This is suitable for live real-time streams. For recorded logs spanning week boundaries or
  delayed streams, further logic is needed to detect and adjust the GPS week (e.g., compare
  computed `utc_datetime` to current time and adjust week +/-1 if discrepancy is large).

- Leap seconds and system offsets: `GNSSTime.LEAP_SECONDS` is a static constant (18s). For long-term
  accuracy update this from an authoritative source for leap-second changes.

- BeiDou week alignment: ephemeris parsing aligns BDS week to GPS by adding a constant offset (1356 weeks).
  That offset is used for ephemeris; for observations we currently align by using current GPS week and
  applying the +14 s TOW correction. If precise week numbers for BDS observations are required, the
  message stream must provide week-number fields or the handler must infer week from ephemeris availability.

References
----------
- RTCM 3.x MSM message definitions (DF fields)
- BeiDou, Galileo, GLONASS ICD notes on epoch time definitions

Contact
-------
If you want, I can:
- Add automatic week-rollover detection for recorded streams,
- Pull leap-second table updates automatically,
- Or implement cross-checking with ephemeris timestamps to pick the correct week.
