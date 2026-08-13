"""MIDI state and patch selection for the Lyte daemon."""

from __future__ import annotations

import threading
import time

import mido
from pydantic import BaseModel, ConfigDict, SkipValidation
from reccy import logging, rpc

from . import animation, midi, patches
from .daemon_config import DaemonProject
from .retry import RetryConfig
from .twinkly import realtime, track
from .twinkly.client import TwinklyClient

LOGGER = logging.get_logger(__name__)


class DaemonController:
    def __init__(self, patch_names: list[str]) -> None:
        self.patch_names = patch_names
        self.patch_name = patch_names[0]
        self.state = 'starting'
        self.error: str | None = None
        self.stop_requested = False
        self.selected_patch: str | None = None
        self.lock = threading.Lock()

    def handle(self, request: rpc.Request) -> rpc.Response:
        with self.lock:
            if request.command == 'status':
                return rpc.Response(
                    id=request.id,
                    ok=True,
                    result={
                        'state': self.state,
                        'patch': self.patch_name,
                        'error': self.error,
                    },
                )
            if request.command in {'blackout', 'stop'}:
                self.stop_requested = True
                self.state = 'stopping'
                return rpc.Response(id=request.id, ok=True)
            if request.command == 'select_patch':
                patch = request.params.get('name')
                if not isinstance(patch, str) or patch not in self.patch_names:
                    return rpc.Response(
                        id=request.id,
                        ok=False,
                        message='select_patch requires a configured patch name',
                    )
                self.selected_patch = patch
                return rpc.Response(id=request.id, ok=True)
            return rpc.Response(
                id=request.id,
                ok=False,
                message=f'unknown command {request.command}',
            )

    def take_selected_patch(self) -> str | None:
        with self.lock:
            patch, self.selected_patch = self.selected_patch, None
        return patch

    def snapshot(self, patch_name: str) -> dict[str, object]:
        with self.lock:
            self.patch_name = patch_name
            return {'state': self.state, 'patch': patch_name, 'error': self.error}


def run_daemon(project: DaemonProject) -> int:
    config = project.config
    selector = PatchSelector.create(project.library, config.patch_names)
    controller = DaemonController(config.patch_names)
    server = rpc.Server(
        config.control_endpoint,
        config.event_endpoint,
        controller.handle,
        role='lyte',
    )
    if project.library.wearable.physical_map_status == 'guessed':
        LOGGER.info('[warn] Daemon is using a guessed physical map.')
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
        LOGGER.error(f'[failed] {host} does not match the patch library LED count.')
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
        if selected_patch := controller.take_selected_patch():
            selector.select(selected_patch)
        if controller.stop_requested:
            raise KeyboardInterrupt
        while port is None:
            try:
                port = midi.open_input(config.midi)
                LOGGER.info('[connected] MIDI input opened')
            except (OSError, ValueError) as error:
                LOGGER.error(f'[waiting] MIDI input unavailable: {error}')
                time.sleep(1)
        try:
            for message in midi.input_messages(port, config.midi):
                selector.receive(message)
        except OSError as error:
            LOGGER.error(f'[waiting] MIDI input disconnected: {error}')
            port.close()
            port = None

    try:
        if not twinkly_track.prepare():
            return 1
        server.start()
        controller.state = 'streaming'
        server.publish('status', **controller.snapshot(selector.patch_name))
        LOGGER.info(f'[daemon] Selected patch: {selector.patch_name}')
        twinkly_track.stream_frames(
            'daemon',
            config.fps,
            None,
            lambda: patches.encode_wearable_frame(
                project.library.wearable, selector.patch.render(twinkly_track.device)
            ),
            process_messages,
        )
    except KeyboardInterrupt:
        LOGGER.debug('')
        LOGGER.debug('[ok] Stopped')
    finally:
        if port is not None:
            port.close()
        twinkly_track.close()
        controller.state = 'stopped'
        server.publish('status', **controller.snapshot(selector.patch_name))
        server.close()
    return 0


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
