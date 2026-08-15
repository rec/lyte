"""Synchronous Twinkly output track."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, SkipValidation
from reccy import logging

from .. import animation
from ..retry import RetryConfig
from . import realtime
from .client import TwinklyClient

LOGGER = logging.get_logger(__name__)

BLACKOUT_TIMEOUT = 3.0
HEALTH_CHECK_INTERVAL = 2.0
HEALTH_CHECK_TIMEOUT = 1.0


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
        LOGGER.info(
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
    expected_mac: str | None = None
    stop_event: SkipValidation[threading.Event] | None = None
    on_connection_state: (
        SkipValidation[Callable[[realtime.PlaybackConnectionState], None]] | None
    ) = None
    on_device_connected: SkipValidation[Callable[[str, str | None], None]] | None = None
    on_health_check: SkipValidation[Callable[[], None]] | None = None
    last_health_check: float | None = None
    connection: realtime.PlaybackConnection = Field(
        default_factory=realtime.PlaybackConnection
    )

    def prepare(self) -> bool:
        self._set_connection_state(realtime.PlaybackConnectionState.CONNECTING)
        if not realtime.prepare_device(
            self.client, self.retry, self.host, stop_event=self.stop_event
        ):
            return False
        self.connection.resume_streaming()
        self._notify_connection_state()
        self._notify_device_connected()
        self._notify_health_check()
        return True

    def close(self) -> None:
        deadline = time.monotonic() + BLACKOUT_TIMEOUT
        self.connection.finish_blackout(
            realtime.turn_off_streaming_device(
                self.client, self.retry, self.host, deadline
            )
        )
        self._notify_connection_state()

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
                if self.stop_event is not None and self.stop_event.is_set():
                    return
                started_at = time.monotonic()
                if (
                    self.last_health_check is not None
                    and started_at - self.last_health_check >= HEALTH_CHECK_INTERVAL
                ):
                    if not realtime.probe_streaming_device(
                        self.client,
                        self.retry,
                        self.host,
                        started_at + HEALTH_CHECK_TIMEOUT,
                    ):
                        if not self._recover():
                            return
                        continue
                    self._notify_health_check()
                self.last_health_check = started_at
                if before_frame is not None:
                    before_frame()
                frame = animation.validate_byte_rgb_frame(self.device, render_frame())
                result = realtime.send_realtime_frame(
                    self.client, self.retry, self.host, frame
                )
                elapsed = time.monotonic() - started_at
                report.record_frame(elapsed, frame_delay)
                if result.status is not realtime.FrameSendStatus.SENT:
                    recovery_started_at = time.monotonic()
                    if not self._recover():
                        return
                    report.record_recovery(time.monotonic() - recovery_started_at)
                    continue
                remaining = frame_delay - elapsed
                if remaining > 0:
                    time.sleep(remaining)
        finally:
            report.log_report(name, fps)

    def _recover(self) -> bool:
        self.connection.begin_recovery()
        self._notify_connection_state()
        host = realtime.recover_streaming_device(
            self.client,
            self.retry,
            self.configured_host,
            self.discovery_timeout,
            self.device.led_count,
            self.expected_mac,
            self.stop_event,
        )
        if host is None:
            return False
        self.host = host
        self.connection.resume_streaming()
        self._notify_connection_state()
        self._notify_device_connected()
        self._notify_health_check()
        return True

    def _set_connection_state(self, state: realtime.PlaybackConnectionState) -> None:
        self.connection.set_state(state)
        self._notify_connection_state()

    def _notify_connection_state(self) -> None:
        if self.on_connection_state is not None:
            self.on_connection_state(self.connection.state)

    def _notify_device_connected(self) -> None:
        if self.on_device_connected is not None:
            self.on_device_connected(self.host, self.client.mac)

    def _notify_health_check(self) -> None:
        if self.on_health_check is not None:
            self.on_health_check()

    model_config = ConfigDict(arbitrary_types_allowed=True)
