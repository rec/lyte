from __future__ import annotations

from math import isfinite

import mido
import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel
from reccy.protocol import ipc

from . import animation


class MidiPerformance(BaseModel):
    note: int | None = None
    velocity: int = 0
    channel: int = 0
    breath: int | None = None
    pitch: int | None = None

    def receive(self, message: mido.Message) -> None:
        match message.type:
            case 'note_on' if message.velocity:
                self.note = message.note
                self.velocity = message.velocity
                self.channel = message.channel
                self.breath = None
                self.pitch = None
            case 'note_on' | 'note_off' if self.note == message.note:
                self.note = None
                self.velocity = 0
                self.breath = None
                self.pitch = None
            case 'control_change' if self.note is not None and message.control == 2:
                self.breath = message.value
            case 'pitchwheel' if self.note is not None:
                self.pitch = int(message.__getattribute__('pitch'))

    def value(self, source: str) -> float:
        if source == 'gate':
            return float(self.note is not None)
        if source == 'note':
            return float(self.note or 0)
        if source == 'velocity':
            return self.velocity / 127
        if source == 'breath':
            return (self.breath or 0) / 127
        if source == 'pitch_bend':
            pitch = self.pitch or 0
            return pitch / (8192 if pitch < 0 else 8191)
        raise ValueError(f'unknown MIDI control source {source}')


class LightTestCommand(BaseModel, frozen=True):
    level: float = 50.0
    duration: float = 2.0


class ActiveLightTest(BaseModel, frozen=True):
    command: LightTestCommand
    started_at: float

    def render(self, device: animation.Device, now: float) -> NDArray[np.uint8] | None:
        elapsed = now - self.started_at
        if elapsed > self.command.duration:
            return None
        half_duration = self.command.duration / 2
        if elapsed <= half_duration:
            fraction = elapsed / half_duration
        else:
            fraction = (self.command.duration - elapsed) / half_duration
        level = round(255 * self.command.level / 100 * max(0.0, fraction))
        return np.full((device.led_count, 3), level, dtype=np.uint8)


def light_test_command(params: dict[str, object]) -> LightTestCommand | ipc.Error:
    level = _number_param(params, 'level', 50.0)
    duration = _number_param(params, 'duration', 2.0)
    if isinstance(level, ipc.Error):
        return level
    if isinstance(duration, ipc.Error):
        return duration
    if not isfinite(level) or level < 0 or level > 100:
        return ipc.Error(type='error', message='test level must be between 0 and 100')
    if not isfinite(duration) or duration <= 0:
        return ipc.Error(type='error', message='test duration must be greater than 0')
    return LightTestCommand(level=level, duration=duration)


def _number_param(
    params: dict[str, object], name: str, default: float
) -> float | ipc.Error:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return ipc.Error(type='error', message=f'test {name} must be a number')
    return float(value)
