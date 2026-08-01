from __future__ import annotations

from typing import Protocol

from .colors import RGB


class RainbowStateLike(Protocol):
    position: int
    frame: int


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


def advance_rainbow(state: RainbowStateLike, step: int) -> None:
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
