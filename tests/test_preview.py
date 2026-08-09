from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from lyte.animations import bibliopixel
from lyte.preview import document
from lyte.preview.layout import Layout


def preview_data(document: str) -> dict[str, object]:
    start = document.index('const data = ') + len('const data = ')
    end = document.index(';\nconst canvas', start)
    return json.loads(document[start:end])


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
