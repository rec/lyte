from __future__ import annotations

import base64
import json
from math import isfinite
from pathlib import Path

from .. import animation, rendering
from .template import HTML_TEMPLATE


def render_animation_html(
    prepared: rendering.PreparedAnimation,
    path: Path,
    duration: float = 10.0,
    led_size: float = 1.0,
    name: str | None = None,
) -> None:
    path.write_text(animation_document(prepared, duration, led_size, name))


def animation_document(
    prepared: rendering.PreparedAnimation,
    duration: float = 10.0,
    led_size: float = 1.0,
    name: str | None = None,
) -> str:
    if duration <= 0:
        raise ValueError('duration must be greater than zero')
    if led_size <= 0:
        raise ValueError('led_size must be greater than zero')
    if prepared.output.components != ['red', 'green', 'blue']:
        raise ValueError('HTML preview requires red, green, blue components')
    points = [
        [*light.position, *([0.0] * (2 - len(light.position)))]
        for light in prepared.output.layout.lights
    ]
    payload = {
        'name': name or prepared.output.layout.name,
        'coords': [point[:2] for point in points],
        'fps': prepared.fps,
        'frames': encoded_frames(prepared, duration),
        'ledSize': led_size,
    }
    return HTML_TEMPLATE.replace('__LYTE_PREVIEW_DATA__', safe_json(payload))


def encoded_frames(prepared: rendering.PreparedAnimation, duration: float) -> list[str]:
    frame_count = preview_frame_count(
        prepared.fps,
        duration,
        len(prepared.output.layout.lights) * len(prepared.output.components),
    )
    frames = []
    for _ in range(frame_count):
        frame = animation.byte_light_frame_from_float(prepared.render())
        frames.append(base64.b64encode(memoryview(frame).cast('B')).decode('ascii'))
    return frames


def preview_frame_count(fps: float, duration: float, frame_bytes: int) -> int:
    samples = fps * duration
    if not isfinite(samples) or samples <= 0:
        raise ValueError('preview duration and frame rate must be positive and finite')
    count = max(1, round(samples))
    if count > 10000 or count * frame_bytes > 32 * 1024 * 1024:
        raise ValueError(
            'preview exceeds 10000 frames or 32 MiB of frame data; '
            'reduce duration or layout size'
        )
    return count


def safe_json(value: object) -> str:
    return json.dumps(value, separators=(',', ':')).replace('</', '<\\/')
