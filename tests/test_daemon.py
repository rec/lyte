from __future__ import annotations

from pathlib import Path

from reccy import models, paths, renderers

from lyte import daemon


def test_midi_daemon_service_has_a_stable_identity() -> None:
    assert daemon.LYTE_MIDI_SERVICE.name == 'lyte-midi'
    assert daemon.LYTE_MIDI_SERVICE.launchd_label == 'com.swirly.lyte-midi'
    assert daemon.LYTE_MIDI_SERVICE.daemon_env_var == 'LYTE_MIDI_DAEMON'


def test_daemon_install_uses_the_foreground_daemon_command(monkeypatch: object) -> None:
    class Controller:
        paths = object()
        metadata: models.DaemonMetadata | None = None

        def install(self, metadata: models.DaemonMetadata) -> models.StatusResult:
            self.metadata = metadata
            return models.StatusResult(installed=True, running=True)

    controller = Controller()
    monkeypatch.setattr(daemon.paths, 'current_platform', lambda: models.Platform.linux)
    monkeypatch.setattr(
        daemon.renderers,
        'service_metadata',
        lambda executable, platform, argv, paths: models.DaemonMetadata(
            executable=executable,
            platform=platform,
            argv=argv,
            control_endpoint='',
        ),
    )
    monkeypatch.setattr(
        daemon.service, 'print_service_status', lambda name, result: None
    )

    result = daemon.install_service(controller, Path('daemon.toml'))

    assert result == 0
    assert controller.metadata is not None
    assert controller.metadata.argv[:4] == ['-m', 'lyte', 'daemon', 'run']
    assert controller.metadata.argv[-1].endswith('daemon.toml')


def test_reccy_service_definitions_have_no_lyte_endpoint(tmp_path: Path) -> None:
    for platform in [models.Platform.linux, models.Platform.macos]:
        service_paths = paths.service_paths(
            daemon.LYTE_MIDI_SERVICE, platform, tmp_path
        )
        metadata = renderers.service_metadata(
            Path('/venv/bin/python'),
            platform,
            ['-m', 'lyte', 'daemon', 'run'],
            service_paths,
        )
        definition = (
            renderers.linux_systemd_unit(
                metadata, service_paths, daemon.LYTE_MIDI_SERVICE
            )
            if platform is models.Platform.linux
            else renderers.macos_launch_agent(
                metadata, service_paths, daemon.LYTE_MIDI_SERVICE
            )
        )

        expected = (
            'lyte daemon run'
            if platform is models.Platform.linux
            else '<string>lyte</string>'
        )
        assert expected in definition.content
        assert 'endpoint' not in definition.content
