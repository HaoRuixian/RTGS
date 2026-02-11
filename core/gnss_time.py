from datetime import datetime, timedelta, timezone


class GNSSTime:
    """Utility class for GNSS/GPS <-> UTC time conversions.

    Notes:
    - GPS time started at 1980-01-06 00:00:00 (GPS epoch) and does not include leap seconds.
    - UTC includes leap seconds; by default this class uses a fixed leap-second offset
      (18s at time of writing). For production use consider updating leap seconds
      dynamically from a service or table.
    """

    GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)
    LEAP_SECONDS = 18

    @classmethod
    def gps_to_utc_datetime(cls, gps_week: int, gps_seconds: float) -> datetime:
        """Convert GPS week + seconds-of-week to UTC datetime.

        Args:
            gps_week: GPS week number
            gps_seconds: Seconds within the GPS week

        Returns:
            timezone-aware UTC datetime
        """
        total_seconds = gps_week * 7 * 24 * 3600 + gps_seconds
        # GPS time does not include leap seconds, so subtract to get UTC
        utc_dt = cls.GPS_EPOCH + timedelta(seconds=total_seconds - cls.LEAP_SECONDS)
        return utc_dt

    @classmethod
    def utc_to_gps(cls, utc_dt: datetime) -> (int, float):
        """Convert UTC datetime to GPS week and seconds-of-week.

        Returns:
            (week, seconds_of_week)
        """
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)

        # GPS time = UTC + leap_seconds
        gps_time = utc_dt + timedelta(seconds=cls.LEAP_SECONDS)
        delta = gps_time - cls.GPS_EPOCH
        total_seconds = delta.total_seconds()
        week = int(total_seconds // (7 * 24 * 3600))
        seconds_of_week = total_seconds - week * 7 * 24 * 3600
        return week, seconds_of_week

    @classmethod
    def current_gps_week(cls, utc_dt: datetime = None) -> int:
        """Return current GPS week for given UTC (or now)."""
        if utc_dt is None:
            utc_dt = datetime.utcnow().replace(tzinfo=timezone.utc)
        week, _ = cls.utc_to_gps(utc_dt)
        return week

    @classmethod
    def gps_day_of_week(cls, utc_dt: datetime = None) -> int:
        """Return day-of-week in GPS time (0=Sunday..6=Saturday).

        This mirrors earlier code that computed day-of-week from GPS time.
        """
        if utc_dt is None:
            utc_dt = datetime.utcnow().replace(tzinfo=timezone.utc)
        _, seconds_of_week = cls.utc_to_gps(utc_dt)
        day = int(seconds_of_week // (24 * 3600))
        return day


__all__ = ["GNSSTime"]
