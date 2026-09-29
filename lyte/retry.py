"""Retry helpers for transient lyte network operations."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable

from pydantic import BaseModel
from reccy.runtime import logging
from reccy.runtime.retry import RetryPolicy, RetrySchedule, RetryStopReason

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
    schedule = RetrySchedule(
        RetryPolicy(
            attempts=retry.attempts,
            delay=retry.delay,
            backoff=retry.backoff,
            backoff_after=retry.backoff_after,
            # lyte previously had no finite delay cap.
            max_delay=sys.float_info.max,
        ),
        clock=time.monotonic,
        deadline=deadline,
    )
    while True:
        if stop_event is not None and stop_event.is_set():
            return None
        if (wait := schedule.seconds_until_attempt()) is None:
            if schedule.stop_reason is RetryStopReason.deadline:
                LOGGER.error(f'[failed] {label} exceeded its deadline.')
            return None
        if wait > 0:
            if stop_event is not None:
                if stop_event.wait(wait):
                    return None
            else:
                time.sleep(wait)
            continue
        if not schedule.begin_attempt():
            continue
        attempt = schedule.attempt_count
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
            schedule.failed()
            if (wait := schedule.seconds_until_attempt()) is not None:
                LOGGER.debug(
                    f'[retry] Waiting {wait * 1000:.1f} ms before retrying {label}.'
                )
            continue

        elapsed = (time.monotonic() - started_at) * 1000
        if attempt > 1:
            LOGGER.debug(
                f'[ok] {label} recovered on attempt {attempt} after {elapsed:.1f} ms.'
            )
        else:
            LOGGER.debug(f'[ok] {label} completed in {elapsed:.1f} ms.')
        return result
