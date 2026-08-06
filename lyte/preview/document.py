from __future__ import annotations

import base64
import json
from pathlib import Path

from ..animation import (
    Animation,
    Device,
    State,
    byte_light_frame_from_float,
    validate_frame,
)
from .layout import Layout
from .template import HTML_TEMPLATE


def render_animation_html(
    animation: Animation,
    layout: Layout,
    path: Path,
    fps: float = 20.0,
    duration: float = 10.0,
    led_size: float = 1.0,
) -> None:
    path.write_text(animation_document(animation, layout, fps, duration, led_size))


def animation_document(
    animation: Animation,
    layout: Layout,
    fps: float = 20.0,
    duration: float = 10.0,
    led_size: float = 1.0,
) -> str:
    if fps <= 0:
        raise ValueError('fps must be greater than zero')
    if duration <= 0:
        raise ValueError('duration must be greater than zero')
    if led_size <= 0:
        raise ValueError('led_size must be greater than zero')

    points = layout.points()
    device = Device(led_count=len(points))
    state = animation.initial_state(device)
    state.fps = fps
    frames = encoded_frames(animation, device, state, fps, duration)
    payload = {
        'name': layout.name,
        'coords': points,
        'fps': fps,
        'frames': frames,
        'ledSize': led_size,
    }
    return HTML_TEMPLATE.replace('__LYTE_PREVIEW_DATA__', safe_json(payload))


def encoded_frames(
    animation: Animation,
    device: Device,
    state: State,
    fps: float,
    duration: float,
) -> list[str]:
    frame_count = max(1, round(fps * duration))
    frames = []
    for _ in range(frame_count):
        frame = byte_light_frame_from_float(
            validate_frame(device, animation.render(device, state))
        )
        frames.append(base64.b64encode(memoryview(frame).cast('B')).decode('ascii'))
    return frames


def safe_json(value: object) -> str:
    return json.dumps(value, separators=(',', ':')).replace('</', '<\\/')
