from __future__ import annotations

import importlib
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, cast

import tyro
from pydantic import BaseModel, ConfigDict, Field, SkipValidation

from . import animation


class ShowConfig(BaseModel, frozen=True):
    files: Annotated[list[Path], tyro.conf.Positional]


class ShowFileError(ValueError):
    pass


class RunTargetSpec(BaseModel, frozen=True):
    source: str
    params: dict[str, object] = Field(default_factory=dict)


class AnimationSpec(BaseModel, frozen=True):
    impl: str
    sources: list[str] = Field(default_factory=list)
    params: dict[str, object] = Field(default_factory=dict)


class MixerSpec(BaseModel, frozen=True):
    impl: str
    sources: list[str] = Field(default_factory=list)
    params: dict[str, object] = Field(default_factory=dict)


class DeviceSpec(BaseModel, frozen=True):
    kind: str
    params: dict[str, object] = Field(default_factory=dict)


class ShowFile(BaseModel, frozen=True):
    run: dict[str, RunTargetSpec] | None = None
    animations: dict[str, AnimationSpec] = Field(default_factory=dict)
    mixers: dict[str, MixerSpec] = Field(default_factory=dict)
    devices: dict[str, DeviceSpec] = Field(default_factory=dict)


class ShowGraph(BaseModel, frozen=True):
    sources: dict[str, SkipValidation[animation.Animation]] = Field(
        default_factory=dict
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ResolvedShowFile(BaseModel, frozen=True):
    animations: dict[str, object] = Field(default_factory=dict)
    mixers: dict[str, object] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)


def run_show(config: ShowConfig) -> int:
    show_file = load_show_files(config.files)
    build_show_graph(show_file)
    return 0


def load_show_file(path: Path) -> ShowFile:
    with path.open('rb') as file:
        show_file = parse_show_file(tomllib.load(file), str(path))
    validate_graph(show_file)
    return show_file


def load_show_files(paths: list[Path]) -> ShowFile:
    if not paths:
        raise ShowFileError('at least one show file is required')
    show_files = []
    for path in paths:
        with path.open('rb') as file:
            show_files.append(parse_show_file(tomllib.load(file), str(path)))
    return merge_show_files(show_files)


def parse_show_file(data: dict[str, object], source: str) -> ShowFile:
    reject_unknown_top_level(data, source)
    return ShowFile(
        run=parse_run_section(optional_table(data, 'run', source), source),
        animations=parse_animation_specs(
            optional_table(data, 'animations', source), source
        ),
        mixers=parse_mixer_specs(optional_table(data, 'mixers', source), source),
        devices=parse_device_specs(optional_table(data, 'devices', source), source),
    )


def merge_show_files(show_files: list[ShowFile]) -> ShowFile:
    if not show_files:
        raise ShowFileError('at least one show file is required')
    run_sections = [show_file.run for show_file in show_files if show_file.run]
    if len(run_sections) > 1:
        raise ShowFileError('multiple loaded show files define run sections')
    merged = ShowFile(
        run=run_sections[0] if run_sections else None,
        animations=merge_namespace('animations', [f.animations for f in show_files]),
        mixers=merge_namespace('mixers', [f.mixers for f in show_files]),
        devices=merge_namespace('devices', [f.devices for f in show_files]),
    )
    validate_graph(merged)
    return merged


def build_show_graph(show_file: ShowFile) -> ShowGraph:
    validate_graph(show_file)
    sources = {}

    def build_source(name: str) -> animation.Animation:
        if name in sources:
            return sources[name]
        spec = show_file.animations.get(name) or show_file.mixers.get(name)
        if spec is None:
            raise ShowFileError(f'unknown source {name!r}')
        children = [build_source(source) for source in spec.sources]
        factory = resolve_python_path(spec.impl)
        params = dict(spec.params)
        if children:
            params['sources'] = children
        try:
            value = factory(**params)
        except TypeError as error:
            raise ShowFileError(
                f'could not construct source {name!r}: {error}'
            ) from error
        if not isinstance(value, animation.Animation):
            raise ShowFileError(f'source {name!r} did not construct an Animation')
        sources[name] = value
        return value

    for name in show_file.animations | show_file.mixers:
        build_source(name)
    return ShowGraph(sources=sources)


def resolve_show_file(show_file: ShowFile) -> ResolvedShowFile:
    return ResolvedShowFile(
        animations={
            name: resolve_python_path(spec.impl)
            for name, spec in show_file.animations.items()
        },
        mixers={
            name: resolve_python_path(spec.impl)
            for name, spec in show_file.mixers.items()
        },
    )


def resolve_python_path(path: str) -> Callable[..., object]:
    if '.' not in path:
        raise ShowFileError(f'implementation path {path!r} must include a module')
    module_path, name = path.rsplit('.', 1)
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as error:
        raise ShowFileError(f'could not import module {module_path!r}') from error
    try:
        value = getattr(module, name)
    except AttributeError as error:
        raise ShowFileError(
            f'module {module_path!r} has no attribute {name!r}'
        ) from error
    if not callable(value):
        raise ShowFileError(f'implementation path {path!r} is not callable')
    return cast(Callable[..., object], value)


