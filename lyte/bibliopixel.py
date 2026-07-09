"""Small numpy ports of simple BiblioPixel strip animations."""

from __future__ import annotations

import numpy as np
from numpy import typing as npt
from pydantic import BaseModel, PrivateAttr, model_validator

RGB = tuple[int, int, int]
DEFAULT_PATTERN: tuple[RGB, ...] = ((255, 0, 0), (0, 255, 0), (0, 0, 255))


class ColorFill(BaseModel):
    led_count: int
    color: RGB = (255, 0, 0)

    @model_validator(mode="after")
    def validate_color_fill(self) -> ColorFill:
        validate_led_count(self.led_count)
        validate_rgb(self.color)
        return self

    def next_frame(self) -> npt.NDArray[np.uint8]:
        frame = np.empty((self.led_count, 3), dtype=np.uint8)
        frame[:] = self.color
        return frame


class ColorChase(BaseModel):
    led_count: int
    color: RGB = (255, 0, 0)
    width: int = 1
    start: int = 0
    end: int | None = None
    step: int = 1

    _position: int = PrivateAttr(default=0)

    @model_validator(mode="after")
    def validate_color_chase(self) -> ColorChase:
        validate_span(self.led_count, self.start, self.resolved_end)
        validate_rgb(self.color)
        if self.width < 1:
            raise ValueError("width must be at least 1")
        if self.step < 1:
            raise ValueError("step must be at least 1")
        return self

    @property
    def resolved_end(self) -> int:
        if self.end is None or self.end < 0 or self.end >= self.led_count:
            return self.led_count - 1
        return self.end

    def next_frame(self) -> npt.NDArray[np.uint8]:
        frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        position = self.start + self._position
        for i in range(self.width):
            index = position + i
            if self.start <= index <= self.resolved_end:
                frame[index] = self.color
        self._advance()
        return frame

    def _advance(self) -> None:
        self._position += self.step
        overflow = (self.start + self._position) - self.resolved_end
        if overflow >= 0:
            self._position = overflow


class ColorWipe(BaseModel):
    led_count: int
    color: RGB = (255, 0, 0)
    start: int = 0
    end: int | None = None
    step: int = 1

    _frame: npt.NDArray[np.uint8] = PrivateAttr()
    _position: int = PrivateAttr(default=0)

    @model_validator(mode="after")
    def validate_color_wipe(self) -> ColorWipe:
        validate_span(self.led_count, self.start, self.resolved_end)
        validate_rgb(self.color)
        if self.step < 1:
            raise ValueError("step must be at least 1")
        self._frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        return self

    @property
    def resolved_end(self) -> int:
        if self.end is None or self.end < 0 or self.end >= self.led_count:
            return self.led_count - 1
        return self.end

    def next_frame(self) -> npt.NDArray[np.uint8]:
        if self._position == 0:
            self._frame[:] = 0
        for i in range(self.step):
            index = self.start + self._position - i
            if self.start <= index <= self.resolved_end:
                self._frame[index] = self.color
        self._advance()
        return self._frame

    def _advance(self) -> None:
        self._position += self.step
        overflow = (self.start + self._position) - self.resolved_end
        if overflow >= 0:
            self._position = overflow


class Alternates(BaseModel):
    led_count: int
    color1: RGB = (255, 255, 255)
    color2: RGB = (0, 0, 0)
    max_led: int | None = None

    _positive: bool = PrivateAttr(default=True)

    @model_validator(mode="after")
    def validate_alternates(self) -> Alternates:
        validate_led_count(self.led_count)
        validate_rgb(self.color1)
        validate_rgb(self.color2)
        if self.resolved_max_led < 0:
            raise ValueError("max_led must not be negative")
        return self

    @property
    def resolved_max_led(self) -> int:
        if self.max_led is None or self.max_led < 0 or self.max_led >= self.led_count:
            return self.led_count - 1
        return self.max_led

    def next_frame(self) -> npt.NDArray[np.uint8]:
        frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        for i in range(self.resolved_max_led + 1):
            odd = bool(i % 2)
            frame[i] = self.color1 if odd == self._positive else self.color2
        self._positive = not self._positive
        return frame


class ColorPattern(BaseModel):
    led_count: int
    colors: tuple[RGB, ...] = DEFAULT_PATTERN
    width: int = 1
    reverse: bool = False

    _offset: int = PrivateAttr(default=0)

    @model_validator(mode="after")
    def validate_color_pattern(self) -> ColorPattern:
        validate_led_count(self.led_count)
        if not self.colors:
            raise ValueError("colors must not be empty")
        for color in self.colors:
            validate_rgb(color)
        if self.width < 1:
            raise ValueError("width must be at least 1")
        return self

    def next_frame(self) -> npt.NDArray[np.uint8]:
        frame = np.empty((self.led_count, 3), dtype=np.uint8)
        total_width = self.width * len(self.colors)
        for i in range(self.led_count):
            color_index = ((i + self._offset) % total_width) // self.width
            frame[i] = self.colors[color_index]
        self._offset += -1 if self.reverse else 1
        return frame


def validate_led_count(led_count: int) -> None:
    if led_count <= 0:
        raise ValueError("led_count must be greater than zero")


def validate_span(led_count: int, start: int, end: int) -> None:
    validate_led_count(led_count)
    if start < 0:
        raise ValueError("start must not be negative")
    if start >= led_count:
        raise ValueError("start must be less than led_count")
    if end < start:
        raise ValueError("end must be greater than or equal to start")


def validate_rgb(color: RGB) -> None:
    for component in color:
        if component < 0 or component > 255:
            raise ValueError("RGB values must be between 0 and 255")
