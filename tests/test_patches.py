from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import patch

import mido
import numpy as np
from numpy import testing as npt

from lyte import animation, cli, patches


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
