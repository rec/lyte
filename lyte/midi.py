from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

import mido
from pydantic import BaseModel, ConfigDict

from .animation import State

Config = TypeVar('Config', bound=BaseModel)
ListenerClass = TypeVar('ListenerClass', bound='Listener')


class MidiIn(BaseModel, frozen=True):
    channel: int | None = None
    device_name: str | list[str] | None = None


class Listener(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    patch: Patch[BaseModel, Listener]
    note_on: mido.Message

    """
    When playing a note, the WX7 sends

    1. A note on with a positive velocity, then:
    2. A series of breath control messages, then:
    3. Either a note off: a note on with zero velocity, when the player stops blowing
    4. Or a new note on: when the player changes fingering while blowing

    A Listener is created

    """

    # Classes optionally override the below
    def breath_control(self, msg: mido.Message) -> None:
        pass

    def pitch_bend(self, msg: mido.Message) -> None:
        pass

    def close(self) -> None:
        pass


class Patch(BaseModel, Generic[Config, ListenerClass], ABC):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    config: Config  # frozen
    state: State  # mutable
    listener: ListenerClass | None = None

    @abstractmethod
    def make_listener(self, msg: mido.Message) -> ListenerClass:
        pass

    def receive(self, msg: mido.Message) -> None:
        match vars(msg)['type']:
            case 'note_on':
                if self.listener is not None:
                    self.listener.close()
                self.listener = self.make_listener(msg)
            case 'breath_control':
                if self.listener is not None:
                    self.listener.breath_control(msg)
            case 'pitch_bend':
                if self.listener is not None:
                    self.listener.pitch_bend(msg)
