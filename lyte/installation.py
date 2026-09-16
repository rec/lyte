"""Selectable Twinkly animation installations."""

from __future__ import annotations

import re
import socket
import threading
import time
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from math import isfinite
from pathlib import Path
from typing import Annotated, Literal

import mido
import numpy as np
import tyro
from numpy.typing import NDArray
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    model_validator,
)
from reccy.protocol import ipc, rpc
from reccy.reccy import Reccy, ReccyStatus
from reccy.runtime import logging
from reccy.services import controller
from ufor import library_files
from ufor.library import Library
from ufor.lights import Interpretation

from . import animation, rendering, runtime_control, service, show
from .midi import MidiIn, MidiInput, input_messages, open_input
from .retry import RetryConfig
from .twinkly import diagnostic, discovery, realtime, session, track
from .twinkly.client import TwinklyClient

LOGGER = logging.get_logger(__name__)
_STRING_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]*\Z')
_GESTALT_FIELDS = (
    'device_name',
    'product_name',
    'product_code',
    'hardware_id',
    'firmware_family',
    'led_profile',
)


@dataclass(frozen=True)
class InstallationCommandConfig:
    action: Annotated[
        Literal['run', 'install', 'uninstall', 'start', 'stop', 'restart', 'status'],
        tyro.conf.Positional,
    ] = 'run'
    config: Annotated[Path, tyro.conf.Positional] = Path('installation.toml')
    duration: float | None = None


class InstallationFileError(ValueError):
    pass


class AmbiguousAssignmentError(InstallationFileError):
    pass


class InstallationDefinition(BaseModel, frozen=True):
    model_config = ConfigDict(extra='forbid')


class TwinklySelector(InstallationDefinition, frozen=True):
    device_name: str | None = None
    product_name: str | None = None
    product_code: str | None = None
    hardware_id: str | None = None
    firmware_family: str | None = None
    led_profile: str | None = None

    def matches(self, device: diagnostic.TwinklyDeviceInfo) -> bool:
        return all(
            value is None
            or (candidate is not None and value.casefold() in candidate.casefold())
            for field in _GESTALT_FIELDS
            for value, candidate in [(getattr(self, field), getattr(device, field))]
        )


class ParameterControl(InstallationDefinition, frozen=True):
    source: Literal['gate', 'note', 'velocity', 'breath', 'pitch_bend']
    parameter: str = Field(min_length=1)
    output: list[float] | None = None
    values: list[float] = Field(default_factory=list)

    @model_validator(mode='after')
    def mapping(self) -> ParameterControl:
        if self.output is not None and len(self.output) != 2:
            raise ValueError('control output must contain minimum and maximum')
        if self.values and self.source != 'note':
            raise ValueError('control value tables require the note source')
        if self.values and self.output is not None:
            raise ValueError('control cannot define both output and values')
        return self

    def map(self, performance: runtime_control.MidiPerformance) -> float:
        value = performance.value(self.source)
        if self.values:
            return self.values[int(value) % len(self.values)]
        if self.output is None:
            return value
        minimum, maximum = _CONTROL_RANGES[self.source]
        progress = (value - minimum) / (maximum - minimum)
        return self.output[0] + progress * (self.output[1] - self.output[0])


class AnimationDefaults(InstallationDefinition, frozen=True):
    activation: Literal['always', 'note'] = 'always'
    controls: list[ParameterControl] = Field(default_factory=list)


class BoundAnimation(InstallationDefinition, frozen=True):
    selector: str = Field(min_length=1)
    outputs: dict[str, str] = Field(min_length=1)
    activation: Literal['always', 'note'] = 'always'
    controls: list[ParameterControl] = Field(default_factory=list)

    @model_validator(mode='after')
    def distinct_controls(self) -> BoundAnimation:
        parameters = [c.parameter for c in self.controls]
        if len(parameters) != len(set(parameters)):
            raise ValueError('animation controls must target distinct parameters')
        return self


