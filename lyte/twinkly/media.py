from __future__ import annotations

from typing import Literal

from ..logging import log_status
from .client import TwinklyClient
from .command import run_twinkly_command
from .diagnostic import DiagnosticConfig

MovieAction = Literal['config', 'list', 'current']
PlaylistAction = Literal['list', 'current']


def run_movie_control(config: DiagnosticConfig, action: MovieAction) -> int:
    def run(client: TwinklyClient) -> None:
        if action == 'config':
            log_status(f'[movie] config {client.get_movie_config().data}')
        elif action == 'list':
            log_status(f'[movie] list {client.get_movies().data}')
        else:
            log_status(f'[movie] current {client.get_current_movie().data}')

    return run_twinkly_command(config, run)


def run_playlist_control(config: DiagnosticConfig, action: PlaylistAction) -> int:
    def run(client: TwinklyClient) -> None:
        if action == 'list':
            log_status(f'[playlist] list {client.get_playlist().data}')
        else:
            log_status(f'[playlist] current {client.get_current_playlist_entry().data}')

    return run_twinkly_command(config, run)
