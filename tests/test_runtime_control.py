import numpy as np

from lyte import animation, runtime_control


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
