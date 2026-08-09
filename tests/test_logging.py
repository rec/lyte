from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from lyte.logging import LOGGING, log, log_error, log_status


class LoggingTests(unittest.TestCase):
    def test_logging_is_disabled_by_default(self) -> None:
        self.assertFalse(LOGGING)

    def test_error_logging_is_always_displayed(self) -> None:
        output = io.StringIO()

        with patch('sys.stderr', output):
            log_error('failure')

        self.assertEqual(output.getvalue(), 'failure\n')

    def test_regular_logging_is_hidden_by_default(self) -> None:
        output = io.StringIO()

        with patch('sys.stdout', output):
            log('hidden')

        self.assertEqual(output.getvalue(), '')

    def test_status_logging_is_always_displayed(self) -> None:
        output = io.StringIO()

        with patch('sys.stdout', output):
            log_status('visible')

        self.assertEqual(output.getvalue(), 'visible\n')
