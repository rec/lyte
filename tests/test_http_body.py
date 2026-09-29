from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lyte import http_body


def test_body_reader_accepts_complete_chunks() -> None:
    connection = Mock()
    connection.gettimeout.return_value = 5
    handler = SimpleNamespace(
        headers={'Content-Length': '5'},
        connection=connection,
        rfile=BytesIO(b'hello'),
    )

    assert http_body.read_body(handler) == b'hello'
    connection.settimeout.assert_called_with(5)


def test_body_reader_rejects_truncated_body() -> None:
    handler = SimpleNamespace(
        headers={'Content-Length': '5'},
        connection=Mock(gettimeout=Mock(return_value=5)),
        rfile=BytesIO(b'hi'),
    )

    with pytest.raises(ValueError, match='ended early'):
        http_body.read_body(handler)


def test_body_reader_has_absolute_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = SimpleNamespace(now=0.0)

    class SlowBody:
        def read1(self, count: int) -> bytes:
            clock.now += 3
            return b'a'

    handler = SimpleNamespace(
        headers={'Content-Length': '5'},
        connection=Mock(gettimeout=Mock(return_value=5)),
        rfile=SlowBody(),
    )
    monkeypatch.setattr(http_body.time, 'monotonic', lambda: clock.now)

    with pytest.raises(TimeoutError, match='timed out'):
        http_body.read_body(handler)
