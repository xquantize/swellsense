"""An explainable 0-10 score for one hour at one spot.

The classifiers decide what the wind, swell and tide are. This module only
turns those decisions into points. A later answer can phrase the rating; it
should not invent a different one.
"""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from swellsense.conditions.swell import SwellJudgement, classify_swell
from swellsense.conditions.thresholds import (
    EPIC_MIN,
    FAIR_MIN,
    GOOD_MIN,
    GREAT_MIN,
    MARGINAL_WINDOW_PENALTY,
    OFFSHORE_BONUS_CUT,
    OUTSIDE_WINDOW_CAP,
    SCORE_MAX,
    SCORE_MIN,
    SWELL_KIND_ADJUST,
    SWELL_SIZE_BASE,
    TIDE_MISMATCH_PENALTY,
    TIDE_SUITS_BONUS,
    WIND_QUALITY_ADJUST,
)
from swellsense.conditions.tide import TideJudgement, classify_tide
from swellsense.conditions.wind import WindJudgement, classify_wind
from swellsense.forecast.models import HourlyConditions
from swellsense.spots.models import Spot
from swellsense.tides.models import TideState

RatingLabel = Literal["poor", "fair", "good", "great", "epic"]

# Directions that receive the offshore bonus. Glassy is judged on its own.
_OFFSHORE_FAMILY = {"offshore", "cross-offshore"}


def score_label(score: int) -> RatingLabel:
    """Map a 0-10 score to the word a report shows.

    The boundaries live in ``thresholds`` so a later tune can move a band
    without rewriting this ladder. A score on a boundary takes the higher word.
    """
    if score < FAIR_MIN:
        return "poor"
    if score < GOOD_MIN:
        return "fair"
    if score < GREAT_MIN:
        return "good"
    if score < EPIC_MIN:
        return "great"
    return "epic"


class FactorContribution(BaseModel):
    """Points one factor actually added, after caps and the 0-10 bounds."""

    points: int
    reason: str = Field(min_length=1)


class Contributions(BaseModel):
    """The four parts of an hour. Their points sum to the score."""

    swell: FactorContribution
    wind: FactorContribution
    window: FactorContribution
    tide: FactorContribution

    def total(self) -> int:
        return (
            self.swell.points + self.wind.points + self.window.points + self.tide.points
        )


