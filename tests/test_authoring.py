from __future__ import annotations

from base64 import b64decode
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from shutil import copytree
from zipfile import ZipFile

import numpy as np
import pytest
from numpy.typing import NDArray
from ufor import codec, effects, library_files, light_animation
from ufor.interface import OutputSelection
from ufor.preset import PresetScore

from lyte import authoring
from lyte.rendering import PreparedAnimation


def test_authoring_session_lists_and_previews_animation_scores() -> None:
    library = library_files.read_library(Path('examples/library.toml'))
    session = authoring.AuthoringSession(
        library,
        authoring.AuthorConfig(
            library_config=Path('examples/library.toml'), duration=0.1
        ),
    )

    selectors = [animation.selector for animation in session.animations]
    preview = session.preview(selectors[0], {})

    assert 'examples:/aurora.toml' in selectors
    assert preview['fps'] == 20
    assert len(preview['frames']) == 2


def test_author_document_contains_animation_catalogue() -> None:
    document = authoring.author_document(
        [
            authoring.AuthorAnimation(
                selector='examples:/aurora.toml',
                title='Aurora',
                parameters=[authoring.AuthorParameter('speed', 0, 2, 1, 'ratio')],
            )
        ]
    )

    assert 'examples:/aurora.toml' in document
    assert 'lyte Author' in document
    assert 'id="previous"' in document
    assert 'id="frame"' in document
    assert 'projectedPoints' in document
    assert 'preview.coords' in document
    assert 'id="preset-name"' in document
    assert '/api/preset' in document
    assert 'id="composition"' in document
    assert 'id="inspector"' in document
    assert 'compositionNode' in document
    assert 'id="operation-template"' in document
    assert '/api/operation' in document
    assert 'id="timeline"' in document
    assert 'rebuildTimeline' in document
    assert 'id="operation-fields"' in document
    assert '/api/fields' in document


def test_score_title_cannot_close_the_authoring_script() -> None:
    document = authoring.author_document(
        [
            authoring.AuthorAnimation(
                selector='example',
                title='</script><script>alert(1)</script>',
                parameters=[],
            )
        ]
    )

    assert document.count('</script>') == 1


def test_authoring_session_previews_built_in_reactive_effects() -> None:
    library = library_files.read_library(Path('examples/library.toml'))
    session = authoring.AuthoringSession(
        library,
        authoring.AuthorConfig(
            library_config=Path('examples/library.toml'), duration=0.1
        ),
    )

    preview = session.preview('builtin:audio-scan', {'speed': 1})

    assert preview['fps'] == 30
    assert len(preview['frames']) == 3


def test_authoring_session_downloads_validated_ufor_preset() -> None:
    library = library_files.read_library(Path('examples/library.toml'))
    session = authoring.AuthoringSession(
        library,
        authoring.AuthorConfig(
            library_config=Path('examples/library.toml'), duration=0.1
        ),
    )

    document = session.preset_document('examples:/aurora.toml', {}, 'preset-aurora')

    preset = codec.parse_score(document)
    assert isinstance(preset, PresetScore)
    assert preset.name == 'preset-aurora'
    assert preset.score.selector == 'examples:/aurora.toml'


def test_authoring_session_rejects_reactive_preset() -> None:
    library = library_files.read_library(Path('examples/library.toml'))
    session = authoring.AuthoringSession(library, authoring.AuthorConfig())

    with pytest.raises(ValueError, match='cannot be saved'):
        session.preset_document('builtin:audio-scan', {}, 'preset-audio-scan')


def test_authoring_session_exposes_composition_operations_and_sources() -> None:
    library = library_files.read_library(Path('examples/library.toml'))
    session = authoring.AuthoringSession(library, authoring.AuthorConfig())

    selected = next(
        item
        for item in session.animations
        if item.selector == 'examples:/composition.toml'
    )

    assert selected.composition is not None
    assert selected.composition['effect'] == 'cues'
    assert [child['source'] for child in selected.composition['children']] == [
        'limbs',
        'aurora',
    ]
    assert selected.composition['timeline'] == {
        'effect': 'cues',
        'duration': '10',
        'events': [
            {
                'name': 'limbs',
                'output': 'light',
                'start': '0',
                'duration': '6',
                'end': '6',
            },
            {
                'name': 'aurora',
                'output': 'light',
                'start': '4',
                'duration': '6',
                'end': '10',
            },
        ],
    }


