"""Region-local effects driven by resolved MIDI controls, without MIDI I/O.

Velocity Splash creates a ripple whose brightness and width derive from note
velocity. Pitch class selects the palette color through the patch binding.
Breath Bloom uses CC 2 to control a persistent bloom's size and brightness;
releasing breath contracts it smoothly. Pitch-Bend Travel moves a focal point
along a region, with breath controlling its halo and intensity. Note-Age
Constellation separates and dims a small set of points as the note ages; a new
note replaces it through the existing single-active-note lifecycle.
"""

import math

import numpy as np
from numpy.typing import NDArray
from pydantic import Field

from ..animation import ConfiguredAnimation, Device, State


class ReactiveState(State):
    velocity: float = 1.0
    breath: float = 0.0
    pitch: float = 0.0
    bloom: float = 0.0


class ReactiveAnimation(ConfiguredAnimation[ReactiveState], frozen=True):
    speed: float = Field(default=1.0, ge=0, allow_inf_nan=False)
    color: list[float] = Field(default=[1.0, 1.0, 1.0], min_length=3, max_length=3)

    def initial_state(self, device: Device) -> ReactiveState:
        return ReactiveState()


class VelocitySplash(ReactiveAnimation, frozen=True):
    def render(self, device: Device, state: ReactiveState) -> NDArray[np.float32]:
        age = state.frame / state.fps * self.speed
        x = coordinates(device)
        width = 0.025 + 0.1 * state.velocity
        distance = np.abs(x - 0.5) - age * 0.35
        levels = np.exp(-0.5 * (distance / width) ** 2)
        levels *= state.velocity * math.exp(-age * 1.5)
        state.frame += 1
        return rgb_levels(levels, self.color)


class BreathBloom(ReactiveAnimation, frozen=True):
    def render(self, device: Device, state: ReactiveState) -> NDArray[np.float32]:
        state.bloom += (state.breath - state.bloom) * (
            1 - math.exp(-6 * self.speed / state.fps)
        )
        radius = 0.025 + 0.45 * state.bloom
        levels = np.exp(-0.5 * ((coordinates(device) - 0.5) / radius) ** 2)
        state.frame += 1
        return rgb_levels(levels * state.bloom, self.color)


class PitchBendTravel(ReactiveAnimation, frozen=True):
    def render(self, device: Device, state: ReactiveState) -> NDArray[np.float32]:
        center = (state.pitch + 1) / 2
        radius = 0.015 + 0.15 * state.breath
        levels = np.exp(-0.5 * ((coordinates(device) - center) / radius) ** 2)
        state.frame += 1
        return rgb_levels(levels * (0.15 + 0.85 * state.breath), self.color)


class NoteAgeConstellation(ReactiveAnimation, frozen=True):
    def render(self, device: Device, state: ReactiveState) -> NDArray[np.float32]:
        age = state.frame / state.fps * self.speed
        spread = 0.03 + 0.42 * (1 - math.exp(-age * 0.6))
        centers = 0.5 + np.linspace(-1, 1, 5) * spread
        distance = coordinates(device)[:, None] - centers
        levels = np.exp(-0.5 * (distance / 0.012) ** 2).max(axis=1)
        state.frame += 1
        return rgb_levels(levels * math.exp(-age * 0.35), self.color)


def coordinates(device: Device) -> NDArray[np.float32]:
    if device.led_count == 1:
        return np.array([0.5], dtype=np.float32)
    return np.linspace(0, 1, device.led_count, dtype=np.float32)


def rgb_levels(levels: NDArray, color: list[float]) -> NDArray[np.float32]:
    return np.ascontiguousarray(levels[:, None] * np.asarray(color), dtype=np.float32)
