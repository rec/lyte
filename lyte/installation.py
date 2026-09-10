"""Mixed Twinkly and DMX installation playback."""

from __future__ import annotations

import socket
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal, Protocol, cast

import numpy as np
import tyro
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, SkipValidation, ValidationError
from reccy.runtime import logging
from ufor import library_files
from ufor.library import Library
from ufor.lights import Interpretation

from . import animation, artnet, dmx, rendering, show
from .retry import RetryConfig
from .twinkly import track
from .twinkly.client import TwinklyClient

LOGGER = logging.get_logger(__name__)


@dataclass(frozen=True)
class InstallationCommandConfig:
    action: Annotated[Literal['run'], tyro.conf.Positional] = 'run'
    config: Annotated[Path, tyro.conf.Positional] = Path('installation.toml')
    duration: float | None = None


class InstallationFileError(ValueError):
    pass


class InstallationDefinition(BaseModel, frozen=True):
    model_config = ConfigDict(extra='forbid')


class TwinklyTargetSpec(InstallationDefinition, frozen=True):
    host: str = Field(min_length=1)
    led_count: int = Field(gt=0)
    fps: float = Field(default=30.0, gt=0)
    timeout: float = Field(default=5.0, gt=0)
    attempts: int = Field(default=10, gt=0)
    retry_delay: float = Field(default=0.5, ge=0)
    retry_backoff: float = Field(default=2.0, ge=1)


class DmxTargetSpec(dmx.DmxInstrument, frozen=True):
    fps: float = Field(default=40.0, gt=0)


class PixelProgramSpec(show.LightProgramSpec, frozen=True):
    kind: Literal['pixel'] = 'pixel'


class DmxProgramSpec(dmx.DmxValues, frozen=True):
    kind: Literal['dmx'] = 'dmx'


ProgramSpec = Annotated[PixelProgramSpec | DmxProgramSpec, Field(discriminator='kind')]


class InstallationRunSpec(InstallationDefinition, frozen=True):
    program: str = Field(min_length=1)


class InstallationFile(InstallationDefinition, frozen=True):
    library_config: Path | None = None
    artnet_endpoint: artnet.ArtNetEndpoint | None = None
    twinkly_targets: dict[str, TwinklyTargetSpec] = Field(default_factory=dict)
    dmx_targets: dict[str, DmxTargetSpec] = Field(default_factory=dict)
    programs: dict[str, ProgramSpec] = Field(default_factory=dict)
    run: dict[str, InstallationRunSpec] = Field(default_factory=dict)


class OutputDriver(Protocol):
    def open(self) -> bool: ...

    def send(self, name: str, payload: object) -> bool: ...

    def blackout(self) -> None: ...

    def close(self) -> None: ...


class TargetStatus(BaseModel):
    state: Literal['pending', 'running', 'stopped', 'failed'] = 'pending'
    frame_count: int = 0
    failure_count: int = 0
    last_error: str | None = None


class InstallationStatus(BaseModel, frozen=True):
    targets: dict[str, TargetStatus]

    @property
    def successful(self) -> bool:
        return all(status.failure_count == 0 for status in self.targets.values())


class InstallationTarget(BaseModel):
    name: str
    fps: float = Field(gt=0)
    render: SkipValidation[Callable[[], object]]
    driver: SkipValidation[OutputDriver]
    status: TargetStatus = Field(default_factory=TargetStatus)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class InstallationRuntime(BaseModel):
    targets: list[InstallationTarget]
    drivers: list[SkipValidation[OutputDriver]]

    model_config = ConfigDict(arbitrary_types_allowed=True)


class PixelRenderer:
    def __init__(
        self, prepared: rendering.PreparedAnimation, output_fps: float
    ) -> None:
        self.prepared = prepared
        self.tick_ratio = prepared.rate / Fraction(str(output_fps))
        self.frame_count = 0
        self.current: NDArray[np.uint8] | None = None

    def __call__(self) -> NDArray[np.uint8]:
        logical_tick = int(self.frame_count * self.tick_ratio)
        while self.prepared.tick <= logical_tick:
            self.current = self.prepared.byte_frame(wired=True)
        self.frame_count += 1
        assert self.current is not None
        return self.current


