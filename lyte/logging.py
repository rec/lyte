"""Small opt-in diagnostic logging helpers."""

from __future__ import annotations

import sys


LOGGING = False


def log(message: str = "") -> None:
    if LOGGING:
        print(message)


def log_error(message: str) -> None:
    print(message, file=sys.stderr)
