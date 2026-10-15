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
from swellsense.spots.models import Skill, Spot
from swellsense.tides.linz import LINZ_ATTRIBUTION
from swellsense.tides.models import TideEvent, TideState
from swellsense.tides.state import tide_at

# Easier skills sort first inside a tie. A surfer can surf their own level.
_SKILL_ORDER: dict[Skill, int] = {
    "beginner": 0,
    "intermediate": 1,
    "advanced": 2,
}


class ConditionsReport(BaseModel):
    """One spot over a half-open time range, ``start`` inclusive and ``end`` exclusive.

    ``min_skill`` and ``access`` are copied from the profile. The ranking
    uses them when two spots share a score.
    """

    spot_id: str
    spot_name: str
    min_skill: Skill
    access: str
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
        min_skill=spot.min_skill,
        access=spot.access,
        start=start,
        end=end,
        hours=ratings,
        best_hour=_best_hour(ratings),
        uncertainties=_uncertainties(spot, forecast, selected, missing_tide),
        hazards=list(spot.hazards),
        attributions=[forecast.attribution, LINZ_ATTRIBUTION],
    )


class RankedSpot(BaseModel):
    """One place in a ranking. Tied scores share ``rank``, written ``=1``."""

    rank: str = Field(pattern=r"^=?[1-9]\d*$")
    report: ConditionsReport


class SpotRanking(BaseModel):
    """Spots in rank order, plus any left out as above the surfer's level.

    ``above_level`` is empty when no skill was given. Those spots stay in
    the result so a caller can list them instead of dropping them.
    """

    ranked: list[RankedSpot]
    above_level: list[ConditionsReport] = Field(default_factory=list)


def rank_spots(
    reports: list[ConditionsReport],
    skill: Skill | None = None,
) -> SpotRanking:
    """Order spots by their best-hour score, and mark ties instead of hiding them.

    The highest score comes first. Spots with the same score share a rank,
    shown as ``=1``, ``=1``, ``3``. A report with no rated hour sorts last.
    Two unrated reports share a rank.

    Within a tie the order is practicality: spots without special access
    come first (a boat is special access), then the easier ``min_skill``,
    then the earlier best hour, then the name. When those all match, the
    spot id keeps the order stable.

    Pass ``skill`` to rank only spots at or below that level. Harder spots
    are left out of the ranking and returned in ``above_level``, in this
    same order. Omit ``skill`` to rank every report.
    """
    if skill is not None and skill not in _SKILL_ORDER:
        raise ValueError("skill must be beginner, intermediate or advanced")

    eligible: list[ConditionsReport] = []
    above: list[ConditionsReport] = []
    for report in reports:
        if skill is not None and _SKILL_ORDER[report.min_skill] > _SKILL_ORDER[skill]:
            above.append(report)
        else:
            eligible.append(report)

    return SpotRanking(
        ranked=_with_ranks(sorted(eligible, key=_rank_key)),
        above_level=sorted(above, key=_rank_key),
    )


def _best_hour(hours: list[HourRating]) -> HourRating | None:
    best: HourRating | None = None
    for hour in hours:
        if best is None or hour.score > best.score:
            best = hour
    return best


def _with_ranks(reports: list[ConditionsReport]) -> list[RankedSpot]:
    rows: list[RankedSpot] = []
    index = 0
    while index < len(reports):
        score = _best_score(reports[index])
        end = index + 1
        while end < len(reports) and _best_score(reports[end]) == score:
            end += 1
        # Competition ranking: the next spot skips the places the tie used.
        label = f"={index + 1}" if end - index > 1 else str(index + 1)
        rows.extend(
            RankedSpot(rank=label, report=report) for report in reports[index:end]
        )
        index = end
    return rows


def _best_score(report: ConditionsReport) -> int | None:
    if report.best_hour is None:
        return None
    return report.best_hour.score


def _rank_key(report: ConditionsReport) -> tuple[int, int, int, int, float, str, str]:
    best = report.best_hour
    # Unrated reports share one group at the end. A missing hour is its own score.
    if best is None:
        return (
            1,
            0,
            _needs_boat(report.access),
            _SKILL_ORDER[report.min_skill],
            0.0,
            report.spot_name.casefold(),
            report.spot_id,
        )
    return (
        0,
        -best.score,
        _needs_boat(report.access),
        _SKILL_ORDER[report.min_skill],
        best.time.timestamp(),
        report.spot_name.casefold(),
        report.spot_id,
    )


def _needs_boat(access: str) -> int:
    """Boat access sorts after a spot you can reach from the shore.

    The profiles only call out a boat as special access. Road, beach and
    anything else stay in the first group.
    """
    return int(access.casefold().strip() == "boat")


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
