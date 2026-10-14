"""Wind relative to the direction a spot faces.

Offshore is the wind that blows off the land. Calm air is glassy even when
that direction would otherwise be onshore, so quality is judged separately
from relation.
"""

from typing import Literal

from pydantic import BaseModel, Field

from swellsense.conditions.angles import angle_diff
from swellsense.conditions.thresholds import (
    CALM_MAX_KN,
    CROSS_OFFSHORE_MAX_DEG,
    CROSS_ONSHORE_MAX_DEG,
    CROSS_SHORE_MAX_DEG,
    LIGHT_MAX_KN,
    MODERATE_MAX_KN,
    OFFSHORE_MAX_DEG,
    STRONG_MAX_KN,
)
from swellsense.spots.models import Spot

Relation = Literal[
    "offshore",
    "cross-offshore",
    "cross-shore",
    "cross-onshore",
    "onshore",
]
Strength = Literal["calm", "light", "moderate", "strong", "very strong"]


class WindJudgement(BaseModel):
    """Wind for one spot.

    ``quality`` matches ``relation``, except under 5 kn, when it is glassy.
    A missing direction or speed is unknown rather than a guessed class.
    """

    relation: Relation | Literal["unknown"]
    strength: Strength | Literal["unknown"]
    quality: Relation | Literal["glassy", "unknown"]
    reason: str = Field(min_length=1)


def classify_wind(
    spot: Spot | None,
    direction_deg: float | None,
    speed_kn: float | None,
) -> WindJudgement:
    """Judge wind direction and speed for one spot.

    Direction is where the wind blows from. Offshore is opposite the
    direction the beach faces, ``(facing_deg + 180) % 360``. Under 5 kn the
    quality is glassy whichever way that wind is coming from.
    """
    if spot is None or direction_deg is None or speed_kn is None:
        return _unknown(spot)

    # Facing is out to sea, so the opposite compass point comes off the land.
    offshore_deg = (spot.facing_deg + 180) % 360
    relation = _relation(angle_diff(direction_deg, offshore_deg))
    strength = _strength(speed_kn)
    quality: Relation | Literal["glassy"] = "glassy" if strength == "calm" else relation
    return WindJudgement(
        relation=relation,
        strength=strength,
        quality=quality,
        reason=(
            f"{_fmt(speed_kn)} kn from {_fmt(direction_deg)}°, {quality} "
            f"for a {spot.break_type} facing {spot.facing_deg}°"
        ),
    )


def _relation(diff: float) -> Relation:
    if diff <= OFFSHORE_MAX_DEG:
        return "offshore"
    if diff <= CROSS_OFFSHORE_MAX_DEG:
        return "cross-offshore"
    if diff <= CROSS_SHORE_MAX_DEG:
        return "cross-shore"
    if diff <= CROSS_ONSHORE_MAX_DEG:
        return "cross-onshore"
    return "onshore"


def _strength(speed_kn: float) -> Strength:
    if speed_kn < CALM_MAX_KN:
        return "calm"
    if speed_kn < LIGHT_MAX_KN:
        return "light"
    if speed_kn < MODERATE_MAX_KN:
        return "moderate"
    if speed_kn < STRONG_MAX_KN:
        return "strong"
    return "very strong"


def _unknown(spot: Spot | None) -> WindJudgement:
    if spot is None:
        reason = "The spot is missing, so the wind is unknown."
    else:
        reason = "Wind direction or speed is missing, so the wind is unknown."
    return WindJudgement(
        relation="unknown",
        strength="unknown",
        quality="unknown",
        reason=reason,
    )


def _fmt(value: float) -> str:
    """Short decimal for a reason, without changing the class already chosen."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    if text in {"", "-0", "-"}:
        return "0"
    return text
