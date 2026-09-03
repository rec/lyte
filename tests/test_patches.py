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
from lyte.twinkly import realtime, track
from lyte.twinkly.client import TwinklyClient


def make_track(led_count: int = 200) -> track.TwinklyTrack:
    return track.TwinklyTrack(
        client=TwinklyClient(host='192.168.1.23'),
        retry=RetryConfig(attempts=1, delay=0, backoff=1),
        host='192.168.1.23',
        configured_host=None,
        discovery_timeout=None,
        device=animation.Device(led_count=led_count),
    )


class PatchLibraryTests(unittest.TestCase):
    def test_load_wearable_library_and_map_logical_regions(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))

        self.assertEqual(len(library.patches), 32)
        self.assertIn('random_walk', library.layers)
        self.assertEqual(library.wearable.physical_map_status, 'guessed')
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

    def test_wearable_layout_scales_to_the_connected_led_count(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))

        with patch('lyte.patches.LOGGER.warning') as log_warning:
            wearable = patches.scale_wearable_layout(library.wearable, 250)

        assert wearable.led_count == 250
        assert wearable.segments['left_leg'] == patches.RegionSpec(
            start=0, led_count=40
        )
        assert wearable.segments['left_arm'] == patches.RegionSpec(
            start=80, led_count=55
        )
        assert wearable.physical_map['left_arm'].ranges == [
            patches.PhysicalRangeSpec(start=0, led_count=35),
            patches.PhysicalRangeSpec(start=75, led_count=20),
        ]
        frame = np.zeros((250, 3), dtype=np.float32)
        assert patches.map_logical_frame(wearable, frame).shape == (250, 3)
        log_warning.assert_called_once_with(
            '[warn] Scaling wearable layout from 200 LEDs to 250 LEDs.'
        )

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

    def test_library_rejects_bindings_unsupported_by_layer_capabilities(self) -> None:
        base = {
            'wearable': {
                'led_count': 1,
                'physical_map_status': 'measured',
                'segments': {'body': {'start': 0, 'led_count': 1}},
                'physical_map': {'body': {'ranges': [{'start': 0, 'led_count': 1}]}},
            },
            'layers': {'solid': {'kind': 'solid'}},
        }
        with self.assertRaisesRegex(ValueError, 'does not support'):
            patches.PatchLibrary.model_validate(
                base
                | {
                    'patches': {
                        'test': {
                            'activation': 'note',
                            'layers': ['solid'],
                            'bindings': [
                                {
                                    'source': 'breath',
                                    'target': 'solid.speed',
                                    'map': {
                                        'kind': 'linear',
                                        'output': [0.0, 1.0],
                                    },
                                }
                            ],
                        }
                    }
                }
            )
        with self.assertRaisesRegex(ValueError, 'without a weighted blend'):
            patches.PatchLibrary.model_validate(
                base
                | {
                    'patches': {
                        'test': {
                            'activation': 'note',
                            'layers': ['solid'],
                            'bindings': [
                                {
                                    'source': 'breath',
                                    'target': 'mix.solid',
                                    'map': {
                                        'kind': 'linear',
                                        'output': [0.0, 1.0],
                                    },
                                }
                            ],
                        }
                    }
                }
            )

    def test_wearable_encoder_maps_logical_values_before_byte_encoding(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
        logical_frame = np.zeros((200, 3), dtype=np.float32)
        logical_frame[0:32, 1] = 1.0

        encoded = patches.encode_wearable_frame(library.wearable, logical_frame)

        self.assertTrue(np.all(encoded[28:60, 1] == 255))
        self.assertTrue(np.all(encoded[0:28, 1] == 0))

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

    def test_note_and_breath_bindings_change_the_declared_layer_state(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
        note_patch = patches.build_light_patch(library, 'prism_limbs')
        breath_patch = patches.build_light_patch(library, 'breath_walker')
        if not isinstance(note_patch, patches.DeclarativeLightPatch):
            self.fail('note patch did not compile')
        if not isinstance(breath_patch, patches.DeclarativeLightPatch):
            self.fail('breath patch did not compile')

        note_patch.receive(mido.Message('note_on', note=61, velocity=100))
        breath_patch.receive(mido.Message('note_on', note=60, velocity=100))
        breath_patch.receive(mido.Message('control_change', control=2, value=127))
        if note_patch.state is None:
            self.fail('note patch state was not created')

        self.assertEqual(
            note_patch.state.colors['five_color_fill'],
            note_patch.config.note_palette[1],
        )
        self.assertEqual(
            breath_patch.layers['random_walk'].config.regions[0].animation.speed,
            100.0,
        )

    def test_note_end_restores_layer_speed_before_the_next_note(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
        patch = patches.build_light_patch(library, 'breath_walker')
        if not isinstance(patch, patches.DeclarativeLightPatch):
            self.fail('patch did not compile to DeclarativeLightPatch')

        layer = patch.layers['random_walk']
        if not isinstance(layer, midi.RegionLightPatch):
            self.fail('layer did not compile to a region light patch')
        initial_speed = layer.config.regions[0].animation.speed
        patch.receive(mido.Message('note_on', note=60, velocity=100))
        patch.receive(mido.Message('control_change', control=2, value=127))
        self.assertEqual(layer.config.regions[0].animation.speed, 100.0)

        patch.receive(mido.Message('note_off', note=60))
        self.assertEqual(layer.config.regions[0].animation.speed, initial_speed)
        patch.receive(mido.Message('note_on', note=61, velocity=100))
        self.assertEqual(layer.config.regions[0].animation.speed, initial_speed)

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

    def test_layer_regions_override_the_patch_default_regions(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
        patch = patches.build_light_patch(library, 'chest_orbit')
        if not isinstance(patch, patches.DeclarativeLightPatch):
            self.fail('patch did not compile')

        chest = patch.layers['chest_spiral']
        limbs = patch.layers['limb_fill']
        self.assertEqual(len(chest.config.regions), 1)
        self.assertEqual(chest.config.regions[0].start, 152)
        self.assertEqual(len(limbs.config.regions), 4)
        self.assertNotIn(152, [region.start for region in limbs.config.regions])

    def test_declarative_patch_compiles_declared_blend_policy(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
        additive = patches.build_light_patch(library, 'prism_limbs')
        weighted = patches.build_light_patch(library, 'breath_mix_walk_twinkle')

        if not isinstance(additive, patches.DeclarativeLightPatch):
            self.fail('additive patch did not compile')
        if not isinstance(weighted, patches.DeclarativeLightPatch):
            self.fail('weighted patch did not compile')
        self.assertIsInstance(additive.mixer, midi.BlendLightPatch)
        self.assertIsInstance(weighted.mixer, midi.WeightedBlendLightPatch)

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
        self.assertIn('Wearable: 200 LEDs (guessed physical map)', output.getvalue())
        self.assertIn('prism_limbs:', output.getvalue())

    def test_patch_playback_rejects_a_provisional_physical_map(self) -> None:
        library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
        library = library.model_copy(
            update={
                'wearable': library.wearable.model_copy(
                    update={'physical_map_status': 'provisional'}
                )
            }
        )
        with patch('lyte.patches.LOGGER.error') as log_error:
            result = patches.run_patch_playback(
                patches.PatchCommandConfig(action='play', patch_name='breath_walker'),
                library,
            )

        self.assertEqual(result, 1)
        log_error.assert_called_once_with(
            '[failed] Patch playback requires a guessed or measured physical map.'
        )

    def test_patch_playback_recovers_after_a_failed_frame_send(self) -> None:
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
        failed = realtime.FrameSendResult(status=realtime.FrameSendStatus.TOKEN_MISSING)

        with (
            patch('lyte.patches.realtime.discover_host', return_value='192.168.1.23'),
            patch('lyte.patches.realtime.read_led_count', return_value=250),
            patch('lyte.patches.realtime.prepare_device', return_value=True),
            patch(
                'lyte.patches.realtime.send_realtime_frame', return_value=failed
            ) as send,
            patch(
                'lyte.patches.realtime.recover_streaming_device',
                return_value='192.168.1.23',
            ) as recover,
            patch('lyte.patches.realtime.turn_off_streaming_device', return_value=True),
            patch('lyte.patches.midi.open_input', return_value=port),
            patch(
                'lyte.twinkly.track.time.monotonic',
                side_effect=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0],
            ),
            patch('lyte.twinkly.track.time.sleep'),
        ):
            result = patches.run_patch_playback(config, library)

        self.assertEqual(result, 0)
        self.assertTrue(port.closed)
        send.assert_called_once()
        assert send.call_args.args[3].shape == (250, 3)
        recover.assert_called_once()

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
                'lyte.twinkly.track.realtime.send_realtime_frame',
                side_effect=lambda *args: frames.append(args[-2]) or sent,
            ),
            patch(
                'lyte.twinkly.track.time.monotonic',
                side_effect=[0.0, 0.0, 0.0, 0.0, 1.0],
            ),
            patch('lyte.twinkly.track.time.sleep'),
        ):
            patches.stream_patch_frames(
                Port(),
                patches.PatchCommandConfig(action='play', duration=0.1),
                library,
                light_patch,
                make_track(),
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
