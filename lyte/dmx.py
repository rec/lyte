"""Typed DMX instruments, programs, and universe encoding."""

from __future__ import annotations

from typing import Annotated, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, SkipValidation, model_validator

DMX_CHANNEL_COUNT = 512


class DmxDefinition(BaseModel, frozen=True):
    model_config = ConfigDict(extra='forbid')


class BrightnessChannels(DmxDefinition, frozen=True):
    kind: Literal['brightness'] = 'brightness'
    channels: list[int] = Field(min_length=1)


class RgbChannels(DmxDefinition, frozen=True):
    kind: Literal['rgb'] = 'rgb'
    red: list[int] = Field(min_length=1)
    green: list[int] = Field(min_length=1)
    blue: list[int] = Field(min_length=1)


class WhiteChannels(DmxDefinition, frozen=True):
    kind: Literal['white'] = 'white'
    channels: list[int] = Field(min_length=1)


class ChaseSpeedChannels(DmxDefinition, frozen=True):
    kind: Literal['chase_speed'] = 'chase_speed'
    channels: list[int] = Field(min_length=1)


class PatternSelectChannels(DmxDefinition, frozen=True):
    kind: Literal['pattern_select'] = 'pattern_select'
    channels: list[int] = Field(min_length=1)
    patterns: dict[str, int] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_patterns(self) -> PatternSelectChannels:
        _validate_named_values(self.patterns, len(self.channels), 'pattern')
        return self


class StrobeChannels(DmxDefinition, frozen=True):
    kind: Literal['strobe'] = 'strobe'
    channels: list[int] = Field(min_length=1)


class PanChannels(DmxDefinition, frozen=True):
    kind: Literal['pan'] = 'pan'
    channels: list[int] = Field(min_length=1)


class TiltChannels(DmxDefinition, frozen=True):
    kind: Literal['tilt'] = 'tilt'
    channels: list[int] = Field(min_length=1)


class ColorWheelChannels(DmxDefinition, frozen=True):
    kind: Literal['color_wheel'] = 'color_wheel'
    channels: list[int] = Field(min_length=1)
    colors: dict[str, int] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_colors(self) -> ColorWheelChannels:
        _validate_named_values(self.colors, len(self.channels), 'color')
        return self


class GoboSelectChannels(DmxDefinition, frozen=True):
    kind: Literal['gobo_select'] = 'gobo_select'
    channels: list[int] = Field(min_length=1)
    gobos: dict[str, int] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_gobos(self) -> GoboSelectChannels:
        _validate_named_values(self.gobos, len(self.channels), 'gobo')
        return self


class RawChannels(DmxDefinition, frozen=True):
    kind: Literal['raw'] = 'raw'
    name: str = Field(min_length=1)
    channels: list[int] = Field(min_length=1)


DmxChannelCategory = Annotated[
    BrightnessChannels
    | RgbChannels
    | WhiteChannels
    | ChaseSpeedChannels
    | PatternSelectChannels
    | StrobeChannels
    | PanChannels
    | TiltChannels
    | ColorWheelChannels
    | GoboSelectChannels
    | RawChannels,
    Field(discriminator='kind'),
]


class DmxInstrument(DmxDefinition, frozen=True):
    name: str = Field(min_length=1)
    universe: int = Field(ge=1)
    start_channel: int = Field(ge=1, le=DMX_CHANNEL_COUNT)
    channel_count: int = Field(ge=1, le=DMX_CHANNEL_COUNT)
    categories: list[DmxChannelCategory] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_instrument(self) -> DmxInstrument:
        if self.start_channel + self.channel_count - 1 > DMX_CHANNEL_COUNT:
            raise ValueError('instrument channel range must end at or before 512')
        assigned: dict[int, str] = {}
        raw_names: set[str] = set()
        for category in self.categories:
            if isinstance(category, RawChannels):
                if category.name in raw_names:
                    raise ValueError(f'duplicate raw channel name {category.name!r}')
                raw_names.add(category.name)
            for channel in category_channel_offsets(category):
                if channel < 1 or channel > self.channel_count:
                    raise ValueError(
                        f'{category.kind} channel {channel} is outside instrument range'
                    )
                if (previous := assigned.get(channel)) is not None:
                    raise ValueError(
                        f'channel {channel} is assigned to both {previous} and '
                        f'{category.kind}'
                    )
                assigned[channel] = category.kind
        return self


