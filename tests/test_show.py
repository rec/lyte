from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lyte import show


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
