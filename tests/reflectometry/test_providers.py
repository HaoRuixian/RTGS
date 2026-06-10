"""Provider tests."""

from datetime import datetime

from core.reflectometry.models import ObservationRecord, ObservationRequest, ReceiverPosition
from core.reflectometry.providers import CacheObservationProvider, ListObservationProvider


def test_list_provider_respects_request_filters():
    records = [
        ObservationRecord(
            station_id="DEMO",
            timestamp=datetime.fromisoformat("2026-03-19T00:00:00"),
            constellation="G",
            satellite="G01",
            signal="1C",
            snr=45.2,
            azimuth_deg=180.0,
            elevation_deg=12.5,
        ),
        ObservationRecord(
            station_id="DEMO",
            timestamp=datetime.fromisoformat("2026-03-19T00:00:30"),
            constellation="R",
            satellite="R02",
            signal="2C",
            snr=41.0,
            azimuth_deg=190.0,
            elevation_deg=14.0,
        ),
    ]

    provider = ListObservationProvider(records)
    filtered = provider.fetch_observations(
        ObservationRequest(
            start_time=datetime.fromisoformat("2026-03-18T23:59:00"),
            end_time=datetime.fromisoformat("2026-03-19T00:01:00"),
            exclude_constellations=("R",),
            exclude_signals=("2C",),
        )
    )

    assert len(filtered) == 1
    assert filtered[0].satellite == "G01"


def test_cache_provider_normalizes_mapping_payloads():
    payload = [
        {
            "timestamp": "2026-03-19T00:00:00",
            "constellation": "G",
            "satellite": "G01",
            "signal": "1C",
            "snr": 45.2,
            "azimuth_deg": 180.0,
            "elevation_deg": 12.5,
        }
    ]

    provider = CacheObservationProvider(
        reader=lambda _request: payload,
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


def test_signal_filters_accept_rinex_observation_type_prefixes():
    records = [
        ObservationRecord(
            station_id="DEMO",
            timestamp=datetime.fromisoformat("2026-03-19T00:00:00"),
            constellation="C",
            satellite="C07",
            signal="2I",
            snr=45.2,
            azimuth_deg=180.0,
            elevation_deg=12.5,
        )
    ]

    provider = ListObservationProvider(records)
    filtered = provider.fetch_observations(ObservationRequest(signals=("S2I",)))

    assert len(filtered) == 1
    assert filtered[0].satellite_system_key == ("C", "C07", "2I")
