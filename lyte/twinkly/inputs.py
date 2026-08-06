from __future__ import annotations

from typing import Literal

from ..logging import log_status
from .client import TwinklyClient
from .command import run_twinkly_command
from .diagnostic import DiagnosticConfig

MqttAction = Literal['config']
MicAction = Literal['config', 'sample']
MusicAction = Literal['drivers', 'driver-sets', 'current-driver-set']


def run_mqtt_control(config: DiagnosticConfig, action: MqttAction) -> int:
    def run(client: TwinklyClient) -> None:
        if action == 'config':
            log_status(f'[mqtt] config {client.get_mqtt_config().data}')

    return run_twinkly_command(config, run)


def run_mic_control(config: DiagnosticConfig, action: MicAction) -> int:
    def run(client: TwinklyClient) -> None:
        if action == 'config':
            log_status(f'[mic] config {client.get_mic_config().data}')
        else:
            log_status(f'[mic] sample {client.get_mic_sample().data}')

    return run_twinkly_command(config, run)


def run_music_control(config: DiagnosticConfig, action: MusicAction) -> int:
    def run(client: TwinklyClient) -> None:
        if action == 'drivers':
            log_status(f'[music] drivers {client.get_music_drivers().data}')
        elif action == 'driver-sets':
            log_status(f'[music] driver-sets {client.get_music_driver_sets().data}')
        else:
            log_status(
                f'[music] current-driver-set '
                f'{client.get_current_music_driver_set().data}'
            )

    return run_twinkly_command(config, run)
