"""Bounded request-body reads for local browser tools."""

import time
from http.server import BaseHTTPRequestHandler


def read_body(handler: BaseHTTPRequestHandler, timeout: float = 5.0) -> bytes:
    length = int(handler.headers.get('Content-Length', '0'))
    if not 0 < length <= 65536:
        raise ValueError('request body must be between 1 and 65536 bytes')
    deadline = time.monotonic() + timeout
    previous_timeout = handler.connection.gettimeout()
    chunks: list[bytes] = []
    try:
        while length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('request body timed out')
            handler.connection.settimeout(remaining)
            chunk = handler.rfile.read1(min(length, 8192))
            if not chunk:
                raise ValueError('request body ended early')
            chunks.append(chunk)
            length -= len(chunk)
    finally:
        handler.connection.settimeout(previous_timeout)
    return b''.join(chunks)
