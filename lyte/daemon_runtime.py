"""MIDI state and patch selection for the Lyte daemon."""

from __future__ import annotations

import time

import mido
from pydantic import BaseModel, ConfigDict, SkipValidation
from reccy import logging

from . import animation, midi, patches
from .daemon_config import DaemonProject
from .retry import RetryConfig
from .twinkly import realtime, track
from .twinkly.client import TwinklyClient

LOGGER = logging.get_logger(__name__)


def run_daemon(project: DaemonProject) -> int:
    config = project.config
    selector = PatchSelector.create(project.library, config.patch_names)
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

    model_config = ConfigDict(arbitrary_types_allowed=True)
