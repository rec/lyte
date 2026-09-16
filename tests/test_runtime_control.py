import mido
import numpy as np
import pytest

from lyte import animation, runtime_control


@pytest.mark.parametrize(
    'message',
    [
        mido.Message('note_off', note=60),
        mido.Message('note_on', note=60, velocity=0),
        mido.Message('control_change', control=2, value=30),
        mido.Message('pitchwheel', pitch=4000),
    ],
)
def test_active_note_ignores_release_and_controls_from_other_channels(
    message: mido.Message,
) -> None:
    performance = runtime_control.MidiPerformance(
        note=60, channel=1, velocity=100, breath=80, pitch=2000
    )
    expected = performance.model_copy()
    performance.receive(message)
    assert performance == expected
    performance.receive(message.copy(channel=1))
    assert performance != expected


def test_latest_note_owns_the_midi_controls() -> None:
    performance = runtime_control.MidiPerformance()
    performance.receive(mido.Message('note_on', note=60, channel=0, velocity=100))
    performance.receive(mido.Message('note_on', note=60, channel=1, velocity=90))
    performance.receive(mido.Message('note_off', note=60, channel=0))
    assert performance.note == 60
    assert performance.channel == 1
    performance.receive(mido.Message('control_change', control=2, value=70, channel=1))
    assert performance.breath == 70
    performance.receive(mido.Message('note_off', note=60, channel=1))
    assert performance.note is None


def test_active_light_test_fades_to_configured_white_level_then_black() -> None:
    device = animation.Device(led_count=2)
    test = runtime_control.ActiveLightTest(
        command=runtime_control.LightTestCommand(level=50.0, duration=2.0),
        started_at=10.0,
    )

    frames = [
        test.render(device, 10.0),
        test.render(device, 10.5),
        test.render(device, 11.0),
        test.render(device, 11.5),
        test.render(device, 12.0),
        test.render(device, 12.1),
    ]

    values = [None if f is None else int(f[0, 0]) for f in frames]
    assert values == [0, 64, 128, 64, 0, None]
    for frame in frames[:-1]:
        assert frame is not None
        assert np.all(frame == frame[0, 0])