def test_authoring_session_exposes_exact_crossfade_timeline(tmp_path: Path) -> None:
    scores = tmp_path / 'scores'
    scores.mkdir()
    for source in Path('examples/scores').glob('*.toml'):
        (scores / source.name).write_text(source.read_text())
    composition = codec.parse_score(
        Path('examples/scores/composition.toml').read_text()
    )
    assert isinstance(composition, light_animation.AnimationScore)
    operation = light_animation.Crossfade(
        outgoing=OutputSelection(name='limbs', output='light'),
        incoming=OutputSelection(name='aurora', output='light'),
        fade=light_animation.Fade(duration='3/2'),
    )
    edited = composition.model_copy(
        update={'body': composition.body.model_copy(update={'operation': operation})}
    )
    (scores / 'composition.toml').write_text(codec.score_toml(edited))
    config = tmp_path / 'library.toml'
    config.write_text('[[libraries]]\nname = "example"\nroot = "scores"\n')

    session = authoring.AuthoringSession(
        library_files.read_library(config),
        authoring.AuthorConfig(library_config=config),
    )
    selected = next(
        item
        for item in session.animations
        if item.selector == 'example:/composition.toml'
    )

    assert selected.composition is not None
    assert selected.composition['timeline'] == {
        'effect': 'crossfade',
        'duration': '3/2',
        'events': [
            {
                'name': 'limbs',
                'output': 'light',
                'start': '0',
                'duration': '3/2',
                'end': '3/2',
            },
            {
                'name': 'aurora',
                'output': 'light',
                'start': '0',
                'duration': '3/2',
                'end': '3/2',
            },
        ],
    }
    document = session.timeline_document(
        'example:/composition.toml', 'light', {'duration': '5/4'}
    )
    edited = codec.parse_score(document)

    assert isinstance(edited, light_animation.AnimationScore)
    assert isinstance(edited.body.operation, light_animation.Crossfade)
    assert edited.body.operation.fade.duration == Fraction(5, 4)


def test_authoring_session_accumulates_edits_without_mutating_source_files(
    tmp_path: Path,
) -> None:
    scores = tmp_path / 'scores'
    scores.mkdir()
    for source in Path('examples/scores').glob('*.toml'):
        (scores / source.name).write_text(source.read_text())
    composition = scores / 'composition.toml'
    composition.write_text(
        '# preserved comment\n'
        + composition.read_text().replace(
            '[[body.operation.cues]]',
            '# preserved timing comment\n[[body.operation.cues]]',
        )
    )
    config = tmp_path / 'library.toml'
    config.write_text('[[libraries]]\nname = "example"\nroot = "scores"\n')
    session = authoring.AuthoringSession(
        library_files.read_library(config),
        authoring.AuthorConfig(library_config=config),
    )
    original = composition.read_text()

    document = session.timeline_document(
        'example:/composition.toml',
        'light',
        {
            'events': [
                {'start': '0', 'duration': '9/2'},
                {'start': '4', 'duration': '5'},
            ]
        },
    )
    edited = codec.parse_score(document)

    assert '# preserved comment' in document
    assert '# preserved timing comment' in document
    assert isinstance(edited, light_animation.AnimationScore)
    assert isinstance(edited.body.operation, light_animation.Cues)
    assert [(cue.start, cue.duration) for cue in edited.body.operation.cues] == [
        (Fraction(0), Fraction(9, 2)),
        (Fraction(4), Fraction(5)),
    ]
    combined = session.field_document(
        'example:/composition.toml', 'light', {'easing': 'smooth'}
    )
    combined_score = codec.parse_score(combined)
    assert isinstance(combined_score, light_animation.AnimationScore)
    assert isinstance(combined_score.body.operation, light_animation.Cues)
    assert combined_score.body.operation.easing == 'smooth'
    assert combined_score.body.operation.cues[0].duration == Fraction(9, 2)
    assert '# preserved timing comment' in combined
    assert composition.read_text() == original
    with pytest.raises(ValueError, match='cues require increasing starts and ends'):
        session.timeline_document(
            'example:/composition.toml',
            'light',
            {
                'events': [
                    {'start': '0', 'duration': '6'},
                    {'start': '4', 'duration': '1'},
                ]
            },
        )
    assert session.preview('example:/composition.toml', {})['frames']
    assert session.documents['example:/composition.toml'] == combined
    selected = next(
        a for a in session.animations if a.selector == 'example:/composition.toml'
    )
    assert selected.composition['fields']['easing'] == 'smooth'


