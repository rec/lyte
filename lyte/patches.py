from __future__ import annotations

import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import mido
import numpy as np
import tyro
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, SkipValidation, model_validator
from reccy import logging

from . import animation, midi
from .animations import bibliopixel
from .animations.christmas.random_walk import RandomWalk
from .retry import RetryConfig
from .twinkly import realtime, track
from .twinkly.client import TwinklyClient

LOGGER = logging.get_logger(__name__)


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
    physical_map_status: Literal['provisional', 'guessed', 'measured']
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
    kind: Literal['solid', 'random_walk', 'twinkle', 'chase', 'rainbow']
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


class DeclarativePatchState(BaseModel):
    colors: dict[str, list[float]] = {}
    gains: dict[str, float] = {}
    weights: dict[str, float] = {}


class DeclarativeLightPatch(midi.LightPatch[PatchSpec, DeclarativePatchState]):
    layers: dict[str, SkipValidation[midi.LightPatch]]
    base_layer_configs: dict[str, midi.RegionLightPatchConfig]
    mixer: SkipValidation[midi.BlendLightPatch | midi.WeightedBlendLightPatch]

    def make_state(self, msg: mido.Message) -> DeclarativePatchState:
        return DeclarativePatchState(
            gains={name: 1.0 for name in self.layers},
            weights={name: 1.0 for name in self.layers},
        )

    def receive(self, msg: mido.Message) -> None:
        super().receive(msg)
        for layer in self.layers.values():
            layer.receive(msg)

    def breath_control(self, msg: mido.Message) -> None:
        self.apply_bindings('breath', msg.value)

    def pitch_bend(self, msg: mido.Message) -> None:
        self.apply_bindings('pitch_bend', int(msg.__getattribute__('pitch')))

    def note_on(self, msg: mido.Message) -> None:
        self.restore_layer_configs()
        if isinstance(self.mixer, midi.WeightedBlendLightPatch):
            self.mixer.state = self.mixer.make_state(msg)
        else:
            self.mixer.state = self.mixer.make_state(msg)
        self.apply_bindings('note', msg.note)

    def note_off(self) -> None:
        self.restore_layer_configs()
        self.mixer.state = None

    def restore_layer_configs(self) -> None:
        for name, layer in self.layers.items():
            if not isinstance(layer, midi.RegionLightPatch):
                raise ValueError(
                    'Declarative patch layers must be region light patches'
                )
            layer.config = self.base_layer_configs[name]

    def apply_bindings(self, source: str, value: int) -> None:
        if self.state is None:
            return
        for binding in self.config.bindings:
            if binding.source != source:
                continue
            target_name, _, parameter = binding.target.partition('.')
            if binding.mapping == 'pitch_class_palette':
                color = self.config.note_palette[value % 12]
                self.state.colors[target_name] = color
                continue
            mapped_value = map_binding_value(binding.mapping, value)
            if target_name == 'mix':
                self.state.weights[parameter] = mapped_value
                if len(self.layers) == 2:
                    other = next(name for name in self.layers if name != parameter)
                    self.state.weights[other] = 1.0 - mapped_value
                if isinstance(self.mixer, midi.WeightedBlendLightPatch):
                    for index, name in enumerate(self.layers):
                        self.mixer.set_weight(index, self.state.weights[name])
            elif parameter == 'gain':
                self.state.gains[target_name] = mapped_value
            elif parameter == 'speed':
                set_layer_speed(self.layers[target_name], mapped_value)

    def render(self, device: animation.Device) -> NDArray[np.float32]:
        if self.state is None:
            return animation.validate_frame(
                device, np.zeros((device.led_count, 3), dtype=np.float32)
            )
        frames = []
        for name, layer in self.layers.items():
            frame = animation.validate_frame(device, layer.render(device))
            if (color := self.state.colors.get(name)) is not None:
                intensity = np.max(frame, axis=1, keepdims=True)
                frame = intensity * np.array(color, dtype=np.float32)
            frame *= self.state.gains[name]
            frames.append(frame)
        return self.mixer.blend(device, frames)

    model_config = ConfigDict(arbitrary_types_allowed=True)


def layer_supports_parameter(layer: LayerSpec, parameter: str) -> bool:
    if parameter in {'color', 'gain'}:
        return True
    return parameter == 'speed' and layer.kind != 'solid'