class DmxRenderer:
    def __init__(
        self,
        program: dmx.DmxProgram,
        instrument: dmx.DmxInstrument,
        state: dmx.DmxState,
    ) -> None:
        self.program = program
        self.instrument = instrument
        self.state = state

    def __call__(self) -> dmx.InstrumentOutput:
        return dmx.InstrumentOutput(
            instrument=self.instrument,
            values=self.program.render(self.instrument, self.state),
        )


class TwinklyOutputDriver:
    def __init__(self, name: str, spec: TwinklyTargetSpec) -> None:
        self.name = name
        self.spec = spec
        client = TwinklyClient(host=spec.host, timeout=spec.timeout)
        self.track = track.TwinklyTrack(
            client=client,
            retry=RetryConfig(
                attempts=spec.attempts,
                delay=spec.retry_delay,
                backoff=spec.retry_backoff,
            ),
            host=spec.host,
            configured_host=spec.host,
            discovery_timeout=None,
            device=animation.Device(led_count=spec.led_count),
            expected_mac=None,
        )
        self._socket: socket.socket | None = None

    def open(self) -> bool:
        if not self.track.prepare():
            self.track.close()
            return False
        self._socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )
        return True

    def send(self, name: str, payload: object) -> bool:
        if self._socket is None:
            raise RuntimeError('Twinkly output driver is not open')
        if not isinstance(payload, np.ndarray) or payload.dtype != np.uint8:
            raise ValueError('Twinkly output requires a uint8 RGB frame')
        return self.track.send_frame(
            name, cast(NDArray[np.uint8], payload), self._socket
        )

    def blackout(self) -> None:
        self.track.close()

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None


class ArtNetOutputDriver:
    def __init__(
        self, endpoint: artnet.ArtNetEndpoint, instruments: list[DmxTargetSpec]
    ) -> None:
        self.driver = artnet.ArtNetDriver(endpoint)
        self.outputs = {
            instrument.name: dmx.InstrumentOutput(
                instrument=instrument, values=dmx.DmxValues()
            )
            for instrument in instruments
        }

    def open(self) -> bool:
        self.driver.open()
        return True

    def send(self, name: str, payload: object) -> bool:
        if not isinstance(payload, dmx.InstrumentOutput):
            raise ValueError('Art-Net output requires a DMX instrument output')
        if (
            name not in self.outputs
            or payload.instrument != self.outputs[name].instrument
        ):
            raise ValueError(f'Art-Net output does not match instrument {name!r}')
        self.outputs[name] = payload
        self.driver.send(dmx.render_universes(list(self.outputs.values())))
        return True

    def blackout(self) -> None:
        universes = sorted(
            {output.instrument.universe for output in self.outputs.values()}
        )
        self.driver.blackout(universes)

    def close(self) -> None:
        self.driver.close()


def load_installation(path: Path) -> InstallationFile:
    try:
        with path.open('rb') as source:
            data = tomllib.load(source)
        config = parse_installation(data)
        if (
            config.library_config is not None
            and not config.library_config.is_absolute()
        ):
            config = config.model_copy(
                update={'library_config': path.parent / config.library_config}
            )
        return config
    except (OSError, tomllib.TOMLDecodeError, ValidationError, ValueError) as error:
        raise InstallationFileError(f'{path}: {error}') from error


def parse_installation(data: dict[str, object]) -> InstallationFile:
    allowed = {'library_config', 'artnet', 'twinkly', 'dmx', 'programs', 'run'}
    if unknown := sorted(set(data) - allowed):
        raise ValueError(f'unknown top-level sections: {", ".join(unknown)}')
    dmx_data = _table(data.get('dmx', {}), 'dmx')
    parsed = InstallationFile.model_validate(
        {
            'library_config': data.get('library_config'),
            'artnet_endpoint': data.get('artnet'),
            'twinkly_targets': data.get('twinkly', {}),
            'dmx_targets': {
                name: _table(value, f'dmx.{name}') | {'name': name}
                for name, value in dmx_data.items()
            },
            'programs': data.get('programs', {}),
            'run': data.get('run', {}),
        }
    )
    _validate_installation(parsed)
    return parsed


