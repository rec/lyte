from base64 import b64encode
from pathlib import Path

import mido
import pytest
import tomlkit

from lyte import control_recording, rehearsal


@pytest.fixture
def installation_path(tmp_path: Path) -> Path:
    path = tmp_path / 'installation.toml'
    path.write_text(
        tomlkit.dumps(
            {
                'library_config': str(Path('examples/library.toml').resolve()),
                'fps': 30,
                'initial_animation': 'a',
                'midi': {},
                'twinkly': {'left': {}, 'right': {}},
                'animations': {
                    'a': {
                        'selector': 'aurora',
                        'activation': 'note',
                        'outputs': {'light': 'left + right'},
                    },
                    'b': {'selector': 'grid', 'outputs': {'light': 'left * right'}},
                },
            }
        )
    )
    return path


def test_recording_replays_midi_operator_commands_and_delivery_times_exactly(
    installation_path: Path, tmp_path: Path
) -> None:
    destination = tmp_path / 'performance.jsonl'
    live = rehearsal.RehearsalSession(
        rehearsal.RehearsalConfig(
            config=installation_path,
            string_counts={'left': 3, 'right': 5},
            record_input=destination,
        )
    )
    expected = []
    for index in range(12):
        if index in [0, 5]:
            live.request(
                rehearsal.RehearsalRequest(
                    command='midi',
                    params=mido.Message(
                        'note_on', channel=1, note=60 + index, velocity=90
                    ).dict(),
                )
            )
        if index == 1:
            live.request(
                rehearsal.RehearsalRequest(
                    command='midi',
                    params=mido.Message('note_off', channel=0, note=60).dict(),
                )
            )
        if index == 2:
            live.request(
                rehearsal.RehearsalRequest(
                    command='select_animation', params={'name': 'b', 'duration': 0.3}
                )
            )
        if index == 4:
            live.request(
                rehearsal.RehearsalRequest(
                    command='master_level', params={'level': 0.4}
                )
            )
        if index == 6:
            live.request(
                rehearsal.RehearsalRequest(command='test', params={'duration': 0.04})
            )
        if index == 8:
            live.request(rehearsal.RehearsalRequest(command='blackout'))
        if index == 9:
            live.request(
                rehearsal.RehearsalRequest(
                    command='select_animation', params={'name': 'a'}
                )
            )
        if index == 10:
            live.request(
                rehearsal.RehearsalRequest(
                    command='midi',
                    params=mido.Message('note_off', channel=1, note=65).dict(),
                )
            )
        at = 100 + index / 30 + (index % 3) * 0.007
        frames = {n: b64encode(f).decode() for n, f in live.playback.render(at)}
        expected.append((frames, live.playback.performance.model_dump(), at - 100))
    live.close()
    replay = rehearsal.RehearsalSession(
        rehearsal.RehearsalConfig(config=installation_path, replay=destination)
    )
    assert not replay.warnings
    for frames, performance, at in expected:
        result = replay.request(rehearsal.RehearsalRequest(command='step'))
        assert result['frames'] == frames
        assert result['performance'] == performance
        assert result['time'] == at
    assert result['finished']
    with pytest.raises(ValueError, match='recording'):
        replay.request(rehearsal.RehearsalRequest(command='blackout'))
    replay.close()


def test_replay_reports_configuration_changes_and_rejects_truncated_recordings(
    installation_path: Path, tmp_path: Path
) -> None:
    path = tmp_path / 'input.jsonl'
    session = rehearsal.RehearsalSession(
        rehearsal.RehearsalConfig(
            config=installation_path,
            string_counts={'left': 2, 'right': 3},
            record_input=path,
        )
    )
    session.request(rehearsal.RehearsalRequest(command='step'))
    session.close()
    installation_path.write_text(
        installation_path.read_text().replace('fps = 30', 'fps = 20')
    )
    replay = rehearsal.RehearsalSession(
        rehearsal.RehearsalConfig(config=installation_path, replay=path)
    )
    assert replay.warnings == ['Installation configuration differs from the recording']
    replay.close()
    path.write_text('\n'.join(path.read_text().splitlines()[:-1]) + '\n')
    replay = rehearsal.RehearsalSession(
        rehearsal.RehearsalConfig(config=installation_path, replay=path)
    )
    with pytest.raises(ValueError, match='incomplete'):
        replay.request(rehearsal.RehearsalRequest(command='step'))
    replay.close()


def test_recording_never_overwrites_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / 'input.jsonl'
    path.write_text('existing')
    with pytest.raises(FileExistsError):
        control_recording.ControlRecorder(path)
    assert path.read_text() == 'existing'
