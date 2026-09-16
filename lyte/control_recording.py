"""A delivery journal using uFor MIDI events and reccy command requests."""

from pathlib import Path
from typing import Annotated, Literal, TextIO

import mido
from pydantic import BaseModel, Field
from reccy.protocol import rpc
from ufor.events import MidiEvent
from ufor.library import Library

from .installation_config import InstallationFile


class RecordingHeader(BaseModel, frozen=True):
    kind: Literal['lyte-control-recording'] = 'lyte-control-recording'
    installation: dict[str, object]
    scores: dict[str, dict[str, object]]


class Delivery(BaseModel, frozen=True):
    at: float = Field(allow_inf_nan=False)
    string_counts: dict[str, Annotated[int, Field(gt=0)]]
    inputs: list[MidiEvent | rpc.Request]


class ControlRecorder:
    def __init__(self, path: Path) -> None:
        self.stream: TextIO = path.open('x')
        self.pending: list[MidiEvent | rpc.Request] = []
        self.tick = 0
        self.ordinal = 0

    def start(self, config: InstallationFile, library: Library) -> None:
        try:
            self.write(recording_header(config, library).model_dump_json())
        except OSError:
            self.stream.close()
            raise

    def midi(self, message: mido.Message) -> None:
        self.pending.append(
            MidiEvent(tick=self.tick, ordinal=self.ordinal, data=message.bytes())
        )
        self.ordinal += 1

    def command(self, command: str, params: dict[str, object]) -> None:
        self.pending.append(rpc.Request(command=command, params=params))

    def delivery(self, now: float, counts: dict[str, int]) -> None:
        self.write(
            Delivery(
                at=now, string_counts=counts, inputs=self.pending
            ).model_dump_json()
        )
        self.pending = []
        self.tick += 1

    def write(self, line: str) -> None:
        self.stream.write(line + '\n')
        self.stream.flush()

    def close(self) -> None:
        try:
            self.write('{"kind":"end"}')
        finally:
            self.stream.close()


def recording_header(config: InstallationFile, library: Library) -> RecordingHeader:
    return RecordingHeader(
        installation=config.model_dump(mode='json'),
        scores={
            e.key: {'sha256': e.sha256, 'score': e.resolved.model_dump(mode='json')}
            for e in library.entries.values()
            if e.resolved is not None
        },
    )
