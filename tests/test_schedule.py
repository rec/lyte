from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from astral import Observer
from pydantic import ValidationError

from lyte import installation, installation_config, installation_playback, schedule
from lyte.twinkly.diagnostic import TwinklyDeviceInfo


@pytest.fixture
def config() -> schedule.DailySchedule:
    return schedule.DailySchedule(
        latitude=49.4432, longitude=1.0993, timezone='Europe/Paris'
    )


@pytest.fixture
def sunset_at_six(monkeypatch: pytest.MonkeyPatch) -> None:
    def setting(observer: Observer, date: date, tzinfo: ZoneInfo) -> datetime:
        return datetime.combine(date, time(18), tzinfo)

    monkeypatch.setattr(schedule, 'sunset', setting)


@pytest.mark.parametrize(
    'clock,phase,level',
    [
        ('18:29:59', 'off', 0),
        ('18:30', 'fading_in', 0),
        ('19:00', 'fading_in', 0.5),
        ('19:30', 'full', 1),
        ('22:59:59', 'full', 1),
        ('23:00', 'fading_out', 1),
        ('23:15', 'fading_out', 0.5),
        ('23:30', 'off', 0),
    ],
)
def test_daily_fade_boundaries_and_midpoints(
    config: schedule.DailySchedule,
    sunset_at_six: None,
    clock: str,
    phase: str,
    level: float,
) -> None:
    now = datetime.combine(date(2026, 1, 15), time.fromisoformat(clock), config.zone)
    status = schedule.SunsetScheduler(config).evaluate(now)
    assert status.phase == phase
    assert status.level == level


