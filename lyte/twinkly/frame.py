"""Convert lyte RGB arrays to transport buffers."""

import numpy as np
from numpy.typing import NDArray


def frame_payload(frame: NDArray[np.uint8]) -> memoryview:
    if frame.dtype != np.uint8:
        raise ValueError('Realtime frames must have dtype uint8')
    if frame.ndim != 2 or frame.shape[1] != 3:
        raise ValueError('Realtime frames must have shape Nx3')
    return memoryview(frame)
