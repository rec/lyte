from __future__ import annotations

# ruff: noqa: I001

import base64
import importlib
import io
import json
import random
import tempfile
import unittest
from collections.abc import Sized
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import mido
import numpy as np
from numpy import testing as npt
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict

from lyte import animation, cli, fps_test, midi, patches, show
from lyte.animate import config, random_show
from lyte.animations import bibliopixel
from lyte.animations.christmas import hamiltonian
from lyte.animations.christmas.random_walk import RandomWalk, perturb
from lyte.animations.colors import solid_rgb_frame
from lyte.errors import DiscoveryError, ProtocolError, UnsupportedEndpointError
from lyte.logging import LOGGING, log, log_error, log_status
from lyte.preview import document
from lyte.preview.layout import Layout
from lyte.retry import RetryConfig, retry_call
from lyte.twinkly import diagnostic
from lyte.twinkly import inputs
from lyte.twinkly import layout
from lyte.twinkly import media
from lyte.twinkly import mode
from lyte.twinkly import networking
from lyte.twinkly import output
from lyte.twinkly import session
from lyte.twinkly import timer
from lyte.twinkly.authentication import CHALLENGE_KEY, derive_key, mac_bytes, rc4
from lyte.twinkly.client import TWINKLY_API_PREFIX, TwinklyClient, TwinklyResponse
from lyte.twinkly.discovery import DiscoveredDevice, parse_discovery_response
from lyte.twinkly.frame import frame_packets_v3, frame_payload, send_frame_v3

COMMAND = 'lyte.twinkly.command'
OUTPUT = 'lyte.twinkly.output'
DIAGNOSTIC = 'lyte.twinkly.diagnostic'


def render(
    source: animation.Animation,
    device: animation.Device,
    state: animation.State,
) -> NDArray[np.uint8]:
    return animation.byte_light_frame_from_float(source.render(device, state))


def initial_state(
    source: animation.Animation, led_count: int
) -> tuple[animation.Device, animation.State]:
    device = animation.Device(led_count=led_count)
    return device, source.initial_state(device)


class ShowFileTests(unittest.TestCase):
    def test_parse_show_file_accepts_device_to_source_run_map(self) -> None:
        show_file = show.parse_show_file(
            {
                'run': {'tree': 'rainbow'},
                'animations': {
                    'rainbow': {
                        'impl': 'lyte.animations.bibliopixel.rainbow.Rainbow',
                        'fps': 60,
                    }
                },
                'devices': {'tree': {'kind': 'twinkly', 'host': '192.168.1.23'}},
            },
            'show.toml',
        )

        self.assertIsNotNone(show_file.run)
        if show_file.run is None:
            self.fail('run section was not parsed')
        self.assertEqual(show_file.run['tree'].source, 'rainbow')
        self.assertEqual(show_file.animations['rainbow'].params, {'fps': 60})
        self.assertEqual(show_file.devices['tree'].params, {'host': '192.168.1.23'})

    def test_load_show_files_reads_and_merges_toml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / 'library.toml'
            devices = root / 'devices.toml'
            run = root / 'run.toml'
            library.write_text(
                '[animations.rainbow]\n'
                'impl = "lyte.animations.bibliopixel.rainbow.Rainbow"\n'
            )
            devices.write_text('[devices.tree]\nkind = "twinkly"\n')
            run.write_text('[run]\ntree = "rainbow"\n')

            show_file = show.load_show_files([library, devices, run])

        self.assertEqual(set(show_file.animations), {'rainbow'})
        self.assertEqual(set(show_file.devices), {'tree'})
        self.assertIsNotNone(show_file.run)

    def test_parse_show_file_accepts_run_target_tables(self) -> None:
        show_file = show.parse_show_file(
            {
                'run': {'tree': {'source': 'rainbow', 'brightness': 0.8}},
                'animations': {
                    'rainbow': {'impl': 'lyte.animations.bibliopixel.rainbow.Rainbow'}
                },
                'devices': {'tree': {'kind': 'twinkly'}},
            },
            'show.toml',
        )

        self.assertIsNotNone(show_file.run)
        if show_file.run is None:
            self.fail('run section was not parsed')
        self.assertEqual(show_file.run['tree'].source, 'rainbow')
        self.assertEqual(show_file.run['tree'].params, {'brightness': 0.8})

    def test_parse_show_file_rejects_routes_section(self) -> None:
        with self.assertRaisesRegex(show.ShowFileError, 'unknown top-level'):
            show.parse_show_file({'routes': {}}, 'show.toml')

    def test_parse_show_file_preserves_animation_sources(self) -> None:
        show_file = show.parse_show_file(
            {
                'animations': {
                    'wash': {
                        'impl': 'lyte.animations.bibliopixel.color_fill.ColorFill'
                    },
                    'sparkle': {'impl': 'lyte.animations.bibliopixel.twinkle.Twinkle'},
                    'look': {
                        'impl': 'lyte.composition.Add',
                        'sources': ['wash', 'sparkle'],
                        'clip': True,
                    },
                },
            },
            'show.toml',
        )

        self.assertEqual(show_file.animations['look'].sources, ['wash', 'sparkle'])
        self.assertEqual(show_file.animations['look'].params, {'clip': True})

    def test_merge_show_files_combines_library_device_and_run_files(self) -> None:
        library = show.parse_show_file(
            {
                'animations': {
                    'rainbow': {'impl': 'lyte.animations.bibliopixel.rainbow.Rainbow'}
                }
            },
            'library.toml',
        )
        devices = show.parse_show_file(
            {'devices': {'tree': {'kind': 'twinkly'}}},
            'devices.toml',
        )
        run = show.parse_show_file({'run': {'tree': 'rainbow'}}, 'run.toml')

        merged = show.merge_show_files([library, devices, run])

        self.assertEqual(set(merged.animations), {'rainbow'})
        self.assertEqual(set(merged.devices), {'tree'})
        self.assertIsNotNone(merged.run)

    def test_merge_show_files_rejects_duplicate_names(self) -> None:
        first = show.parse_show_file(
            {
                'animations': {
                    'rainbow': {'impl': 'lyte.animations.bibliopixel.rainbow.Rainbow'}
                }
            },
            'first.toml',
        )
        second = show.parse_show_file(
            {
                'animations': {
                    'rainbow': {'impl': 'lyte.animations.bibliopixel.rainbow.Rainbow'}
                }
            },
            'second.toml',
        )

        with self.assertRaisesRegex(show.ShowFileError, 'duplicate animations'):
            show.merge_show_files([first, second])

    def test_merge_show_files_rejects_multiple_run_sections(self) -> None:
        first = show.ShowFile(
            run={'tree': show.RunTargetSpec(source='rainbow')},
            animations={
                'rainbow': show.AnimationSpec(
                    impl='lyte.animations.bibliopixel.rainbow.Rainbow'
                )
            },
            devices={'tree': show.DeviceSpec(kind='twinkly')},
        )
        second = show.ShowFile(
            run={'arch': show.RunTargetSpec(source='rainbow')},
            animations={
                'rainbow': show.AnimationSpec(
                    impl='lyte.animations.bibliopixel.rainbow.Rainbow'
                )
            },
            devices={'arch': show.DeviceSpec(kind='twinkly')},
        )

        with self.assertRaisesRegex(show.ShowFileError, 'multiple loaded show files'):
            show.merge_show_files([first, second])

    def test_show_file_rejects_unknown_run_device(self) -> None:
        with self.assertRaisesRegex(ValueError, 'does not name a device'):
            show.validate_graph(
                show.ShowFile(
                    run={'tree': show.RunTargetSpec(source='rainbow')},
                    animations={
                        'rainbow': show.AnimationSpec(
                            impl='lyte.animations.bibliopixel.rainbow.Rainbow'
                        )
                    },
                )
            )

    def test_show_file_rejects_unknown_source(self) -> None:
        with self.assertRaisesRegex(ValueError, 'unknown source'):
            show.validate_graph(
                show.ShowFile(
                    run={'tree': show.RunTargetSpec(source='missing')},
                    devices={'tree': show.DeviceSpec(kind='twinkly')},
                )
            )

    def test_show_file_rejects_source_cycles(self) -> None:
        with self.assertRaisesRegex(ValueError, 'cycle'):
            show.validate_graph(
                show.ShowFile(
                    animations={
                        'a': show.AnimationSpec(impl='lyte.fake.A', sources=['b']),
                        'b': show.AnimationSpec(impl='lyte.fake.B', sources=['a']),
                    }
                )
            )

    def test_resolve_python_path_finds_callables(self) -> None:
        value = show.resolve_python_path('lyte.animations.bibliopixel.rainbow.Rainbow')

        self.assertTrue(callable(value))

    def test_resolve_python_path_rejects_non_callables(self) -> None:
        with self.assertRaisesRegex(show.ShowFileError, 'not callable'):
            show.resolve_python_path('lyte.animation.__doc__')

    def test_run_show_loads_and_resolves_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            show_file = root / 'show.toml'
            show_file.write_text(
                '[run]\n'
                'tree = "rainbow"\n'
                '[animations.rainbow]\n'
                'impl = "lyte.animations.bibliopixel.rainbow.Rainbow"\n'
                '[devices.tree]\n'
                'kind = "twinkly"\n'
            )

            result = show.run_show(show.ShowConfig(files=[show_file]))

        self.assertEqual(result, 0)


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


class PatchLibraryTests(unittest.TestCase):
    def test_load_wearable_library_and_map_logical_regions(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))

        self.assertEqual(len(library.patches), 32)
        self.assertEqual(library.wearable.physical_map_status, 'provisional')
        self.assertEqual(
            list(library.wearable.segments),
            ['left_leg', 'right_leg', 'left_arm', 'right_arm', 'chest'],
        )

        logical_frame = np.zeros((200, 3), dtype=np.float32)
        logical_frame[:, 0] = np.arange(200, dtype=np.float32)
        physical_frame = patches.map_logical_frame(library.wearable, logical_frame)

        npt.assert_array_equal(physical_frame[28:60], logical_frame[0:32])
        npt.assert_array_equal(physical_frame[128:160], logical_frame[32:64])
        npt.assert_array_equal(physical_frame[0:28], logical_frame[64:92])
        npt.assert_array_equal(physical_frame[60:76], logical_frame[92:108])
        npt.assert_array_equal(physical_frame[76:100], logical_frame[152:176])
        npt.assert_array_equal(physical_frame[176:200], logical_frame[176:200])

    def test_locator_frame_lights_only_the_selected_logical_region(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))

        frame = patches.locator_frame(library.wearable, 'left_arm')

        self.assertTrue(np.all(frame[0:28] == 1.0))
        self.assertTrue(np.all(frame[60:76] == 1.0))
        self.assertTrue(np.all(frame[28:60] == 0.0))
        self.assertTrue(np.all(frame[76:200] == 0.0))

    def test_patch_command_lists_library_without_connecting(self) -> None:
        output = io.StringIO()
        with patch('sys.stdout', output):
            result = patches.run_patch_command(
                patches.PatchCommandConfig(library=Path('patches/wearable-breath.toml'))
            )

        self.assertEqual(result, 0)
        self.assertIn(
            'Wearable: 200 LEDs (provisional physical map)', output.getvalue()
        )
        self.assertIn('prism_limbs:', output.getvalue())

    def test_cli_patch_command_dispatches_patch_library(self) -> None:
        with patch.object(patches, 'run_patch_command', return_value=0) as run_command:
            result = cli.main(['patch', 'list'])

        self.assertEqual(result, 0)
        self.assertEqual(run_command.call_args.args[0].action, 'list')

    def test_patch_library_rejects_physical_map_gaps(self) -> None:
        with self.assertRaisesRegex(ValueError, 'must contain 2 LEDs'):
            patches.PatchLibrary.model_validate(
                {
                    'wearable': {
                        'led_count': 2,
                        'physical_map_status': 'provisional',
                        'segments': {'body': {'start': 0, 'led_count': 2}},
                        'physical_map': {
                            'body': {'ranges': [{'start': 0, 'led_count': 1}]}
                        },
                    },
                    'patches': {'black': {'layers': ['solid']}},
                }
            )


class ChristmasAnimationTests(unittest.TestCase):
    def test_ported_animations_render_float_frames(self) -> None:
        from lyte.animations.christmas import effects, gradients

        device = animation.Device(led_count=4)
        sources = [
            effects.ExponentialFade(),
            effects.GreyCode(),
            effects.Rain(seed=1),
            effects.Randomize(seed=1),
            gradients.LinearGradient(),
            gradients.LogGradient(),
        ]

        for source in sources:
            state = source.initial_state(device)
            frame = source.render(device, state)
            self.assertEqual(frame.shape, (4, 3))
            self.assertEqual(frame.dtype, np.float32)
            self.assertTrue(frame.flags.c_contiguous)


class DiscoveryTests(unittest.TestCase):
    def test_parse_discovery_response(self) -> None:
        device = parse_discovery_response(b'\xab\x01\xa8\xc0OKTwinkly_A1234B\x00')

        self.assertEqual(device.ip_address, '192.168.1.171')
        self.assertEqual(device.device_id, 'Twinkly_A1234B')

    def test_rejects_bad_discovery_response(self) -> None:
        with self.assertRaises(DiscoveryError):
            parse_discovery_response(b'\xab\x01\xa8\xc0NOTwinkly_A1234B\x00')


class CryptoTests(unittest.TestCase):
    def test_mac_bytes_accepts_common_formats(self) -> None:
        expected = b'\x5c\xcf\x7f\x33\xaa\xff'

        self.assertEqual(mac_bytes('5C:CF:7F:33:AA:FF'), expected)
        self.assertEqual(mac_bytes('5c-cf-7f-33-aa-ff'), expected)
        self.assertEqual(mac_bytes('5ccf7f33aaff'), expected)

    def test_derive_key_matches_original_driver(self) -> None:
        key = derive_key(CHALLENGE_KEY, '5C:CF:7F:33:AA:FF')

        self.assertEqual(key, b'9\xb9\x1a]\xc7\x90.\xaa\x0cV\xc9\x8d9\xbb^\x12')

    def test_rc4_known_vector(self) -> None:
        self.assertEqual(rc4(b'Plaintext', b'Key').hex(), 'bbf316e8d940af0ad3')


