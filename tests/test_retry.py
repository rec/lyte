from __future__ import annotations

import io
import unittest
from unittest.mock import Mock, patch

from lyte.retry import RetryConfig, retry_call


class RetryTests(unittest.TestCase):
    def test_retry_call_retries_retryable_result_failures(self) -> None:
        calls = 0

        def operation() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RetryableTestError('empty reply')
            return 'ok'

        retry = RetryConfig(
            attempts=2,
            delay=0,
            backoff=1,
            backoff_after=1,
        )

        with (
            patch('sys.stdout', new_callable=io.StringIO),
            patch(
                'sys.stderr',
                new_callable=io.StringIO,
            ),
        ):
            result = retry_call(
                'operation',
                retry,
                operation,
                (RetryableTestError,),
            )

        self.assertEqual(result, 'ok')
        self.assertEqual(calls, 2)

    def test_retry_call_keeps_deferred_uncapped_backoff(self) -> None:
        calls = 0
        clock = 0.0
        sleeps: list[float] = []

        def now() -> float:
            return clock

        def sleep(seconds: float) -> None:
            nonlocal clock
            sleeps.append(seconds)
            clock += seconds

        def operation() -> str:
            nonlocal calls
            calls += 1
            if calls < 4:
                raise RetryableTestError('empty reply')
            return 'ok'

        retry = RetryConfig(
            attempts=4,
            delay=30,
            backoff=3,
            backoff_after=2,
        )

        with (
            patch('sys.stdout', new_callable=io.StringIO),
            patch(
                'sys.stderr',
                new_callable=io.StringIO,
            ),
            patch('lyte.retry.time.monotonic', now),
            patch('lyte.retry.time.sleep', sleep),
        ):
            result = retry_call(
                'operation',
                retry,
                operation,
                (RetryableTestError,),
            )

        self.assertEqual(result, 'ok')
        self.assertEqual(sleeps, [30, 30, 90])

    def test_retry_call_prints_only_final_failure(self) -> None:
        def operation() -> str:
            raise RetryableTestError('empty reply')

        retry = RetryConfig(
            attempts=3,
            delay=0,
            backoff=1,
            backoff_after=1,
        )
        with (
            patch('lyte.retry.LOGGER.error') as log_error,
            patch('lyte.retry.time.sleep'),
        ):
            result = retry_call(
                'operation',
                retry,
                operation,
                (RetryableTestError,),
            )

        self.assertIsNone(result)
        log_error.assert_called_once()
        self.assertIn('attempt 3/3', log_error.call_args.args[0])

    def test_retry_call_stops_when_cancelled_during_wait(self) -> None:
        calls = 0
        stop_event = Mock()
        stop_event.is_set.return_value = False
        stop_event.wait.return_value = True

        def operation() -> str:
            nonlocal calls
            calls += 1
            raise RetryableTestError('empty reply')

        result = retry_call(
            'operation',
            RetryConfig(attempts=3, delay=1, backoff=2),
            operation,
            (RetryableTestError,),
            stop_event=stop_event,
        )

        self.assertIsNone(result)
        self.assertEqual(calls, 1)
        stop_event.wait.assert_called_once()

    def test_retry_call_stops_at_deadline_before_another_attempt(self) -> None:
        clock = 0.0
        sleeps: list[float] = []
        calls = 0

        def now() -> float:
            return clock

        def sleep(seconds: float) -> None:
            nonlocal clock
            sleeps.append(seconds)
            clock += seconds

        def operation() -> str:
            nonlocal calls
            calls += 1
            raise RetryableTestError('empty reply')

        with (
            patch('lyte.retry.time.monotonic', now),
            patch('lyte.retry.time.sleep', sleep),
            patch('lyte.retry.LOGGER.error') as log_error,
        ):
            result = retry_call(
                'operation',
                RetryConfig(attempts=3, delay=10, backoff=2),
                operation,
                (RetryableTestError,),
                deadline=3,
            )

        self.assertIsNone(result)
        self.assertEqual(calls, 1)
        self.assertEqual(sleeps, [3])
        log_error.assert_called_once_with('[failed] operation exceeded its deadline.')


class RetryableTestError(Exception):
    pass
