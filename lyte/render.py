"""Render uFor light animations as MP4 files."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal

import numpy as np
import tyro
from numpy.typing import NDArray
from pydantic import BaseModel, Field, model_validator
from ufor import library_files
from ufor.library import Library
from ufor.light_animation import AnimationScore

from . import animation, show
from .spatial import SpatialView, projected_points

_COLORS = {
    'black': (0, 0, 0),
    'blue': (0, 0, 255),
    'cyan': (0, 255, 255),
    'gray': (128, 128, 128),
    'green': (0, 128, 0),
    'magenta': (255, 0, 255),
    'red': (255, 0, 0),
    'white': (255, 255, 255),
    'yellow': (255, 255, 0),
}


class RenderConfig(BaseModel, frozen=True):
    selectors: Annotated[list[str], tyro.conf.Positional] = Field(default_factory=list)
    output: Path = Path('rendered')
    library_config: Path | None = None
    audio: Path | None = None
    light_output: str = 'light'
    duration: float = Field(default=10.0, gt=0)
    diameter: float = Field(default=20.0, gt=0)
    padding: float = Field(default=5.0, ge=0)
    shape: Literal['circle', 'rect'] = 'circle'
    layout: list[int] | None = None
    background_color: str = 'white'
    projection: Literal['grid', 'xy', 'xz', 'yz'] = 'grid'
    width: int = Field(default=960, ge=64)
    height: int = Field(default=540, ge=64)
    led_size: float = Field(default=1, gt=0, allow_inf_nan=False)
    zoom: float = Field(default=1, gt=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def validate_layout(self) -> RenderConfig:
        if self.layout is not None and (
            len(self.layout) != 2 or any(value <= 0 for value in self.layout)
        ):
            raise ValueError('layout must contain positive column and row counts')
        parse_color(self.background_color)
        if self.projection != 'grid' and self.layout is not None:
            raise ValueError('layout columns and rows only apply to grid projection')
        return self


class RenderError(ValueError):
    pass


class FrameRenderer:
    def __init__(
        self,
        led_count: int,
        diameter: float,
        padding: float,
        shape: Literal['circle', 'rect'],
        layout: list[int] | None,
        background_color: str,
        *,
        positions: list[list[float]] | None = None,
        view: SpatialView | None = None,
        width: int = 960,
        height: int = 540,
    ) -> None:
        if led_count <= 0:
            raise ValueError('led_count must be greater than zero')
        if layout is None:
            columns = math.ceil(math.sqrt(led_count))
            rows = math.ceil(led_count / columns)
        else:
            columns, rows = layout
            if columns * rows < led_count:
                raise ValueError('layout does not have enough cells for the animation')
        self.led_count = led_count
        self.diameter = max(1, round(diameter))
        self.padding = max(0, round(padding))
        self.shape = shape
        self.background = np.array(parse_color(background_color), dtype=np.uint8)
        self.cell_size = self.diameter + self.padding
        self.width = _even(columns * self.cell_size + self.padding)
        self.height = _even(rows * self.cell_size + self.padding)
        self.origins = [
            (
                self.padding + (index % columns) * self.cell_size,
                self.padding + (index // columns) * self.cell_size,
            )
            for index in range(led_count)
        ]
        if positions is not None:
            view = view or SpatialView()
            self.width, self.height = _even(width), _even(height)
            self.diameter = max(
                1, round(2 * max(3, min(self.width, self.height) / 140) * view.led_size)
            )
            self.origins = [
                (round(p[0] - self.diameter / 2), round(p[1] - self.diameter / 2))
                for p in projected_points(positions, self.width, self.height, view)
            ]
        indexes = np.indices((self.diameter, self.diameter))
        radius = self.diameter / 2
        self.circle_mask = (indexes[0] + 0.5 - radius) ** 2 + (
            indexes[1] + 0.5 - radius
        ) ** 2 <= radius**2

    def render(self, values: NDArray[np.uint8]) -> NDArray[np.uint8]:
        animation.validate_byte_rgb_frame(
            animation.Device(led_count=self.led_count), values
        )
        frame = np.empty((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = self.background
        for color, (left, top) in zip(values, self.origins, strict=True):
            x0, y0 = max(0, left), max(0, top)
            x1, y1 = (
                min(self.width, left + self.diameter),
                min(self.height, top + self.diameter),
            )
            if x1 <= x0 or y1 <= y0:
                continue
            region = frame[y0:y1, x0:x1]
            if self.shape == 'circle':
                region[self.circle_mask[y0 - top : y1 - top, x0 - left : x1 - left]] = (
                    color
                )
            else:
                region[:] = color
        return frame


def run_render(config: RenderConfig) -> int:
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg is None:
        raise RenderError('lyte render requires ffmpeg on PATH')
    library = library_files.read_library(config.library_config)
    show.log_diagnostics(library)
    selectors = config.selectors or list_animation_selectors(library)
    if not selectors:
        raise RenderError('library contains no animation scores')
    destinations: dict[str, str] = {}
    for selector in selectors:
        destination = config.output / f'{safe_name(selector)}.mp4'
        key = destination.name.casefold()
        if key in destinations:
            raise RenderError(
                f'{selector!r} and {destinations[key]!r} '
                f'share destination {destination}'
            )
        if destination.exists():
            raise RenderError(f'output already exists: {destination}')
        destinations[key] = selector
    config.output.mkdir(parents=True, exist_ok=True)
    for selector in selectors:
        render_animation(selector, config, ffmpeg, library)
    return 0


def list_animation_selectors(library: Library) -> list[str]:
    return [
        entry.name or entry.key
        for entry in library.find()
        if isinstance(entry.resolved, AnimationScore)
    ]


def render_animation(
    selector: str, config: RenderConfig, ffmpeg: str, library: Library
) -> Path:
    try:
        prepared = show.prepare_library_animation(
            library,
            show.LightProgramSpec(selector=selector, output=config.light_output),
        )
    except (OSError, ValueError) as error:
        raise RenderError(f'{selector}: {error}') from error
    if prepared.output.components != ['red', 'green', 'blue']:
        raise RenderError(f'{selector}: render requires red, green, blue components')
    if config.audio is not None:
        prepared.set_audio(config.audio)
    if prepared.requires_audio and prepared.audio is None:
        raise RenderError('this score requires --audio with a PCM WAV file')
    renderer = FrameRenderer(
        len(prepared.output.layout.lights),
        config.diameter,
        config.padding,
        config.shape,
        config.layout,
        config.background_color,
        positions=(
            [p.position for p in prepared.output.layout.lights]
            if config.projection != 'grid'
            else None
        ),
        view=SpatialView(
            plane=config.projection if config.projection != 'grid' else 'xy',
            zoom=config.zoom,
            led_size=config.led_size,
        ),
        width=config.width,
        height=config.height,
    )
    output = config.output / f'{safe_name(selector)}.mp4'
    frame_count = (
        len(prepared.audio.frames)
        if prepared.audio is not None
        else max(1, round(prepared.fps * config.duration))
    )
    with TemporaryDirectory(prefix='.lyte-render-', dir=config.output) as directory:
        temporary = Path(directory) / 'movie.mp4'
        command = [
            ffmpeg,
            '-n',
            '-f',
            'rawvideo',
            '-pixel_format',
            'rgb24',
            '-video_size',
            f'{renderer.width}x{renderer.height}',
            '-framerate',
            str(prepared.rate),
            '-i',
            '-',
            '-an',
            '-c:v',
            'libx264',
            '-pix_fmt',
            'yuv420p',
            '-movflags',
            '+faststart',
            *(['-t', str(float(prepared.audio.duration))] if prepared.audio else []),
            str(temporary),
        ]
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
        input_complete = False
        try:
            if process.stdin is None:
                raise RenderError('ffmpeg did not provide a frame input')
            for _ in range(frame_count):
                lights = animation.byte_light_frame_from_float(prepared.render())
                process.stdin.write(renderer.render(lights).tobytes())
            process.stdin.close()
            input_complete = True
        except BrokenPipeError as error:
            raise RenderError(f'{selector}: ffmpeg stopped accepting frames') from error
        finally:
            if not input_complete and process.poll() is None:
                process.kill()
            try:
                if process.stdin is not None and not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except BrokenPipeError:
                        pass
            finally:
                return_code = process.wait()
        if return_code != 0:
            raise RenderError(f'{selector}: ffmpeg failed')
        try:
            output.hardlink_to(temporary)
        except FileExistsError as error:
            raise RenderError(f'output already exists: {output}') from error
    return output


def parse_color(value: str) -> tuple[int, int, int]:
    if (name := value.casefold()) in _COLORS:
        return _COLORS[name]
    if value.startswith('#') and len(value) in {4, 7}:
        digits = value[1:]
        if len(digits) == 3:
            digits = ''.join(digit * 2 for digit in digits)
        try:
            return (
                int(digits[0:2], 16),
                int(digits[2:4], 16),
                int(digits[4:6], 16),
            )
        except ValueError as error:
            raise ValueError(f'invalid background color {value!r}') from error
    raise ValueError(f'invalid background color {value!r}')


def safe_name(selector: str) -> str:
    return (
        ''.join(
            character if character.isalnum() else '-' for character in selector
        ).strip('-')
        or 'animation'
    )


def _even(value: int) -> int:
    return value if value % 2 == 0 else value + 1