class RealtimeTests(unittest.TestCase):
    def test_solid_rgb_frame(self) -> None:
        npt.assert_array_equal(
            solid_rgb_frame(3, 230, 85, 0),
            np.array([[230, 85, 0], [230, 85, 0], [230, 85, 0]], dtype=np.uint8),
        )

    def test_solid_float_light_frame(self) -> None:
        npt.assert_array_equal(
            animation.solid_float_light_frame(2, (1.0, 0.5, 0.0, 0.25)),
            np.array(
                [[1.0, 0.5, 0.0, 0.25], [1.0, 0.5, 0.0, 0.25]],
                dtype=np.float32,
            ),
        )

    def test_validate_float_light_frame_checks_shape_dtype_and_finiteness(
        self,
    ) -> None:
        frame = np.zeros((2, 3), dtype=np.float32)

        self.assertIs(animation.validate_float_light_frame(2, 3, frame), frame)
        with self.assertRaisesRegex(ValueError, 'dtype float32'):
            animation.validate_float_light_frame(2, 3, frame.astype(np.float64))
        with self.assertRaisesRegex(ValueError, 'shape light_count x light channels'):
            animation.validate_float_light_frame(2, 4, frame)
        with self.assertRaisesRegex(ValueError, 'finite'):
            animation.validate_float_light_frame(
                1,
                3,
                np.array([[np.nan, 0.0, 0.0]], dtype=np.float32),
            )
        with self.assertRaisesRegex(ValueError, 'C-contiguous'):
            animation.validate_float_light_frame(
                2, 3, np.zeros((3, 2), dtype=np.float32).T
            )

    def test_byte_light_frame_from_float_clips_rounds_and_contiguates(self) -> None:
        frame = np.array(
            [
                [-0.25, 0.0, 0.5],
                [1.0, 1.25, 128 / 255],
            ],
            dtype=np.float32,
        ).T

        encoded = animation.byte_light_frame_from_float(frame)

        npt.assert_array_equal(
            encoded,
            np.array([[0, 255], [0, 255], [128, 128]], dtype=np.uint8),
        )
        self.assertTrue(encoded.flags.c_contiguous)

    def test_float_rgb_helpers_convert_at_byte_boundary(self) -> None:
        self.assertEqual(
            animation.float_color_from_rgb((255, 128, 0)), (1.0, 128 / 255, 0.0)
        )
        self.assertEqual(
            animation.rgb_from_float_color((1.25, 0.5, -0.25)), (255, 128, 0)
        )

    def test_generation_2_v3_packet(self) -> None:
        frame = solid_rgb_frame(250, 230, 85, 0)

        packets = list(frame_packets_v3('MCIGBF1qJlg=', frame))

        self.assertEqual(len(packets), 1)
        header, payload = packets[0]
        self.assertIs(payload.obj, frame)
        self.assertEqual(header, b'\x030"\x06\x04]j&X\x00\x00\x00')
        self.assertEqual(
            bytes(payload),
            b'\xe6U\x00' * 250,
        )

    def test_generation_2_v3_fragments_large_frames(self) -> None:
        frame = np.frombuffer(b'a' * 903, dtype=np.uint8).reshape((301, 3))

        packets = list(frame_packets_v3('MCIGBF1qJlg=', frame))

        self.assertEqual(len(packets), 2)
        self.assertEqual(packets[0][0], b'\x030"\x06\x04]j&X\x00\x00\x00')
        self.assertEqual(packets[1][0], b'\x030"\x06\x04]j&X\x00\x00\x01')
        self.assertEqual(len(packets[0][1]), 900)
        self.assertEqual(bytes(packets[1][1]), b'aaa')

    def test_rejects_bad_frame_shape(self) -> None:
        with self.assertRaises(ValueError):
            frame_payload(np.zeros((9,), dtype=np.uint8))

    def test_send_frame_uses_array_payload_buffer(self) -> None:
        frame = solid_rgb_frame(1, 1, 2, 3)
        sent_buffers = []

        class Socket:
            def __enter__(self) -> Socket:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def sendmsg(
                self,
                buffers: list[Sized],
                flags: list[object],
                mode: int,
                address: tuple[str, int],
            ) -> int:
                sent_buffers.append((buffers, flags, mode, address))
                return sum(len(buffer) for buffer in buffers)

        with patch('lyte.twinkly.frame.socket.socket', return_value=Socket()):
            sent = send_frame_v3('192.168.1.23', 'MCIGBF1qJlg=', frame)

        self.assertEqual(sent, 15)
        buffers, flags, mode, address = sent_buffers[0]
        self.assertEqual(flags, [])
        self.assertEqual(mode, 0)
        self.assertEqual(address, ('192.168.1.23', 7777))
        self.assertEqual(buffers[0], b'\x030"\x06\x04]j&X\x00\x00\x00')
        self.assertIs(buffers[1].obj, frame)

    def test_rejects_bad_realtime_token(self) -> None:
        with self.assertRaises(ProtocolError):
            list(frame_packets_v3('bad', solid_rgb_frame(1, 0, 0, 0)))


