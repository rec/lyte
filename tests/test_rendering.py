from __future__ import annotations

from fractions import Fraction

import numpy as np
from numpy import testing
from ufor import light_animation
from ufor.control import Scope
from ufor.interface import (
    LightBinding,
    Output,
    OutputSelection,
    ParameterExport,
    Part,
    ScoreVersion,
)
from ufor.library import Entry, Library
from ufor.lights import LightType, Wiring, matrix, serpentine, strip
from ufor.modulation import Modulation, Parameter, Target, Unit
from ufor.preset import PresetScore
from ufor.time import Rate, Timebase

from lyte import animation, rendering, show


class CounterState(animation.State):
    pass


class CounterScore(rendering.PythonAnimationScore):
    name: str = 'counter'
    title: str = 'Counter'
    timebases: list[Timebase] = [Timebase(name='frames', rate=Rate(numerator=2))]
    outputs: list[Output] = [
        Output(
            name='light',
            stream=LightType(
                timebase='frames',
                components=['red', 'green', 'blue'],
                layout=strip(1),
            ),
            binding=LightBinding(),
        )
    ]
    body: light_animation.Animation = light_animation.Animation(
        operation=light_animation.Fill(values=[0.0, 0.0, 0.0])
    )

    def initial_lyte_state(self, output: LightType) -> animation.State:
        return CounterState()

    def render_lyte_frame(
        self,
        output: LightType,
        state: animation.State,
        tick: int,
        parameters: dict[str, float],
    ) -> np.ndarray:
        state.frame += 1
        return animation.solid_float_light_frame(
            len(output.layout.lights), (state.frame / 100, 0.0, 0.0)
        )


def light_type(components: list[str], count: int = 2) -> LightType:
    return LightType(timebase='frames', components=components, layout=strip(count))


def frame(values: list[list[float]]) -> np.ndarray:
    return np.ascontiguousarray(values, dtype=np.float32)


def test_generic_fill_supports_one_through_five_components() -> None:
    for count in range(1, 6):
        values = [i / 10 for i in range(count)]
        output = light_type([f'component_{i}' for i in range(count)])

        actual = rendering.compose_frame(
            light_animation.Fill(values=values), output, {}
        )

        testing.assert_allclose(actual, [values, values])
        assert actual.dtype == np.float32
        assert actual.flags.c_contiguous


def test_numpy_composition_matches_ufor_operation_semantics() -> None:
    child = OutputSelection(name='child', output='light')
    output = light_type(['warm', 'cool'])
    source = frame([[0.75, 0.25], [0.25, 0.75]])

    mixed = rendering.compose_frame(
        light_animation.Mix(
            sources=[light_animation.WeightedSource(source=child, weight=2)]
        ),
        output,
        {child: source},
    )
    gained = rendering.compose_frame(
        light_animation.Gain(source=child, amount=2),
        output,
        {child: source},
    )
    reversed_frame = rendering.compose_frame(
        light_animation.Reverse(source=child), output, {child: source}
    )

    testing.assert_array_equal(mixed, [[1.0, 0.5], [0.5, 1.0]])
    testing.assert_array_equal(gained, [[1.5, 0.5], [0.5, 1.5]])
    testing.assert_array_equal(reversed_frame, source[::-1])


