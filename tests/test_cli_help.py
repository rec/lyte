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
            'benchmark',
            'calibrate-black',
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
            'panel',
            'playlist',
            'preview',
            'render',
            'rehearse',
            'saturation',
            'validate',
            'fps-test',
            'dither-test',
            'timer',
            'verify-output',
            'wled',
        ],
    )


def test_installation_help(cli_help) -> None:
    cli_help(
        'lyte installation',
        lambda: main(['installation', *sys.argv[1:]]),
        subcommands=[
            'run',
            'install',
            'uninstall',
            'start',
            'stop',
            'restart',
            'status',
        ],
    )
