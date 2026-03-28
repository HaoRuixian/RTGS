from __future__ import annotations

from pathlib import Path

from core.replay_ui_policy import (
    THROTTLED_GUI_INTERVAL_SECONDS,
    choose_gui_refresh_interval,
    estimate_effective_replay_period_seconds,
    is_high_rate_replay,
)


def _header_line(content: str, label: str) -> str:
    return f"{content:<60}{label}\n"


def _write_sample_obs(path: Path, interval: float) -> Path:
    lines = [
        _header_line("     3.04           OBSERVATION DATA    M: MIXED", "RINEX VERSION / TYPE"),
        _header_line("RTGS TESTER         OPENAI              20260323 000000 UTC", "PGM / RUN BY / DATE"),
        _header_line("G    4 C1C L1C D1C S1C", "SYS / # / OBS TYPES"),
        _header_line("  2025     7     5     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
        _header_line(f"{interval:10.3f}", "INTERVAL"),
        _header_line("", "END OF HEADER"),
    ]
    path.write_text("".join(lines), encoding="utf-8")
    return path


def test_high_rate_replay_uses_throttled_gui_interval(tmp_path):
    obs_path = _write_sample_obs(tmp_path / "sample.obs", interval=15.0)
    settings = {
        "source": "RINEX File",
        "file_path": str(obs_path),
        "replay_speed": 30.0,
    }

    assert estimate_effective_replay_period_seconds(settings) == 0.5
    assert is_high_rate_replay(settings) is True
    assert choose_gui_refresh_interval(0.3, settings) == THROTTLED_GUI_INTERVAL_SECONDS


def test_normal_rate_replay_keeps_original_gui_interval(tmp_path):
    obs_path = _write_sample_obs(tmp_path / "sample.obs", interval=15.0)
    settings = {
        "source": "RINEX File",
        "file_path": str(obs_path),
        "replay_speed": 10.0,
    }

    assert estimate_effective_replay_period_seconds(settings) == 1.5
    assert is_high_rate_replay(settings) is False
    assert choose_gui_refresh_interval(0.3, settings) == 0.3


def test_non_file_stream_does_not_trigger_gui_throttling():
    settings = {
        "source": "NTRIP Server",
        "replay_speed": 100.0,
    }

    assert estimate_effective_replay_period_seconds(settings) is None
    assert is_high_rate_replay(settings) is False
    assert choose_gui_refresh_interval(0.3, settings) == 0.3
