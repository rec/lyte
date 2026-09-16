"""Loopback browser editor for declared uFor animation parameters."""

from __future__ import annotations

import math
from base64 import b64encode
from dataclasses import dataclass, field, replace
from fractions import Fraction
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Literal, cast
from zipfile import ZIP_DEFLATED, ZipFile

import tomlkit
from pydantic import BaseModel, Field
from tomlkit.items import Table
from ufor import codec, effects, library_files, light_animation
from ufor.base import Model
from ufor.composition import Composition
from ufor.interface import ScoreVersion
from ufor.library import Entry, Library, State
from ufor.light_animation import AnimationScore
from ufor.lights import LightType
from ufor.preset import PresetScore
from ufor.selector import LibraryConfig

from . import (
    animation,
    authoring_colors,
    authoring_composition,
    reactive_effects,
    reactivity,
    show,
)
from .authoring_template import AUTHOR_TEMPLATE
from .preview.document import encoded_frames, preview_frame_count, safe_json


class AuthorConfig(BaseModel, frozen=True):
    library_config: Path | None = None
    light_output: str = 'light'
    duration: float = Field(default=10, gt=0)
    port: int = Field(default=8765, ge=1024, le=65535)
    open: bool = True


@dataclass(frozen=True)
class AuthorParameter:
    name: str
    minimum: float
    maximum: float
    default: float
    unit: str
    description: str = ''

    def document(self) -> dict[str, object]:
        return {
            'name': self.name,
            'minimum': self.minimum,
            'maximum': self.maximum,
            'default': self.default,
            'unit': self.unit,
            'description': self.description,
        }


@dataclass(frozen=True)
class AuthorAnimation:
    selector: str
    title: str
    parameters: list[AuthorParameter]
    renderer: Literal['ufor', 'builtin'] = 'ufor'
    composition: dict[str, object] | None = None
    source: str | None = None
    source_kind: str = 'Built-in preview'
    outputs: list[str] = field(default_factory=list)
    library: str = 'builtin'
    name: str = ''
    tags: list[str] = field(default_factory=list)
    family: str = 'reactive'
    rate: str = ''
    light_count: int = 0
    diagnostics: list[str] = field(default_factory=list)
    used_by: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)

    def document(self) -> dict[str, object]:
        return {
            'selector': self.selector,
            'title': self.title,
            'parameters': [parameter.document() for parameter in self.parameters],
            'renderer': self.renderer,
            'composition': self.composition,
            'source': self.source,
            'source_kind': self.source_kind,
            'outputs': self.outputs,
            'library': self.library,
            'name': self.name,
            'tags': self.tags,
            'family': self.family,
            'rate': self.rate,
            'light_count': self.light_count,
            'diagnostics': self.diagnostics,
            'used_by': self.used_by,
            'dependencies': self.dependencies,
        }


class DocumentEdit(BaseModel, frozen=True):
    entry: str
    output: str
    before: str
    after: str


