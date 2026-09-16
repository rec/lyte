from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest
from ufor import codec, effects, library_files, light_animation
from ufor.interface import OutputSelection
from ufor.preset import PresetScore

from lyte import authoring


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

    assert 'aurora' in selectors
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

    document = session.preset_document('aurora', {}, 'preset-aurora')

    preset = codec.parse_score(document)
    assert isinstance(preset, PresetScore)
    assert preset.name == 'preset-aurora'
    assert preset.score.selector == 'aurora'


def test_authoring_session_rejects_reactive_preset() -> None:
    library = library_files.read_library(Path('examples/library.toml'))
    session = authoring.AuthoringSession(library, authoring.AuthorConfig())

    with pytest.raises(ValueError, match='cannot be saved'):
        session.preset_document('builtin:audio-scan', {}, 'preset-audio-scan')


def test_authoring_session_exposes_composition_operations_and_sources() -> None:
    library = library_files.read_library(Path('examples/library.toml'))
    session = authoring.AuthoringSession(library, authoring.AuthorConfig())

    selected = next(
        item for item in session.animations if item.selector == 'composition'
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
        item for item in session.animations if item.selector == 'composition'
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
    assert session.preview('composition', {})['frames']
    assert session.documents['example:/composition.toml'] == combined
    selected = next(a for a in session.animations if a.selector == 'composition')
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

    assert not [item for item in session.animations if item.renderer == 'ufor']


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
    assert session.preview('aurora', {})['frames']
