from base64 import b64decode, b64encode
from fractions import Fraction
from pathlib import Path

import mido
import pytest
import tomlkit

from lyte import installation_config, installation_playback, rehearsal, show


@pytest.fixture
def session(tmp_path: Path) -> rehearsal.RehearsalSession:
    config = tmp_path / 'installation.toml'
    config.write_text(
        tomlkit.dumps(
            {
                'library_config': str(Path('examples/library.toml').resolve()),
                'fps': 30,
                'initial_animation': 'concat',
                'twinkly': {'left': {}, 'right': {}},
                'midi': {'channel': 2},
                'animations': {
                    'concat': {
                        'selector': 'aurora',
                        'outputs': {'light': 'left + right'},
                        'activation': 'note',
                    },
                    'mirror': {
                        'selector': 'aurora',
                        'outputs': {'light': 'left * right'},
                    },
                },
            }
        )
    )
    return rehearsal.RehearsalSession(
        rehearsal.RehearsalConfig(config=config, string_counts={'left': 2, 'right': 3})
    )


def test_rehearsal_matches_score_clock_and_distribution(
    session: rehearsal.RehearsalSession,
) -> None:
    assert all(
        not any(b64decode(f))
        for f in session.request(rehearsal.RehearsalRequest(command='step'))[
            'frames'
        ].values()
    )
    session.request(
        rehearsal.RehearsalRequest(
            command='midi',
            params={'type': 'note_on', 'channel': 1, 'note': 60, 'velocity': 90},
        )
    )
    reference = show.prepare_library_animation(
        session.playback.library, show.LightProgramSpec(selector='aurora')
    )
    expression = installation_config.parse_output_expression(
        'left + right', ['left', 'right']
    )
    first_frames = None
    for _ in range(31):
        result = session.request(rehearsal.RehearsalRequest(command='step'))
        target = int(
            (Fraction(str(result['time'])) - Fraction(str(1 / 30))) * reference.rate
        )
        while reference.tick <= target:
            expected = reference.byte_frame(wired=True)
        frames = installation_playback.distribute_frame(
            expected, expression, {'left': 2, 'right': 3}
        )
        assert result['frames'] == {n: b64encode(f).decode() for n, f in frames}
        if first_frames is None:
            first_frames = result['frames']
    first = session.request(
        rehearsal.RehearsalRequest(
            command='midi',
            params={'type': 'note_on', 'channel': 1, 'note': 62, 'velocity': 90},
        )
    )
    assert first['performance']['note'] == 62
    assert (
        session.request(rehearsal.RehearsalRequest(command='step'))['frames']
        == first_frames
    )


def test_rehearsal_midi_filter_ownership_blackout_and_test(
    session: rehearsal.RehearsalSession,
) -> None:
    for message in [
        mido.Message('note_on', channel=1, note=60, velocity=90),
        mido.Message('control_change', channel=0, control=2, value=50),
    ]:
        result = session.request(
            rehearsal.RehearsalRequest(command='midi', params=message.dict())
        )
    assert result['performance']['breath'] is None
    result = session.request(
        rehearsal.RehearsalRequest(
            command='midi',
            params=mido.Message('pitchwheel', channel=1, pitch=4096).dict(),
        )
    )
    assert result['performance']['pitch'] == 4096
    session.request(
        rehearsal.RehearsalRequest(
            command='select_animation', params={'name': 'mirror'}
        )
    )
    result = session.request(rehearsal.RehearsalRequest(command='step'))
    assert result['active'] == 'mirror'
    assert [len(b64decode(f)) for f in result['frames'].values()] == [6, 9]
    session.request(rehearsal.RehearsalRequest(command='test', params={'duration': 1}))
    assert session.request(rehearsal.RehearsalRequest(command='step'))['test']
    session.request(rehearsal.RehearsalRequest(command='blackout'))
    result = session.request(rehearsal.RehearsalRequest(command='step'))
    assert result['blackout'] and not result['test']
    assert all(not any(b64decode(f)) for f in result['frames'].values())
    with pytest.raises(ValueError, match='blackout'):
        session.request(rehearsal.RehearsalRequest(command='test'))
