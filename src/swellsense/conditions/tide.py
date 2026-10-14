"""Tide phase relative to the tides a spot prefers.

``uncertain`` follows the spot profile: a conflicting or unknown tide note
is not treated as a settled fact. A missing tide is unknown rather than a
guess that it does not suit.
"""

from typing import Literal

from pydantic import BaseModel, Field

from swellsense.spots.models import Spot
from swellsense.tides.models import TidePhase, TideState


class TideJudgement(BaseModel):
    """Tide for one spot.

    ``suits_spot`` is none when the tide or the spot is missing, so a gap is
    not stored as a tide that fails the spot. ``uncertain`` is true unless
    the profile's tide confidence is agreed and a tide was actually supplied.
    """

    phase: TidePhase | Literal["unknown"]
    rising: bool | None
    suits_spot: bool | None
    uncertain: bool
    reason: str = Field(min_length=1)


def classify_tide(spot: Spot | None, tide_state: TideState | None) -> TideJudgement:
    """Judge one tide state against a spot's preferred tides.

    The phase has to be one of ``spot.best_tides``. A rising tide is also
    required when ``spot.tide_rising_better`` is true. False and none do not
    add a falling requirement; the profile only records when rising is better.
    """
    if spot is None or tide_state is None:
        return _unknown(spot, tide_state)

    suits = _suits(spot, tide_state)
    return TideJudgement(
        phase=tide_state.phase,
        rising=tide_state.rising,
        suits_spot=suits,
        uncertain=spot.tide_confidence != "agreed",
        reason=_reason(spot, tide_state, suits),
    )


def _suits(spot: Spot, tide_state: TideState) -> bool:
    if tide_state.phase not in spot.best_tides:
        return False
    if spot.tide_rising_better:
        return tide_state.rising
    return True


def _reason(spot: Spot, tide_state: TideState, suits: bool) -> str:
    movement = "rising" if tide_state.rising else "falling"
    suit = "suits this spot" if suits else "does not suit this spot"
    reason = f"{tide_state.phase} and {movement}, {suit}"
    if spot.tide_confidence != "agreed":
        reason += f" (tide call is {spot.tide_confidence})"
    return reason


def _unknown(spot: Spot | None, tide_state: TideState | None) -> TideJudgement:
    if spot is None and tide_state is None:
        reason = "The spot and the tide are missing, so the tide is unknown."
    elif spot is None:
        reason = "The spot is missing, so the tide is unknown."
    else:
        reason = "The tide is missing, so the tide is unknown."
    return TideJudgement(
        phase="unknown",
        rising=None,
        suits_spot=None,
        uncertain=True,
        reason=reason,
    )
