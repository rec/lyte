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


class Animation(BaseModel, Generic[StateT]):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    def initial_state(self, device: Device) -> StateT:
        return cast(StateT, State())

    def render(self, device: Device, state: StateT) -> NDArray[np.uint8]:
        raise NotImplementedError


def validate_frame(device: Device, frame: NDArray[np.uint8]) -> NDArray[np.uint8]:
    if frame.dtype != np.uint8:
        raise ValueError('Animation frames must have dtype uint8')
    if frame.shape != (device.led_count, 3):
        raise ValueError('Animation frames must have shape led_count x 3')
    if not frame.flags.c_contiguous:
        raise ValueError('Animation frames must be C-contiguous')
    return frame
