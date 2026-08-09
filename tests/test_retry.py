from __future__ import annotations

import io
import unittest
from unittest.mock import patch

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

    def test_retry_call_delays_backoff_until_configured_attempt(self) -> None:
        calls = 0
        sleeps = []

        def operation() -> str:
            nonlocal calls
            calls += 1
            if calls < 4:
                raise RetryableTestError('empty reply')
            return 'ok'

        retry = RetryConfig(
            attempts=4,
            delay=0.01,
            backoff=2,
            backoff_after=10,
        )

        with (
            patch('sys.stdout', new_callable=io.StringIO),
            patch(
                'sys.stderr',
                new_callable=io.StringIO,
            ),
            patch('lyte.retry.time.sleep', sleeps.append),
        ):
            result = retry_call(
                'operation',
                retry,
                operation,
                (RetryableTestError,),
            )

        self.assertEqual(result, 'ok')
        self.assertEqual(sleeps, [0.01, 0.01, 0.01])

    def test_retry_call_prints_only_final_failure(self) -> None:
        def operation() -> str:
            raise RetryableTestError('empty reply')

        retry = RetryConfig(
            attempts=3,
            delay=0,
            backoff=1,
            backoff_after=1,
        )
        error_output = io.StringIO()

        with (
            patch('sys.stdout', new_callable=io.StringIO),
            patch('sys.stderr', error_output),
            patch('lyte.retry.time.sleep'),
        ):
            result = retry_call(
                'operation',
                retry,
                operation,
                (RetryableTestError,),
            )

        self.assertIsNone(result)
        self.assertNotIn('attempt 1/3', error_output.getvalue())
        self.assertNotIn('attempt 2/3', error_output.getvalue())
        self.assertIn('attempt 3/3', error_output.getvalue())


class RetryableTestError(Exception):
    pass
