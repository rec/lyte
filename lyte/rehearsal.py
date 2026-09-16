"""Installation rehearsal with a simulated clock and no device connections."""

from base64 import b64encode
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal

import mido
import tyro
from pydantic import BaseModel, Field
from reccy.protocol import ipc

from . import installation_config, installation_playback
from .preview.document import preview_frame_count


class RehearsalConfig(BaseModel, frozen=True):
    config: Annotated[Path, tyro.conf.Positional] = Path('installation.toml')
    string_counts: dict[str, Annotated[int, Field(gt=0)]]
    port: int = Field(default=8766, ge=1024, le=65535)
    open: bool = True


class RehearsalRequest(BaseModel, frozen=True):
    command: Literal['step', 'select_animation', 'test', 'blackout', 'midi']
    params: dict[str, object] = Field(default_factory=dict)


class RehearsalSession:
    def __init__(self, config: RehearsalConfig) -> None:
        installation = installation_config.load_installation(config.config)
        if set(config.string_counts) != set(installation.twinkly):
            raise ValueError(
                'string counts must name every configured string exactly once'
            )
        preview_frame_count(1, 1, sum(config.string_counts.values()) * 3)
        library = installation_playback.load_library(installation)
        self.playback = installation_playback.InstallationPlayback(
            installation, library, dict(config.string_counts)
        )
        self.playback.select(installation.initial_animation)
        self.tick = 0
        self.frames: dict[str, str] = {}

    def request(self, request: RehearsalRequest) -> dict[str, object]:
        if request.command == 'step':
            now = float(Fraction(self.tick) / Fraction(str(self.playback.config.fps)))
            self.frames = {
                n: b64encode(memoryview(f).cast('B')).decode('ascii')
                for n, f in self.playback.render(now)
            }
            self.tick += 1
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
            'tick': self.tick,
            'time': max(0, self.tick - 1) / self.playback.config.fps,
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