class DmxFrame(DmxDefinition, frozen=True):
    universe: int = Field(ge=1)
    slots: SkipValidation[NDArray[np.uint8]]

    @model_validator(mode='after')
    def validate_frame(self) -> DmxFrame:
        validate_slots(self.slots)
        return self

    model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')


class DmxState(BaseModel):
    frame: int = 0
    fps: float = Field(default=40.0, gt=0)


class DmxValues(DmxDefinition, frozen=True):
    brightness: float | None = None
    rgb: list[float] | None = None
    white: float | None = None
    chase_speed: float | None = None
    pattern: str | None = None
    strobe: float | None = None
    pan: float | None = None
    tilt: float | None = None
    color: str | None = None
    gobo: str | None = None
    raw: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_values(self) -> DmxValues:
        for name in NORMALIZED_VALUE_NAMES:
            value = getattr(self, name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f'{name} must be between 0 and 1')
        if self.rgb is not None:
            if len(self.rgb) != 3:
                raise ValueError('rgb must contain red, green, and blue')
            if any(value < 0 or value > 1 for value in self.rgb):
                raise ValueError('rgb values must be between 0 and 1')
        if any(value < 0 for value in self.raw.values()):
            raise ValueError('raw values must not be negative')
        return self


class DmxProgram(DmxDefinition, frozen=True):
    def initial_state(self, instrument: DmxInstrument) -> DmxState:
        return DmxState()

    def render(self, instrument: DmxInstrument, state: DmxState) -> DmxValues:
        raise NotImplementedError


class StaticDmxProgram(DmxProgram, frozen=True):
    values: DmxValues

    def render(self, instrument: DmxInstrument, state: DmxState) -> DmxValues:
        state.frame += 1
        return self.values


class InstrumentOutput(DmxDefinition, frozen=True):
    instrument: DmxInstrument
    values: DmxValues


def validate_slots(slots: NDArray[np.uint8]) -> NDArray[np.uint8]:
    if slots.dtype != np.uint8:
        raise ValueError('DMX frame must have dtype uint8')
    if slots.shape != (DMX_CHANNEL_COUNT,):
        raise ValueError('DMX frame must contain exactly 512 slots')
    if not slots.flags.c_contiguous:
        raise ValueError('DMX frame must be C-contiguous')
    return slots


def blackout_frame(universe: int) -> DmxFrame:
    return DmxFrame(
        universe=universe, slots=np.zeros(DMX_CHANNEL_COUNT, dtype=np.uint8)
    )


def category_channel_offsets(category: DmxChannelCategory) -> list[int]:
    if isinstance(category, RgbChannels):
        return category.red + category.green + category.blue
    return category.channels


