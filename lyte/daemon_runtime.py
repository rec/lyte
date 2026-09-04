"""MIDI state and patch selection for the Lyte daemon."""

from __future__ import annotations

import datetime
import enum
import threading
import time
from math import isfinite
from pathlib import Path

import mido
import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, PrivateAttr, SkipValidation
from reccy import ipc, logging, rpc, service_spec
from reccy.reccy import Reccy, ReccyStatus

from . import animation, midi, patches
from .daemon_config import DaemonProject
from .retry import RetryConfig
from .twinkly import realtime, track
from .twinkly.client import TwinklyClient

LYTE_SERVICE = service_spec.load(Path(__file__).with_name('service.toml'))
LOGGER = logging.get_logger(__name__)


class DaemonState(enum.StrEnum):
    STARTING = enum.auto()
    CONNECTING = enum.auto()
    STREAMING = enum.auto()
    RECOVERING = enum.auto()
    STOPPING = enum.auto()
    STOPPED = enum.auto()
    UNKNOWN = enum.auto()


class LyteMidiStatus(ReccyStatus):
    state: DaemonState = DaemonState.STARTING
    patch: str | None = None
    host: str | None = None
    device_mac: str | None = None
    planned_led_count: int | None = None
    actual_led_count: int | None = None
    last_output_contact: datetime.datetime | None = None
    midi_connected: bool = False
    midi_error: str | None = None
    output_state: realtime.PlaybackConnectionState = (
        realtime.PlaybackConnectionState.UNKNOWN
    )
    recovery_count: int = 0
    queued_test: LightTestCommand | None = None
    active_test: LightTestCommand | None = None
    frame_send_count: int = 0
    last_frame_sent_at: datetime.datetime | None = None
    output_error: str | None = None
    output_failure_count: int = 0
    render_error: str | None = None
    render_error_count: int = 0
    last_failure: str | None = None
    last_failure_at: datetime.datetime | None = None
    failure_count: int = 0
    selection_generation: int = 0
    applied_selection_generation: int = 0


class LightTestCommand(BaseModel, frozen=True):
    level: float = 50.0
    duration: float = 2.0


class ActiveLightTest(BaseModel, frozen=True):
    command: LightTestCommand
    started_at: float

    def render(self, device: animation.Device, now: float) -> NDArray[np.uint8] | None:
        elapsed = now - self.started_at
        if elapsed > self.command.duration:
            return None
        half_duration = self.command.duration / 2
        if elapsed <= half_duration:
            fraction = elapsed / half_duration
        else:
            fraction = (self.command.duration - elapsed) / half_duration
        level = round(255 * self.command.level / 100 * max(0.0, fraction))
        return np.full((device.led_count, 3), level, dtype=np.uint8)


