from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ui.monitoring.workers import RinexReplayThread


def test_replay_speed_normalization_defaults_to_positive_speed():
    assert RinexReplayThread._normalize_replay_speed(None) == 1.0
    assert RinexReplayThread._normalize_replay_speed(0) == 1.0
    assert RinexReplayThread._normalize_replay_speed(-5) == 1.0
    assert RinexReplayThread._normalize_replay_speed("30") == 30.0


def test_epoch_source_delta_uses_real_epoch_spacing_when_available():
    t0 = datetime(2025, 7, 5, 0, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=15)

    delta = RinexReplayThread._epoch_source_delta_seconds(t0, t1, interval_hint=1.0)

    assert delta == 15.0


def test_epoch_source_delta_falls_back_to_interval_hint_for_missing_or_non_monotonic_time():
    t0 = datetime(2025, 7, 5, 0, 0, 15, tzinfo=timezone.utc)
    t1 = t0 - timedelta(seconds=2)

    assert RinexReplayThread._epoch_source_delta_seconds(None, t0, interval_hint=15.0) == 0.0
    assert RinexReplayThread._epoch_source_delta_seconds(t0, None, interval_hint=15.0) == 15.0
    assert RinexReplayThread._epoch_source_delta_seconds(t0, t1, interval_hint=15.0) == 15.0


def test_target_replay_deadline_stays_on_absolute_schedule_at_high_rate():
    replay_start = 100.0
    replay_speed = 30.0
    source_interval = 15.0

    first_deadline = RinexReplayThread._target_replay_deadline(replay_start, 0.0, replay_speed)
    second_deadline = RinexReplayThread._target_replay_deadline(
        replay_start,
        source_interval,
        replay_speed,
    )
    third_deadline = RinexReplayThread._target_replay_deadline(
        replay_start,
        source_interval * 2,
        replay_speed,
    )

    # 15 s source interval at 30x should emit every 0.5 s in wall-clock time.
    assert first_deadline == 100.0
    assert second_deadline == 100.5
    assert third_deadline == 101.0

    # If parsing the previous epoch already consumed 120 ms, the next wait should
    # be shortened accordingly instead of sleeping the full 0.5 s again.
    simulated_now_after_processing = 100.12
    remaining_wait = second_deadline - simulated_now_after_processing
    assert abs(remaining_wait - 0.38) < 1e-9
