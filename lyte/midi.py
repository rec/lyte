from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

import mido
from pydantic import BaseModel, ConfigDict

ConfigT = TypeVar('ConfigT', bound=BaseModel)


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

    def receive(self, msg: mido.Message) -> None:
        if msg.type == 'control_change' and msg.control == 2:
            self.breath_control(msg)
        elif msg.type == 'note_on':
            if msg.velocity == 0:
                self.note_off(msg)
            else:
                self.note_on(msg)
        elif msg.type == 'note_off':
            self.note_off(msg)
        elif msg.type == 'pitchwheel':
            self.pitch_bend(msg)

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


ListenerT = TypeVar('ListenerT', bound=Listener)


class Patch(BaseModel, Generic[ConfigT, ListenerT], ABC):
    config: ConfigT
    listener: ListenerT | None = None

    @abstractmethod
    def make_listener(self, msg: mido.Message) -> ListenerT:
        pass

    def receive(self, msg: mido.Message) -> None:
        if self.listener is not None:
            self.listener.receive(msg)
        if msg.type == 'note_on' and msg.velocity > 0:
            self.listener = self.make_listener(msg)
        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            self.listener = None

    model_config = ConfigDict(arbitrary_types_allowed=True)
