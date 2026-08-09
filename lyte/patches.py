from __future__ import annotations

import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
import tyro
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, model_validator

from . import animation, midi
from .animations import bibliopixel
from .animations.christmas.random_walk import RandomWalk
from .logging import log, log_status
from .retry import RetryConfig
from .twinkly import realtime
from .twinkly.client import TwinklyClient


class PatchLibraryError(ValueError):
    pass


class RegionSpec(BaseModel, frozen=True):
    start: int
    led_count: int

    @model_validator(mode='after')
    def validate_region(self) -> RegionSpec:
        if self.start < 0:
            raise ValueError('region start must not be negative')
        if self.led_count <= 0:
            raise ValueError('region led_count must be greater than zero')
        return self

    model_config = ConfigDict(extra='forbid')


class PhysicalRangeSpec(BaseModel, frozen=True):
    start: int
    led_count: int

    @model_validator(mode='after')
    def validate_range(self) -> PhysicalRangeSpec:
        if self.start < 0:
            raise ValueError('physical range start must not be negative')
        if self.led_count <= 0:
            raise ValueError('physical range led_count must be greater than zero')
        return self

    model_config = ConfigDict(extra='forbid')


class PhysicalRegionSpec(BaseModel, frozen=True):
    ranges: list[PhysicalRangeSpec]

    @model_validator(mode='after')
    def validate_ranges(self) -> PhysicalRegionSpec:
        if not self.ranges:
            raise ValueError('physical region must contain at least one range')
        return self

    model_config = ConfigDict(extra='forbid')


class WearableSpec(BaseModel, frozen=True):
    led_count: int
    physical_map_status: Literal['provisional', 'measured']
    segments: dict[str, RegionSpec]
    physical_map: dict[str, PhysicalRegionSpec]

    @model_validator(mode='after')
    def validate_layout(self) -> WearableSpec:
        if self.led_count <= 0:
            raise ValueError('wearable led_count must be greater than zero')
        if set(self.segments) != set(self.physical_map):
            raise ValueError('physical map names must match wearable segments')

        logical_indexes = []
        physical_indexes = []
        for name, segment in self.segments.items():
            logical_indexes.extend(
                range(segment.start, segment.start + segment.led_count)
            )
            physical_ranges = self.physical_map[name].ranges
            if sum(r.led_count for r in physical_ranges) != segment.led_count:
                raise ValueError(
                    f'physical map for {name} must contain {segment.led_count} LEDs'
                )
            for physical_range in physical_ranges:
                physical_indexes.extend(
                    range(
                        physical_range.start,
                        physical_range.start + physical_range.led_count,
                    )
                )

        expected_indexes = set(range(self.led_count))
        if (
            set(logical_indexes) != expected_indexes
            or len(logical_indexes) != self.led_count
        ):
            raise ValueError(
                'wearable segments must cover each logical LED exactly once'
            )
        if (
            set(physical_indexes) != expected_indexes
            or len(physical_indexes) != self.led_count
        ):
            raise ValueError('physical map must cover each physical LED exactly once')
        return self

    model_config = ConfigDict(extra='forbid')


class LayerSpec(BaseModel, frozen=True):
    kind: Literal['solid', 'random_walk', 'twinkle', 'chase', 'rainbow']
    color: list[float] = [1.0, 1.0, 1.0]
    speed: float = 10.0

    @model_validator(mode='after')
    def validate_layer(self) -> LayerSpec:
        if len(self.color) != 3 or any(value < 0 or value > 1 for value in self.color):
            raise ValueError('layer color must contain three values between 0 and 1')
        if self.speed < 0:
            raise ValueError('layer speed must not be negative')
        return self

    model_config = ConfigDict(extra='forbid')


class PatchSpec(BaseModel, frozen=True):
    layers: list[str]
    regions: list[str] = []
    note_color: str | None = None
    breath_speed: str | None = None
    breath_mix: str | None = None
    pitch_speed: str | None = None

    @model_validator(mode='after')
    def validate_patch(self) -> PatchSpec:
        if not self.layers:
            raise ValueError('patch must contain at least one layer')
        return self

    model_config = ConfigDict(extra='forbid')


class PatchLibrary(BaseModel, frozen=True):
    wearable: WearableSpec
    layers: dict[str, LayerSpec]
    patches: dict[str, PatchSpec]

    @model_validator(mode='after')
    def validate_patches(self) -> PatchLibrary:
        if not self.patches:
            raise ValueError('patch library must contain at least one patch')
        for name, patch in self.patches.items():
            unknown_layers = set(patch.layers).difference(self.layers)
            if unknown_layers:
                unknown = ', '.join(sorted(unknown_layers))
                raise ValueError(f'patch {name} names unknown layers: {unknown}')
            unknown_regions = set(patch.regions).difference(self.wearable.segments)
            if unknown_regions:
                unknown = ', '.join(sorted(unknown_regions))
                raise ValueError(f'patch {name} names unknown regions: {unknown}')
        return self

    model_config = ConfigDict(extra='forbid')


def load_patch_library(path: Path) -> PatchLibrary:
    try:
        with path.open('rb') as source:
            data = tomllib.load(source)
        return PatchLibrary.model_validate(data)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
        raise PatchLibraryError(f'{path}: {error}') from error


