"""Background MIDI daemon command and service definition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import tyro
from reccy import service

from . import daemon_config, daemon_runtime


@dataclass(frozen=True)
class DaemonCommandConfig:
    action: Annotated[
        Literal['run', 'install', 'uninstall', 'start', 'stop', 'restart', 'status'],
        tyro.conf.Positional,
    ] = 'run'
    config: Path = Path('patches/wearable-daemon.toml')


def run_daemon_command(config: DaemonCommandConfig) -> int:
    if config.action == 'run':
        project = daemon_config.load_daemon_project(config.config)
        return daemon_runtime.LyteMidiDaemon(project=project).run()

    daemon = daemon_runtime.LyteMidiDaemon()
    if config.action == 'install':
        result = daemon.install_service(
            ['-m', 'lyte', 'daemon', 'run', '--config', str(config.config.resolve())]
        )
    else:
        result = getattr(daemon, f'{config.action}_service')()
    service.print_service_status(daemon_runtime.LYTE_MIDI_SERVICE.name, result)
    return 0 if result.running is not False else 1
