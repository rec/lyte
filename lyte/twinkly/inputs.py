from __future__ import annotations

from typing import Literal

from reccy import logging

from .client import TwinklyClient
from .command import run_twinkly_command
from .diagnostic import DiagnosticConfig

MqttAction = Literal['config']
MicAction = Literal['config', 'sample']
MusicAction = Literal['drivers', 'driver-sets', 'current-driver-set']


LOGGER = logging.get_logger(__name__)


def run_mqtt_control(config: DiagnosticConfig, action: MqttAction) -> int:
    def run(client: TwinklyClient) -> None:
        if action == 'config':
            LOGGER.info(f'[mqtt] config {client.get_mqtt_config().data}')

    return run_twinkly_command(config, run)


def run_mic_control(config: DiagnosticConfig, action: MicAction) -> int:
    def run(client: TwinklyClient) -> None:
        if action == 'config':
            LOGGER.info(f'[mic] config {client.get_mic_config().data}')
        else:
            LOGGER.info(f'[mic] sample {client.get_mic_sample().data}')

    return run_twinkly_command(config, run)


def run_music_control(config: DiagnosticConfig, action: MusicAction) -> int:
    def run(client: TwinklyClient) -> None:
        if action == 'drivers':
            LOGGER.info(f'[music] drivers {client.get_music_drivers().data}')
        elif action == 'driver-sets':
            LOGGER.info(f'[music] driver-sets {client.get_music_driver_sets().data}')
        else:
            LOGGER.info(
                f'[music] current-driver-set '
                f'{client.get_current_music_driver_set().data}'
            )

    return run_twinkly_command(config, run)