class FpsTestTests(unittest.TestCase):
    def test_fps_values_include_120_hz(self) -> None:
        self.assertEqual(fps_test.FPS_VALUES, (30.0, 60.0, 120.0, 240, 480, 960, 1920))

    def test_cli_animate_command_dispatches_animation(self) -> None:
        with patch.object(cli, 'run_animate', return_value=0) as run_animate:
            result = cli.main(
                [
                    'animate',
                    'rainbow',
                    '--duration',
                    '1.5',
                    '--fps',
                    '30',
                ]
            )

        self.assertEqual(result, 0)
        config = run_animate.call_args.args[0]
        self.assertEqual(config.animation, 'rainbow')
        self.assertEqual(config.duration, 1.5)
        self.assertEqual(config.fps, 30)

    def test_cli_preview_command_dispatches_preview(self) -> None:
        with patch.object(cli, 'run_preview', return_value=0) as run_preview:
            result = cli.main(
                [
                    'preview',
                    'rainbow',
                    'preview.html',
                    '--width',
                    '24',
                    '--duration',
                    '1.5',
                ]
            )

        self.assertEqual(result, 0)
        config = run_preview.call_args.args[0]
        self.assertEqual(config.animation, 'rainbow')
        self.assertEqual(config.output, Path('preview.html'))
        self.assertEqual(config.width, 24)
        self.assertEqual(config.duration, 1.5)

    def test_cli_preview_command_lists_patterns_without_arguments(self) -> None:
        output = io.StringIO()

        with patch('sys.stdout', output):
            result = cli.main(['preview'])

        self.assertEqual(result, 0)
        self.assertIn('color_fill\n', output.getvalue())
        self.assertIn('rainbow\n', output.getvalue())
        self.assertNotIn('off\n', output.getvalue())

    def test_gradient_frame_blends_between_endpoint_colors(self) -> None:
        npt.assert_array_equal(
            fps_test.gradient_frame(3, (0, 0, 0), (100, 50, 200)),
            np.array([[0, 0, 0], [50, 25, 100], [100, 50, 200]], dtype=np.uint8),
        )

    def test_blend_frames_crossfades_two_frames(self) -> None:
        first_frame = np.array([[0, 100, 200]], dtype=np.uint8)
        second_frame = np.array([[100, 200, 0]], dtype=np.uint8)

        npt.assert_array_equal(
            fps_test.blend_frames(first_frame, second_frame, 0.25),
            np.array([[25, 125, 150]], dtype=np.uint8),
        )

    def test_cli_test_command_dispatches_fps_test(self) -> None:
        with patch.object(cli.fps_test, 'run_fps_test', return_value=0) as run_fps_test:
            result = cli.main(
                [
                    'test',
                    '--host',
                    '192.168.1.23',
                    '--led-count',
                    '10',
                    '--duration',
                    '1.5',
                ]
            )

        self.assertEqual(result, 0)
        config = run_fps_test.call_args.args[0]
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(config.led_count, 10)
        self.assertEqual(config.duration, 1.5)

    def test_cli_test2_command_dispatches_temporal_dither_test(self) -> None:
        with patch.object(
            cli.fps_test, 'run_temporal_dither_test', return_value=0
        ) as run_temporal_dither_test:
            result = cli.main(
                [
                    'test2',
                    '--host',
                    '192.168.1.23',
                    '--led-count',
                    '10',
                    '--time',
                    '4.5',
                ]
            )

        self.assertEqual(result, 0)
        config = run_temporal_dither_test.call_args.args[0]
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(config.led_count, 10)
        self.assertEqual(config.time, 4.5)

    def test_cli_show_command_dispatches_show_validation(self) -> None:
        with patch.object(cli.show, 'run_show', return_value=0) as run_show:
            result = cli.main(['show', 'first.toml', 'second.toml'])

        self.assertEqual(result, 0)
        config = run_show.call_args.args[0]
        self.assertEqual(config.files, [Path('first.toml'), Path('second.toml')])

    def test_cli_black_floor_command_dispatches_black_floor_test(self) -> None:
        with patch.object(
            cli.fps_test, 'run_black_floor_test', return_value=0
        ) as run_black_floor_test:
            result = cli.main(
                [
                    'black-floor',
                    '--host',
                    '192.168.1.23',
                    '--led-count',
                    '10',
                ]
            )

        self.assertEqual(result, 0)
        config = run_black_floor_test.call_args.args[0]
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(config.led_count, 10)

    def test_cli_verify_command_dispatches_verify_test(self) -> None:
        with patch.object(
            cli.fps_test, 'run_verify_test', return_value=0
        ) as run_verify_test:
            result = cli.main(
                [
                    'verify',
                    '--host',
                    '192.168.1.23',
                    '--led-count',
                    '10',
                    '--mode',
                    'slow',
                ]
            )

        self.assertEqual(result, 0)
        config = run_verify_test.call_args.args[0]
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(config.led_count, 10)
        self.assertEqual(config.mode, 'slow')

    def test_cli_diagnostic_command_dispatches_diagnostic(self) -> None:
        with patch.object(
            cli.diagnostic, 'run_diagnostic_command', return_value=0
        ) as run_diagnostic_command:
            result = cli.main(
                [
                    'diagnostic',
                    '--host',
                    '192.168.1.23',
                    '--attempts',
                    '2',
                ]
            )

        self.assertEqual(result, 0)
        config = run_diagnostic_command.call_args.args[0]
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(config.attempts, 2)

    def test_cli_diagnostic_realtime_flag_dispatches_diagnostic(self) -> None:
        with patch.object(
            cli.diagnostic, 'run_diagnostic_command', return_value=0
        ) as run_diagnostic_command:
            result = cli.main(
                [
                    'diagnostic',
                    '--realtime',
                    '--led-count',
                    '10',
                    '--pause',
                    '0.1',
                ]
            )

        self.assertEqual(result, 0)
        config = run_diagnostic_command.call_args.args[0]
        self.assertTrue(config.realtime)
        self.assertEqual(config.led_count, 10)
        self.assertEqual(config.pause, 0.1)

    def test_cli_brightness_command_dispatches_output_control(self) -> None:
        with patch.object(
            cli.output, 'run_output_control', return_value=0
        ) as run_output_control:
            result = cli.main(
                [
                    'brightness',
                    'set',
                    '75',
                    '--host',
                    '192.168.1.23',
                ]
            )

        self.assertEqual(result, 0)
        config, kind, action, value = run_output_control.call_args.args
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(kind, 'brightness')
        self.assertEqual(action, 'set')
        self.assertEqual(value, 75)

    def test_cli_saturation_command_dispatches_output_control(self) -> None:
        with patch.object(
            cli.output, 'run_output_control', return_value=0
        ) as run_output_control:
            result = cli.main(
                [
                    'saturation',
                    'get',
                    '--host',
                    '192.168.1.23',
                ]
            )

        self.assertEqual(result, 0)
        config, kind, action, value = run_output_control.call_args.args
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(kind, 'saturation')
        self.assertEqual(action, 'get')
        self.assertIsNone(value)

    def test_cli_mode_command_dispatches_mode_control(self) -> None:
        with patch.object(
            cli.mode, 'run_mode_control', return_value=0
        ) as run_mode_control:
            result = cli.main(['mode', 'set', 'demo'])

        self.assertEqual(result, 0)
        config, action, mode = run_mode_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set')
        self.assertEqual(mode, 'demo')

    def test_cli_color_command_dispatches_color_control(self) -> None:
        with patch.object(
            cli.mode, 'run_color_control', return_value=0
        ) as run_color_control:
            result = cli.main(['color', 'set', '1', '2', '3'])

        self.assertEqual(result, 0)
        config, action, red, green, blue = run_color_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set')
        self.assertEqual((red, green, blue), (1, 2, 3))

    def test_cli_effects_command_dispatches_effect_control(self) -> None:
        with patch.object(
            cli.mode, 'run_effect_control', return_value=0
        ) as run_effect_control:
            result = cli.main(['effects', 'set-current', '4'])

        self.assertEqual(result, 0)
        config, action, effect_id = run_effect_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set-current')
        self.assertEqual(effect_id, 4)

    def test_cli_layout_command_dispatches_layout_control(self) -> None:
        with patch.object(
            cli.layout, 'run_layout_control', return_value=0
        ) as run_layout_control:
            result = cli.main(['layout', 'export', 'layout.json'])

        self.assertEqual(result, 0)
        config, action, path = run_layout_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'export')
        self.assertEqual(path, Path('layout.json'))

    def test_cli_led_config_command_dispatches_led_config_control(self) -> None:
        with patch.object(
            cli.layout, 'run_led_config_control', return_value=0
        ) as run_led_config_control:
            result = cli.main(['led-config', 'set', 'config.json'])

        self.assertEqual(result, 0)
        config, action, path = run_led_config_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set')
        self.assertEqual(path, Path('config.json'))

    def test_cli_timer_command_dispatches_timer_control(self) -> None:
        with patch.object(
            cli.timer, 'run_timer_control', return_value=0
        ) as run_timer_control:
            result = cli.main(['timer', 'set', '3600', '7200', '--time-now', '1800'])

        self.assertEqual(result, 0)
        config, action, time_on, time_off, time_now = run_timer_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set')
        self.assertEqual(time_on, 3600)
        self.assertEqual(time_off, 7200)
        self.assertEqual(time_now, 1800)

    def test_cli_movie_command_dispatches_movie_control(self) -> None:
        with patch.object(
            cli.media, 'run_movie_control', return_value=0
        ) as run_movie_control:
            result = cli.main(['movie', 'current'])

        self.assertEqual(result, 0)
        config, action = run_movie_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'current')

    def test_cli_playlist_command_dispatches_playlist_control(self) -> None:
        with patch.object(
            cli.media, 'run_playlist_control', return_value=0
        ) as run_playlist_control:
            result = cli.main(['playlist', 'current'])

        self.assertEqual(result, 0)
        config, action = run_playlist_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'current')

    def test_cli_network_command_dispatches_network_control(self) -> None:
        with patch.object(
            cli.networking, 'run_network_control', return_value=0
        ) as run_network_control:
            result = cli.main(['network', 'scan-results'])

        self.assertEqual(result, 0)
        config, action = run_network_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'scan-results')

    def test_cli_mqtt_command_dispatches_mqtt_control(self) -> None:
        with patch.object(
            cli.inputs, 'run_mqtt_control', return_value=0
        ) as run_mqtt_control:
            result = cli.main(['mqtt', 'config'])

        self.assertEqual(result, 0)
        config, action = run_mqtt_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'config')

    def test_cli_mic_command_dispatches_mic_control(self) -> None:
        with patch.object(
            cli.inputs, 'run_mic_control', return_value=0
        ) as run_mic_control:
            result = cli.main(['mic', 'sample'])

        self.assertEqual(result, 0)
        config, action = run_mic_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'sample')

    def test_cli_music_command_dispatches_music_control(self) -> None:
        with patch.object(
            cli.inputs, 'run_music_control', return_value=0
        ) as run_music_control:
            result = cli.main(['music', 'current-driver-set'])

        self.assertEqual(result, 0)
        config, action = run_music_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'current-driver-set')

    def test_discover_host_retries_until_a_device_replies(self) -> None:
        device = DiscoveredDevice(ip_address='192.168.1.23', device_id='twinkly')

        with (
            patch(
                'lyte.twinkly.realtime.discover',
                side_effect=(iter(()), iter([device])),
            ),
            patch('sys.stdout', new_callable=io.StringIO),
            patch('sys.stderr', new_callable=io.StringIO),
        ):
            host = fps_test.realtime.discover_host(None)

        self.assertEqual(host, '192.168.1.23')

    def test_discover_host_stops_at_timeout(self) -> None:
        with (
            patch('lyte.twinkly.realtime.discover', return_value=iter(())),
            patch('lyte.twinkly.realtime.time.monotonic', side_effect=(0.0, 0.0, 1.0)),
            patch('sys.stdout', new_callable=io.StringIO),
            patch('sys.stderr', new_callable=io.StringIO),
        ):
            host = fps_test.realtime.discover_host(1.0)

        self.assertIsNone(host)

    def test_verify_lists_demos_before_running_them(self) -> None:
        output = io.StringIO()

        with (
            patch('lyte.fps_test.realtime.discover_host', return_value='192.168.1.23'),
            patch('lyte.fps_test.realtime.read_led_count', return_value=2),
            patch('lyte.fps_test.realtime.prepare_device', return_value=True),
            patch('lyte.fps_test.run_fast_verify', return_value=()),
            patch('lyte.fps_test.realtime.turn_off_device', return_value=True),
            patch('sys.stdout', output),
        ):
            result = fps_test.run_verify_test(fps_test.VerifyConfig())

        self.assertEqual(result, 0)
        self.assertIn(
            '[verify] Demos: primary-channels, moving-gradient, crossfade, '
            'temporal-dither',
            output.getvalue(),
        )

    def test_realtime_command_turns_off_device_after_setup_interrupt(self) -> None:
        def interrupt_setup(
            client: TwinklyClient,
            retry: RetryConfig,
            host: str,
        ) -> bool:
            raise KeyboardInterrupt

        with (
            patch('lyte.fps_test.realtime.read_led_count', return_value=2),
            patch('lyte.fps_test.realtime.prepare_device', interrupt_setup),
            patch(
                'lyte.fps_test.realtime.turn_off_device', return_value=True
            ) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = fps_test.run_realtime_command(
                '192.168.1.23',
                5.0,
                None,
                1,
                0,
                1,
                None,
                lambda _client, _retry, _host, _device: None,
            )

        self.assertEqual(result, 0)
        turn_off.assert_called_once()

    def test_dispersed_pixel_order_visits_each_led_once(self) -> None:
        order = fps_test.dispersed_pixel_order(11)

        self.assertEqual(sorted(order.tolist()), list(range(11)))
        self.assertEqual(order.tolist(), [0, 5, 10, 4, 9, 3, 8, 2, 7, 1, 6])

    def test_temporal_dither_grayscale_frame_spreads_fractional_step(
        self,
    ) -> None:
        device = animation.Device(led_count=4)
        order = np.array([0, 2, 1, 3], dtype=np.int64)

        frame = fps_test.temporal_dither_grayscale_frame(device, 0, 1, 2, 5, order)

        npt.assert_array_equal(
            frame,
            np.array([[1, 1, 1], [0, 0, 0], [1, 1, 1], [0, 0, 0]], dtype=np.uint8),
        )

    def test_solid_grayscale_frame_fills_all_channels(self) -> None:
        npt.assert_array_equal(
            fps_test.solid_grayscale_frame(animation.Device(led_count=2), 7),
            np.array([[7, 7, 7], [7, 7, 7]], dtype=np.uint8),
        )

    def test_solid_rgb_level_frame_fills_all_channels(self) -> None:
        npt.assert_array_equal(
            fps_test.solid_rgb_level_frame(animation.Device(led_count=2), (1, 2, 3)),
            np.array([[1, 2, 3], [1, 2, 3]], dtype=np.uint8),
        )

    def test_adjust_black_floor_level_changes_one_channel(self) -> None:
        self.assertEqual(fps_test.adjust_black_floor_level((0, 0, 0), 'r'), (1, 0, 0))
        self.assertEqual(fps_test.adjust_black_floor_level((0, 0, 0), 'g'), (0, 1, 0))
        self.assertEqual(fps_test.adjust_black_floor_level((0, 0, 0), 'b'), (0, 0, 1))
        self.assertEqual(fps_test.adjust_black_floor_level((1, 1, 1), 'R'), (0, 1, 1))
        self.assertEqual(fps_test.adjust_black_floor_level((1, 1, 1), 'G'), (1, 0, 1))
        self.assertEqual(fps_test.adjust_black_floor_level((1, 1, 1), 'B'), (1, 1, 0))
        self.assertEqual(fps_test.adjust_black_floor_level((0, 0, 0), 'R'), (0, 0, 0))
        self.assertEqual(
            fps_test.adjust_black_floor_level((255, 255, 255), 'r'), (255, 255, 255)
        )
        self.assertEqual(
            fps_test.adjust_black_floor_level((1, 2, 3), fps_test.UP_KEY), (2, 3, 4)
        )
        self.assertEqual(
            fps_test.adjust_black_floor_level((1, 2, 3), fps_test.DOWN_KEY), (0, 1, 2)
        )
        self.assertEqual(
            fps_test.adjust_black_floor_level((255, 255, 255), fps_test.UP_KEY),
            (255, 255, 255),
        )

    def test_black_floor_keys_show_initial_black_and_each_valid_key(self) -> None:
        sent_frames = []
        keys = iter(['r', 'g', 'b', 'R', 'x', 'B', fps_test.UP_KEY, fps_test.DOWN_KEY])

        def record_frame(
            client: TwinklyClient,
            retry: RetryConfig,
            host: str,
            frame: NDArray[np.uint8],
        ) -> int:
            sent_frames.append(frame.copy())
            return frame.nbytes

        def read_key() -> str:
            try:
                return next(keys)
            except StopIteration:
                raise KeyboardInterrupt from None

        with (
            patch('lyte.fps_test.realtime.send_realtime_frame', record_frame),
            self.assertRaises(KeyboardInterrupt),
        ):
            fps_test.run_black_floor_keys(
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                animation.Device(led_count=1),
                read_key,
            )

        self.assertEqual(
            [tuple(int(i) for i in f[0]) for f in sent_frames],
            [
                (0, 0, 0),
                (1, 0, 0),
                (1, 1, 0),
                (1, 1, 1),
                (0, 1, 1),
                (0, 1, 0),
                (1, 2, 1),
                (0, 1, 0),
            ],
        )

    def test_read_single_key_uses_unbuffered_file_descriptor(self) -> None:
        with patch('lyte.fps_test.os.read', return_value=b'r') as read:
            key = fps_test.read_single_key(7)

        self.assertEqual(key, 'r')
        read.assert_called_once_with(7, 1)

    def test_read_single_key_reads_arrow_escape_sequence(self) -> None:
        with patch('lyte.fps_test.os.read', side_effect=[b'\x1b', b'[A']) as read:
            key = fps_test.read_single_key(7)

        self.assertEqual(key, fps_test.UP_KEY)
        self.assertEqual(read.call_args_list[0].args, (7, 1))
        self.assertEqual(read.call_args_list[1].args, (7, 2))

    def test_temporal_dither_comparison_runs_direct_then_dithered(self) -> None:
        device = animation.Device(led_count=2)
        phases = []

        def record_fade(
            client: TwinklyClient,
            retry: RetryConfig,
            host: str,
            device: animation.Device,
            fps: float,
            duration: float,
            phase: str,
            frame_at: object,
        ) -> fps_test.FadeReport:
            phases.append((phase, fps, duration))
            return fps_test.FadeReport(
                fps=fps,
                phase=phase,
                total_frames=1,
                unique_frames=1,
                late_frames=0,
                short_sends=0,
                max_late_ms=0,
                elapsed_ms=0,
            )

        with (
            patch('lyte.fps_test.stream_frames', record_fade),
            patch('lyte.fps_test.report_fades'),
        ):
            fps_test.run_temporal_dither_comparison(
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                device,
                5,
            )

        self.assertEqual(
            phases,
            [
                ('normal-black-to-white', 240.0, 5),
                ('normal-white-to-black', 240.0, 5),
                ('normal-black-hold', 240.0, 1.0),
                ('dithered-black-to-white', 240.0, 5),
                ('dithered-white-to-black', 240.0, 5),
                ('dithered-black-hold', 240.0, 1.0),
            ],
        )

    def test_verify_primary_channels_cycles_rgb_and_white(self) -> None:
        device = animation.Device(led_count=2)

        frames = [
            fps_test.verify_primary_channels_frame(device, i, 4) for i in range(4)
        ]

        npt.assert_array_equal(frames[0], np.full((2, 3), (255, 0, 0), dtype=np.uint8))
        npt.assert_array_equal(frames[1], np.full((2, 3), (0, 255, 0), dtype=np.uint8))
        npt.assert_array_equal(frames[2], np.full((2, 3), (0, 0, 255), dtype=np.uint8))
        npt.assert_array_equal(
            frames[3], np.full((2, 3), (255, 255, 255), dtype=np.uint8)
        )

    def test_verify_answer_accepts_only_yes_and_no(self) -> None:
        self.assertIs(fps_test.verify_answer('y'), True)
        self.assertIs(fps_test.verify_answer('n'), False)
        self.assertIsNone(fps_test.verify_answer('x'))
        self.assertIsNone(fps_test.verify_answer(None))

    def test_fast_verify_shows_black_demo_black_for_each_demo(self) -> None:
        device = animation.Device(led_count=2)
        phases = []

        def record_frames(
            client: TwinklyClient,
            retry: RetryConfig,
            host: str,
            device: animation.Device,
            fps: float,
            duration: float,
            phase: str,
            frame_at: object,
        ) -> fps_test.FadeReport:
            phases.append((phase, fps, duration))
            return fps_test.FadeReport(
                fps=fps,
                phase=phase,
                total_frames=1,
                unique_frames=1,
                late_frames=0,
                short_sends=0,
                max_late_ms=0,
                elapsed_ms=0,
            )

        with (
            patch(
                'lyte.fps_test.VERIFY_DEMOS',
                (fps_test.VERIFY_DEMOS[0], fps_test.VERIFY_DEMOS[1]),
            ),
            patch('lyte.fps_test.stream_frames', record_frames),
            patch('lyte.fps_test.report_fades'),
        ):
            results = fps_test.run_fast_verify(
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                device,
            )

        self.assertEqual(
            phases,
            [
                ('primary-channels-black-before', 60.0, 1.0),
                ('primary-channels', 60.0, 3.0),
                ('primary-channels-black-after', 60.0, 1.0),
                ('moving-gradient-black-before', 60.0, 1.0),
                ('moving-gradient', 60.0, 3.0),
                ('moving-gradient-black-after', 60.0, 1.0),
            ],
        )
        self.assertEqual(
            results,
            (
                fps_test.VerifyResult('primary-channels', None),
                fps_test.VerifyResult('moving-gradient', None),
            ),
        )

    def test_report_verify_results_lists_status_groups(self) -> None:
        output = io.StringIO()
        errors = io.StringIO()

        with (
            patch('sys.stdout', output),
            patch('sys.stderr', errors),
        ):
            fps_test.report_verify_results(
                (
                    fps_test.VerifyResult('good', True),
                    fps_test.VerifyResult('bad', False),
                    fps_test.VerifyResult('shown', None),
                )
            )

        self.assertIn('Worked: good', output.getvalue())
        self.assertIn('Shown without pass/fail: shown', output.getvalue())
        self.assertIn('Did not work: bad', errors.getvalue())

    def test_run_fades_separates_each_test_with_black(self) -> None:
        device = animation.Device(led_count=2)
        fades = []

        def record_fade(
            client: TwinklyClient,
            retry: RetryConfig,
            host: str,
            device: animation.Device,
            first_frame: NDArray[np.uint8],
            second_frame: NDArray[np.uint8],
            fps: float,
            duration: float,
            phase: str,
        ) -> fps_test.FadeReport:
            fades.append((first_frame.copy(), second_frame.copy(), fps, duration))
            return fps_test.FadeReport(
                fps=fps,
                phase=phase,
                total_frames=1,
                unique_frames=1,
                late_frames=0,
                short_sends=0,
                max_late_ms=0,
                elapsed_ms=0,
            )

        with (
            patch('lyte.fps_test.FPS_VALUES', (20.0,)),
            patch('lyte.fps_test.stream_fade', record_fade),
            patch('lyte.fps_test.report_fades'),
        ):
            fps_test.run_fades(
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                device,
                1.5,
                0,
            )

        self.assertEqual(len(fades), 3)
        npt.assert_array_equal(fades[0][0], np.zeros((2, 3), dtype=np.uint8))
        npt.assert_array_equal(fades[0][1], fades[1][0])
        npt.assert_array_equal(fades[1][1], fades[2][0])
        npt.assert_array_equal(fades[2][1], np.zeros((2, 3), dtype=np.uint8))
        self.assertEqual([f[2] for f in fades], [20.0, 20.0, 20.0])
        self.assertEqual([f[3] for f in fades], [1.5, 1.5, 1.5])

    def test_stream_fade_reports_unique_frames(self) -> None:
        device = animation.Device(led_count=1)

        with (
            patch('lyte.fps_test.realtime.send_realtime_frame', return_value=3),
            patch('lyte.fps_test.time.sleep'),
        ):
            report = fps_test.stream_fade(
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                device,
                np.array([[0, 0, 0]], dtype=np.uint8),
                np.array([[1, 0, 0]], dtype=np.uint8),
                2,
                2,
                'test',
            )

        self.assertEqual(report.total_frames, 4)
        self.assertEqual(report.unique_frames, 2)
        self.assertEqual(report.duplicate_frames, 2)
        self.assertEqual(report.short_sends, 0)

    def test_report_fades_reports_unexpected_events(self) -> None:
        output = io.StringIO()
        errors = io.StringIO()

        with (
            patch('sys.stdout', output),
            patch('sys.stderr', errors),
        ):
            fps_test.report_fades(
                (
                    fps_test.FadeReport(
                        fps=120,
                        phase='test',
                        total_frames=10,
                        unique_frames=4,
                        late_frames=2,
                        short_sends=1,
                        max_late_ms=1.5,
                        elapsed_ms=100,
                    ),
                )
            )

        self.assertIn('4/10 unique frames', output.getvalue())
        self.assertIn('2/10 times', errors.getvalue())
        self.assertIn('1 short UDP sends', errors.getvalue())


class FakeHttpResponse:
    def __init__(self, status: int, raw: bytes) -> None:
        self.status = status
        self.raw = raw

    def read(self) -> bytes:
        return self.raw


class FakeHttpConnection:
    response = FakeHttpResponse(200, b'{}')
    requests: list[
        tuple[str, int, float, str, str, bytes | None, dict[str, str] | None]
    ] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.requests.append(
            (self.host, self.port, self.timeout, method, url, body, headers)
        )

    def getresponse(self) -> FakeHttpResponse:
        return self.response

    def close(self) -> None:
        return None


class ClientTests(unittest.TestCase):
    def test_constructs_with_keyword_arguments(self) -> None:
        client = TwinklyClient(host='192.168.1.23', timeout=1.5)

        self.assertEqual(client.host, '192.168.1.23')
        self.assertEqual(client.timeout, 1.5)

    def test_delete_uses_delete_request(self) -> None:
        FakeHttpConnection.response = FakeHttpResponse(200, b'{"code":1000}')
        FakeHttpConnection.requests = []

        with patch('lyte.twinkly.client.client.HTTPConnection', FakeHttpConnection):
            response = TwinklyClient(host='192.168.1.23').delete(
                'movies', authenticated=False
            )

        self.assertEqual(response.data, {'code': 1000})
        self.assertEqual(
            FakeHttpConnection.requests,
            [
                (
                    '192.168.1.23',
                    80,
                    5.0,
                    'DELETE',
                    f'{TWINKLY_API_PREFIX}/movies',
                    None,
                    {'Content-Type': 'application/json'},
                )
            ],
        )

    def test_post_bytes_sends_binary_payload(self) -> None:
        FakeHttpConnection.response = FakeHttpResponse(200, b'{"code":1000}')
        FakeHttpConnection.requests = []

        with patch('lyte.twinkly.client.client.HTTPConnection', FakeHttpConnection):
            response = TwinklyClient(host='192.168.1.23').post_bytes(
                'movies/full',
                b'\x01\x02\x03',
                'application/octet-stream',
                authenticated=False,
            )

        self.assertEqual(response.data, {'code': 1000})
        self.assertEqual(
            FakeHttpConnection.requests,
            [
                (
                    '192.168.1.23',
                    80,
                    5.0,
                    'POST',
                    f'{TWINKLY_API_PREFIX}/movies/full',
                    b'\x01\x02\x03',
                    {
                        'Content-Type': 'application/octet-stream',
                        'Content-Length': '3',
                    },
                )
            ],
        )

    def test_request_rejects_json_body_and_binary_payload(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with self.assertRaisesRegex(ValueError, 'both JSON body and binary payload'):
            client.request(
                'POST',
                'movies/full',
                body={'code': 1000},
                payload=b'\x00',
                authenticated=False,
            )

    def test_404_raises_unsupported_endpoint_error(self) -> None:
        FakeHttpConnection.response = FakeHttpResponse(404, b'{"code":1101}')
        FakeHttpConnection.requests = []

        with (
            patch('lyte.twinkly.client.client.HTTPConnection', FakeHttpConnection),
            self.assertRaises(UnsupportedEndpointError) as raised,
        ):
            TwinklyClient(host='192.168.1.23').get('missing', authenticated=False)

        self.assertEqual(raised.exception.path, 'missing')
        self.assertEqual(raised.exception.text, '{"code":1101}')

    def test_firmware_version_and_status_default_to_unauthenticated_gets(self) -> None:
        calls = []

        def get(
            self: TwinklyClient,
            path: str,
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append((self.host, path, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        client = TwinklyClient(host='192.168.1.23')

        with patch.object(TwinklyClient, 'get', get):
            client.get_firmware_version()
            client.get_status()

        self.assertEqual(
            calls,
            [
                ('192.168.1.23', 'fw/version', False),
                ('192.168.1.23', 'status', False),
            ],
        )

    def test_device_name_summary_and_echo_use_documented_paths(self) -> None:
        calls = []

        def get(
            self: TwinklyClient,
            path: str,
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('GET', self.host, path, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def post(
            self: TwinklyClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('POST', self.host, path, body, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        client = TwinklyClient(host='192.168.1.23')

        with (
            patch.object(TwinklyClient, 'get', get),
            patch.object(TwinklyClient, 'post', post),
        ):
            client.get_device_name()
            client.get_summary()
            client.echo({'message': 'hello'})

        self.assertEqual(
            calls,
            [
                ('GET', '192.168.1.23', 'device_name', True),
                ('GET', '192.168.1.23', 'summary', True),
                ('POST', '192.168.1.23', 'echo', {'message': 'hello'}, True),
            ],
        )

    def test_brightness_and_saturation_use_documented_paths(self) -> None:
        calls = []

        def get(
            self: TwinklyClient,
            path: str,
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('GET', self.host, path, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'value': 100})

        def post(
            self: TwinklyClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('POST', self.host, path, body, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        client = TwinklyClient(host='192.168.1.23')

        with (
            patch.object(TwinklyClient, 'get', get),
            patch.object(TwinklyClient, 'post', post),
        ):
            client.get_brightness()
            client.set_brightness({'mode': 'enabled', 'type': 'A', 'value': 75})
            client.get_saturation()
            client.set_saturation({'mode': 'enabled', 'type': 'A', 'value': 80})

        self.assertEqual(
            calls,
            [
                ('GET', '192.168.1.23', 'led/out/brightness', True),
                (
                    'POST',
                    '192.168.1.23',
                    'led/out/brightness',
                    {'mode': 'enabled', 'type': 'A', 'value': 75},
                    True,
                ),
                ('GET', '192.168.1.23', 'led/out/saturation', True),
                (
                    'POST',
                    '192.168.1.23',
                    'led/out/saturation',
                    {'mode': 'enabled', 'type': 'A', 'value': 80},
                    True,
                ),
            ],
        )

    def test_mode_color_and_effects_use_documented_paths(self) -> None:
        calls = []

        def get(
            self: TwinklyClient,
            path: str,
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('GET', self.host, path, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def post(
            self: TwinklyClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('POST', self.host, path, body, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        client = TwinklyClient(host='192.168.1.23')

        with (
            patch.object(TwinklyClient, 'get', get),
            patch.object(TwinklyClient, 'post', post),
        ):
            client.get_led_mode()
            client.set_led_mode({'mode': 'demo'})
            client.get_led_color()
            client.set_led_color({'mode': 'rgb', 'red': 1, 'green': 2, 'blue': 3})
            client.get_effects()
            client.get_current_effect()
            client.set_current_effect({'effect_id': 4})

        self.assertEqual(
            calls,
            [
                ('GET', '192.168.1.23', 'led/mode', True),
                ('POST', '192.168.1.23', 'led/mode', {'mode': 'demo'}, True),
                ('GET', '192.168.1.23', 'led/color', True),
                (
                    'POST',
                    '192.168.1.23',
                    'led/color',
                    {'mode': 'rgb', 'red': 1, 'green': 2, 'blue': 3},
                    True,
                ),
                ('GET', '192.168.1.23', 'led/effects', True),
                ('GET', '192.168.1.23', 'led/effects/current', True),
                (
                    'POST',
                    '192.168.1.23',
                    'led/effects/current',
                    {'effect_id': 4},
                    True,
                ),
            ],
        )

    def test_layout_and_led_config_use_documented_paths(self) -> None:
        calls = []

        def get(
            self: TwinklyClient,
            path: str,
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('GET', self.host, path, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def post(
            self: TwinklyClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('POST', self.host, path, body, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def delete(
            self: TwinklyClient,
            path: str,
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('DELETE', self.host, path, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        client = TwinklyClient(host='192.168.1.23')

        with (
            patch.object(TwinklyClient, 'get', get),
            patch.object(TwinklyClient, 'post', post),
            patch.object(TwinklyClient, 'delete', delete),
        ):
            client.get_layout_full()
            client.set_layout_full({'source': '3d'})
            client.delete_layout_full()
            client.get_led_config()
            client.set_led_config({'strings': []})
            client.get_timer()
            client.set_timer({'time_now': 1800, 'time_on': 3600, 'time_off': 7200})
            client.get_movie_config()
            client.get_movies()
            client.get_current_movie()
            client.get_playlist()
            client.get_current_playlist_entry()
            client.get_network_scan()
            client.get_network_scan_results()
            client.get_network_status()
            client.get_mqtt_config()
            client.get_mic_config()
            client.get_mic_sample()
            client.get_music_drivers()
            client.get_music_driver_sets()
            client.get_current_music_driver_set()

        self.assertEqual(
            calls,
            [
                ('GET', '192.168.1.23', 'led/layout/full', True),
                ('POST', '192.168.1.23', 'led/layout/full', {'source': '3d'}, True),
                ('DELETE', '192.168.1.23', 'led/layout/full', True),
                ('GET', '192.168.1.23', 'led/config', True),
                ('POST', '192.168.1.23', 'led/config', {'strings': []}, True),
                ('GET', '192.168.1.23', 'timer', True),
                (
                    'POST',
                    '192.168.1.23',
                    'timer',
                    {'time_now': 1800, 'time_on': 3600, 'time_off': 7200},
                    True,
                ),
                ('GET', '192.168.1.23', 'led/movie/config', True),
                ('GET', '192.168.1.23', 'movies', True),
                ('GET', '192.168.1.23', 'led/movies/current', True),
                ('GET', '192.168.1.23', 'playlist', True),
                ('GET', '192.168.1.23', 'playlist/current', True),
                ('GET', '192.168.1.23', 'network/scan', True),
                ('GET', '192.168.1.23', 'network/scan_results', True),
                ('GET', '192.168.1.23', 'network/status', True),
                ('GET', '192.168.1.23', 'mqtt/config', True),
                ('GET', '192.168.1.23', 'mic/config', True),
                ('GET', '192.168.1.23', 'mic/sample', True),
                ('GET', '192.168.1.23', 'music/drivers', True),
                ('GET', '192.168.1.23', 'music/drivers/sets', True),
                ('GET', '192.168.1.23', 'music/drivers/sets/current', True),
            ],
        )

    def test_set_off_mode_uses_led_mode_off(self) -> None:
        calls = []

        def post(
            self: TwinklyClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append((self.host, path, body, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        client = TwinklyClient(host='192.168.1.23')

        with patch.object(TwinklyClient, 'post', post):
            response = client.set_off_mode()

        self.assertEqual(response.data, {'code': 1000})
        self.assertEqual(
            calls,
            [('192.168.1.23', 'led/mode', {'mode': 'off'}, True)],
        )


class SessionTests(unittest.TestCase):
    def test_twinkly_request_label_includes_method_path_and_host(self) -> None:
        self.assertEqual(
            session.twinkly_request_label('get', 'fw/version', '192.168.1.23'),
            f'GET {TWINKLY_API_PREFIX}/fw/version on 192.168.1.23',
        )

    def test_set_mac_from_gestalt_updates_client(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        result = session.set_mac_from_gestalt(client, {'mac': 'AA:BB:CC:DD:EE:FF'})

        self.assertTrue(result)
        self.assertEqual(client.mac, 'AA:BB:CC:DD:EE:FF')

    def test_led_count_from_gestalt_returns_positive_ints(self) -> None:
        self.assertEqual(session.led_count_from_gestalt({'number_of_led': 250}), 250)
        self.assertIsNone(session.led_count_from_gestalt({'number_of_led': 0}))
        self.assertIsNone(session.led_count_from_gestalt({'number_of_led': '250'}))

    def test_turn_off_with_retry_uses_twinkly_label(self) -> None:
        labels = []

        def set_off_mode(
            client: TwinklyClient,
            retry: RetryConfig,
            label: str,
        ) -> TwinklyResponse:
            labels.append(label)
            return TwinklyResponse(http_status=200, data={'code': 1000})

        with patch('lyte.twinkly.session.set_off_mode_with_retry', set_off_mode):
            result = session.turn_off_with_retry(
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
            )

        self.assertTrue(result)
        self.assertEqual(
            labels, [f'POST {TWINKLY_API_PREFIX}/led/mode on 192.168.1.23']
        )


class PackageDiagnosticTests(unittest.TestCase):
    def test_device_info_preserves_raw_gestalt_and_extracts_fields(self) -> None:
        raw = {
            'device_name': 'Twinkly',
            'product_name': 'Twinkly',
            'product_code': 'TWI190SPP',
            'hw_id': '1cc190',
            'fw_family': 'G',
            'mac': 'AA',
            'uuid': 'UUID',
            'led_profile': 'RGBW',
            'number_of_led': 190,
            'bytes_per_led': 4,
            'frame_rate': 28.57,
            'movie_capacity': 992,
            'max_supported_led': 1200,
            'unknown': 'preserved',
        }

        device = diagnostic.TwinklyDeviceInfo.from_gestalt(raw)

        self.assertEqual(device.raw, raw)
        self.assertEqual(device.device_name, 'Twinkly')
        self.assertEqual(device.product_code, 'TWI190SPP')
        self.assertEqual(device.hardware_id, '1cc190')
        self.assertEqual(device.firmware_family, 'G')
        self.assertEqual(device.led_count, 190)
        self.assertEqual(device.bytes_per_led, 4)
        self.assertEqual(device.frame_rate, 28.57)

    def test_read_endpoint_reports_unsupported_endpoint(self) -> None:
        def request() -> dict[str, object]:
            raise UnsupportedEndpointError('summary', 'Resource not found.')

        report = diagnostic.read_endpoint(
            TwinklyClient(host='192.168.1.23'),
            RetryConfig(attempts=1, delay=0, backoff=1),
            'summary',
            'GET',
            'summary',
            request,
        )

        self.assertEqual(
            report,
            diagnostic.TwinklyEndpointReport(
                name='summary',
                path='summary',
                supported=False,
                error='Resource not found.',
            ),
        )

    def test_authenticated_reports_probe_device_name_summary_and_echo(self) -> None:
        calls = []

        def get_layout_full(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'layout'))
            return TwinklyResponse(
                http_status=200, data={'code': 1000, 'coordinates': []}
            )

        def get_led_config(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'led-config'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'strings': []})

        def get_led_mode(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'mode'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'mode': 'off'})

        def get_timer(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'timer'))
            return TwinklyResponse(
                http_status=200,
                data={'code': 1000, 'time_now': 1800, 'time_on': -1, 'time_off': -1},
            )

        def get_movie_config(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'movie-config'))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def get_movies(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'movies'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'entries': []})

        def get_current_movie(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'current-movie'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'id': 0})

        def get_playlist(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'playlist'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'entries': []})

        def get_current_playlist_entry(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'current-playlist-entry'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'id': 0})

        def get_network_status(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'network-status'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'mode': 1})

        def get_network_scan(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'network-scan'))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def get_network_scan_results(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'network-scan-results'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'networks': []})

        def get_mqtt_config(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'mqtt-config'))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def get_mic_config(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'mic-config'))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def get_mic_sample(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'mic-sample'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'sample': 0})

        def get_music_drivers(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'music-drivers'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'drivers': []})

        def get_music_driver_sets(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'music-driver-sets'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'sets': []})

        def get_current_music_driver_set(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'current-music-driver-set'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'id': 0})

        def get_led_color(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'color'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'red': 1})

        def get_effects(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'effects'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'effects': []})

        def get_current_effect(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'current-effect'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'effect_id': 0})

        def get_brightness(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'brightness'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'value': 75})

        def get_saturation(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'saturation'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'value': 80})

        def get_device_name(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'device_name'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'name': 'Tree'})

        def get_summary(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'summary'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'leds': 250})

        def echo(self: TwinklyClient, body: dict[str, object]) -> TwinklyResponse:
            calls.append(('POST', 'echo', body))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'json': body})

        methods = {
            'get_layout_full': get_layout_full,
            'get_led_config': get_led_config,
            'get_led_mode': get_led_mode,
            'get_timer': get_timer,
            'get_movie_config': get_movie_config,
            'get_movies': get_movies,
            'get_current_movie': get_current_movie,
            'get_playlist': get_playlist,
            'get_current_playlist_entry': get_current_playlist_entry,
            'get_network_status': get_network_status,
            'get_network_scan': get_network_scan,
            'get_network_scan_results': get_network_scan_results,
            'get_mqtt_config': get_mqtt_config,
            'get_mic_config': get_mic_config,
            'get_mic_sample': get_mic_sample,
            'get_music_drivers': get_music_drivers,
            'get_music_driver_sets': get_music_driver_sets,
            'get_current_music_driver_set': get_current_music_driver_set,
            'get_led_color': get_led_color,
            'get_effects': get_effects,
            'get_current_effect': get_current_effect,
            'get_brightness': get_brightness,
            'get_saturation': get_saturation,
            'get_device_name': get_device_name,
            'get_summary': get_summary,
            'echo': echo,
        }
        with ExitStack() as stack:
            for name, method in methods.items():
                stack.enter_context(patch.object(TwinklyClient, name, method))
            reports = diagnostic.authenticated_reports(
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
            )

        self.assertEqual(
            [i.name for i in reports],
            [
                'layout',
                'led-config',
                'mode',
                'timer',
                'movie-config',
                'movies',
                'current-movie',
                'playlist',
                'current-playlist-entry',
                'network-status',
                'network-scan',
                'network-scan-results',
                'mqtt-config',
                'mic-config',
                'mic-sample',
                'music-drivers',
                'music-driver-sets',
                'current-music-driver-set',
                'color',
                'effects',
                'current-effect',
                'brightness',
                'saturation',
                'device-name',
                'summary',
                'echo',
            ],
        )
        self.assertEqual(
            calls,
            [
                ('GET', 'layout'),
                ('GET', 'led-config'),
                ('GET', 'mode'),
                ('GET', 'timer'),
                ('GET', 'movie-config'),
                ('GET', 'movies'),
                ('GET', 'current-movie'),
                ('GET', 'playlist'),
                ('GET', 'current-playlist-entry'),
                ('GET', 'network-status'),
                ('GET', 'network-scan'),
                ('GET', 'network-scan-results'),
                ('GET', 'mqtt-config'),
                ('GET', 'mic-config'),
                ('GET', 'mic-sample'),
                ('GET', 'music-drivers'),
                ('GET', 'music-driver-sets'),
                ('GET', 'current-music-driver-set'),
                ('GET', 'color'),
                ('GET', 'effects'),
                ('GET', 'current-effect'),
                ('GET', 'brightness'),
                ('GET', 'saturation'),
                ('GET', 'device_name'),
                ('GET', 'summary'),
                ('POST', 'echo', {'message': 'lyte diagnostic'}),
            ],
        )

    def test_run_diagnostic_reports_read_only_device_state(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{DIAGNOSTIC}.discover_host', return_value='192.168.1.23'),
            patch(f'{DIAGNOSTIC}.TwinklyClient', return_value=client),
            patch(
                f'{DIAGNOSTIC}.read_endpoint',
                side_effect=(
                    diagnostic.TwinklyEndpointReport(
                        name='gestalt',
                        path='gestalt',
                        supported=True,
                        data={'device_name': 'Tree', 'mac': 'AA', 'number_of_led': 250},
                    ),
                    diagnostic.TwinklyEndpointReport(
                        name='firmware',
                        path='fw/version',
                        supported=True,
                        data={'version': '1.0'},
                    ),
                    diagnostic.TwinklyEndpointReport(
                        name='status',
                        path='status',
                        supported=True,
                        data={'mode': 'rt'},
                    ),
                ),
            ),
            patch(f'{DIAGNOSTIC}.session.authenticate_device', return_value=object()),
            patch(f'{DIAGNOSTIC}.authenticated_reports', return_value=()),
            patch(
                f'{DIAGNOSTIC}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = diagnostic.run_diagnostic(diagnostic.DiagnosticConfig())

        self.assertEqual(result, 0)
        self.assertEqual(client.mac, 'AA')
        turn_off.assert_called_once()
        self.assertIn('Device name: Tree', output.getvalue())
        self.assertIn("firmware: {'version': '1.0'}", output.getvalue())

    def test_diagnostic_command_runs_twinkly_diagnostic_by_default(self) -> None:
        with patch(f'{DIAGNOSTIC}.run_diagnostic', return_value=0) as run_diagnostic:
            result = diagnostic.run_diagnostic_command(
                diagnostic.DiagnosticCommandConfig(host='192.168.1.23', attempts=2)
            )

        self.assertEqual(result, 0)
        config = run_diagnostic.call_args.args[0]
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(config.attempts, 2)

    def test_diagnostic_command_runs_realtime_diagnostic_when_requested(self) -> None:
        with patch(f'{DIAGNOSTIC}.run_realtime_diagnostic', return_value=0) as realtime:
            result = diagnostic.run_diagnostic_command(
                diagnostic.DiagnosticCommandConfig(
                    realtime=True,
                    led_count=10,
                    pause=0.1,
                )
            )

        self.assertEqual(result, 0)
        config = realtime.call_args.args[0]
        self.assertEqual(config.led_count, 10)
        self.assertEqual(config.pause, 0.1)
        self.assertEqual(config.discovery_timeout, 0.1)


class TwinklyControlTests(unittest.TestCase):
    def test_output_control_accepts_string_values_from_device(self) -> None:
        control = output.OutputControl.from_response({'mode': 'enabled', 'value': '75'})

        self.assertEqual(control.mode, 'enabled')
        self.assertEqual(control.type, 'A')
        self.assertEqual(control.value, 75)

    def test_output_control_request_body_uses_documented_shape(self) -> None:
        self.assertEqual(
            output.OutputControl(value=80).request_body(),
            {'mode': 'enabled', 'type': 'A', 'value': 80},
        )

    def test_layout_model_accepts_documented_shape(self) -> None:
        twinkly_layout = layout.TwinklyLayout.from_response(
            {
                'aspectXY': 1,
                'aspectXZ': 2,
                'coordinates': [{'x': 1.0, 'y': 2.0, 'z': 3.0}],
                'source': '3d',
                'synthesized': False,
                'uuid': '00000000-0000-0000-0000-000000000000',
            }
        )

        self.assertEqual(
            twinkly_layout.request_body(),
            {
                'aspectXY': 1,
                'aspectXZ': 2,
                'coordinates': [{'x': 1.0, 'y': 2.0, 'z': 3.0}],
                'source': '3d',
                'synthesized': False,
                'uuid': '00000000-0000-0000-0000-000000000000',
            },
        )

    def test_timer_model_uses_seconds_after_midnight(self) -> None:
        twinkly_timer = timer.TwinklyTimer.from_response(
            {'time_now': 1800, 'time_on': -1, 'time_off': 7200, 'code': 1000}
        )

        self.assertEqual(twinkly_timer.time_now, 1800)
        self.assertEqual(twinkly_timer.time_on, -1)
        self.assertEqual(twinkly_timer.time_off, 7200)
        self.assertEqual(
            twinkly_timer.request_body(),
            {'time_on': -1, 'time_off': 7200, 'time_now': 1800},
        )

    def test_timer_request_can_omit_current_time(self) -> None:
        self.assertEqual(
            timer.TwinklyTimer(time_on=3600, time_off=7200).request_body(),
            {'time_on': 3600, 'time_off': 7200},
        )

    def test_read_output_control_dispatches_by_kind(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch.object(
                TwinklyClient,
                'get_brightness',
                return_value=TwinklyResponse(
                    http_status=200,
                    data={'mode': 'enabled', 'value': 75},
                ),
            ) as get_brightness,
            patch.object(
                TwinklyClient,
                'get_saturation',
                return_value=TwinklyResponse(
                    http_status=200,
                    data={'mode': 'enabled', 'value': 80},
                ),
            ) as get_saturation,
        ):
            brightness = output.read_output_control(client, 'brightness')
            saturation = output.read_output_control(client, 'saturation')

        self.assertEqual(brightness.value, 75)
        self.assertEqual(saturation.value, 80)
        get_brightness.assert_called_once()
        get_saturation.assert_called_once()

    def test_write_output_control_dispatches_by_kind(self) -> None:
        client = TwinklyClient(host='192.168.1.23')
        control = output.OutputControl(value=90)

        with (
            patch.object(TwinklyClient, 'set_brightness') as set_brightness,
            patch.object(TwinklyClient, 'set_saturation') as set_saturation,
        ):
            output.write_output_control(client, 'brightness', control)
            output.write_output_control(client, 'saturation', control)

        set_brightness.assert_called_once_with(
            {'mode': 'enabled', 'type': 'A', 'value': 90}
        )
        set_saturation.assert_called_once_with(
            {'mode': 'enabled', 'type': 'A', 'value': 90}
        )

    def test_run_output_control_get_reports_current_value(self) -> None:
        stream = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch(
                f'{OUTPUT}.read_output_control',
                return_value=output.OutputControl(value=75),
            ),
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', stream),
        ):
            result = output.run_output_control(
                diagnostic.DiagnosticConfig(),
                'brightness',
                'get',
                None,
            )

        self.assertEqual(result, 0)
        turn_off.assert_called_once()
        self.assertIn('[brightness] mode=enabled type=A value=75', stream.getvalue())

    def test_run_output_control_set_writes_value(self) -> None:
        stream = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch(f'{OUTPUT}.write_output_control') as write_output_control,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', stream),
        ):
            result = output.run_output_control(
                diagnostic.DiagnosticConfig(),
                'saturation',
                'set',
                80,
            )

        self.assertEqual(result, 0)
        turn_off.assert_called_once()
        write_output_control.assert_called_once_with(
            client,
            'saturation',
            output.OutputControl(value=80),
        )
        self.assertIn(
            '[saturation] set mode=enabled type=A value=80',
            stream.getvalue(),
        )

    def test_run_mode_control_sets_mode_then_turns_off(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(TwinklyClient, 'set_led_mode') as set_led_mode,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = mode.run_mode_control(diagnostic.DiagnosticConfig(), 'set', 'demo')

        self.assertEqual(result, 0)
        set_led_mode.assert_called_once_with({'mode': 'demo'})
        turn_off.assert_called_once()

    def test_run_color_control_sets_rgb_then_turns_off(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(TwinklyClient, 'set_led_color') as set_led_color,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = mode.run_color_control(
                diagnostic.DiagnosticConfig(), 'set', 1, 2, 3
            )

        self.assertEqual(result, 0)
        set_led_color.assert_called_once_with(
            {'mode': 'rgb', 'red': 1, 'green': 2, 'blue': 3}
        )
        turn_off.assert_called_once()

    def test_run_effect_control_sets_current_effect_then_turns_off(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(TwinklyClient, 'set_current_effect') as set_current_effect,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = mode.run_effect_control(
                diagnostic.DiagnosticConfig(), 'set-current', 4
            )

        self.assertEqual(result, 0)
        set_current_effect.assert_called_once_with({'effect_id': 4})
        turn_off.assert_called_once()

    def test_run_layout_control_exports_layout_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layout.json'
            with (
                patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
                patch(f'{COMMAND}.TwinklyClient', return_value=client),
                patch(f'{COMMAND}.prepare_authenticated_client'),
                patch.object(
                    TwinklyClient,
                    'get_layout_full',
                    return_value=TwinklyResponse(
                        http_status=200,
                        data={'source': '3d', 'coordinates': []},
                    ),
                ),
                patch(
                    f'{COMMAND}.session.turn_off_with_retry', return_value=True
                ) as turn_off,
                patch('sys.stdout', output),
            ):
                result = layout.run_layout_control(
                    diagnostic.DiagnosticConfig(), 'export', path
                )

            self.assertEqual(result, 0)
            self.assertEqual(
                json.loads(path.read_text()),
                {'coordinates': [], 'source': '3d'},
            )
            turn_off.assert_called_once()
            self.assertIn('[layout] exported', output.getvalue())

    def test_run_layout_control_uploads_layout_then_turns_off(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layout.json'
            path.write_text(
                json.dumps(
                    {
                        'aspectXY': 0,
                        'aspectXZ': 0,
                        'coordinates': [{'x': 1, 'y': 2, 'z': 3}],
                        'source': '3d',
                        'synthesized': False,
                    }
                )
            )
            with (
                patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
                patch(f'{COMMAND}.TwinklyClient', return_value=client),
                patch(f'{COMMAND}.prepare_authenticated_client'),
                patch.object(TwinklyClient, 'set_layout_full') as set_layout_full,
                patch(
                    f'{COMMAND}.session.turn_off_with_retry', return_value=True
                ) as turn_off,
                patch('sys.stdout', new_callable=io.StringIO),
            ):
                result = layout.run_layout_control(
                    diagnostic.DiagnosticConfig(), 'upload', path
                )

        self.assertEqual(result, 0)
        set_layout_full.assert_called_once_with(
            {
                'aspectXY': 0,
                'aspectXZ': 0,
                'coordinates': [{'x': 1.0, 'y': 2.0, 'z': 3.0}],
                'source': '3d',
                'synthesized': False,
            }
        )
        turn_off.assert_called_once()

    def test_run_led_config_control_sets_json_config_then_turns_off(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'strings': [{'first_led_id': 0}]}))
            with (
                patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
                patch(f'{COMMAND}.TwinklyClient', return_value=client),
                patch(f'{COMMAND}.prepare_authenticated_client'),
                patch.object(TwinklyClient, 'set_led_config') as set_led_config,
                patch(
                    f'{COMMAND}.session.turn_off_with_retry', return_value=True
                ) as turn_off,
                patch('sys.stdout', new_callable=io.StringIO),
            ):
                result = layout.run_led_config_control(
                    diagnostic.DiagnosticConfig(), 'set', path
                )

        self.assertEqual(result, 0)
        set_led_config.assert_called_once_with({'strings': [{'first_led_id': 0}]})
        turn_off.assert_called_once()

    def test_run_timer_control_reads_timer_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_timer',
                return_value=TwinklyResponse(
                    http_status=200,
                    data={'time_now': 1800, 'time_on': -1, 'time_off': 7200},
                ),
            ),
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = timer.run_timer_control(
                diagnostic.DiagnosticConfig(), 'get', None, None, None
            )

        self.assertEqual(result, 0)
        self.assertIn(
            '[timer] time_now=1800 time_on=-1 time_off=7200',
            output.getvalue(),
        )
        turn_off.assert_called_once()

    def test_run_timer_control_sets_timer_then_turns_off(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(TwinklyClient, 'set_timer') as set_timer,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = timer.run_timer_control(
                diagnostic.DiagnosticConfig(), 'set', 3600, 7200, 1800
            )

        self.assertEqual(result, 0)
        set_timer.assert_called_once_with(
            {'time_on': 3600, 'time_off': 7200, 'time_now': 1800}
        )
        turn_off.assert_called_once()

    def test_run_movie_control_reads_current_movie_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_current_movie',
                return_value=TwinklyResponse(http_status=200, data={'id': 0}),
            ) as get_current_movie,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = media.run_movie_control(diagnostic.DiagnosticConfig(), 'current')

        self.assertEqual(result, 0)
        get_current_movie.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[movie] current {'id': 0}", output.getvalue())

    def test_run_playlist_control_reads_playlist_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_playlist',
                return_value=TwinklyResponse(http_status=200, data={'entries': []}),
            ) as get_playlist,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = media.run_playlist_control(diagnostic.DiagnosticConfig(), 'list')

        self.assertEqual(result, 0)
        get_playlist.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[playlist] list {'entries': []}", output.getvalue())

    def test_run_network_control_reads_status_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_network_status',
                return_value=TwinklyResponse(http_status=200, data={'mode': 1}),
            ) as get_network_status,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = networking.run_network_control(
                diagnostic.DiagnosticConfig(), 'status'
            )

        self.assertEqual(result, 0)
        get_network_status.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[network] status {'mode': 1}", output.getvalue())

    def test_run_mqtt_control_reads_config_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_mqtt_config',
                return_value=TwinklyResponse(http_status=200, data={'enabled': False}),
            ) as get_mqtt_config,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = inputs.run_mqtt_control(diagnostic.DiagnosticConfig(), 'config')

        self.assertEqual(result, 0)
        get_mqtt_config.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[mqtt] config {'enabled': False}", output.getvalue())

    def test_run_mic_control_reads_sample_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_mic_sample',
                return_value=TwinklyResponse(http_status=200, data={'sample': 3}),
            ) as get_mic_sample,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = inputs.run_mic_control(diagnostic.DiagnosticConfig(), 'sample')

        self.assertEqual(result, 0)
        get_mic_sample.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[mic] sample {'sample': 3}", output.getvalue())

    def test_run_music_control_reads_current_driver_set_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_current_music_driver_set',
                return_value=TwinklyResponse(http_status=200, data={'id': 1}),
            ) as get_current_music_driver_set,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = inputs.run_music_control(
                diagnostic.DiagnosticConfig(), 'current-driver-set'
            )

        self.assertEqual(result, 0)
        get_current_music_driver_set.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[music] current-driver-set {'id': 1}", output.getvalue())


