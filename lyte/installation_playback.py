"""Hardware-independent installation playback and frame distribution."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import isfinite

import mido
import numpy as np
from numpy.typing import NDArray
from reccy.protocol import ipc, rpc
from ufor import library_files
from ufor.library import Library
from ufor.lights import Interpretation

from . import animation, installation_config, rendering, runtime_control, show
from .control_recording import ControlRecorder
from .metrics import RenderCost


class InstallationPlayback:
    def __init__(
        self,
        config: installation_config.InstallationFile,
        library: Library,
        led_counts: dict[str, int],
    ) -> None:
        self.config = config
        self.library = library
        self.led_counts = led_counts
        self.active: ActiveAnimation | None = None
        self.queued_name: str | None = None
        self.queued_duration = 0.0
        self.master_level = 1.0
        self.transition_duration = 0.0
        self.transition_started = 0.0
        self.outgoing: ActiveAnimation | None = None
        self.transition_snapshot: dict[str, NDArray[np.uint8]] | None = None
        self.last_frames: dict[str, NDArray[np.uint8]] = {}
        self.performance = runtime_control.MidiPerformance()
        self.selected_test: runtime_control.LightTestCommand | None = None
        self.active_test: runtime_control.ActiveLightTest | None = None
        self.blackout = False
        self.revision = 0
        self.render_costs: dict[str, dict[str, RenderCost]] = {}
        self.recorder: ControlRecorder | None = None

    def command(self, command: str, params: dict[str, object]) -> rpc.Result:
        if command == 'select_animation':
            name = params.get('name')
            if not isinstance(name, str) or name not in self.config.animations:
                return ipc.Error(
                    type='error',
                    message='select_animation requires a configured animation name',
                )
            duration = params.get('duration', 0.0)
            if (
                isinstance(duration, bool)
                or not isinstance(duration, int | float)
                or not isfinite(duration)
                or duration < 0
            ):
                return ipc.Error(
                    type='error',
                    message='transition duration must be finite and nonnegative',
                )
            self.queued_name = name
            self.queued_duration = float(duration)
            result: rpc.Result = {'state': 'queued', 'name': name}
        elif command == 'master_level':
            level = params.get('level')
            if (
                isinstance(level, bool)
                or not isinstance(level, int | float)
                or not isfinite(level)
                or not 0 <= level <= 1
            ):
                return ipc.Error(
                    type='error', message='master level must be between 0 and 1'
                )
            self.master_level = float(level)
            result = 'ok'
        elif command == 'test':
            if self.blackout:
                return ipc.Error(
                    type='error',
                    message='select an animation before testing during blackout',
                )
            test = runtime_control.light_test_command(params)
            if isinstance(test, ipc.Error):
                return test
            self.selected_test = test
            result = {'state': 'queued', 'level': test.level, 'duration': test.duration}
        elif command == 'blackout':
            self.blackout = True
            self.queued_name = None
            self.selected_test = None
            self.active_test = None
            self.outgoing = None
            self.transition_snapshot = None
            self.transition_duration = 0.0
            self.last_frames = {}
            result = 'ok'
        else:
            return ipc.Error(type='error', message=f'unknown command {command}')
        self.revision += 1
        if self.recorder is not None:
            self.recorder.command(command, params)
        return result

    def select(self, name: str, duration: float = 0, now: float = 0) -> None:
        active = ActiveAnimation(
            name, self.config.animations[name], self.library, self.led_counts
        )
        active.costs = self.render_costs.setdefault(name, {})
        for binding in active.bindings:
            binding.prepared.timing = active.costs.setdefault(
                binding.output_name, binding.prepared.timing
            )
        active.apply_performance(self.performance)
        if duration > 0 and self.active is not None:
            if (
                self.outgoing is not None
                or self.transition_snapshot is not None
                or self.active_test is not None
                or self.blackout
            ):
                self.transition_snapshot = {
                    n: self.last_frames.get(n, np.zeros((c, 3), dtype=np.uint8)).copy()
                    for n, c in self.led_counts.items()
                }
                self.outgoing = None
            else:
                self.outgoing = self.active
                self.transition_snapshot = None
            self.transition_duration = duration
            self.transition_started = now
        else:
            self.outgoing = None
            self.transition_snapshot = None
            self.transition_duration = 0.0
        self.active = active
        self.blackout = False
        self.active_test = None
        self.revision += 1

    def receive_midi(self, message: mido.Message) -> None:
        if self.recorder is not None:
            self.recorder.midi(message)
        if self.config.midi is None or (
            self.config.midi.channel is not None
            and getattr(message, 'channel', None) != self.config.midi.channel - 1
        ):
            return
        if message.type == 'program_change':
            names = list(self.config.animations)
            current = self.queued_name or (
                self.active.name if self.active is not None else names[0]
            )
            self.queued_name = names[(names.index(current) + 1) % len(names)]
            self.queued_duration = 0.0
        else:
            self.performance.receive(message)
            for active in [self.active, self.outgoing]:
                if active is None:
                    continue
                active.apply_performance(
                    self.performance,
                    restart=message.type == 'note_on' and bool(message.velocity),
                )
        self.revision += 1

    def reset_midi(self) -> None:
        if self.recorder is not None:
            self.recorder.command('reset_midi', {})
        self.performance = runtime_control.MidiPerformance()
        for active in [self.active, self.outgoing]:
            if active is not None:
                active.apply_performance(self.performance)
        self.revision += 1

    def render(self, now: float) -> list[tuple[str, NDArray[np.uint8]]]:
        if self.recorder is not None:
            self.recorder.delivery(now, self.led_counts)
        if self.queued_name is not None:
            name = self.queued_name
            self.queued_name = None
            self.select(name, self.queued_duration, now)
        if self.blackout:
            return [
                (n, np.zeros((c, 3), dtype=np.uint8))
                for n, c in self.led_counts.items()
            ]
        if self.selected_test is not None:
            self.active_test = runtime_control.ActiveLightTest(
                command=self.selected_test, started_at=now
            )
            self.selected_test = None
            self.revision += 1
        if self.active_test is not None:
            frames = []
            for name, count in self.led_counts.items():
                frame = self.active_test.render(animation.Device(led_count=count), now)
                if frame is None:
                    self.active_test = None
                    self.revision += 1
                    break
                frames.append((name, frame))
            else:
                return self.finish_frame(frames)
        assert self.active is not None
        frames = self.active.render(now)
        if self.transition_duration:
            progress = min(
                1.0,
                max(0.0, (now - self.transition_started) / self.transition_duration),
            )
            if progress >= 1:
                self.outgoing = None
                self.transition_snapshot = None
                self.transition_duration = 0.0
                self.revision += 1
            else:
                source = (
                    dict(self.outgoing.render(now))
                    if self.outgoing is not None
                    else self.transition_snapshot
                )
                assert source is not None
                frames = [
                    (
                        n,
                        np.rint(
                            animation.scale_byte_rgb_frame(source[n], len(f)).astype(
                                np.float64
                            )
                            * (1 - progress)
                            + f.astype(np.float64) * progress
                        ).astype(np.uint8),
                    )
                    for n, f in frames
                ]
        return self.finish_frame(frames)

    def finish_frame(
        self, frames: list[tuple[str, NDArray[np.uint8]]]
    ) -> list[tuple[str, NDArray[np.uint8]]]:
        self.last_frames = dict(frames)
        if self.master_level == 1:
            return frames
        return [
            (n, np.rint(f.astype(np.float64) * self.master_level).astype(np.uint8))
            for n, f in frames
        ]


@dataclass
class PreparedBinding:
    output_name: str
    expression: installation_config.OutputExpression
    prepared: rendering.PreparedAnimation
    frame: NDArray[np.uint8] | None = None


class ActiveAnimation:
    def __init__(
        self,
        name: str,
        definition: installation_config.BoundAnimation,
        library: Library,
        led_counts: dict[str, int],
    ) -> None:
        self.name = name
        self.definition = definition
        self.library = library
        self.led_counts = led_counts
        self.performance = runtime_control.MidiPerformance()
        self.bindings: list[PreparedBinding] = []
        self.costs: dict[str, RenderCost] = {}
        self._prepare()

    def _prepare(self) -> None:
        self.started_at: Fraction | None = None
        self.bindings = [
            PreparedBinding(
                output_name,
                installation_config.parse_output_expression(
                    expression, self.led_counts
                ),
                prepare_output(self.library, self.definition.selector, output_name),
            )
            for output_name, expression in self.definition.outputs.items()
        ]
        for binding in self.bindings:
            binding.prepared.timing = self.costs.setdefault(
                binding.output_name, binding.prepared.timing
            )

    def apply_performance(
        self, performance: runtime_control.MidiPerformance, *, restart: bool = False
    ) -> None:
        self.performance = performance.model_copy(deep=True)
        if restart:
            self._prepare()
        values = {c.parameter: c.map(performance) for c in self.definition.controls}
        if values:
            for binding in self.bindings:
                binding.prepared.set_parameters(values)

    def render(self, now: float) -> list[tuple[str, NDArray[np.uint8]]]:
        at = Fraction(str(now))
        if self.started_at is None:
            self.started_at = at
        elapsed = at - self.started_at
        frames: list[tuple[str, NDArray[np.uint8]]] = []
        for binding in self.bindings:
            if (
                self.definition.activation == 'always'
                or self.performance.note is not None
            ):
                tick = int(elapsed * binding.prepared.rate)
                binding.prepared.timing.catch_up_ticks += max(
                    0, tick - binding.prepared.tick
                )
                while binding.prepared.tick <= tick:
                    binding.frame = binding.prepared.byte_frame(wired=True)
                assert binding.frame is not None
                source = binding.frame
            else:
                source = np.zeros(
                    (len(binding.prepared.output.layout.lights), 3), dtype=np.uint8
                )
            frames.extend(
                distribute_frame(
                    source,
                    binding.expression,
                    self.led_counts,
                )
            )
        return frames


def distribute_frame(
    source: NDArray[np.uint8],
    expression: installation_config.OutputExpression,
    led_counts: dict[str, int],
) -> list[tuple[str, NDArray[np.uint8]]]:
    if expression.operator == 'mirror':
        return [
            (name, animation.scale_byte_rgb_frame(source, led_counts[name]))
            for name in expression.members
        ]
    total = sum(led_counts[name] for name in expression.members)
    scaled = animation.scale_byte_rgb_frame(source, total)
    frames: list[tuple[str, NDArray[np.uint8]]] = []
    start = 0
    for name in expression.members:
        end = start + led_counts[name]
        frames.append((name, np.ascontiguousarray(scaled[start:end])))
        start = end
    return frames


def prepare_output(
    library: Library, selector: str, output_name: str
) -> rendering.PreparedAnimation:
    try:
        prepared = show.prepare_library_animation(
            library, show.LightProgramSpec(selector=selector, output=output_name)
        )
    except ValueError as error:
        raise installation_config.InstallationFileError(
            f'animation output {output_name!r}: {error}'
        ) from error
    if prepared.requires_audio:
        raise installation_config.InstallationFileError(
            'audio-driven scores currently support offline preview and export only'
        )
    if prepared.output.components != ['red', 'green', 'blue']:
        raise installation_config.InstallationFileError(
            f'animation output {output_name!r} requires red, green, blue components'
        )
    if prepared.output.interpretation != Interpretation.drive:
        raise installation_config.InstallationFileError(
            f'animation output {output_name!r} requires drive light values'
        )
    return prepared


def load_library(config: installation_config.InstallationFile) -> Library:
    try:
        library = library_files.read_library(config.library_config)
    except (OSError, ValueError) as error:
        raise installation_config.InstallationFileError(str(error)) from error
    show.log_diagnostics(library)
    for definition in config.animations.values():
        for output_name in definition.outputs:
            prepared = prepare_output(library, definition.selector, output_name)
            for control in definition.controls:
                try:
                    contract = prepared.composition.parameter_contract(
                        prepared.composition.root, control.parameter
                    )
                    values = (
                        control.values
                        or control.output
                        or installation_config._CONTROL_RANGES[control.source]
                    )
                    original = prepared.composition.parts['root'].parameters.copy()
                    for value in values:
                        if (
                            not isfinite(value)
                            or not contract.minimum <= value <= contract.maximum
                        ):
                            raise ValueError(
                                f'mapped value {value} is outside '
                                f'{contract.minimum}..{contract.maximum}'
                            )
                        prepared.set_parameters({control.parameter: value})
                    prepared.set_parameters(original)
                except ValueError as error:
                    raise installation_config.InstallationFileError(
                        f'{definition.selector}, output {output_name}, '
                        f'control {control.parameter}: {error}'
                    ) from error
    return library
