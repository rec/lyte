"""Spatial, mixing, and temporal compositions of pixel animations."""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field, SkipValidation, model_validator

from ..animation import (
    Animation,
    ConfiguredAnimation,
    Device,
    Family,
    State,
    validate_frame,
)


class Placement(BaseModel, frozen=True):
    start: int = Field(ge=0)
    led_count: int = Field(gt=0)


class ChildrenState(State):
    states: list[SkipValidation[State]]


class Segments(ConfiguredAnimation[ChildrenState], frozen=True):
    family: ClassVar[Family] = Family.COMPOSITIONS

    sources: list[SkipValidation[Animation]] = Field(min_length=1)
    placements: list[Placement] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_placements(self) -> Segments:
        if len(self.sources) != len(self.placements):
            raise ValueError('each source requires one placement')
        ordered = sorted(self.placements, key=lambda p: p.start)
        if any(
            a.start + a.led_count > b.start
            for a, b in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError('segment placements must not overlap; use Mix')
        return self

    def initial_state(self, device: Device) -> ChildrenState:
        if any(p.start + p.led_count > device.led_count for p in self.placements):
            raise ValueError('segments must fit within device led_count')
        return ChildrenState(
            states=[
                s.initial_state(Device(led_count=p.led_count))
                for s, p in zip(self.sources, self.placements, strict=True)
            ]
        )

    def render(self, device: Device, state: ChildrenState) -> NDArray[np.float32]:
        frames = []
        for source, child, placement in zip(
            self.sources, state.states, self.placements, strict=True
        ):
            child.fps = state.fps
            frames.append(source.render(Device(led_count=placement.led_count), child))
        state.frame += 1
        return place_frames(device, self.placements, frames)


class MixState(ChildrenState):
    weights: list[float]


class Mix(ConfiguredAnimation[MixState], frozen=True):
    family: ClassVar[Family] = Family.COMPOSITIONS

    sources: list[SkipValidation[Animation]] = Field(min_length=1)
    weights: list[float] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_weights(self) -> Mix:
        if len(self.sources) != len(self.weights):
            raise ValueError('weights must match sources')
        if any(not np.isfinite(w) or w < 0 for w in self.weights):
            raise ValueError('weights must be finite and nonnegative')
        return self

    def initial_state(self, device: Device) -> MixState:
        return MixState(
            states=[s.initial_state(device) for s in self.sources],
            weights=list(self.weights),
        )

    def render(self, device: Device, state: MixState) -> NDArray[np.float32]:
        frames = []
        for source, child in zip(self.sources, state.states, strict=True):
            child.fps = state.fps
            frames.append(source.render(device, child))
        state.frame += 1
        return mix_frames(device, frames, state.weights)


class TimedChildrenState(ChildrenState):
    elapsed: float = 0.0


class Fade(BaseModel, frozen=True):
    """Blend two frames, including the selector's patch transition morph.

    On a program change, PatchSelector crossfades the current and next patches.
    The selector owns the transition; individual animations remain independent.
    """

    duration: float = Field(gt=0, allow_inf_nan=False)
    easing: Literal['linear', 'smooth'] = 'linear'

    def progress(self, elapsed: float) -> float:
        progress = min(1.0, max(0.0, elapsed / self.duration))
        return (
            progress
            if self.easing == 'linear'
            else progress * progress * (3 - 2 * progress)
        )

    def render(
        self, device: Device, frames: list[NDArray[np.float32]], elapsed: float
    ) -> NDArray[np.float32]:
        if len(frames) != 2:
            raise ValueError('crossfade requires two frames')
        progress = self.progress(elapsed)
        # Unlike a clipped Mix, a crossfade preserves the logical child range.
        return (
            validate_frame(device, frames[0]) * (1 - progress)
            + validate_frame(device, frames[1]) * progress
        )


class Crossfade(ConfiguredAnimation[TimedChildrenState], frozen=True):
    family: ClassVar[Family] = Family.COMPOSITIONS

    sources: list[SkipValidation[Animation]] = Field(min_length=2, max_length=2)
    fade: Fade

    def initial_state(self, device: Device) -> TimedChildrenState:
        return TimedChildrenState(
            states=[s.initial_state(device) for s in self.sources]
        )

    def render(self, device: Device, state: TimedChildrenState) -> NDArray[np.float32]:
        frames = []
        for source, child in zip(self.sources, state.states, strict=True):
            child.fps = state.fps
            frames.append(source.render(device, child))
        frame = self.fade.render(device, frames, state.elapsed)
        state.elapsed += 1 / state.fps
        state.frame += 1
        return frame


class Reverse(ConfiguredAnimation[ChildrenState], frozen=True):
    family: ClassVar[Family] = Family.COMPOSITIONS

    sources: list[SkipValidation[Animation]] = Field(min_length=1, max_length=1)

    def initial_state(self, device: Device) -> ChildrenState:
        return ChildrenState(states=[self.sources[0].initial_state(device)])

    def render(self, device: Device, state: ChildrenState) -> NDArray[np.float32]:
        child = state.states[0]
        child.fps = state.fps
        frame = validate_frame(device, self.sources[0].render(device, child))
        state.frame += 1
        return np.ascontiguousarray(frame[::-1])


class EnvelopePoint(BaseModel, frozen=True):
    time: float = Field(ge=0, allow_inf_nan=False)
    gain: float = Field(ge=0, allow_inf_nan=False)


class Envelope(ConfiguredAnimation[TimedChildrenState], frozen=True):
    family: ClassVar[Family] = Family.COMPOSITIONS

    sources: list[SkipValidation[Animation]] = Field(min_length=1, max_length=1)
    points: list[EnvelopePoint] = Field(min_length=1)
    repeat: bool = False

    @model_validator(mode='after')
    def validate_points(self) -> Envelope:
        if self.points[0].time != 0 or any(
            a.time >= b.time for a, b in zip(self.points, self.points[1:], strict=False)
        ):
            raise ValueError('envelope times must start at zero and strictly increase')
        if self.repeat and self.points[-1].time == 0:
            raise ValueError('repeated envelope requires a positive period')
        return self

    def initial_state(self, device: Device) -> TimedChildrenState:
        return TimedChildrenState(states=[self.sources[0].initial_state(device)])

    def render(self, device: Device, state: TimedChildrenState) -> NDArray[np.float32]:
        elapsed = state.elapsed % self.points[-1].time if self.repeat else state.elapsed
        gain = float(
            np.interp(
                elapsed, [p.time for p in self.points], [p.gain for p in self.points]
            )
        )
        child = state.states[0]
        child.fps = state.fps
        frame = validate_frame(device, self.sources[0].render(device, child)) * gain
        state.frame += 1
        state.elapsed += 1 / state.fps
        return frame


class Cue(BaseModel, frozen=True):
    start: float = Field(ge=0, allow_inf_nan=False)
    duration: float = Field(gt=0, allow_inf_nan=False)


class Sequence(ConfiguredAnimation[TimedChildrenState], frozen=True):
    family: ClassVar[Family] = Family.COMPOSITIONS

    sources: list[SkipValidation[Animation]] = Field(min_length=1)
    cues: list[Cue] = Field(min_length=1)
    easing: Literal['linear', 'smooth'] = 'linear'

    @model_validator(mode='after')
    def validate_cues(self) -> Sequence:
        if len(self.sources) != len(self.cues):
            raise ValueError('each source requires one cue')
        for index, (left, right) in enumerate(
            zip(self.cues, self.cues[1:], strict=False)
        ):
            if (
                left.start >= right.start
                or left.start + left.duration >= right.start + right.duration
            ):
                raise ValueError('cues must have increasing start and end times')
            if (
                index
                and self.cues[index - 1].start + self.cues[index - 1].duration
                > right.start
            ):
                raise ValueError('at most two cues may overlap')
        return self

    def initial_state(self, device: Device) -> TimedChildrenState:
        return TimedChildrenState(
            states=[s.initial_state(device) for s in self.sources]
        )

    def render(self, device: Device, state: TimedChildrenState) -> NDArray[np.float32]:
        active = [
            i
            for i, c in enumerate(self.cues)
            if c.start <= state.elapsed + 1e-10
            and state.elapsed < c.start + c.duration - 1e-10
        ]
        frames = []
        for index in active:
            child = state.states[index]
            child.fps = state.fps
            frames.append(
                validate_frame(device, self.sources[index].render(device, child))
            )
        if len(active) == 2:
            first, second = (self.cues[i] for i in active)
            fade = Fade(
                duration=first.start + first.duration - second.start, easing=self.easing
            )
            frame = fade.render(device, frames, state.elapsed - second.start)
        elif frames:
            frame = frames[0]
        else:
            frame = np.zeros((device.led_count, 3), dtype=np.float32)
        state.elapsed += 1 / state.fps
        state.frame += 1
        return frame


def place_frames(
    device: Device, placements: list[Placement], frames: list[NDArray[np.float32]]
) -> NDArray[np.float32]:
    output = np.zeros((device.led_count, 3), dtype=np.float32)
    for placement, frame in zip(placements, frames, strict=True):
        end = placement.start + placement.led_count
        if end > device.led_count:
            raise ValueError('segments must fit within device led_count')
        output[placement.start : end] = validate_frame(
            Device(led_count=placement.led_count), frame
        )
    return output


def mix_frames(
    device: Device, frames: list[NDArray[np.float32]], weights: list[float]
) -> NDArray[np.float32]:
    total = np.zeros((device.led_count, 3), dtype=np.float32)
    for frame, weight in zip(frames, weights, strict=True):
        if not np.isfinite(weight) or weight < 0:
            raise ValueError('weights must be finite and nonnegative')
        total += validate_frame(device, frame) * weight
    return np.clip(total, 0.0, 1.0)