class HourRating(BaseModel):
    """One hour, the judgements behind it, and the points each factor added."""

    time: datetime
    score: int = Field(ge=SCORE_MIN, le=SCORE_MAX)
    label: RatingLabel
    wind: WindJudgement
    swell: SwellJudgement
    tide: TideJudgement
    contributions: Contributions

    @field_validator("time")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("rating time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        # A rating that does not add up cannot be explained, so it is rejected
        # before a report or a sentence treats it as a result.
        if self.contributions.total() != self.score:
            raise ValueError("contributions must add up to the score")
        if score_label(self.score) != self.label:
            raise ValueError("label does not match the score")
        return self


def rate_hour(
    spot: Spot,
    hour: HourlyConditions,
    tide_state: TideState | None,
) -> HourRating:
    """Score one hour at one spot.

    Swell size and kind are the base. Wind then moves it: glassy and offshore
    up, cross-shore unchanged, cross-onshore and onshore down. A strong or
    very strong wind reduces an offshore bonus and does not turn it into a
    penalty. Marginal swell takes a point off. Swell outside the window caps
    the score. Tide adds or removes a point only when that call is certain.

    The swell series is the primary swell (``swell_height_m``, period and
    direction). Wind chop is judged through the wind, not as a second swell.
    Flat swell scores 0 whatever the wind, the window or the tide.
    """
    wind = classify_wind(spot, hour.wind_direction_deg, hour.wind_speed_kn)
    swell = classify_swell(
        spot,
        hour.swell_height_m,
        hour.swell_period_s,
        hour.swell_direction_deg,
    )
    tide = classify_tide(spot, tide_state)
    contributions = _contributions(swell, wind, tide)
    score = contributions.total()
    return HourRating(
        time=hour.time,
        score=score,
        label=score_label(score),
        wind=wind,
        swell=swell,
        tide=tide,
        contributions=contributions,
    )


def _contributions(
    swell: SwellJudgement,
    wind: WindJudgement,
    tide: TideJudgement,
) -> Contributions:
    if swell.size == "flat":
        return Contributions(
            swell=FactorContribution(points=0, reason="Flat swell scores 0."),
            wind=FactorContribution(
                points=0, reason="Wind does not change a flat swell."
            ),
            window=FactorContribution(
                points=0, reason="The swell window does not change a flat swell."
            ),
            tide=FactorContribution(
                points=0, reason="The tide does not change a flat swell."
            ),
        )
    if swell.size == "unknown" or swell.kind == "unknown":
        return Contributions(
            swell=FactorContribution(
                points=0, reason="Swell is missing, so the score stays 0."
            ),
            wind=FactorContribution(
                points=0, reason="Wind is not applied without a swell."
            ),
            window=FactorContribution(
                points=0, reason="The swell window is not applied without a swell."
            ),
            tide=FactorContribution(
                points=0, reason="The tide is not applied without a swell."
            ),
        )

    total, swell_part = _swell_part(swell)
    total, wind_part = _wind_part(wind, total)
    total, tide_part = _tide_part(tide, total)
    _, window_part = _window_part(swell, total)
    return Contributions(
        swell=swell_part,
        wind=wind_part,
        window=window_part,
        tide=tide_part,
    )


def _swell_part(swell: SwellJudgement) -> tuple[int, FactorContribution]:
    nominal = SWELL_SIZE_BASE[swell.size] + SWELL_KIND_ADJUST[swell.kind]
    total, applied = _apply(0, nominal)
    return total, FactorContribution(
        points=applied,
        reason=f"{swell.size.capitalize()} {swell.kind} starts at {applied}.",
    )


def _wind_part(wind: WindJudgement, total: int) -> tuple[int, FactorContribution]:
    nominal, reason = _wind_nominal(wind)
    total, applied = _apply(total, nominal)
    if applied != nominal:
        reason = _bound_reason(wind.quality, applied, total)
    return total, FactorContribution(points=applied, reason=reason)


def _wind_nominal(wind: WindJudgement) -> tuple[int, str]:
    if wind.quality == "unknown":
        return 0, "Wind is unknown, so it changes nothing."

    nominal = WIND_QUALITY_ADJUST[wind.quality]
    if wind.quality in _OFFSHORE_FAMILY:
        cut = OFFSHORE_BONUS_CUT.get(wind.strength, 0)
        reduced = max(0, nominal - cut)
        if reduced != nominal:
            if reduced == 0:
                reason = (
                    f"{wind.strength.capitalize()} {wind.quality} wind adds nothing; "
                    "the offshore bonus is taken off."
                )
            else:
                reason = (
                    f"{wind.strength.capitalize()} {wind.quality} wind adds {reduced}, "
                    f"less than a lighter {wind.quality} wind."
                )
            return reduced, reason

    if nominal > 0:
        return nominal, f"{wind.quality.capitalize()} wind adds {nominal}."
    if nominal < 0:
        return nominal, f"{wind.quality.capitalize()} wind takes {-nominal} off."
    return 0, f"{wind.quality.capitalize()} wind changes nothing."


def _tide_part(tide: TideJudgement, total: int) -> tuple[int, FactorContribution]:
    # Uncertain covers a conflicting or unknown profile and a missing tide.
    # Either way the hour must match the hour with no tide adjustment.
    if tide.uncertain or tide.suits_spot is None:
        return total, FactorContribution(
            points=0,
            reason="The tide call is uncertain, so it changes nothing.",
        )

    nominal = TIDE_SUITS_BONUS if tide.suits_spot else -TIDE_MISMATCH_PENALTY
    total, applied = _apply(total, nominal)
    if applied != nominal:
        reason = _bound_reason("tide", applied, total)
    elif tide.suits_spot:
        reason = f"A tide that suits this spot adds {applied}."
    else:
        reason = f"A tide that does not suit this spot takes {-applied} off."
    return total, FactorContribution(points=applied, reason=reason)


def _window_part(swell: SwellJudgement, total: int) -> tuple[int, FactorContribution]:
    if swell.in_window == "in":
        return total, FactorContribution(points=0, reason="In the swell window.")
    if swell.in_window == "marginal":
        total, applied = _apply(total, -MARGINAL_WINDOW_PENALTY)
        if applied == 0:
            reason = (
                "Marginal for the swell window changes nothing once the score is 0."
            )
        else:
            reason = f"Marginal for the swell window takes {-applied} off."
        return total, FactorContribution(points=applied, reason=reason)
    if swell.in_window == "outside":
        capped = min(total, OUTSIDE_WINDOW_CAP)
        applied = capped - total
        if applied == 0:
            reason = (
                "Outside the swell window, and the score is already "
                f"at or under {OUTSIDE_WINDOW_CAP}."
            )
        else:
            reason = f"Outside the swell window caps the score at {OUTSIDE_WINDOW_CAP}."
        return capped, FactorContribution(points=applied, reason=reason)
    return total, FactorContribution(points=0, reason="The swell window is unknown.")


def _apply(total: int, delta: int) -> tuple[int, int]:
    """Return ``(new total, points actually added)`` inside the score range."""
    updated = min(SCORE_MAX, max(SCORE_MIN, total + delta))
    return updated, updated - total


def _bound_reason(name: str, applied: int, total: int) -> str:
    """Explain a part that was cut by the 0-10 bounds.

    The points on the part are what it actually added. The reason has to say
    that, including when a penalty can only take the score down to zero.
    """
    bound = SCORE_MAX if total == SCORE_MAX else SCORE_MIN
    if applied == 0:
        return f"{name.capitalize()} changes nothing once the score is {bound}."
    return (
        f"{name.capitalize()} changes the score by {applied}, "
        f"which leaves it at {bound}."
    )