class AuthoringSession:
    def __init__(self, library: Library, config: AuthorConfig) -> None:
        self.library = library
        self.config = config
        self.documents: dict[str, str] = {}
        self.original_documents: dict[str, str] = {}
        self.undo_history: list[DocumentEdit] = []
        self.redo_history: list[DocumentEdit] = []
        self.animations = [
            *_author_animations(library, config.light_output),
            *_builtin_animations(),
        ]

    def preview(self, selector: str, parameters: dict[str, float]) -> dict[str, object]:
        selected = self._animation(selector)
        if selected.renderer == 'builtin':
            return _builtin_preview(
                selector.removeprefix('builtin:'), parameters, self.config.duration
            )
        prepared = show.prepare_library_animation(
            self.library,
            show.LightProgramSpec(
                selector=selector,
                output=self.config.light_output,
                parameters=parameters,
            ),
        )
        if prepared.output.components != ['red', 'green', 'blue']:
            raise ValueError('authoring preview requires red, green, blue components')
        points = [
            [*light.position, *([0.0] * (2 - len(light.position)))]
            for light in prepared.output.layout.lights
        ]
        return {
            'coords': [point[:2] for point in points],
            'fps': prepared.fps,
            'frames': encoded_frames(prepared, self.config.duration),
        }

    def thumbnail(self, selector: str) -> dict[str, object]:
        selected = self._animation(selector)
        if selected.renderer != 'ufor':
            raise ValueError('thumbnails require a library score')
        prepared = show.prepare_library_animation(
            self.library,
            show.LightProgramSpec(selector=selector, output=self.config.light_output),
        )
        preview_frame_count(1, 1, len(prepared.output.layout.lights) * 3)
        frame = animation.byte_light_frame_from_float(prepared.render())
        return {
            'coords': [
                (p.position + [0.0, 0.0])[:2] for p in prepared.output.layout.lights
            ],
            'frame': b64encode(memoryview(frame).cast('B')).decode('ascii'),
        }

    def preset_document(
        self, selector: str, parameters: dict[str, float], name: str
    ) -> str:
        selected = self._animation(selector)
        if selected.renderer != 'ufor':
            raise ValueError(
                'built-in reactive effects cannot be saved as uFor presets'
            )
        preset = PresetScore(
            name=name,
            title=f'{selected.title} preset',
            score=ScoreVersion(selector=selector),
            parameters=parameters,
        )
        entries = [
            entry.model_copy(
                update={
                    'state': State.pending,
                    'dependencies': {},
                    'resolved': None,
                    'content_origin': None,
                }
            )
            for entry in self.library.entries.values()
        ]
        address = f'/{name}.toml'
        validation_library = Library(
            [
                *entries,
                Entry(library='author', address=address, name=name, score=preset),
            ]
        )
        show.prepare_library_animation(
            validation_library,
            show.LightProgramSpec(
                selector=f'author:{address}', output=self.config.light_output
            ),
        )
        return codec.score_toml(preset)

    def operation_document(self, entry_key: str, output: str, template: str) -> str:
        entry = self.library.entries.get(entry_key)
        if entry is None or not isinstance(entry.score, AnimationScore):
            raise ValueError(
                'selected operation is not backed by a TOML animation score'
            )
        source = self._source_path(entry)
        if source.suffix != '.toml':
            raise ValueError(
                'selected operation is not backed by a TOML animation score'
            )
        document = tomlkit.parse(
            self.documents[entry_key]
            if entry_key in self.documents
            else source.read_text()
        )
        operation = _operation_template(template, entry.score)
        body = document.get('body')
        if not isinstance(body, Table):
            raise ValueError(f'{source}: animation body is missing')
        body['operation'] = tomlkit.item(operation.model_dump(mode='json'))
        text = tomlkit.dumps(document)
        return self._apply_document(entry_key, output, text)

    def timeline_document(
        self, entry_key: str, output: str, timing: dict[str, object]
    ) -> str:
        entry = self.library.entries.get(entry_key)
        if entry is None or not isinstance(entry.score, AnimationScore):
            raise ValueError('selected timing is not backed by a TOML animation score')
        source = self._source_path(entry)
        if source.suffix != '.toml':
            raise ValueError('selected timing is not backed by a TOML animation score')
        document = tomlkit.parse(
            self.documents[entry_key]
            if entry_key in self.documents
            else source.read_text()
        )
        body = document.get('body')
        if not isinstance(body, Table):
            raise ValueError(f'{source}: animation body is missing')
        operation = body.get('operation')
        if not isinstance(operation, Table):
            raise ValueError(f'{source}: animation operation is missing')
        if isinstance(entry.score.body.operation, light_animation.Cues):
            events = timing.get('events')
            cues = operation.get('cues')
            if not isinstance(events, list) or not isinstance(cues, list):
                raise ValueError('cues require timing events')
            if len(events) != len(cues):
                raise ValueError('cues require one timing event per cue')
            for index, (event, cue) in enumerate(zip(events, cues, strict=True)):
                if not isinstance(event, dict) or not isinstance(cue, Table):
                    raise ValueError('cues require timing events')
                cue['start'] = _rational_value(event.get('start'), f'cue {index} start')
                cue['duration'] = _rational_value(
                    event.get('duration'), f'cue {index} duration'
                )
        elif isinstance(entry.score.body.operation, light_animation.Crossfade):
            fade = operation.get('fade')
            if not isinstance(fade, Table):
                raise ValueError(f'{source}: crossfade is missing its fade')
            fade['duration'] = _rational_value(timing.get('duration'), 'fade duration')
        else:
            raise ValueError(
                'selected operation has no editable cue or crossfade timing'
            )
        text = tomlkit.dumps(document)
        return self._apply_document(entry_key, output, text)

    def field_document(
        self, entry_key: str, output: str, fields: dict[str, object]
    ) -> str:
        entry = self.library.entries.get(entry_key)
        if entry is None or not isinstance(entry.score, AnimationScore):
            raise ValueError('selected fields are not backed by a TOML animation score')
        operation = entry.score.body.operation
        editable = _operation_fields(operation)
        if fields.keys() != editable.keys():
            raise ValueError('operation fields do not match the selected operation')
        edited_operation = type(operation).model_validate(
            operation.model_dump(mode='json') | fields
        )
        source = self._source_path(entry)
        if source.suffix != '.toml':
            raise ValueError('selected fields are not backed by a TOML animation score')
        document = tomlkit.parse(
            self.documents[entry_key]
            if entry_key in self.documents
            else source.read_text()
        )
        body = document.get('body')
        if not isinstance(body, Table):
            raise ValueError(f'{source}: animation body is missing')
        document_operation = body.get('operation')
        if not isinstance(document_operation, Table):
            raise ValueError(f'{source}: animation operation is missing')
        for name, value in _operation_fields(edited_operation).items():
            document_operation[name] = tomlkit.item(value)
        text = tomlkit.dumps(document)
        return self._apply_document(entry_key, output, text)

    def color_document(
        self, entry_key: str, output: str, fields: dict[str, object]
    ) -> str:
        entry = self.library.entries.get(entry_key)
        if (
            entry is None
            or not isinstance(entry.score, AnimationScore)
            or not entry.address.endswith('.toml')
        ):
            raise ValueError('colour editing requires a direct TOML animation')
        text = authoring_colors.color_document(
            self.source_document(entry_key), entry.score, fields
        )
        return self._apply_document(entry_key, output, text)

    def source_document(self, entry_key: str) -> str:
        if entry_key in self.documents:
            return self.documents[entry_key]
        return self._source_path(self.library.entries[entry_key]).read_text()

    def structure_document(
        self, entry_key: str, output: str, structure: dict[str, object], *, apply: bool
    ) -> str:
        entry = self.library.entries.get(entry_key)
        if (
            entry is None
            or not isinstance(entry.score, AnimationScore)
            or not entry.address.endswith('.toml')
        ):
            raise ValueError('composition editing requires a direct TOML animation')
        source = self.documents.get(entry_key)
        if source is None:
            source = self._source_path(entry).read_text()
        text = authoring_composition.composition_document(
            source, entry.score, structure
        )
        if apply:
            return self._apply_document(entry_key, output, text)
        self._prepare_document(entry_key, output, text)
        return text

    def changed_documents(self) -> dict[str, str]:
        return {
            k: v
            for k, v in sorted(self.documents.items())
            if v != self.original_documents[k]
        }

    def download_bundle(self) -> dict[str, object]:
        changed = self.changed_documents()
        if not changed:
            raise ValueError('There are no changed scores to download')
        buffer = BytesIO()
        with ZipFile(buffer, 'w', compression=ZIP_DEFLATED) as archive:
            for key, text in changed.items():
                entry = self.library.entries[key]
                if entry.library in {'.', '..'} or any(
                    c in entry.library for c in ('\\', '\x00')
                ):
                    raise ValueError(f'{entry.library!r}: unsafe ZIP directory name')
                path = f'{entry.library}/{entry.address.lstrip("/")}'
                archive.writestr(path, text)
        return {
            'filename': 'lyte-edits.zip',
            'archive': b64encode(buffer.getvalue()).decode('ascii'),
            'revisions': {k: document_revision(v) for k, v in changed.items()},
        }

    def history_state(self) -> dict[str, object]:
        changed = self.changed_documents()
        return {
            'can_undo': bool(self.undo_history),
            'can_redo': bool(self.redo_history),
            'changed': list(changed),
            'revisions': {k: document_revision(v) for k, v in changed.items()},
        }

    def undo(self) -> None:
        if not self.undo_history:
            raise ValueError('There is no edit to undo')
        edit = self.undo_history[-1]
        self._restore_document(edit.entry, edit.output, edit.before)
        self.undo_history.pop()
        self.redo_history.append(edit)

    def redo(self) -> None:
        if not self.redo_history:
            raise ValueError('There is no edit to redo')
        edit = self.redo_history[-1]
        self._restore_document(edit.entry, edit.output, edit.after)
        self.redo_history.pop()
        self.undo_history.append(edit)

    def _apply_document(self, entry_key: str, output: str, text: str) -> str:
        before = (
            self.documents[entry_key]
            if entry_key in self.documents
            else self._source_path(self.library.entries[entry_key]).read_text()
        )
        self._restore_document(entry_key, output, text)
        self.original_documents.setdefault(entry_key, before)
        self.undo_history.append(
            DocumentEdit(entry=entry_key, output=output, before=before, after=text)
        )
        self.redo_history.clear()
        return text

    def _restore_document(self, entry_key: str, output: str, text: str) -> None:
        library, animations = self._prepare_document(entry_key, output, text)
        self.library = library
        self.animations = animations
        self.documents[entry_key] = text

    def _prepare_document(
        self, entry_key: str, output: str, text: str
    ) -> tuple[Library, list[AuthorAnimation]]:
        edited = codec.parse_score(text)
        if not isinstance(edited, AnimationScore):
            raise ValueError('edited score is not an animation')
        library = _validation_library(self.library, entry_key, edited)
        broken = [
            e.key
            for e in self.library.entries.values()
            if e.state == State.ready and library.entries[e.key].state != State.ready
        ]
        if broken:
            details = '; '.join(
                f'{d.library}:{d.address}: {d.message}' for d in library.diagnostics
            )
            raise ValueError(details or f'edit makes scores unavailable: {broken}')
        show.prepare_library_animation(
            library, show.LightProgramSpec(selector=entry_key, output=output)
        )
        animations = [
            *_author_animations(library, self.config.light_output),
            *_builtin_animations(),
        ]
        previously_ready = {a.selector for a in self.animations if not a.diagnostics}
        failures = [
            a for a in animations if a.selector in previously_ready and a.diagnostics
        ]
        if failures:
            raise ValueError(
                '; '.join(f'{a.selector}: {", ".join(a.diagnostics)}' for a in failures)
            )
        return library, animations

    def _animation(self, selector: str) -> AuthorAnimation:
        for item in self.animations:
            if item.selector == selector:
                if item.diagnostics:
                    raise ValueError('; '.join(item.diagnostics))
                return item
        raise ValueError(f'unknown animation {selector!r}')

    def _source_path(self, entry: Entry) -> Path:
        config_path = library_files.configuration_path(self.config.library_config)
        config = LibraryConfig.model_validate(tomlkit.parse(config_path.read_text()))
        registration = next(
            (item for item in config.libraries if item.name == entry.library), None
        )
        if registration is None:
            raise ValueError(f'{entry.library}: library registration is missing')
        root = library_files.expanded_path(registration.root)
        if not root.is_absolute():
            root = config_path.parent / root
        return root / entry.address.removeprefix('/')


