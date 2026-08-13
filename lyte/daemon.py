"""Background MIDI daemon command and service definition."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import tyro
from reccy import models, paths, renderers, service

from . import daemon_config, daemon_runtime

LYTE_MIDI_SERVICE = models.ServiceSpec(
    name='lyte-midi',
    display_name='Lyte MIDI',
    description='Lyte MIDI patch player',
    launchd_label='com.swirly.lyte-midi',
    daemon_env_var='LYTE_MIDI_DAEMON',
    windows_pipe=r'\.\pipe\lyte-midi',
)


@dataclass(frozen=True)
class DaemonCommandConfig:
    action: Annotated[
        Literal['run', 'install', 'uninstall', 'start', 'stop', 'restart', 'status'],
        tyro.conf.Positional,
    ] = 'run'
    config: Path = Path('lyte-daemon.toml')


def run_daemon_command(config: DaemonCommandConfig) -> int:
    if config.action == 'run':
        project = daemon_config.load_daemon_project(config.config)
        return daemon_runtime.run_daemon(project)
    controller = service.ServiceController(LYTE_MIDI_SERVICE, paths.current_platform())
    if config.action == 'install':
        return install_service(controller, config.config)
    result = getattr(controller, config.action)()
    service.print_service_status(LYTE_MIDI_SERVICE.name, result)
    return 0 if result.running is not False else 1


def install_service(controller: service.ServiceController, config: Path) -> int:
    platform = paths.current_platform()
    metadata = renderers.service_metadata(
        Path(sys.executable),
        platform,
        ['-m', 'lyte', 'daemon', 'run', '--config', str(config.resolve())],
        controller.paths,
    )
    result = controller.install(metadata)
    service.print_service_status(LYTE_MIDI_SERVICE.name, result)
    return 0 if result.running else 1
