from __future__ import annotations

from typing import Literal

from reccy.runtime import logging
from tinkly.client import TwinklyClient

from .command import run_twinkly_command
from .diagnostic import DiagnosticConfig

NetworkAction = Literal['status', 'scan', 'scan-results']


LOGGER = logging.get_logger(__name__)


def run_network_control(config: DiagnosticConfig, action: NetworkAction) -> int:
    def run(client: TwinklyClient) -> None:
        if action == 'status':
            LOGGER.info(f'[network] status {client.network_status.data}')
        elif action == 'scan':
            LOGGER.info(f'[network] scan {client.start_network_scan().data}')
        else:
            LOGGER.info(f'[network] scan-results {client.network_scan_results.data}')

    return run_twinkly_command(config, run)
