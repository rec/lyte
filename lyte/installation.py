"""Selectable Twinkly and WLED animation installations."""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
import tyro
from numpy.typing import NDArray
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
)
from reccy.errors import ReccyError
from reccy.protocol import ipc, rpc
from reccy.reccy import Reccy, ReccyStatus
from reccy.runtime import logging
from reccy.services import controller
from ufor.library import Library

from . import (
    animation,
    installation_config,
    installation_playback,
    runtime_control,
    service,
)
from .control_recording import ControlRecorder
from .metrics import DeliveryTiming, RenderCost
from .midi import MidiInput, input_messages, open_input
from .retry import RetryConfig
from .twinkly import diagnostic, discovery, realtime, session, track
from .twinkly.client import TwinklyClient
from .wled_output import WledDdpOutput

LOGGER = logging.get_logger(__name__)


@dataclass(frozen=True)
class InstallationCommandConfig:
    action: Annotated[
        Literal['run', 'install', 'uninstall', 'start', 'stop', 'restart', 'status'],
        tyro.conf.Positional,
    ] = 'run'
    config: Annotated[Path, tyro.conf.Positional] = Path('installation.toml')
    duration: float | None = None
    record_input: Path | None = None


class AmbiguousAssignmentError(installation_config.InstallationFileError):
    pass


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
    transport: Literal['twinkly', 'wled'] = 'twinkly'
    state: str = 'pending'
    host: str | None = None
    mac: str | None = None
    led_count: int | None = None
    frame_count: int = 0
    failure_count: int = 0
    last_error: str | None = None


class InstallationStatus(ReccyStatus):
    recording: bool = False
    recording_path: str | None = None
    recording_error: str | None = None
    render_error: str | None = None
    status_error: str | None = None
    master_level: float = 1
    transition_duration: float = 0
    outgoing_animation: str | None = None
    transition_from_snapshot: bool = False
    animations: list[str] = Field(default_factory=list)
    render_costs: dict[str, dict[str, RenderCost]] = Field(default_factory=dict)
    delivery: DeliveryTiming | None = None
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


def assign_twinkly_devices(
    selectors: dict[str, installation_config.TwinklySelector],
    devices: list[DiscoveredTwinkly],
) -> dict[str, DiscoveredTwinkly]:
    matches = {
        name: [device for device in devices if selector.matches(device.device)]
        for name, selector in selectors.items()
    }
    solutions: list[dict[str, DiscoveredTwinkly]] = []

    def search(remaining: list[str], chosen: dict[str, DiscoveredTwinkly]) -> None:
        if len(solutions) == 2:
            return
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
            raise installation_config.InstallationFileError(
                f'could not assign Twinkly strings: {detail}'
            )
        raise AmbiguousAssignmentError('Twinkly device assignment is ambiguous')
    return solutions[0]


class TwinklyOutput:
    def __init__(
        self,
        assignment: TwinklyAssignment,
        config: installation_config.InstallationFile,
    ) -> None:
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


class WledOutput:
    def __init__(self, target: installation_config.WledTarget, timeout: float) -> None:
        self.target = target
        self.timeout = timeout
        self.led_count = target.led_count
        self.status = StringStatus(
            transport='wled', host=target.host, led_count=target.led_count
        )
        self.output: WledDdpOutput | None = None

    def open(self) -> bool:
        # DDP has no handshake. Socket acquisition is retried by scheduled sends.
        self.status.state = 'ready'
        return True

    def send(self, animation_name: str, frame: NDArray[np.uint8]) -> bool:
        if self.output is None:
            self.output = WledDdpOutput(self.target.host, self.led_count)
            self.output.socket.settimeout(self.timeout)
        self.output.send(frame)
        self.status.state = 'sending (unconfirmed)'
        self.status.frame_count += 1
        self.status.last_error = None
        return True

    def record_failure(self, message: str) -> None:
        self.status.state = 'failed'
        self.status.failure_count += 1
        self.status.last_error = message

    def close(self) -> None:
        if self.output is not None:
            try:
                self.output.send(np.zeros((self.led_count, 3), dtype=np.uint8))
            except OSError as error:
                self.record_failure(str(error))
                LOGGER.warning(f'Could not send final WLED blackout: {error}')
            finally:
                self.output.close()
                self.output = None
        if self.status.state != 'failed':
            self.status.state = 'stopped'