class InstallationFile(InstallationDefinition, frozen=True):
    library_config: Path | None = None
    twinkly: dict[str, TwinklySelector] = Field(min_length=1)
    animation_defaults: AnimationDefaults = Field(default_factory=AnimationDefaults)
    animations: dict[str, BoundAnimation] = Field(min_length=1)
    initial_animation: str
    fps: float = Field(default=30.0, gt=0)
    timeout: float = Field(default=5.0, gt=0)
    attempts: int = Field(default=10, gt=0)
    retry_delay: float = Field(default=0.5, ge=0)
    retry_backoff: float = Field(default=2.0, ge=1)
    discovery_timeout: float = Field(default=5.0, gt=0)
    startup_timeout: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    midi: MidiIn | None = None

    @model_validator(mode='after')
    def controls_require_midi(self) -> InstallationFile:
        animations = {
            name: animation.model_copy(
                update={
                    **(
                        {'activation': self.animation_defaults.activation}
                        if 'activation' not in animation.model_fields_set
                        else {}
                    ),
                    **(
                        {'controls': self.animation_defaults.controls}
                        if 'controls' not in animation.model_fields_set
                        else {}
                    ),
                }
            )
            for name, animation in self.animations.items()
        }
        object.__setattr__(self, 'animations', animations)
        if self.midi is None and any(
            a.activation == 'note' or a.controls for a in animations.values()
        ):
            raise ValueError('controlled animations require MIDI configuration')
        return self


@dataclass(frozen=True)
class OutputExpression:
    members: list[str]
    operator: Literal['single', 'concat', 'mirror']


@dataclass(frozen=True)
class DiscoveredTwinkly:
    host: str
    device: diagnostic.TwinklyDeviceInfo


@dataclass(frozen=True)
class TwinklyAssignment:
    name: str
    host: str
    device: diagnostic.TwinklyDeviceInfo


class StringStatus(BaseModel):
    state: str = 'pending'
    host: str | None = None
    mac: str | None = None
    led_count: int | None = None
    frame_count: int = 0
    failure_count: int = 0
    last_error: str | None = None


class InstallationStatus(ReccyStatus):
    active_animation: str | None = None
    queued_animation: str | None = None
    blackout: bool = False
    strings: dict[str, StringStatus] = Field(default_factory=dict)
    bindings: dict[str, str] = Field(default_factory=dict)
    midi_connected: bool = False
    midi_error: str | None = None
    note: int | None = None
    breath: int | None = None
    pitch_bend: int | None = None
    queued_test: runtime_control.LightTestCommand | None = None
    active_test: runtime_control.LightTestCommand | None = None


def parse_output_expression(value: str, strings: Iterable[str]) -> OutputExpression:
    known = set(strings)
    if not value or value != value.strip():
        raise ValueError(
            'output expression must not have leading or trailing whitespace'
        )
    plus = '+' in value
    star = '*' in value
    if plus and star:
        raise ValueError('output expression cannot mix + and *')
    if plus:
        members = value.split(' + ')
        operator: Literal['single', 'concat', 'mirror'] = 'concat'
    elif star:
        members = value.split(' * ')
        operator = 'mirror'
    else:
        members = [value]
        operator = 'single'
    if len(members) != len(set(members)):
        raise ValueError('output expression cannot name a string more than once')
    if any(not _STRING_NAME.fullmatch(member) for member in members):
        raise ValueError('output expression must use spaces around + or *')
    unknown = sorted(set(members) - known)
    if unknown:
        raise ValueError(f'output expression names unknown string {unknown[0]!r}')
    return OutputExpression(members, operator)


