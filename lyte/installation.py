"""Selectable Twinkly animation installations."""

from __future__ import annotations

import re
import socket
import threading
import time
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
import tyro
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError
from reccy.protocol import ipc, rpc
from reccy.reccy import Reccy, ReccyStatus
from reccy.runtime import logging
from ufor import library_files
from ufor.library import Library
from ufor.lights import Interpretation

from . import animation, rendering, show
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
    action: Annotated[Literal['run'], tyro.conf.Positional] = 'run'
    config: Annotated[Path, tyro.conf.Positional] = Path('installation.toml')
    duration: float | None = None


class InstallationFileError(ValueError):
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


class BoundAnimation(InstallationDefinition, frozen=True):
    selector: str = Field(min_length=1)
    outputs: dict[str, str] = Field(min_length=1)


class InstallationFile(InstallationDefinition, frozen=True):
    library_config: Path | None = None
    twinkly: dict[str, TwinklySelector] = Field(min_length=1)
    animations: dict[str, BoundAnimation] = Field(min_length=1)
    initial_animation: str
    fps: float = Field(default=30.0, gt=0)
    timeout: float = Field(default=5.0, gt=0)
    attempts: int = Field(default=10, gt=0)
    retry_delay: float = Field(default=0.5, ge=0)
    retry_backoff: float = Field(default=2.0, ge=1)
    discovery_timeout: float = Field(default=5.0, gt=0)


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
    strings: dict[str, StringStatus] = Field(default_factory=dict)
    bindings: dict[str, str] = Field(default_factory=dict)


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
        raise InstallationFileError('Twinkly device assignment is ambiguous')
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


class ActiveAnimation:
    def __init__(
        self,
        name: str,
        definition: BoundAnimation,
        library: Library,
        outputs: dict[str, TwinklyOutput],
    ) -> None:
        self.name = name
        self.outputs = outputs
        self.bindings = [
            PreparedBinding(
                output_name,
                parse_output_expression(expression, outputs),
                _prepare_output(library, definition.selector, output_name),
            )
            for output_name, expression in definition.outputs.items()
        ]

    def render(self) -> list[tuple[str, NDArray[np.uint8]]]:
        frames: list[tuple[str, NDArray[np.uint8]]] = []
        for binding in self.bindings:
            source = binding.prepared.byte_frame(wired=True)
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
    name = 'lyte-installation'
    status_model = InstallationStatus
    rpc_enabled = True

    config: InstallationFile
    library: Library
    outputs: dict[str, TwinklyOutput]

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _active: ActiveAnimation | None = PrivateAttr(default=None)
    _queued_name: str | None = PrivateAttr(default=None)
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
                strings={name: output.status for name, output in self.outputs.items()},
                bindings=bindings,
            )

    def run(self, duration: float | None = None) -> int:
        if duration is not None and duration <= 0:
            raise ValueError('duration must be greater than zero')
        self.start()
        opened: list[TwinklyOutput] = []
        deadline = None if duration is None else time.monotonic() + duration
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
            while not self._stop_requested.is_set():
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    break
                if now < next_frame:
                    time.sleep(next_frame - now)
                    continue
                self._apply_queued_selection()
                assert self._active is not None
                for name, frame in self._active.render():
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
            for output in opened:
                output.close()
            self.close()
        return 0

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
        LOGGER.info(f'[installation] Selected animation: {name}')
        self.publish_status()


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
        'animations',
        'initial_animation',
        'fps',
        'timeout',
        'attempts',
        'retry_delay',
        'retry_backoff',
        'discovery_timeout',
    }
    if unknown := sorted(set(data) - allowed):
        raise ValueError(f'unknown top-level sections: {", ".join(unknown)}')
    config = InstallationFile.model_validate(data)
    _validate_installation(config)
    return config


def discover_assignments(config: InstallationFile) -> dict[str, TwinklyAssignment]:
    retry = RetryConfig(
        attempts=config.attempts,
        delay=config.retry_delay,
        backoff=config.retry_backoff,
    )
    while True:
        devices: list[DiscoveredTwinkly] = []
        for found in discovery.discover(config.discovery_timeout):
            client = TwinklyClient(host=found.ip_address, timeout=config.timeout)
            gestalt = session.read_gestalt(
                client, retry, f'GET gestalt on {found.ip_address}'
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
        except InstallationFileError as error:
            LOGGER.warning(f'[waiting] {error}')
            time.sleep(config.retry_delay)
            continue
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
            _prepare_output(library, definition.selector, output_name)
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
    return build_service(load_installation(config.config)).run(config.duration)


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


def _describe_device(device: diagnostic.TwinklyDeviceInfo) -> str:
    return (
        ' '.join(
            value
            for value in (device.device_name, device.product_name, device.product_code)
            if value is not None
        )
        or 'unnamed Twinkly'
    )
