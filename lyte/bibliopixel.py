"""Small numpy ports of simple BiblioPixel strip animations."""

from __future__ import annotations

import math
import random
from typing import Protocol, cast

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, PrivateAttr, model_validator

from .animation import Animation, Device, State

RGB = tuple[int, int, int]
DEFAULT_PATTERN: tuple[RGB, ...] = ((255, 0, 0), (0, 255, 0), (0, 0, 255))
SEARCHLIGHT_COLORS: tuple[RGB, ...] = (
    (60, 179, 113),
    (147, 112, 219),
    (199, 21, 133),
)


class _ColorFillRenderer(BaseModel):
    led_count: int
    color: RGB = (255, 0, 0)

    @model_validator(mode="after")
    def validate_color_fill(self) -> _ColorFillRenderer:
        validate_led_count(self.led_count)
        validate_rgb(self.color)
        return self

    def next_frame(self) -> NDArray[np.uint8]:
        frame = np.empty((self.led_count, 3), dtype=np.uint8)
        frame[:] = self.color
        return frame


class _ColorChaseRenderer(BaseModel):
    led_count: int
    color: RGB = (255, 0, 0)
    width: int = 1
    start: int = 0
    end: int | None = None
    step: int = 1

    _position: int = PrivateAttr(default=0)

    @model_validator(mode="after")
    def validate_color_chase(self) -> _ColorChaseRenderer:
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

    def next_frame(self) -> NDArray[np.uint8]:
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


class _ColorWipeRenderer(BaseModel):
    led_count: int
    color: RGB = (255, 0, 0)
    start: int = 0
    end: int | None = None
    step: int = 1

    _frame: NDArray[np.uint8] = PrivateAttr()
    _position: int = PrivateAttr(default=0)

    @model_validator(mode="after")
    def validate_color_wipe(self) -> _ColorWipeRenderer:
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

    def next_frame(self) -> NDArray[np.uint8]:
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


class _AlternatesRenderer(BaseModel):
    led_count: int
    color1: RGB = (255, 255, 255)
    color2: RGB = (0, 0, 0)
    max_led: int | None = None

    _positive: bool = PrivateAttr(default=True)

    @model_validator(mode="after")
    def validate_alternates(self) -> _AlternatesRenderer:
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

    def next_frame(self) -> NDArray[np.uint8]:
        frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        for i in range(self.resolved_max_led + 1):
            odd = bool(i % 2)
            frame[i] = self.color1 if odd == self._positive else self.color2
        self._positive = not self._positive
        return frame


class _ColorPatternRenderer(BaseModel):
    led_count: int
    colors: tuple[RGB, ...] = DEFAULT_PATTERN
    width: int = 1
    reverse: bool = False

    _offset: int = PrivateAttr(default=0)

    @model_validator(mode="after")
    def validate_color_pattern(self) -> _ColorPatternRenderer:
        validate_led_count(self.led_count)
        if not self.colors:
            raise ValueError("colors must not be empty")
        for color in self.colors:
            validate_rgb(color)
        if self.width < 1:
            raise ValueError("width must be at least 1")
        return self

    def next_frame(self) -> NDArray[np.uint8]:
        frame = np.empty((self.led_count, 3), dtype=np.uint8)
        total_width = self.width * len(self.colors)
        for i in range(self.led_count):
            color_index = ((i + self._offset) % total_width) // self.width
            frame[i] = self.colors[color_index]
        self._offset += -1 if self.reverse else 1
        return frame


class _ColorFadeRenderer(BaseModel):
    led_count: int
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    level_step: int = 5
    start: int = 0
    end: int | None = None

    _position: int = PrivateAttr(default=0)
    _levels: list[int] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def validate_color_fade(self) -> _ColorFadeRenderer:
        validate_span(self.led_count, self.start, self.resolved_end)
        validate_palette(self.colors)
        if self.level_step < 1:
            raise ValueError("level_step must be at least 1")
        levels = list(range(30, 256, self.level_step))
        self._levels = levels + list(reversed(levels[:-1]))
        return self

    @property
    def resolved_end(self) -> int:
        return resolve_end(self.led_count, self.end)

    def next_frame(self) -> NDArray[np.uint8]:
        color_index, level_index = divmod(self._position, len(self._levels))
        color = scale_color(
            self.colors[color_index % len(self.colors)], self._levels[level_index]
        )
        frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        frame[self.start : self.resolved_end + 1] = color
        self._position += 1
        return frame