def test_crossfade_and_component_map_preserve_unclipped_values() -> None:
    left = OutputSelection(name='left', output='light')
    right = OutputSelection(name='right', output='light')
    mono = light_type(['white'])
    crossfade = light_animation.Crossfade(
        outgoing=left,
        incoming=right,
        fade=light_animation.Fade(duration=Fraction(1), easing='smooth'),
    )

    actual = rendering.compose_frame(
        crossfade,
        mono,
        {left: frame([[2.0], [2.0]]), right: frame([[4.0], [4.0]])},
        Fraction(1, 4),
    )
    mapped = rendering.compose_frame(
        light_animation.ComponentMap(
            source=left,
            matrix=[[1.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        ),
        light_type(['red', 'white']),
        {left: frame([[1.5, 0.5, 0.25], [2.0, 0.0, 0.0]])},
    )

    testing.assert_allclose(actual, [[2.3125], [2.3125]])
    testing.assert_array_equal(mapped, [[1.5, 0.0], [2.0, 0.0]])


def test_repeated_source_is_rendered_once_per_tick() -> None:
    child = CounterScore()
    root = animation_score(
        'root',
        light_animation.Mix(
            sources=[
                light_animation.WeightedSource(
                    source=OutputSelection(name='counter', output='light'),
                    weight=0.5,
                ),
                light_animation.WeightedSource(
                    source=OutputSelection(name='counter', output='light'),
                    weight=0.5,
                ),
            ]
        ),
        [Part(name='counter', score=ScoreVersion(path='counter.py'))],
    )
    library = Library(
        [
            Entry(
                library='test',
                address='/counter.py',
                name='counter',
                score=child,
                python_class=CounterScore,
            ),
            Entry(library='test', address='/root.toml', name='root', score=root),
        ]
    )
    prepared = show.prepare_library_animation(
        library, show.LightProgramSpec(selector='root')
    )

    testing.assert_allclose(prepared.render(), [[0.01, 0.0, 0.0]])
    assert prepared.states['root/counter'].frame == 1


def test_separate_parts_have_independent_state() -> None:
    child = CounterScore()
    selections = [
        OutputSelection(name=name, output='light') for name in ('left', 'right')
    ]
    root = animation_score(
        'root',
        light_animation.Mix(
            sources=[
                light_animation.WeightedSource(source=selection, weight=0.5)
                for selection in selections
            ]
        ),
        [
            Part(name=name, score=ScoreVersion(path='counter.py'))
            for name in ('left', 'right')
        ],
    )
    library = Library(
        [
            Entry(
                library='test',
                address='/counter.py',
                name='counter',
                score=child,
                python_class=CounterScore,
            ),
            Entry(library='test', address='/root.toml', name='root', score=root),
        ]
    )
    prepared = show.prepare_library_animation(
        library, show.LightProgramSpec(selector='root')
    )

    prepared.render()

    assert prepared.states['root/left'] is not prepared.states['root/right']
    assert prepared.states['root/left'].frame == 1
    assert prepared.states['root/right'].frame == 1


def test_delayed_cue_starts_child_at_local_tick_zero() -> None:
    child = CounterScore()
    selection = OutputSelection(name='counter', output='light')
    root = animation_score(
        'root',
        light_animation.Cues(
            cues=[
                light_animation.Cue(
                    source=selection, start=Fraction(1), duration=Fraction(1)
                )
            ]
        ),
        [Part(name='counter', score=ScoreVersion(path='counter.py'))],
    )
    library = Library(
        [
            Entry(
                library='test',
                address='/counter.py',
                name='counter',
                score=child,
                python_class=CounterScore,
            ),
            Entry(library='test', address='/root.toml', name='root', score=root),
        ]
    )
    prepared = show.prepare_library_animation(
        library, show.LightProgramSpec(selector='root')
    )

    frames = [prepared.render()[0, 0] for _ in range(4)]

    testing.assert_allclose(frames, [0.0, 0.0, 0.01, 0.02])


def test_preset_defaults_caller_overrides_and_live_gain_preserve_state() -> None:
    child = CounterScore()
    selection = OutputSelection(name='counter', output='light')
    root = animation_score(
        'brightness',
        light_animation.Gain(source=selection, amount=1.0),
        [Part(name='counter', score=ScoreVersion(path='counter.py'))],
    ).model_copy(
        update={
            'parameters': [
                ParameterExport(
                    name='brightness',
                    binding=Target(name='animation', parameter='amount'),
                )
            ],
            'body': light_animation.Animation(
                operation=light_animation.Gain(source=selection, amount=1.0),
                parts=[Part(name='counter', score=ScoreVersion(path='counter.py'))],
                modulation=Modulation(
                    parameters=[
                        Parameter(
                            target=Target(name='animation', parameter='amount'),
                            unit=Unit.ratio,
                            scope=Scope.part,
                            minimum=0.0,
                            maximum=2.0,
                            default=1.0,
                        )
                    ]
                ),
            ),
        }
    )
    preset = PresetScore(
        name='dim',
        title='Dim',
        score=ScoreVersion(path='brightness.toml'),
        parameters={'brightness': 0.25},
    )
    library = Library(
        [
            Entry(
                library='test',
                address='/counter.py',
                name='counter',
                score=child,
                python_class=CounterScore,
            ),
            Entry(
                library='test',
                address='/brightness.toml',
                name='brightness',
                score=root,
            ),
            Entry(library='test', address='/dim.toml', name='dim', score=preset),
        ]
    )
    prepared = show.prepare_library_animation(
        library, show.LightProgramSpec(selector='dim')
    )
    overridden = show.prepare_library_animation(
        library,
        show.LightProgramSpec(selector='dim', parameters={'brightness': 0.75}),
    )

    testing.assert_allclose(prepared.render()[0, 0], 0.0025)
    testing.assert_allclose(overridden.render()[0, 0], 0.0075)
    prepared.set_parameters({'brightness': 0.5})
    testing.assert_allclose(prepared.render()[0, 0], 0.01)
    assert prepared.states['root/counter'].frame == 2


def test_serpentine_wiring_is_applied_only_to_physical_frame() -> None:
    layout = matrix(3, 2)
    value = light_animation.AnimationScore(
        name='gradient',
        title='Gradient',
        timebases=[Timebase(name='frames', rate=Rate(numerator=20))],
        outputs=[
            Output(
                name='light',
                stream=LightType(
                    timebase='frames',
                    components=['red', 'green', 'blue'],
                    layout=layout,
                ),
                binding=LightBinding(),
            )
        ],
        body=light_animation.Animation(
            operation={
                'effect': 'linear_gradient',
                'start': 0.0,
                'end': 1.0,
            }
        ),
    )
    library = Library(
        [Entry(library='test', address='/gradient.toml', name='gradient', score=value)]
    )
    logical_renderer = rendering.PreparedAnimation(
        library,
        library.composition('gradient'),
        'light',
    )
    physical_renderer = rendering.PreparedAnimation(
        library,
        library.composition('gradient'),
        'light',
        Wiring(order=serpentine(3, 2).order),
    )

    logical = logical_renderer.render()
    physical = physical_renderer.byte_frame(wired=True)

    expected = animation.byte_light_frame_from_float(logical)
    testing.assert_array_equal(physical[:, 0], expected[[0, 1, 2, 5, 4, 3], 0])


def animation_score(
    name: str, operation: object, parts: list[Part]
) -> light_animation.AnimationScore:
    return light_animation.AnimationScore(
        name=name,
        title=name.title(),
        timebases=[Timebase(name='frames', rate=Rate(numerator=2))],
        outputs=[
            Output(
                name='light',
                stream=LightType(
                    timebase='frames',
                    components=['red', 'green', 'blue'],
                    layout=strip(1),
                ),
                binding=LightBinding(),
            )
        ],
        body=light_animation.Animation(operation=operation, parts=parts),
    )