class InstallationService(Reccy):
    name = 'lyte'
    service_spec = service.LYTE_SERVICE
    status_model = InstallationStatus
    rpc_enabled = True

    config: installation_config.InstallationFile
    library: Library
    outputs: dict[str, TwinklyOutput | WledOutput]

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _midi_port: MidiInput | None = PrivateAttr(default=None)
    _next_midi_open_at: float = PrivateAttr(default=0.0)
    _midi_connected: bool = PrivateAttr(default=False)
    _midi_error: str | None = PrivateAttr(default=None)
    _stop_requested: threading.Event = PrivateAttr(default_factory=threading.Event)
    _lock: threading.RLock = PrivateAttr(default_factory=threading.RLock)
    _delivery: DeliveryTiming | None = PrivateAttr(default=None)
    _render_error: str | None = PrivateAttr(default=None)
    _status_error: str | None = PrivateAttr(default=None)

    def publish_status(self) -> None:
        try:
            super().publish_status()
        except (OSError, ReccyError, ValueError) as error:
            if self._status_error != str(error):
                LOGGER.error(f'Could not publish installation status: {error}')
            self._status_error = str(error)
        else:
            self._status_error = None

    @cached_property
    def playback(self) -> installation_playback.InstallationPlayback:
        return installation_playback.InstallationPlayback(
            self.config, self.library, {n: o.led_count for n, o in self.outputs.items()}
        )

    def rpc_response(self, request: rpc.Request) -> rpc.Result:
        with self._lock:
            if request.command == 'status':
                return self.status_snapshot().model_dump(mode='json')
            if request.command == 'stop':
                self._stop_requested.set()
                return 'ok'
            result = self.playback.command(request.command, request.params)
            if not isinstance(result, ipc.Error):
                self.publish_status()
            return result

    def status_snapshot(self) -> InstallationStatus:
        with self._lock:
            active = None if self.playback.active is None else self.playback.active.name
            bindings = (
                {}
                if self.playback.active is None
                else self.config.animations[self.playback.active.name].outputs.copy()
            )
            return InstallationStatus(
                recording=self.playback.recorder is not None
                and self.playback.recorder.stream is not None,
                recording_path=str(self.playback.recorder.path)
                if self.playback.recorder
                else None,
                recording_error=self.playback.recorder.error
                if self.playback.recorder
                else None,
                render_error=self._render_error,
                status_error=self._status_error,
                master_level=self.playback.master_level,
                transition_duration=self.playback.transition_duration,
                outgoing_animation=self.playback.outgoing.name
                if self.playback.outgoing
                else None,
                transition_from_snapshot=self.playback.transition_snapshot is not None,
                animations=list(self.config.animations),
                render_costs=self.playback.render_costs,
                delivery=self._delivery,
                running=self._started,
                errors=self._errors.copy(),
                active_animation=active,
                queued_animation=self.playback.queued_name,
                blackout=self.playback.blackout,
                strings={name: output.status for name, output in self.outputs.items()},
                bindings=bindings,
                midi_connected=self._midi_connected,
                midi_error=self._midi_error,
                note=self.playback.performance.note,
                breath=self.playback.performance.breath,
                pitch_bend=self.playback.performance.pitch,
                queued_test=self.playback.selected_test,
                active_test=(
                    None
                    if self.playback.active_test is None
                    else self.playback.active_test.command
                ),
            )

    def run(
        self, duration: float | None = None, record_input: Path | None = None
    ) -> int:
        if duration is not None and duration <= 0:
            raise ValueError('duration must be greater than zero')
        self.playback.select(self.config.initial_animation)
        if record_input is not None:
            self.playback.recorder = ControlRecorder(record_input)
            self.playback.recorder.start(self.config, self.library)
        opened: list[TwinklyOutput | WledOutput] = []
        try:
            self.start()
            for name, output in self.outputs.items():
                if output.open():
                    opened.append(output)
                else:
                    self.publish_error(f'{name}: could not open output')
            if len(opened) != len(self.outputs):
                return 1
            self.publish_status()
            next_frame = time.monotonic()
            deadline = None if duration is None else next_frame + duration
            self._delivery = DeliveryTiming(
                scheduled_interval_seconds=1 / self.config.fps
            )
            previous_frame: float | None = None
            while not self._stop_requested.is_set():
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    break
                if now < next_frame:
                    time.sleep(next_frame - now)
                    continue
                self._process_midi(now)
                self._delivery.record(
                    None if previous_frame is None else now - previous_frame,
                    now - next_frame,
                )
                previous_frame = now
                assert self.playback.active is not None
                previous_error = self._render_error
                try:
                    frames = self.render(now)
                except (OSError, RuntimeError, ValueError) as error:
                    if self._render_error != str(error):
                        LOGGER.error(f'Animation render failed; continuing: {error}')
                    self._render_error = str(error)
                    frames = []
                else:
                    self._render_error = None
                if self._render_error != previous_error:
                    self.publish_status()
                for name, frame in frames:
                    output = self.outputs[name]
                    started = time.perf_counter()
                    try:
                        if not output.send(self.playback.active.name, frame):
                            self._delivery.output_failures += 1
                            self.publish_status()
                    except (OSError, RuntimeError, ValueError) as error:
                        self._delivery.output_failures += 1
                        output.record_failure(str(error))
                        self.publish_error(f'{name}: output failed: {error}')
                    finally:
                        self._delivery.output_seconds += time.perf_counter() - started
                next_frame += 1 / self.config.fps
                while next_frame <= now:
                    next_frame += 1 / self.config.fps
        except KeyboardInterrupt:
            LOGGER.info('[installation] Interrupted.')
        finally:
            if self.playback.recorder is not None:
                self.playback.recorder.close()
            self._close_midi()
            for output in opened:
                output.close()
            self.close()
        return 0

    def render(self, now: float) -> list[tuple[str, NDArray[np.uint8]]]:
        with self._lock:
            self.playback.led_counts.update(
                {n: o.led_count for n, o in self.outputs.items()}
            )
            revision = self.playback.revision
            recording_error = (
                self.playback.recorder.error if self.playback.recorder else None
            )
            frames = self.playback.render(now)
            if self.playback.revision != revision or (
                self.playback.recorder is not None
                and self.playback.recorder.error != recording_error
            ):
                self.publish_status()
            return frames

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
                with self._lock:
                    self.playback.receive_midi(message)
                    self.publish_status()
        except (OSError, ValueError) as error:
            self._close_midi()
            self._next_midi_open_at = now + 1
            with self._lock:
                self.playback.reset_midi()
            self._set_midi_status(False, str(error))

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


