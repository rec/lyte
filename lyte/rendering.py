"""Prepare and render Ufor light compositions with Lyte's NumPy effects."""

from __future__ import annotations

from fractions import Fraction
from typing import cast

import numpy as np
from numpy.typing import NDArray
from ufor import effects, light_animation
from ufor.composition import Composition
from ufor.interface import OutputSelection
from ufor.library import Library
from ufor.lights import LightType, Wiring

from . import animation
from .animate.build import RendererCapabilityError, build_effect


class PythonAnimationScore(light_animation.AnimationScore):
    """Explicit runtime contract for a Python-defined Ufor animation score."""

    def initial_lyte_state(self, output: LightType) -> animation.State:
        return animation.State()

    def render_lyte_frame(
        self,
        output: LightType,
        state: animation.State,
        tick: int,
        parameters: dict[str, float],
    ) -> NDArray[np.float32]:
        raise NotImplementedError


class PreparedAnimation:
    def __init__(
        self,
        library: Library,
        composition: Composition,
        output_name: str,
        wiring: Wiring | None = None,
    ) -> None:
        self.library = library
        self.composition = composition
        self.output_name = output_name
        output = composition.output('root', output_name)
        if not isinstance(output.stream, LightType):
            raise RendererCapabilityError(
                f'output {output_name!r} is not a light output'
            )
        self.output = output.stream
        self.wiring_indexes = (
            None
            if wiring is None
            else np.asarray(wiring.indexes(self.output.layout), dtype=np.intp)
        )
        self.states: dict[str, animation.State] = {}
        self.renderers: dict[str, animation.Animation | PythonAnimationScore] = {}
        self._last_ticks: dict[str, int] = {}
        self._cache: dict[tuple[str, int], NDArray[np.float32]] = {}
        self.tick = 0
        self._prepare_parts()

    @property
    def rate(self) -> Fraction:
        output = self.composition.output('root', self.output_name)
        return self.composition.rate('root', output.stream.timebase)

    @property
    def fps(self) -> float:
        return float(self.rate)

    def render(self) -> NDArray[np.float32]:
        frame = self._render_part('root', self.output_name, self.tick)
        self.tick += 1
        self._cache.clear()
        return frame

    def byte_frame(self, wired: bool = False) -> NDArray[np.uint8]:
        frame = self.render()
        if wired and self.wiring_indexes is not None:
            frame = np.ascontiguousarray(frame[self.wiring_indexes])
        return animation.byte_light_frame_from_float(frame)

    def set_parameters(self, values: dict[str, float]) -> None:
        current = self.composition.parts['root'].parameters
        updated = Composition(
            self.composition.root,
            self.composition.scores,
            current | values,
        )
        if updated.parts.keys() != self.composition.parts.keys() or any(
            updated.parts[p].score != self.composition.parts[p].score
            for p in updated.parts
        ):
            raise RendererCapabilityError(
                'parameter update changed the prepared score structure'
            )
        output = updated.output('root', self.output_name)
        if output.stream != self.output:
            raise RendererCapabilityError(
                'parameter update changed the prepared light output'
            )
        for path, part in updated.parts.items():
            score = updated.scores[part.score].score
            previous_part = self.composition.parts[path]
            previous_score = self.composition.scores[previous_part.score].score
            if not isinstance(score, light_animation.AnimationScore) or not isinstance(
                previous_score, light_animation.AnimationScore
            ):
                continue
            current_operation = light_animation.operation_at(
                previous_score.body,
                Fraction(0),
                self._local_parameters(previous_score, previous_part.parameters),
            )
            next_operation = light_animation.operation_at(
                score.body,
                Fraction(0),
                self._local_parameters(score, part.parameters),
            )
            if (
                isinstance(current_operation, effects.Effect)
                and current_operation != next_operation
            ):
                raise RendererCapabilityError(
                    f'{path}: live built-in effect parameters are construction-only'
                )
        self.composition = updated

    def _prepare_parts(self) -> None:
        for path, part in self.composition.parts.items():
            score = self.composition.scores[part.score].score
            if not isinstance(score, light_animation.AnimationScore):
                raise RendererCapabilityError(f'{path}: score is not an animation')
            custom = self._python_score(part.score, score)
            if custom is not None:
                renderer: animation.Animation | PythonAnimationScore = custom
            elif isinstance(score.body.operation, effects.Effect):
                renderer = build_effect(cast(effects.EffectValue, score.body.operation))
            else:
                continue
            output = score.outputs[0].stream
            assert isinstance(output, LightType)
            if isinstance(renderer, PythonAnimationScore):
                state = renderer.initial_lyte_state(output)
            else:
                state = renderer.initial_state(
                    animation.Device(led_count=len(output.layout.lights))
                )
            state.fps = float(self.composition.rate(path, output.timebase))
            self.renderers[path] = renderer
            self.states[path] = state

    def _python_score(
        self, identity: str, score: light_animation.AnimationScore
    ) -> PythonAnimationScore | None:
        entry = self.library.entries[identity]
        origin = self.library.entries[entry.content_origin or identity]
        score_type = origin.python_class
        if score_type is None:
            return None
        if not issubclass(score_type, PythonAnimationScore):
            raise RendererCapabilityError(
                f'{identity}: Python animation must subclass PythonAnimationScore'
            )
        if score_type.render_lyte_frame is PythonAnimationScore.render_lyte_frame:
            raise RendererCapabilityError(
                f'{identity}: Python animation does not implement render_lyte_frame'
            )
        return score_type.model_validate(score.model_dump())

    def _render_part(
        self, path: str, output_name: str, tick: int
    ) -> NDArray[np.float32]:
        key = path, tick
        if key in self._cache:
            return self._cache[key]
        part = self.composition.parts[path]
        score = self.composition.scores[part.score].score
        if not isinstance(score, light_animation.AnimationScore):
            raise RendererCapabilityError(f'{path}: score is not an animation')
        output = self.composition.output(path, output_name)
        stream = cast(LightType, output.stream)
        rate = self.composition.rate(path, stream.timebase)
        at = Fraction(tick, 1) / rate
        operation = light_animation.operation_at(
            score.body, at, self._local_parameters(score, part.parameters)
        )
        renderer = self.renderers.get(path)
        if isinstance(renderer, PythonAnimationScore):
            self._require_next_tick(path, tick)
            frame = renderer.render_lyte_frame(
                stream, self.states[path], tick, part.parameters
            )
        elif isinstance(operation, effects.Effect):
            description = cast(effects.EffectValue, operation)
            if renderer is None:
                raise RendererCapabilityError(
                    f'{path}: no renderer prepared for {description.effect!r}'
                )
            current = build_effect(description)
            self._require_next_tick(path, tick)
            frame = current.render(
                animation.Device(led_count=len(stream.layout.lights)),
                self.states[path],
            )
        else:
            frames = self._source_frames(path, operation, tick, rate)
            frame = compose_frame(operation, stream, frames, at)
        result = animation.validate_float_light_frame(
            len(stream.layout.lights), len(stream.components), frame
        )
        self._cache[key] = result
        return result

    def _source_frames(
        self,
        path: str,
        operation: object,
        tick: int,
        rate: Fraction,
    ) -> dict[OutputSelection, NDArray[np.float32]]:
        if isinstance(operation, light_animation.Cues):
            selections = [
                (source, exact_tick(local * rate))
                for source, local, _ in light_animation.cue_weights(
                    operation, Fraction(tick, 1) / rate
                )
            ]
        else:
            selections = [
                (source, tick) for source in light_animation.sources(operation)
            ]
        part = self.composition.parts[path]
        return {
            source: self._render_part(
                part.children[source.name], source.output, child_tick
            )
            for source, child_tick in selections
        }

    def _require_next_tick(self, path: str, tick: int) -> None:
        previous = self._last_ticks.get(path)
        if previous is not None and tick != previous + 1:
            raise ValueError(
                f'{path}: stateful rendering requires sequential logical ticks'
            )
        self._last_ticks[path] = tick

    @staticmethod
    def _local_parameters(
        score: light_animation.AnimationScore, parameters: dict[str, float]
    ) -> dict[str, float]:
        return {
            export.binding.parameter: parameters[export.name]
            for export in score.parameters
            if export.binding.name == 'animation'
        }


