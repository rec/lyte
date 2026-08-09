from __future__ import annotations

import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lyte.animations import bibliopixel


def preview_data(document: str) -> dict[str, object]:
    start = document.index('const data = ') + len('const data = ')
    end = document.index(';\nconst canvas', start)
    return json.loads(document[start:end])


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
