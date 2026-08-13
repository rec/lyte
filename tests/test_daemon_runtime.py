from __future__ import annotations

from collections import deque
from pathlib import Path
from unittest.mock import patch

import mido
from pydantic import BaseModel

from lyte import daemon_config, daemon_runtime, midi, patches


class Config(BaseModel, frozen=True):
    pass


class State(BaseModel):
    pass


class RecordingPatch(midi.LightPatch[Config, State]):
    events: list[str] = []

    def make_state(self, msg: mido.Message) -> State:
        self.events.append(f'note:{msg.note}:{msg.velocity}')
        return State()

    def breath_control(self, msg: mido.Message) -> None:
        self.events.append(f'breath:{msg.value}')

    def pitch_bend(self, msg: mido.Message) -> None:
        self.events.append(f'pitch:{msg.pitch}')

    def program_change(self, msg: mido.Message) -> None:
        self.events.append(f'program:{msg.program}')

    def render(self, device: object) -> object:
        raise NotImplementedError


def test_program_change_wraps_to_the_first_patch(monkeypatch: object) -> None:
    created: deque[RecordingPatch] = deque()

    def build_patch(library: object, name: str) -> RecordingPatch:
        patch = RecordingPatch(config=Config())
        created.append(patch)
        return patch

    monkeypatch.setattr(daemon_runtime.patches, 'build_light_patch', build_patch)
    selector = daemon_runtime.PatchSelector.create(object(), ['one', 'two'])

    selector.receive(mido.Message('program_change', program=3))
    selector.receive(mido.Message('program_change', program=4))

    assert selector.patch_name == 'one'
    assert list(created)[0].events == ['program:3']


def test_program_change_replays_active_note_controls(monkeypatch: object) -> None:
    created: list[RecordingPatch] = []

    def build_patch(library: object, name: str) -> RecordingPatch:
        patch = RecordingPatch(config=Config())
        created.append(patch)
        return patch

    monkeypatch.setattr(daemon_runtime.patches, 'build_light_patch', build_patch)
    selector = daemon_runtime.PatchSelector.create(object(), ['one', 'two'])
    selector.receive(mido.Message('note_on', channel=2, note=60, velocity=100))
    selector.receive(mido.Message('control_change', channel=2, control=2, value=64))
    selector.receive(mido.Message('pitchwheel', channel=2, pitch=1024))
    selector.receive(mido.Message('program_change', channel=2, program=1))

    assert selector.patch_name == 'two'
    assert created[1].events == ['note:60:100', 'breath:64', 'pitch:1024']


def test_daemon_reopens_an_unavailable_midi_input() -> None:
    class Port:
        closed = False

        def close(self) -> None:
            self.closed = True

        def poll(self) -> mido.Message | None:
            return None

    class FakeTrack:
        def __init__(self, **kwargs: object) -> None:
            self.device = kwargs['device']

        def prepare(self) -> bool:
            return True

        def stream_frames(
            self,
            name: str,
            fps: float,
            duration: float | None,
            render_frame: object,
            before_frame: object,
        ) -> None:
            before_frame()

        def close(self) -> None:
            pass

    library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
    library = library.model_copy(
        update={
            'wearable': library.wearable.model_copy(
                update={'physical_map_status': 'measured'}
            )
        }
    )
    project = daemon_config.DaemonProject(
        config=daemon_config.DaemonConfig(
            patch_library=Path('patches/wearable-breath.toml'),
            patches=['breath_walker'],
            midi=midi.MidiIn(channel=0),
            twinkly=daemon_config.TwinklyDaemonConfig(host='192.168.1.23'),
        ),
        library=library,
    )
    port = Port()
    with (
        patch('lyte.daemon_runtime.realtime.read_led_count', return_value=200),
        patch('lyte.daemon_runtime.realtime.prepare_device', return_value=True),
        patch(
            'lyte.daemon_runtime.realtime.turn_off_streaming_device', return_value=True
        ),
        patch(
            'lyte.daemon_runtime.midi.open_input',
            side_effect=[ValueError('missing'), port],
        ),
        patch('lyte.daemon_runtime.track.TwinklyTrack', FakeTrack),
        patch('lyte.daemon_runtime.time.sleep') as sleep,
    ):
        result = daemon_runtime.run_daemon(project)

    assert result == 0
    assert port.closed
    sleep.assert_called_once_with(1)