def test_late_sunset_holds_full_brightness_for_two_hours_across_midnight(
    config: schedule.DailySchedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    def setting(observer: Observer, date: date, tzinfo: ZoneInfo) -> datetime:
        return datetime.combine(date, time(22), tzinfo)

    monkeypatch.setattr(schedule, 'sunset', setting)
    scheduler = schedule.SunsetScheduler(config)
    day = date(2026, 6, 21)
    window = schedule.evening_window(config, day)
    assert window.fade_out_at.astimezone(config.zone) == datetime(
        2026, 6, 22, 1, 30, tzinfo=config.zone
    )
    assert window.fade_out_at - window.full_at == timedelta(hours=2)
    at = window.fade_out_at + timedelta(minutes=15)
    status = scheduler.evaluate(at)
    assert status.phase == 'fading_out'
    assert status.level == 0.5
    assert status.starts_at == window.starts_at
    assert scheduler.evaluate(window.ends_at).level == 0


def test_restarts_clock_changes_and_date_rollover_recompute_current_brightness(
    config: schedule.DailySchedule, sunset_at_six: None
) -> None:
    scheduler = schedule.SunsetScheduler(config)
    now = datetime(2026, 1, 15, 19, tzinfo=config.zone)
    assert scheduler.evaluate(now).level == 0.5
    assert schedule.SunsetScheduler(config).evaluate(now).level == 0.5
    assert scheduler.evaluate(now - timedelta(hours=1)).level == 0
    assert scheduler.evaluate(now + timedelta(days=1)).level == 0.5
    assert scheduler.evaluate(now).level == 0.5


@pytest.mark.parametrize('day', [date(2026, 3, 29), date(2026, 10, 25)])
def test_fades_measure_elapsed_time_across_daylight_saving_changes(
    config: schedule.DailySchedule, monkeypatch: pytest.MonkeyPatch, day: date
) -> None:
    def setting(observer: Observer, date: date, tzinfo: ZoneInfo) -> datetime:
        return datetime.combine(date, time(1), tzinfo)

    monkeypatch.setattr(schedule, 'sunset', setting)
    window = schedule.evening_window(config, day)
    at = window.starts_at + timedelta(minutes=30)
    assert schedule.SunsetScheduler(config).evaluate(at).level == 0.5
    assert window.full_at - window.starts_at == timedelta(hours=1)
    assert window.fade_out_at.astimezone(config.zone).hour == 23


def test_missing_sunset_is_reported_and_later_dates_can_recover() -> None:
    config = schedule.DailySchedule(latitude=70, longitude=0, timezone='UTC')
    scheduler = schedule.SunsetScheduler(config)
    status = scheduler.evaluate(datetime(2026, 6, 21, tzinfo=UTC))
    assert status.phase == 'error'
    assert status.level == 0
    assert status.error is not None
    assert scheduler.evaluate(datetime(2026, 4, 15, tzinfo=UTC)).error is None


def test_configured_maximum_limits_the_whole_envelope(
    config: schedule.DailySchedule, sunset_at_six: None
) -> None:
    config = config.model_copy(update={'maximum_level': 0.4})
    now = datetime(2026, 1, 15, 19, tzinfo=config.zone)
    assert schedule.SunsetScheduler(config).evaluate(now).level == 0.2


@pytest.mark.parametrize(
    'values',
    [
        {'timezone': 'Unknown/Town'},
        {'latitude': 91},
        {'longitude': float('nan')},
        {'fade_in': '0s'},
        {'fade_out': '-1s'},
        {'minimum_hold': '25h'},
        {'fade_out_not_before': '23:00+02:00'},
        {'maximum_level': 1.1},
    ],
)
def test_schedule_rejects_invalid_configuration(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        schedule.DailySchedule.model_validate(
            {'latitude': 49.4432, 'longitude': 1.0993, 'timezone': 'Europe/Paris'}
            | values
        )


def test_daemon_combines_schedule_and_operator_brightness_and_reports_status(
    config: schedule.DailySchedule,
    sunset_at_six: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = installation_config.load_installation(
        Path('examples/installation-sunset.toml')
    )
    clock = Mock(wraps=datetime)
    clock.now.return_value = datetime(2026, 1, 15, 19, tzinfo=config.zone)
    monkeypatch.setattr(installation, 'datetime', clock)
    runtime = installation.build_service(
        definition,
        {
            'garden': installation.TwinklyAssignment(
                'garden', '192.0.2.1', TwinklyDeviceInfo(raw={})
            )
        },
    )
    monkeypatch.setattr(installation.InstallationService, 'publish_status', Mock())
    runtime.playback.select('random_walk')
    reference = installation_playback.InstallationPlayback(
        definition, runtime.library, {'garden': 1}
    )
    reference.select('random_walk')
    expected = reference.render(0)[0][1]
    runtime.playback.command('master_level', {'level': 0.5})
    frame = runtime.render(0)[0][1]
    assert np.array_equal(frame, np.rint(expected.astype(float) * 0.25))
    status = runtime.status_snapshot()
    assert status.schedule is not None
    assert status.schedule.phase == 'fading_in'
    assert status.schedule.level == 0.5
    assert status.master_level == 0.5
    runtime.playback.command('blackout', {})
    assert not runtime.render(0.1)[0][1].any()


def test_installation_parameters_apply_to_random_walk_initial_fill() -> None:
    config = installation_config.load_installation(
        Path('examples/installation-sunset.toml')
    )
    definition = config.animations['random_walk'].model_copy(
        update={'parameters': {'speed': 60, 'variance': 0, 'seed': 42}}
    )
    config = config.model_copy(update={'animations': {'random_walk': definition}})
    library = installation_playback.load_library(config)
    playback = installation_playback.InstallationPlayback(
        config, library, {'garden': 250}
    )
    playback.select('random_walk')
    frame = playback.render(0)[0][1]
    assert np.all(frame == frame[0])
    assert frame.any()


def test_invalid_installation_parameters_fail_before_device_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = installation_config.load_installation(
        Path('examples/installation-sunset.toml')
    )
    definition = config.animations['random_walk'].model_copy(
        update={'parameters': {'variance': 256}}
    )
    config = config.model_copy(update={'animations': {'random_walk': definition}})
    discover = Mock()
    monkeypatch.setattr(installation, 'discover_assignments', discover)
    with pytest.raises(installation_config.InstallationFileError, match='public range'):
        installation.build_service(config)
    discover.assert_not_called()
