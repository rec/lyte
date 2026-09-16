from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import mido
import numpy as np
import tyro
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, SkipValidation
from reccy.runtime import logging

from . import animation, midi, patch_config
from .animations import compositions, reactive
from .animations.events import color_chase, twinkle
from .animations.fields import rainbow
from .animations.patterns import color_fill
from .animations.simulations.random_walk import RandomWalk
from .retry import RetryConfig
from .twinkly import realtime, track
from .twinkly.client import TwinklyClient

LOGGER = logging.get_logger(__name__)


class DeclarativePatchState(BaseModel):
    colors: dict[str, list[float]] = {}
    gains: dict[str, float] = {}
    weights: dict[str, float] = {}


class DeclarativeLightPatch(
    midi.LightPatch[patch_config.PatchSpec, DeclarativePatchState]
):
    layers: dict[str, SkipValidation[midi.LightPatch]]
    base_layer_configs: dict[str, compositions.Segments]
    mixer: SkipValidation[midi.MixLightPatch]

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
            layer.fps = self.fps
            frame = animation.validate_frame(device, layer.render(device))
            if (color := self.state.colors.get(name)) is not None:
                intensity = np.max(frame, axis=1, keepdims=True)
                frame = intensity * np.array(color, dtype=np.float32)
            frame *= self.state.gains[name]
            frames.append(frame)
        return self.mixer.blend(device, frames)

    model_config = ConfigDict(arbitrary_types_allowed=True)


def map_binding_value(mapping: patch_config.LinearMapSpec, value: int) -> float:
    if mapping.kind == 'positive_linear' and value <= 0:
        return mapping.output[0]
    start, end = mapping.input
    progress = max(0.0, min(1.0, (value - start) / (end - start)))
    return mapping.output[0] + progress * (mapping.output[1] - mapping.output[0])


def set_layer_speed(layer: midi.LightPatch, speed: float) -> None:
    if not isinstance(layer, midi.RegionLightPatch):
        raise ValueError('Layer speed control requires a region light patch')
    sources = []
    for source in layer.config.sources:
        if isinstance(source, RandomWalk):
            source = source.model_copy(update={'speed': speed})
        elif isinstance(source, twinkle.Twinkle):
            source = source.model_copy(update={'speed': round(speed)})
        elif isinstance(source, color_chase.ColorChase | rainbow.Rainbow):
            source = source.model_copy(update={'step': max(1, round(speed))})
        elif isinstance(source, reactive.ReactiveAnimation):
            source = source.model_copy(update={'speed': speed})
        sources.append(source)
    layer.config = compositions.Segments(
        sources=sources, placements=layer.config.placements
    )