def test_authoring_session_rejects_unknown_score_fields(tmp_path: Path) -> None:
    scores = tmp_path / 'scores'
    scores.mkdir()
    source = 'unknown = true\n' + Path('examples/scores/aurora.toml').read_text()
    (scores / 'aurora.toml').write_text(source)
    config = tmp_path / 'library.toml'
    config.write_text('[[libraries]]\nname = "example"\nroot = "scores"\n')

    session = authoring.AuthoringSession(
        library_files.read_library(config),
        authoring.AuthorConfig(library_config=config),
    )

    selected = next(a for a in session.animations if a.source == 'example:/aurora.toml')
    assert selected.diagnostics
    assert selected.composition is None


def test_authoring_session_round_trips_comments_when_replacing_operation(
    tmp_path: Path,
) -> None:
    scores = tmp_path / 'scores'
    scores.mkdir()
    source = Path('examples/scores/aurora.toml').read_text()
    (scores / 'aurora.toml').write_text('# preserved comment\n' + source)
    config = tmp_path / 'library.toml'
    config.write_text('[[libraries]]\nname = "example"\nroot = "scores"\n')
    library = library_files.read_library(config)
    session = authoring.AuthoringSession(
        library, authoring.AuthorConfig(library_config=config)
    )

    document = session.operation_document('example:/aurora.toml', 'light', 'fill')

    edited = codec.parse_score(document)
    assert '# preserved comment' in document
    assert isinstance(edited, light_animation.AnimationScore)
    assert isinstance(edited.body.operation, light_animation.Fill)


def test_authoring_session_edits_operation_scalar_fields(tmp_path: Path) -> None:
    scores = tmp_path / 'scores'
    scores.mkdir()
    source = Path('examples/scores/aurora.toml').read_text()
    (scores / 'aurora.toml').write_text('# preserved comment\n' + source)
    config = tmp_path / 'library.toml'
    config.write_text('[[libraries]]\nname = "example"\nroot = "scores"\n')
    session = authoring.AuthoringSession(
        library_files.read_library(config),
        authoring.AuthorConfig(library_config=config),
    )

    document = session.field_document(
        'example:/aurora.toml',
        'light',
        {
            'band_count': 6,
            'softness': 0.2,
            'intensity': 0.6,
            'speed': 1.25,
            'seed': 8,
        },
    )
    edited = codec.parse_score(document)

    assert '# preserved comment' in document
    assert isinstance(edited, light_animation.AnimationScore)
    assert isinstance(edited.body.operation, effects.Aurora)
    assert edited.body.operation.speed == 1.25
    assert edited.body.operation.seed == 8
    with pytest.raises(ValueError, match='operation fields do not match'):
        session.field_document('example:/aurora.toml', 'light', {})
    assert session.preview('example:/aurora.toml', {})['frames']


@pytest.fixture
def editable_session(tmp_path: Path) -> authoring.AuthoringSession:
    scores = tmp_path / 'scores'
    scores.mkdir()
    for p in Path('examples/scores').glob('*.toml'):
        (scores / p.name).write_text('# retained comment\n' + p.read_text())
    config = tmp_path / 'library.toml'
    config.write_text('[[libraries]]\nname = "example"\nroot = "scores"\n')
    return authoring.AuthoringSession(
        library_files.read_library(config),
        authoring.AuthorConfig(library_config=config, duration=0.1),
    )


