"""Small numpy ports of simple BiblioPixel strip animations."""

from __future__ import annotations

import math
import random

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, model_validator

from ..animation import Animation, Device, State

RGB = tuple[int, int, int]
DEFAULT_PATTERN: tuple[RGB, ...] = ((255, 0, 0), (0, 255, 0), (0, 0, 255))
SEARCHLIGHT_COLORS: tuple[RGB, ...] = (
    (60, 179, 113),
    (147, 112, 219),
    (199, 21, 133),
)


class ColorFill(Animation[State]):
    color: RGB = (255, 0, 0)

    @model_validator(mode="after")
    def validate_color_fill(self) -> ColorFill:
        validate_rgb(self.color)
        return self

    def render(self, device: Device, state: State) -> NDArray[np.uint8]:
        frame = np.empty((device.led_count, 3), dtype=np.uint8)
        frame[:] = self.color
        state.frame += 1
        return frame


class ColorChaseState(State):
    position: int = 0


class ColorChase(Animation[ColorChaseState]):
    color: RGB = (255, 0, 0)
    width: int = 1
    start: int = 0
    end: int | None = None
    step: int = 1

    @model_validator(mode="after")
    def validate_color_chase(self) -> ColorChase:
        validate_rgb(self.color)
        validate_step(self.step)
        if self.width < 1:
            raise ValueError("width must be at least 1")
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> ColorChaseState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return ColorChaseState()

    def render(self, device: Device, state: ColorChaseState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        end = resolve_end(device.led_count, self.end)
        position = self.start + state.position
        for i in range(self.width):
            index = position + i
            if self.start <= index <= end:
                frame[index] = self.color
        state.position = advance_position(self.start, end, state.position, self.step)
        state.frame += 1
        return frame


class ColorWipeState(State):
    frame_buffer: NDArray[np.uint8]
    position: int = 0


class ColorWipe(Animation[ColorWipeState]):
    color: RGB = (255, 0, 0)
    start: int = 0
    end: int | None = None
    step: int = 1

    @model_validator(mode="after")
    def validate_color_wipe(self) -> ColorWipe:
        validate_rgb(self.color)
        validate_step(self.step)
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> ColorWipeState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return ColorWipeState(
            frame_buffer=np.zeros((device.led_count, 3), dtype=np.uint8)
        )

    def render(self, device: Device, state: ColorWipeState) -> NDArray[np.uint8]:
        end = resolve_end(device.led_count, self.end)
        if state.position == 0:
            state.frame_buffer[:] = 0
        for i in range(self.step):
            index = self.start + state.position - i
            if self.start <= index <= end:
                state.frame_buffer[index] = self.color
        state.position = advance_position(self.start, end, state.position, self.step)
        state.frame += 1
        return state.frame_buffer


class AlternatesState(State):
    positive: bool = True


class Alternates(Animation[AlternatesState]):
    color1: RGB = (255, 255, 255)
    color2: RGB = (0, 0, 0)
    max_led: int | None = None

    @model_validator(mode="after")
    def validate_alternates(self) -> Alternates:
        validate_rgb(self.color1)
        validate_rgb(self.color2)
        return self

    def initial_state(self, device: Device) -> AlternatesState:
        if resolve_end(device.led_count, self.max_led) < 0:
            raise ValueError("max_led must not be negative")
        return AlternatesState()

    def render(self, device: Device, state: AlternatesState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        for i in range(resolve_end(device.led_count, self.max_led) + 1):
            odd = bool(i % 2)
            frame[i] = self.color1 if odd == state.positive else self.color2
        state.positive = not state.positive
        state.frame += 1
        return frame


class ColorPatternState(State):
    offset: int = 0


class ColorPattern(Animation[ColorPatternState]):
    colors: tuple[RGB, ...] = DEFAULT_PATTERN
    width: int = 1
    reverse: bool = False

    @model_validator(mode="after")
    def validate_color_pattern(self) -> ColorPattern:
        validate_palette(self.colors)
        if self.width < 1:
            raise ValueError("width must be at least 1")
        return self

    def initial_state(self, device: Device) -> ColorPatternState:
        return ColorPatternState()

    def render(self, device: Device, state: ColorPatternState) -> NDArray[np.uint8]:
        frame = np.empty((device.led_count, 3), dtype=np.uint8)
        total_width = self.width * len(self.colors)
        for i in range(device.led_count):
            color_index = ((i + state.offset) % total_width) // self.width
            frame[i] = self.colors[color_index]
        state.offset += -1 if self.reverse else 1
        state.frame += 1
        return frame


class ColorFadeState(State):
    levels: list[int]
    position: int = 0


class ColorFade(Animation[ColorFadeState]):
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    level_step: int = 5
    start: int = 0
    end: int | None = None

    @model_validator(mode="after")
    def validate_color_fade(self) -> ColorFade:
        validate_palette(self.colors)
        if self.level_step < 1:
            raise ValueError("level_step must be at least 1")
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> ColorFadeState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        levels = list(range(30, 256, self.level_step))
        return ColorFadeState(levels=levels + list(reversed(levels[:-1])))

    def render(self, device: Device, state: ColorFadeState) -> NDArray[np.uint8]:
        color_index, level_index = divmod(state.position, len(state.levels))
        color = scale_color(
            self.colors[color_index % len(self.colors)], state.levels[level_index]
        )
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        frame[self.start : resolve_end(device.led_count, self.end) + 1] = color
        state.position += 1
        state.frame += 1
        return frame


class PartyModeState(State):
    position: int = 0


class PartyMode(Animation[PartyModeState]):
    colors: tuple[RGB, ...] = DEFAULT_PATTERN

    @model_validator(mode="after")
    def validate_party_mode(self) -> PartyMode:
        validate_palette(self.colors)
        return self

    def initial_state(self, device: Device) -> PartyModeState:
        return PartyModeState()

    def render(self, device: Device, state: PartyModeState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        if state.position % 2 == 0:
            frame[:] = self.colors[(state.position // 2) % len(self.colors)]
        state.position += 1
        state.frame += 1
        return frame


class FireFliesState(State):
    random: random.Random


class FireFlies(Animation[FireFliesState]):
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    width: int = 1
    count: int = 1
    start: int = 0
    end: int | None = None
    seed: int | None = None

    @model_validator(mode="after")
    def validate_fire_flies(self) -> FireFlies:
        validate_palette(self.colors)
        if self.width < 1:
            raise ValueError("width must be at least 1")
        if self.count < 1:
            raise ValueError("count must be at least 1")
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> FireFliesState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return FireFliesState(random=random.Random(self.seed))

    def render(self, device: Device, state: FireFliesState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        end = resolve_end(device.led_count, self.end)
        for _ in range(self.count):
            pixel = state.random.randint(self.start, end)
            color = state.random.choice(self.colors)
            frame[pixel : min(pixel + self.width, end + 1)] = color
        state.frame += 1
        return frame


class SaberBladeState(State):
    color_index: int = 0
    position: int = 0
    speed: int


class SaberBlade(Animation[SaberBladeState]):
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    speed: int = 1

    @model_validator(mode="after")
    def validate_saber_blade(self) -> SaberBlade:
        validate_palette(self.colors)
        if self.speed == 0:
            raise ValueError("speed must not be zero")
        return self

    def initial_state(self, device: Device) -> SaberBladeState:
        return SaberBladeState(speed=self.speed)

    def render(self, device: Device, state: SaberBladeState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        if state.position > 0:
            frame[: min(state.position, device.led_count)] = self.colors[
                state.color_index % len(self.colors)
            ]
        state.position += state.speed
        if state.speed > 0 and state.position + state.speed > device.led_count:
            state.speed *= -1
        elif state.speed < 0 and state.position <= 0:
            state.position = 0
            state.color_index += 1
            state.speed *= -1
        state.frame += 1
        return frame


class RainbowState(State):
    position: int = 0


class Rainbow(Animation[RainbowState]):
    start: int = 0
    end: int | None = None
    step: int = 1

    @model_validator(mode="after")
    def validate_rainbow(self) -> Rainbow:
        validate_step(self.step)
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> RainbowState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return RainbowState()

    def render(self, device: Device, state: RainbowState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        for i in range(span_size(device.led_count, self.start, self.end)):
            frame[self.start + i] = wheel_color((i + state.position) % 255)
        advance_rainbow(state, self.step)
        return frame


class RainbowCycle(Rainbow):
    def render(self, device: Device, state: RainbowState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        size = span_size(device.led_count, self.start, self.end)
        for i in range(size):
            frame[self.start + i] = wheel_color(round(i * 255 / size + state.position))
        advance_rainbow(state, self.step)
        return frame


class LinearRainbowState(State):
    current: int = 0
    frame_buffer: NDArray[np.uint8]
    position: int = 0


class LinearRainbow(Animation[LinearRainbowState]):
    max_led: int | None = None
    individual_pixel: bool = False
    step: int = 1

    @model_validator(mode="after")
    def validate_linear_rainbow(self) -> LinearRainbow:
        validate_step(self.step)
        return self

    def initial_state(self, device: Device) -> LinearRainbowState:
        return LinearRainbowState(
            frame_buffer=np.zeros((device.led_count, 3), dtype=np.uint8)
        )

    def render(self, device: Device, state: LinearRainbowState) -> NDArray[np.uint8]:
        max_led = resolve_end(device.led_count, self.max_led)
        if self.individual_pixel:
            state.frame_buffer[state.current] = wheel_color(state.position)
        else:
            state.frame_buffer[: state.current + 1] = wheel_color(state.position)
        state.position += self.step
        state.current = 0 if state.current == max_led else state.current + self.step
        if state.current > max_led:
            state.current = max_led
        state.frame += 1
        return state.frame_buffer


class HalvesRainbowState(State):
    current: int = 0
    frame_buffer: NDArray[np.uint8]
    position: int = 0


class HalvesRainbow(Animation[HalvesRainbowState]):
    max_led: int | None = None
    center_out: bool = True
    rainbow_inc: int = 4
    step: int = 1

    @model_validator(mode="after")
    def validate_halves_rainbow(self) -> HalvesRainbow:
        validate_step(self.step)
        if self.rainbow_inc < 0:
            raise ValueError("rainbow_inc must not be negative")
        return self

    def initial_state(self, device: Device) -> HalvesRainbowState:
        return HalvesRainbowState(
            frame_buffer=np.zeros((device.led_count, 3), dtype=np.uint8)
        )

    def render(self, device: Device, state: HalvesRainbowState) -> NDArray[np.uint8]:
        max_led = resolve_end(device.led_count, self.max_led)
        color = wheel_color(state.position)
        center = max_led / 2
        center_floor = math.floor(center)
        center_ceil = math.ceil(center)
        if self.center_out:
            state.frame_buffer[int(center_floor - state.current)] = color
            state.frame_buffer[int(center_ceil + state.current)] = color
        else:
            state.frame_buffer[state.current] = color
            state.frame_buffer[max_led - state.current] = color
        state.position += self.step + self.rainbow_inc
        state.current = (
            0 if state.current == center_floor else state.current + self.step
        )
        if state.current > center_floor:
            state.current = center_floor
        state.frame += 1
        return state.frame_buffer


class LarsonScannerState(State):
    direction: int = -1
    position: int = 0
    tail: int = 1


class LarsonScanner(Animation[LarsonScannerState]):
    color: RGB = (255, 0, 0)
    tail: int = 2
    start: int = 0
    end: int | None = None
    step: int = 1
    rainbow: bool = False

    @model_validator(mode="after")
    def validate_larson_scanner(self) -> LarsonScanner:
        validate_rgb(self.color)
        validate_step(self.step)
        if self.tail < 0:
            raise ValueError("tail must not be negative")
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> LarsonScannerState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return LarsonScannerState(
            tail=bounded_tail(
                self.tail, span_size(device.led_count, self.start, self.end)
            )
        )

    def render(self, device: Device, state: LarsonScannerState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        end = resolve_end(device.led_count, self.end)
        center = self.start + state.position
        color = wheel_color(state.position) if self.rainbow else self.color
        fade = 256 // state.tail
        for i in range(state.tail):
            scaled = scale_color(color, max(0, 255 - fade * i))
            for index in (center - i, center + i):
                if self.start <= index <= end:
                    frame[index] = scaled
        if self.start + state.position >= end:
            state.direction = -state.direction
        elif state.position <= 0:
            state.direction = -state.direction
        state.position += state.direction * self.step
        state.frame += 1
        return frame


class PulseState(State):
    color: RGB | None = None
    position: int = 0
    random: random.Random
    speed: int = 0
    tail: int = 1


class Pulse(Animation[PulseState]):
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    tail: int = 2
    chance: int = 30
    min_speed: int = 1
    max_speed: int = 5
    seed: int | None = None

    @model_validator(mode="after")
    def validate_pulse(self) -> Pulse:
        validate_palette(self.colors)
        if self.tail < 0:
            raise ValueError("tail must not be negative")
        if self.chance < 0 or self.chance > 100:
            raise ValueError("chance must be between 0 and 100")
        if self.min_speed < 1 or self.max_speed <= self.min_speed:
            raise ValueError("min_speed and max_speed must define a non-empty range")
        return self

    def initial_state(self, device: Device) -> PulseState:
        return PulseState(
            tail=bounded_tail(self.tail, device.led_count),
            random=random.Random(self.seed),
        )

    def render(self, device: Device, state: PulseState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        if state.speed == 0 and state.random.randrange(0, 100) <= self.chance:
            state.color = state.random.choice(self.colors)
            state.speed = state.random.randrange(self.min_speed, self.max_speed)
            state.position = 0
        if state.speed > 0 and state.color is not None:
            fade = 256 // state.tail
            for i in range(state.tail):
                scaled = scale_color(state.color, max(0, 255 - fade * i))
                for index in (state.position - i, state.position + i):
                    if 0 <= index < device.led_count:
                        frame[index] = scaled
            if state.position > device.led_count + state.tail:
                state.speed = 0
            else:
                state.position += state.speed
        state.frame += 1
        return frame


class PixelPingPongState(State):
    current: int = 0
    frame_buffer: NDArray[np.uint8]
    positive: bool = True


class PixelPingPong(Animation[PixelPingPongState]):
    color: RGB = (255, 255, 255)
    max_led: int | None = None
    total_pixels: int = 1
    fade_delay: int = 1

    @model_validator(mode="after")
    def validate_pixel_ping_pong(self) -> PixelPingPong:
        validate_rgb(self.color)
        if self.total_pixels < 1:
            raise ValueError("total_pixels must be at least 1")
        if self.fade_delay < 1:
            raise ValueError("fade_delay must be at least 1")
        return self

    def initial_state(self, device: Device) -> PixelPingPongState:
        return PixelPingPongState(
            frame_buffer=np.zeros((device.led_count, 3), dtype=np.uint8)
        )

    def render(self, device: Device, state: PixelPingPongState) -> NDArray[np.uint8]:
        decrement = np.array(self.color, dtype=np.float64) / self.fade_delay
        faded = state.frame_buffer.astype(np.float64) - decrement
        state.frame_buffer[:] = np.maximum(faded, 0).astype(np.uint8)
        max_led = resolve_end(device.led_count, self.max_led)
        end = min(state.current + self.total_pixels, max_led + 1)
        state.frame_buffer[state.current : end] = self.color
        state.current += 1 if state.positive else -1
        if state.current + self.total_pixels - 1 >= max_led:
            state.positive = False
        if state.current <= 0:
            state.current = 0
            state.positive = True
        state.frame += 1
        return state.frame_buffer


class SearchlightsState(State):
    directions: list[int]
    random: random.Random
    steps: list[int]
    tail: int = 1


class Searchlights(Animation[SearchlightsState]):
    colors: tuple[RGB, ...] = SEARCHLIGHT_COLORS
    tail: int = 5
    start: int = 0
    end: int | None = None
    seed: int | None = None

    @model_validator(mode="after")
    def validate_searchlights(self) -> Searchlights:
        validate_palette(self.colors)
        if len(self.colors) < 3:
            raise ValueError("colors must contain at least three colors")
        if self.tail < 0:
            raise ValueError("tail must not be negative")
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> SearchlightsState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return SearchlightsState(
            directions=[1, 1, 1],
            random=random.Random(self.seed),
            steps=[1, 1, 1],
            tail=bounded_tail(
                self.tail, span_size(device.led_count, self.start, self.end)
            ),
        )

    def render(self, device: Device, state: SearchlightsState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        end = resolve_end(device.led_count, self.end)
        fade = 256 / state.tail
        for i in range(3):
            position = self.start + state.steps[i]
            color = self.colors[i]
            blend_color(frame, position, color)
            for j in range(1, state.tail):
                scaled = scale_color(color, round(255 - fade * j))
                blend_color(frame, position - j, scaled)
                blend_color(frame, position + j, scaled)
            if position >= end:
                state.directions[i] = -1
            elif position <= self.start:
                state.directions[i] = 1
            if state.random.random() > i * 0.05:
                state.steps[i] += state.directions[i]
        state.frame += 1
        return frame


class WaveState(State):
    move_step: int = 0
    position: int = 0


class Wave(Animation[WaveState]):
    color: RGB = (255, 0, 0)
    cycles: int = 2
    start: int = 0
    end: int | None = None
    moving: bool = False

    @model_validator(mode="after")
    def validate_wave(self) -> Wave:
        validate_rgb(self.color)
        if self.cycles < 1:
            raise ValueError("cycles must be at least 1")
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> WaveState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return WaveState()

    def render(self, device: Device, state: WaveState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        size = span_size(device.led_count, self.start, self.end)
        for i in range(size):
            if self.moving:
                value = math.sin(math.pi * self.cycles * i / size + state.move_step)
            else:
                value = math.sin(math.pi * self.cycles * state.position * i / size)
            frame[self.start + i] = wave_color(self.color, value)
        if self.moving:
            state.move_step += 2
            if state.move_step >= size:
                state.move_step = 0
        else:
            state.position += 1
        state.frame += 1
        return frame


class TwinklePixel(BaseModel):
    direction: int = 0
    color: RGB = (0, 0, 0)
    level: int = 0


class TwinkleState(State):
    pixels: list[TwinklePixel]
    random: random.Random


class Twinkle(Animation[TwinkleState]):
    colors: tuple[RGB, ...] = DEFAULT_PATTERN
    density: int = 20
    speed: int = 2
    max_bright: int = 255
    seed: int | None = None

    @model_validator(mode="after")
    def validate_twinkle(self) -> Twinkle:
        validate_palette(self.colors)
        return self

    @property
    def bounded_speed(self) -> int:
        return max(2, min(100, self.speed))

    @property
    def bounded_density(self) -> int:
        return max(2, min(100, self.density))

    @property
    def bounded_max_bright(self) -> int:
        return max(5, min(255, self.max_bright))

    def initial_state(self, device: Device) -> TwinkleState:
        return TwinkleState(
            pixels=[TwinklePixel() for _ in range(device.led_count)],
            random=random.Random(self.seed),
        )

    def render(self, device: Device, state: TwinkleState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        pick_twinkle_led(state, self.colors, self.bounded_density, self.bounded_speed)
        for i, pixel in enumerate(state.pixels):
            if pixel.direction == 1:
                pixel.level += self.bounded_speed
                if pixel.level > self.bounded_max_bright:
                    pixel.level = self.bounded_max_bright
                    pixel.direction = 2
                frame[i] = scale_color(pixel.color, pixel.level)
            elif pixel.direction == 2:
                pixel.level -= self.bounded_speed
                if pixel.level < 0:
                    pixel.level = 0
                    pixel.direction = 0
                frame[i] = scale_color(pixel.color, pixel.level)
        state.frame += 1
        return frame


class WhiteTwinkle(Twinkle):
    colors: tuple[RGB, ...] = ((255, 255, 255),)
    density: int = 80


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


def validate_start(start: int) -> None:
    if start < 0:
        raise ValueError("start must not be negative")


def validate_step(step: int) -> None:
    if step < 1:
        raise ValueError("step must be at least 1")


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


def span_size(led_count: int, start: int, end: int | None) -> int:
    return resolve_end(led_count, end) - start + 1


def advance_position(start: int, end: int, position: int, step: int) -> int:
    position += step
    overflow = (start + position) - end
    if overflow >= 0:
        return overflow
    return position


def advance_rainbow(state: RainbowState, step: int) -> None:
    state.position += step
    overflow = state.position - 256
    if overflow >= 0:
        state.position = overflow
    state.frame += 1


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


def pick_twinkle_led(
    state: TwinkleState,
    colors: tuple[RGB, ...],
    density: int,
    speed: int,
) -> None:
    index = state.random.randrange(0, len(state.pixels))
    pixel = state.pixels[index]
    if state.random.randrange(0, 100) < density and pixel.direction == 0:
        pixel.direction = 1
        pixel.color = state.random.choice(colors)
        pixel.level += speed
