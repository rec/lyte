"""Local sunset calculations and daily pixel-brightness envelopes."""

from datetime import UTC, date, datetime, time, timedelta
from functools import cached_property
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from astral import Observer
from astral.sun import sunset
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from reccy.configuration import units


class DailySchedule(BaseModel, frozen=True):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    timezone: str
    sunset_offset: units.Seconds = Field(default=1800, ge=0)
    fade_in: units.Seconds = Field(default=3600, gt=0)
    minimum_hold: units.Seconds = Field(default=7200, ge=0)
    fade_out_not_before: time = time(23)
    fade_out: units.Seconds = Field(default=1800, gt=0)
    maximum_level: float = Field(default=1, ge=0, le=1, allow_inf_nan=False)

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f'unknown time zone {value!r}') from error
        return value

    @field_validator('fade_out_not_before')
    @classmethod
    def local_clock(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError(
                'fade_out_not_before must be a local time without an offset'
            )
        return value

    @model_validator(mode='after')
    def daily_duration(self) -> Self:
        if (
            self.sunset_offset + self.fade_in + self.minimum_hold + self.fade_out
            > 86400
        ):
            raise ValueError(
                'sunset offset and scheduled durations must total at most 24h'
            )
        return self

    @cached_property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    model_config = ConfigDict(extra='forbid')


class ScheduleStatus(BaseModel, frozen=True):
    phase: Literal['off', 'fading_in', 'full', 'fading_out', 'error'] = 'off'
    level: float = 0
    sunset: datetime | None = None
    starts_at: datetime | None = None
    full_at: datetime | None = None
    fade_out_at: datetime | None = None
    ends_at: datetime | None = None
    error: str | None = None


class EveningWindow(BaseModel, frozen=True):
    sunset: datetime
    starts_at: datetime
    full_at: datetime
    fade_out_at: datetime
    ends_at: datetime

    def status(self, now: datetime, maximum_level: float) -> ScheduleStatus:
        if self.starts_at <= now < self.full_at:
            phase = 'fading_in'
            fraction = (now - self.starts_at) / (self.full_at - self.starts_at)
        elif self.full_at <= now < self.fade_out_at:
            phase = 'full'
            fraction = 1.0
        elif self.fade_out_at <= now < self.ends_at:
            phase = 'fading_out'
            fraction = (self.ends_at - now) / (self.ends_at - self.fade_out_at)
        else:
            phase = 'off'
            fraction = 0.0
        return ScheduleStatus(
            phase=phase,
            level=fraction * maximum_level,
            **self.model_dump(),
        )


class SunsetScheduler:
    def __init__(self, config: DailySchedule) -> None:
        self.config = config
        self.day: date | None = None
        self.windows: list[EveningWindow] = []
        self.error: str | None = None

    def evaluate(self, now: datetime) -> ScheduleStatus:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('schedule evaluation requires a time zone')
        day = now.astimezone(self.config.zone).date()
        now = now.astimezone(UTC)
        if day != self.day:
            self.day = day
            self.windows = []
            self.error = None
            # Yesterday's evening can still be playing after local midnight.
            for d in [day - timedelta(days=1), day]:
                try:
                    self.windows.append(evening_window(self.config, d))
                except ValueError as error:
                    if d == day:
                        self.error = f'{day}: {error}'
        for w in reversed(self.windows):
            if w.starts_at <= now < w.ends_at:
                return w.status(now, self.config.maximum_level)
        if self.error is not None:
            return ScheduleStatus(phase='error', error=self.error)
        return self.windows[-1].status(now, self.config.maximum_level)


def evening_window(config: DailySchedule, day: date) -> EveningWindow:
    setting = sunset(
        Observer(latitude=config.latitude, longitude=config.longitude),
        date=day,
        tzinfo=config.zone,
    ).astimezone(UTC)
    starts_at = setting + timedelta(seconds=config.sunset_offset)
    full_at = starts_at + timedelta(seconds=config.fade_in)
    cutoff = datetime.combine(day, config.fade_out_not_before, config.zone).astimezone(
        UTC
    )
    fade_out_at = max(cutoff, full_at + timedelta(seconds=config.minimum_hold))
    return EveningWindow(
        sunset=setting,
        starts_at=starts_at,
        full_at=full_at,
        fade_out_at=fade_out_at,
        ends_at=fade_out_at + timedelta(seconds=config.fade_out),
    )
