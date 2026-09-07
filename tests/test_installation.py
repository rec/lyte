from __future__ import annotations

from pathlib import Path

import pytest

from lyte import dmx, installation


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.now += duration


class FakeDriver:
    def __init__(self, fail_first_send: bool = False) -> None:
        self.fail_first_send = fail_first_send
        self.sent: list[tuple[str, object]] = []
        self.opened = False
        self.blacked_out = False
        self.closed = False

    def open(self) -> bool:
        self.opened = True
        return True

    def send(self, name: str, payload: object) -> bool:
        self.sent.append((name, payload))
        if self.fail_first_send:
            self.fail_first_send = False
            return False
        return True

    def blackout(self) -> None:
        self.blacked_out = True

    def close(self) -> None:
        self.closed = True


class Renderer:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.frame = 0

    def __call__(self) -> object:
        self.frame += 1
        return self.payload


def test_parse_installation_accepts_mixed_targets() -> None:
    config = installation.parse_installation(example_installation())

    assert set(config.twinkly_targets) == {'tree'}
    assert config.twinkly_targets['tree'].led_count == 250
    assert set(config.dmx_targets) == {'front_wash'}
    assert config.dmx_targets['front_wash'].name == 'front_wash'
    assert isinstance(config.dmx_targets['front_wash'].categories[1], dmx.RgbChannels)
    assert set(config.run) == {'tree', 'front_wash'}


def test_load_installation_reports_source_path(tmp_path: Path) -> None:
    path = tmp_path / 'invalid.toml'
    path.write_text('[run.missing]\nprogram = "unknown"\n')

    with pytest.raises(installation.InstallationFileError, match=str(path)):
        installation.load_installation(path)


def test_installation_rejects_program_for_wrong_target_family() -> None:
    data = example_installation()
    data['run'] = {'tree': {'program': 'wash'}}

    with pytest.raises(ValueError, match='requires a pixel program'):
        installation.parse_installation(data)


def test_build_runtime_constructs_both_target_families() -> None:
    runtime = installation.build_runtime(
        installation.parse_installation(example_installation())
    )

    assert [target.name for target in runtime.targets] == ['tree', 'front_wash']
    assert isinstance(runtime.targets[0].render, installation.PixelRenderer)
    assert isinstance(runtime.targets[1].render, installation.DmxRenderer)
    assert len(runtime.drivers) == 2


def test_scheduler_runs_pixel_and_dmx_targets_on_one_clock() -> None:
    clock = FakeClock()
    pixel_driver = FakeDriver()
    dmx_driver = FakeDriver()
    runtime = installation.InstallationRuntime(
        targets=[
            installation.InstallationTarget(
                name='tree',
                fps=2,
                render=Renderer('pixels'),
                driver=pixel_driver,
            ),
            installation.InstallationTarget(
                name='wash',
                fps=1,
                render=Renderer('dmx'),
                driver=dmx_driver,
            ),
        ],
        drivers=[pixel_driver, dmx_driver],
    )

    status = installation.run_runtime(
        runtime, duration=1, clock=clock.monotonic, sleep=clock.sleep
    )

    assert pixel_driver.sent == [('tree', 'pixels'), ('tree', 'pixels')]
    assert dmx_driver.sent == [('wash', 'dmx')]
    assert status.targets['tree'].frame_count == 2
    assert status.targets['wash'].frame_count == 1
    assert pixel_driver.blacked_out and pixel_driver.closed
    assert dmx_driver.blacked_out and dmx_driver.closed


def test_scheduler_reports_failure_and_continues_other_targets() -> None:
    clock = FakeClock()
    failing_driver = FakeDriver(fail_first_send=True)
    healthy_driver = FakeDriver()
    runtime = installation.InstallationRuntime(
        targets=[
            installation.InstallationTarget(
                name='failing',
                fps=2,
                render=Renderer('first'),
                driver=failing_driver,
            ),
            installation.InstallationTarget(
                name='healthy',
                fps=2,
                render=Renderer('second'),
                driver=healthy_driver,
            ),
        ],
        drivers=[failing_driver, healthy_driver],
    )

    status = installation.run_runtime(
        runtime, duration=1, clock=clock.monotonic, sleep=clock.sleep
    )

    assert len(failing_driver.sent) == 2
    assert len(healthy_driver.sent) == 2
    assert status.targets['failing'].failure_count == 1
    assert status.targets['failing'].frame_count == 1
    assert status.targets['healthy'].failure_count == 0
    assert not status.successful


def example_installation() -> dict[str, object]:
    return {
        'artnet': {'host': '192.168.1.50'},
        'twinkly': {'tree': {'host': '192.168.1.23', 'led_count': 250, 'fps': 30}},
        'dmx': {
            'front_wash': {
                'universe': 1,
                'start_channel': 1,
                'channel_count': 8,
                'fps': 40,
                'categories': [
                    {'kind': 'brightness', 'channels': [1]},
                    {'kind': 'rgb', 'red': [2], 'green': [3], 'blue': [4]},
                    {'kind': 'chase_speed', 'channels': [5]},
                    {
                        'kind': 'pattern_select',
                        'channels': [6],
                        'patterns': {'static': 0, 'chase': 64},
                    },
                    {'kind': 'raw', 'name': 'reserved', 'channels': [7, 8]},
                ],
            }
        },
        'programs': {
            'rainbow': {
                'kind': 'pixel',
                'impl': 'lyte.animations.bibliopixel.rainbow.Rainbow',
            },
            'wash': {
                'kind': 'dmx',
                'brightness': 0.5,
                'rgb': [1.0, 0.25, 0.0],
                'chase_speed': 1.0,
                'pattern': 'chase',
            },
        },
        'run': {
            'tree': {'program': 'rainbow'},
            'front_wash': {'program': 'wash'},
        },
    }