def encode_instrument(
    slots: NDArray[np.uint8], instrument: DmxInstrument, values: DmxValues
) -> NDArray[np.uint8]:
    encoded = validate_slots(slots).copy()
    for category in instrument.categories:
        if isinstance(category, BrightnessChannels) and values.brightness is not None:
            _write_normalized(encoded, instrument, category.channels, values.brightness)
        elif isinstance(category, RgbChannels) and values.rgb is not None:
            _write_normalized(encoded, instrument, category.red, values.rgb[0])
            _write_normalized(encoded, instrument, category.green, values.rgb[1])
            _write_normalized(encoded, instrument, category.blue, values.rgb[2])
        elif isinstance(category, WhiteChannels) and values.white is not None:
            _write_normalized(encoded, instrument, category.channels, values.white)
        elif (
            isinstance(category, ChaseSpeedChannels) and values.chase_speed is not None
        ):
            _write_normalized(
                encoded, instrument, category.channels, values.chase_speed
            )
        elif isinstance(category, PatternSelectChannels) and values.pattern is not None:
            _write_named(
                encoded,
                instrument,
                category.channels,
                category.patterns,
                values.pattern,
                'pattern',
            )
        elif isinstance(category, StrobeChannels) and values.strobe is not None:
            _write_normalized(encoded, instrument, category.channels, values.strobe)
        elif isinstance(category, PanChannels) and values.pan is not None:
            _write_normalized(encoded, instrument, category.channels, values.pan)
        elif isinstance(category, TiltChannels) and values.tilt is not None:
            _write_normalized(encoded, instrument, category.channels, values.tilt)
        elif isinstance(category, ColorWheelChannels) and values.color is not None:
            _write_named(
                encoded,
                instrument,
                category.channels,
                category.colors,
                values.color,
                'color',
            )
        elif isinstance(category, GoboSelectChannels) and values.gobo is not None:
            _write_named(
                encoded,
                instrument,
                category.channels,
                category.gobos,
                values.gobo,
                'gobo',
            )
        elif isinstance(category, RawChannels) and category.name in values.raw:
            _write_integer(
                encoded,
                instrument,
                category.channels,
                values.raw[category.name],
            )
    return np.ascontiguousarray(encoded)


def render_universes(outputs: list[InstrumentOutput]) -> dict[int, DmxFrame]:
    slots_by_universe: dict[int, NDArray[np.uint8]] = {}
    occupied_by_universe: dict[int, set[int]] = {}
    for output in outputs:
        instrument = output.instrument
        occupied = occupied_by_universe.setdefault(instrument.universe, set())
        instrument_slots = set(
            range(
                instrument.start_channel,
                instrument.start_channel + instrument.channel_count,
            )
        )
        if overlap := occupied.intersection(instrument_slots):
            first = min(overlap)
            raise ValueError(
                f'instrument {instrument.name!r} overlaps universe '
                f'{instrument.universe} channel {first}'
            )
        occupied.update(instrument_slots)
        slots = slots_by_universe.setdefault(
            instrument.universe, np.zeros(DMX_CHANNEL_COUNT, dtype=np.uint8)
        )
        slots_by_universe[instrument.universe] = encode_instrument(
            slots, instrument, output.values
        )
    return {
        universe: DmxFrame(universe=universe, slots=slots)
        for universe, slots in slots_by_universe.items()
    }


def _write_normalized(
    slots: NDArray[np.uint8],
    instrument: DmxInstrument,
    channels: list[int],
    value: float,
) -> None:
    maximum = 256 ** len(channels) - 1
    _write_integer(slots, instrument, channels, round(value * maximum))


def _write_named(
    slots: NDArray[np.uint8],
    instrument: DmxInstrument,
    channels: list[int],
    values: dict[str, int],
    name: str,
    category: str,
) -> None:
    if name not in values:
        raise ValueError(f'unknown {category} {name!r}')
    _write_integer(slots, instrument, channels, values[name])


def _write_integer(
    slots: NDArray[np.uint8],
    instrument: DmxInstrument,
    channels: list[int],
    value: int,
) -> None:
    maximum = 256 ** len(channels) - 1
    if value < 0 or value > maximum:
        raise ValueError(f'value {value} does not fit in {len(channels)} channels')
    encoded = value.to_bytes(len(channels))
    for channel, byte in zip(channels, encoded, strict=True):
        slots[instrument.start_channel + channel - 2] = byte


def _validate_named_values(
    values: dict[str, int], channel_count: int, category: str
) -> None:
    maximum = 256**channel_count - 1
    for name, value in values.items():
        if not name:
            raise ValueError(f'{category} names must not be empty')
        if value < 0 or value > maximum:
            raise ValueError(
                f'{category} value {value} does not fit in {channel_count} channels'
            )


NORMALIZED_VALUE_NAMES = [
    'brightness',
    'white',
    'chase_speed',
    'strobe',
    'pan',
    'tilt',
]
