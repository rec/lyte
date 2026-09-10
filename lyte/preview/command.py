"""Render a Ufor light score to a standalone HTML preview."""

import sys
import webbrowser
from collections.abc import Sequence
from pathlib import Path

import tyro
from ufor import effects, library_files
from ufor.light_animation import AnimationScore

from .. import show
from .config import PreviewConfig
from .document import render_animation_html


def main() -> int:
    return run_preview(parse_args())


def run_preview(args: PreviewConfig) -> int:
    if args.selector is None and args.output is None:
        print_preview_scores(args.library_config, args.family)
        return 0
    if args.selector is None or args.output is None:
        sys.exit('preview requires both selector and output')
    if args.family is not None:
        sys.exit('--family is only used when listing scores')
    if args.duration <= 0:
        sys.exit('--duration must be greater than zero')
    if args.led_size <= 0:
        sys.exit('--led-size must be greater than zero')
    prepared = show.prepare_animation(
        show.LightProgramSpec(
            selector=args.selector,
            output=args.light_output,
            parameters=args.parameters,
        ),
        args.library_config,
    )
    render_animation_html(
        prepared,
        args.output,
        duration=args.duration,
        led_size=args.led_size,
        name=args.name,
    )
    if args.open:
        webbrowser.open(args.output.resolve().as_uri())
    return 0


def parse_args(args: Sequence[str] | None = None) -> PreviewConfig:
    return tyro.cli(PreviewConfig, args=args)


def print_preview_scores(
    library_config: Path | None = None, family: str | None = None
) -> None:
    library = library_files.read_library(library_config)
    show.log_diagnostics(library)
    for entry in library.find():
        score = entry.resolved
        if not isinstance(score, AnimationScore):
            continue
        operation = score.body.operation
        score_family = (
            operation.family if isinstance(operation, effects.Effect) else 'composition'
        )
        if family is None or family == score_family:
            print(entry.name or entry.key)


if __name__ == '__main__':
    raise SystemExit(main())