def assign_twinkly_devices(
    selectors: dict[str, TwinklySelector], devices: list[DiscoveredTwinkly]
) -> dict[str, DiscoveredTwinkly]:
    matches = {
        name: [device for device in devices if selector.matches(device.device)]
        for name, selector in selectors.items()
    }
    solutions: list[dict[str, DiscoveredTwinkly]] = []

    def search(remaining: list[str], chosen: dict[str, DiscoveredTwinkly]) -> None:
        if not remaining:
            solutions.append(chosen)
            return
        name = min(remaining, key=lambda item: len(matches[item]))
        for device in matches[name]:
            if device not in chosen.values():
                search(
                    [item for item in remaining if item != name],
                    chosen | {name: device},
                )

    search(list(selectors), {})
    if len(solutions) != 1:
        if not solutions:
            unmatched = [name for name, value in matches.items() if not value]
            detail = ', '.join(unmatched) if unmatched else 'selectors'
            raise InstallationFileError(f'could not assign Twinkly strings: {detail}')
        raise AmbiguousAssignmentError('Twinkly device assignment is ambiguous')
    return solutions[0]


class TwinklyOutput:
    def __init__(self, assignment: TwinklyAssignment, config: InstallationFile) -> None:
        self.assignment = assignment
        self.status = StringStatus(host=assignment.host, mac=assignment.device.mac)
        client = TwinklyClient(host=assignment.host, timeout=config.timeout)
        self.track = track.TwinklyTrack(
            client=client,
            retry=RetryConfig(
                attempts=config.attempts,
                delay=config.retry_delay,
                backoff=config.retry_backoff,
            ),
            host=assignment.host,
            configured_host=None,
            discovery_timeout=config.discovery_timeout,
            device=animation.Device(led_count=1),
            expected_mac=assignment.device.mac,
            on_connection_state=self._connection_state,
            on_device_connected=self._connected,
            on_frame_sent=self._sent,
            on_output_failure=self._failed,
        )
        self.socket: socket.socket | None = None

    @property
    def led_count(self) -> int:
        return self.track.device.led_count

    def open(self) -> bool:
        if not self.track.prepare():
            self.status.state = 'failed'
            return False
        self.socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )
        self.status.state = 'streaming'
        self.status.led_count = self.led_count
        return True

    def send(self, animation_name: str, frame: NDArray[np.uint8]) -> bool:
        if self.socket is None:
            raise RuntimeError('Twinkly output is not open')
        sent = self.track.send_frame(animation_name, frame, self.socket)
        self.status.led_count = self.led_count
        return sent

    def close(self) -> None:
        try:
            self.track.close()
        finally:
            if self.socket is not None:
                self.socket.close()
                self.socket = None
            if self.status.state != 'failed':
                self.status.state = 'stopped'

    def _connected(self, host: str, mac: str | None) -> None:
        self.status.host = host
        self.status.mac = mac
        self.status.led_count = self.led_count

    def _connection_state(self, state: realtime.PlaybackConnectionState) -> None:
        self.status.state = state

    def _sent(self) -> None:
        self.status.frame_count += 1
        self.status.last_error = None

    def _failed(self, message: str) -> None:
        self.record_failure(message)

    def record_failure(self, message: str) -> None:
        self.status.state = 'failed'
        self.status.failure_count += 1
        self.status.last_error = message


@dataclass
class PreparedBinding:
    output_name: str
    expression: OutputExpression
    prepared: rendering.PreparedAnimation
    frame: NDArray[np.uint8] | None = None


class ActiveAnimation:
    def __init__(
        self,
        name: str,
        definition: BoundAnimation,
        library: Library,
        outputs: dict[str, TwinklyOutput],
    ) -> None:
        self.name = name
        self.definition = definition
        self.library = library
        self.outputs = outputs
        self.performance = runtime_control.MidiPerformance()
        self.bindings: list[PreparedBinding] = []
        self._prepare()

    def _prepare(self) -> None:
        self.started_at: Fraction | None = None
        self.bindings = [
            PreparedBinding(
                output_name,
                parse_output_expression(expression, self.outputs),
                _prepare_output(self.library, self.definition.selector, output_name),
            )
            for output_name, expression in self.definition.outputs.items()
        ]

    def apply_performance(
        self, performance: runtime_control.MidiPerformance, *, restart: bool = False
    ) -> None:
        self.performance = performance.model_copy(deep=True)
        if restart:
            self._prepare()
        values = {c.parameter: c.map(performance) for c in self.definition.controls}
        if values:
            for binding in self.bindings:
                binding.prepared.set_parameters(values)

    def render(self, now: float) -> list[tuple[str, NDArray[np.uint8]]]:
        at = Fraction(str(now))
        if self.started_at is None:
            self.started_at = at
        elapsed = at - self.started_at
        frames: list[tuple[str, NDArray[np.uint8]]] = []
        for binding in self.bindings:
            if (
                self.definition.activation == 'always'
                or self.performance.note is not None
            ):
                tick = int(elapsed * binding.prepared.rate)
                while binding.prepared.tick <= tick:
                    binding.frame = binding.prepared.byte_frame(wired=True)
                assert binding.frame is not None
                source = binding.frame
            else:
                source = np.zeros(
                    (len(binding.prepared.output.layout.lights), 3), dtype=np.uint8
                )
            frames.extend(
                distribute_frame(
                    source,
                    binding.expression,
                    {name: output.led_count for name, output in self.outputs.items()},
                )
            )
        return frames