def document_revision(text: str) -> str:
    return sha256(text.encode()).hexdigest()


def author_document(
    animations: list[AuthorAnimation], history: dict[str, object] | None = None
) -> str:
    if not animations:
        raise ValueError('authoring document requires at least one animation')
    catalog = safe_json([animation.document() for animation in animations])
    return AUTHOR_TEMPLATE.replace('__LYTE_AUTHOR_CATALOG__', catalog).replace(
        '__LYTE_AUTHOR_HISTORY__', safe_json(history or {})
    )


def _author_animations(library: Library, output: str) -> list[AuthorAnimation]:
    animations = []
    for entry in library.entries.values():
        score = entry.resolved
        if entry.state == State.ready and not isinstance(score, AnimationScore):
            continue
        item = AuthorAnimation(
            selector=entry.key,
            title=getattr(score, 'title', None) or entry.name or entry.key,
            parameters=[],
            source=entry.key,
            source_kind=_source_kind(entry),
            library=entry.library,
            name=entry.name or '',
            tags=entry.tags,
            family='unavailable',
            diagnostics=[
                f'{d.code}: {d.field + ": " if d.field else ""}{d.message}'
                + (f' (cycle: {" -> ".join(d.cycle)})' if d.cycle else '')
                for d in library.diagnostics
                if d.library == entry.library and d.address == entry.address
            ],
            used_by=sorted(
                e.key
                for e in library.entries.values()
                if entry.key in e.dependencies.values()
            ),
            dependencies=sorted(set(entry.dependencies.values())),
        )
        if isinstance(score, AnimationScore) and entry.state == State.ready:
            stream = score.outputs[0].stream
            assert isinstance(stream, LightType)
            rate = score.timebases[0].rate
            try:
                prepared = show.prepare_library_animation(
                    library, show.LightProgramSpec(selector=entry.key, output=output)
                )
                if stream.components != ['red', 'green', 'blue']:
                    raise ValueError(
                        'authoring preview requires red, green, blue components'
                    )
                composition = prepared.composition
                parameters = [
                    AuthorParameter(
                        name=e.name,
                        minimum=c.minimum,
                        maximum=c.maximum,
                        default=c.default,
                        unit=c.unit,
                        description=f'Controls {e.binding.name}.{e.binding.parameter}',
                    )
                    for e in score.parameters
                    for c in [composition.parameter_contract(composition.root, e.name)]
                ]
                tree = _composition_tree(library, composition, output)
            except ValueError as error:
                item.diagnostics.append(str(error))
                parameters = []
                tree = None
            item = replace(
                item,
                parameters=parameters,
                composition=tree,
                outputs=[o.name for o in score.outputs],
                family=score.body.operation.family
                if isinstance(score.body.operation, effects.Effect)
                else 'composition',
                rate=str(Fraction(rate.numerator, rate.denominator)),
                light_count=len(stream.layout.lights),
            )
        elif not item.diagnostics:
            item.diagnostics.append(f'Score is {entry.state.value}')
        animations.append(item)
    return animations


