"""Shared animation data model."""

from __future__ import annotations

from typing import Generic, TypeVar, cast

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, model_validator


class Device(BaseModel):
    model_config = ConfigDict(frozen=True)

    led_count: int

    @model_validator(mode='after')
    def validate_device(self) -> Device:
        if self.led_count <= 0:
            raise ValueError('led_count must be greater than zero')
        return self


class State(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    frame: int = 0
    fps: float = 20.0

    @model_validator(mode='after')
    def validate_state(self) -> State:
        if self.fps <= 0:
            raise ValueError('fps must be greater than zero')
        return self


StateT = TypeVar('StateT', bound=State)
RGB = tuple[int, int, int]
FloatRGB = tuple[float, float, float]


class Animation(BaseModel, Generic[StateT]):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    def initial_state(self, device: Device) -> StateT:
        return cast(StateT, State())

    def render(self, device: Device, state: StateT) -> NDArray[np.float32]:
        raise NotImplementedError


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