def map_binding_value(mapping: LinearMapSpec, value: int) -> float:
    if mapping.kind == 'positive_linear' and value <= 0:
        return mapping.output[0]
    start, end = mapping.input
    progress = max(0.0, min(1.0, (value - start) / (end - start)))
    return mapping.output[0] + progress * (mapping.output[1] - mapping.output[0])


def set_layer_speed(layer: midi.LightPatch, speed: float) -> None:
    if not isinstance(layer, midi.RegionLightPatch):
        raise ValueError('Layer speed control requires a region light patch')
    regions = []
    for region in layer.config.regions:
        source = region.animation
        if isinstance(source, RandomWalk):
            source = source.model_copy(update={'speed': speed})
        elif isinstance(source, bibliopixel.Twinkle):
            source = source.model_copy(update={'speed': round(speed)})
        elif isinstance(source, bibliopixel.ColorChase | bibliopixel.Rainbow):
            source = source.model_copy(update={'step': max(1, round(speed))})
        regions.append(
            midi.RegionAnimation(
                animation=source,
                start=region.start,
                led_count=region.led_count,
            )
        )
    layer.config = midi.RegionLightPatchConfig(regions=regions)


def load_patch_library(path: Path) -> PatchLibrary:
    try:
        with path.open('rb') as source:
            data = tomllib.load(source)
        return PatchLibrary.model_validate(data)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
        raise PatchLibraryError(f'{path}: {error}') from error


def scale_wearable_layout(wearable: WearableSpec, led_count: int) -> WearableSpec:
    if led_count <= 0:
        raise ValueError('runtime LED count must be greater than zero')
    if led_count == wearable.led_count:
        return wearable
    LOGGER.warning(
        f'[warn] Scaling wearable layout from {wearable.led_count} LEDs to '
        f'{led_count} LEDs.'
    )
    physical_map = {
        name: PhysicalRegionSpec(
            ranges=[
                _scaled_physical_range(
                    physical_range, wearable.led_count, led_count, name
                )
                for physical_range in physical_region.ranges
            ]
        )
        for name, physical_region in wearable.physical_map.items()
    }
    segments = {}
    start = 0
    for name in wearable.segments:
        region_led_count = sum(r.led_count for r in physical_map[name].ranges)
        segments[name] = RegionSpec(start=start, led_count=region_led_count)
        start += region_led_count
    return WearableSpec(
        led_count=led_count,
        physical_map_status=wearable.physical_map_status,
        segments=segments,
        physical_map=physical_map,
    )


def scale_patch_library(library: PatchLibrary, led_count: int) -> PatchLibrary:
    return library.model_copy(
        update={'wearable': scale_wearable_layout(library.wearable, led_count)}
    )


def _scaled_physical_range(
    physical_range: PhysicalRangeSpec,
    planned_led_count: int,
    actual_led_count: int,
    name: str,
) -> PhysicalRangeSpec:
    return PhysicalRangeSpec(
        start=_scale_boundary(
            physical_range.start, planned_led_count, actual_led_count
        ),
        led_count=_scaled_led_count(
            physical_range.start,
            physical_range.led_count,
            planned_led_count,
            actual_led_count,
            f'physical range for {name}',
        ),
    )


