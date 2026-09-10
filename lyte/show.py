"""Ufor score selection and Lyte renderer preparation."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import tyro
from pydantic import BaseModel, Field
from reccy.runtime import logging
from ufor import library_files
from ufor.library import Library
from ufor.lights import Wiring

from .rendering import PreparedAnimation

LOGGER = logging.get_logger(__name__)


class ShowFileError(ValueError):
    pass


class LightProgramSpec(BaseModel, frozen=True):
    selector: str = Field(min_length=1)
    output: str = Field(default='light', min_length=1)
    parameters: dict[str, float] = Field(default_factory=dict)
    wiring: list[str] | None = None


class ShowConfig(BaseModel, frozen=True):
    selector: Annotated[str, tyro.conf.Positional]
    library_config: Path | None = None
    output: str = 'light'
    parameters: dict[str, float] = Field(default_factory=dict)
    wiring: list[str] | None = None


def run_show(config: ShowConfig) -> int:
    prepare_animation(
        LightProgramSpec(
            selector=config.selector,
            output=config.output,
            parameters=config.parameters,
            wiring=config.wiring,
        ),
        config.library_config,
    )
    return 0


def prepare_animation(
    program: LightProgramSpec, library_config: Path | None = None
) -> PreparedAnimation:
    try:
        library = library_files.read_library(library_config)
        log_diagnostics(library)
        return prepare_library_animation(library, program)
    except (OSError, ValueError) as error:
        raise ShowFileError(str(error)) from error


def prepare_library_animation(
    library: Library, program: LightProgramSpec
) -> PreparedAnimation:
    composition = library.composition(program.selector, program.parameters)
    wiring = None if program.wiring is None else Wiring(order=program.wiring)
    return PreparedAnimation(library, composition, program.output, wiring)


def log_diagnostics(library: Library) -> None:
    for diagnostic in library.diagnostics:
        details = []
        if diagnostic.field is not None:
            details.append(f'field={diagnostic.field}')
        if diagnostic.cycle:
            details.append(f'cycle={" -> ".join(diagnostic.cycle)}')
        suffix = '' if not details else f' ({", ".join(details)})'
        LOGGER.warning(
            f'[{diagnostic.code}] {diagnostic.library}:{diagnostic.address}: '
            f'{diagnostic.message}{suffix}'
        )
