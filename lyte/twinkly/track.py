"""Synchronous Twinkly output track."""

from __future__ import annotations

import math
import time
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field

from .. import animation
from ..logging import log_status
from ..retry import RetryConfig
from . import realtime
from .client import TwinklyClient


class FrameDeadlineReport(BaseModel):
    frame_count: int = 0
    late_frames: int = 0
    missed_deadlines: int = 0
    worst_overrun_ms: float = 0
    recovery_count: int = 0
    recovery_duration_ms: float = 0

    def record_frame(self, elapsed: float, deadline: float) -> None:
        self.frame_count += 1
        overrun = elapsed - deadline
        if overrun <= 0:
            return
        self.late_frames += 1
        self.missed_deadlines += max(1, math.floor(elapsed / deadline))
        self.worst_overrun_ms = max(self.worst_overrun_ms, overrun * 1000)

    def record_recovery(self, duration: float) -> None:
        self.recovery_count += 1
        self.recovery_duration_ms += duration * 1000

    def log_report(self, name: str, fps: float) -> None:
        log_status(
            f'[report] {name} {fps:g} FPS: {self.frame_count} frames, '
            f'{self.late_frames} late frames, {self.missed_deadlines} missed '
            f'deadlines, worst overrun {self.worst_overrun_ms:.2f} ms, '
            f'{self.recovery_count} recoveries over '
            f'{self.recovery_duration_ms:.2f} ms.'
        )


class TwinklyTrack(BaseModel):
    client: TwinklyClient
    retry: RetryConfig
    host: str
    configured_host: str | None
    discovery_timeout: float | None
    device: animation.Device
    connection: realtime.PlaybackConnection = Field(
        default_factory=realtime.PlaybackConnection
    )

    def prepare(self) -> bool:
        self.connection.set_state(realtime.PlaybackConnectionState.CONNECTING)
        if not realtime.prepare_device(self.client, self.retry, self.host):
            return False
        self.connection.resume_streaming()
        return True

    def close(self) -> None:
        self.connection.finish_blackout(
            realtime.turn_off_streaming_device(self.client, self.retry, self.host)
        )

    def stream_frames(
        self,
        name: str,
        fps: float,
        duration: float | None,
        render_frame: Callable[[], NDArray[np.uint8]],
        before_frame: Callable[[], None] | None = None,
    ) -> None:
        frame_delay = 1 / fps
        stop_at = None if duration is None else time.monotonic() + duration
        report = FrameDeadlineReport()
        try:
            while stop_at is None or time.monotonic() < stop_at:
                started_at = time.monotonic()
                if before_frame is not None:
                    before_frame()
                frame = animation.validate_byte_rgb_frame(self.device, render_frame())
                result = realtime.send_realtime_frame(
                    self.client, self.retry, self.host, frame
                )
                elapsed = time.monotonic() - started_at
                report.record_frame(elapsed, frame_delay)
                if result.status is not realtime.FrameSendStatus.SENT:
                    self.connection.begin_recovery()
                    recovery_started_at = time.monotonic()
                    self.host = realtime.recover_streaming_device(
                        self.client,
                        self.retry,
                        self.configured_host,
                        self.discovery_timeout,
                        self.device.led_count,
                    )
                    report.record_recovery(time.monotonic() - recovery_started_at)
                    self.connection.resume_streaming()
                    continue
                remaining = frame_delay - elapsed
                if remaining > 0:
                    time.sleep(remaining)
        finally:
            report.log_report(name, fps)

    model_config = ConfigDict(arbitrary_types_allowed=True)
