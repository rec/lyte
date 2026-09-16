"""uFor adapter for the preserved wearable patch catalogue."""

from pathlib import Path
from typing import cast

import mido
import numpy as np
from numpy.typing import NDArray
from pydantic import Field, SkipValidation
from ufor import light_animation
from ufor.control import Scope
from ufor.interface import LightBinding, Output, ParameterExport
from ufor.lights import Interpretation, Layout, Light, LightType
from ufor.modulation import Parameter, Target, Unit
from ufor.time import Rate, Timebase

from lyte import animation, midi, patch_config, patches, rendering

_LIBRARY = patch_config.load_patch_library(
    Path(__file__).parents[1] / 'wearable-breath.toml'
)
_LED_COUNT = cast(int, _LIBRARY.wearable.led_count)
_LAYOUT = Layout(
    name='wearable',
    axes=['x'],
    lights=[Light(name=f'light_{i}', position=[i]) for i in range(_LED_COUNT)],
    regions={
        name: [
            f'light_{i}'
            for physical_range in region.ranges
            for i in range(
                physical_range.start,
                physical_range.start + physical_range.led_count,
            )
        ]
        for name, region in _LIBRARY.wearable.physical_map.items()
    },
)


class _WearableState(animation.State):
    patch: SkipValidation[midi.LightPatch]
    parameters: dict[str, float] = Field(default_factory=dict)


def _parameter(name: str, minimum: float, maximum: float, default: float) -> Parameter:
    return Parameter(
        target=Target(name='renderer', parameter=name),
        unit=Unit.ratio,
        scope=Scope.part,
        minimum=minimum,
        maximum=maximum,
        default=default,
    )


class WearableScore(rendering.PythonAnimationScore):
    name: str = 'wearable'
    title: str = 'Wearable patch'
    tags: list[str] = []
    timebases: list[Timebase] = [Timebase(name='frames', rate=Rate(numerator=60))]
    outputs: list[Output] = [
        Output(
            name='light',
            stream=LightType(
                timebase='frames',
                components=['red', 'green', 'blue'],
                interpretation=Interpretation.drive,
                layout=_LAYOUT,
            ),
            binding=LightBinding(),
        )
    ]
    parameters: list[ParameterExport] = [
        ParameterExport(name='note', binding=Target(name='renderer', parameter='note')),
        ParameterExport(
            name='velocity', binding=Target(name='renderer', parameter='velocity')
        ),
        ParameterExport(
            name='breath', binding=Target(name='renderer', parameter='breath')
        ),
        ParameterExport(
            name='pitch_bend',
            binding=Target(name='renderer', parameter='pitch_bend'),
        ),
    ]
    body: light_animation.Animation = light_animation.Animation(
        operation=light_animation.Fill(values=[0.0, 0.0, 0.0]),
        renderer_parameters=[
            _parameter('note', 0.0, 127.0, 60.0),
            _parameter('velocity', 0.0, 127.0, 127.0),
            _parameter('breath', 0.0, 127.0, 0.0),
            _parameter('pitch_bend', -8192.0, 8191.0, 0.0),
        ],
    )

    def initial_lyte_state(self, output: LightType) -> animation.State:
        if self.name not in _LIBRARY.patches:
            raise ValueError(f'unknown wearable patch: {self.name}')
        return _WearableState(patch=patches.build_light_patch(_LIBRARY, self.name))

    def render_lyte_frame(
        self,
        output: LightType,
        state: animation.State,
        tick: int,
        parameters: dict[str, float],
    ) -> NDArray[np.float32]:
        if not isinstance(state, _WearableState):
            raise TypeError('wearable score requires _WearableState')
        _apply_parameters(state, parameters)
        state.patch.fps = state.fps
        logical = state.patch.render(animation.Device(led_count=_LED_COUNT))
        state.frame += 1
        return patches.map_logical_frame(_LIBRARY.wearable, logical)


def _apply_parameters(state: _WearableState, parameters: dict[str, float]) -> None:
    note = round(parameters['note'])
    velocity = round(parameters['velocity'])
    if (
        state.parameters.get('note') != note
        or state.parameters.get('velocity') != velocity
    ):
        state.patch.receive(mido.Message('note_on', note=note, velocity=velocity))
    breath = round(parameters['breath'])
    if state.parameters.get('breath') != breath:
        state.patch.receive(mido.Message('control_change', control=2, value=breath))
    pitch = round(parameters['pitch_bend'])
    if state.parameters.get('pitch_bend') != pitch:
        state.patch.receive(mido.Message('pitchwheel', pitch=pitch))
    state.parameters = parameters.copy()
