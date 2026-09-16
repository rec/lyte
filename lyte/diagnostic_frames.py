"""Pure frame generation for device diagnostics."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from .animation import Device
from .animations.colors import RGB


def gradient_frame(led_count: int, start: RGB, end: RGB) -> NDArray[np.uint8]:
    if led_count <= 0:
        raise ValueError('led_count must be greater than zero')
    if led_count == 1:
        return np.array([start], dtype=np.uint8)
    start_array = np.array(start, dtype=np.float32)
    end_array = np.array(end, dtype=np.float32)
    positions = np.linspace(0.0, 1.0, led_count, dtype=np.float32)[:, np.newaxis]
    return np.rint(start_array * (1.0 - positions) + end_array * positions).astype(
        np.uint8
    )


def blend_frames(
    first_frame: NDArray[np.uint8],
    second_frame: NDArray[np.uint8],
    progress: float,
) -> NDArray[np.uint8]:
    if first_frame.shape != second_frame.shape:
        raise ValueError('cannot blend frames with different shapes')
    progress = max(0.0, min(1.0, progress))
    blended = (
        first_frame.astype(np.float32) * (1.0 - progress)
        + second_frame.astype(np.float32) * progress
    )
    return np.rint(blended).astype(np.uint8)


def dispersed_pixel_order(led_count: int) -> NDArray[np.int64]:
    if led_count <= 0:
        raise ValueError('led_count must be greater than zero')
    if led_count == 1:
        return np.array([0], dtype=np.int64)
    midpoint = led_count / 2
    stride = min(
        (i for i in range(1, led_count) if math.gcd(i, led_count) == 1),
        key=lambda i: (abs(i - midpoint), i),
    )
    return np.fromiter(
        ((i * stride) % led_count for i in range(led_count)),
        dtype=np.int64,
        count=led_count,
    )


def temporal_dither_grayscale_frame(
    device: Device,
    start: int,
    end: int,
    index: int,
    frame_count: int,
    order: NDArray[np.int64],
) -> NDArray[np.uint8]:
    if frame_count < 2:
        raise ValueError('frame_count must be at least 2')
    if not 0 <= start <= 255 or not 0 <= end <= 255:
        raise ValueError('start and end must be 8-bit channel values')
    if len(order) != device.led_count:
        raise ValueError('order must have one entry per LED')
    progress = index / (frame_count - 1)
    ideal = start + (end - start) * max(0.0, min(1.0, progress))
    lower = math.floor(ideal)
    upper = math.ceil(ideal)
    fraction = ideal - lower
    high_count = round(fraction * device.led_count)
    frame = np.full((device.led_count, 3), lower, dtype=np.uint8)
    if high_count and upper != lower:
        offset = lower % device.led_count
        selected = np.concatenate((order[offset:], order[:offset]))[:high_count]
        frame[selected] = upper
    return frame


def verify_primary_channels_frame(
    device: Device,
    index: int,
    frame_count: int,
) -> NDArray[np.uint8]:
    colors: tuple[RGB, ...] = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255))
    color = colors[(index * len(colors)) // frame_count % len(colors)]
    return solid_rgb_level_frame(device, color)


def verify_moving_gradient_frame(
    device: Device,
    index: int,
    frame_count: int,
) -> NDArray[np.uint8]:
    frame = gradient_frame(device.led_count, (255, 0, 80), (0, 160, 255))
    return np.roll(frame, round(index * device.led_count / frame_count), axis=0)


def verify_crossfade_frame(
    device: Device,
    index: int,
    frame_count: int,
) -> NDArray[np.uint8]:
    first_frame = gradient_frame(device.led_count, *LOW_CONTRAST_BLEND)
    second_frame = gradient_frame(device.led_count, *HIGH_CONTRAST_BLEND)
    cycle = math.sin((index / frame_count) * math.tau) * 0.5 + 0.5
    return blend_frames(first_frame, second_frame, cycle)


def verify_temporal_dither_frame(
    device: Device,
    index: int,
    frame_count: int,
) -> NDArray[np.uint8]:
    if frame_count < 2:
        raise ValueError('frame_count must be at least 2')
    half = max(2, frame_count // 2)
    if index < half:
        return temporal_dither_grayscale_frame(
            device,
            0,
            32,
            index,
            half,
            dispersed_pixel_order(device.led_count),
        )
    return temporal_dither_grayscale_frame(
        device,
        32,
        0,
        index - half,
        max(2, frame_count - half),
        dispersed_pixel_order(device.led_count),
    )


def solid_grayscale_frame(device: Device, level: int) -> NDArray[np.uint8]:
    if not 0 <= level <= 255:
        raise ValueError('level must be an 8-bit channel value')
    return np.full((device.led_count, 3), level, dtype=np.uint8)


def solid_rgb_level_frame(device: Device, level: RGB) -> NDArray[np.uint8]:
    if any(not 0 <= i <= 255 for i in level):
        raise ValueError('levels must be 8-bit channel values')
    return np.full((device.led_count, 3), level, dtype=np.uint8)


LOW_CONTRAST_BLEND: tuple[RGB, RGB] = ((255, 0, 80), (0, 160, 255))
HIGH_CONTRAST_BLEND: tuple[RGB, RGB] = ((0, 255, 120), (255, 240, 0))
