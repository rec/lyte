from __future__ import annotations

from abc import ABC, abstractmethod

import mido
from pydantic import BaseModel, ConfigDict


class MidiIn(BaseModel, frozen=True):
    channel: int | None = None
    device_name: str | list[str] | None = None


class Patch[ConfigT: BaseModel, StateT: BaseModel](BaseModel, ABC):
    config: ConfigT
    state: StateT | None = None

    """
    When playing a note, the WX7 sends

    1. A note on with a positive velocity, then:
    2. A series of breath control messages, then:
    3. Either a note off: a note on with zero velocity, when the player stops blowing
    4. Or a new note on: when the player changes fingering while blowing

    """

    @abstractmethod
    def make_state(self, msg: mido.Message) -> StateT:
        pass

    def receive(self, msg: mido.Message) -> None:
        if msg.type in ('note_on', 'note_off'):
            if self.state:
                self.note_off()
                self.state = None
            if msg.velocity and msg.type == 'note_on':
                self.state = self.make_state(msg)
            return
        if self.state:
            if msg.type == 'control_change' and msg.control == 2:
                self.breath_control(msg)
            elif msg.type == 'pitchwheel':
                self.pitch_bend(msg)

    # Classes optionally override the below.
    def note_on(self, msg: mido.Message) -> None:
        pass

    def note_off(self) -> None:
        pass

    def breath_control(self, msg: mido.Message) -> None:
        pass

    def pitch_bend(self, msg: mido.Message) -> None:
        pass

    model_config = ConfigDict(arbitrary_types_allowed=True)