def distribute_frame(
    source: NDArray[np.uint8],
    expression: OutputExpression,
    led_counts: dict[str, int],
) -> list[tuple[str, NDArray[np.uint8]]]:
    if expression.operator == 'mirror':
        return [
            (name, animation.scale_byte_rgb_frame(source, led_counts[name]))
            for name in expression.members
        ]
    total = sum(led_counts[name] for name in expression.members)
    scaled = animation.scale_byte_rgb_frame(source, total)
    frames: list[tuple[str, NDArray[np.uint8]]] = []
    start = 0
    for name in expression.members:
        end = start + led_counts[name]
        frames.append((name, np.ascontiguousarray(scaled[start:end])))
        start = end
    return frames


class InstallationService(Reccy):
    name = 'lyte'
    service_spec = service.LYTE_SERVICE
    status_model = InstallationStatus
    rpc_enabled = True

    config: InstallationFile
    library: Library
    outputs: dict[str, TwinklyOutput]

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _active: ActiveAnimation | None = PrivateAttr(default=None)
    _queued_name: str | None = PrivateAttr(default=None)
    _performance: runtime_control.MidiPerformance = PrivateAttr(
        default_factory=runtime_control.MidiPerformance
    )
    _midi_port: MidiInput | None = PrivateAttr(default=None)
    _next_midi_open_at: float = PrivateAttr(default=0.0)
    _midi_connected: bool = PrivateAttr(default=False)
    _midi_error: str | None = PrivateAttr(default=None)
    _selected_test: runtime_control.LightTestCommand | None = PrivateAttr(default=None)
    _active_test: runtime_control.ActiveLightTest | None = PrivateAttr(default=None)
    _blackout: bool = PrivateAttr(default=False)
    _stop_requested: threading.Event = PrivateAttr(default_factory=threading.Event)
    _lock: threading.RLock = PrivateAttr(default_factory=threading.RLock)

    def rpc_response(self, request: rpc.Request) -> rpc.Result:
        with self._lock:
            if request.command == 'status':
                return self.status_snapshot().model_dump(mode='json')
            if request.command == 'select_animation':
                name = request.params.get('name')
                if not isinstance(name, str) or name not in self.config.animations:
                    return ipc.Error(
                        type='error',
                        message='select_animation requires a configured animation name',
                    )
                self._queued_name = name
                self.publish_status()
                return {'state': 'queued', 'name': name}
            if request.command == 'test':
                if self._blackout:
                    return ipc.Error(
                        type='error',
                        message='select an animation before testing during blackout',
                    )
                test = runtime_control.light_test_command(request.params)
                if isinstance(test, ipc.Error):
                    return test
                self._selected_test = test
                self.publish_status()
                return {
                    'state': 'queued',
                    'level': test.level,
                    'duration': test.duration,
                }
            if request.command == 'blackout':
                self._blackout = True
                self._queued_name = None
                self._selected_test = None
                self._active_test = None
                self.publish_status()
                return 'ok'
            if request.command == 'stop':
                self._stop_requested.set()
                return 'ok'
        return ipc.Error(type='error', message=f'unknown command {request.command}')

    def status_snapshot(self) -> InstallationStatus:
        with self._lock:
            active = None if self._active is None else self._active.name
            bindings = (
                {}
                if self._active is None
                else self.config.animations[self._active.name].outputs.copy()
            )
            return InstallationStatus(
                running=self._started,
                errors=self._errors.copy(),
                active_animation=active,
                queued_animation=self._queued_name,
                blackout=self._blackout,
                strings={name: output.status for name, output in self.outputs.items()},
                bindings=bindings,
                midi_connected=self._midi_connected,
                midi_error=self._midi_error,
                note=self._performance.note,
                breath=self._performance.breath,
                pitch_bend=self._performance.pitch,
                queued_test=self._selected_test,
                active_test=(
                    None if self._active_test is None else self._active_test.command
                ),
            )

    def run(self, duration: float | None = None) -> int:
        if duration is not None and duration <= 0:
            raise ValueError('duration must be greater than zero')
        self.start()
        opened: list[TwinklyOutput] = []
        try:
            for output in self.outputs.values():
                if output.open():
                    opened.append(output)
                else:
                    self.publish_error(
                        f'{output.assignment.name}: could not open output'
                    )
            if len(opened) != len(self.outputs):
                return 1
            self._select(self.config.initial_animation)
            next_frame = time.monotonic()
            deadline = None if duration is None else next_frame + duration
            while not self._stop_requested.is_set():
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    break
                if now < next_frame:
                    time.sleep(next_frame - now)
                    continue
                self._process_midi(now)
                assert self._active is not None
                frames = self.render(now)
                for name, frame in frames:
                    output = self.outputs[name]
                    try:
                        if not output.send(self._active.name, frame):
                            self.publish_status()
                    except (OSError, RuntimeError, ValueError) as error:
                        output.record_failure(str(error))
                        self.publish_error(f'{name}: output failed: {error}')
                next_frame += 1 / self.config.fps
                while next_frame <= now:
                    next_frame += 1 / self.config.fps
        except KeyboardInterrupt:
            LOGGER.info('[installation] Interrupted.')
        finally:
            self._close_midi()
            for output in opened:
                output.close()
            self.close()
        return 0

    def render(self, now: float) -> list[tuple[str, NDArray[np.uint8]]]:
        with self._lock:
            self._apply_queued_selection()
            if self._blackout:
                return [
                    (n, np.zeros((o.led_count, 3), dtype=np.uint8))
                    for n, o in self.outputs.items()
                ]
            self._apply_queued_test(now)
            assert self._active is not None
            return self._test_frames(now) or self._active.render(now)

    def _apply_queued_selection(self) -> None:
        with self._lock:
            if self._queued_name is None:
                return
            name = self._queued_name
            self._queued_name = None
            self._select(name)

    def _select(self, name: str) -> None:
        active = ActiveAnimation(
            name, self.config.animations[name], self.library, self.outputs
        )
        with self._lock:
            self._active = active
            active.apply_performance(self._performance)
            self._blackout = False
            self._active_test = None
        LOGGER.info(f'[installation] Selected animation: {name}')
        self.publish_status()

    def _process_midi(self, now: float) -> None:
        if self.config.midi is None:
            return
        if self._midi_port is None:
            if now < self._next_midi_open_at:
                return
            try:
                self._midi_port = open_input(self.config.midi)
            except (OSError, ValueError) as error:
                self._next_midi_open_at = now + 1
                self._set_midi_status(False, str(error))
                return
            self._set_midi_status(True, None)
        try:
            for message in input_messages(self._midi_port, self.config.midi):
                self._receive_midi(message)
        except (OSError, ValueError) as error:
            self._close_midi()
            self._next_midi_open_at = now + 1
            self._performance = runtime_control.MidiPerformance()
            if self._active is not None:
                self._active.apply_performance(self._performance)
            self._set_midi_status(False, str(error))

    def _receive_midi(self, message: mido.Message) -> None:
        if message.type == 'program_change':
            names = list(self.config.animations)
            current = self._active.name if self._active is not None else names[0]
            self._queued_name = names[(names.index(current) + 1) % len(names)]
            self.publish_status()
            return
        restart = message.type == 'note_on' and bool(message.velocity)
        self._performance.receive(message)
        if self._active is not None:
            self._active.apply_performance(self._performance, restart=restart)
        self.publish_status()

    def _set_midi_status(self, connected: bool, error: str | None) -> None:
        changed = self._midi_connected != connected or self._midi_error != error
        self._midi_connected = connected
        self._midi_error = error
        if changed:
            self.publish_status()

    def _close_midi(self) -> None:
        if self._midi_port is None:
            return
        try:
            self._midi_port.close()
        except (OSError, ValueError) as error:
            LOGGER.warning(f'[warn] Could not close MIDI input: {error}')
        self._midi_port = None

    def _apply_queued_test(self, now: float) -> None:
        if self._selected_test is None:
            return
        self._active_test = runtime_control.ActiveLightTest(
            command=self._selected_test, started_at=now
        )
        self._selected_test = None
        self.publish_status()

    def _test_frames(self, now: float) -> list[tuple[str, NDArray[np.uint8]]]:
        if self._active_test is None:
            return []
        frames = []
        for name, output in self.outputs.items():
            frame = self._active_test.render(
                animation.Device(led_count=output.led_count), now
            )
            if frame is None:
                self._active_test = None
                self.publish_status()
                return []
            frames.append((name, frame))
        return frames