def compose_frame(
    operation: object,
    output: LightType,
    frames: dict[OutputSelection, NDArray[np.float32]],
    at: Fraction = Fraction(0),
) -> NDArray[np.float32]:
    count = len(output.layout.lights)
    components = len(output.components)
    if isinstance(operation, light_animation.Fill):
        frame = np.tile(np.asarray(operation.values, dtype=np.float32), (count, 1))
    elif isinstance(operation, light_animation.Reverse):
        frame = np.ascontiguousarray(frames[operation.source][::-1])
    elif isinstance(operation, light_animation.Gain):
        frame = frames[operation.source] * np.float32(operation.amount)
    elif isinstance(operation, light_animation.ComponentMap):
        frame = (
            frames[operation.source] @ np.asarray(operation.matrix, dtype=np.float32).T
        )
    elif isinstance(operation, light_animation.Place):
        frame = np.zeros((count, components), dtype=np.float32)
        indexes = {light.name: i for i, light in enumerate(output.layout.lights)}
        for placement in operation.placements:
            frame[[indexes[n] for n in placement.lights]] = frames[placement.source]
    elif isinstance(operation, light_animation.Mix):
        frame = sum(
            (
                frames[source.source] * np.float32(source.weight)
                for source in operation.sources
            ),
            start=np.zeros((count, components), dtype=np.float32),
        )
        frame = np.clip(frame, 0, 1)
    elif isinstance(operation, light_animation.Crossfade):
        progress = np.float32(operation.fade.progress(at))
        frame = (
            frames[operation.outgoing] * (np.float32(1) - progress)
            + frames[operation.incoming] * progress
        )
    elif isinstance(operation, light_animation.Cues):
        frame = sum(
            (
                frames[source] * np.float32(weight)
                for source, _, weight in light_animation.cue_weights(operation, at)
            ),
            start=np.zeros((count, components), dtype=np.float32),
        )
    else:
        raise RendererCapabilityError(
            f'Lyte cannot compose operation {type(operation).__name__}'
        )
    return np.ascontiguousarray(frame, dtype=np.float32)


def exact_tick(seconds: Fraction) -> int:
    if seconds.denominator != 1:
        raise ValueError(f'light time {seconds} is not an exact logical tick')
    return seconds.numerator
