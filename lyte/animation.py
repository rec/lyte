"""Shared animation data model."""

from __future__ import annotations

from typing import cast

import numpy as np
import pydantic
from numpy.typing import NDArray


class Device(pydantic.BaseModel, frozen=True):
    led_count: int

    @pydantic.model_validator(mode='after')
    def validate_device(self) -> Device:
        if self.led_count <= 0:
            raise ValueError('led_count must be greater than zero')
        return self


class State(pydantic.BaseModel):
    frame: int = 0
    fps: float = 20.0

    @pydantic.model_validator(mode='after')
    def validate_state(self) -> State:
        if self.fps <= 0:
            raise ValueError('fps must be greater than zero')
        return self

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)


RGB = tuple[int, int, int]
FloatRGB = tuple[float, float, float]


class Animation[StateT: State](pydantic.BaseModel, frozen=True):
    def initial_state(self, device: Device) -> StateT:
        return cast(StateT, State())

    def render(self, device: Device, state: StateT) -> NDArray[np.float32]:
        raise NotImplementedError

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)


class AnimationSegment(pydantic.BaseModel, frozen=True):
    animation: pydantic.SkipValidation[Animation]
    led_count: int

    @pydantic.model_validator(mode='after')
    def validate_segment(self) -> AnimationSegment:
        if self.led_count <= 0:
            raise ValueError('segment led_count must be greater than zero')
        return self

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)


class SegmentState(State):
    states: list[pydantic.SkipValidation[State]]


class SegmentAnimation(Animation[SegmentState], frozen=True):
    segments: list[AnimationSegment]

    @pydantic.model_validator(mode='after')
    def validate_segments(self) -> SegmentAnimation:
        if len(self.segments) < 2:
            raise ValueError('SegmentAnimation requires at least two segments')
        return self

    def initial_state(self, device: Device) -> SegmentState:
        self.validate_device_length(device)
        states = [
            s.animation.initial_state(Device(led_count=s.led_count))
            for s in self.segments
        ]
        return SegmentState(states=states)

    def render(self, device: Device, state: SegmentState) -> NDArray[np.float32]:
        self.validate_device_length(device)
        if len(state.states) != len(self.segments):
            raise ValueError('Segment state must contain one state per segment')
        frames = []
        for segment, child_state in zip(self.segments, state.states, strict=True):
            child_device = Device(led_count=segment.led_count)
            child_state.fps = state.fps
            frames.append(
                validate_frame(
                    child_device, segment.animation.render(child_device, child_state)
                )
            )
        state.frame += 1
        return validate_frame(device, np.ascontiguousarray(np.concatenate(frames)))

    def validate_device_length(self, device: Device) -> None:
        segment_led_count = sum(s.led_count for s in self.segments)
        if segment_led_count != device.led_count:
            raise ValueError('Segment led counts must total device led_count')


def validate_frame(device: Device, frame: NDArray[np.float32]) -> NDArray[np.float32]:
    return validate_float_light_frame(device.led_count, 3, frame)


def validate_byte_rgb_frame(
    device: Device,
    frame: NDArray[np.uint8],
) -> NDArray[np.uint8]:
    if frame.dtype != np.uint8:
        raise ValueError('Byte RGB frames must have dtype uint8')
    if frame.shape != (device.led_count, 3):
        raise ValueError('Byte RGB frames must have shape led_count x 3')
    if not frame.flags.c_contiguous:
        raise ValueError('Byte RGB frames must be C-contiguous')
    return frame


def validate_float_light_frame(
    light_count: int,
    light_channel_count: int,
    frame: NDArray[np.float32],
) -> NDArray[np.float32]:
    if light_count <= 0:
        raise ValueError('light_count must be greater than zero')
    if light_channel_count <= 0:
        raise ValueError('light_channel_count must be greater than zero')
    if frame.dtype != np.float32:
        raise ValueError('Float light frames must have dtype float32')
    if frame.shape != (light_count, light_channel_count):
        raise ValueError(
            'Float light frames must have shape light_count x light channels'
        )
    if not frame.flags.c_contiguous:
        raise ValueError('Float light frames must be C-contiguous')
    if not np.isfinite(frame).all():
        raise ValueError('Float light frames must contain only finite values')
    return frame


def solid_float_light_frame(
    light_count: int,
    values: tuple[float, ...],
) -> NDArray[np.float32]:
    if light_count <= 0:
        raise ValueError('light_count must be greater than zero')
    if not values:
        raise ValueError('values must not be empty')
    frame = np.empty((light_count, len(values)), dtype=np.float32)
    frame[:] = values
    return validate_float_light_frame(light_count, len(values), frame)


def byte_light_frame_from_float(frame: NDArray[np.float32]) -> NDArray[np.uint8]:
    if frame.dtype != np.float32:
        raise ValueError('Float light frames must have dtype float32')
    if frame.ndim != 2:
        raise ValueError('Float light frames must be two-dimensional')
    if not np.isfinite(frame).all():
        raise ValueError('Float light frames must contain only finite values')
    encoded = np.rint(np.clip(frame, 0.0, 1.0) * 255).astype(np.uint8)
    return np.ascontiguousarray(encoded)


def float_color_from_rgb(color: RGB) -> FloatRGB:
    validate_rgb_color(color)
    return color[0] / 255, color[1] / 255, color[2] / 255


def rgb_from_float_color(color: FloatRGB) -> RGB:
    frame = np.array([color], dtype=np.float32)
    red, green, blue = byte_light_frame_from_float(frame)[0]
    return int(red), int(green), int(blue)


def validate_rgb_color(color: RGB) -> None:
    for value in color:
        if value < 0 or value > 255:
            raise ValueError('RGB values must be between 0 and 255')