class LyteMidiDaemon(Reccy, frozen=True):
    service_spec = LYTE_SERVICE
    daemon_module = 'lyte'
    status_model = LyteMidiStatus
    rpc_enabled = True
    rpc_role = 'lyte'

    project: DaemonProject | None = None

    _patch_name: str = PrivateAttr()
    _selected_patch: tuple[str, int] | None = PrivateAttr(default=None)
    _selected_test: LightTestCommand | None = PrivateAttr(default=None)
    _active_test: ActiveLightTest | None = PrivateAttr(default=None)
    _selection_generation: int = PrivateAttr(default=0)
    _applied_selection_generation: int = PrivateAttr(default=0)
    _state: DaemonState = PrivateAttr(default=DaemonState.STARTING)
    _host: str | None = PrivateAttr(default=None)
    _device_mac: str | None = PrivateAttr(default=None)
    _planned_led_count: int | None = PrivateAttr(default=None)
    _actual_led_count: int | None = PrivateAttr(default=None)
    _last_output_contact: datetime.datetime | None = PrivateAttr(default=None)
    _midi_connected: bool = PrivateAttr(default=False)
    _midi_error: str | None = PrivateAttr(default=None)
    _output_state: realtime.PlaybackConnectionState = PrivateAttr(
        default=realtime.PlaybackConnectionState.UNKNOWN
    )
    _recovery_count: int = PrivateAttr(default=0)
    _frame_send_count: int = PrivateAttr(default=0)
    _last_frame_sent_at: datetime.datetime | None = PrivateAttr(default=None)
    _output_error: str | None = PrivateAttr(default=None)
    _output_failure_count: int = PrivateAttr(default=0)
    _render_error: str | None = PrivateAttr(default=None)
    _render_error_count: int = PrivateAttr(default=0)
    _last_failure: str | None = PrivateAttr(default=None)
    _last_failure_at: datetime.datetime | None = PrivateAttr(default=None)
    _failure_count: int = PrivateAttr(default=0)
    _stop_requested: threading.Event = PrivateAttr(default_factory=threading.Event)
    _lock: threading.RLock = PrivateAttr(default_factory=threading.RLock)

    def model_post_init(self, context: object) -> None:
        if self.project is not None:
            object.__setattr__(self, '_patch_name', self.project.config.patch_names[0])
        else:
            object.__setattr__(self, '_patch_name', '')

    def rpc_response(self, request: rpc.Request) -> rpc.Result:
        with self._lock:
            if request.command == 'status':
                return self._status_data()
            if request.command in {'blackout', 'stop'}:
                self._stop_requested.set()
                object.__setattr__(self, '_state', DaemonState.STOPPING)
                return 'ok'
            if request.command == 'select_patch':
                patch = request.params.get('name')
                if (
                    self.project is None
                    or not isinstance(patch, str)
                    or patch not in self.project.config.patch_names
                ):
                    return ipc.Error(
                        type='error',
                        message='select_patch requires a configured patch name',
                    )
                generation = self._selection_generation + 1
                object.__setattr__(self, '_selection_generation', generation)
                object.__setattr__(self, '_selected_patch', (patch, generation))
                return {'state': 'queued', 'generation': generation}
            if request.command == 'test':
                test = _light_test_command(request.params)
                if isinstance(test, ipc.Error):
                    return test
                object.__setattr__(self, '_selected_test', test)
                return {
                    'state': 'queued',
                    'level': test.level,
                    'duration': test.duration,
                }
        return ipc.Error(type='error', message=f'unknown command {request.command}')

    def status_snapshot(self) -> LyteMidiStatus:
        with self._lock:
            return LyteMidiStatus(
                running=self._started,
                errors=self._errors.copy(),
                state=self._state,
                patch=self._patch_name,
                host=self._host,
                device_mac=self._device_mac,
                planned_led_count=self._planned_led_count,
                actual_led_count=self._actual_led_count,
                last_output_contact=self._last_output_contact,
                midi_connected=self._midi_connected,
                midi_error=self._midi_error,
                output_state=self._output_state,
                recovery_count=self._recovery_count,
                queued_test=self._selected_test,
                active_test=(
                    None if self._active_test is None else self._active_test.command
                ),
                frame_send_count=self._frame_send_count,
                last_frame_sent_at=self._last_frame_sent_at,
                output_error=self._output_error,
                output_failure_count=self._output_failure_count,
                render_error=self._render_error,
                render_error_count=self._render_error_count,
                last_failure=self._last_failure,
                last_failure_at=self._last_failure_at,
                failure_count=self._failure_count,
                selection_generation=self._selection_generation,
                applied_selection_generation=self._applied_selection_generation,
            )

    def run(self) -> int:
        if self.project is None:
            raise ValueError('daemon requires a project')
        project = self.project
        config = project.config
        twinkly_track: track.TwinklyTrack | None = None
        port: midi.MidiInput | None = None
        next_midi_open_at = 0.0
        self.start()
        self._set_state(DaemonState.CONNECTING)

        try:
            if project.library.wearable.physical_map_status == 'guessed':
                LOGGER.info('[warn] Daemon is using a guessed physical map.')
            retry = RetryConfig(
                attempts=config.twinkly.attempts,
                delay=config.twinkly.retry_delay,
                backoff=config.twinkly.retry_backoff,
            )
            client = TwinklyClient(
                host=config.twinkly.host or '0.0.0.0', timeout=config.twinkly.timeout
            )
            host = realtime.recover_streaming_device(
                client,
                retry,
                config.twinkly.host,
                config.twinkly.discovery_timeout,
                None,
                stop_event=self._stop_requested,
            )
            if host is None:
                return 0
            actual_led_count = realtime.read_led_count(client, retry, None, host)
            if actual_led_count is None:
                self._set_state(DaemonState.UNKNOWN)
                return 1
            runtime_library = patches.scale_patch_library(
                project.library, actual_led_count
            )
            selector = PatchSelector.create(runtime_library, config.patch_names)
            with self._lock:
                object.__setattr__(self, '_host', host)
                object.__setattr__(
                    self, '_planned_led_count', project.library.wearable.led_count
                )
                object.__setattr__(self, '_actual_led_count', actual_led_count)
            self.publish_status()
            twinkly_track = track.TwinklyTrack(
                client=client,
                retry=retry,
                host=host,
                configured_host=config.twinkly.host,
                discovery_timeout=config.twinkly.discovery_timeout,
                device=animation.Device(led_count=actual_led_count),
                expected_mac=client.mac,
                stop_event=self._stop_requested,
                on_connection_state=self._set_output_state,
                on_device_connected=self._set_output_device,
                on_health_check=self._confirm_output_contact,
                on_frame_sent=self._record_frame_sent,
                on_output_failure=self._record_output_failure,
            )

            def process_messages() -> None:
                nonlocal next_midi_open_at, port
                with self._lock:
                    selected_patch = self._selected_patch
                    selected_test = self._selected_test
                    object.__setattr__(self, '_selected_patch', None)
                    object.__setattr__(self, '_selected_test', None)
                    stop_requested = self._stop_requested.is_set()
                if selected_patch is not None:
                    patch_name, generation = selected_patch
                    selector.select(patch_name)
                    with self._lock:
                        object.__setattr__(self, '_patch_name', selector.patch_name)
                        object.__setattr__(
                            self, '_applied_selection_generation', generation
                        )
                    self.publish_status()
                if selected_test is not None:
                    with self._lock:
                        object.__setattr__(
                            self,
                            '_active_test',
                            ActiveLightTest(
                                command=selected_test, started_at=time.monotonic()
                            ),
                        )
                    LOGGER.info(
                        f'[test] Consumed light test: {selected_test.level:g}% white '
                        f'over {selected_test.duration:g} seconds'
                    )
                    self.publish_status()
                if stop_requested:
                    raise KeyboardInterrupt
                if port is None:
                    if time.monotonic() < next_midi_open_at:
                        return
                    try:
                        port = midi.open_input(config.midi)
                    except (OSError, ValueError) as error:
                        next_midi_open_at = time.monotonic() + 1
                        self._set_midi_connection(False, str(error))
                        return
                    self._set_midi_connection(True, None)
                    LOGGER.info('[connected] MIDI input opened')
                try:
                    for message in midi.input_messages(port, config.midi):
                        try:
                            selector.receive(message)
                        except (AttributeError, TypeError, ValueError) as error:
                            self._record_failure(f'Ignoring MIDI message: {error}')
                    with self._lock:
                        object.__setattr__(self, '_patch_name', selector.patch_name)
                except (OSError, ValueError) as error:
                    self._close_midi_port(port)
                    port = None
                    next_midi_open_at = time.monotonic() + 1
                    selector.clear_performance()
                    self._set_midi_connection(False, str(error))
                    self._record_failure(f'MIDI input disconnected: {error}')
                    LOGGER.error(f'[waiting] MIDI input disconnected: {error}')

            if not twinkly_track.prepare():
                self._set_state(DaemonState.UNKNOWN)
                return 1
            self._set_state(DaemonState.STREAMING)
            LOGGER.info(f'[daemon] Selected patch: {selector.patch_name}')

            def render_frame() -> NDArray[np.uint8]:
                with self._lock:
                    active_test = self._active_test
                if active_test is not None:
                    frame = active_test.render(twinkly_track.device, time.monotonic())
                    if frame is not None:
                        return frame
                    with self._lock:
                        if self._active_test == active_test:
                            object.__setattr__(self, '_active_test', None)
                    self._stop_requested.set()
                    LOGGER.info('[test] Completed light test; stopping Lyte.')
                    return np.zeros((twinkly_track.device.led_count, 3), dtype=np.uint8)
                try:
                    frame = patches.encode_wearable_frame(
                        runtime_library.wearable,
                        selector.patch.render(twinkly_track.device),
                    )
                except (ArithmeticError, IndexError, TypeError, ValueError) as error:
                    self._record_render_error(selector.patch_name, error)
                    return np.zeros((twinkly_track.device.led_count, 3), dtype=np.uint8)
                self._clear_render_error()
                return frame

            twinkly_track.stream_frames(
                'daemon', config.fps, None, render_frame, process_messages
            )
        except KeyboardInterrupt:
            LOGGER.debug('')
            LOGGER.debug('[ok] Stopped')
        finally:
            if port is not None:
                self._close_midi_port(port)
            if twinkly_track is not None:
                twinkly_track.close()
            self._set_state(DaemonState.STOPPED)
            self.close()
        return 0

    def _set_output_state(self, output_state: realtime.PlaybackConnectionState) -> None:
        if output_state is realtime.PlaybackConnectionState.UNKNOWN:
            self._record_failure('Twinkly output state is unknown')
        with self._lock:
            if output_state is realtime.PlaybackConnectionState.RECOVERING:
                object.__setattr__(self, '_recovery_count', self._recovery_count + 1)
                object.__setattr__(self, '_state', DaemonState.RECOVERING)
            elif output_state is realtime.PlaybackConnectionState.STREAMING:
                object.__setattr__(self, '_state', DaemonState.STREAMING)
            object.__setattr__(self, '_output_state', output_state)
        self.publish_status()

    def _record_render_error(self, patch_name: str, error: Exception) -> None:
        message = f'Patch {patch_name} render failed: {error}'
        with self._lock:
            object.__setattr__(self, '_render_error', message)
            object.__setattr__(
                self, '_render_error_count', self._render_error_count + 1
            )
        self._record_failure(message)

    def _record_failure(self, message: str) -> None:
        with self._lock:
            changed = self._last_failure != message
            object.__setattr__(self, '_last_failure', message)
            object.__setattr__(
                self, '_last_failure_at', datetime.datetime.now(datetime.UTC)
            )
            object.__setattr__(self, '_failure_count', self._failure_count + 1)
        if changed:
            self.publish_error(message)

    def _clear_render_error(self) -> None:
        with self._lock:
            if self._render_error is None:
                return
            object.__setattr__(self, '_render_error', None)
            object.__setattr__(self, '_render_error_count', 0)
        self.publish_status()

    def _set_output_device(self, host: str, mac: str | None) -> None:
        with self._lock:
            object.__setattr__(self, '_host', host)
            object.__setattr__(self, '_device_mac', mac)
        self.publish_status()

    def _confirm_output_contact(self) -> None:
        with self._lock:
            object.__setattr__(
                self, '_last_output_contact', datetime.datetime.now(datetime.UTC)
            )

    def _record_frame_sent(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        with self._lock:
            object.__setattr__(self, '_frame_send_count', self._frame_send_count + 1)
            object.__setattr__(self, '_last_frame_sent_at', now)
            object.__setattr__(self, '_last_output_contact', now)
            object.__setattr__(self, '_output_error', None)

    def _record_output_failure(self, message: str) -> None:
        with self._lock:
            object.__setattr__(self, '_output_error', message)
            object.__setattr__(
                self, '_output_failure_count', self._output_failure_count + 1
            )
        self._record_failure(f'Twinkly output failed: {message}')

    def _set_midi_connection(self, connected: bool, error: str | None) -> None:
        with self._lock:
            changed = self._midi_connected != connected or self._midi_error != error
            object.__setattr__(self, '_midi_connected', connected)
            object.__setattr__(self, '_midi_error', error)
        if changed:
            self.publish_status()

    def _close_midi_port(self, port: midi.MidiInput) -> None:
        try:
            port.close()
        except (OSError, ValueError) as error:
            LOGGER.error(f'[warn] Could not close MIDI input: {error}')

    def _set_state(self, state: DaemonState) -> None:
        with self._lock:
            object.__setattr__(self, '_state', state)
        self.publish_status()

    def _status_data(self) -> dict[str, object]:
        return self.status_snapshot().model_dump(mode='json')


class MidiPerformance(BaseModel):
    note: int | None = None
    velocity: int = 0
    channel: int = 0
    breath: int | None = None
    pitch: int | None = None

    def receive(self, msg: mido.Message) -> None:
        match msg.type:
            case 'note_on' if msg.velocity:
                self.note = msg.note
                self.velocity = msg.velocity
                self.channel = msg.channel
                self.breath = None
                self.pitch = None
            case 'note_on' | 'note_off' if self.note == msg.note:
                self.note = None
                self.velocity = 0
                self.breath = None
                self.pitch = None
            case 'control_change' if self.note is not None and msg.control == 2:
                self.breath = msg.value
            case 'pitchwheel' if self.note is not None:
                self.pitch = int(msg.__getattribute__('pitch'))

    def replay(self, patch: midi.LightPatch) -> None:
        if self.note is None:
            return
        patch.receive(
            mido.Message(
                'note_on',
                channel=self.channel,
                note=self.note,
                velocity=self.velocity,
            )
        )
        if self.breath is not None:
            patch.receive(
                mido.Message(
                    'control_change',
                    channel=self.channel,
                    control=2,
                    value=self.breath,
                )
            )
        if self.pitch is not None:
            patch.receive(
                mido.Message('pitchwheel', channel=self.channel, pitch=self.pitch)
            )


class PatchSelector(BaseModel):
    library: SkipValidation[patches.PatchLibrary]
    patch_names: list[str]
    index: int = 0
    patch: SkipValidation[midi.LightPatch]
    performance: MidiPerformance = MidiPerformance()

    @property
    def patch_name(self) -> str:
        return self.patch_names[self.index]

    @classmethod
    def create(
        cls, library: patches.PatchLibrary, patch_names: list[str]
    ) -> PatchSelector:
        return cls(
            library=library,
            patch_names=patch_names,
            patch=patches.build_light_patch(library, patch_names[0]),
        )

    def receive(self, msg: mido.Message) -> None:
        if msg.type == 'program_change':
            self.patch.receive(msg)
            self.advance()
            return
        self.performance.receive(msg)
        self.patch.receive(msg)

    def advance(self) -> None:
        self.index = (self.index + 1) % len(self.patch_names)
        self.patch = patches.build_light_patch(self.library, self.patch_name)
        self.performance.replay(self.patch)

    def select(self, name: str) -> None:
        self.index = self.patch_names.index(name)
        self.patch = patches.build_light_patch(self.library, name)
        self.performance.replay(self.patch)

    def clear_performance(self) -> None:
        if self.performance.note is not None:
            self.patch.receive(
                mido.Message(
                    'note_off',
                    channel=self.performance.channel,
                    note=self.performance.note,
                    velocity=0,
                )
            )
        self.performance = MidiPerformance()

    model_config = ConfigDict(arbitrary_types_allowed=True)


def _light_test_command(params: dict[str, object]) -> LightTestCommand | ipc.Error:
    level = _number_param(params, 'level', 50.0)
    duration = _number_param(params, 'duration', 2.0)
    if isinstance(level, ipc.Error):
        return level
    if isinstance(duration, ipc.Error):
        return duration
    if not isfinite(level) or level < 0 or level > 100:
        return ipc.Error(type='error', message='test level must be between 0 and 100')
    if not isfinite(duration) or duration <= 0:
        return ipc.Error(type='error', message='test duration must be greater than 0')
    return LightTestCommand(level=level, duration=duration)


def _number_param(
    params: dict[str, object], name: str, default: float
) -> float | ipc.Error:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return ipc.Error(type='error', message=f'test {name} must be a number')
    return float(value)


def _light_test_data(test: LightTestCommand | None) -> dict[str, float] | None:
    if test is None:
        return None
    return {'level': test.level, 'duration': test.duration}
