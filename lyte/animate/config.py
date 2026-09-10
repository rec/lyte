from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, NoReturn

import tyro
from pydantic import BaseModel, Field


class AnimateConfig(BaseModel, frozen=True):
    selector: Annotated[str, tyro.conf.Positional]
    library_config: Path | None = None
    output: str = 'light'
    parameters: dict[str, float] = Field(default_factory=dict)
    wiring: list[str] | None = None
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float | None = None
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0
    led_count: int | None = None
    duration: float | None = None


def validate_args(args: AnimateConfig) -> None:
    if args.attempts < 1:
        fail('--attempts must be at least 1')
    if args.retry_delay < 0:
        fail('--retry-delay must not be negative')
    if args.retry_backoff < 1:
        fail('--retry-backoff must be at least 1')
    if args.duration is not None and args.duration <= 0:
        fail('--duration must be greater than zero')


def fail(message: str) -> NoReturn:
    sys.exit(message)
