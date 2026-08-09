from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import patch

import mido
import numpy as np
from numpy import testing as npt
from pydantic import BaseModel

from lyte import animation, midi, patches
from lyte.retry import RetryConfig
from lyte.twinkly import realtime
from lyte.twinkly.client import TwinklyClient


class PatchLibraryTests(unittest.TestCase):
    def test_load_wearable_library_and_map_logical_regions(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))

        self.assertEqual(len(library.patches), 32)
        self.assertIn('random_walk', library.layers)
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

    def test_library_uses_validated_control_bindings(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
        patch = library.patches['breath_mix_walk_twinkle']

        self.assertEqual(patch.activation, 'note')
        self.assertEqual(
            [(binding.source, binding.target) for binding in patch.bindings],
            [('breath', 'random_walk.speed'), ('breath', 'mix.region_twinkle')],
        )
        self.assertEqual(patch.blend, 'weighted')

    def test_library_rejects_unknown_binding_target(self) -> None:
        with self.assertRaisesRegex(ValueError, 'invalid binding target'):
            patches.PatchLibrary.model_validate(
                {
                    'wearable': {
                        'led_count': 1,
                        'physical_map_status': 'measured',
                        'segments': {'body': {'start': 0, 'led_count': 1}},
                        'physical_map': {
                            'body': {'ranges': [{'start': 0, 'led_count': 1}]}
                        },
                    },
                    'layers': {'solid': {'kind': 'solid'}},
                    'patches': {
                        'test': {
                            'activation': 'note',
                            'layers': ['solid'],
                            'bindings': [
                                {
                                    'source': 'breath',
                                    'target': 'missing.speed',
                                    'map': {
                                        'kind': 'linear',
                                        'output': [0.0, 1.0],
                                    },
                                }
                            ],
                        }
                    },
                }
            )

    def test_locator_frame_lights_only_the_selected_logical_region(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))

        frame = patches.locator_frame(library.wearable, 'left_arm')

        self.assertTrue(np.all(frame[0:28] == 1.0))
        self.assertTrue(np.all(frame[60:76] == 1.0))
        self.assertTrue(np.all(frame[28:60] == 0.0))
        self.assertTrue(np.all(frame[76:200] == 0.0))

    def test_build_light_patch_composes_named_layers(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
        patch = patches.build_light_patch(library, 'breath_mix_walk_twinkle')
        device = animation.Device(led_count=200)

        patch.receive(mido.Message('note_on', note=64, velocity=100))

        frame = patch.render(device)
        self.assertEqual(frame.shape, (200, 3))
        self.assertEqual(frame.dtype, np.float32)
        self.assertTrue(frame.flags.c_contiguous)

    def test_declarative_patch_applies_note_breath_mix_and_pitch_bindings(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
        patch = patches.build_light_patch(library, 'breath_mix_walk_twinkle')
        if not isinstance(patch, patches.DeclarativeLightPatch):
            self.fail('patch did not compile to DeclarativeLightPatch')

        patch.receive(mido.Message('note_on', note=61, velocity=100))
        patch.receive(mido.Message('control_change', control=2, value=127))
        state = patch.state
        if state is None:
            self.fail('patch state was not created')

        self.assertEqual(state.weights['region_twinkle'], 1.0)
        self.assertEqual(state.weights['random_walk'], 0.0)
        patch.receive(mido.Message('note_off', note=61))
        self.assertIsNone(patch.state)

    def test_pitch_bend_maps_only_the_positive_half(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
        patch = patches.build_light_patch(library, 'pitch_turbo_walk')
        if not isinstance(patch, patches.DeclarativeLightPatch):
            self.fail('patch did not compile to DeclarativeLightPatch')

        patch.receive(mido.Message('note_on', note=60, velocity=100))
        layer = patch.layers['random_walk']
        patch.receive(mido.Message('pitchwheel', pitch=-4096))
        self.assertEqual(layer.config.regions[0].animation.speed, 1.0)
        patch.receive(mido.Message('pitchwheel', pitch=8191))
        self.assertEqual(layer.config.regions[0].animation.speed, 300.0)

    def test_build_light_patch_rejects_unknown_patch(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))

        with self.assertRaisesRegex(ValueError, 'unknown patch'):
            patches.build_light_patch(library, 'missing')

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

    def test_patch_playback_polls_midi_and_streams_mapped_frames(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))

        class Port:
            messages = iter([mido.Message('note_on', note=60, velocity=100)])
            closed = False

            def close(self) -> None:
                self.closed = True

            def poll(self) -> mido.Message | None:
                return next(self.messages, None)

        port = Port()
        config = patches.PatchCommandConfig(
            action='play',
            patch_name='breath_walker',
            duration=0.1,
        )
        sent = realtime.FrameSendResult(
            status=realtime.FrameSendStatus.SENT,
            byte_count=600,
        )

        with (
            patch('lyte.patches.realtime.discover_host', return_value='192.168.1.23'),
            patch('lyte.patches.realtime.read_led_count', return_value=200),
            patch('lyte.patches.realtime.prepare_device', return_value=True),
            patch(
                'lyte.patches.realtime.send_realtime_frame', return_value=sent
            ) as send,
            patch('lyte.patches.realtime.turn_off_streaming_device', return_value=True),
            patch('lyte.patches.midi.open_input', return_value=port),
            patch('lyte.patches.time.monotonic', side_effect=[0.0, 0.0, 1.0]),
            patch('lyte.patches.time.sleep'),
        ):
            result = patches.run_patch_playback(config, library)

        self.assertEqual(result, 0)
        self.assertTrue(port.closed)
        send.assert_called_once()

    def test_patch_playback_applies_input_before_rendering_each_frame(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))

        class Port:
            messages = iter([mido.Message('note_on', note=60, velocity=100)])

            def close(self) -> None:
                pass

            def poll(self) -> mido.Message | None:
                return next(self.messages, None)

        class Config(BaseModel, frozen=True):
            pass

        class State(BaseModel):
            pass

        class TestPatch(midi.LightPatch[Config, State]):
            def make_state(self, msg: mido.Message) -> State:
                return State()

            def render(self, device: animation.Device) -> np.ndarray:
                frame = np.zeros((device.led_count, 3), dtype=np.float32)
                if self.state is not None:
                    frame[:, 0] = 1.0
                return animation.validate_frame(device, frame)

        light_patch = TestPatch(config=Config())
        sent = realtime.FrameSendResult(
            status=realtime.FrameSendStatus.SENT,
            byte_count=600,
        )
        frames = []

        with (
            patch(
                'lyte.patches.realtime.send_realtime_frame',
                side_effect=lambda *args: frames.append(args[-1]) or sent,
            ),
            patch('lyte.patches.time.monotonic', side_effect=[0.0, 0.0, 1.0]),
            patch('lyte.patches.time.sleep'),
        ):
            patches.stream_patch_frames(
                Port(),
                patches.PatchCommandConfig(action='play', duration=0.1),
                library,
                light_patch,
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
            )

        self.assertEqual(len(frames), 1)
        self.assertTrue(np.all(frames[0][:, 0] == 255))

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
