from __future__ import annotations

import pytest

from core.rtcm_handler import RTCMHandler


class FakeRTCMMessage:
    def __init__(self, identity: str, **attrs):
        self.identity = identity
        for key, value in attrs.items():
            setattr(self, key, value)


def test_rtcm_handler_parses_gps_combined_ssr_corrections():
    handler = RTCMHandler(compute_geometry=False)
    msg = FakeRTCMMessage(
        "1060",
        DF385=100.0,
        DF391=1,
        DF388=0,
        DF375=0,
        DF413=4,
        DF414=12,
        DF415=1,
        DF387=1,
        DF068_01=1,
        DF071_01=7,
        DF365_01=1000.0,
        DF366_01=2000.0,
        DF367_01=-3000.0,
        DF368_01=10.0,
        DF369_01=20.0,
        DF370_01=-30.0,
        DF376_01=500.0,
        DF377_01=2.0,
        DF378_01=-0.5,
    )

    handler.process_message(msg)

    orbit = handler.ssr_corrections.get_orbit("G01")
    clock = handler.ssr_corrections.get_clock("G01")
    assert orbit is not None
    assert clock is not None
    assert orbit.delta_radial_m == pytest.approx(1.0)
    assert orbit.delta_along_track_m == pytest.approx(2.0)
    assert orbit.delta_cross_track_m == pytest.approx(-3.0)
    assert orbit.dot_delta_radial_mps == pytest.approx(0.01)
    assert orbit.iod == 7
    assert clock.delta_clock_m == pytest.approx(0.5)
    assert clock.delta_clock_rate_mps == pytest.approx(0.002)
    assert clock.delta_clock_accel_mps2 == pytest.approx(-0.0005)


def test_rtcm_handler_parses_non_gps_ssr_satellite_fields():
    handler = RTCMHandler(compute_geometry=False)

    handler.process_message(
        FakeRTCMMessage(
            "1064",
            DF386=120.0,
            DF391=1,
            DF388=0,
            DF413=4,
            DF414=12,
            DF415=1,
            DF387=1,
            DF384_01=7,
            DF376_01=250.0,
            DF377_01=0.0,
            DF378_01=0.0,
        )
    )
    handler.process_message(
        FakeRTCMMessage(
            "1240",
            DF458=130.0,
            DF391=1,
            DF388=0,
            DF375=0,
            DF413=4,
            DF414=12,
            DF415=1,
            DF387=1,
            DF252_01=11,
            DF459_01=9,
            DF365_01=100.0,
            DF366_01=0.0,
            DF367_01=0.0,
            DF368_01=0.0,
            DF369_01=0.0,
            DF370_01=0.0,
        )
    )
    handler.process_message(
        FakeRTCMMessage(
            "1258",
            DF465=140.0,
            DF391=1,
            DF388=0,
            DF375=0,
            DF413=4,
            DF414=12,
            DF415=1,
            DF387=1,
            DF488_01=6,
            DF471_01=5,
            DF365_01=200.0,
            DF366_01=0.0,
            DF367_01=0.0,
            DF368_01=0.0,
            DF369_01=0.0,
            DF370_01=0.0,
        )
    )

    assert handler.ssr_corrections.get_clock("R07").delta_clock_m == pytest.approx(0.25)
    assert handler.ssr_corrections.get_orbit("E11").delta_radial_m == pytest.approx(0.1)
    assert handler.ssr_corrections.get_orbit("C06").delta_radial_m == pytest.approx(0.2)
