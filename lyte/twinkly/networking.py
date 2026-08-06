from __future__ import annotations

from typing import Literal

from ..logging import log_status
from .client import TwinklyClient
from .command import run_twinkly_command
from .diagnostic import DiagnosticConfig

NetworkAction = Literal['status', 'scan', 'scan-results']


def run_network_control(config: DiagnosticConfig, action: NetworkAction) -> int:
    def run(client: TwinklyClient) -> None:
        if action == 'status':
            log_status(f'[network] status {client.get_network_status().data}')
        elif action == 'scan':
            log_status(f'[network] scan {client.get_network_scan().data}')
        else:
            log_status(
                f'[network] scan-results {client.get_network_scan_results().data}'
            )

    return run_twinkly_command(config, run)
