from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import mido
import numpy as np
import pytest
from pydantic import ValidationError
from ufor import library_files

from lyte import installation, installation_config, installation_playback
from lyte.twinkly.diagnostic import TwinklyDeviceInfo


def config_data() -> dict[str, object]:
    return {
        'library_config': str(Path('examples/library.toml').resolve()),
        'twinkly': {'dots': {'product_name': 'Dots'}, 'strings': {}},
        'initial_animation': 'show',
        'animations': {
            'show': {
                'selector': 'grid',
                'outputs': {'light': 'dots + strings'},
            }
        },
    }


@pytest.mark.parametrize('value', [0, -1, float('inf'), float('nan')])
def test_setup_timeout_requires_a_positive_finite_value(value: float) -> None:
    with pytest.raises(ValidationError, match='setup_timeout'):
        installation_config.parse_installation(config_data() | {'setup_timeout': value})


def test_partial_twinkly_open_attempts_blackout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assignment = installation.TwinklyAssignment(
        'dots',
        '192.0.2.1',
        TwinklyDeviceInfo.from_gestalt({'product_name': 'Dots'}),
    )
    output = installation.TwinklyOutput(
        assignment, installation_config.parse_installation(config_data())
    )
    output.track = Mock()
    output.track.prepare.return_value = True
    monkeypatch.setattr(
        installation.socket, 'socket', Mock(side_effect=OSError('no descriptors'))
    )

    with pytest.raises(OSError, match='no descriptors'):
        output.open()

    output.track.close.assert_called_once()
    assert output.socket is None


def test_output_setup_receives_stop_event_and_shared_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = installation_config.parse_installation(
        config_data() | {'setup_timeout': 7}
    )
    assignment = installation.TwinklyAssignment(
        'dots',
        '192.0.2.1',
        TwinklyDeviceInfo.from_gestalt({'product_name': 'Dots'}),
    )
    output = installation.TwinklyOutput(assignment, config)
    service = installation.InstallationService.model_construct(
        config=config,
        library=library_files.read_library(Path('examples/library.toml')),
        outputs={'dots': output},
        home=tmp_path,
    )

    def open_output(deadline: float) -> bool:
        assert deadline == 12
        assert output.track.stop_event is service._stop_requested
        return False

    output.open = Mock(side_effect=open_output)
    monkeypatch.setattr(installation.time, 'monotonic', lambda: 5.0)
    monkeypatch.setattr(installation.InstallationService, 'start', lambda self: None)
    monkeypatch.setattr(installation.InstallationService, 'close', lambda self: None)
    monkeypatch.setattr(
        installation_playback.InstallationPlayback, 'select', lambda self, name: None
    )

    assert service.run() == 1


def test_discovery_accumulates_answers_from_separate_scans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = installation_config.parse_installation(config_data())
    scans = iter(
        [
            [
                installation.discovery.DiscoveredDevice(
                    ip_address='192.0.2.1', device_id='dots'
                )
            ],
            [
                installation.discovery.DiscoveredDevice(
                    ip_address='192.0.2.2', device_id='strings'
                )
            ],
        ]
    )
    monkeypatch.setattr(installation.discovery, 'discover', lambda timeout: next(scans))
    monkeypatch.setattr(installation.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(
        installation.session,
        'read_gestalt',
        lambda client, retry, label, deadline: {
            'product_name': 'Dots' if client.host.endswith('.1') else 'Strings',
            'mac': client.host,
        },
    )

    assignments = installation.discover_assignments(config)

    assert assignments['dots'].host == '192.0.2.1'
    assert assignments['strings'].host == '192.0.2.2'


def test_continuous_midi_input_cannot_monopolize_delivery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = installation_config.parse_installation(config_data() | {'midi': {}})
    service = installation.InstallationService.model_construct(
        config=config, library=None, outputs={}, home=tmp_path
    )
    service._midi_port = Mock()
    service.playback.receive_midi = Mock()
    publish_status = Mock()
    monkeypatch.setattr(
        installation.InstallationService, 'publish_status', publish_status
    )

    def messages(port: object, midi_config: object) -> Iterator[mido.Message]:
        while True:
            yield mido.Message('note_on', note=60, velocity=100)

    monkeypatch.setattr(installation, 'input_messages', messages)

    service._process_midi(0)

    assert (
        service.playback.receive_midi.call_count
        == installation.MAX_MIDI_MESSAGES_PER_FRAME
    )
    publish_status.assert_called_once()


def test_shutdown_closes_other_outputs_after_one_close_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = installation_config.parse_installation(config_data() | {'fps': 1})
    outputs = {
        name: Mock(led_count=2, status=installation.StringStatus())
        for name in ['dots', 'strings']
    }
    for output in outputs.values():
        output.open.return_value = True
        output.send.return_value = True
    outputs['dots'].close.side_effect = RuntimeError('close failed')
    service = installation.InstallationService.model_construct(
        config=config, library=None, outputs=outputs, home=tmp_path
    )
    service.playback.active = Mock(name='active')
    service.playback.active.name = 'show'
    service.playback.active.render.return_value = [
        (name, np.zeros((2, 3), dtype=np.uint8)) for name in outputs
    ]
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(installation.time, 'monotonic', lambda: clock.now)
    monkeypatch.setattr(
        installation.time,
        'sleep',
        lambda seconds: setattr(clock, 'now', clock.now + seconds),
    )
    monkeypatch.setattr(installation.InstallationService, 'start', lambda self: None)
    close_service = Mock()
    monkeypatch.setattr(installation.InstallationService, 'close', close_service)
    monkeypatch.setattr(
        installation_playback.InstallationPlayback, 'select', lambda self, name: None
    )

    assert service.run(duration=1) == 0
    outputs['dots'].close.assert_called_once()
    outputs['strings'].close.assert_called_once()
    close_service.assert_called_once_with()


def test_failed_selection_keeps_active_animation_and_reports_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playback = installation_playback.InstallationPlayback(
        installation_config.parse_installation(config_data()),
        library_files.read_library(Path('examples/library.toml')),
        {'dots': 2, 'strings': 3},
    )
    playback.select('show')
    active = playback.active
    playback.queued_name = 'show'
    monkeypatch.setattr(
        installation_playback,
        'ActiveAnimation',
        Mock(side_effect=ValueError('cannot prepare')),
    )

    frames = playback.render(0)

    assert len(frames) == 2
    assert playback.active is active
    assert playback.selection_error == 'show: cannot prepare'
