from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import mido
import numpy as np
import pytest
import tomlkit
from pytest_regressions.data_regression import DataRegressionFixture
from reccy.protocol import ipc

from lyte import (
    artnet,
    installation,
    installation_config,
    installation_playback,
    rehearsal,
)
from lyte.control_recording import ControlRecorder
from lyte.control_replay import ControlReplay
from lyte.installation_dmx import ArtNetOutput


@pytest.fixture
def definition() -> dict[str, object]:
    data = tomlkit.parse(Path('examples/installation-laser.toml').read_text()).unwrap()
    data['dmx']['laser']['profile'] = str(
        Path('examples/fixtures/laser.toml').resolve()
    )
    return data


def test_laser_values_cut_preserve_centres_and_black_out_only_mode(
    definition: dict[str, object], data_regression: DataRegressionFixture
) -> None:
    config = installation_config.parse_installation(definition)
    engine = installation_playback.InstallationPlayback(
        config, installation_playback.load_library(config), {}
    )
    engine.select('idle')
    assert isinstance(engine.command('test', {}), ipc.Error)
    snapshots = {}
    for tick, (name, params) in enumerate(
        [
            ('select_animation', {'name': 'circle'}),
            ('select_animation', {'name': 'square', 'duration': 2}),
            ('master_level', {'level': 0}),
            ('blackout', {}),
        ]
    ):
        engine.command(name, params)
        assert engine.render(tick) == []
        snapshots[name + str(tick)] = engine.dmx_frames[1].slots[:9].tolist()
        assert not engine.dmx_frames[1].slots[9:].any()
    data_regression.check(snapshots)
    assert snapshots['select_animation0'] == [192, 0, 64, 64, 64, 64, 64, 64, 128]
    assert snapshots['blackout3'][0] == 0
    assert snapshots['blackout3'][1:] == snapshots['master_level2'][1:]


def test_fixture_controls_and_recording_replay_share_delivery_boundaries(
    definition: dict[str, object], tmp_path: Path
) -> None:
    definition['initial_animation'] = 'circle'
    definition['midi'] = {'channel': 1}
    definition['animation_defaults'] = {
        'activation': 'note',
        'controls': [
            {
                'source': 'breath',
                'fixture': 'laser',
                'parameter': 'hpos',
                'output': [64, 255],
            }
        ],
    }
    config = installation_config.parse_installation(definition)
    library = installation_playback.load_library(config)
    engine = installation_playback.InstallationPlayback(config, library, {})
    engine.select('circle')
    destination = tmp_path / 'recording.jsonl'
    engine.recorder = ControlRecorder(destination)
    engine.recorder.start(config, library)
    expected = []
    for tick in range(3):
        if tick == 1:
            engine.receive_midi(mido.Message('note_on', note=60, velocity=100))
            engine.receive_midi(mido.Message('control_change', control=2, value=127))
        engine.render(tick / 30)
        expected.append(engine.dmx_frames[1].slots.copy())
    engine.recorder.close()
    assert expected[0][0] == 0
    assert expected[1][0] == 192 and expected[1][6] == 255
    replay = ControlReplay(destination)
    assert 'fixture:laser' in replay.header.scores
    actual = installation_playback.InstallationPlayback(config, library, {})
    actual.select('circle')
    for frame in expected:
        at = replay.apply(actual)
        assert at is not None
        actual.render(at)
        np.testing.assert_array_equal(actual.dmx_frames[1].slots, frame)
        replay.advance()
    replay.stream.close()


