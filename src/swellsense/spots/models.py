"""Spot profiles: the static facts a conditions check can use.

Live swell, wind and tide are fetched later. Directions are stored as degrees
true so offshore, onshore and swell fit can be calculated rather than guessed.
"""

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

BreakType = Literal["beach", "point", "reef", "bar"]
Bottom = Literal["sand", "reef", "rock", "mixed"]
TideStage = Literal["low", "mid", "high"]
TideConfidence = Literal["agreed", "conflicting", "unknown"]
Skill = Literal["beginner", "intermediate", "advanced"]


class SwellWindow(BaseModel):
    """Swell directions, coming from, that reach this spot.

    Both ends are degrees true from 0 to 359. ``end_deg`` may be numerically
    smaller than ``start_deg`` when the window crosses north, for example
    330 to 60. That wrap is a real window, not a data error.
    """

    start_deg: int = Field(ge=0, le=359)
    end_deg: int = Field(ge=0, le=359)


class SpotSource(BaseModel):
    """A page the profile was drawn from, so a note can be checked later."""

    name: str = Field(min_length=1)
    url: str = Field(min_length=1, pattern=r"^https?://")


class Spot(BaseModel):
    """One surf spot. ``verified`` stays false until a local has checked it.

    ``facing_deg`` is the direction the beach faces out to sea. An offshore
    wind blows from ``facing_deg + 180`` (mod 360).

    ``forecast_lat`` and ``forecast_lon`` are the point sent to the marine
    grid. They default to the beach coordinates. A beach point that sits on
    a land cell returns null waves, so those two fields move the request
    slightly offshore.
    """

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1)
    region: str = Field(min_length=1)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    forecast_lat: float | None = Field(default=None, ge=-90, le=90)
    forecast_lon: float | None = Field(default=None, ge=-180, le=180)
    facing_deg: int = Field(ge=0, le=359)
    break_type: BreakType
    bottom: Bottom
    swell_window: SwellWindow
    best_tides: list[TideStage]
    tide_rising_better: bool | None = None
    tide_confidence: TideConfidence
    tide_notes: str
    min_skill: Skill
    hazards: list[str] = Field(default_factory=list)
    access: str
    notes: str
    sources: list[SpotSource] = Field(min_length=1)
    verified: bool = False

    @model_validator(mode="after")
    def _forecast_point_is_a_pair(self) -> Self:
        # One coordinate and not the other would be an incomplete sea point.
        if (self.forecast_lat is None) != (self.forecast_lon is None):
            raise ValueError("forecast_lat and forecast_lon must both be set")
        return self

    def forecast_point(self) -> tuple[float, float]:
        """Latitude and longitude to request, offshore when the beach is land."""
        if self.forecast_lat is None or self.forecast_lon is None:
            return (self.lat, self.lon)
        return (self.forecast_lat, self.forecast_lon)