def test_history_restores_referenced_scores_and_clears_changed_markers(
    editable_session: authoring.AuthoringSession,
    tmp_path: Path,
) -> None:
    session = editable_session
    aurora = 'example:/aurora.toml'
    limbs = 'example:/limbs.toml'
    original = {p.name: p.read_text() for p in (tmp_path / 'scores').glob('*.toml')}
    before = session.preview('example:/composition.toml', {})
    first = session.operation_document(aurora, 'light', 'color_fill')
    after_first = session.preview('example:/composition.toml', {})
    second = session.operation_document(limbs, 'light', 'fill')
    after_second = session.preview('example:/composition.toml', {})
    assert session.history_state()['changed'] == [aurora, limbs]
    assert '# retained comment' in first and '# retained comment' in second

    session.undo()
    assert session.preview('example:/composition.toml', {}) == after_first
    assert session.history_state()['changed'] == [aurora]
    session.undo()
    assert session.preview('example:/composition.toml', {}) == before
    assert session.documents[aurora] == original['aurora.toml']
    assert session.documents[limbs] == original['limbs.toml']
    assert session.history_state() == {
        'can_undo': False,
        'can_redo': True,
        'changed': [],
        'revisions': {},
    }
    session.redo()
    assert session.documents[aurora] == first
    session.redo()
    assert session.documents[limbs] == second
    assert session.preview('example:/composition.toml', {}) == after_second
    assert not session.history_state()['can_redo']
    assert {
        p.name: p.read_text() for p in (tmp_path / 'scores').glob('*.toml')
    } == original


def test_rejected_edit_and_preview_leave_redo_available(
    editable_session: authoring.AuthoringSession,
) -> None:
    session = editable_session
    session.operation_document('example:/aurora.toml', 'light', 'color_fill')
    session.undo()
    with pytest.raises(ValueError):
        session.operation_document('example:/aurora.toml', 'light', 'missing')
    session.preview('example:/aurora.toml', {})
    session.preset_document('example:/aurora.toml', {}, 'copy')
    assert session.history_state()['can_redo']
    session.operation_document('example:/limbs.toml', 'light', 'fill')
    assert not session.history_state()['can_redo']
    with pytest.raises(ValueError, match='no edit to redo'):
        session.redo()


def test_bundle_preserves_root_and_part_edits_and_reloads(
    editable_session: authoring.AuthoringSession,
    tmp_path: Path,
) -> None:
    session = editable_session
    with pytest.raises(ValueError, match='no changed scores'):
        session.download_bundle()
    session.field_document('example:/composition.toml', 'light', {'easing': 'linear'})
    session.operation_document('example:/aurora.toml', 'light', 'color_fill')
    session.operation_document('example:/limbs.toml', 'light', 'fill')
    bundle = session.download_bundle()
    assert bundle['revisions'] == session.history_state()['revisions']
    copytree(tmp_path / 'scores', tmp_path / 'restored')
    assert isinstance(bundle['archive'], str)
    with ZipFile(BytesIO(b64decode(bundle['archive']))) as archive:
        assert set(archive.namelist()) == {
            'example/composition.toml',
            'example/aurora.toml',
            'example/limbs.toml',
        }
        for name in archive.namelist():
            data = archive.read(name)
            assert data.startswith(b'# retained comment')
            (tmp_path / 'restored' / Path(name).relative_to('example')).write_bytes(
                data
            )
    config = tmp_path / 'restored.toml'
    config.write_text('[[libraries]]\nname = "example"\nroot = "restored"\n')
    restored = authoring.AuthoringSession(
        library_files.read_library(config),
        authoring.AuthorConfig(library_config=config, duration=0.1),
    )
    assert restored.preview('example:/composition.toml', {}) == session.preview(
        'example:/composition.toml', {}
    )
    for key, document in session.changed_documents().items():
        assert document == (tmp_path / 'restored' / key.split('/')[-1]).read_text()
    session.undo()
    assert len(session.changed_documents()) == 2
    assert bundle['revisions'] != session.history_state()['revisions']


def test_bundle_separates_equal_filenames_in_different_libraries(
    tmp_path: Path,
) -> None:
    config = tmp_path / 'library.toml'
    registrations = []
    for name in ['first', 'second']:
        root = tmp_path / name
        root.mkdir()
        source = Path('examples/scores/aurora.toml').read_text()
        (root / 'aurora.toml').write_text(
            source.replace('name = "aurora"', f'name = "{name}"')
        )
        registrations.append(f'[[libraries]]\nname = "{name}"\nroot = "{name}"\n')
    config.write_text('\n'.join(registrations))
    session = authoring.AuthoringSession(
        library_files.read_library(config),
        authoring.AuthorConfig(library_config=config),
    )
    session.operation_document('first:/aurora.toml', 'light', 'fill')
    session.operation_document('second:/aurora.toml', 'light', 'color_fill')
    archive = session.download_bundle()['archive']
    assert isinstance(archive, str)
    with ZipFile(BytesIO(b64decode(archive))) as bundle:
        assert set(bundle.namelist()) == {'first/aurora.toml', 'second/aurora.toml'}
        assert bundle.read('first/aurora.toml') != bundle.read('second/aurora.toml')


