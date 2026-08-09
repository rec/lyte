from __future__ import annotations

import unittest

import mido
import numpy as np
from numpy import testing as npt
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict

from lyte import animation, midi
from lyte.animations import bibliopixel


class MidiTests(unittest.TestCase):
    def test_patch_creates_state_from_first_note_on(self) -> None:
        class Config(BaseModel, frozen=True):
            name: str = 'wx7'

        class TestState(BaseModel):
            initial_note_on: mido.Message
            events: list[str] = []

            model_config = ConfigDict(arbitrary_types_allowed=True)

        class TestPatch(midi.Patch[Config, TestState]):
            def make_state(self, msg: mido.Message) -> TestState:
                return TestState(initial_note_on=msg)

        patch = TestPatch(config=Config())
        msg = mido.Message('note_on', note=64, velocity=100)

        patch.receive(msg)

        self.assertIsNotNone(patch.state)
        if patch.state is None:
            self.fail('state was not created')
        self.assertEqual(patch.state.initial_note_on, msg)

    def test_patch_routes_wx7_messages_to_state_callbacks(self) -> None:
        class Config(BaseModel, frozen=True):
            name: str = 'wx7'

        class TestState(BaseModel):
            initial_note_on: mido.Message
            events: list[str] = []

            model_config = ConfigDict(arbitrary_types_allowed=True)

        class TestPatch(midi.Patch[Config, TestState]):
            def make_state(self, msg: mido.Message) -> TestState:
                return TestState(initial_note_on=msg)

            def note_off(self) -> None:
                if (state := self.state) is None:
                    raise AssertionError('state was not set')
                state.events.append('note-off')

            def breath_control(self, msg: mido.Message) -> None:
                if (state := self.state) is None:
                    raise AssertionError('state was not set')
                state.events.append(f'breath:{msg.value}')

            def pitch_bend(self, msg: mido.Message) -> None:
                if (state := self.state) is None:
                    raise AssertionError('state was not set')
                state.events.append('pitch')

        patch = TestPatch(config=Config())
        patch.receive(mido.Message('note_on', note=64, velocity=100))
        if patch.state is None:
            self.fail('state was not created')
        state = patch.state

        patch.receive(mido.Message('control_change', control=2, value=96))
        patch.receive(mido.Message('pitchwheel', pitch=1024))
        patch.receive(mido.Message('note_on', note=64, velocity=0))

        self.assertEqual(
            state.events,
            ['breath:96', 'pitch', 'note-off'],
        )
        self.assertIsNone(patch.state)

    def test_region_light_patch_composes_stateful_animations(self) -> None:
        patch = midi.RegionLightPatch(
            config=midi.RegionLightPatchConfig(
                regions=[
                    midi.RegionAnimation(
                        animation=bibliopixel.ColorFill(color=(255, 0, 0)),
                        start=0,
                        led_count=2,
                    ),
                    midi.RegionAnimation(
                        animation=bibliopixel.ColorFill(color=(0, 0, 255)),
                        start=2,
                        led_count=3,
                    ),
                ]
            )
        )
        device = animation.Device(led_count=5)

        patch.receive(mido.Message('note_on', note=64, velocity=100))

        npt.assert_array_equal(
            patch.render(device),
            np.array(
                [
                    [1.0, 0.0, 0.0],
                    [1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0],
                    [0.0, 0.0, 1.0],
                    [0.0, 0.0, 1.0],
                ],
                dtype=np.float32,
            ),
        )

    def test_region_light_patch_is_black_without_an_active_note(self) -> None:
        patch = midi.RegionLightPatch(
            config=midi.RegionLightPatchConfig(
                regions=[
                    midi.RegionAnimation(
                        animation=bibliopixel.ColorFill(color=(255, 0, 0)),
                        start=0,
                        led_count=1,
                    )
                ]
            )
        )

        npt.assert_array_equal(
            patch.render(animation.Device(led_count=1)),
            np.zeros((1, 3), dtype=np.float32),
        )

    def test_blend_light_patch_adds_child_frames_by_default(self) -> None:
        class RedConfig(BaseModel, frozen=True):
            value: float = 0.4

        class GreenConfig(BaseModel, frozen=True):
            value: float = 0.75

        class RedState(BaseModel):
            note: int

        class GreenState(BaseModel):
            note: int

        class RedPatch(midi.LightPatch[RedConfig, RedState]):
            def make_state(self, msg: mido.Message) -> RedState:
                return RedState(note=msg.note)

            def render(self, device: animation.Device) -> NDArray[np.float32]:
                frame = np.zeros((device.led_count, 3), dtype=np.float32)
                if self.state is not None:
                    frame[:, 0] = self.config.value
                return animation.validate_frame(device, frame)

        class GreenPatch(midi.LightPatch[GreenConfig, GreenState]):
            def make_state(self, msg: mido.Message) -> GreenState:
                return GreenState(note=msg.note)

            def render(self, device: animation.Device) -> NDArray[np.float32]:
                frame = np.zeros((device.led_count, 3), dtype=np.float32)
                if self.state is not None:
                    frame[:, 1] = self.config.value
                return animation.validate_frame(device, frame)

        patch = midi.BlendLightPatch(
            config=midi.BlendLightPatchConfig(),
            patches=[
                RedPatch(config=RedConfig()),
                GreenPatch(config=GreenConfig()),
            ],
        )
        device = animation.Device(led_count=2)

        patch.receive(mido.Message('note_on', note=64, velocity=100))

        npt.assert_array_equal(
            patch.render(device),
            np.array([[0.4, 0.75, 0.0], [0.4, 0.75, 0.0]], dtype=np.float32),
        )

    def test_blend_light_patch_clips_added_frames_by_default(self) -> None:
        class Config(BaseModel, frozen=True):
            channel: int

        class State(BaseModel):
            note: int

        class ConstantPatch(midi.LightPatch[Config, State]):
            def make_state(self, msg: mido.Message) -> State:
                return State(note=msg.note)

            def render(self, device: animation.Device) -> NDArray[np.float32]:
                frame = np.zeros((device.led_count, 3), dtype=np.float32)
                frame[:, self.config.channel] = 0.75
                return animation.validate_frame(device, frame)

        patch = midi.BlendLightPatch(
            config=midi.BlendLightPatchConfig(),
            patches=[
                ConstantPatch(config=Config(channel=0)),
                ConstantPatch(config=Config(channel=0)),
            ],
        )

        npt.assert_array_equal(
            patch.render(animation.Device(led_count=1)),
            np.array([[1.0, 0.0, 0.0]], dtype=np.float32),
        )

    def test_weighted_blend_light_patch_uses_mutable_note_state_weights(self) -> None:
        class Config(BaseModel, frozen=True):
            color: tuple[float, float, float]

        class State(BaseModel):
            pass

        class ConstantPatch(midi.LightPatch[Config, State]):
            def make_state(self, msg: mido.Message) -> State:
                return State()

            def render(self, device: animation.Device) -> NDArray[np.float32]:
                frame = np.empty((device.led_count, 3), dtype=np.float32)
                frame[:] = self.config.color
                return animation.validate_frame(device, frame)

        patch = midi.WeightedBlendLightPatch(
            config=midi.WeightedBlendLightPatchConfig(weights=[1.0, 0.0]),
            patches=[
                ConstantPatch(config=Config(color=(1.0, 0.0, 0.0))),
                ConstantPatch(config=Config(color=(0.0, 0.0, 1.0))),
            ],
        )
        device = animation.Device(led_count=1)
        patch.receive(mido.Message('note_on', note=64, velocity=100))

        npt.assert_array_equal(
            patch.render(device), np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        )

        patch.set_weight(0, 0.25)
        patch.set_weight(1, 0.75)

        npt.assert_array_equal(
            patch.render(device), np.array([[0.25, 0.0, 0.75]], dtype=np.float32)
        )

    def test_union_light_patch_renders_for_each_named_device(self) -> None:
        class Config(BaseModel, frozen=True):
            channel: int

        class State(BaseModel):
            note: int

        class ConstantPatch(midi.LightPatch[Config, State]):
            def make_state(self, msg: mido.Message) -> State:
                return State(note=msg.note)

            def render(self, device: animation.Device) -> NDArray[np.float32]:
                frame = np.zeros((device.led_count, 3), dtype=np.float32)
                frame[:, self.config.channel] = 0.5
                return animation.validate_frame(device, frame)

        patch = midi.UnionLightPatch(
            config=midi.UnionLightPatchConfig(),
            patches={
                'tree': ConstantPatch(config=Config(channel=0)),
                'window': ConstantPatch(config=Config(channel=1)),
            },
        )

        frames = patch.render(
            {
                'tree': animation.Device(led_count=2),
                'window': animation.Device(led_count=3),
            }
        )

        npt.assert_array_equal(
            frames['tree'],
            np.array([[0.5, 0.0, 0.0], [0.5, 0.0, 0.0]], dtype=np.float32),
        )
        npt.assert_array_equal(
            frames['window'],
            np.array(
                [[0.0, 0.5, 0.0], [0.0, 0.5, 0.0], [0.0, 0.5, 0.0]],
                dtype=np.float32,
            ),
        )

    def test_union_light_patch_requires_matching_device_names(self) -> None:
        patch = midi.UnionLightPatch(
            config=midi.UnionLightPatchConfig(),
            patches={},
        )

        with self.assertRaisesRegex(ValueError, 'must match'):
            patch.render({'tree': animation.Device(led_count=2)})

    def test_concat_light_patch_splits_virtual_frame_across_devices(self) -> None:
        class Config(BaseModel, frozen=True):
            pass

        class State(BaseModel):
            pass

        class IndexPatch(midi.LightPatch[Config, State]):
            def make_state(self, msg: mido.Message) -> State:
                return State()

            def render(self, device: animation.Device) -> NDArray[np.float32]:
                frame = np.zeros((device.led_count, 3), dtype=np.float32)
                frame[:, 0] = np.arange(device.led_count, dtype=np.float32)
                return animation.validate_frame(device, frame)

        patch = midi.ConcatLightPatch(
            config=midi.ConcatLightPatchConfig(),
            devices=[
                animation.Device(led_count=2),
                midi.DeviceSegment(
                    device=animation.Device(led_count=6), start=2, led_count=3
                ),
            ],
            patch=IndexPatch(config=Config()),
        )

        frames = patch.render()

        npt.assert_array_equal(
            frames[0].frame,
            np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32),
        )
        self.assertEqual(frames[0].segment.start, 0)
        npt.assert_array_equal(
            frames[1].frame,
            np.array(
                [[2.0, 0.0, 0.0], [3.0, 0.0, 0.0], [4.0, 0.0, 0.0]],
                dtype=np.float32,
            ),
        )
        self.assertEqual(frames[1].segment.start, 2)

    def test_device_segment_must_fit_within_its_device(self) -> None:
        with self.assertRaisesRegex(ValueError, 'must fit'):
            midi.DeviceSegment(
                device=animation.Device(led_count=3), start=1, led_count=3
            )
