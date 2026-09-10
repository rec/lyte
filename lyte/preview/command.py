"""Render a Lyte animation to a standalone HTML preview."""

import sys
import webbrowser
from collections.abc import Sequence
from typing import cast

import tyro

from ..animate import build, config
from ..animation import Family
from .config import PREVIEW_ANIMATIONS, PreviewConfig
from .document import render_animation_html
from .layout import Layout
from .validation import validate_args


def main() -> int:
    args = parse_args()
    return run_preview(args)


def run_preview(args: PreviewConfig) -> int:
    if args.animation is None and args.output is None:
        print_preview_patterns(args.family)
        return 0
    if args.animation is None or args.output is None:
        sys.exit('preview requires both animation and output')
    if args.family is not None:
        sys.exit('--family is only used when listing animations')
    validate_args(args)
    layout = Layout(
        name=args.name or args.animation,
        dims=[args.height, args.width],
        spacing=args.spacing,
    )
    animation = build.build_animation(args.animation_config)
    render_animation_html(
        animation,
        layout,
        args.output,
        fps=args.fps,
        duration=args.duration,
        led_size=args.led_size,
    )
    if args.open:
        webbrowser.open(args.output.resolve().as_uri())
    return 0


def parse_args(args: Sequence[str] | None = None) -> PreviewConfig:
    return tyro.cli(PreviewConfig, args=args)


def print_preview_patterns(family: Family | None = None) -> None:
    for name in PREVIEW_ANIMATIONS:
        if family is None:
            print(name)
        elif name == 'composition':
            if family == Family.COMPOSITIONS:
                print(name)
        elif (
            build.build_animation(
                config.AnimateConfig(animation=cast(config.AnimationName, name))
            ).family
            == family
        ):
            print(name)


if __name__ == '__main__':
    raise SystemExit(main())
