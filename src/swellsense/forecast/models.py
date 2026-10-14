"""Forecast values the rest of the program can rely on.

A conditions check reads these models rather than an API payload, so a missing
hour or a naive time fails before it is treated as a wave height.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, field_validator

# New Zealand civil time. Daylight saving is UTC+13, winter is UTC+12.
AUCKLAND = ZoneInfo("Pacific/Auckland")


class HourlyConditions(BaseModel):
    """One hour of swell and wind.

    Directions are degrees true, where the swell or wind is coming from.
    A value is None when the API returned null for that hour.
    """

    time: datetime
    wave_height_m: float | None = None
    wave_period_s: float | None = None
    wave_direction_deg: float | None = None
    swell_height_m: float | None = None
    swell_period_s: float | None = None
    swell_direction_deg: float | None = None
    wind_wave_height_m: float | None = None
    wind_wave_period_s: float | None = None
    wind_wave_direction_deg: float | None = None
    wind_speed_kn: float | None = None
    wind_gust_kn: float | None = None
    wind_direction_deg: float | None = None

    @field_validator("time")
    @classmethod
    def _local(cls, value: datetime) -> datetime:
        # A UTC stamp would print the wrong hour, and a naive one cannot be
        # placed on a daylight-saving day.
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("forecast time must be timezone-aware")
        if value.tzinfo != AUCKLAND:
            raise ValueError("forecast time must be Pacific/Auckland")
        return value


class SpotForecast(BaseModel):
    """The hourly forecast fetched for one spot."""

    spot_id: str
    fetched_at: datetime
    hours: list[HourlyConditions]
    attribution: str

    @field_validator("fetched_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")
        return value