class RuntimeTests(unittest.TestCase):
    def test_read_device_led_count_uses_configured_count_after_reading_gestalt(
        self,
    ) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with patch(
            'lyte.twinkly.session.read_gestalt',
            return_value={'mac': 'AA', 'number_of_led': 250},
        ):
            led_count, gestalt = session.read_device_led_count(
                client,
                RetryConfig(attempts=1, delay=0, backoff=1),
                100,
                'read',
            )

        self.assertEqual(led_count, 100)
        self.assertEqual(gestalt, {'mac': 'AA', 'number_of_led': 250})
        self.assertEqual(client.mac, 'AA')

    def test_read_device_led_count_detects_count_from_gestalt(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with patch(
            'lyte.twinkly.session.read_gestalt',
            return_value={'mac': 'AA', 'number_of_led': 250},
        ):
            led_count, _gestalt = session.read_device_led_count(
                client,
                RetryConfig(attempts=1, delay=0, backoff=1),
                None,
                'read',
            )

        self.assertEqual(led_count, 250)

    def test_send_authenticated_frame_returns_none_without_token(self) -> None:
        frame = solid_rgb_frame(1, 255, 0, 0)

        sent = session.send_authenticated_frame(
            TwinklyClient(host='192.168.1.23'),
            '192.168.1.23',
            frame,
            RetryConfig(attempts=1, delay=0, backoff=1),
            'send',
        )

        self.assertIsNone(sent)


class LoggingTests(unittest.TestCase):
    def test_logging_is_disabled_by_default(self) -> None:
        self.assertFalse(LOGGING)

    def test_error_logging_is_always_displayed(self) -> None:
        output = io.StringIO()

        with patch('sys.stderr', output):
            log_error('failure')

        self.assertEqual(output.getvalue(), 'failure\n')

    def test_regular_logging_is_hidden_by_default(self) -> None:
        output = io.StringIO()

        with patch('sys.stdout', output):
            log('hidden')

        self.assertEqual(output.getvalue(), '')

    def test_status_logging_is_always_displayed(self) -> None:
        output = io.StringIO()

        with patch('sys.stdout', output):
            log_status('visible')

        self.assertEqual(output.getvalue(), 'visible\n')


class HamiltonianTests(unittest.TestCase):
    def test_next_hamiltonian_matches_loop_special_case(self) -> None:
        self.assertEqual(hamiltonian.next_hamiltonian(4, 1, 0, 0), (0, 0, 0))
        self.assertEqual(hamiltonian.next_hamiltonian(4, 1, 0, 1), (2, 0, 1))

    def test_counter_produces_scaled_rgb_values(self) -> None:
        counter = hamiltonian.HamiltonianCounter(n=4)

        self.assertEqual(counter.next_color(), (0, 0, 0))
        self.assertEqual(counter.next_color(), (0, 0, 64))
        self.assertEqual(counter.next_color(), (0, 0, 128))

    def test_hamiltonian_colors_generates_one_full_cycle(self) -> None:
        colors = list(hamiltonian.hamiltonian_colors(n=4))

        self.assertEqual(len(colors), 64)
        self.assertEqual(colors[:3], [(0, 0, 0), (0, 0, 64), (0, 0, 128)])

    def test_counter_supports_order_and_inversion(self) -> None:
        counter = hamiltonian.HamiltonianCounter(n=4, order='bgr', inverted='r')

        self.assertEqual(counter.next_color(), (192, 0, 0))
        self.assertEqual(counter.next_color(), (128, 0, 0))

    def test_parse_order_rejects_invalid_orders(self) -> None:
        with self.assertRaises(ValueError):
            hamiltonian.parse_order('rrg')

    def test_hamiltonian_returns_one_rgb_triplet_per_led(self) -> None:
        animation = hamiltonian.Hamiltonian(n=4, speed=4)
        device, state = initial_state(animation, 3)
        state.fps = 4

        npt.assert_array_equal(
            render(animation, device, state),
            np.zeros((3, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(animation, device, state),
            np.zeros((3, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[0, 0, 0], [0, 0, 0], [0, 0, 64]], dtype=np.uint8),
        )


class RandomWalkTests(unittest.TestCase):
    def test_perturb_matches_original_random_step(self) -> None:
        generator = random.Random(1)

        self.assertAlmostEqual(perturb(0, 5, (0, 10), generator), -3.656357558875988)
        self.assertAlmostEqual(perturb(9, 5, (0, 10), generator), 5.525662630627673)

    def test_next_color_returns_current_color_before_advancing(self) -> None:
        walk = RandomWalk(color=(10.0, 20.0, 30.0), variance=0)
        device = animation.Device(led_count=1)
        state = walk.initial_state(device)

        self.assertEqual(walk.next_color(state, 0), (10.0, 20.0, 30.0))
        self.assertEqual(walk.next_color(state, 1), (10.0, 20.0, 30.0))

    def test_render_streams_walk_through_leds(self) -> None:
        walk = RandomWalk(speed=1, color=(10.0, 20.0, 30.0), variance=0)
        device, state = initial_state(walk, 2)
        state.fps = 1

        npt.assert_array_equal(
            render(walk, device, state),
            np.zeros((2, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(walk, device, state),
            np.array([[0, 0, 0], [10, 20, 30]], dtype=np.uint8),
        )


class BiblioPixelTests(unittest.TestCase):
    def test_color_fill_fills_all_leds(self) -> None:
        animation = bibliopixel.ColorFill(color=(1, 2, 3))
        device, state = initial_state(animation, 3)

        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[1, 2, 3], [1, 2, 3], [1, 2, 3]], dtype=np.uint8),
        )

    def test_color_chase_moves_lit_window(self) -> None:
        chase = bibliopixel.ColorChase(color=(9, 8, 7), width=2)
        device, state = initial_state(chase, 5)

        npt.assert_array_equal(
            render(chase, device, state),
            np.array(
                [[9, 8, 7], [9, 8, 7], [0, 0, 0], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(chase, device, state),
            np.array(
                [[0, 0, 0], [9, 8, 7], [9, 8, 7], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_color_wipe_preserves_previous_lit_leds(self) -> None:
        wipe = bibliopixel.ColorWipe(color=(1, 2, 3))
        device, state = initial_state(wipe, 4)

        npt.assert_array_equal(
            render(wipe, device, state),
            np.array(
                [[1, 2, 3], [0, 0, 0], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(wipe, device, state),
            np.array(
                [[1, 2, 3], [1, 2, 3], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_alternates_flips_each_frame(self) -> None:
        source = bibliopixel.Alternates(color1=(1, 1, 1), color2=(2, 2, 2))
        device, state = initial_state(source, 4)

        npt.assert_array_equal(
            render(source, device, state),
            np.array(
                [[2, 2, 2], [1, 1, 1], [2, 2, 2], [1, 1, 1]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(source, device, state),
            np.array(
                [[1, 1, 1], [2, 2, 2], [1, 1, 1], [2, 2, 2]],
                dtype=np.uint8,
            ),
        )

    def test_color_pattern_repeats_color_widths(self) -> None:
        pattern = bibliopixel.ColorPattern(
            colors=((1, 0, 0), (0, 2, 0), (0, 0, 3)),
            width=2,
        )
        device, state = initial_state(pattern, 6)

        npt.assert_array_equal(
            render(pattern, device, state),
            np.array(
                [[1, 0, 0], [1, 0, 0], [0, 2, 0], [0, 2, 0], [0, 0, 3], [0, 0, 3]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(pattern, device, state),
            np.array(
                [[1, 0, 0], [0, 2, 0], [0, 2, 0], [0, 0, 3], [0, 0, 3], [1, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_color_fade_scales_color_across_span(self) -> None:
        fade = bibliopixel.ColorFade(
            colors=((10, 20, 30),),
            level_step=225,
            start=1,
            end=2,
        )
        device, state = initial_state(fade, 4)

        npt.assert_array_equal(
            render(fade, device, state),
            np.array(
                [[0, 0, 0], [1, 2, 4], [1, 2, 4], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_party_mode_alternates_color_and_blank_frames(self) -> None:
        party = bibliopixel.PartyMode(colors=((1, 2, 3), (4, 5, 6)))
        device, state = initial_state(party, 2)

        npt.assert_array_equal(
            render(party, device, state),
            np.array([[1, 2, 3], [1, 2, 3]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(party, device, state),
            np.zeros((2, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(party, device, state),
            np.array([[4, 5, 6], [4, 5, 6]], dtype=np.uint8),
        )

    def test_fire_flies_lights_seeded_random_pixels(self) -> None:
        source = bibliopixel.FireFlies(
            colors=((1, 2, 3),),
            width=2,
            count=1,
            seed=1,
        )
        device, state = initial_state(source, 5)

        frame = render(source, device, state)

        self.assertEqual(frame.shape, (5, 3))
        self.assertGreaterEqual(np.count_nonzero(frame[:, 0]), 1)
        self.assertLessEqual(np.count_nonzero(frame[:, 0]), 2)

    def test_saber_blade_extends_then_retracts(self) -> None:
        saber = bibliopixel.SaberBlade(colors=((1, 2, 3),), speed=1)
        device, state = initial_state(saber, 3)

        npt.assert_array_equal(
            render(saber, device, state),
            np.zeros((3, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(saber, device, state),
            np.array([[1, 2, 3], [0, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )

    def test_rainbows_generate_wheel_frames(self) -> None:
        source = bibliopixel.Rainbow()
        cycle = bibliopixel.RainbowCycle()
        device, state = initial_state(source, 3)
        cycle_device, cycle_state = initial_state(cycle, 3)

        npt.assert_array_equal(
            render(source, device, state),
            np.array([[255, 0, 0], [252, 3, 0], [249, 6, 0]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(cycle, cycle_device, cycle_state),
            np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.uint8),
        )

    def test_linear_rainbow_fills_progressively(self) -> None:
        source = bibliopixel.LinearRainbow()
        device, state = initial_state(source, 3)

        npt.assert_array_equal(
            render(source, device, state),
            np.array([[255, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(source, device, state),
            np.array([[252, 3, 0], [252, 3, 0], [0, 0, 0]], dtype=np.uint8),
        )

    def test_halves_rainbow_expands_from_center(self) -> None:
        source = bibliopixel.HalvesRainbow()
        device, state = initial_state(source, 5)

        npt.assert_array_equal(
            render(source, device, state),
            np.array(
                [[0, 0, 0], [0, 0, 0], [255, 0, 0], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(source, device, state),
            np.array(
                [[0, 0, 0], [240, 15, 0], [255, 0, 0], [240, 15, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_larson_scanner_bounces_lit_pixel(self) -> None:
        scanner = bibliopixel.LarsonScanner(color=(1, 2, 3), tail=0)
        device, state = initial_state(scanner, 3)

        npt.assert_array_equal(
            render(scanner, device, state),
            np.array([[1, 2, 3], [0, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(scanner, device, state),
            np.array([[0, 0, 0], [1, 2, 3], [0, 0, 0]], dtype=np.uint8),
        )

    def test_pulse_starts_when_chance_always_hits(self) -> None:
        source = bibliopixel.Pulse(
            colors=((10, 20, 30),),
            tail=0,
            chance=100,
            min_speed=1,
            max_speed=2,
            seed=1,
        )
        device, state = initial_state(source, 4)

        frame = render(source, device, state)

        self.assertGreater(np.count_nonzero(frame), 0)

    def test_pixel_ping_pong_fades_previous_pixels(self) -> None:
        ping_pong = bibliopixel.PixelPingPong(color=(10, 0, 0), fade_delay=1)
        device, state = initial_state(ping_pong, 3)

        npt.assert_array_equal(
            render(ping_pong, device, state),
            np.array([[10, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(ping_pong, device, state),
            np.array([[0, 0, 0], [10, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )

    def test_searchlights_blend_moving_beams(self) -> None:
        source = bibliopixel.Searchlights(
            colors=((10, 0, 0), (0, 20, 0), (0, 0, 30)),
            tail=0,
            seed=1,
        )
        device, state = initial_state(source, 8)

        frame = render(source, device, state)

        self.assertEqual(frame.shape, (8, 3))
        self.assertGreater(np.count_nonzero(frame), 0)

    def test_wave_generates_sine_colored_frame(self) -> None:
        source = bibliopixel.Wave(color=(10, 20, 30), cycles=1)
        device, state = initial_state(source, 3)

        npt.assert_array_equal(
            render(source, device, state),
            np.array([[10, 20, 30], [10, 20, 30], [10, 20, 30]], dtype=np.uint8),
        )

    def test_twinkle_lights_seeded_random_pixel(self) -> None:
        source = bibliopixel.Twinkle(
            colors=((10, 20, 30),),
            density=100,
            speed=10,
            seed=1,
        )
        device, state = initial_state(source, 4)

        frame = render(source, device, state)

        self.assertGreater(np.count_nonzero(frame), 0)

    def test_white_twinkle_uses_white_pixels(self) -> None:
        source = bibliopixel.WhiteTwinkle(density=100, speed=10, seed=1)
        device, state = initial_state(source, 4)

        frame = render(source, device, state)

        self.assertGreater(np.count_nonzero(frame), 0)
        self.assertTrue(np.all(frame[frame > 0] == int(np.max(frame))))


class PreviewTests(unittest.TestCase):
    def test_layout_accepts_explicit_coords(self) -> None:
        layout = Layout(coords=[[0.0, 0.0], [1.0, 0.5]])

        self.assertEqual(layout.points(), [[0.0, 0.0], [1.0, 0.5]])

    def test_layout_generates_grid_from_dims_and_spacing(self) -> None:
        layout = Layout(dims=[2, 3], spacing=[2.0, 3.0])

        self.assertEqual(
            layout.points(),
            [
                [0.0, 0.0],
                [2.0, 0.0],
                [4.0, 0.0],
                [0.0, 3.0],
                [2.0, 3.0],
                [4.0, 3.0],
            ],
        )

    def test_layout_requires_exactly_one_coordinate_source(self) -> None:
        with self.assertRaises(ValueError):
            Layout()
        with self.assertRaises(ValueError):
            Layout(coords=[[0.0, 0.0]], dims=[1, 1])

    def test_animation_document_embeds_base64_frames(self) -> None:
        html = document.animation_document(
            bibliopixel.ColorFill(color=(1, 2, 3)),
            Layout(name='preview', dims=[1, 2]),
            fps=2,
            duration=1,
            led_size=2.5,
        )

        data = preview_data(html)

        self.assertEqual(data['name'], 'preview')
        self.assertEqual(data['coords'], [[0.0, 0.0], [1.0, 0.0]])
        self.assertEqual(data['ledSize'], 2.5)
        frames = data['frames']
        if not isinstance(frames, list):
            self.fail('frames must be a list')
        first_frame = frames[0]
        if not isinstance(first_frame, str):
            self.fail('frames must contain strings')
        self.assertEqual(len(frames), 2)
        self.assertEqual(
            base64.b64decode(first_frame),
            bytes([1, 2, 3, 1, 2, 3]),
        )

    def test_render_animation_html_writes_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preview.html'

            document.render_animation_html(
                bibliopixel.ColorFill(color=(1, 2, 3)),
                Layout(coords=[[0.0, 0.0]]),
                path,
                fps=1,
                duration=1,
                led_size=3,
            )

            self.assertIn('<canvas', path.read_text())


def preview_data(document: str) -> dict[str, object]:
    start = document.index('const data = ') + len('const data = ')
    end = document.index(';\nconst canvas', start)
    return json.loads(document[start:end])


class RetryTests(unittest.TestCase):
    def test_retry_call_retries_retryable_result_failures(self) -> None:
        calls = 0

        def operation() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RetryableTestError('empty reply')
            return 'ok'

        retry = RetryConfig(
            attempts=2,
            delay=0,
            backoff=1,
            backoff_after=1,
        )

        with (
            patch('sys.stdout', new_callable=io.StringIO),
            patch(
                'sys.stderr',
                new_callable=io.StringIO,
            ),
        ):
            result = retry_call(
                'operation',
                retry,
                operation,
                (RetryableTestError,),
            )

        self.assertEqual(result, 'ok')
        self.assertEqual(calls, 2)

    def test_retry_call_delays_backoff_until_configured_attempt(self) -> None:
        calls = 0
        sleeps = []

        def operation() -> str:
            nonlocal calls
            calls += 1
            if calls < 4:
                raise RetryableTestError('empty reply')
            return 'ok'

        retry = RetryConfig(
            attempts=4,
            delay=0.01,
            backoff=2,
            backoff_after=10,
        )

        with (
            patch('sys.stdout', new_callable=io.StringIO),
            patch(
                'sys.stderr',
                new_callable=io.StringIO,
            ),
            patch('lyte.retry.time.sleep', sleeps.append),
        ):
            result = retry_call(
                'operation',
                retry,
                operation,
                (RetryableTestError,),
            )

        self.assertEqual(result, 'ok')
        self.assertEqual(sleeps, [0.01, 0.01, 0.01])

    def test_retry_call_prints_only_final_failure(self) -> None:
        def operation() -> str:
            raise RetryableTestError('empty reply')

        retry = RetryConfig(
            attempts=3,
            delay=0,
            backoff=1,
            backoff_after=1,
        )
        error_output = io.StringIO()

        with (
            patch('sys.stdout', new_callable=io.StringIO),
            patch('sys.stderr', error_output),
            patch('lyte.retry.time.sleep'),
        ):
            result = retry_call(
                'operation',
                retry,
                operation,
                (RetryableTestError,),
            )

        self.assertIsNone(result)
        self.assertNotIn('attempt 1/3', error_output.getvalue())
        self.assertNotIn('attempt 2/3', error_output.getvalue())
        self.assertIn('attempt 3/3', error_output.getvalue())


class RetryableTestError(Exception):
    pass


class DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.diagnostic = importlib.import_module('lyte.twinkly.realtime_diagnostic')

    def test_discover_one_retries_empty_discovery_attempts(self) -> None:
        calls = 0
        timeouts = []
        reported = []

        def discovery_attempt(
            sock,
            timeout: float,
            attempt: int,
            attempts: int,
            report_failure: bool,
        ):
            nonlocal calls
            calls += 1
            timeouts.append(timeout)
            reported.append(report_failure)
            if calls == 1:
                return None
            return DiscoveredDevice(ip_address='192.168.1.23', device_id='Twinkly')

        retry = RetryConfig(
            attempts=2,
            delay=0,
            backoff=1,
            backoff_after=1,
        )

        with (
            patch.object(
                self.diagnostic,
                'discovery_attempt',
                discovery_attempt,
            ),
            patch('sys.stdout', new_callable=io.StringIO),
            patch(
                'sys.stderr',
                new_callable=io.StringIO,
            ),
        ):
            host = self.diagnostic.discover_one(0.01, retry)

        self.assertEqual(host, '192.168.1.23')
        self.assertEqual(calls, 2)
        self.assertEqual(timeouts, [0.01, 0.01])
        self.assertEqual(reported, [False, True])

    def test_config_uses_slower_network_retry_defaults(self) -> None:
        config = self.diagnostic.RealtimeDiagnosticConfig()

        self.assertEqual(config.retry.attempts, 10)
        self.assertEqual(config.retry.delay, 0.5)
        self.assertEqual(config.discovery_retry.delay, 0.05)


class HamiltonianAnimationTests(unittest.TestCase):
    def test_hamiltonian_renders_rgb_frame(self) -> None:
        animation = hamiltonian.Hamiltonian(speed=64, n=4)
        device, state = initial_state(animation, 3)
        state.fps = 1

        frame = render(animation, device, state)

        self.assertEqual(frame.shape, (3, 3))
        self.assertEqual(frame.dtype, np.uint8)


class SegmentAnimationTests(unittest.TestCase):
    def test_segments_render_contiguous_frames_with_independent_states(self) -> None:
        class CountingState(animation.State):
            led_count: int

        class CountingAnimation(animation.Animation[CountingState]):
            def initial_state(self, device: animation.Device) -> CountingState:
                return CountingState(led_count=device.led_count)

            def render(
                self, device: animation.Device, state: CountingState
            ) -> NDArray[np.float32]:
                state.frame += 1
                return animation.solid_float_light_frame(
                    device.led_count,
                    (state.frame / 10, device.led_count / 10, state.fps / 100),
                )

        source = CountingAnimation()
        composite = animation.SegmentAnimation(
            segments=[
                animation.AnimationSegment(animation=source, led_count=2),
                animation.AnimationSegment(animation=source, led_count=3),
            ]
        )
        device = animation.Device(led_count=5)
        state = composite.initial_state(device)
        state.fps = 60

        npt.assert_allclose(
            composite.render(device, state),
            np.array(
                [
                    [0.1, 0.2, 0.6],
                    [0.1, 0.2, 0.6],
                    [0.1, 0.3, 0.6],
                    [0.1, 0.3, 0.6],
                    [0.1, 0.3, 0.6],
                ],
                dtype=np.float32,
            ),
        )
        self.assertIsNot(state.states[0], state.states[1])
        self.assertEqual(state.frame, 1)

        npt.assert_allclose(
            composite.render(device, state)[:, 0],
            np.full(5, 0.2, dtype=np.float32),
        )

    def test_requires_at_least_two_segments(self) -> None:
        with self.assertRaisesRegex(ValueError, 'at least two segments'):
            animation.SegmentAnimation(segments=[])

    def test_requires_segment_lengths_to_match_device(self) -> None:
        source = bibliopixel.ColorFill(color=(1, 2, 3))
        composite = animation.SegmentAnimation(
            segments=[
                animation.AnimationSegment(animation=source, led_count=2),
                animation.AnimationSegment(animation=source, led_count=3),
            ]
        )

        with self.assertRaisesRegex(ValueError, 'must total device led_count'):
            composite.initial_state(animation.Device(led_count=4))


class AnimateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = importlib.import_module('lyte.animate.playback')

    def test_build_animation_creates_hamiltonian(self) -> None:
        with patch('sys.argv', ['lyte', 'hamiltonian']):
            args = self.script.parse_args()

        animation = self.script.build_animation(args)

        self.assertIsInstance(animation, hamiltonian.Hamiltonian)

    def test_parse_args_defaults_to_random_animation(self) -> None:
        with patch('sys.argv', ['lyte']):
            args = self.script.parse_args()

        self.assertEqual(args.animation, 'random')

    def test_random_mode_uses_hamiltonian_settings(self) -> None:
        with patch('sys.argv', ['lyte']):
            args = self.script.parse_args()

        with patch(
            'lyte.animate.random_show.config.RANDOM_ANIMATIONS', ('hamiltonian',)
        ):
            segment_args = random_show.random_animation_args(
                args, random.Random(1), None
            )

        self.assertEqual(segment_args.animation, 'hamiltonian')
        self.assertEqual(segment_args.n, 256)
        self.assertEqual(segment_args.speed, 100)

    def test_random_mode_uses_exciting_random_walk_settings(self) -> None:
        with patch('sys.argv', ['lyte']):
            args = self.script.parse_args()

        with patch(
            'lyte.animate.random_show.config.RANDOM_ANIMATIONS', ('random_walk',)
        ):
            segment_args = random_show.random_animation_args(
                args, random.Random(1), None
            )

        self.assertEqual(segment_args.animation, 'random_walk')
        self.assertEqual(segment_args.speed, config.RANDOM_WALK_SPEED)
        self.assertEqual(segment_args.variance, config.RANDOM_WALK_VARIANCE)
        self.assertEqual(segment_args.bounds, config.RANDOM_WALK_BOUNDS)
        self.assertEqual(segment_args.period, config.RANDOM_WALK_PERIOD)
        self.assertTrue(segment_args.pre_fill)

    def test_random_mode_prints_selected_pattern(self) -> None:
        with patch('sys.argv', ['lyte', '--duration', '1']):
            args = self.script.parse_args()

        output = io.StringIO()

        with (
            patch(
                'lyte.animate.random_show.config.RANDOM_ANIMATIONS', ('hamiltonian',)
            ),
            patch(
                'lyte.animate.playback.build_animation',
                return_value=bibliopixel.ColorFill(),
            ),
            patch('lyte.animate.playback.run_animation_state') as run_animation_state,
            patch('lyte.animate.playback.time.monotonic', side_effect=[0, 0, 0, 2]),
            patch('sys.stdout', output),
        ):
            self.script.run_random_animations(
                args,
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                animation.Device(led_count=3),
            )

        self.assertIn('[pattern] hamiltonian', output.getvalue())
        run_animation_state.assert_called_once()

    def test_random_overlap_is_half_the_pattern_duration(self) -> None:
        self.assertEqual(random_show.random_overlap_duration(10), 5)
        self.assertEqual(random_show.random_overlap_duration(30), 15)

    def test_blend_frames_crossfades_rgb_values(self) -> None:
        current_frame = np.array([[0.0, 100 / 255, 200 / 255]], dtype=np.float32)
        next_frame = np.array([[100 / 255, 200 / 255, 0.0]], dtype=np.float32)

        npt.assert_allclose(
            animation.byte_light_frame_from_float(
                self.script.blend_frames(current_frame, next_frame, 0.25)
            ),
            np.array([[25, 125, 150]], dtype=np.uint8),
        )

    def test_crossfade_advances_both_streamers(self) -> None:
        class ConstantAnimation(animation.Animation):
            color: tuple[int, int, int]
            calls: int = 0

            def render(
                self, device: animation.Device, state: animation.State
            ) -> NDArray[np.float32]:
                state.frame += 1
                object.__setattr__(self, 'calls', self.calls + 1)
                return np.array([self.color], dtype=np.float32) / 255

        current_animation = ConstantAnimation(color=(0, 0, 0))
        next_animation = ConstantAnimation(color=(100, 200, 250))
        device = animation.Device(led_count=1)
        current_state = animation.State()
        next_state = animation.State()
        args = config.AnimateConfig(fps=1, animation='color_fill')
        sent_frames = []

        with (
            patch(
                'lyte.animate.playback.time.monotonic',
                side_effect=[0.0, 0.5, 0.5, 0.5, 2.0],
            ),
            patch('lyte.animate.playback.time.sleep'),
            patch(
                'lyte.animate.playback.realtime.send_realtime_frame',
                lambda *a: sent_frames.append(a[-1]),
            ),
        ):
            self.script.run_crossfade(
                current_animation,
                current_state,
                next_animation,
                next_state,
                args,
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                device,
                1.0,
            )

        self.assertEqual(current_animation.calls, 1)
        self.assertEqual(next_animation.calls, 1)
        npt.assert_array_equal(
            sent_frames[0],
            np.array([[50, 100, 125]], dtype=np.uint8),
        )

    def test_build_animation_creates_random_walk(self) -> None:
        with patch(
            'sys.argv',
            [
                'lyte',
                'random_walk',
                '--color',
                '10',
                '20',
                '30',
                '--seed',
                '1',
            ],
        ):
            args = self.script.parse_args()

        animation = self.script.build_animation(args)
        device, state = initial_state(animation, 2)

        self.assertIsInstance(animation, RandomWalk)
        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[0, 0, 0], [2, 5, 8]], dtype=np.uint8),
        )

    def test_build_animation_creates_color_chase(self) -> None:
        with patch(
            'sys.argv',
            [
                'lyte',
                'color_chase',
                '--color',
                '1',
                '2',
                '3',
                '--width',
                '2',
            ],
        ):
            args = self.script.parse_args()

        animation = self.script.build_animation(args)
        device, state = initial_state(animation, 3)

        self.assertIsInstance(animation, bibliopixel.ColorChase)
        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[1, 2, 3], [1, 2, 3], [0, 0, 0]], dtype=np.uint8),
        )

    def test_build_animation_creates_ported_strip_animation(self) -> None:
        with patch('sys.argv', ['lyte', 'rainbow']):
            args = self.script.parse_args()

        animation = self.script.build_animation(args)
        device, state = initial_state(animation, 3)

        self.assertIsInstance(animation, bibliopixel.Rainbow)
        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[255, 0, 0], [252, 3, 0], [249, 6, 0]], dtype=np.uint8),
        )

    def test_off_mode_skips_realtime_streaming(self) -> None:
        with (
            patch('sys.argv', ['lyte', 'off', '--host', '192.168.1.23']),
            patch(
                'lyte.twinkly.realtime.session.read_gestalt', return_value={'mac': 'AA'}
            ),
            patch(
                'lyte.twinkly.realtime.session.authenticate_device',
                return_value=object(),
            ),
            patch(
                'lyte.twinkly.realtime.session.set_off_mode_with_retry',
                return_value=TwinklyResponse(http_status=200, data={'code': 1000}),
            ) as set_off_mode,
            patch('lyte.animate.playback.realtime.read_led_count') as read_led_count,
            patch('lyte.animate.playback.realtime.prepare_device') as prepare_device,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = self.script.main()

        self.assertEqual(result, 0)
        set_off_mode.assert_called_once()
        read_led_count.assert_not_called()
        prepare_device.assert_not_called()

    def test_read_led_count_prints_device_info(self) -> None:
        output = io.StringIO()

        with (
            patch(
                'lyte.twinkly.realtime.session.read_device_led_count',
                return_value=(250, {'mac': 'AA', 'number_of_led': 250}),
            ),
            patch('sys.stdout', output),
        ):
            led_count = self.script.realtime.read_led_count(
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                None,
                '192.168.1.23',
            )

        self.assertEqual(led_count, 250)
        self.assertEqual(output.getvalue(), '[connected] 192.168.1.23: 250 LEDs\n')

    def test_animation_turns_off_device_after_exception(self) -> None:
        class BrokenAnimation(animation.Animation):
            def render(
                self, device: animation.Device, state: animation.State
            ) -> NDArray[np.float32]:
                raise RuntimeError('boom')

        with (
            patch(
                'sys.argv',
                [
                    'lyte',
                    'color_fill',
                    '--host',
                    '192.168.1.23',
                ],
            ),
            patch('lyte.animate.playback.realtime.read_led_count', return_value=1),
            patch('lyte.animate.playback.realtime.prepare_device', return_value=True),
            patch(
                'lyte.animate.playback.build_animation',
                return_value=BrokenAnimation(),
            ),
            patch(
                'lyte.twinkly.realtime.session.set_off_mode_with_retry',
                return_value=TwinklyResponse(http_status=200, data={'code': 1000}),
            ) as set_off_mode,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            with self.assertRaisesRegex(RuntimeError, 'boom'):
                self.script.main()

        set_off_mode.assert_called_once()


class PreviewCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = importlib.import_module('lyte.preview.command')

    def test_parse_args_builds_preview_animation(self) -> None:
        with patch(
            'sys.argv',
            [
                'lyte',
                'color_fill',
                'preview.html',
                '--color',
                '1',
                '2',
                '3',
            ],
        ):
            args = self.script.parse_args()

        animation = self.script.build.build_animation(args.animation_config)

        self.assertIsInstance(animation, bibliopixel.ColorFill)
        self.assertEqual(args.output, Path('preview.html'))
        self.assertEqual(args.width, 16)
        self.assertEqual(args.height, 16)
        self.assertEqual(args.spacing, 1.0)
        self.assertEqual(args.led_size, 1.0)

    def test_main_without_arguments_prints_patterns(self) -> None:
        output = io.StringIO()

        with (
            patch('sys.argv', ['lyte']),
            patch('sys.stdout', output),
            patch.object(self.script, 'render_animation_html') as render_animation_html,
        ):
            result = self.script.main()

        self.assertEqual(result, 0)
        self.assertIn('color_fill\n', output.getvalue())
        self.assertIn('rainbow\n', output.getvalue())
        self.assertNotIn('off\n', output.getvalue())
        self.assertNotIn('random\n', output.getvalue())
        render_animation_html.assert_not_called()

    def test_animation_config_keeps_layout_width_out_of_animation(self) -> None:
        with patch(
            'sys.argv',
            ['lyte', 'color_chase', 'preview.html', '--width', '24'],
        ):
            args = self.script.parse_args()

        self.assertEqual(args.width, 24)
        self.assertEqual(args.animation_config.width, 1)

    def test_main_writes_preview_without_layout_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'preview.html'
            with patch(
                'sys.argv',
                [
                    'lyte',
                    'color_fill',
                    str(output),
                    '--width',
                    '2',
                    '--height',
                    '1',
                    '--duration',
                    '1',
                    '--fps',
                    '1',
                    '--name',
                    'Preview',
                    '--led-size',
                    '2.5',
                    '--open',
                ],
            ):
                with patch.object(self.script.webbrowser, 'open') as open_browser:
                    result = self.script.main()

            data = preview_data(output.read_text())

        self.assertEqual(result, 0)
        self.assertEqual(data['name'], 'Preview')
        self.assertEqual(data['coords'], [[0.0, 0.0], [1.0, 0.0]])
        self.assertEqual(data['ledSize'], 2.5)
        open_browser.assert_called_once_with(output.resolve().as_uri())


if __name__ == '__main__':
    unittest.main()