def _scale_boundary(
    position: int, planned_led_count: int, actual_led_count: int
) -> int:
    return (position * actual_led_count + planned_led_count // 2) // planned_led_count


def _scaled_led_count(
    start: int,
    led_count: int,
    planned_led_count: int,
    actual_led_count: int,
    name: str,
) -> int:
    scaled_start = _scale_boundary(start, planned_led_count, actual_led_count)
    scaled_end = _scale_boundary(start + led_count, planned_led_count, actual_led_count)
    if scaled_end <= scaled_start:
        raise ValueError(f'{name} collapses when scaled to {actual_led_count} LEDs')
    return scaled_end - scaled_start


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


def encode_wearable_frame(
    wearable: WearableSpec, logical_frame: NDArray[np.float32]
) -> NDArray[np.uint8]:
    return animation.byte_light_frame_from_float(
        map_logical_frame(wearable, logical_frame)
    )


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
    action: Annotated[Literal['list', 'locator', 'play'], tyro.conf.Positional] = 'list'
    patch_name: Annotated[str | None, tyro.conf.Positional] = None
    library: Path = Path('patches/wearable-breath.toml')
    region_duration: float = 3.0
    fps: float = 20.0
    duration: float | None = None
    midi_input: midi.MidiIn = midi.MidiIn()
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
    if config.action == 'locator':
        return run_locator(config, library)
    return run_patch_playback(config, library)


def list_patch_library(library: PatchLibrary) -> None:
    print(
        f'Wearable: {library.wearable.led_count} LEDs '
        f'({library.wearable.physical_map_status} physical map)'
    )
    for name, patch in library.patches.items():
        regions = patch.regions or list(library.wearable.segments)
        controls = [binding.source for binding in patch.bindings]
        control_text = ', '.join(controls) if controls else 'none'
        print(
            f'[experimental] {name}: regions={", ".join(regions)}; '
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
    wearable = scale_wearable_layout(library.wearable, led_count)
    try:
        if not realtime.prepare_device(client, retry, host):
            return 1
        for region in wearable.segments:
            LOGGER.info(f'[locator] {region}')
            frame = animation.byte_light_frame_from_float(
                locator_frame(wearable, region)
            )
            stop_at = time.monotonic() + config.region_duration
            while time.monotonic() < stop_at:
                realtime.send_realtime_frame(client, retry, host, frame)
                time.sleep(1 / config.fps)
    except KeyboardInterrupt:
        LOGGER.debug('')
        LOGGER.debug('[ok] Stopped')
    finally:
        realtime.turn_off_streaming_device(client, retry, host)
    return 0


def run_patch_playback(config: PatchCommandConfig, library: PatchLibrary) -> int:
    validate_playback_config(config)
    if library.wearable.physical_map_status == 'provisional':
        LOGGER.error(
            '[failed] Patch playback requires a guessed or measured physical map.'
        )
        return 1
    if library.wearable.physical_map_status == 'guessed':
        LOGGER.info('[warn] Patch playback is using a guessed physical map.')
    if config.patch_name is None:
        sys.exit('Patch playback requires a patch name')
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
    runtime_library = scale_patch_library(library, led_count)
    patch = build_light_patch(runtime_library, config.patch_name)

    port = midi.open_input(config.midi_input)
    twinkly_track = track.TwinklyTrack(
        client=client,
        retry=retry,
        host=host,
        configured_host=config.host,
        discovery_timeout=config.discovery_timeout,
        device=animation.Device(led_count=led_count),
    )
    try:
        if not twinkly_track.prepare():
            return 1
        stream_patch_frames(port, config, runtime_library, patch, twinkly_track)
    except KeyboardInterrupt:
        LOGGER.debug('')
        LOGGER.debug('[ok] Stopped')
    finally:
        port.close()
        twinkly_track.close()
    return 0


def stream_patch_frames(
    port: midi.MidiInput,
    config: PatchCommandConfig,
    library: PatchLibrary,
    patch: midi.LightPatch,
    twinkly_track: track.TwinklyTrack,
) -> None:
    def process_messages() -> None:
        for message in midi.input_messages(port, config.midi_input):
            patch.receive(message)

    twinkly_track.stream_frames(
        'patch',
        config.fps,
        config.duration,
        lambda: encode_wearable_frame(
            library.wearable, patch.render(twinkly_track.device)
        ),
        process_messages,
    )


def validate_playback_config(config: PatchCommandConfig) -> None:
    validate_locator_config(config)
    if config.duration is not None and config.duration <= 0:
        sys.exit('--duration must be greater than zero')


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
    default_regions = patch.regions or list(library.wearable.segments)
    layers = {}
    for layer_name in patch.layers:
        layer = library.layers[layer_name]
        layer_regions = layer.regions or default_regions
        layers[layer_name] = midi.RegionLightPatch(
            config=midi.RegionLightPatchConfig(
                regions=[
                    midi.RegionAnimation(
                        animation=build_layer_animation(layer),
                        start=library.wearable.segments[region].start,
                        led_count=library.wearable.segments[region].led_count,
                    )
                    for region in layer_regions
                ]
            )
        )
    children = list(layers.values())
    if patch.blend == 'weighted':
        mixer = midi.WeightedBlendLightPatch(
            config=midi.WeightedBlendLightPatchConfig(
                weights=[1.0] + [0.0] * (len(children) - 1)
            ),
            patches=children,
        )
    else:
        mixer = midi.BlendLightPatch(
            config=midi.BlendLightPatchConfig(), patches=children
        )
    return DeclarativeLightPatch(
        config=patch,
        layers=layers,
        base_layer_configs={
            name: layer.config
            for name, layer in layers.items()
            if isinstance(layer, midi.RegionLightPatch)
        },
        mixer=mixer,
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
