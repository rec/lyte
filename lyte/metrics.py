"""Bounded aggregate timing diagnostics; no per-frame logging."""

from pydantic import BaseModel, computed_field


class RenderCost(BaseModel):
    fps: float
    light_count: int
    frames: int = 0
    total_seconds: float = 0
    max_seconds: float = 0
    over_budget_frames: int = 0
    catch_up_ticks: int = 0

    def record(self, seconds: float) -> None:
        self.frames += 1
        self.total_seconds += seconds
        self.max_seconds = max(self.max_seconds, seconds)
        self.over_budget_frames += seconds > 1 / self.fps

    @computed_field
    @property
    def mean_seconds(self) -> float:
        return self.total_seconds / self.frames if self.frames else 0


class DeliveryTiming(BaseModel):
    scheduled_interval_seconds: float
    frames: int = 0
    total_interval_seconds: float = 0
    max_interval_seconds: float = 0
    max_lateness_seconds: float = 0
    output_seconds: float = 0
    output_failures: int = 0

    def record(self, interval: float | None, lateness: float) -> None:
        self.frames += 1
        if interval is not None:
            self.total_interval_seconds += interval
            self.max_interval_seconds = max(self.max_interval_seconds, interval)
        self.max_lateness_seconds = max(self.max_lateness_seconds, lateness)

    @computed_field
    @property
    def mean_interval_seconds(self) -> float:
        return self.total_interval_seconds / (self.frames - 1) if self.frames > 1 else 0