def build_runtime(config: InstallationFile) -> InstallationRuntime:
    library = _read_pixel_library(config)
    targets: list[InstallationTarget] = []
    drivers: list[OutputDriver] = []
    pixel_drivers = {
        name: TwinklyOutputDriver(name, config.twinkly_targets[name])
        for name in config.run
        if name in config.twinkly_targets
    }
    drivers.extend(pixel_drivers.values())
    artnet_driver = None
    if config.dmx_targets:
        if config.artnet_endpoint is None:
            raise InstallationFileError('DMX targets require an Art-Net endpoint')
        instruments = [
            config.dmx_targets[name]
            for name in config.run
            if name in config.dmx_targets
        ]
        artnet_driver = ArtNetOutputDriver(config.artnet_endpoint, instruments)
        drivers.append(artnet_driver)
    for name, run_spec in config.run.items():
        program_spec = config.programs[run_spec.program]
        if name in config.twinkly_targets:
            target_spec = config.twinkly_targets[name]
            if not isinstance(program_spec, PixelProgramSpec):
                raise InstallationFileError(
                    f'Twinkly target {name!r} requires a pixel program'
                )
            if library is None:
                raise InstallationFileError('pixel programs require a Ufor library')
            try:
                prepared = show.prepare_library_animation(library, program_spec)
            except ValueError as error:
                raise InstallationFileError(
                    f'pixel program {run_spec.program!r}: {error}'
                ) from error
            _validate_twinkly_program(name, target_spec, prepared)
            targets.append(
                InstallationTarget(
                    name=name,
                    fps=target_spec.fps,
                    render=PixelRenderer(prepared, target_spec.fps),
                    driver=pixel_drivers[name],
                )
            )
        else:
            target_spec = config.dmx_targets[name]
            if not isinstance(program_spec, DmxProgramSpec):
                raise InstallationFileError(
                    f'DMX target {name!r} requires a DMX program'
                )
            values = dmx.DmxValues.model_validate(
                program_spec.model_dump(exclude={'kind'})
            )
            program = dmx.StaticDmxProgram(values=values)
            state = program.initial_state(target_spec)
            state.fps = target_spec.fps
            targets.append(
                InstallationTarget(
                    name=name,
                    fps=target_spec.fps,
                    render=DmxRenderer(program, target_spec, state),
                    driver=cast(OutputDriver, artnet_driver),
                )
            )
    return InstallationRuntime(targets=targets, drivers=drivers)


def _read_pixel_library(config: InstallationFile) -> Library | None:
    if not any(isinstance(p, PixelProgramSpec) for p in config.programs.values()):
        return None
    try:
        library = library_files.read_library(config.library_config)
    except (OSError, ValueError) as error:
        raise InstallationFileError(str(error)) from error
    show.log_diagnostics(library)
    return library


def _validate_twinkly_program(
    name: str,
    target: TwinklyTargetSpec,
    prepared: rendering.PreparedAnimation,
) -> None:
    output = prepared.output
    if output.components != ['red', 'green', 'blue']:
        raise InstallationFileError(
            f'Twinkly target {name!r} requires red, green, blue components'
        )
    if output.interpretation != Interpretation.drive:
        raise InstallationFileError(
            f'Twinkly target {name!r} requires drive light values'
        )
    if len(output.layout.lights) != target.led_count:
        raise InstallationFileError(
            f'Twinkly target {name!r} has {target.led_count} LEDs but score '
            f'layout {output.layout.name!r} has {len(output.layout.lights)}'
        )