def _source_kind(entry: Entry) -> str:
    if entry.state != State.ready:
        return 'Unavailable source'
    if entry.address.endswith('.py'):
        return 'Python score (read-only)'
    if isinstance(entry.score, PresetScore):
        return 'Preset (read-only)'
    return 'Editable TOML'


def _composition_tree(
    library: Library, composition: Composition, output: str
) -> dict[str, object]:
    def node(path: str, output_name: str) -> dict[str, object]:
        part = composition.parts[path]
        score = composition.scores[part.score].score
        if not isinstance(score, AnimationScore):
            raise ValueError(f'{path}: score is not an animation')
        operation = score.body.operation
        entry = library.entries[part.score]
        children = []
        for source in light_animation.sources(operation):
            child = part.children[source.name]
            children.append(
                {
                    'source': source.name,
                    'output': source.output,
                    'node': node(child, source.output),
                }
            )
        stream = score.outputs[0].stream
        assert isinstance(stream, LightType)
        return {
            'path': path,
            'output': output_name,
            'effect': operation.effect,
            'fields': operation.model_dump(mode='json'),
            'editor_fields': _operation_fields(operation),
            'color_fields': authoring_colors.color_fields(score),
            'timeline': _operation_timeline(operation),
            'entry': entry.key,
            'editable': _source_kind(entry) == 'Editable TOML',
            'source_kind': _source_kind(entry),
            'templates': _operation_templates(score),
            'children': children,
            'parts': [
                p.model_dump(mode='json', exclude_none=True) for p in score.body.parts
            ],
            'dependencies': entry.dependencies,
            'used_by': sorted(
                e.key
                for e in library.entries.values()
                if entry.key in e.dependencies.values()
            ),
            'lights': [p.name for p in stream.layout.lights],
        }

    return node('root', output)


