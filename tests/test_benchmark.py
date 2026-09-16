from pathlib import Path

import pytest
from ufor import library_files

from lyte import (
    benchmark,
    installation_config,
    installation_playback,
    metrics,
    rendering,
)


def test_benchmark_reports_frames_that_exceed_the_render_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter([0.0, 0.1, 0.1, 0.12])
    monkeypatch.setattr(rendering, 'perf_counter', lambda: next(clock))
    result = benchmark.benchmark(
        benchmark.BenchmarkConfig(
            selector='aurora',
            library_config=Path('examples/library.toml'),
            duration=0.1,
        )
    )
    assert result.frames == 2
    assert result.light_count == 250
    assert result.fps == 20
    assert result.mean_seconds == pytest.approx(0.06)
    assert result.max_seconds == 0.1
    assert result.over_budget_frames == 1


def test_catch_up_costs_survive_note_restarts_and_reselection() -> None:
    config = installation_config.parse_installation(
        {
            'twinkly': {'left': {}},
            'midi': {},
            'initial_animation': 'a',
            'animations': {'a': {'selector': 'aurora', 'outputs': {'light': 'left'}}},
        }
    )
    playback = installation_playback.InstallationPlayback(
        config, library_files.read_library(Path('examples/library.toml')), {'left': 4}
    )
    playback.select('a')
    playback.render(0)
    playback.render(0.5)
    cost = playback.render_costs['a']['light']
    assert cost.frames == 11
    assert cost.catch_up_ticks == 9
    playback.select('a')
    playback.render(1)
    assert cost.frames == 12
    assert playback.render_costs['a']['light'] is cost


def test_delivery_report_separates_interval_and_lateness() -> None:
    timing = metrics.DeliveryTiming(scheduled_interval_seconds=0.05)
    timing.record(None, 0)
    timing.record(0.08, 0.03)
    timing.record(0.02, 0)
    assert timing.mean_interval_seconds == pytest.approx(0.05)
    assert timing.max_interval_seconds == 0.08
    assert timing.max_lateness_seconds == 0.03
