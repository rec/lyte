from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import TypeAdapter
from ufor import effects, light_animation
from ufor.interface import LightBinding, Output
from ufor.library import Diagnostic, Entry, Library
from ufor.lights import LightType, strip
from ufor.time import Rate, Timebase

from lyte import animation, rendering, show
from lyte.animate import build


def score(
    name: str,
    operation: object,
    count: int = 3,
    components: list[str] | None = None,
) -> light_animation.AnimationScore:
    return light_animation.AnimationScore(
        name=name,
        title=name.title(),
        timebases=[Timebase(name='frames', rate=Rate(numerator=20))],
        outputs=[
            Output(
                name='light',
                stream=LightType(
                    timebase='frames',
                    components=components or ['red', 'green', 'blue'],
                    layout=strip(count),
                ),
                binding=LightBinding(),
            )
        ],
        body=light_animation.Animation(operation=operation),
    )


def library_for(value: light_animation.AnimationScore) -> Library:
    return Library(
        [
            Entry(
                library='test',
                address=f'/{value.name}.toml',
                name=value.name,
                score=value,
            )
        ]
    )


def test_example_library_prepares_and_renders() -> None:
    prepared = show.prepare_animation(
        show.LightProgramSpec(selector='examples:/composition.toml'),
        Path('examples/library.toml'),
    )

    assert prepared.output.layout.name == 'installation'
    assert prepared.fps == 20
    assert prepared.render().shape == (250, 3)


def test_missing_and_ambiguous_selections_fail_during_preparation() -> None:
    first = score('first', light_animation.Fill(values=[0.0, 0.0, 0.0]))
    second = score('second', light_animation.Fill(values=[0.0, 0.0, 0.0]))
    library = Library(
        [
            Entry(library='a', address='/first.toml', name='same', score=first),
            Entry(library='b', address='/second.toml', name='same', score=second),
        ]
    )

    with pytest.raises(ValueError, match='no score matches'):
        show.prepare_library_animation(
            library, show.LightProgramSpec(selector='missing')
        )
    with pytest.raises(ValueError, match='ambiguous selector'):
        show.prepare_library_animation(library, show.LightProgramSpec(selector='same'))


def test_library_diagnostics_include_fields_and_cycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = []
    monkeypatch.setattr(show.LOGGER, 'warning', messages.append)
    library = Library(
        [],
        [
            Diagnostic(
                library='shows',
                address='/broken.toml',
                code='cycle',
                message='circular reference',
                field='body.parts[0]',
                cycle=['shows:/a.toml', 'shows:/b.toml'],
            )
        ],
    )

    show.log_diagnostics(library)

    assert messages == [
        '[cycle] shows:/broken.toml: circular reference '
        '(field=body.parts[0], cycle=shows:/a.toml -> shows:/b.toml)'
    ]


def test_every_ufor_effect_has_an_installed_renderer() -> None:
    assert len(build.EFFECT_RENDERERS) == 41
    for tag in build.EFFECT_RENDERERS:
        description = TypeAdapter(effects.EffectValue).validate_python({'effect': tag})
        renderer = build.build_effect(description)
        assert isinstance(renderer, animation.Animation)
        assert isinstance(renderer, type(description))
        assert (
            type(renderer).model_fields.keys() == type(description).model_fields.keys()
        )


def test_missing_effect_renderer_is_a_capability_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderers = dict(build.EFFECT_RENDERERS)
    renderers.pop('aurora')
    monkeypatch.setattr(build, 'EFFECT_RENDERERS', renderers)

    with pytest.raises(build.RendererCapabilityError, match='aurora'):
        build.build_effect(effects.Aurora())


def test_non_light_output_is_rejected_before_rendering() -> None:
    value = score(
        'white',
        light_animation.Fill(values=[0.5]),
        components=['white'],
    )
    prepared = show.prepare_library_animation(
        library_for(value), show.LightProgramSpec(selector='white')
    )

    assert prepared.render().tolist() == [[0.5], [0.5], [0.5]]


def test_log_gradient_one_light_is_finite() -> None:
    value = score('log', effects.LogGradient(), count=1)
    prepared = show.prepare_library_animation(
        library_for(value), show.LightProgramSpec(selector='log')
    )

    frame = prepared.render()

    assert np.isfinite(frame).all()
    assert frame.tolist() == [[1.0, 1.0, 1.0]]


def test_python_score_requires_explicit_lyte_contract() -> None:
    value = score('plain', light_animation.Fill(values=[0.0, 0.0, 0.0]))
    entry = Entry(
        library='test',
        address='/plain.py',
        name='plain',
        score=value,
        python_class=light_animation.AnimationScore,
    )
    library = Library([entry])

    with pytest.raises(rendering.RendererCapabilityError, match='PythonAnimationScore'):
        show.prepare_library_animation(library, show.LightProgramSpec(selector='plain'))
