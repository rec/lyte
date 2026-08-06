from __future__ import annotations

import base64
import json
from pathlib import Path

from .. import animation
from .layout import Layout
from .template import HTML_TEMPLATE


def render_animation_html(
    source: animation.Animation,
    layout: Layout,
    path: Path,
    fps: float = 20.0,
    duration: float = 10.0,
    led_size: float = 1.0,
) -> None:
    path.write_text(animation_document(source, layout, fps, duration, led_size))


def animation_document(
    source: animation.Animation,
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
    device = animation.Device(led_count=len(points))
    state = source.initial_state(device)
    state.fps = fps
    frames = encoded_frames(source, device, state, fps, duration)
    payload = {
        'name': layout.name,
        'coords': points,
        'fps': fps,
        'frames': frames,
        'ledSize': led_size,
    }
    return HTML_TEMPLATE.replace('__LYTE_PREVIEW_DATA__', safe_json(payload))


def encoded_frames(
    source: animation.Animation,
    device: animation.Device,
    state: animation.State,
    fps: float,
    duration: float,
) -> list[str]:
    frame_count = max(1, round(fps * duration))
    frames = []
    for _ in range(frame_count):
        frame = animation.byte_light_frame_from_float(
            animation.validate_frame(device, source.render(device, state))
        )
        frames.append(base64.b64encode(memoryview(frame).cast('B')).decode('ascii'))
    return frames


def safe_json(value: object) -> str:
    return json.dumps(value, separators=(',', ':')).replace('</', '<\\/')
