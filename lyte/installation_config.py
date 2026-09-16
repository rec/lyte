"""Installation TOML schema, MIDI mappings, and output expressions."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from . import runtime_control
from .midi import MidiIn
from .twinkly import diagnostic

_STRING_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]*\Z')
_GESTALT_FIELDS = (
    'device_name',
    'product_name',
    'product_code',
    'hardware_id',
    'firmware_family',
    'led_profile',
)


class InstallationFileError(ValueError):
    pass


class InstallationDefinition(BaseModel, frozen=True):
    model_config = ConfigDict(extra='forbid')


class TwinklySelector(InstallationDefinition, frozen=True):
    device_name: str | None = None
    product_name: str | None = None
    product_code: str | None = None
    hardware_id: str | None = None
    firmware_family: str | None = None
    led_profile: str | None = None

    def matches(self, device: diagnostic.TwinklyDeviceInfo) -> bool:
        return all(
            value is None
            or (candidate is not None and value.casefold() in candidate.casefold())
            for field in _GESTALT_FIELDS
            for value, candidate in [(getattr(self, field), getattr(device, field))]
        )


class ParameterControl(InstallationDefinition, frozen=True):
    source: Literal['gate', 'note', 'velocity', 'breath', 'pitch_bend']
    parameter: str = Field(min_length=1)
    output: list[float] | None = None
    values: list[float] = Field(default_factory=list)

    @model_validator(mode='after')
    def mapping(self) -> ParameterControl:
        if self.output is not None and len(self.output) != 2:
            raise ValueError('control output must contain minimum and maximum')
        if self.values and self.source != 'note':
            raise ValueError('control value tables require the note source')
        if self.values and self.output is not None:
            raise ValueError('control cannot define both output and values')
        return self

    def map(self, performance: runtime_control.MidiPerformance) -> float:
        value = performance.value(self.source)
        if self.values:
            return self.values[int(value) % len(self.values)]
        if self.output is None:
            return value
        minimum, maximum = _CONTROL_RANGES[self.source]
        progress = (value - minimum) / (maximum - minimum)
        return self.output[0] + progress * (self.output[1] - self.output[0])


class AnimationDefaults(InstallationDefinition, frozen=True):
    activation: Literal['always', 'note'] = 'always'
    controls: list[ParameterControl] = Field(default_factory=list)


class BoundAnimation(InstallationDefinition, frozen=True):
    selector: str = Field(min_length=1)
    outputs: dict[str, str] = Field(min_length=1)
    activation: Literal['always', 'note'] = 'always'
    controls: list[ParameterControl] = Field(default_factory=list)

    @model_validator(mode='after')
    def distinct_controls(self) -> BoundAnimation:
        parameters = [c.parameter for c in self.controls]
        if len(parameters) != len(set(parameters)):
            raise ValueError('animation controls must target distinct parameters')
        return self


class InstallationFile(InstallationDefinition, frozen=True):
    library_config: Path | None = None
    twinkly: dict[str, TwinklySelector] = Field(min_length=1)
    animation_defaults: AnimationDefaults = Field(default_factory=AnimationDefaults)
    animations: dict[str, BoundAnimation] = Field(min_length=1)
    initial_animation: str
    fps: float = Field(default=30.0, gt=0)
    timeout: float = Field(default=5.0, gt=0)
    attempts: int = Field(default=10, gt=0)
    retry_delay: float = Field(default=0.5, ge=0)
    retry_backoff: float = Field(default=2.0, ge=1)
    discovery_timeout: float = Field(default=5.0, gt=0)
    startup_timeout: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    midi: MidiIn | None = None

    @model_validator(mode='after')
    def controls_require_midi(self) -> InstallationFile:
        animations = {
            name: animation.model_copy(
                update={
                    **(
                        {'activation': self.animation_defaults.activation}
                        if 'activation' not in animation.model_fields_set
                        else {}
                    ),
                    **(
                        {'controls': self.animation_defaults.controls}
                        if 'controls' not in animation.model_fields_set
                        else {}
                    ),
                }
            )
            for name, animation in self.animations.items()
        }
        object.__setattr__(self, 'animations', animations)
        if self.midi is None and any(
            a.activation == 'note' or a.controls for a in animations.values()
        ):
            raise ValueError('controlled animations require MIDI configuration')
        return self


@dataclass(frozen=True)
class OutputExpression:
    members: list[str]
    operator: Literal['single', 'concat', 'mirror']


def parse_output_expression(value: str, strings: Iterable[str]) -> OutputExpression:
    known = set(strings)
    if not value or value != value.strip():
        raise ValueError(
            'output expression must not have leading or trailing whitespace'
        )
    plus = '+' in value
    star = '*' in value
    if plus and star:
        raise ValueError('output expression cannot mix + and *')
    if plus:
        members = value.split(' + ')
        operator: Literal['single', 'concat', 'mirror'] = 'concat'
    elif star:
        members = value.split(' * ')
        operator = 'mirror'
    else:
        members = [value]
        operator = 'single'
    if len(members) != len(set(members)):
        raise ValueError('output expression cannot name a string more than once')
    if any(not _STRING_NAME.fullmatch(member) for member in members):
        raise ValueError('output expression must use spaces around + or *')
    unknown = sorted(set(members) - known)
    if unknown:
        raise ValueError(f'output expression names unknown string {unknown[0]!r}')
    return OutputExpression(members, operator)


def load_installation(path: Path) -> InstallationFile:
    try:
        with path.open('rb') as source:
            config = parse_installation(tomllib.load(source))
        if (
            config.library_config is not None
            and not config.library_config.is_absolute()
        ):
            config = config.model_copy(
                update={'library_config': path.parent / config.library_config}
            )
        return config
    except (OSError, tomllib.TOMLDecodeError, ValidationError, ValueError) as error:
        raise InstallationFileError(f'{path}: {error}') from error


def parse_installation(data: dict[str, object]) -> InstallationFile:
    allowed = {
        'library_config',
        'twinkly',
        'animation_defaults',
        'animations',
        'initial_animation',
        'fps',
        'timeout',
        'attempts',
        'retry_delay',
        'retry_backoff',
        'discovery_timeout',
        'startup_timeout',
        'midi',
    }
    if unknown := sorted(set(data) - allowed):
        raise ValueError(f'unknown top-level sections: {", ".join(unknown)}')
    config = InstallationFile.model_validate(data)
    _validate_installation(config)
    return config


def _validate_installation(config: InstallationFile) -> None:
    for name in config.twinkly:
        if not _STRING_NAME.fullmatch(name):
            raise ValueError(f'Twinkly string name {name!r} is not an identifier')
    for name, definition in config.animations.items():
        used: set[str] = set()
        for expression in definition.outputs.values():
            parsed = parse_output_expression(expression, config.twinkly)
            duplicate = used.intersection(parsed.members)
            if duplicate:
                raise ValueError(
                    f'animation {name!r} binds string {min(duplicate)!r} more than once'
                )
            used.update(parsed.members)
        missing = set(config.twinkly) - used
        if missing:
            raise ValueError(
                f'animation {name!r} does not bind string {min(missing)!r}'
            )
    if config.initial_animation not in config.animations:
        raise ValueError('initial_animation names an unknown animation')


_CONTROL_RANGES = {
    'gate': (0.0, 1.0),
    'note': (0.0, 127.0),
    'velocity': (0.0, 1.0),
    'breath': (0.0, 1.0),
    'pitch_bend': (-1.0, 1.0),
}
