from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

from lyte.preview import command


def preview_data(value: str) -> dict[str, object]:
    start = value.index('const data = ') + len('const data = ')
    end = value.index(';\nconst canvas', start)
    return json.loads(value[start:end])


def test_parse_args_selects_a_library_score() -> None:
    args = command.parse_args(
        [
            'examples:/composition.toml',
            'preview.html',
            '--library-config',
            'examples/library.toml',
        ]
    )

    assert args.selector == 'examples:/composition.toml'
    assert args.output == Path('preview.html')
    assert args.library_config == Path('examples/library.toml')
    assert args.led_size == 1.0


def test_main_without_arguments_lists_ready_animation_scores() -> None:
    output = io.StringIO()

    with (
        patch('sys.argv', ['lyte', '--library-config', 'examples/library.toml']),
        patch('sys.stdout', output),
        patch.object(command, 'render_animation_html') as render_animation_html,
    ):
        result = command.main()

    assert result == 0
    assert 'composition\n' in output.getvalue()
    assert 'aurora\n' in output.getvalue()
    render_animation_html.assert_not_called()


def test_family_listing_uses_effect_metadata() -> None:
    output = io.StringIO()

    with patch('sys.stdout', output):
        command.print_preview_scores(Path('examples/library.toml'), 'fields')

    assert output.getvalue().splitlines() == ['aurora']


def test_main_writes_preview_from_authored_layout(tmp_path: Path) -> None:
    output = tmp_path / 'preview.html'
    result = command.run_preview(
        command.PreviewConfig(
            selector='examples:/composition.toml',
            output=output,
            library_config=Path('examples/library.toml'),
            duration=0.05,
            name='Preview',
            led_size=2.5,
        )
    )

    data = preview_data(output.read_text())

    assert result == 0
    assert data['name'] == 'Preview'
    assert len(data['coords']) == 250
    assert data['ledSize'] == 2.5
