from __future__ import annotations

from abc import ABC, abstractmethod

import mido
from pydantic import BaseModel, ConfigDict


class MidiIn(BaseModel, frozen=True):
    channel: int | None = None
    device_name: str | list[str] | None = None


class Listener(BaseModel, ABC):
    patch: object
    initial_note_on: mido.Message

    """
    When playing a note, the WX7 sends

    1. A note on with a positive velocity, then:
    2. A series of breath control messages, then:
    3. Either a note off: a note on with zero velocity, when the player stops blowing
    4. Or a new note on: when the player changes fingering while blowing

    """

    # Classes optionally override the below.
    def note_on(self, msg: mido.Message) -> None:
        pass

    def note_off(self, msg: mido.Message) -> None:
        pass

    def breath_control(self, msg: mido.Message) -> None:
        pass

    def pitch_bend(self, msg: mido.Message) -> None:
        pass

    model_config = ConfigDict(arbitrary_types_allowed=True)


class Patch[ConfigT: BaseModel, ListenerT: Listener](BaseModel, ABC):
    config: ConfigT
    listener: ListenerT | None = None

    @abstractmethod
    def make_listener(self, msg: mido.Message) -> ListenerT:
        pass

    def receive(self, msg: mido.Message) -> None:
        match msg.type:
            case 'control_change':
                if self.listener is not None and msg.control == 2:
                    self.listener.breath_control(msg)
            case 'note_on':
                if msg.velocity == 0:
                    if self.listener is not None:
                        self.listener.note_off(msg)
                    self.listener = None
                else:
                    if self.listener is not None:
                        self.listener.note_on(msg)
                    self.listener = self.make_listener(msg)
            case 'note_off':
                if self.listener is not None:
                    self.listener.note_off(msg)
                self.listener = None
            case 'pitchwheel':
                if self.listener is not None:
                    self.listener.pitch_bend(msg)

    model_config = ConfigDict(arbitrary_types_allowed=True)
