from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from core.gnss_time import GNSSTime
from core.rinex_loader import (
    FileEphemerisProvider,
    RinexObservationReader,
    SatelliteEphemerisState,
    _parse_float,
    read_rinex_observation_header,
)


def _header_line(content: str, label: str) -> str:
    return f"{content:<60}{label}\n"


def _obs_line(satellite_id: str, values: list[float]) -> str:
    body = "".join(f"{value:14.3f}  " for value in values)
    return f"{satellite_id}{body}\n"


def _obs_field(value: float, lli: int | str = " ", ssi: int | str = " ") -> str:
    return f"{value:14.3f}{lli}{ssi}"


def _write_sample_obs(path: Path, approx_position=(3875000.0, 332500.0, 5029000.0), interval=15.0) -> Path:
    lines = [
        _header_line("     3.04           OBSERVATION DATA    M: MIXED", "RINEX VERSION / TYPE"),
        _header_line("RTGS TESTER         OPENAI              20260323 000000 UTC", "PGM / RUN BY / DATE"),
        _header_line("G    4 C1C L1C D1C S1C", "SYS / # / OBS TYPES"),
        _header_line(
            f"{approx_position[0]:14.4f}{approx_position[1]:14.4f}{approx_position[2]:14.4f}",
            "APPROX POSITION XYZ",
        ),
        _header_line(f"{interval:10.3f}", "INTERVAL"),
        _header_line("  2025     7     5     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
        _header_line("", "END OF HEADER"),
        "> 2025 07 05 00 00  0.0000000  0  1\n",
        _obs_line("G01", [21474836.000, 123456.789, -1234.567, 45.000]),
        "> 2025 07 05 00 00 15.0000000  0  1\n",
        _obs_line("G01", [21474837.500, 123457.123, -1234.321, 44.500]),
    ]
    path.write_text("".join(lines), encoding="utf-8")
    return path


class _DummyEphemerisProvider:
    def get_state(self, satellite_id: str, gps_week: int, gps_sow: float, pseudorange_m: float | None = None):
        assert satellite_id == "G01"
        assert pseudorange_m is not None
        return SatelliteEphemerisState(
            position_ecef_m=np.array([20200000.0, 14000000.0, 21700000.0], dtype=float),
            clock_correction_s=1.25e-4,
            source="dummy",
        )


def test_read_rinex_observation_header_extracts_interval_and_position(tmp_path):
    obs_path = _write_sample_obs(tmp_path / "sample.obs")

    metadata = read_rinex_observation_header(obs_path)

    assert metadata.interval_seconds == 15.0
    assert metadata.approx_position_ecef == (3875000.0, 332500.0, 5029000.0)
    assert metadata.time_system == "GPS"
    assert metadata.has_nonzero_approx_position is True
    assert metadata.sys_obs_types["G"] == ["C1C", "L1C", "D1C", "S1C"]


def test_parse_float_accepts_embedded_quality_flag():
    assert _parse_float("6483452.632 5") == 6483452.632


def test_rinex_observation_reader_emits_epochs_with_geometry(tmp_path):
    obs_path = _write_sample_obs(tmp_path / "sample.obs")
    reader = RinexObservationReader(obs_path)

    epochs = list(
        reader.iter_epochs(
            ephemeris_provider=_DummyEphemerisProvider(),
            receiver_position_ecef=[3875000.0, 332500.0, 5029000.0],
            target_systems=["G"],
        )
    )

    assert len(epochs) == 2
    assert abs(epochs[1].gps_time - epochs[0].gps_time - 15.0) < 1e-6

    first_sat = epochs[0].satellites["G01"]
    assert "1C" in first_sat.signals
    assert first_sat.signals["1C"].pseudorange == 21474836.0
    assert first_sat.sat_pos_ecef == [20200000.0, 14000000.0, 21700000.0]
    assert first_sat.azimuth is not None
    assert first_sat.elevation is not None


def test_rinex_observation_reader_handles_long_rinex3_records(tmp_path):
    obs_path = tmp_path / "long_record.obs"
    lines = [
        _header_line("     3.04           OBSERVATION DATA    M: MIXED", "RINEX VERSION / TYPE"),
        _header_line("RTGS TESTER         OPENAI              20260323 000000 UTC", "PGM / RUN BY / DATE"),
        _header_line(
            "G   12 C1C L1C D1C S1C C2W L2W D2W S2W C5Q L5Q D5Q S5Q",
            "SYS / # / OBS TYPES",
        ),
        _header_line("  2023     1     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
        _header_line("", "END OF HEADER"),
        "> 2023 01 01 00 00  0.0000000  0  1\n",
        (
            "G01"
            + _obs_field(21601338.228)
            + _obs_field(113515815.404, 0, 7)
            + _obs_field(2269.264)
            + _obs_field(47.750)
            + _obs_field(21601338.137)
            + _obs_field(88453905.327, 0, 7)
            + _obs_field(1768.258)
            + _obs_field(46.150)
            + _obs_field(21601338.485)
            + _obs_field(84768318.817, 0, 8)
            + _obs_field(1694.500)
            + _obs_field(52.950)
            + "\n"
        ),
    ]
    obs_path.write_text("".join(lines), encoding="utf-8")

    reader = RinexObservationReader(obs_path)
    epochs = list(reader.iter_epochs(target_systems=["G"]))

    assert len(epochs) == 1
    sat = epochs[0].satellites["G01"]
    assert sat.signals["1C"].pseudorange == 21601338.228
    assert sat.signals["1C"].phase == 113515815.404
    assert sat.signals["1C"].doppler == 2269.264
    assert sat.signals["1C"].snr == 47.75
    assert sat.signals["2W"].pseudorange == 21601338.137
    assert sat.signals["2W"].phase == 88453905.327
    assert sat.signals["2W"].doppler == 1768.258
    assert sat.signals["2W"].snr == 46.15
    assert sat.signals["5Q"].pseudorange == 21601338.485
    assert sat.signals["5Q"].phase == 84768318.817
    assert sat.signals["5Q"].doppler == 1694.5
    assert sat.signals["5Q"].snr == 52.95


def test_broadcast_nav_provider_loads_sample_nav():
    nav_path = Path("tests/BRDC00IGS_R_20251860000_01D_MN.rnx")

    provider = FileEphemerisProvider.from_file(nav_path, file_type="Broadcast RINEX")
    eph = provider.get_ephemeris("G01")

    assert provider.kind == "broadcast"
    assert eph is not None
    assert eph["satellite_id"] == "G01"
    assert eph["system"] == "GPS"
    assert eph["sqrt_a"] > 5000.0


def test_precise_sp3_provider_reads_sample_sp3_epoch():
    sp3_path = Path("tests/COD0MGXFIN_20252530000_01D_05M_ORB.SP3")
    provider = FileEphemerisProvider.from_file(sp3_path, file_type="Precise SP3")

    utc_epoch = datetime(2025, 9, 9, 23, 59, 42, tzinfo=timezone.utc)
    gps_week, gps_sow = GNSSTime.utc_to_gps(utc_epoch)
    state = provider.get_state("G01", gps_week, gps_sow)

    assert provider.kind == "precise"
    assert state is not None
    np.testing.assert_allclose(
        state.position_ecef_m,
        np.array([-7989131.076, -14219145.388, -20968889.816]),
        atol=1.0,
    )
    assert abs(state.clock_correction_s - 344.257598e-6) < 1e-12
