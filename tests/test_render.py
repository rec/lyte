from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pytest

from lyte import render


def test_grid_renderer_uses_rounded_square_layout() -> None:
    renderer = render.GridRenderer(5, 4, 1, 'rect', None, 'white')
    values = np.array(
        [[255, 0, 0], [0, 255, 0], [0, 0, 255], [0, 0, 0], [255, 255, 0]],
        dtype=np.uint8,
    )

    frame = renderer.render(values)

    assert frame.shape == (12, 16, 3)
    assert frame[1, 1].tolist() == [255, 0, 0]
    assert frame[1, 6].tolist() == [0, 255, 0]
    assert frame[6, 1].tolist() == [0, 0, 0]


def test_grid_renderer_draws_circular_lights() -> None:
    renderer = render.GridRenderer(1, 4, 0, 'circle', [1, 1], '#000')

    frame = renderer.render(np.array([[255, 0, 0]], dtype=np.uint8))

    assert frame[0, 0].tolist() == [0, 0, 0]
    assert frame[2, 2].tolist() == [255, 0, 0]


@pytest.mark.parametrize(
    ('value', 'expected'),
    [('white', (255, 255, 255)), ('#0aF', (0, 170, 255)), ('#123456', (18, 52, 86))],
)
def test_parse_color(value: str, expected: tuple[int, int, int]) -> None:
    assert render.parse_color(value) == expected


def test_parse_color_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match='background color'):
        render.parse_color('chartreuse')


def test_run_render_uses_explicit_selectors(tmp_path: Path) -> None:
    config = render.RenderConfig(selectors=['one', 'two'], output=tmp_path, duration=1)
    library = Mock()

    with (
        patch.object(render.shutil, 'which', return_value='/opt/homebrew/bin/ffmpeg'),
        patch.object(render.library_files, 'read_library', return_value=library),
        patch.object(render.show, 'log_diagnostics'),
        patch.object(render, 'render_animation') as render_animation,
    ):
        assert render.run_render(config) == 0

    assert [call.args[0] for call in render_animation.call_args_list] == ['one', 'two']


def test_run_render_uses_all_library_animations(tmp_path: Path) -> None:
    config = render.RenderConfig(output=tmp_path, duration=1)
    library = Mock()

    with (
        patch.object(render.shutil, 'which', return_value='/opt/homebrew/bin/ffmpeg'),
        patch.object(render.library_files, 'read_library', return_value=library),
        patch.object(render.show, 'log_diagnostics'),
        patch.object(render, 'list_animation_selectors', return_value=['one', 'two']),
        patch.object(render, 'render_animation') as render_animation,
    ):
        assert render.run_render(config) == 0

    assert [call.args[0] for call in render_animation.call_args_list] == ['one', 'two']


def test_run_render_rejects_missing_ffmpeg(tmp_path: Path) -> None:
    with (
        patch.object(render.shutil, 'which', return_value=None),
        pytest.raises(render.RenderError, match='ffmpeg'),
    ):
        render.run_render(render.RenderConfig(selectors=['one'], output=tmp_path))


def test_safe_name_uses_a_file_name() -> None:
    assert render.safe_name('show:/spark.toml') == 'show--spark-toml'
