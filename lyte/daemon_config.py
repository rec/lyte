"""Daemon configuration loaded from TOML."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SkipValidation, model_validator

from . import midi, patches


class DaemonConfigError(ValueError):
    pass


class TwinklyDaemonConfig(BaseModel, frozen=True):
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float | None = None
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0

    @model_validator(mode='after')
    def validate_connection(self) -> TwinklyDaemonConfig:
        if self.timeout <= 0:
            raise ValueError('twinkly timeout must be greater than zero')
        if self.discovery_timeout is not None and self.discovery_timeout <= 0:
            raise ValueError('twinkly discovery_timeout must be greater than zero')
        if self.attempts < 1:
            raise ValueError('twinkly attempts must be at least one')
        if self.retry_delay < 0:
            raise ValueError('twinkly retry_delay must not be negative')
        if self.retry_backoff < 1:
            raise ValueError('twinkly retry_backoff must be at least one')
        return self

    model_config = ConfigDict(extra='forbid')


class DaemonConfig(BaseModel, frozen=True):
    patch_library: Path
    patch_names: list[str] = Field(alias='patches')
    fps: float = 60.0
    midi: midi.MidiIn
    twinkly: TwinklyDaemonConfig

    @model_validator(mode='after')
    def validate_daemon(self) -> DaemonConfig:
        if not self.patch_names:
            raise ValueError('patches must not be empty')
        if len(set(self.patch_names)) != len(self.patch_names):
            raise ValueError('patches must not contain duplicates')
        if self.fps <= 0:
            raise ValueError('fps must be greater than zero')
        return self

    model_config = ConfigDict(extra='forbid', populate_by_name=True)


class DaemonProject(BaseModel, frozen=True):
    config: DaemonConfig
    library: SkipValidation[patches.PatchLibrary]

    model_config = ConfigDict(arbitrary_types_allowed=True)


def load_daemon_project(path: Path) -> DaemonProject:
    try:
        with path.open('rb') as source:
            data = tomllib.load(source)
        daemon = data.get('daemon')
        if not isinstance(daemon, dict):
            raise ValueError('daemon section must be a table')
        config = DaemonConfig.model_validate(
            daemon | {'midi': data.get('midi'), 'twinkly': data.get('twinkly')}
        )
    except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
        raise DaemonConfigError(f'{path}: {error}') from error
    config = config.model_copy(
        update={'patch_library': path.parent / config.patch_library}
    )
    try:
        library = patches.load_patch_library(config.patch_library)
    except patches.PatchLibraryError as error:
        raise DaemonConfigError(str(error)) from error
    if library.wearable.physical_map_status == 'provisional':
        raise DaemonConfigError(
            'daemon requires a guessed or measured wearable physical map'
        )
    unknown = set(config.patch_names).difference(library.patches)
    if unknown:
        raise DaemonConfigError(
            f'daemon names unknown patches: {", ".join(sorted(unknown))}'
        )
    return DaemonProject(config=config, library=library)
