from __future__ import annotations

import sys

from lyte.cli import main


def test_cli_help(cli_help) -> None:
    cli_help(
        'lyte',
        lambda: main(sys.argv[1:]),
        subcommands=[
            'animate',
            'author',
            'black-floor',
            'brightness',
            'color',
            'diagnostic',
            'effects',
            'installation',
            'layout',
            'led-config',
            'mic',
            'mode',
            'movie',
            'mqtt',
            'music',
            'network',
            'patch',
            'playlist',
            'preview',
            'render',
            'saturation',
            'show',
            'test',
            'test2',
            'timer',
            'verify',
            'wled',
        ],
    )