def discover_assignments(
    config: installation_config.InstallationFile,
) -> dict[str, TwinklyAssignment]:
    if not config.twinkly:
        return {}
    deadline = time.monotonic() + config.startup_timeout

    def remaining() -> float:
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise installation_config.InstallationFileError(
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
        except installation_config.InstallationFileError as error:
            LOGGER.warning(f'[waiting] {error}')
            time.sleep(min(config.retry_delay, remaining()))
            continue
        remaining()
        return {
            name: TwinklyAssignment(name, found.host, found.device)
            for name, found in assignment.items()
        }


def build_service(
    config: installation_config.InstallationFile,
    assignments: dict[str, TwinklyAssignment] | None = None,
) -> InstallationService:
    library = installation_playback.load_library(config)
    resolved = discover_assignments(config) if assignments is None else assignments
    if set(resolved) != set(config.twinkly):
        raise installation_config.InstallationFileError(
            'Twinkly assignments do not match configured strings'
        )
    return InstallationService(
        config=config,
        library=library,
        outputs={
            **{n: TwinklyOutput(v, config) for n, v in resolved.items()},
            **{n: WledOutput(v, config.timeout) for n, v in config.wled.items()},
        },
    )


def run_installation_command(config: InstallationCommandConfig) -> int:
    if config.record_input is not None and config.action != 'run':
        raise ValueError('--record-input is only available with installation run')
    if config.action == 'run':
        return build_service(installation_config.load_installation(config.config)).run(
            config.duration, config.record_input
        )
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


def _describe_device(device: diagnostic.TwinklyDeviceInfo) -> str:
    return (
        ' '.join(
            value
            for value in (device.device_name, device.product_name, device.product_code)
            if value is not None
        )
        or 'unnamed Twinkly'
    )