def load_installation(path: Path) -> InstallationFile:
    try:
        with path.open('rb') as source:
            config = parse_installation(tomllib.load(source))
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
    allowed = {
        'library_config',
        'twinkly',
        'animation_defaults',
        'animations',
        'initial_animation',
        'fps',
        'timeout',
        'attempts',
        'retry_delay',
        'retry_backoff',
        'discovery_timeout',
        'startup_timeout',
        'midi',
    }
    if unknown := sorted(set(data) - allowed):
        raise ValueError(f'unknown top-level sections: {", ".join(unknown)}')
    config = InstallationFile.model_validate(data)
    _validate_installation(config)
    return config


def discover_assignments(config: InstallationFile) -> dict[str, TwinklyAssignment]:
    deadline = time.monotonic() + config.startup_timeout

    def remaining() -> float:
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise InstallationFileError(
                f'device discovery exceeded startup_timeout={config.startup_timeout:g}s'
            )
        return seconds

    retry = RetryConfig(
        attempts=config.attempts,
        delay=config.retry_delay,
        backoff=config.retry_backoff,
    )
    while True:
        devices: list[DiscoveredTwinkly] = []
        for found in discovery.discover(min(config.discovery_timeout, remaining())):
            client = TwinklyClient(
                host=found.ip_address, timeout=min(config.timeout, remaining())
            )
            gestalt = session.read_gestalt(
                client, retry, f'GET gestalt on {found.ip_address}', deadline=deadline
            )
            if gestalt is None:
                LOGGER.warning(
                    f'[waiting] Could not read gestalt from {found.ip_address}'
                )
                continue
            device = diagnostic.TwinklyDeviceInfo.from_gestalt(gestalt)
            devices.append(DiscoveredTwinkly(found.ip_address, device))
            LOGGER.info(f'[discovered] {found.ip_address}: {_describe_device(device)}')
        try:
            assignment = assign_twinkly_devices(config.twinkly, devices)
        except AmbiguousAssignmentError:
            raise
        except InstallationFileError as error:
            LOGGER.warning(f'[waiting] {error}')
            time.sleep(min(config.retry_delay, remaining()))
            continue
        remaining()
        return {
            name: TwinklyAssignment(name, found.host, found.device)
            for name, found in assignment.items()
        }