class _PartyModeRenderer(BaseModel):
    led_count: int
    colors: tuple[RGB, ...] = DEFAULT_PATTERN

    _position: int = PrivateAttr(default=0)

    @model_validator(mode="after")
    def validate_party_mode(self) -> _PartyModeRenderer:
        validate_led_count(self.led_count)
        validate_palette(self.colors)
        return self

    def next_frame(self) -> NDArray[np.uint8]:
        frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        if self._position % 2 == 0:
            frame[:] = self.colors[(self._position // 2) % len(self.colors)]
        self._position += 1
        return frame


class _FireFliesRenderer(BaseModel):
    led_count: int
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    width: int = 1
    count: int = 1
    start: int = 0
    end: int | None = None
    seed: int | None = None

    _random: random.Random = PrivateAttr()

    @model_validator(mode="after")
    def validate_fire_flies(self) -> _FireFliesRenderer:
        validate_span(self.led_count, self.start, self.resolved_end)
        validate_palette(self.colors)
        if self.width < 1:
            raise ValueError("width must be at least 1")
        if self.count < 1:
            raise ValueError("count must be at least 1")
        self._random = random.Random(self.seed)
        return self

    @property
    def resolved_end(self) -> int:
        return resolve_end(self.led_count, self.end)

    def next_frame(self) -> NDArray[np.uint8]:
        frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        for _ in range(self.count):
            pixel = self._random.randint(self.start, self.resolved_end)
            color = self._random.choice(self.colors)
            frame[pixel : min(pixel + self.width, self.resolved_end + 1)] = color
        return frame


class _SaberBladeRenderer(BaseModel):
    led_count: int
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    speed: int = 1

    _color_index: int = PrivateAttr(default=0)
    _position: int = PrivateAttr(default=0)
    _speed: int = PrivateAttr()

    @model_validator(mode="after")
    def validate_saber_blade(self) -> _SaberBladeRenderer:
        validate_led_count(self.led_count)
        validate_palette(self.colors)
        if self.speed == 0:
            raise ValueError("speed must not be zero")
        self._speed = self.speed
        return self

    def next_frame(self) -> NDArray[np.uint8]:
        frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        if self._position > 0:
            frame[: min(self._position, self.led_count)] = self.colors[
                self._color_index % len(self.colors)
            ]
        self._position += self._speed
        if self._speed > 0 and self._position + self._speed > self.led_count:
            self._speed *= -1
        elif self._speed < 0 and self._position <= 0:
            self._position = 0
            self._color_index += 1
            self._speed *= -1
        return frame


class _RainbowRenderer(BaseModel):
    led_count: int
    start: int = 0
    end: int | None = None
    step: int = 1

    _position: int = PrivateAttr(default=0)

    @model_validator(mode="after")
    def validate_rainbow(self) -> _RainbowRenderer:
        validate_span(self.led_count, self.start, self.resolved_end)
        if self.step < 1:
            raise ValueError("step must be at least 1")
        return self

    @property
    def resolved_end(self) -> int:
        return resolve_end(self.led_count, self.end)

    @property
    def size(self) -> int:
        return self.resolved_end - self.start + 1

    def next_frame(self) -> NDArray[np.uint8]:
        frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        for i in range(self.size):
            frame[self.start + i] = wheel_color((i + self._position) % 255)
        self._advance()
        return frame

    def _advance(self) -> None:
        self._position += self.step
        overflow = self._position - 256
        if overflow >= 0:
            self._position = overflow


class _RainbowCycleRenderer(_RainbowRenderer):
    def next_frame(self) -> NDArray[np.uint8]:
        frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        for i in range(self.size):
            frame[self.start + i] = wheel_color(
                round(i * 255 / self.size + self._position)
            )
        self._advance()
        return frame


class _LinearRainbowRenderer(BaseModel):
    led_count: int
    max_led: int | None = None
    individual_pixel: bool = False
    step: int = 1

    _current: int = PrivateAttr(default=0)
    _position: int = PrivateAttr(default=0)
    _frame: NDArray[np.uint8] = PrivateAttr()

    @model_validator(mode="after")
    def validate_linear_rainbow(self) -> _LinearRainbowRenderer:
        validate_led_count(self.led_count)
        if self.step < 1:
            raise ValueError("step must be at least 1")
        self._frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        return self

    @property
    def resolved_max_led(self) -> int:
        return resolve_end(self.led_count, self.max_led)

    def next_frame(self) -> NDArray[np.uint8]:
        if self.individual_pixel:
            self._frame[self._current] = wheel_color(self._position)
        else:
            self._frame[: self._current + 1] = wheel_color(self._position)
        self._position += self.step
        self._current = (
            0 if self._current == self.resolved_max_led else self._current + self.step
        )
        if self._current > self.resolved_max_led:
            self._current = self.resolved_max_led
        return self._frame


class _HalvesRainbowRenderer(BaseModel):
    led_count: int
    max_led: int | None = None
    center_out: bool = True
    rainbow_inc: int = 4
    step: int = 1

    _current: int = PrivateAttr(default=0)
    _position: int = PrivateAttr(default=0)
    _frame: NDArray[np.uint8] = PrivateAttr()

    @model_validator(mode="after")
    def validate_halves_rainbow(self) -> _HalvesRainbowRenderer:
        validate_led_count(self.led_count)
        if self.step < 1:
            raise ValueError("step must be at least 1")
        self._frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        return self

    @property
    def resolved_max_led(self) -> int:
        return resolve_end(self.led_count, self.max_led)

    def next_frame(self) -> NDArray[np.uint8]:
        color = wheel_color(self._position)
        center = self.resolved_max_led / 2
        center_floor = math.floor(center)
        center_ceil = math.ceil(center)
        if self.center_out:
            self._frame[int(center_floor - self._current)] = color
            self._frame[int(center_ceil + self._current)] = color
        else:
            self._frame[self._current] = color
            self._frame[self.resolved_max_led - self._current] = color
        self._position += self.step + self.rainbow_inc
        self._current = (
            0 if self._current == center_floor else self._current + self.step
        )
        if self._current > center_floor:
            self._current = center_floor
        return self._frame


class _LarsonScannerRenderer(BaseModel):
    led_count: int
    color: RGB = (255, 0, 0)
    tail: int = 2
    start: int = 0
    end: int | None = None
    step: int = 1
    rainbow: bool = False

    _direction: int = PrivateAttr(default=-1)
    _position: int = PrivateAttr(default=0)
    _tail: int = PrivateAttr(default=1)

    @model_validator(mode="after")
    def validate_larson_scanner(self) -> _LarsonScannerRenderer:
        validate_span(self.led_count, self.start, self.resolved_end)
        validate_rgb(self.color)
        if self.tail < 0:
            raise ValueError("tail must not be negative")
        if self.step < 1:
            raise ValueError("step must be at least 1")
        self._tail = bounded_tail(self.tail, self.size)
        return self

    @property
    def resolved_end(self) -> int:
        return resolve_end(self.led_count, self.end)

    @property
    def size(self) -> int:
        return self.resolved_end - self.start + 1

    def next_frame(self) -> NDArray[np.uint8]:
        frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        center = self.start + self._position
        color = wheel_color(self._position) if self.rainbow else self.color
        fade = 256 // self._tail
        for i in range(self._tail):
            scaled = scale_color(color, max(0, 255 - fade * i))
            for index in (center - i, center + i):
                if self.start <= index <= self.resolved_end:
                    frame[index] = scaled
        if self.start + self._position >= self.resolved_end:
            self._direction = -self._direction
        elif self._position <= 0:
            self._direction = -self._direction
        self._position += self._direction * self.step
        return frame


class _PulseRenderer(BaseModel):
    led_count: int
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    tail: int = 2
    chance: int = 30
    min_speed: int = 1
    max_speed: int = 5
    seed: int | None = None

    _color: RGB | None = PrivateAttr(default=None)
    _position: int = PrivateAttr(default=0)
    _random: random.Random = PrivateAttr()
    _speed: int = PrivateAttr(default=0)
    _tail: int = PrivateAttr(default=1)

    @model_validator(mode="after")
    def validate_pulse(self) -> _PulseRenderer:
        validate_led_count(self.led_count)
        validate_palette(self.colors)
        if self.tail < 0:
            raise ValueError("tail must not be negative")
        if self.chance < 0 or self.chance > 100:
            raise ValueError("chance must be between 0 and 100")
        if self.min_speed < 1 or self.max_speed <= self.min_speed:
            raise ValueError("min_speed and max_speed must define a non-empty range")
        self._tail = bounded_tail(self.tail, self.led_count)
        self._random = random.Random(self.seed)
        return self

    def next_frame(self) -> NDArray[np.uint8]:
        frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        if self._speed == 0 and self._random.randrange(0, 100) <= self.chance:
            self._color = self._random.choice(self.colors)
            self._speed = self._random.randrange(self.min_speed, self.max_speed)
            self._position = 0
        if self._speed > 0 and self._color is not None:
            fade = 256 // self._tail
            for i in range(self._tail):
                scaled = scale_color(self._color, max(0, 255 - fade * i))
                for index in (self._position - i, self._position + i):
                    if 0 <= index < self.led_count:
                        frame[index] = scaled
            if self._position > self.led_count + self._tail:
                self._speed = 0
            else:
                self._position += self._speed
        return frame


class _PixelPingPongRenderer(BaseModel):
    led_count: int
    color: RGB = (255, 255, 255)
    max_led: int | None = None
    total_pixels: int = 1
    fade_delay: int = 1

    _current: int = PrivateAttr(default=0)
    _frame: NDArray[np.uint8] = PrivateAttr()
    _positive: bool = PrivateAttr(default=True)

    @model_validator(mode="after")
    def validate_pixel_ping_pong(self) -> _PixelPingPongRenderer:
        validate_led_count(self.led_count)
        validate_rgb(self.color)
        if self.total_pixels < 1:
            raise ValueError("total_pixels must be at least 1")
        if self.fade_delay < 1:
            raise ValueError("fade_delay must be at least 1")
        self._frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        return self

    @property
    def resolved_max_led(self) -> int:
        return resolve_end(self.led_count, self.max_led)

    def next_frame(self) -> NDArray[np.uint8]:
        decrement = np.array(self.color, dtype=np.float64) / self.fade_delay
        faded = self._frame.astype(np.float64) - decrement
        self._frame[:] = np.maximum(faded, 0).astype(np.uint8)
        end = min(self._current + self.total_pixels, self.resolved_max_led + 1)
        self._frame[self._current : end] = self.color
        if self._positive:
            self._current += 1
        else:
            self._current -= 1
        if self._current + self.total_pixels - 1 >= self.resolved_max_led:
            self._positive = False
        if self._current <= 0:
            self._current = 0
            self._positive = True
        return self._frame


class _SearchlightsRenderer(BaseModel):
    led_count: int
    colors: tuple[RGB, ...] = SEARCHLIGHT_COLORS
    tail: int = 5
    start: int = 0
    end: int | None = None
    seed: int | None = None

    _directions: list[int] = PrivateAttr(default_factory=list)
    _random: random.Random = PrivateAttr()
    _steps: list[int] = PrivateAttr(default_factory=list)
    _tail: int = PrivateAttr(default=1)

    @model_validator(mode="after")
    def validate_searchlights(self) -> _SearchlightsRenderer:
        validate_span(self.led_count, self.start, self.resolved_end)
        validate_palette(self.colors)
        if len(self.colors) < 3:
            raise ValueError("colors must contain at least three colors")
        if self.tail < 0:
            raise ValueError("tail must not be negative")
        self._tail = bounded_tail(self.tail, self.size)
        self._directions = [1, 1, 1]
        self._steps = [1, 1, 1]
        self._random = random.Random(self.seed)
        return self

    @property
    def resolved_end(self) -> int:
        return resolve_end(self.led_count, self.end)

    @property
    def size(self) -> int:
        return self.resolved_end - self.start + 1

    def next_frame(self) -> NDArray[np.uint8]:
        colors = np.zeros((self.led_count, 3), dtype=np.uint8)
        fade = 256 / self._tail
        for i in range(3):
            position = self.start + self._steps[i]
            color = self.colors[i]
            blend_color(colors, position, color)
            for j in range(1, self._tail):
                scaled = scale_color(color, round(255 - fade * j))
                blend_color(colors, position - j, scaled)
                blend_color(colors, position + j, scaled)
            if position >= self.resolved_end:
                self._directions[i] = -1
            elif position <= self.start:
                self._directions[i] = 1
            if self._random.random() > i * 0.05:
                self._steps[i] += self._directions[i]
        return colors


class _WaveRenderer(BaseModel):
    led_count: int
    color: RGB = (255, 0, 0)
    cycles: int = 2
    start: int = 0
    end: int | None = None
    moving: bool = False

    _move_step: int = PrivateAttr(default=0)
    _position: int = PrivateAttr(default=0)

    @model_validator(mode="after")
    def validate_wave(self) -> _WaveRenderer:
        validate_span(self.led_count, self.start, self.resolved_end)
        validate_rgb(self.color)
        if self.cycles < 1:
            raise ValueError("cycles must be at least 1")
        return self

    @property
    def resolved_end(self) -> int:
        return resolve_end(self.led_count, self.end)

    @property
    def size(self) -> int:
        return self.resolved_end - self.start + 1

    def next_frame(self) -> NDArray[np.uint8]:
        frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        for i in range(self.size):
            if self.moving:
                value = math.sin(
                    math.pi * self.cycles * i / self.size + self._move_step
                )
            else:
                value = math.sin(math.pi * self.cycles * self._position * i / self.size)
            frame[self.start + i] = wave_color(self.color, value)
        if self.moving:
            self._move_step += 2
            if self._move_step >= self.size:
                self._move_step = 0
        else:
            self._position += 1
        return frame


class _TwinkleRenderer(BaseModel):
    led_count: int
    colors: tuple[RGB, ...] = DEFAULT_PATTERN
    density: int = 20
    speed: int = 2
    max_bright: int = 255
    seed: int | None = None

    _pixels: list[tuple[int, RGB, int]] = PrivateAttr(default_factory=list)
    _random: random.Random = PrivateAttr()

    @model_validator(mode="after")
    def validate_twinkle(self) -> _TwinkleRenderer:
        validate_led_count(self.led_count)
        validate_palette(self.colors)
        self.speed = max(2, min(100, self.speed))
        self.density = max(2, min(100, self.density))
        self.max_bright = max(5, min(255, self.max_bright))
        self._pixels = [(0, (0, 0, 0), 0)] * self.led_count
        self._random = random.Random(self.seed)
        return self

    def next_frame(self) -> NDArray[np.uint8]:
        frame = np.zeros((self.led_count, 3), dtype=np.uint8)
        self._pick_led()
        for i, pixel in enumerate(self._pixels):
            direction, color, level = pixel
            if direction == 1:
                level += self.speed
                if level > self.max_bright:
                    level = self.max_bright
                    direction = 2
                frame[i] = scale_color(color, level)
            elif direction == 2:
                level -= self.speed
                if level < 0:
                    level = 0
                    direction = 0
                frame[i] = scale_color(color, level)
            self._pixels[i] = direction, color, level
        return frame

    def _pick_led(self) -> None:
        index = self._random.randrange(0, self.led_count)
        direction, color, level = self._pixels[index]
        if self._random.randrange(0, 100) < self.density and direction == 0:
            self._pixels[index] = (
                1,
                self._random.choice(self.colors),
                level + self.speed,
            )


class _WhiteTwinkleRenderer(BaseModel):
    led_count: int
    density: int = 80
    speed: int = 2
    max_bright: int = 255
    seed: int | None = None

    _twinkle: _TwinkleRenderer = PrivateAttr()

    @model_validator(mode="after")
    def validate_white_twinkle(self) -> _WhiteTwinkleRenderer:
        self._twinkle = _TwinkleRenderer(
            led_count=self.led_count,
            colors=((255, 255, 255),),
            density=self.density,
            speed=self.speed,
            max_bright=self.max_bright,
            seed=self.seed,
        )
        return self

    def next_frame(self) -> NDArray[np.uint8]:
        return self._twinkle.next_frame()


class _FrameRenderer(Protocol):
    def next_frame(self) -> NDArray[np.uint8]:
        pass


class BiblioPixelState(State):
    renderer: object


class ColorFill(Animation[BiblioPixelState]):
    color: RGB = (255, 0, 0)

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_ColorFillRenderer(led_count=device.led_count, color=self.color)
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class ColorChase(Animation[BiblioPixelState]):
    color: RGB = (255, 0, 0)
    width: int = 1
    start: int = 0
    end: int | None = None
    step: int = 1

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_ColorChaseRenderer(
                led_count=device.led_count,
                color=self.color,
                width=self.width,
                start=self.start,
                end=self.end,
                step=self.step,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class ColorWipe(Animation[BiblioPixelState]):
    color: RGB = (255, 0, 0)
    start: int = 0
    end: int | None = None
    step: int = 1

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_ColorWipeRenderer(
                led_count=device.led_count,
                color=self.color,
                start=self.start,
                end=self.end,
                step=self.step,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class Alternates(Animation[BiblioPixelState]):
    color1: RGB = (255, 255, 255)
    color2: RGB = (0, 0, 0)
    max_led: int | None = None

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_AlternatesRenderer(
                led_count=device.led_count,
                color1=self.color1,
                color2=self.color2,
                max_led=self.max_led,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class ColorPattern(Animation[BiblioPixelState]):
    colors: tuple[RGB, ...] = DEFAULT_PATTERN
    width: int = 1
    reverse: bool = False

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_ColorPatternRenderer(
                led_count=device.led_count,
                colors=self.colors,
                width=self.width,
                reverse=self.reverse,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class ColorFade(Animation[BiblioPixelState]):
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    level_step: int = 5
    start: int = 0
    end: int | None = None

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_ColorFadeRenderer(
                led_count=device.led_count,
                colors=self.colors,
                level_step=self.level_step,
                start=self.start,
                end=self.end,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class PartyMode(Animation[BiblioPixelState]):
    colors: tuple[RGB, ...] = DEFAULT_PATTERN

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_PartyModeRenderer(led_count=device.led_count, colors=self.colors)
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class FireFlies(Animation[BiblioPixelState]):
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    width: int = 1
    count: int = 1
    start: int = 0
    end: int | None = None
    seed: int | None = None

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_FireFliesRenderer(
                led_count=device.led_count,
                colors=self.colors,
                width=self.width,
                count=self.count,
                start=self.start,
                end=self.end,
                seed=self.seed,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class SaberBlade(Animation[BiblioPixelState]):
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    speed: int = 1

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_SaberBladeRenderer(
                led_count=device.led_count,
                colors=self.colors,
                speed=self.speed,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class Rainbow(Animation[BiblioPixelState]):
    start: int = 0
    end: int | None = None
    step: int = 1

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_RainbowRenderer(
                led_count=device.led_count,
                start=self.start,
                end=self.end,
                step=self.step,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class RainbowCycle(Rainbow):
    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_RainbowCycleRenderer(
                led_count=device.led_count,
                start=self.start,
                end=self.end,
                step=self.step,
            )
        )


class LinearRainbow(Animation[BiblioPixelState]):
    max_led: int | None = None
    individual_pixel: bool = False
    step: int = 1

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_LinearRainbowRenderer(
                led_count=device.led_count,
                max_led=self.max_led,
                individual_pixel=self.individual_pixel,
                step=self.step,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class HalvesRainbow(Animation[BiblioPixelState]):
    max_led: int | None = None
    center_out: bool = True
    rainbow_inc: int = 4
    step: int = 1

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_HalvesRainbowRenderer(
                led_count=device.led_count,
                max_led=self.max_led,
                center_out=self.center_out,
                rainbow_inc=self.rainbow_inc,
                step=self.step,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class LarsonScanner(Animation[BiblioPixelState]):
    color: RGB = (255, 0, 0)
    tail: int = 2
    start: int = 0
    end: int | None = None
    step: int = 1
    rainbow: bool = False

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_LarsonScannerRenderer(
                led_count=device.led_count,
                color=self.color,
                tail=self.tail,
                start=self.start,
                end=self.end,
                step=self.step,
                rainbow=self.rainbow,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class Pulse(Animation[BiblioPixelState]):
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    tail: int = 2
    chance: int = 30
    min_speed: int = 1
    max_speed: int = 5
    seed: int | None = None

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_PulseRenderer(
                led_count=device.led_count,
                colors=self.colors,
                tail=self.tail,
                chance=self.chance,
                min_speed=self.min_speed,
                max_speed=self.max_speed,
                seed=self.seed,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class PixelPingPong(Animation[BiblioPixelState]):
    color: RGB = (255, 255, 255)
    max_led: int | None = None
    total_pixels: int = 1
    fade_delay: int = 1

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_PixelPingPongRenderer(
                led_count=device.led_count,
                color=self.color,
                max_led=self.max_led,
                total_pixels=self.total_pixels,
                fade_delay=self.fade_delay,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class Searchlights(Animation[BiblioPixelState]):
    colors: tuple[RGB, ...] = SEARCHLIGHT_COLORS
    tail: int = 5
    start: int = 0
    end: int | None = None
    seed: int | None = None

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_SearchlightsRenderer(
                led_count=device.led_count,
                colors=self.colors,
                tail=self.tail,
                start=self.start,
                end=self.end,
                seed=self.seed,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class Wave(Animation[BiblioPixelState]):
    color: RGB = (255, 0, 0)
    cycles: int = 2
    start: int = 0
    end: int | None = None
    moving: bool = False

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_WaveRenderer(
                led_count=device.led_count,
                color=self.color,
                cycles=self.cycles,
                start=self.start,
                end=self.end,
                moving=self.moving,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class Twinkle(Animation[BiblioPixelState]):
    colors: tuple[RGB, ...] = DEFAULT_PATTERN
    density: int = 20
    speed: int = 2
    max_bright: int = 255
    seed: int | None = None

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_TwinkleRenderer(
                led_count=device.led_count,
                colors=self.colors,
                density=self.density,
                speed=self.speed,
                max_bright=self.max_bright,
                seed=self.seed,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


class WhiteTwinkle(Animation[BiblioPixelState]):
    density: int = 80
    speed: int = 2
    max_bright: int = 255
    seed: int | None = None

    def initial_state(self, device: Device) -> BiblioPixelState:
        return BiblioPixelState(
            renderer=_TwinkleRenderer(
                led_count=device.led_count,
                colors=((255, 255, 255),),
                density=self.density,
                speed=self.speed,
                max_bright=self.max_bright,
                seed=self.seed,
            )
        )

    def render(self, device: Device, state: BiblioPixelState) -> NDArray[np.uint8]:
        state.frame += 1
        return cast(_FrameRenderer, state.renderer).next_frame()


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


def validate_palette(colors: tuple[RGB, ...]) -> None:
    if not colors:
        raise ValueError("colors must not be empty")
    for color in colors:
        validate_rgb(color)


def resolve_end(led_count: int, end: int | None) -> int:
    if end is None or end < 0 or end >= led_count:
        return led_count - 1
    return end


def bounded_tail(tail: int, size: int) -> int:
    bounded = tail + 1
    if bounded >= size // 2:
        bounded = (size // 2) - 1
    return max(1, bounded)


def scale_color(color: RGB, level: int | float) -> RGB:
    level = max(0, min(255, round(level)))
    return (
        round(color[0] * level / 255),
        round(color[1] * level / 255),
        round(color[2] * level / 255),
    )


def blend_color(frame: NDArray[np.uint8], index: int, color: RGB) -> None:
    if 0 <= index < len(frame):
        frame[index] = ((frame[index].astype(np.uint16) + np.array(color)) // 2).astype(
            np.uint8
        )


def wheel_color(position: int | float) -> RGB:
    position = round(position) % 256
    if position < 85:
        return 255 - position * 3, position * 3, 0
    if position < 170:
        position -= 85
        return 0, 255 - position * 3, position * 3
    position -= 170
    return position * 3, 0, 255 - position * 3


def wave_color(color: RGB, value: float) -> RGB:
    if value >= 0:
        level = 1 - value
        return (
            round(255 - (255 - color[0]) * level),
            round(255 - (255 - color[1]) * level),
            round(255 - (255 - color[2]) * level),
        )
    level = value + 1
    return (
        round(color[0] * level),
        round(color[1] * level),
        round(color[2] * level),
    )
