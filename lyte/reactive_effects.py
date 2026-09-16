"""Independently designed one-dimensional audio-reactive light effects."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np
import pydantic
from numpy.typing import NDArray
from pydantic import Field
from ufor import effects
from ufor.audio_features import AudioFeatures

from . import animation, reactivity

_RAINBOW = reactivity.Gradient(
    stops=[
        reactivity.GradientStop(position=0, color=[1, 0, 0.2]),
        reactivity.GradientStop(position=0.33, color=[1, 0.7, 0]),
        reactivity.GradientStop(position=0.66, color=[0, 0.8, 1]),
        reactivity.GradientStop(position=1, color=[0.7, 0, 1]),
    ]
)
_FIRE = reactivity.Gradient(
    stops=[
        reactivity.GradientStop(position=0, color=[0, 0, 0]),
        reactivity.GradientStop(position=0.35, color=[0.8, 0, 0]),
        reactivity.GradientStop(position=0.7, color=[1, 0.45, 0]),
        reactivity.GradientStop(position=1, color=[1, 1, 0.7]),
    ]
)
_WHITE = reactivity.Gradient(
    stops=[
        reactivity.GradientStop(position=0, color=[0, 0, 0]),
        reactivity.GradientStop(position=1, color=[1, 1, 1]),
    ]
)
_SILENCE = AudioFeatures(
    level=0, bass=0, mid=0, treble=0, onset=0, beat=0, spectrum=[0]
)


class AudioState(animation.State):
    features: AudioFeatures = _SILENCE


class AudioReactiveAnimation(pydantic.BaseModel, frozen=True):
    gradient: reactivity.Gradient = _RAINBOW

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)


class ScanState(AudioState):
    direction: int = 1
    position: float = 0


class AudioScan(AudioReactiveAnimation, animation.Animation[ScanState], frozen=True):
    width: float = Field(default=0.12, gt=0, le=1)
    speed: float = Field(default=0.4, ge=0)
    sensitivity: float = Field(default=1.5, ge=0)

    def initial_state(self, device: animation.Device) -> ScanState:
        return ScanState()

    def render(self, device: animation.Device, state: ScanState) -> NDArray[np.float32]:
        step = self.speed * (0.2 + state.features.bass * self.sensitivity) / state.fps
        state.position += state.direction * step
        if state.position > 1:
            state.position = 1
            state.direction = -1
        elif state.position < 0:
            state.position = 0
            state.direction = 1
        positions = _positions(device)
        levels = np.maximum(0, 1 - np.abs(positions - state.position) / self.width)
        frame = (
            self.gradient.sample(positions + state.position, cyclic=True)
            * levels[:, None]
        )
        state.frame += 1
        return np.ascontiguousarray(frame)


class SpectrumState(AudioState):
    levels: NDArray[np.float32]


class AudioSpectrum(
    effects.AudioSpectrum, animation.Animation[SpectrumState], frozen=True
):
    def initial_state(self, device: animation.Device) -> SpectrumState:
        return SpectrumState(levels=np.zeros(device.led_count, dtype=np.float32))

    def render(
        self, device: animation.Device, state: SpectrumState
    ) -> NDArray[np.float32]:
        source = np.asarray(state.features.spectrum, dtype=np.float32)
        levels = np.interp(_positions(device), np.linspace(0, 1, len(source)), source)
        state.levels = np.asarray(
            [
                reactivity.smooth(
                    current, target * self.gain, self.smoothing, 1 / state.fps
                )
                for current, target in zip(state.levels, levels, strict=True)
            ],
            dtype=np.float32,
        )
        colors = np.asarray(self.palette, dtype=np.float32) / 255
        palette = np.column_stack(
            [
                np.interp(
                    _positions(device), np.linspace(0, 1, len(colors)), colors[:, c]
                )
                for c in range(3)
            ]
        )
        frame = np.asarray(
            palette * np.clip(state.levels, 0, 1)[:, None], dtype=np.float32
        )
        state.frame += 1
        return np.ascontiguousarray(frame)


class PulseState(AudioState):
    energy: float = 0
    phase: float = 0


class BassPulse(AudioReactiveAnimation, animation.Animation[PulseState], frozen=True):
    speed: float = Field(default=0.55, gt=0)
    decay: float = Field(default=3.5, gt=0)

    def initial_state(self, device: animation.Device) -> PulseState:
        return PulseState()

    def render(
        self, device: animation.Device, state: PulseState
    ) -> NDArray[np.float32]:
        state.energy = max(
            state.features.bass + state.features.onset,
            state.energy * math.exp(-self.decay / state.fps),
        )
        state.phase += self.speed * (0.25 + state.energy) / state.fps
        radius = (state.phase % 1) * 0.8 + 0.02
        distance = np.abs(_positions(device) - 0.5)
        levels = np.exp(-(((distance - radius) / 0.045) ** 2)) * state.energy
        frame = (
            self.gradient.sample(_positions(device) + state.phase, cyclic=True)
            * levels[:, None]
        )
        state.frame += 1
        return np.ascontiguousarray(frame)


@dataclass
class Spotlight:
    center: float
    energy: float
    color: float


class SpotlightState(AudioState):
    generator: random.Random
    spots: list[Spotlight] = Field(default_factory=list)


class AudioSpotlights(
    AudioReactiveAnimation, animation.Animation[SpotlightState], frozen=True
):
    density: float = Field(default=4, ge=0)
    width: float = Field(default=0.08, gt=0, le=1)
    decay: float = Field(default=2.4, gt=0)
    seed: int | None = 1

    def initial_state(self, device: animation.Device) -> SpotlightState:
        return SpotlightState(generator=random.Random(self.seed))

    def render(
        self, device: animation.Device, state: SpotlightState
    ) -> NDArray[np.float32]:
        chance = (
            self.density
            * (0.05 + state.features.onset + state.features.beat)
            / state.fps
        )
        if state.generator.random() < chance:
            state.spots.append(
                Spotlight(
                    center=state.generator.random(),
                    energy=min(1, 0.3 + state.features.level + state.features.onset),
                    color=state.generator.random(),
                )
            )
        positions = _positions(device)
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        remaining = []
        for spot in state.spots:
            level = (
                np.exp(-(((positions - spot.center) / self.width) ** 2)) * spot.energy
            )
            frame += (
                self.gradient.sample(positions + spot.color, cyclic=True)
                * level[:, None]
            )
            spot.energy *= math.exp(-self.decay / state.fps)
            if spot.energy > 0.01:
                remaining.append(spot)
        state.spots = remaining
        state.frame += 1
        return np.ascontiguousarray(np.clip(frame, 0, 1))


class WaterfallState(AudioState):
    history: NDArray[np.float32]


class AudioWaterfall(
    AudioReactiveAnimation, animation.Animation[WaterfallState], frozen=True
):
    speed: float = Field(default=0.7, ge=0)

    def initial_state(self, device: animation.Device) -> WaterfallState:
        return WaterfallState(history=np.zeros(device.led_count, dtype=np.float32))

    def render(
        self, device: animation.Device, state: WaterfallState
    ) -> NDArray[np.float32]:
        source = np.asarray(state.features.spectrum, dtype=np.float32)
        shift = max(1, round(self.speed * device.led_count / state.fps))
        state.history[shift:] = state.history[:-shift]
        positions = np.linspace(0, 1, len(source), dtype=np.float32)
        for index in range(min(shift, device.led_count)):
            progress = (state.frame * shift + index) % device.led_count
            state.history[index] = np.interp(
                progress / device.led_count, positions, source
            )
        state.frame += 1
        return np.ascontiguousarray(
            self.gradient.sample(_positions(device), cyclic=True)
            * np.clip(state.history, 0, 1)[:, None]
        )


class FlameState(AudioState):
    generator: random.Random
    heat: NDArray[np.float32]


class AudioFlame(AudioReactiveAnimation, animation.Animation[FlameState], frozen=True):
    cooling: float = Field(default=1.2, gt=0)
    sparks: float = Field(default=2.5, ge=0)
    gradient: reactivity.Gradient = _FIRE
    seed: int | None = 1

    def initial_state(self, device: animation.Device) -> FlameState:
        return FlameState(
            generator=random.Random(self.seed),
            heat=np.zeros(device.led_count, dtype=np.float32),
        )

    def render(
        self, device: animation.Device, state: FlameState
    ) -> NDArray[np.float32]:
        state.heat *= math.exp(-self.cooling / state.fps)
        state.heat[1:] = (state.heat[1:] + state.heat[:-1]) / 2
        sparks = round(self.sparks * (0.2 + state.features.bass + state.features.onset))
        for _ in range(sparks):
            index = state.generator.randrange(max(1, min(8, device.led_count)))
            state.heat[index] = max(state.heat[index], state.generator.uniform(0.4, 1))
        state.frame += 1
        return np.ascontiguousarray(self.gradient.sample(np.clip(state.heat, 0, 1)))


class StrobeState(AudioState):
    energy: float = 0
    was_beat: bool = False


class BeatStrobe(AudioReactiveAnimation, animation.Animation[StrobeState], frozen=True):
    decay: float = Field(default=8, gt=0)
    gradient: reactivity.Gradient = _WHITE

    def initial_state(self, device: animation.Device) -> StrobeState:
        return StrobeState()

    def render(
        self, device: animation.Device, state: StrobeState
    ) -> NDArray[np.float32]:
        if state.features.beat > 0 and not state.was_beat:
            state.energy = 1
        else:
            state.energy *= math.exp(-self.decay / state.fps)
        state.was_beat = state.features.beat > 0
        state.frame += 1
        return np.ascontiguousarray(
            np.tile(
                self.gradient.sample(np.array([state.energy], dtype=np.float32)),
                (device.led_count, 1),
            )
        )


def update_features(state: AudioState, features: AudioFeatures) -> None:
    state.features = features


def _positions(device: animation.Device) -> NDArray[np.float32]:
    if device.led_count == 1:
        return np.array([0.5], dtype=np.float32)
    return np.linspace(0, 1, device.led_count, dtype=np.float32)


EFFECTS: dict[str, type[AudioReactiveAnimation | AudioSpectrum]] = {
    'audio-scan': AudioScan,
    'audio-spectrum': AudioSpectrum,
    'bass-pulse': BassPulse,
    'audio-spotlights': AudioSpotlights,
    'audio-waterfall': AudioWaterfall,
    'audio-flame': AudioFlame,
    'beat-strobe': BeatStrobe,
}
