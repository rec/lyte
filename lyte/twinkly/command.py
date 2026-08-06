from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

from ..retry import RetryConfig
from . import session
from .client import TwinklyClient
from .diagnostic import DiagnosticConfig
from .realtime import discover_host


def run_twinkly_command(
    config: DiagnosticConfig,
    action: Callable[[TwinklyClient], None],
) -> int:
    host = config.host or discover_host(config.discovery_timeout)
    if host is None:
        return 1

    retry = RetryConfig(
        attempts=config.attempts,
        delay=config.retry_delay,
        backoff=config.retry_backoff,
    )
    client = TwinklyClient(host=host, timeout=config.timeout)
    prepare_authenticated_client(client, retry, host)

    off_succeeded = True
    try:
        action(client)
    finally:
        off_succeeded = session.turn_off_with_retry(client, retry, host)
    return 0 if off_succeeded else 1


def prepare_authenticated_client(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
) -> None:
    gestalt = session.read_gestalt(
        client, retry, session.twinkly_request_label('GET', 'gestalt', host)
    )
    if gestalt is None:
        sys.exit(f'Could not read device info from {host}.')
    session.set_mac_from_gestalt(client, gestalt)
    if session.authenticate_device(
        client, retry, session.twinkly_request_label('POST', 'login', host)
    ):
        return
    sys.exit(f'Could not authenticate with {host}.')


def read_json_object(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        sys.exit(f'{path} must contain a JSON object')
    return data


def write_json_file(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
