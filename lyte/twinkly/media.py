from __future__ import annotations

from typing import Literal

from reccy.runtime import logging
from tinkly.client import TwinklyClient

from .command import run_twinkly_command
from .diagnostic import DiagnosticConfig

MovieAction = Literal['config', 'list', 'current']
PlaylistAction = Literal['list', 'current']


LOGGER = logging.get_logger(__name__)


def run_movie_control(config: DiagnosticConfig, action: MovieAction) -> int:
    def run(client: TwinklyClient) -> None:
        if action == 'config':
            LOGGER.info(f'[movie] config {client.movie_config.data}')
        elif action == 'list':
            LOGGER.info(f'[movie] list {client.movies.data}')
        else:
            LOGGER.info(f'[movie] current {client.current_movie.data}')

    return run_twinkly_command(config, run)


def run_playlist_control(config: DiagnosticConfig, action: PlaylistAction) -> int:
    def run(client: TwinklyClient) -> None:
        if action == 'list':
            LOGGER.info(f'[playlist] list {client.playlist.data}')
        else:
            LOGGER.info(f'[playlist] current {client.current_playlist_entry.data}')

    return run_twinkly_command(config, run)
