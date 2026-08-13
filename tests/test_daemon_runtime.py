from __future__ import annotations

from collections import deque

import mido
from pydantic import BaseModel

from lyte import daemon_runtime, midi


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
