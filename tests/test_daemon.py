from __future__ import annotations

from pathlib import Path

from reccy import models, paths, renderers

from lyte import daemon, daemon_runtime


def test_midi_daemon_service_has_a_stable_identity() -> None:
    assert daemon_runtime.LYTE_MIDI_SERVICE.name == 'lyte-midi'
    assert daemon_runtime.LYTE_MIDI_SERVICE.launchd_label == 'com.swirly.lyte-midi'
    assert daemon_runtime.LYTE_MIDI_SERVICE.daemon_env_var == 'LYTE_MIDI_DAEMON'


def test_reccy_daemon_metadata_uses_the_foreground_daemon_command(
    tmp_path: Path,
) -> None:
    midi_daemon = daemon_runtime.LyteMidiDaemon(home=tmp_path)

    metadata = midi_daemon.service_metadata(
        ['-m', 'lyte', 'daemon', 'run', '--config', '/tmp/daemon.toml']
    )

    assert metadata.argv[:4] == ['-m', 'lyte', 'daemon', 'run']
    assert metadata.argv[-1] == '/tmp/daemon.toml'


def test_daemon_install_uses_reccy_application(
    tmp_path: Path, monkeypatch: object
) -> None:
    class MidiDaemon:
        argv: list[str] | None = None

        def install_service(self, argv: list[str]) -> models.StatusResult:
            self.argv = argv
            return models.StatusResult(installed=True, running=True)

    midi_daemon = MidiDaemon()
    monkeypatch.setattr(daemon.daemon_runtime, 'LyteMidiDaemon', lambda: midi_daemon)
    monkeypatch.setattr(
        daemon.service, 'print_service_status', lambda name, result: None
    )

    result = daemon.run_daemon_command(
        daemon.DaemonCommandConfig(action='install', config=tmp_path / 'daemon.toml')
    )

    assert result == 0
    assert midi_daemon.argv is not None
    assert midi_daemon.argv[:4] == ['-m', 'lyte', 'daemon', 'run']
    assert midi_daemon.argv[-1].endswith('daemon.toml')


def test_reccy_service_definitions_start_the_foreground_daemon(tmp_path: Path) -> None:
    for platform in [models.Platform.linux, models.Platform.macos]:
        service_paths = paths.service_paths(
            daemon_runtime.LYTE_MIDI_SERVICE, platform, tmp_path
        )
        metadata = renderers.service_metadata(
            Path('/venv/bin/python'),
            platform,
            ['-m', 'lyte', 'daemon', 'run'],
            service_paths,
        )
        definition = (
            renderers.linux_systemd_unit(
                metadata, service_paths, daemon_runtime.LYTE_MIDI_SERVICE
            )
            if platform is models.Platform.linux
            else renderers.macos_launch_agent(
                metadata, service_paths, daemon_runtime.LYTE_MIDI_SERVICE
            )
        )

        expected = (
            'lyte daemon run'
            if platform is models.Platform.linux
            else '<string>lyte</string>'
        )
        assert expected in definition.content
