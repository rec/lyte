from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

import mido
from pydantic import BaseModel, ConfigDict

ConfigT = TypeVar('ConfigT', bound=BaseModel)
ListenerT = TypeVar('ListenerT', bound='Listener')


class MidiIn(BaseModel, frozen=True):
    channel: int | None = None
    device_name: str | list[str] | None = None


class Listener(BaseModel):
    patch: Patch[BaseModel, Listener]
    note_on: mido.Message

    """
    When playing a note, the WX7 sends

    1. A note on with a positive velocity, then:
    2. A series of breath control messages, then:
    3. Either a note off: a note on with zero velocity, when the player stops blowing
    4. Or a new note on: when the player changes fingering while blowing

    """

    # Classes optionally override the below
    def note_on(self, msg: mido.Message) -> None:  # The next note on
        pass

    def breath_control(self, msg: mido.Message) -> None:
        pass

    def pitch_bend(self, msg: mido.Message) -> None:
        pass

    model_config = ConfigDict(arbitrary_types_allowed=True)


class Patch(BaseModel, Generic[ConfigT, ListenerT], ABC):
    config: ConfigT
    listener: ListenerT | None = None

    @abstractmethod
    def make_listener(self, msg: mido.Message) -> ListenerT:
        pass

    def receive(self, msg: mido.Message) -> None:
        if cb := getattr(self.listener, msg.type):
            cb(msg)
        if msg.type == 'note_on':
            self.listener = self.make_listener(msg)

    model_config = ConfigDict(arbitrary_types_allowed=True)
