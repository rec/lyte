"""Render Lyte animations as standalone HTML previews."""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from .animation import Animation, Device, State, validate_frame


class Layout(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = "layout"
    coords: list[list[float]] | None = None
    dims: list[int] | None = None
    spacing: float | list[float] = 1.0

    @model_validator(mode="after")
    def validate_layout(self) -> Layout:
        if (self.coords is None) == (self.dims is None):
            raise ValueError("Exactly one of coords and dims must be set")
        if self.coords is not None:
            if not self.coords:
                raise ValueError("coords must not be empty")
            for coord in self.coords:
                validate_coord(coord)
        if self.dims is not None:
            if len(self.dims) != 2:
                raise ValueError("dims must contain rows and columns")
            rows, columns = self.dims
            if rows <= 0 or columns <= 0:
                raise ValueError("dims rows and columns must be greater than zero")
        spacing = self.resolved_spacing
        if spacing[0] <= 0 or spacing[1] <= 0:
            raise ValueError("spacing must be greater than zero")
        return self

    @property
    def resolved_spacing(self) -> tuple[float, float]:
        if isinstance(self.spacing, int | float):
            return float(self.spacing), float(self.spacing)
        if len(self.spacing) != 2:
            raise ValueError("spacing must be a float or x, y pair")
        return float(self.spacing[0]), float(self.spacing[1])

    def points(self) -> list[list[float]]:
        if self.coords is not None:
            return self.coords
        if self.dims is None:
            raise ValueError("Exactly one of coords and dims must be set")
        rows, columns = self.dims
        x_spacing, y_spacing = self.resolved_spacing
        return [
            [column * x_spacing, row * y_spacing]
            for row in range(rows)
            for column in range(columns)
        ]


def render_animation_html(
    animation: Animation,
    layout: Layout,
    path: Path,
    fps: float = 20.0,
    duration: float = 10.0,
) -> None:
    path.write_text(animation_document(animation, layout, fps, duration))


def animation_document(
    animation: Animation,
    layout: Layout,
    fps: float = 20.0,
    duration: float = 10.0,
) -> str:
    if fps <= 0:
        raise ValueError("fps must be greater than zero")
    if duration <= 0:
        raise ValueError("duration must be greater than zero")

    points = layout.points()
    device = Device(led_count=len(points))
    state = animation.initial_state(device)
    state.fps = fps
    frames = encoded_frames(animation, device, state, fps, duration)
    payload = {
        "name": layout.name,
        "coords": points,
        "fps": fps,
        "frames": frames,
    }
    return HTML_TEMPLATE.replace("__LYTE_PREVIEW_DATA__", safe_json(payload))


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
        frame = validate_frame(device, animation.render(device, state))
        frames.append(base64.b64encode(memoryview(frame).cast("B")).decode("ascii"))
    return frames


def safe_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":")).replace("</", "<\\/")


def validate_coord(coord: list[float]) -> None:
    if len(coord) != 2:
        raise ValueError("coords must contain x, y pairs")
    for value in coord:
        if not math.isfinite(value):
            raise ValueError("coords must contain finite values")


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lyte Preview</title>
<style>
html, body {
  height: 100%;
  margin: 0;
  background: #050506;
  color: #f3f4f6;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
main {
  height: 100%;
  display: grid;
  grid-template-rows: auto 1fr;
}
header {
  padding: 12px 16px;
  border-bottom: 1px solid #25262b;
}
h1 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}
canvas {
  width: 100%;
  height: 100%;
  display: block;
}
</style>
</head>
<body>
<main>
<header><h1 id="title">Lyte Preview</h1></header>
<canvas id="preview"></canvas>
</main>
<script>
const data = __LYTE_PREVIEW_DATA__;
const canvas = document.getElementById("preview");
const context = canvas.getContext("2d");
document.getElementById("title").textContent = data.name;

function resize() {
  const scale = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width * scale));
  canvas.height = Math.max(1, Math.round(rect.height * scale));
}

function decodeFrame(text) {
  const binary = atob(text);
  const values = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    values[i] = binary.charCodeAt(i);
  }
  return values;
}

const frames = data.frames.map(decodeFrame);
const bounds = data.coords.reduce((acc, point) => ({
  minX: Math.min(acc.minX, point[0]),
  minY: Math.min(acc.minY, point[1]),
  maxX: Math.max(acc.maxX, point[0]),
  maxY: Math.max(acc.maxY, point[1]),
}), {
  minX: Infinity,
  minY: Infinity,
  maxX: -Infinity,
  maxY: -Infinity,
});

function projectedPoints() {
  const width = canvas.width;
  const height = canvas.height;
  const pad = Math.max(24, Math.min(width, height) * 0.08);
  const spanX = Math.max(1e-9, bounds.maxX - bounds.minX);
  const spanY = Math.max(1e-9, bounds.maxY - bounds.minY);
  const scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY);
  const offsetX = (width - spanX * scale) / 2;
  const offsetY = (height - spanY * scale) / 2;
  return data.coords.map(point => [
    offsetX + (point[0] - bounds.minX) * scale,
    offsetY + (point[1] - bounds.minY) * scale,
  ]);
}

function draw(time) {
  if (canvas.width === 0 || canvas.height === 0) {
    resize();
  }
  const frame = frames[Math.floor(time / 1000 * data.fps) % frames.length];
  const points = projectedPoints();
  const radius = Math.max(3, Math.min(canvas.width, canvas.height) / 140);
  context.fillStyle = "#050506";
  context.fillRect(0, 0, canvas.width, canvas.height);
  for (let i = 0; i < points.length; i += 1) {
    const offset = i * 3;
    context.fillStyle =
      `rgb(${frame[offset]}, ${frame[offset + 1]}, ${frame[offset + 2]})`;
    context.beginPath();
    context.arc(points[i][0], points[i][1], radius, 0, Math.PI * 2);
    context.fill();
  }
  requestAnimationFrame(draw);
}

window.addEventListener("resize", resize);
resize();
requestAnimationFrame(draw);
</script>
</body>
</html>
"""
