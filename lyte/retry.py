"""Retry helpers for transient Lyte network operations."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from .logging import log, log_error

T = TypeVar('T')


class RetryConfig(BaseModel, frozen=True):
    attempts: int
    delay: float
    backoff: float
    backoff_after: int = 1


def retry_call(
    label: str,
    retry: RetryConfig,
    operation: Callable[[], T],
    retry_errors: tuple[type[BaseException], ...],
) -> T | None:
    delay = retry.delay
    last_failure = ''
    for attempt in range(1, retry.attempts + 1):
        log(f'[try] {label}: attempt {attempt}/{retry.attempts}')
        started_at = time.monotonic()
        try:
            result = operation()
        except retry_errors as err:
            elapsed = (time.monotonic() - started_at) * 1000
            last_failure = (
                f'[failed] {label} failed on attempt {attempt}/{retry.attempts} '
                f'after {elapsed:.1f} ms: {type(err).__name__}: {err}'
            )
            if attempt == retry.attempts:
                log_error(last_failure)
                return None
            log(f'[retry] Waiting {delay * 1000:.1f} ms before retrying {label}.')
            time.sleep(delay)
            if attempt >= retry.backoff_after:
                delay *= retry.backoff
            continue

        elapsed = (time.monotonic() - started_at) * 1000
        if attempt > 1:
            log(f'[ok] {label} recovered on attempt {attempt} after {elapsed:.1f} ms.')
        else:
            log(f'[ok] {label} completed in {elapsed:.1f} ms.')
        return result
    return None
