"""Audio analysis and one-dimensional rendering primitives for reactive effects."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field, model_validator
from ufor.audio_features import AudioFeatures


class GradientStop(BaseModel, frozen=True):
    position: float = Field(ge=0, le=1)
    color: list[float] = Field(min_length=3, max_length=3)

    @model_validator(mode='after')
    def normalized_color(self) -> GradientStop:
        if any(not 0 <= value <= 1 for value in self.color):
            raise ValueError('gradient colors must be between zero and one')
        return self


class Gradient(BaseModel, frozen=True):
    stops: list[GradientStop] = Field(min_length=2)

    @model_validator(mode='after')
    def ordered_stops(self) -> Gradient:
        if any(
            right.position <= left.position
            for left, right in zip(self.stops, self.stops[1:], strict=False)
        ):
            raise ValueError('gradient stop positions must increase')
        return self

    def sample(
        self, positions: NDArray[np.float32], cyclic: bool = False
    ) -> NDArray[np.float32]:
        if positions.ndim != 1:
            raise ValueError('gradient positions must be one-dimensional')
        values = np.mod(positions, 1) if cyclic else np.clip(positions, 0, 1)
        locations = np.array([stop.position for stop in self.stops], dtype=np.float32)
        colors = np.array([stop.color for stop in self.stops], dtype=np.float32)
        result = np.empty((len(values), 3), dtype=np.float32)
        for channel in range(3):
            result[:, channel] = np.interp(values, locations, colors[:, channel])
        return np.ascontiguousarray(result)


@dataclass
class AudioAnalyzer:
    """Stateful envelope and onset analysis for caller-provided sample blocks."""

    spectrum_bands: int = 16
    attack: float = 0.5
    release: float = 0.08
    beat_threshold: float = 1.5
    _envelope: float = 0
    _average_onset: float = 0

    def analyze(
        self, samples: NDArray[np.float32], sample_rate: float
    ) -> AudioFeatures:
        if sample_rate <= 0:
            raise ValueError('sample rate must be greater than zero')
        if samples.ndim != 1 or not len(samples):
            raise ValueError('audio samples must be a nonempty one-dimensional array')
        if samples.dtype != np.float32 or not np.isfinite(samples).all():
            raise ValueError('audio samples must be finite float32 values')
        if self.spectrum_bands <= 0:
            raise ValueError('spectrum bands must be greater than zero')
        level = min(1.0, float(np.sqrt(np.mean(samples * samples))))
        coefficient = self.attack if level > self._envelope else self.release
        self._envelope += coefficient * (level - self._envelope)
        onset = max(0.0, level - self._envelope)
        beat = (
            1.0
            if onset > self._average_onset * self.beat_threshold and onset > 0
            else 0.0
        )
        self._average_onset += 0.05 * (onset - self._average_onset)
        magnitude, frequencies = _spectrum(samples, sample_rate)
        spectrum = _spectrum_bands(magnitude, frequencies, self.spectrum_bands)
        return AudioFeatures(
            level=level,
            bass=_band_level(magnitude, frequencies, 20, 250),
            mid=_band_level(magnitude, frequencies, 250, 2000),
            treble=_band_level(magnitude, frequencies, 2000, 8000),
            onset=min(1.0, onset),
            beat=beat,
            spectrum=spectrum.tolist(),
        )


def smooth(current: float, target: float, rate: float, elapsed: float) -> float:
    if rate < 0 or elapsed < 0:
        raise ValueError('smoothing rate and elapsed time must not be negative')
    return current + (target - current) * (1 - math.exp(-rate * elapsed))


def blur(frame: NDArray[np.float32], radius: int) -> NDArray[np.float32]:
    _validate_frame(frame)
    if radius < 0:
        raise ValueError('blur radius must not be negative')
    if radius == 0:
        return np.ascontiguousarray(frame)
    kernel = np.ones(radius * 2 + 1, dtype=np.float32) / (radius * 2 + 1)
    result = np.empty_like(frame)
    for channel in range(3):
        padded = np.pad(frame[:, channel], radius, mode='edge')
        result[:, channel] = np.convolve(padded, kernel, mode='valid')
    return np.ascontiguousarray(result)


def mirror(frame: NDArray[np.float32]) -> NDArray[np.float32]:
    _validate_frame(frame)
    return np.ascontiguousarray((frame + frame[::-1]) / 2)


def flip(frame: NDArray[np.float32]) -> NDArray[np.float32]:
    _validate_frame(frame)
    return np.ascontiguousarray(frame[::-1])


def blend(
    frames: list[NDArray[np.float32]], mode: Literal['add', 'maximum', 'multiply']
) -> NDArray[np.float32]:
    if not frames:
        raise ValueError('blend requires at least one frame')
    for frame in frames:
        _validate_frame(frame)
        if frame.shape != frames[0].shape:
            raise ValueError('blend frames must have the same shape')
    stacked = np.stack(frames)
    if mode == 'add':
        result = np.sum(stacked, axis=0)
    elif mode == 'maximum':
        result = np.max(stacked, axis=0)
    else:
        result = np.prod(stacked, axis=0)
    return np.ascontiguousarray(np.clip(result, 0, 1).astype(np.float32))


def apply_mask(
    frame: NDArray[np.float32], mask: NDArray[np.float32]
) -> NDArray[np.float32]:
    _validate_frame(frame)
    if mask.shape != (len(frame),) or mask.dtype != np.float32:
        raise ValueError('mask must be float32 with one value per light')
    if not np.isfinite(mask).all():
        raise ValueError('mask must contain finite values')
    return np.ascontiguousarray(np.clip(frame * mask[:, None], 0, 1))


def background(
    frame: NDArray[np.float32], color: tuple[float, float, float], amount: float
) -> NDArray[np.float32]:
    _validate_frame(frame)
    if not 0 <= amount <= 1 or any(not 0 <= value <= 1 for value in color):
        raise ValueError('background color and amount must be between zero and one')
    base = np.array(color, dtype=np.float32)
    return np.ascontiguousarray(np.clip(base * amount + frame, 0, 1))


def _spectrum(
    samples: NDArray[np.float32], sample_rate: float
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    window = np.hanning(len(samples)).astype(np.float32)
    magnitude = np.abs(np.fft.rfft(samples * window)).astype(np.float32)
    magnitude /= max(1, len(samples))
    frequencies = np.fft.rfftfreq(len(samples), 1 / sample_rate).astype(np.float32)
    return magnitude, frequencies


def _band_level(
    magnitude: NDArray[np.float32],
    frequencies: NDArray[np.float32],
    low: float,
    high: float,
) -> float:
    selected = magnitude[(frequencies >= low) & (frequencies < high)]
    return (
        0.0
        if not len(selected)
        else min(1.0, float(np.sqrt(np.mean(selected * selected)) * 8))
    )


def _spectrum_bands(
    magnitude: NDArray[np.float32], frequencies: NDArray[np.float32], count: int
) -> NDArray[np.float32]:
    edges = np.geomspace(20, 20000, count + 1)
    return np.array(
        [
            _band_level(magnitude, frequencies, low, high)
            for low, high in zip(edges, edges[1:], strict=False)
        ],
        dtype=np.float32,
    )


def _validate_frame(frame: NDArray[np.float32]) -> None:
    if frame.dtype != np.float32 or frame.ndim != 2 or frame.shape[1] != 3:
        raise ValueError('frame must have shape light_count x 3 and dtype float32')
    if not len(frame) or not np.isfinite(frame).all():
        raise ValueError('frame must be nonempty and finite')
