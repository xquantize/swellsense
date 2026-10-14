"""Tide values the rest of the program can rely on.

Predictions and the interpolated state both go through these models so a
bad time or an unknown phase fails before a conditions check uses it.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

TideKind = Literal["high", "low"]
TidePhase = Literal["low", "mid", "high"]


class TideEvent(BaseModel):
    """One predicted high or low water."""

    time: datetime
    height_m: float
    kind: TideKind

    @field_validator("time")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        # A naive time would compare wrongly with Auckland predictions.
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("tide time must be timezone-aware")
        return value


class TideState(BaseModel):
    """The tide at one moment, computed between two predictions."""

    height_m: float
    rising: bool
    phase: TidePhase
    previous_event: TideEvent
    next_event: TideEvent
