"""MIDI state and patch selection for the Lyte daemon."""

from __future__ import annotations

import mido
from pydantic import BaseModel, ConfigDict, SkipValidation

from . import midi, patches


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
