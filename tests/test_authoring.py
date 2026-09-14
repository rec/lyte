from __future__ import annotations

from pathlib import Path

import pytest
from ufor import codec, library_files
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
    assert 'Lyte Author' in document
    assert 'id="previous"' in document
    assert 'id="frame"' in document
    assert 'projectedPoints' in document
    assert 'preview.coords' in document
    assert 'id="preset-name"' in document
    assert '/api/preset' in document


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
