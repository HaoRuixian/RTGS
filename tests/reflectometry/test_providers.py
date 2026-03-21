"""Provider tests."""

from datetime import datetime

import pandas as pd

from core.reflectometry.providers import CsvObservationProvider
from core.reflectometry.models import ObservationRequest, ReceiverPosition


def test_csv_provider_normalizes_columns(tmp_path):
    path = tmp_path / "observations.csv"
    pd.DataFrame(
        [
            {
                "time": "2026-03-19T00:00:00",
                "sys": "G",
                "prn": "G01",
                "signal_id": "1C",
                "cno": 45.2,
                "azimuth": 180.0,
                "elevation": 12.5,
            }
        ]
    ).to_csv(path, index=False)

    provider = CsvObservationProvider(
        path=path,
        station_id="DEMO",
        receiver_position=ReceiverPosition(latitude_deg=1.0, longitude_deg=2.0, height_m=3.0),
    )
    records = provider.fetch_observations(
        ObservationRequest(
            start_time=datetime.fromisoformat("2026-03-18T23:59:00"),
            end_time=datetime.fromisoformat("2026-03-19T00:01:00"),
            constellations=("G",),
            signals=("1C",),
        )
    )

    assert len(records) == 1
    assert records[0].station_id == "DEMO"
    assert records[0].satellite == "G01"
    assert records[0].elevation_deg == 12.5


def test_csv_provider_supports_exclusion_filters(tmp_path):
    path = tmp_path / "observations.csv"
    pd.DataFrame(
        [
            {
                "time": "2026-03-19T00:00:00",
                "sys": "G",
                "prn": "G01",
                "signal_id": "1C",
                "cno": 45.2,
                "azimuth": 180.0,
                "elevation": 12.5,
            },
            {
                "time": "2026-03-19T00:00:30",
                "sys": "R",
                "prn": "R02",
                "signal_id": "2C",
                "cno": 41.0,
                "azimuth": 190.0,
                "elevation": 14.0,
            },
        ]
    ).to_csv(path, index=False)

    provider = CsvObservationProvider(
        path=path,
        station_id="DEMO",
        receiver_position=ReceiverPosition(latitude_deg=1.0, longitude_deg=2.0, height_m=3.0),
    )
    records = provider.fetch_observations(
        ObservationRequest(
            start_time=datetime.fromisoformat("2026-03-18T23:59:00"),
            end_time=datetime.fromisoformat("2026-03-19T00:01:00"),
            exclude_constellations=("R",),
            exclude_signals=("2C",),
        )
    )

    assert len(records) == 1
    assert records[0].satellite == "G01"