def _operation_timeline(operation: Model) -> dict[str, object] | None:
    if isinstance(operation, light_animation.Cues):
        end = max(cue.start + cue.duration for cue in operation.cues)
        return {
            'effect': operation.effect,
            'duration': _rational_text(end),
            'events': [
                {
                    'name': cue.source.name,
                    'output': cue.source.output,
                    'start': _rational_text(cue.start),
                    'duration': _rational_text(cue.duration),
                    'end': _rational_text(cue.start + cue.duration),
                }
                for cue in operation.cues
            ],
        }
    if isinstance(operation, light_animation.Crossfade):
        duration = _rational_text(operation.fade.duration)
        return {
            'effect': operation.effect,
            'duration': duration,
            'events': [
                {
                    'name': operation.outgoing.name,
                    'output': operation.outgoing.output,
                    'start': '0',
                    'duration': duration,
                    'end': duration,
                },
                {
                    'name': operation.incoming.name,
                    'output': operation.incoming.output,
                    'start': '0',
                    'duration': duration,
                    'end': duration,
                },
            ],
        }
    return None


def _rational_text(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else str(value)


def _rational_value(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f'{name} must be a rational number')
    try:
        return _rational_text(Fraction(value))
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f'{name} must be a rational number') from error


def _operation_fields(operation: Model) -> dict[str, str | int | float | bool]:
    return {
        name: value
        for name, value in operation.model_dump(mode='json').items()
        if name != 'effect' and isinstance(value, (str, int, float, bool))
    }


def _operation_templates(score: AnimationScore) -> list[str]:
    stream = score.outputs[0].stream
    assert isinstance(stream, LightType)
    templates = ['fill']
    if stream.components == ['red', 'green', 'blue']:
        templates.extend(['aurora', 'color_fill', 'color_chase'])
    return templates


