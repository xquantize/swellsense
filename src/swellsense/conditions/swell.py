"""Swell height, period and direction relative to one spot.

Size uses the open-ocean height passed in. It is not an estimate of how big
the wave will be when it breaks.
"""

from typing import Literal

from pydantic import BaseModel, Field

from swellsense.conditions.angles import angle_diff, in_window
from swellsense.conditions.thresholds import (
    FLAT_MAX_M,
    FUN_MAX_M,
    MIXED_MAX_S,
    SMALL_MAX_M,
    SOLID_MAX_M,
    SWELL_MARGINAL_DEG,
    WINDSWELL_MAX_S,
)
from swellsense.spots.models import Spot

WindowFit = Literal["in", "marginal", "outside"]
SwellKind = Literal["windswell", "mixed", "groundswell"]
SwellSize = Literal["flat", "small", "fun", "solid", "big"]

_FIT_WORDS = {
    "in": "in the swell window",
    "marginal": "marginal for the swell window",
    "outside": "outside the swell window",
}


class SwellJudgement(BaseModel):
    """Swell for one spot.

    ``in_window`` is ``in`` inside the swell window, ``marginal`` within 15°
    outside it, and ``outside`` beyond that.
    """

    in_window: WindowFit | Literal["unknown"]
    kind: SwellKind | Literal["unknown"]
    size: SwellSize | Literal["unknown"]
    reason: str = Field(min_length=1)


def classify_swell(
    spot: Spot | None,
    height_m: float | None,
    period_s: float | None,
    direction_deg: float | None,
) -> SwellJudgement:
    """Judge swell height, period and direction against one spot.

    ``height_m`` is open-ocean height, not the height of the breaking wave.
    A metre of swell offshore can stand up quite differently once it hits
    the bank, so the size word stays tied to the ocean measurement.
    """
    if spot is None or height_m is None or period_s is None or direction_deg is None:
        return _unknown(spot)

    window = spot.swell_window
    fit = _fit(direction_deg, window.start_deg, window.end_deg)
    kind = _kind(period_s)
    size = _size(height_m)
    return SwellJudgement(
        in_window=fit,
        kind=kind,
        size=size,
        reason=(
            f"{_fmt(height_m)} m at {_fmt(period_s)} s from {_fmt(direction_deg)}°, "
            f"{_FIT_WORDS[fit]}, {kind}, {size} size"
        ),
    )


def _fit(direction_deg: float, start: float, end: float) -> WindowFit:
    if in_window(direction_deg, start, end):
        return "in"
    # An exterior point's nearest place on the arc is an endpoint, so the
    # shorter compass step to either end is how far outside the window it is.
    outside = min(
        angle_diff(direction_deg, start),
        angle_diff(direction_deg, end),
    )
    if outside <= SWELL_MARGINAL_DEG:
        return "marginal"
    return "outside"


def _kind(period_s: float) -> SwellKind:
    if period_s < WINDSWELL_MAX_S:
        return "windswell"
    if period_s < MIXED_MAX_S:
        return "mixed"
    return "groundswell"


def _size(height_m: float) -> SwellSize:
    if height_m < FLAT_MAX_M:
        return "flat"
    if height_m < SMALL_MAX_M:
        return "small"
    if height_m < FUN_MAX_M:
        return "fun"
    if height_m < SOLID_MAX_M:
        return "solid"
    return "big"


def _unknown(spot: Spot | None) -> SwellJudgement:
    if spot is None:
        reason = "The spot is missing, so the swell is unknown."
    else:
        reason = (
            "Swell height, period or direction is missing, so the swell is unknown."
        )
    return SwellJudgement(
        in_window="unknown",
        kind="unknown",
        size="unknown",
        reason=reason,
    )


def _fmt(value: float) -> str:
    """Short decimal for a reason, without changing the class already chosen."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    if text in {"", "-0", "-"}:
        return "0"
    return text