def scale_wearable_layout(
    wearable: patch_config.WearableSpec, led_count: int
) -> patch_config.WearableSpec:
    if led_count <= 0:
        raise ValueError('runtime LED count must be greater than zero')
    planned_led_count = wearable.led_count
    assert planned_led_count is not None
    if led_count == planned_led_count:
        return wearable
    LOGGER.warning(
        f'[warn] Scaling wearable layout from {planned_led_count} LEDs to '
        f'{led_count} LEDs.'
    )
    physical_map = {
        name: patch_config.PhysicalRegionSpec(
            ranges=[
                _scaled_physical_range(
                    physical_range, planned_led_count, led_count, name
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
        segments[name] = patch_config.RegionSpec(
            start=start, led_count=region_led_count
        )
        start += region_led_count
    return patch_config.WearableSpec(
        led_count=led_count,
        physical_map_status=wearable.physical_map_status,
        segments=segments,
        physical_map=physical_map,
    )


def scale_patch_library(
    library: patch_config.PatchLibrary, led_count: int
) -> patch_config.PatchLibrary:
    return library.model_copy(
        update={'wearable': scale_wearable_layout(library.wearable, led_count)}
    )


def _scaled_physical_range(
    physical_range: patch_config.PhysicalRangeSpec,
    planned_led_count: int,
    actual_led_count: int,
    name: str,
) -> patch_config.PhysicalRangeSpec:
    return patch_config.PhysicalRangeSpec(
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
    wearable: patch_config.WearableSpec,
    logical_frame: NDArray[np.float32],
) -> NDArray[np.float32]:
    led_count = wearable.led_count
    assert led_count is not None
    device = animation.Device(led_count=led_count)
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
    wearable: patch_config.WearableSpec, logical_frame: NDArray[np.float32]
) -> NDArray[np.uint8]:
    return animation.byte_light_frame_from_float(
        map_logical_frame(wearable, logical_frame)
    )


def locator_frame(
    wearable: patch_config.WearableSpec,
    region: str,
    color: animation.FloatRGB = (1.0, 1.0, 1.0),
) -> NDArray[np.float32]:
    if region not in wearable.segments:
        raise ValueError(f'unknown wearable region: {region}')
    led_count = wearable.led_count
    assert led_count is not None
    device = animation.Device(led_count=led_count)
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
    library = patch_config.load_patch_library(config.library)
    if config.action == 'list':
        list_patch_library(library)
        return 0
    if config.action == 'locator':
        return run_locator(config, library)
    return run_patch_playback(config, library)


def list_patch_library(library: patch_config.PatchLibrary) -> None:
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


def run_locator(config: PatchCommandConfig, library: patch_config.PatchLibrary) -> int:
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


def run_patch_playback(
    config: PatchCommandConfig, library: patch_config.PatchLibrary
) -> int:
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
    library: patch_config.PatchLibrary,
    patch: midi.LightPatch,
    twinkly_track: track.TwinklyTrack,
) -> None:
    patch.fps = config.fps

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


def build_light_patch(library: patch_config.PatchLibrary, name: str) -> midi.LightPatch:
    if (patch := library.patches.get(name)) is None:
        raise ValueError(f'unknown patch: {name}')
    default_regions = patch.regions or list(library.wearable.segments)
    layers = {}
    for layer_name in patch.layers:
        layer = library.layers[layer_name]
        layer_regions = layer.regions or default_regions
        layers[layer_name] = midi.RegionLightPatch(
            config=compositions.Segments(
                sources=[build_layer_animation(layer) for _ in layer_regions],
                placements=[
                    compositions.Placement(
                        start=library.wearable.segments[region].start,
                        led_count=library.wearable.segments[region].led_count,
                    )
                    for region in layer_regions
                ],
            )
        )
    children = list(layers.values())
    weights = (
        [1.0] + [0.0] * (len(children) - 1)
        if patch.blend == 'weighted'
        else [1.0] * len(children)
    )
    mixer = midi.MixLightPatch(
        config=midi.MixLightPatchConfig(weights=weights), patches=children
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


def build_layer_animation(layer: patch_config.LayerSpec) -> animation.Animation:
    if layer.kind == 'velocity_splash':
        return reactive.VelocitySplash(speed=layer.speed, color=layer.color)
    if layer.kind == 'breath_bloom':
        return reactive.BreathBloom(speed=layer.speed, color=layer.color)
    if layer.kind == 'pitch_bend_travel':
        return reactive.PitchBendTravel(color=layer.color)
    if layer.kind == 'note_age_constellation':
        return reactive.NoteAgeConstellation(speed=layer.speed, color=layer.color)
    color = (layer.color[0], layer.color[1], layer.color[2])
    rgb = animation.rgb_from_float_color(color)
    if layer.kind == 'solid':
        return color_fill.ColorFill(color=list(rgb))
    if layer.kind == 'random_walk':
        return RandomWalk(
            speed=layer.speed,
            color=[color[0] * 255, color[1] * 255, color[2] * 255],
        )
    if layer.kind == 'twinkle':
        return twinkle.Twinkle(colors=[list(rgb)], speed=round(layer.speed))
    if layer.kind == 'chase':
        return color_chase.ColorChase(color=list(rgb), step=max(1, round(layer.speed)))
    return rainbow.Rainbow(step=max(1, round(layer.speed)))