def validate_graph(show_file: ShowFile) -> None:
    source_names = set(show_file.animations) | set(show_file.mixers)
    if show_file.run is not None:
        for device_name, target in show_file.run.items():
            if device_name not in show_file.devices:
                raise ValueError(f'run target {device_name!r} does not name a device')
            if target.source not in source_names:
                raise ValueError(
                    f'run target {device_name!r} names unknown source {target.source!r}'
                )
    for name, spec in show_file.animations.items():
        validate_source_names(f'animation {name!r}', spec.sources, source_names)
    for name, spec in show_file.mixers.items():
        validate_source_names(f'mixer {name!r}', spec.sources, source_names)
    validate_acyclic_sources(show_file)


def validate_source_names(
    label: str, sources: list[str], source_names: set[str]
) -> None:
    for source in sources:
        if source not in source_names:
            raise ValueError(f'{label} names unknown source {source!r}')


def validate_acyclic_sources(show_file: ShowFile) -> None:
    sources_by_name = {
        name: spec.sources for name, spec in show_file.animations.items()
    } | {name: spec.sources for name, spec in show_file.mixers.items()}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise ValueError(f'source graph contains a cycle at {name!r}')
        visiting.add(name)
        for source in sources_by_name[name]:
            visit(source)
        visiting.remove(name)
        visited.add(name)

    for name in sources_by_name:
        visit(name)


def reject_unknown_top_level(data: dict[str, object], source: str) -> None:
    allowed = {'run', 'animations', 'mixers', 'devices'}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ShowFileError(
            f'{source}: unknown top-level sections: {", ".join(unknown)}'
        )


def optional_table(
    data: dict[str, object], name: str, source: str
) -> dict[str, object]:
    value = data.get(name, {})
    return object_table(value, f'{source}: {name}')


def parse_run_section(
    data: dict[str, object], source: str
) -> dict[str, RunTargetSpec] | None:
    if not data:
        return None
    return {name: parse_run_target(name, value, source) for name, value in data.items()}


def parse_run_target(name: str, value: object, source: str) -> RunTargetSpec:
    if isinstance(value, str):
        return RunTargetSpec(source=value)
    if isinstance(value, dict):
        table = object_table(value, f'{source}: run.{name}')
        target_source = required_string(table, 'source', f'{source}: run.{name}')
        return RunTargetSpec(
            source=target_source, params=params_without(table, {'source'})
        )
    raise ShowFileError(f'{source}: run.{name} must be a string or table')


def parse_animation_specs(
    data: dict[str, object], source: str
) -> dict[str, AnimationSpec]:
    specs = {}
    for name, value in data.items():
        table = named_table(value, f'{source}: animations.{name}')
        specs[name] = AnimationSpec(
            impl=required_string(table, 'impl', f'{source}: animations.{name}'),
            sources=optional_string_list(
                table, 'sources', f'{source}: animations.{name}'
            ),
            params=params_without(table, {'impl', 'sources'}),
        )
    return specs


def parse_mixer_specs(data: dict[str, object], source: str) -> dict[str, MixerSpec]:
    specs = {}
    for name, value in data.items():
        table = named_table(value, f'{source}: mixers.{name}')
        specs[name] = MixerSpec(
            impl=required_string(table, 'impl', f'{source}: mixers.{name}'),
            sources=optional_string_list(table, 'sources', f'{source}: mixers.{name}'),
            params=params_without(table, {'impl', 'sources'}),
        )
    return specs


def parse_device_specs(data: dict[str, object], source: str) -> dict[str, DeviceSpec]:
    specs = {}
    for name, value in data.items():
        table = named_table(value, f'{source}: devices.{name}')
        specs[name] = DeviceSpec(
            kind=required_string(table, 'kind', f'{source}: devices.{name}'),
            params=params_without(table, {'kind'}),
        )
    return specs


def named_table(value: object, label: str) -> dict[str, object]:
    return object_table(value, label)


def object_table(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ShowFileError(f'{label} must be a table')
    if any(not isinstance(k, str) for k in value):
        raise ShowFileError(f'{label} table keys must be strings')
    return cast(dict[str, object], value)


def required_string(data: dict[str, object], name: str, label: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise ShowFileError(f'{label}.{name} must be a non-empty string')
    return value


def optional_string_list(data: dict[str, object], name: str, label: str) -> list[str]:
    value = data.get(name, [])
    if not isinstance(value, list) or any(
        not isinstance(s, str) or not s for s in value
    ):
        raise ShowFileError(f'{label}.{name} must be a list of non-empty strings')
    return [s for s in value if isinstance(s, str)]


def params_without(data: dict[str, object], names: set[str]) -> dict[str, object]:
    return {name: value for name, value in data.items() if name not in names}


def merge_namespace[T](namespace: str, sections: list[dict[str, T]]) -> dict[str, T]:
    merged: dict[str, T] = {}
    for section in sections:
        for name, value in section.items():
            if name in merged:
                raise ShowFileError(f'duplicate {namespace} name {name!r}')
            merged[name] = value
    return merged
