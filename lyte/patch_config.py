"""Wearable patch library schema and TOML loading."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    led_count: int | None = None
    physical_map_status: Literal['provisional', 'guessed', 'measured']
    segments: dict[str, RegionSpec]
    physical_map: dict[str, PhysicalRegionSpec]

    @model_validator(mode='after')
    def validate_layout(self) -> WearableSpec:
        if set(self.segments) != set(self.physical_map):
            raise ValueError('physical map names must match wearable segments')
        if not self.segments:
            raise ValueError('wearable must contain at least one segment')

        led_count = self.led_count or max(
            segment.start + segment.led_count for segment in self.segments.values()
        )
        if led_count <= 0:
            raise ValueError('wearable led_count must be greater than zero')

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

        expected_indexes = set(range(led_count))
        if (
            set(logical_indexes) != expected_indexes
            or len(logical_indexes) != led_count
        ):
            raise ValueError(
                'wearable segments must cover each logical LED exactly once'
            )
        if (
            set(physical_indexes) != expected_indexes
            or len(physical_indexes) != led_count
        ):
            raise ValueError('physical map must cover each physical LED exactly once')
        object.__setattr__(self, 'led_count', led_count)
        return self

    model_config = ConfigDict(extra='forbid')


class LinearMapSpec(BaseModel, frozen=True):
    kind: Literal['linear', 'positive_linear']
    input: list[float] = [0.0, 127.0]
    output: list[float]

    @model_validator(mode='after')
    def validate_ranges(self) -> LinearMapSpec:
        if len(self.input) != 2 or len(self.output) != 2:
            raise ValueError('linear maps require two input and output values')
        if self.input[0] >= self.input[1] or self.output[0] > self.output[1]:
            raise ValueError('linear map ranges must be ordered')
        return self

    model_config = ConfigDict(extra='forbid')


class BindingSpec(BaseModel, frozen=True):
    source: Literal['note', 'breath', 'pitch_bend']
    target: str
    mapping: Literal['pitch_class_palette'] | LinearMapSpec = Field(alias='map')

    model_config = ConfigDict(extra='forbid', populate_by_name=True)


class LayerSpec(BaseModel, frozen=True):
    kind: Literal[
        'solid',
        'random_walk',
        'twinkle',
        'chase',
        'rainbow',
        'velocity_splash',
        'breath_bloom',
        'pitch_bend_travel',
        'note_age_constellation',
    ]
    color: list[float] = [1.0, 1.0, 1.0]
    speed: float = 10.0
    regions: list[str] = []

    @model_validator(mode='after')
    def validate_layer(self) -> LayerSpec:
        if len(self.color) != 3 or any(value < 0 or value > 1 for value in self.color):
            raise ValueError('layer color must contain three values between 0 and 1')
        if self.speed < 0:
            raise ValueError('layer speed must not be negative')
        return self

    model_config = ConfigDict(extra='forbid')


class PatchSpec(BaseModel, frozen=True):
    activation: Literal['note']
    layers: list[str]
    regions: list[str] = []
    note_palette: list[list[float]] = []
    bindings: list[BindingSpec] = []
    blend: Literal['add', 'weighted'] = 'add'

    @model_validator(mode='after')
    def validate_patch(self) -> PatchSpec:
        if not self.layers:
            raise ValueError('patch must contain at least one layer')
        if self.note_palette and (
            len(self.note_palette) != 12
            or any(
                len(color) != 3 or any(value < 0 or value > 1 for value in color)
                for color in self.note_palette
            )
        ):
            raise ValueError('note_palette must contain twelve RGB colors')
        for binding in self.bindings:
            if binding.source == 'note' and binding.mapping != 'pitch_class_palette':
                raise ValueError('note bindings require pitch_class_palette mapping')
            if binding.source == 'note' and not self.note_palette:
                raise ValueError('note bindings require note_palette')
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
        for layer_name, layer in self.layers.items():
            unknown_regions = set(layer.regions).difference(self.wearable.segments)
            if unknown_regions:
                unknown = ', '.join(sorted(unknown_regions))
                raise ValueError(f'layer {layer_name} names unknown regions: {unknown}')
        for name, patch in self.patches.items():
            unknown_layers = set(patch.layers).difference(self.layers)
            if unknown_layers:
                unknown = ', '.join(sorted(unknown_layers))
                raise ValueError(f'patch {name} names unknown layers: {unknown}')
            unknown_regions = set(patch.regions).difference(self.wearable.segments)
            if unknown_regions:
                unknown = ', '.join(sorted(unknown_regions))
                raise ValueError(f'patch {name} names unknown regions: {unknown}')
            for binding in patch.bindings:
                target_name, _, parameter = binding.target.partition('.')
                if target_name == 'mix':
                    if patch.blend != 'weighted':
                        raise ValueError(
                            f'patch {name} uses a mix binding without a weighted blend'
                        )
                    if parameter not in patch.layers:
                        raise ValueError(f'patch {name} names unknown mix target')
                    continue
                if (layer := self.layers.get(target_name)) is None:
                    raise ValueError(f'patch {name} names invalid binding target')
                if not layer_supports_parameter(layer, parameter):
                    raise ValueError(
                        f'layer {target_name} does not support {parameter!r} bindings'
                    )
                if binding.source == 'note' and parameter != 'color':
                    raise ValueError('note bindings must target layer color')
                if binding.source == 'pitch_bend' and parameter != 'speed':
                    raise ValueError('pitch bend bindings must target layer speed')
        return self

    model_config = ConfigDict(extra='forbid')


def layer_supports_parameter(layer: LayerSpec, parameter: str) -> bool:
    if parameter in {'color', 'gain'}:
        return True
    return parameter == 'speed' and layer.kind not in {'solid', 'pitch_bend_travel'}


def load_patch_library(path: Path) -> PatchLibrary:
    try:
        with path.open('rb') as source:
            data = tomllib.load(source)
        return PatchLibrary.model_validate(data)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
        raise PatchLibraryError(f'{path}: {error}') from error
