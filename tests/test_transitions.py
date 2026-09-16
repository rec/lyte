from pathlib import Path

import mido
import numpy as np
import pytest
from reccy.protocol import ipc
from ufor import codec, library, light_animation

from lyte import installation_config, installation_playback


@pytest.fixture
def playback() -> installation_playback.InstallationPlayback:
    original = codec.parse_score(Path('examples/scores/grid.toml').read_text())
    entries = []
    for name, color in [('red', [1, 0, 0]), ('blue', [0, 0, 1]), ('green', [0, 1, 0])]:
        score = original.model_copy(
            deep=True,
            update={
                'name': name,
                'body': original.body.model_copy(
                    update={'operation': light_animation.Fill(values=color)}
                ),
            },
        )
        entries.append(
            library.Entry(
                library='test', address=f'/{name}.toml', name=name, score=score
            )
        )
    config = installation_config.parse_installation(
        {
            'twinkly': {'left': {}, 'right': {}},
            'midi': {},
            'initial_animation': 'red',
            'animations': {
                n: {'selector': n, 'outputs': {'light': 'left + right'}}
                for n in ['red', 'blue', 'green']
            },
        }
    )
    engine = installation_playback.InstallationPlayback(
        config, library.Library(entries), {'left': 2, 'right': 3}
    )
    engine.select('red')
    engine.render(0)
    return engine


def test_fade_endpoints_midpoint_and_interruption_use_the_displayed_blend(
    playback: installation_playback.InstallationPlayback,
) -> None:
    playback.command('select_animation', {'name': 'blue', 'duration': 2})
    assert playback.render(1)[0][1][0].tolist() == [255, 0, 0]
    assert playback.render(2)[0][1][0].tolist() == [128, 0, 128]
    playback.command('select_animation', {'name': 'green', 'duration': 2})
    assert playback.render(2.5)[0][1][0].tolist() == [128, 0, 128]
    assert playback.outgoing is None
    assert playback.render(3.5)[0][1][0].tolist() == [64, 128, 64]
    frames = playback.render(4.5)
    assert all(np.all(f == [0, 255, 0]) for _, f in frames)
    assert playback.transition_duration == 0
    assert playback.transition_snapshot is None


def test_master_applies_once_and_blackout_cancels_a_fade(
    playback: installation_playback.InstallationPlayback,
) -> None:
    playback.command('master_level', {'level': 0.5})
    playback.command('select_animation', {'name': 'blue', 'duration': 2})
    playback.render(1)
    assert playback.render(2)[0][1][0].tolist() == [64, 0, 64]
    playback.command('select_animation', {'name': 'green', 'duration': 2})
    assert playback.render(2.5)[0][1][0].tolist() == [64, 0, 64]
    playback.command('blackout', {})
    assert all(not f.any() for _, f in playback.render(2.6))
    assert playback.transition_duration == 0
    playback.command('select_animation', {'name': 'blue', 'duration': 1})
    assert all(not f.any() for _, f in playback.render(3))
    assert playback.render(4)[0][1][0].tolist() == [0, 0, 128]


def test_both_live_animations_receive_midi_and_obey_their_gates(
    playback: installation_playback.InstallationPlayback,
) -> None:
    for name, definition in playback.config.animations.items():
        playback.config.animations[name] = definition.model_copy(
            update={'activation': 'note'}
        )
    playback.select('red')
    playback.receive_midi(mido.Message('note_on', note=60, velocity=90))
    playback.render(0)
    playback.command('select_animation', {'name': 'blue', 'duration': 2})
    playback.render(1)
    playback.receive_midi(mido.Message('control_change', control=2, value=80))
    assert playback.outgoing.performance.breath == 80
    assert playback.active.performance.breath == 80
    playback.receive_midi(mido.Message('note_off', note=60))
    assert all(not f.any() for _, f in playback.render(2))
    playback.receive_midi(mido.Message('note_on', note=62, velocity=100))
    assert playback.render(2.5)[0][1][0].tolist() == [64, 0, 191]
    assert playback.render_costs['red']['light'].frames > 0
    assert playback.render_costs['blue']['light'].frames > 0


@pytest.mark.parametrize('value', [-1, float('inf'), float('nan'), True])
def test_invalid_controls_do_not_change_queued_selection(
    playback: installation_playback.InstallationPlayback, value: float
) -> None:
    assert isinstance(
        playback.command('select_animation', {'name': 'blue', 'duration': value}),
        ipc.Error,
    )
    assert playback.queued_name is None
    assert isinstance(playback.command('master_level', {'level': value}), ipc.Error)
    assert playback.master_level == 1
