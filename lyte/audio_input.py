"""Offline PCM WAV analysis on the exact root score clock."""

import math
import wave
from fractions import Fraction
from pathlib import Path

import numpy as np
from ufor.audio_features import AudioFeatures

from .reactivity import AudioAnalyzer


class AudioAnalysis:
    def __init__(
        self, path: Path, rate: Fraction, max_frames: int | None = None
    ) -> None:
        self.frames: list[AudioFeatures] = []
        analyzer = AudioAnalyzer()
        try:
            with wave.open(str(path)) as stream:
                sample_rate = stream.getframerate()
                count = stream.getnframes()
                channels = stream.getnchannels()
                width = stream.getsampwidth()
                if width not in (1, 2, 3, 4):
                    raise ValueError('audio requires 8, 16, 24 or 32-bit integer PCM')
                if not count:
                    raise ValueError('audio file is empty')
                if not 0 < rate <= sample_rate:
                    raise ValueError(
                        'score rate must be positive and at most the audio sample rate'
                    )
                self.duration = Fraction(count, sample_rate)
                frame_count = math.ceil(self.duration * rate)
                if max_frames is not None and frame_count > max_frames:
                    raise ValueError(
                        'audio preview exceeds 10000 frames or 32 MiB of frame data'
                    )
                for tick in range(frame_count):
                    start = tick * sample_rate // rate
                    end = (tick + 1) * sample_rate // rate
                    length = int(end - start)
                    available = min(length, count - int(start))
                    data = stream.readframes(available)
                    if len(data) != available * width * channels:
                        raise ValueError(
                            'audio file ends before its declared sample count'
                        )
                    if width == 1:
                        values = (
                            np.frombuffer(data, dtype=np.uint8).astype(np.float32) - 128
                        ) / 128
                    elif width == 3:
                        octets = (
                            np.frombuffer(data, dtype=np.uint8)
                            .reshape(-1, 3)
                            .astype(np.int32)
                        )
                        integers = octets[:, 0] | octets[:, 1] << 8 | octets[:, 2] << 16
                        integers = (integers ^ 0x800000) - 0x800000
                        values = integers.astype(np.float32) / 8388608
                    else:
                        values = np.frombuffer(data, dtype=f'<i{width}').astype(
                            np.float32
                        ) / (2 ** (8 * width - 1))
                    mono = values.reshape(-1, channels).mean(axis=1, dtype=np.float32)
                    if available < length:
                        mono = np.pad(mono, (0, length - available))
                    self.frames.append(analyzer.analyze(mono, sample_rate))
        except (wave.Error, EOFError) as error:
            raise ValueError(
                f'audio requires an uncompressed PCM WAV file: {error}'
            ) from error