@pytest.mark.parametrize(
    'problem', ['overlap', 'range', 'choice', 'control', 'blackout', 'wire']
)
def test_invalid_fixture_configuration_fails_before_discovery(
    definition: dict[str, object], problem: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = definition['dmx']['laser']
    if problem == 'overlap':
        definition['dmx']['other'] = dict(fixture)
        for look in definition['animations'].values():
            look['fixtures']['other'] = {}
    elif problem == 'range':
        fixture['start_channel'] = 510
    elif problem == 'choice':
        fixture['defaults']['pattern'] = 'missing-pattern'
    elif problem == 'control':
        definition['midi'] = {}
        definition['animation_defaults'] = {
            'controls': [
                {
                    'fixture': 'laser',
                    'source': 'breath',
                    'parameter': 'zoom',
                    'output': [0, 256],
                }
            ]
        }
    elif problem == 'blackout':
        fixture['blackout']['unknown'] = 0
    else:
        definition['artnet']['universe_offset'] = 32768
    discovery = Mock(side_effect=AssertionError('must not discover'))
    monkeypatch.setattr(installation, 'discover_assignments', discovery)
    with pytest.raises(ValueError):
        installation.build_service(installation_config.parse_installation(definition))
    discovery.assert_not_called()


def test_two_fixtures_share_one_artnet_packet_and_rehearsal_has_no_network(
    definition: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition['dmx']['other'] = definition['dmx']['laser'] | {'start_channel': 10}
    for look in definition['animations'].values():
        look['fixtures']['other'] = {
            'mode': 'manual',
            'pattern': 'star',
            'color': 'red',
        }
    path = tmp_path / 'installation.toml'
    path.write_text(tomlkit.dumps(definition))
    socket = Mock()
    monkeypatch.setattr(artnet.socket, 'socket', socket)
    session = rehearsal.RehearsalSession(rehearsal.RehearsalConfig(config=path))
    result = session.request(rehearsal.RehearsalRequest(command='step'))
    socket.assert_not_called()
    assert result['dmx_frames'][1][:18] == [
        0,
        0,
        64,
        64,
        64,
        64,
        64,
        64,
        128,
        192,
        56,
        64,
        64,
        64,
        64,
        64,
        64,
        64,
    ]
    target = ArtNetOutput(artnet.ArtNetEndpoint(host='127.0.0.1'), [1], 0.1)
    assert target.send(session.playback.dmx_frames)
    datagram = socket.return_value.sendto.call_args.args[0]
    assert datagram[:8] == b'Art-Net\x00'
    assert datagram[14:16] == b'\x00\x00'
    assert datagram[18:] == bytes(result['dmx_frames'][1])
    socket.return_value.sendto.assert_called_once()
    target.close()


def test_artnet_failure_does_not_stop_pixels_and_shutdown_uses_profile_blackout(
    definition: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition['library_config'] = str(Path('examples/library.toml').resolve())
    definition['twinkly'] = {'pixels': {}}
    definition['fps'] = 2
    definition['initial_animation'] = 'circle'
    for look in definition['animations'].values():
        look.update(selector='grid', outputs={'light': 'pixels'})
    config = installation_config.parse_installation(definition)
    socket = Mock()
    socket.sendto.side_effect = [OSError('simulated outage'), None, None]
    monkeypatch.setattr(artnet.socket, 'socket', lambda *_: socket)
    pixels = Mock(led_count=2, status=installation.StringStatus())
    pixels.open.return_value = pixels.send.return_value = True
    service = installation.InstallationService.model_construct(
        config=config,
        library=installation_playback.load_library(config),
        outputs={'pixels': pixels},
        home=tmp_path,
    )
    clock = SimpleNamespace(now=0.0)

    def advance(seconds: float) -> None:
        clock.now += seconds

    monkeypatch.setattr(installation.time, 'monotonic', lambda: clock.now)
    monkeypatch.setattr(installation.time, 'sleep', advance)
    for method in ['start', 'close', 'publish_status']:
        monkeypatch.setattr(installation.InstallationService, method, lambda self: None)
    assert service.run(duration=1) == 0
    assert pixels.send.call_count == 2
    assert service.artnet_output.status.failure_count == 1
    assert socket.sendto.call_args.args[0][18:27] == bytes(
        [0, 0, 64, 64, 64, 64, 64, 64, 128]
    )
    socket.close.assert_called_once()


def test_failed_profile_fingerprint_disables_recording_without_stopping_fixture(
    definition: dict[str, object], tmp_path: Path
) -> None:
    profile = tmp_path / 'laser.toml'
    profile.write_bytes(Path('examples/fixtures/laser.toml').read_bytes())
    definition['dmx']['laser']['profile'] = str(profile)
    config = installation_config.parse_installation(definition)
    library = installation_playback.load_library(config)
    engine = installation_playback.InstallationPlayback(config, library, {})
    engine.select('circle')
    # Simulate the source becoming unavailable after the profile was prepared.
    profile.rename(tmp_path / 'moved.toml')
    engine.recorder = ControlRecorder(tmp_path / 'capture.jsonl')
    engine.recorder.start(config, library)
    assert engine.recorder.error is not None
    engine.render(0)
    assert engine.dmx_frames[1].slots[0] == 192
