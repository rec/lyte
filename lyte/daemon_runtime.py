"""MIDI state and patch selection for the Lyte daemon."""

from __future__ import annotations

import threading
import time

import mido
from pydantic import BaseModel, ConfigDict, PrivateAttr, SkipValidation
from reccy import models, rpc
from reccy.reccy import Reccy, ReccyStatus

from . import animation, midi, patches
from .daemon_config import DaemonProject
from .retry import RetryConfig
from .twinkly import realtime, track
from .twinkly.client import TwinklyClient

LYTE_MIDI_SERVICE = models.ServiceSpec(
    name='lyte-midi',
    display_name='Lyte MIDI',
    description='Lyte MIDI patch player',
    launchd_label='com.swirly.lyte-midi',
    daemon_env_var='LYTE_MIDI_DAEMON',
    windows_pipe=r'\\.\pipe\lyte-midi',
)


class LyteMidiStatus(ReccyStatus):
    state: str = 'starting'
    patch: str | None = None


class LyteMidiDaemon(Reccy, frozen=True):
    service_spec = LYTE_MIDI_SERVICE
    status_model = LyteMidiStatus
    rpc_enabled = True
    rpc_role = 'lyte'
    logger_name = 'lyte.daemon'

    project: DaemonProject | None = None

    _patch_name: str = PrivateAttr()
    _selected_patch: str | None = PrivateAttr(default=None)
    _state: str = PrivateAttr(default='starting')
    _stop_requested: bool = PrivateAttr(default=False)
    _lock: threading.RLock = PrivateAttr(default_factory=threading.RLock)

    def model_post_init(self, context: object) -> None:
        if self.project is not None:
            object.__setattr__(self, '_patch_name', self.project.config.patch_names[0])
        else:
            object.__setattr__(self, '_patch_name', '')

    def rpc_response(self, request: rpc.Request) -> rpc.Response:
        with self._lock:
            if request.command == 'status':
                return rpc.Response(id=request.id, ok=True, result=self._status_data())
            if request.command in {'blackout', 'stop'}:
                object.__setattr__(self, '_stop_requested', True)
                object.__setattr__(self, '_state', 'stopping')
                return rpc.Response(id=request.id, ok=True)
            if request.command == 'select_patch':
                patch = request.params.get('name')
                if (
                    self.project is None
                    or not isinstance(patch, str)
                    or patch not in self.project.config.patch_names
                ):
                    return rpc.Response(
                        id=request.id,
                        ok=False,
                        message='select_patch requires a configured patch name',
                    )
                object.__setattr__(self, '_selected_patch', patch)
                return rpc.Response(id=request.id, ok=True)
        return rpc.Response(
            id=request.id,
            ok=False,
            message=f'unknown command {request.command}',
        )

    def status_snapshot(self) -> LyteMidiStatus:
        with self._lock:
            return LyteMidiStatus(
                running=self._started,
                errors=self._errors.copy(),
                state=self._state,
                patch=self._patch_name,
            )

    def run(self) -> int:
        if self.project is None:
            raise ValueError('daemon requires a project')
        project = self.project
        config = project.config
        selector = PatchSelector.create(project.library, config.patch_names)
        if project.library.wearable.physical_map_status == 'guessed':
            self.logger.info('[warn] Daemon is using a guessed physical map.')
        host = config.twinkly.host or realtime.discover_host(
            config.twinkly.discovery_timeout
        )
        if host is None:
            return 1
        retry = RetryConfig(
            attempts=config.twinkly.attempts,
            delay=config.twinkly.retry_delay,
            backoff=config.twinkly.retry_backoff,
        )
        client = TwinklyClient(host=host, timeout=config.twinkly.timeout)
        led_count = realtime.read_led_count(client, retry, None, host)
        if led_count is None:
            return 1
        if led_count != project.library.wearable.led_count:
            self.logger.error(
                f'[failed] {host} does not match the patch library LED count.'
            )
            return 1
        twinkly_track = track.TwinklyTrack(
            client=client,
            retry=retry,
            host=host,
            configured_host=config.twinkly.host,
            discovery_timeout=config.twinkly.discovery_timeout,
            device=animation.Device(led_count=led_count),
        )
        port: midi.MidiInput | None = None

        def process_messages() -> None:
            nonlocal port
            with self._lock:
                selected_patch = self._selected_patch
                object.__setattr__(self, '_selected_patch', None)
                stop_requested = self._stop_requested
            if selected_patch is not None:
                selector.select(selected_patch)
                with self._lock:
                    object.__setattr__(self, '_patch_name', selector.patch_name)
                self.publish_status()
            if stop_requested:
                raise KeyboardInterrupt
            while port is None:
                try:
                    port = midi.open_input(config.midi)
                    self.logger.info('[connected] MIDI input opened')
                except (OSError, ValueError) as error:
                    self.logger.error(f'[waiting] MIDI input unavailable: {error}')
                    time.sleep(1)
            try:
                for message in midi.input_messages(port, config.midi):
                    selector.receive(message)
                with self._lock:
                    object.__setattr__(self, '_patch_name', selector.patch_name)
            except OSError as error:
                self.logger.error(f'[waiting] MIDI input disconnected: {error}')
                port.close()
                port = None

        try:
            if not twinkly_track.prepare():
                return 1
            self.start()
            with self._lock:
                object.__setattr__(self, '_state', 'streaming')
            self.publish_status()
            self.logger.info(f'[daemon] Selected patch: {selector.patch_name}')
            twinkly_track.stream_frames(
                'daemon',
                config.fps,
                None,
                lambda: patches.encode_wearable_frame(
                    project.library.wearable,
                    selector.patch.render(twinkly_track.device),
                ),
                process_messages,
            )
        except KeyboardInterrupt:
            self.logger.debug('')
            self.logger.debug('[ok] Stopped')
        finally:
            if port is not None:
                port.close()
            twinkly_track.close()
            with self._lock:
                object.__setattr__(self, '_state', 'stopped')
            self.close()
        return 0

    def _status_data(self) -> dict[str, object]:
        return {
            'state': self._state,
            'patch': self._patch_name,
            'error': None,
        }


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

    model_config = ConfigDict(arbitrary_types_allowed=True)