def test_composition_draft_builds_sequences_and_mixes_without_writing_sources(
    editable_session: authoring.AuthoringSession,
    tmp_path: Path,
) -> None:
    session = editable_session
    entry = 'example:/composition.toml'
    original = session.source_document(entry)
    parts = [
        {'name': 'a', 'score': {'selector': 'example:/aurora.toml'}},
        {'name': 'b', 'score': {'selector': 'example:/aurora.toml'}},
    ]
    cues = {
        'effect': 'cues',
        'cues': [
            {
                'source': {'name': 'a', 'output': 'light'},
                'start': '1/2',
                'duration': '2',
            },
            {'source': {'name': 'b', 'output': 'light'}, 'start': '2', 'duration': '3'},
        ],
    }
    structure = {'parts': parts, 'operation': cues}
    draft = session.structure_document(entry, 'light', structure, apply=False)
    assert not session.history_state()['can_undo']
    assert session.source_document(entry) == original
    assert '# retained comment' in draft
    applied = session.structure_document(entry, 'light', structure, apply=True)
    assert applied == draft
    assert session.preview('example:/composition.toml', {})['frames']
    parsed = codec.parse_score(applied)
    assert isinstance(parsed, light_animation.AnimationScore)
    assert isinstance(parsed.body.operation, light_animation.Cues)
    assert [c.start for c in parsed.body.operation.cues] == [
        Fraction(1, 2),
        Fraction(2),
    ]
    structure['operation'] = {
        'effect': 'mix',
        'sources': [
            {'source': {'name': 'a', 'output': 'light'}, 'weight': 0.25},
            {'source': {'name': 'b', 'output': 'light'}, 'weight': 0.75},
        ],
    }
    mixed = session.structure_document(entry, 'light', structure, apply=True)
    parsed = codec.parse_score(mixed)
    assert isinstance(parsed, light_animation.AnimationScore)
    assert isinstance(parsed.body.operation, light_animation.Mix)
    assert [s.weight for s in parsed.body.operation.sources] == [0.25, 0.75]
    session.undo()
    assert session.source_document(entry) == applied
    session.redo()
    assert session.source_document(entry) == mixed
    path = tmp_path / 'scores' / 'composition.toml'
    assert path.read_text() == original
    for document in [applied, mixed]:
        path.write_text(document)
        reloaded = authoring.AuthoringSession(
            library_files.read_library(session.config.library_config), session.config
        )
        assert reloaded.preview('example:/composition.toml', {})['frames']


@pytest.mark.parametrize('problem', ['cycle', 'missing-output', 'unknown-part'])
def test_invalid_composition_draft_leaves_history_and_working_copy_unchanged(
    editable_session: authoring.AuthoringSession,
    problem: str,
) -> None:
    session = editable_session
    entry = 'example:/composition.toml'
    before = session.source_document(entry)
    structure = {
        'parts': [
            {
                'name': 'a',
                'score': {
                    'selector': entry if problem == 'cycle' else 'example:/aurora.toml'
                },
            }
        ],
        'operation': {
            'effect': 'reverse',
            'source': {
                'name': 'missing' if problem == 'unknown-part' else 'a',
                'output': 'missing' if problem == 'missing-output' else 'light',
            },
        },
    }
    with pytest.raises(ValueError):
        session.structure_document(entry, 'light', structure, apply=True)
    assert session.source_document(entry) == before
    assert not session.history_state()['can_undo']


def test_browser_keeps_blocked_entries_and_their_dependency_diagnostics(
    editable_session: authoring.AuthoringSession,
    tmp_path: Path,
) -> None:
    path = tmp_path / 'scores' / 'composition.toml'
    path.write_text(path.read_text().replace('aurora.toml', 'missing.toml'))
    session = authoring.AuthoringSession(
        library_files.read_library(editable_session.config.library_config),
        editable_session.config,
    )
    item = next(
        a for a in session.animations if a.selector == 'example:/composition.toml'
    )
    assert item.composition is None
    assert any('missing.toml' in d for d in item.diagnostics)
    with pytest.raises(ValueError, match='missing.toml'):
        session.preview(item.selector, {})
    assert (
        next(
            a for a in session.animations if a.selector == 'example:/aurora.toml'
        ).light_count
        == 250
    )


