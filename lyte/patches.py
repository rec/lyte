from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, model_validator

from . import animation


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
    patches: dict[str, PatchSpec]

    @model_validator(mode='after')
    def validate_patches(self) -> PatchLibrary:
        if not self.patches:
            raise ValueError('patch library must contain at least one patch')
        for name, patch in self.patches.items():
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
