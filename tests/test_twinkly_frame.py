import numpy as np
import pytest
from tinkly.frame import frame_packets_v3

from lyte.twinkly.frame import frame_payload


def test_numpy_frame_is_transmitted_without_copying() -> None:
    frame = np.full((301, 3), 42, dtype=np.uint8)

    packets = list(frame_packets_v3('MCIGBF1qJlg=', frame_payload(frame)))

    assert len(packets) == 2
    assert all(p.obj is frame for _, p in packets)
    assert b''.join(p for _, p in packets) == frame.tobytes()


@pytest.mark.parametrize(
    'frame',
    [np.zeros(9, dtype=np.uint8), np.zeros((3, 3), dtype=np.float32)],
)
def test_lyte_rejects_invalid_rgb_arrays(frame: np.ndarray) -> None:
    with pytest.raises(ValueError):
        frame_payload(frame)