def run_runtime(
    runtime: InstallationRuntime,
    duration: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> InstallationStatus:
    if duration is not None and duration <= 0:
        raise ValueError('duration must be greater than zero')
    targets_by_driver = {
        id(driver): [target for target in runtime.targets if target.driver is driver]
        for driver in runtime.drivers
    }
    active = {target.name: target for target in runtime.targets}
    opened: list[OutputDriver] = []
    started_at = clock()
    next_due = {target.name: started_at for target in runtime.targets}
    stop_at = None if duration is None else started_at + duration
    try:
        for driver in runtime.drivers:
            driver_targets = targets_by_driver[id(driver)]
            try:
                if not driver.open():
                    raise RuntimeError('output driver did not open')
                opened.append(driver)
                for target in driver_targets:
                    target.status.state = 'running'
            except (OSError, RuntimeError, ValueError) as error:
                for target in driver_targets:
                    _record_failure(target, f'open failed: {error}')
                    active.pop(target.name, None)
        while active:
            now = clock()
            if stop_at is not None and now >= stop_at:
                break
            due_at = min(next_due[name] for name in active)
            if due_at > now:
                wait = due_at - now
                if stop_at is not None:
                    wait = min(wait, stop_at - now)
                sleep(wait)
                continue
            for name, target in list(active.items()):
                if next_due[name] > now:
                    continue
                try:
                    payload = target.render()
                    if not target.driver.send(name, payload):
                        raise RuntimeError('output was not delivered')
                    target.status.frame_count += 1
                except (OSError, RuntimeError, TypeError, ValueError) as error:
                    _record_failure(target, f'frame failed: {error}')
                frame_period = 1 / target.fps
                next_due[name] += frame_period
                while next_due[name] <= now:
                    next_due[name] += frame_period
    finally:
        for driver in opened:
            driver_targets = targets_by_driver[id(driver)]
            try:
                driver.blackout()
            except (OSError, RuntimeError, ValueError) as error:
                for target in driver_targets:
                    _record_failure(target, f'blackout failed: {error}')
            try:
                driver.close()
            except (OSError, RuntimeError, ValueError) as error:
                for target in driver_targets:
                    _record_failure(target, f'close failed: {error}')
        for target in runtime.targets:
            target.status.state = 'failed' if target.status.failure_count else 'stopped'
    return InstallationStatus(
        targets={target.name: target.status for target in runtime.targets}
    )


def run_installation_command(config: InstallationCommandConfig) -> int:
    installation = load_installation(config.config)
    runtime = build_runtime(installation)
    try:
        status = run_runtime(runtime, duration=config.duration)
    except KeyboardInterrupt:
        LOGGER.info('[installation] Interrupted.')
        return 0
    for name, target in status.targets.items():
        message = (
            f'[installation] {name}: {target.frame_count} frames, '
            f'{target.failure_count} failures'
        )
        if target.last_error is None:
            LOGGER.info(message)
        else:
            LOGGER.error(f'{message}; last error: {target.last_error}')
    return 0 if status.successful else 1


def _validate_installation(config: InstallationFile) -> None:
    if not config.run:
        raise ValueError('installation requires at least one run target')
    target_names = set(config.twinkly_targets) | set(config.dmx_targets)
    duplicates = set(config.twinkly_targets).intersection(config.dmx_targets)
    if duplicates:
        raise ValueError(f'duplicate target name {min(duplicates)!r}')
    for name, run_spec in config.run.items():
        if name not in target_names:
            raise ValueError(f'run target {name!r} is not configured')
        if run_spec.program not in config.programs:
            raise ValueError(
                f'run target {name!r} names unknown program {run_spec.program!r}'
            )
        program = config.programs[run_spec.program]
        if name in config.twinkly_targets and not isinstance(program, PixelProgramSpec):
            raise ValueError(f'Twinkly target {name!r} requires a pixel program')
        if name in config.dmx_targets and not isinstance(program, DmxProgramSpec):
            raise ValueError(f'DMX target {name!r} requires a DMX program')
    if config.dmx_targets and config.artnet_endpoint is None:
        raise ValueError('DMX targets require an Art-Net endpoint')
    dmx.render_universes(
        [
            dmx.InstrumentOutput(instrument=instrument, values=dmx.DmxValues())
            for instrument in config.dmx_targets.values()
        ]
    )


def _record_failure(target: InstallationTarget, message: str) -> None:
    target.status.state = 'failed'
    target.status.failure_count += 1
    target.status.last_error = message
    LOGGER.error(f'[installation] {target.name}: {message}')


def _table(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError(f'{name} must be a table')
    return cast(dict[str, object], value)