def build_service(
    config: InstallationFile,
    assignments: dict[str, TwinklyAssignment] | None = None,
) -> InstallationService:
    try:
        library = library_files.read_library(config.library_config)
    except (OSError, ValueError) as error:
        raise InstallationFileError(str(error)) from error
    show.log_diagnostics(library)
    for definition in config.animations.values():
        for output_name in definition.outputs:
            prepared = _prepare_output(library, definition.selector, output_name)
            for control in definition.controls:
                try:
                    contract = prepared.composition.parameter_contract(
                        prepared.composition.root, control.parameter
                    )
                    values = (
                        control.values
                        or control.output
                        or _CONTROL_RANGES[control.source]
                    )
                    original = prepared.composition.parts['root'].parameters.copy()
                    for value in values:
                        if (
                            not isfinite(value)
                            or not contract.minimum <= value <= contract.maximum
                        ):
                            raise ValueError(
                                f'mapped value {value} is outside '
                                f'{contract.minimum}..{contract.maximum}'
                            )
                        prepared.set_parameters({control.parameter: value})
                    prepared.set_parameters(original)
                except ValueError as error:
                    raise InstallationFileError(
                        f'{definition.selector}, output {output_name}, '
                        f'control {control.parameter}: {error}'
                    ) from error
    resolved = discover_assignments(config) if assignments is None else assignments
    if set(resolved) != set(config.twinkly):
        raise InstallationFileError(
            'Twinkly assignments do not match configured strings'
        )
    return InstallationService(
        config=config,
        library=library,
        outputs={
            name: TwinklyOutput(value, config) for name, value in resolved.items()
        },
    )