def _operation_template(template: str, score: AnimationScore) -> Model:
    stream = score.outputs[0].stream
    assert isinstance(stream, LightType)
    if template == 'fill':
        return light_animation.Fill(values=[0.0] * len(stream.components))
    if stream.components != ['red', 'green', 'blue']:
        raise ValueError(f'{template!r} requires red, green, blue components')
    effect_types = {
        'aurora': effects.Aurora,
        'color_fill': effects.ColorFill,
        'color_chase': effects.ColorChase,
    }
    effect_type = effect_types.get(template)
    if effect_type is None:
        raise ValueError(f'unknown operation template {template!r}')
    return effect_type()


def _validation_library(
    library: Library, entry_key: str, edited: AnimationScore
) -> Library:
    entries = [
        entry.model_copy(
            update={
                'score': edited if entry.key == entry_key else entry.score,
                'state': State.pending,
                'dependencies': {},
                'resolved': None,
                'content_origin': None,
            }
        )
        for entry in library.entries.values()
    ]
    return Library(entries)


def _builtin_animations() -> list[AuthorAnimation]:
    controls = {
        'audio-scan': [
            AuthorParameter('width', 0.02, 0.5, 0.12, 'ratio'),
            AuthorParameter('speed', 0, 2, 0.4, 'ratio'),
            AuthorParameter('sensitivity', 0, 4, 1.5, 'ratio'),
        ],
        'audio-spectrum': [
            AuthorParameter('gain', 0, 4, 1.5, 'ratio'),
            AuthorParameter('smoothing', 0, 30, 10, 'ratio'),
        ],
        'bass-pulse': [
            AuthorParameter('speed', 0.05, 2, 0.55, 'ratio'),
            AuthorParameter('decay', 0.1, 12, 3.5, 'ratio'),
        ],
        'audio-spotlights': [
            AuthorParameter('density', 0, 15, 4, 'ratio'),
            AuthorParameter('width', 0.01, 0.3, 0.08, 'ratio'),
            AuthorParameter('decay', 0.1, 10, 2.4, 'ratio'),
        ],
        'audio-waterfall': [AuthorParameter('speed', 0, 3, 0.7, 'ratio')],
        'audio-flame': [
            AuthorParameter('cooling', 0.1, 5, 1.2, 'ratio'),
            AuthorParameter('sparks', 0, 10, 2.5, 'ratio'),
        ],
        'beat-strobe': [AuthorParameter('decay', 0.1, 20, 8, 'ratio')],
    }
    return [
        AuthorAnimation(
            selector=f'builtin:{name}',
            title=name.replace('-', ' ').title(),
            parameters=parameters,
            renderer='builtin',
            rate='30',
            light_count=128,
        )
        for name, parameters in controls.items()
    ]


def _builtin_preview(
    name: str, parameters: dict[str, float], duration: float
) -> dict[str, object]:
    renderer = reactive_effects.EFFECTS.get(name)
    if renderer is None:
        raise ValueError(f'unknown built-in animation {name!r}')
    source = cast(
        animation.Animation[reactive_effects.AudioState],
        renderer.model_validate(parameters),
    )
    device = animation.Device(led_count=128)
    state = source.initial_state(device)
    state.fps = 30
    frame_count = preview_frame_count(state.fps, duration, device.led_count * 3)
    frames = []
    for index in range(frame_count):
        reactive_effects.update_features(state, _demo_features(index, frame_count))
        frame = animation.byte_light_frame_from_float(source.render(device, state))
        frames.append(b64encode(memoryview(frame).cast('B')).decode('ascii'))
    return {
        'coords': [[index, 0] for index in range(device.led_count)],
        'fps': state.fps,
        'frames': frames,
    }


def _demo_features(index: int, frame_count: int) -> reactivity.AudioFeatures:
    phase = index / max(1, frame_count - 1)
    level = 0.25 + 0.5 * (0.5 + 0.5 * math.sin(phase * math.tau * 3))
    onset = max(0, math.sin(phase * math.tau * 6)) ** 4
    return reactivity.AudioFeatures(
        level=level,
        bass=0.2 + onset * 0.8,
        mid=0.25 + 0.5 * (0.5 + 0.5 * math.sin(phase * math.tau * 2)),
        treble=0.3 + 0.4 * (0.5 + 0.5 * math.sin(phase * math.tau * 5)),
        onset=onset,
        beat=1 if onset > 0.9 else 0,
        spectrum=[
            max(0, math.sin(phase * math.tau * (band + 1) + band)) for band in range(16)
        ],
    )
