"""Retry helpers for transient Lyte network operations."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from pydantic import BaseModel
from reccy import logging

LOGGER = logging.get_logger(__name__)


class RetryConfig(BaseModel, frozen=True):
    attempts: int
    delay: float
    backoff: float
    backoff_after: int = 1


def retry_call[Result](
    label: str,
    retry: RetryConfig,
    operation: Callable[[], Result],
    retry_errors: tuple[type[BaseException], ...],
    deadline: float | None = None,
    stop_event: threading.Event | None = None,
) -> Result | None:
    delay = retry.delay
    for attempt in range(1, retry.attempts + 1):
        if stop_event is not None and stop_event.is_set():
            return None
        if deadline is not None and time.monotonic() >= deadline:
            LOGGER.error(f'[failed] {label} exceeded its deadline.')
            return None
        LOGGER.debug(f'[try] {label}: attempt {attempt}/{retry.attempts}')
        started_at = time.monotonic()
        try:
            result = operation()
        except retry_errors as err:
            elapsed = (time.monotonic() - started_at) * 1000
            failure = (
                f'[failed] {label} failed on attempt {attempt}/{retry.attempts} '
                f'after {elapsed:.1f} ms: {type(err).__name__}: {err}'
            )
            if attempt == retry.attempts:
                LOGGER.error(failure)
                return None
            wait = delay
            if deadline is not None:
                wait = min(wait, max(0.0, deadline - time.monotonic()))
            if wait <= 0 and deadline is not None:
                LOGGER.error(f'[failed] {label} exceeded its deadline.')
                return None
            LOGGER.debug(
                f'[retry] Waiting {wait * 1000:.1f} ms before retrying {label}.'
            )
            if stop_event is not None:
                if stop_event.wait(wait):
                    return None
            else:
                time.sleep(wait)
            if attempt >= retry.backoff_after:
                delay *= retry.backoff
            continue

        elapsed = (time.monotonic() - started_at) * 1000
        if attempt > 1:
            LOGGER.debug(
                f'[ok] {label} recovered on attempt {attempt} after {elapsed:.1f} ms.'
            )
        else:
            LOGGER.debug(f'[ok] {label} completed in {elapsed:.1f} ms.')
        return result
    return None