def map_logical_frame(
    wearable: WearableSpec,
    logical_frame: NDArray[np.float32],
) -> NDArray[np.float32]:
    device = animation.Device(led_count=wearable.led_count)
    animation.validate_frame(device, logical_frame)
    physical_frame = np.zeros_like(logical_frame)
    for name, logical_region in wearable.segments.items():
        logical_start = logical_region.start
        logical_end = logical_start + logical_region.led_count
        logical_values = logical_frame[logical_start:logical_end]
        offset = 0
        for physical_range in wearable.physical_map[name].ranges:
            end = offset + physical_range.led_count
            physical_start = physical_range.start
            physical_end = physical_start + physical_range.led_count
            physical_frame[physical_start:physical_end] = logical_values[offset:end]
            offset = end
    return animation.validate_frame(device, physical_frame)


def locator_frame(
    wearable: WearableSpec,
    region: str,
    color: animation.FloatRGB = (1.0, 1.0, 1.0),
) -> NDArray[np.float32]:
    if region not in wearable.segments:
        raise ValueError(f'unknown wearable region: {region}')
    device = animation.Device(led_count=wearable.led_count)
    logical_frame = np.zeros((device.led_count, 3), dtype=np.float32)
    segment = wearable.segments[region]
    logical_frame[segment.start : segment.start + segment.led_count] = color
    return map_logical_frame(wearable, logical_frame)


@dataclass(frozen=True)
class PatchCommandConfig:
    action: Annotated[Literal['list', 'locator'], tyro.conf.Positional] = 'list'
    library: Path = Path('patches/wearable-breath.toml')
    region_duration: float = 3.0
    fps: float = 20.0
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float | None = None
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0


def run_patch_command(config: PatchCommandConfig) -> int:
    library = load_patch_library(config.library)
    if config.action == 'list':
        list_patch_library(library)
        return 0
    return run_locator(config, library)


def list_patch_library(library: PatchLibrary) -> None:
    print(
        f'Wearable: {library.wearable.led_count} LEDs '
        f'({library.wearable.physical_map_status} physical map)'
    )
    for name, patch in library.patches.items():
        regions = patch.regions or list(library.wearable.segments)
        controls = []
        if patch.note_color is not None:
            controls.append('note color')
        if patch.breath_speed is not None:
            controls.append('breath speed')
        if patch.breath_mix is not None:
            controls.append('breath mix')
        if patch.pitch_speed is not None:
            controls.append('pitch speed')
        control_text = ', '.join(controls) if controls else 'none'
        print(
            f'{name}: regions={", ".join(regions)}; '
            f'layers={", ".join(patch.layers)}; controls={control_text}'
        )


def run_locator(config: PatchCommandConfig, library: PatchLibrary) -> int:
    validate_locator_config(config)
    host = config.host or realtime.discover_host(config.discovery_timeout)
    if host is None:
        return 1

    retry = RetryConfig(
        attempts=config.attempts,
        delay=config.retry_delay,
        backoff=config.retry_backoff,
    )
    client = TwinklyClient(host=host, timeout=config.timeout)
    led_count = realtime.read_led_count(client, retry, None, host)
    if led_count is None:
        return 1
    if led_count != library.wearable.led_count:
        sys.exit(
            f'Patch library needs {library.wearable.led_count} LEDs; '
            f'{host} has {led_count}.'
        )
    try:
        if not realtime.prepare_device(client, retry, host):
            return 1
        for region in library.wearable.segments:
            log_status(f'[locator] {region}')
            frame = animation.byte_light_frame_from_float(
                locator_frame(library.wearable, region)
            )
            stop_at = time.monotonic() + config.region_duration
            while time.monotonic() < stop_at:
                realtime.send_realtime_frame(client, retry, host, frame)
                time.sleep(1 / config.fps)
    except KeyboardInterrupt:
        log()
        log('[ok] Stopped')
    finally:
        realtime.turn_off_streaming_device(client, retry, host)
    return 0


def validate_locator_config(config: PatchCommandConfig) -> None:
    if config.region_duration <= 0:
        sys.exit('--region-duration must be greater than zero')
    if config.fps <= 0:
        sys.exit('--fps must be greater than zero')
    if config.attempts < 1:
        sys.exit('--attempts must be at least 1')
    if config.retry_delay < 0:
        sys.exit('--retry-delay must not be negative')
    if config.retry_backoff < 1:
        sys.exit('--retry-backoff must be at least 1')


def build_light_patch(library: PatchLibrary, name: str) -> midi.LightPatch:
    if (patch := library.patches.get(name)) is None:
        raise ValueError(f'unknown patch: {name}')
    regions = patch.regions or list(library.wearable.segments)
    children = []
    for layer_name in patch.layers:
        layer = library.layers[layer_name]
        children.append(
            midi.RegionLightPatch(
                config=midi.RegionLightPatchConfig(
                    regions=[
                        midi.RegionAnimation(
                            animation=build_layer_animation(layer),
                            start=library.wearable.segments[region].start,
                            led_count=library.wearable.segments[region].led_count,
                        )
                        for region in regions
                    ]
                )
            )
        )
    if len(children) == 1:
        return children[0]
    return midi.BlendLightPatch(
        config=midi.BlendLightPatchConfig(),
        patches=children,
    )


def build_layer_animation(layer: LayerSpec) -> animation.Animation:
    color = (layer.color[0], layer.color[1], layer.color[2])
    rgb = animation.rgb_from_float_color(color)
    if layer.kind == 'solid':
        return bibliopixel.ColorFill(color=rgb)
    if layer.kind == 'random_walk':
        return RandomWalk(
            speed=layer.speed,
            color=(color[0] * 255, color[1] * 255, color[2] * 255),
        )
    if layer.kind == 'twinkle':
        return bibliopixel.Twinkle(colors=(rgb,), speed=round(layer.speed))
    if layer.kind == 'chase':
        return bibliopixel.ColorChase(color=rgb, step=max(1, round(layer.speed)))
    return bibliopixel.Rainbow(step=max(1, round(layer.speed)))
