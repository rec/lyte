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


@pytest.mark.parametrize('selectors', [['a_b', 'a-b'], ['Aurora', 'aurora']])
def test_export_rejects_colliding_names_before_rendering(
    tmp_path: Path, selectors: list[str]
) -> None:
    with (
        patch.object(render.shutil, 'which', return_value='ffmpeg'),
        patch.object(render.library_files, 'read_library'),
        patch.object(render.show, 'log_diagnostics'),
        patch.object(render, 'render_animation') as export,
        pytest.raises(render.RenderError, match='share destination'),
    ):
        render.run_render(render.RenderConfig(selectors=selectors, output=tmp_path))
    export.assert_not_called()


def test_existing_export_stops_the_entire_batch(tmp_path: Path) -> None:
    destination = tmp_path / 'two.mp4'
    destination.write_bytes(b'existing movie')
    with (
        patch.object(render.shutil, 'which', return_value='ffmpeg'),
        patch.object(render.library_files, 'read_library'),
        patch.object(render.show, 'log_diagnostics'),
        patch.object(render, 'render_animation') as export,
        pytest.raises(render.RenderError, match='output already exists'),
    ):
        render.run_render(
            render.RenderConfig(selectors=['one', 'two'], output=tmp_path)
        )
    export.assert_not_called()
    assert destination.read_bytes() == b'existing movie'


@pytest.mark.parametrize(
    'failure', ['render', 'write', 'close', 'exit', 'publish', None]
)
def test_export_reaps_encoder_and_publishes_only_successful_movies(
    tmp_path: Path, failure: str | None
) -> None:
    config = render.RenderConfig(
        output=tmp_path, duration=0.01, library_config=Path('examples/library.toml')
    )
    process = Mock()
    process.stdin.closed = False
    process.poll.return_value = None
    process.wait.return_value = 1 if failure == 'exit' else 0
    if failure == 'write':
        process.stdin.write.side_effect = BrokenPipeError('write failed')
    if failure in {'close', 'render'}:
        process.stdin.close.side_effect = BrokenPipeError('close failed')

    def start(command: list[str], stdin: object) -> Mock:
        Path(command[-1]).write_bytes(b'movie')
        if failure == 'publish':
            (tmp_path / 'aurora.mp4').write_bytes(b'previous movie')
        return process

    with (
        patch.object(render.subprocess, 'Popen', side_effect=start),
        patch.object(
            render.GridRenderer,
            'render',
            return_value=np.zeros((2, 2, 3), dtype=np.uint8),
        ) as frame,
    ):
        if failure == 'render':
            frame.side_effect = ValueError('render failed')
        if failure is None:
            result = render.render_animation('aurora', config, 'ffmpeg')
            assert result.read_bytes() == b'movie'
        else:
            expected = ValueError if failure == 'render' else render.RenderError
            with pytest.raises(
                expected, match='render failed' if failure == 'render' else None
            ):
                render.render_animation('aurora', config, 'ffmpeg')
    process.wait.assert_called_once()
    if failure in {'render', 'write', 'close'}:
        process.kill.assert_called_once()
    if failure == 'publish':
        assert (tmp_path / 'aurora.mp4').read_bytes() == b'previous movie'
    assert sorted(p.name for p in tmp_path.iterdir()) == (
        ['aurora.mp4'] if failure in {None, 'publish'} else []
    )
