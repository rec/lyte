"""A delivery journal using uFor MIDI events and reccy command requests."""

from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal, TextIO

import mido
from pydantic import BaseModel, Field
from reccy.protocol import rpc
from reccy.runtime import logging
from ufor.events import MidiEvent
from ufor.library import Library

from .installation_config import InstallationFile

LOGGER = logging.get_logger(__name__)


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
        self.path = path
        self.stream: TextIO | None = None
        self.error: str | None = None
        self.pending: list[MidiEvent | rpc.Request] = []
        self.tick = 0
        self.ordinal = 0
        try:
            self.stream = path.open('x')
        except OSError as error:
            self.fail(error)

    def start(self, config: InstallationFile, library: Library) -> None:
        if self.error is not None:
            return
        try:
            self.write(recording_header(config, library).model_dump_json())
        except (OSError, ValueError) as error:
            self.fail(error)

    def midi(self, message: mido.Message) -> None:
        if self.error is not None:
            return
        self.pending.append(
            MidiEvent(tick=self.tick, ordinal=self.ordinal, data=message.bytes())
        )
        self.ordinal += 1

    def command(self, command: str, params: dict[str, object]) -> None:
        if self.error is not None:
            return
        self.pending.append(rpc.Request(command=command, params=params))

    def delivery(self, now: float, counts: dict[str, int]) -> None:
        if self.error is not None:
            return
        try:
            self.write(
                Delivery(
                    at=now, string_counts=counts, inputs=self.pending
                ).model_dump_json()
            )
        except ValueError as error:
            self.fail(error)
        self.pending = []
        self.tick += 1

    def write(self, line: str) -> None:
        if self.stream is None:
            return
        try:
            self.stream.write(line + '\n')
            self.stream.flush()
        except (OSError, ValueError) as error:
            self.fail(error)

    def close(self) -> None:
        self.write('{"kind":"end"}')
        if self.stream is None:
            return
        try:
            self.stream.close()
        except (OSError, ValueError) as error:
            self.fail(error)
        finally:
            self.stream = None

    def fail(self, error: OSError | ValueError) -> None:
        if self.error is None:
            LOGGER.error(f'Control recording stopped: {error}')
        self.error = self.error or str(error)
        self.pending.clear()
        if self.stream is not None:
            try:
                self.stream.close()
            except (OSError, ValueError):
                pass
            self.stream = None


def recording_header(config: InstallationFile, library: Library) -> RecordingHeader:
    return RecordingHeader(
        installation=config.model_dump(mode='json'),
        scores={
            e.key: {'sha256': e.sha256, 'score': e.resolved.model_dump(mode='json')}
            for e in library.entries.values()
            if e.resolved is not None
        }
        | {
            f'fixture:{n}': {'sha256': sha256(f.profile.read_bytes()).hexdigest()}
            for n, f in config.dmx.items()
        },
    )