def test_browser_distinguishes_duplicate_names_and_thumbnails_are_repeatable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / 'library.toml'
    registrations = []
    for name in ['first', 'second']:
        root = tmp_path / name
        root.mkdir()
        (root / 'aurora.toml').write_text(
            Path('examples/scores/aurora.toml').read_text()
        )
        registrations.append(f'[[libraries]]\nname = "{name}"\nroot = "{name}"\n')
    config.write_text('\n'.join(registrations))
    render = PreparedAnimation.render
    rendered = []

    def count_render(self: PreparedAnimation) -> NDArray[np.float32]:
        rendered.append(True)
        return render(self)

    monkeypatch.setattr(PreparedAnimation, 'render', count_render)
    session = authoring.AuthoringSession(
        library_files.read_library(config),
        authoring.AuthorConfig(library_config=config, duration=0.1),
    )
    assert not rendered
    items = [a for a in session.animations if a.renderer == 'ufor']
    assert {a.selector for a in items} == {'first:/aurora.toml', 'second:/aurora.toml'}
    assert items[0].title == items[1].title
    assert all(not a.diagnostics for a in items)
    thumbnail = session.thumbnail('first:/aurora.toml')
    assert thumbnail == session.thumbnail('first:/aurora.toml')
    assert len(rendered) == 2
    assert thumbnail['frame'] == session.preview('first:/aurora.toml', {})['frames'][0]


def test_palette_edits_preserve_comments_and_can_be_undone(
    editable_session: authoring.AuthoringSession,
    tmp_path: Path,
) -> None:
    session = editable_session
    key = 'example:/aurora.toml'
    source = tmp_path / 'scores' / 'aurora.toml'
    original = source.read_text().replace(
        'band_count =', '# keep this field comment\nband_count ='
    )
    source.write_text(original)
    palette = [[0, 255, 0], [255, 0, 0], [0, 0, 255]]
    document = session.color_document(key, 'light', {'palette': palette})
    score = codec.parse_score(document)
    assert isinstance(score, light_animation.AnimationScore)
    assert isinstance(score.body.operation, effects.Aurora)
    assert score.body.operation.palette == palette
    assert '# retained comment' in document
    assert '# keep this field comment' in document
    assert source.read_text() == original
    assert session.preview(key, {})['frames']
    with pytest.raises(ValueError):
        session.color_document(key, 'light', {'palette': []})
    assert session.source_document(key) == document
    session.undo()
    assert session.source_document(key) == original
    session.redo()
    assert session.source_document(key) == document


def test_normalized_fill_values_keep_their_units_and_precision(
    editable_session: authoring.AuthoringSession,
) -> None:
    session = editable_session
    key = 'example:/grid.toml'
    values = [0.123456789, 0.5, 1.25]
    document = session.color_document(key, 'light', {'values': values})
    score = codec.parse_score(document)
    assert isinstance(score, light_animation.AnimationScore)
    assert isinstance(score.body.operation, light_animation.Fill)
    assert score.body.operation.values == values
    selected = next(a for a in session.animations if a.selector == key)
    assert selected.composition['color_fields']['values']['scale'] == 1
    with pytest.raises(ValueError, match='finite'):
        session.color_document(key, 'light', {'values': [float('nan'), 0, 0]})
    assert session.source_document(key) == document


def test_byte_colour_rejects_fractional_channels(
    editable_session: authoring.AuthoringSession,
) -> None:
    session = editable_session
    key = 'example:/aurora.toml'
    session.operation_document(key, 'light', 'color_fill')
    before = session.source_document(key)
    with pytest.raises(ValueError):
        session.color_document(key, 'light', {'color': [0.5, 0, 0]})
    assert session.source_document(key) == before
    document = session.color_document(key, 'light', {'color': [128, 0, 255]})
    score = codec.parse_score(document)
    assert isinstance(score, light_animation.AnimationScore)
    assert isinstance(score.body.operation, effects.ColorFill)
    assert score.body.operation.color == [128, 0, 255]
