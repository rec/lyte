from base64 import b64decode
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import tomlkit
from reccy.protocol import rpc
from ufor import library_files

from lyte import installation, installation_config, rehearsal, wled_output


@pytest.fixture
def definition() -> dict[str, object]:
    return {
        'library_config': str(Path('examples/library.toml').resolve()),
        'fps': 2,
        'twinkly': {'left': {}},
        'wled': {'right': {'host': 'wled.local', 'led_count': 3}},
        'initial_animation': 'grid',
        'animations': {
            'grid': {'selector': 'grid', 'outputs': {'light': 'left * right'}},
            'across': {'selector': 'grid', 'outputs': {'light': 'left + right'}},
        },
    }


@pytest.mark.parametrize(
    'change',
    [
        {'twinkly': {}, 'wled': {}},
        {'wled': {'left': {'host': 'wled.local', 'led_count': 3}}},
        {'wled': {'right': {'host': 'http://wled.local', 'led_count': 3}}},
        {'wled': {'right': {'host': 'wled.local', 'led_count': 0}}},
        {
            'wled': {
                'right': {'host': 'wled.local', 'led_count': 3},
                'other': {'host': 'WLED.local', 'led_count': 3},
            }
        },
    ],
)
def test_invalid_wled_targets_are_rejected(
    definition: dict[str, object], change: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        installation_config.parse_installation(definition | change)


def test_wled_only_build_and_rehearsal_need_no_discovery_or_socket(
    definition: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition['twinkly'] = {}
    definition['animations'] = {
        'grid': {'selector': 'grid', 'outputs': {'light': 'right'}}
    }
    config = installation_config.parse_installation(definition)
    monkeypatch.setattr(
        installation.discovery,
        'discover',
        Mock(side_effect=AssertionError('discovery')),
    )
    monkeypatch.setattr(
        installation, 'WledDdpOutput', Mock(side_effect=AssertionError('socket'))
    )
    service = installation.build_service(config)
    assert service.outputs['right'].led_count == 3
    path = tmp_path / 'installation.toml'
    path.write_text(tomlkit.dumps(definition))
    session = rehearsal.RehearsalSession(rehearsal.RehearsalConfig(config=path))
    frame = session.request(rehearsal.RehearsalRequest(command='step'))
    assert frame['strings'] == {'right': 3}
    assert len(b64decode(frame['frames']['right'])) == 9
    with pytest.raises(ValueError, match='WLED uses configured counts'):
        rehearsal.RehearsalSession(
            rehearsal.RehearsalConfig(config=path, string_counts={'right': 9})
        )


@pytest.mark.parametrize('failure', ['socket', 'send'])
def test_mixed_outputs_continue_after_wled_failure_and_share_controls(
    definition: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    config = installation_config.parse_installation(definition)
    datagrams: list[bytes] = []
    socket = Mock()
    failed = False

    def sendto(packet: bytes, address: tuple[str, int]) -> None:
        nonlocal failed
        assert address == ('wled.local', 4048)
        if failure == 'send' and not failed:
            failed = True
            raise OSError('simulated send failure')
        datagrams.append(packet)

    socket.sendto.side_effect = sendto

    def acquire(host: str, count: int) -> wled_output.WledDdpOutput:
        nonlocal failed
        if failure == 'socket' and not failed:
            failed = True
            raise OSError('simulated socket acquisition failure')
        return wled_output.WledDdpOutput(host, count, socket_factory=lambda *_: socket)

    monkeypatch.setattr(installation, 'WledDdpOutput', acquire)
    right = installation.WledOutput(config.wled['right'], config.timeout)
    left = Mock(led_count=2, status=installation.StringStatus())
    left.open.return_value = True
    left.send.return_value = True
    service = installation.InstallationService.model_construct(
        config=config,
        library=library_files.read_library(Path('examples/library.toml')),
        outputs={'left': left, 'right': right},
        home=tmp_path,
    )
    clock = SimpleNamespace(now=0.0)
    recovered = []

    def advance(seconds: float) -> None:
        clock.now += seconds
        if clock.now == 0.5:
            service.rpc_response(
                rpc.Request(command='master_level', params={'level': 0.5})
            )
            service.rpc_response(
                rpc.Request(
                    command='select_animation',
                    params={'name': 'across', 'duration': 0.5},
                )
            )
        if clock.now == 1:
            recovered.append(right.status.model_copy())
            service.rpc_response(rpc.Request(command='blackout'))

    monkeypatch.setattr(installation.time, 'monotonic', lambda: clock.now)
    monkeypatch.setattr(installation.time, 'sleep', advance)
    for method in ['start', 'close', 'publish_status']:
        monkeypatch.setattr(installation.InstallationService, method, lambda self: None)
    monkeypatch.setattr(
        installation.InstallationService, 'publish_error', lambda self, message: None
    )
    assert service.run(duration=1.5) == 0
    assert left.send.call_count == 3
    np.testing.assert_array_equal(left.send.call_args_list[1].args[1][0], [128, 32, 0])
    assert not left.send.call_args_list[2].args[1].any()
    assert datagrams[0][10:] == bytes([128, 32, 0] * 3)
    assert datagrams[1][10:] == bytes(9)  # Operator blackout.
    assert datagrams[2][10:] == bytes(9)  # Final best-effort blackout.
    assert recovered[0].state == 'sending (unconfirmed)'
    assert recovered[0].failure_count == 1
    assert recovered[0].last_error is None
    assert service.status_snapshot().delivery.output_failures == 1
    socket.settimeout.assert_called_once_with(config.timeout)
    socket.close.assert_called_once()
    left.close.assert_called_once()