def run_installation_command(config: InstallationCommandConfig) -> int:
    if config.action == 'run':
        return build_service(load_installation(config.config)).run(config.duration)
    runtime = InstallationService.model_construct()
    if config.action == 'install':
        result = runtime.install_service(
            ['installation', 'run', str(config.config.resolve())]
        )
    elif config.action == 'status':
        result = runtime.service_status()
    else:
        result = getattr(runtime, f'{config.action}_service')()
    controller.print_service_status(service.LYTE_SERVICE.name, result)
    return 0 if result.running is not False else 1


def _prepare_output(
    library: Library, selector: str, output_name: str
) -> rendering.PreparedAnimation:
    try:
        prepared = show.prepare_library_animation(
            library, show.LightProgramSpec(selector=selector, output=output_name)
        )
    except ValueError as error:
        raise InstallationFileError(
            f'animation output {output_name!r}: {error}'
        ) from error
    if prepared.output.components != ['red', 'green', 'blue']:
        raise InstallationFileError(
            f'animation output {output_name!r} requires red, green, blue components'
        )
    if prepared.output.interpretation != Interpretation.drive:
        raise InstallationFileError(
            f'animation output {output_name!r} requires drive light values'
        )
    return prepared


def _validate_installation(config: InstallationFile) -> None:
    for name in config.twinkly:
        if not _STRING_NAME.fullmatch(name):
            raise ValueError(f'Twinkly string name {name!r} is not an identifier')
    for name, definition in config.animations.items():
        used: set[str] = set()
        for expression in definition.outputs.values():
            parsed = parse_output_expression(expression, config.twinkly)
            duplicate = used.intersection(parsed.members)
            if duplicate:
                raise ValueError(
                    f'animation {name!r} binds string {min(duplicate)!r} more than once'
                )
            used.update(parsed.members)
        missing = set(config.twinkly) - used
        if missing:
            raise ValueError(
                f'animation {name!r} does not bind string {min(missing)!r}'
            )
    if config.initial_animation not in config.animations:
        raise ValueError('initial_animation names an unknown animation')


_CONTROL_RANGES = {
    'gate': (0.0, 1.0),
    'note': (0.0, 127.0),
    'velocity': (0.0, 1.0),
    'breath': (0.0, 1.0),
    'pitch_bend': (-1.0, 1.0),
}


def _describe_device(device: diagnostic.TwinklyDeviceInfo) -> str:
    return (
        ' '.join(
            value
            for value in (device.device_name, device.product_name, device.product_code)
            if value is not None
        )
        or 'unnamed Twinkly'
    )
