from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from lyte import daemon_config


def write_config(path: Path, patches: str) -> None:
    path.write_text(
        '[daemon]\n'
        'patch_library = "wearable.toml"\n'
        f'patches = {patches}\n'
        '[midi]\n'
        'channel = 0\n'
        '[twinkly]\n'
    )


def test_daemon_config_rejects_an_empty_patch_list() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'daemon.toml'
        write_config(path, '[]')

        with pytest.raises(daemon_config.DaemonConfigError, match='must not be empty'):
            daemon_config.load_daemon_project(path)


def test_daemon_config_rejects_duplicate_patch_names() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'daemon.toml'
        write_config(path, '["first", "first"]')

        with pytest.raises(daemon_config.DaemonConfigError, match='duplicates'):
            daemon_config.load_daemon_project(path)
