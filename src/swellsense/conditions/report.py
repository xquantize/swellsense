"""A conditions report for one spot, and a ranking across spots.

The report is the thing a later answer phrases. Every judgement in it already
happened in code: the hourly rating, which hour is best, and which gaps
(an unverified profile, a conflicting tide, a missing value) the reader
should hear about.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from swellsense.conditions.rating import HourRating, rate_hour
from swellsense.forecast.models import AUCKLAND, HourlyConditions, SpotForecast
from swellsense.spots.models import Spot
from swellsense.tides.linz import LINZ_ATTRIBUTION
from swellsense.tides.models import TideEvent, TideState
from swellsense.tides.state import tide_at


class ConditionsReport(BaseModel):
    """One spot over a half-open time range, ``start`` inclusive and ``end`` exclusive."""

    spot_id: str
    spot_name: str
    start: datetime
    end: datetime
    hours: list[HourRating]
    best_hour: HourRating | None
    uncertainties: list[str]
    hazards: list[str]
    attributions: list[str] = Field(min_length=1)

    @field_validator("start", "end")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("report times must be timezone-aware")
        return value


def build_report(
    spot: Spot,
    forecast: SpotForecast,
    tide_events: list[TideEvent],
    start: datetime,
    end: datetime,
) -> ConditionsReport:
    """Rate each forecast hour in ``[start, end)`` and collect the caveats.

    The end is exclusive so adjoining windows do not rate the shared hour
    twice. The best hour is the highest score, and the earlier hour when two
    scores match. Tide events that do not cover an hour leave that hour
    without a tide rather than failing the whole report.
    """
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("start must be timezone-aware")
    if end.tzinfo is None or end.utcoffset() is None:
        raise ValueError("end must be timezone-aware")
    if end < start:
        raise ValueError("end must not be before start")
    if forecast.spot_id != spot.id:
        raise ValueError(f"forecast is for {forecast.spot_id}, not {spot.id}")

    selected = sorted(
        (hour for hour in forecast.hours if start <= hour.time < end),
        key=lambda hour: hour.time,
    )
    ratings: list[HourRating] = []
    missing_tide: list[datetime] = []
    for hour in selected:
        tide_state = _tide_or_none(tide_events, hour.time)
        if tide_state is None:
            missing_tide.append(hour.time)
        ratings.append(rate_hour(spot, hour, tide_state))

    return ConditionsReport(
        spot_id=spot.id,
        spot_name=spot.name,
        start=start,
        end=end,
        hours=ratings,
        best_hour=_best_hour(ratings),
        uncertainties=_uncertainties(spot, forecast, selected, missing_tide),
        hazards=list(spot.hazards),
        attributions=[forecast.attribution, LINZ_ATTRIBUTION],
    )


def rank_spots(reports: list[ConditionsReport]) -> list[ConditionsReport]:
    """Order spots by their best hour, highest score first.

    A report with no rated hour sorts last. Equal scores keep the earlier
    best hour first, then the spot id, so the order does not depend on the
    order of the input.
    """
    return sorted(reports, key=_rank_key)


def _best_hour(hours: list[HourRating]) -> HourRating | None:
    best: HourRating | None = None
    for hour in hours:
        if best is None or hour.score > best.score:
            best = hour
    return best


def _rank_key(report: ConditionsReport) -> tuple[int, int, float, str]:
    best = report.best_hour
    if best is None:
        return (1, 0, 0.0, report.spot_id)
    return (0, -best.score, best.time.timestamp(), report.spot_id)


def _tide_or_none(events: list[TideEvent], when: datetime) -> TideState | None:
    if len(events) < 2:
        return None
    try:
        return tide_at(events, when)
    except ValueError:
        return None


def _uncertainties(
    spot: Spot,
    forecast: SpotForecast,
    hours: list[HourlyConditions],
    missing_tide: list[datetime],
) -> list[str]:
    notes: list[str] = []
    if not spot.verified:
        notes.append(f"{spot.name} is not verified, so the profile may be wrong.")
    if spot.tide_confidence == "conflicting":
        notes.append(
            "The tide call is conflicting, so the tide did not change the score."
        )
    elif spot.tide_confidence == "unknown":
        notes.append("The tide call is unknown, so the tide did not change the score.")

    for hour in hours:
        missing = _missing_forecast(hour)
        if missing:
            clock = hour.time.strftime("%Y-%m-%d %H:%M")
            joined = " and ".join(missing)
            notes.append(f"{clock} is missing {joined}.")

    for when in missing_tide:
        clock = when.strftime("%Y-%m-%d %H:%M")
        notes.append(f"{clock} has no tide prediction.")

    if not hours:
        notes.append("No forecast hours fall in this window.")

    fetched = forecast.fetched_at.astimezone(AUCKLAND)
    notes.append(
        f"Forecast fetched at {fetched.strftime('%Y-%m-%d %H:%M')} Pacific/Auckland."
    )
    return notes


def _missing_forecast(hour: HourlyConditions) -> list[str]:
    # Only the series the rating reads. Wind chop and gusts are not scored.
    missing: list[str] = []
    if (
        hour.swell_height_m is None
        or hour.swell_period_s is None
        or hour.swell_direction_deg is None
    ):
        missing.append("swell")
    if hour.wind_speed_kn is None or hour.wind_direction_deg is None:
        missing.append("wind")
    return missing
