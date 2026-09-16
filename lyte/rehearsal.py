"""Installation rehearsal with a simulated clock and no device connections."""

from __future__ import annotations

from base64 import b64encode
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal

import mido
import tyro
from pydantic import BaseModel, Field, model_validator
from reccy.protocol import ipc

from . import installation_config, installation_playback
from .control_recording import ControlRecorder, recording_header
from .control_replay import ControlReplay
from .preview.document import preview_frame_count


class RehearsalConfig(BaseModel, frozen=True):
    config: Annotated[Path, tyro.conf.Positional] = Path('installation.toml')
    string_counts: dict[str, Annotated[int, Field(gt=0)]] = Field(default_factory=dict)
    record_input: Path | None = None
    replay: Path | None = None
    port: int = Field(default=8766, ge=1024, le=65535)
    open: bool = True

    @model_validator(mode='after')
    def recording_mode(self) -> RehearsalConfig:
        if self.replay is not None and (
            self.record_input is not None or self.string_counts
        ):
            raise ValueError(
                'replay uses recorded string counts and cannot also record input'
            )
        return self


class RehearsalRequest(BaseModel, frozen=True):
    command: Literal[
        'step', 'select_animation', 'test', 'blackout', 'midi', 'master_level'
    ]
    params: dict[str, object] = Field(default_factory=dict)


class RehearsalSession:
    def __init__(self, config: RehearsalConfig) -> None:
        installation = installation_config.load_installation(config.config)
        library = installation_playback.load_library(installation)
        self.replay = (
            ControlReplay(config.replay) if config.replay is not None else None
        )
        if self.replay is None and set(config.string_counts) != set(
            installation.twinkly
        ):
            raise ValueError(
                'string counts must name every Twinkly string exactly once; '
                'WLED uses configured counts'
            )
        counts = dict(config.string_counts) | {
            n: t.led_count for n, t in installation.wled.items()
        }
        self.warnings: list[str] = []
        if self.replay is not None:
            if self.replay.next_delivery is None:
                self.replay.stream.close()
                raise ValueError('recording contains no deliveries')
            counts = dict(self.replay.next_delivery.string_counts)
            current = recording_header(installation, library)
            if current.installation != self.replay.header.installation:
                self.warnings.append(
                    'Installation configuration differs from the recording'
                )
            if current.scores != self.replay.header.scores:
                self.warnings.append(
                    'Score sources or declarations (including seeds) '
                    'differ from the recording'
                )
        if set(counts) != set(installation.twinkly) | set(installation.wled):
            if self.replay is not None:
                self.replay.stream.close()
            raise ValueError(
                'string counts must name every configured string exactly once'
            )
        try:
            preview_frame_count(1, 1, sum(counts.values()) * 3)
        except ValueError:
            if self.replay is not None:
                self.replay.stream.close()
            raise
        self.playback = installation_playback.InstallationPlayback(
            installation, library, counts
        )
        self.playback.select(installation.initial_animation)
        if config.record_input is not None:
            self.playback.recorder = ControlRecorder(config.record_input)
            self.playback.recorder.start(installation, library)
        self.tick = 0
        self.origin: float | None = None
        self.at = 0.0
        self.frames: dict[str, str] = {}

    def request(self, request: RehearsalRequest) -> dict[str, object]:
        if request.command == 'step':
            now = float(Fraction(self.tick) / Fraction(str(self.playback.config.fps)))
            if self.replay is not None:
                now = self.replay.apply(self.playback)
            if now is not None:
                if self.origin is None:
                    self.origin = now
                self.at = now - self.origin
                self.frames = {
                    n: b64encode(memoryview(f).cast('B')).decode('ascii')
                    for n, f in self.playback.render(now)
                }
                self.tick += 1
                if self.replay is not None:
                    self.replay.advance()
        elif self.replay is not None:
            raise ValueError('replay controls come from the recording')
        elif request.command == 'midi':
            if self.playback.config.midi is None:
                raise ValueError('this installation has no MIDI configuration')
            self.playback.receive_midi(mido.Message.from_dict(request.params))
        else:
            result = self.playback.command(request.command, request.params)
            if isinstance(result, ipc.Error):
                raise ValueError(result.message)
        active = self.playback.active
        return {
            'recording_error': self.playback.recorder.error
            if self.playback.recorder
            else None,
            'replay': self.replay is not None,
            'finished': self.replay is not None and self.replay.next_delivery is None,
            'warnings': self.warnings,
            'master_level': self.playback.master_level,
            'transition_duration': self.playback.transition_duration,
            'tick': self.tick,
            'time': self.at,
            'fps': self.playback.config.fps,
            'frames': self.frames,
            'strings': self.playback.led_counts,
            'animations': list(self.playback.config.animations),
            'active': active.name if active else None,
            'queued': self.playback.queued_name,
            'bindings': active.definition.outputs if active else {},
            'blackout': self.playback.blackout,
            'test': self.playback.active_test is not None,
            'performance': self.playback.performance.model_dump(),
            'midi': self.playback.config.midi.model_dump()
            if self.playback.config.midi
            else None,
        }

    def close(self) -> None:
        if self.playback.recorder is not None:
            self.playback.recorder.close()
        if self.replay is not None:
            self.replay.stream.close()
