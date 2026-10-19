"""Tools the chatbot can call for a conditions question.

The model only chooses a tool and phrases the JSON. Every judgement, the
time window, the score and the ranking, is made in code. A window that has
already finished is answered from the next sensible one: the rest of today,
or tomorrow morning once it is evening. The note for that is ordinary speech.
"""

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from swellsense.conditions.rating import HourRating
from swellsense.conditions.report import (
    ConditionsReport,
    RankedSpot,
    build_report,
)
from swellsense.conditions.report import (
    rank_spots as order_spots,
)
from swellsense.forecast.models import AUCKLAND, SpotForecast
from swellsense.forecast.openmeteo import fetch_forecast
from swellsense.ingest.fetchers.mediawiki import make_client
from swellsense.spots.models import Skill, Spot
from swellsense.spots.registry import get_spot, load_spots
from swellsense.tides.linz import download_year, parse_predictions
from swellsense.tides.models import TideEvent

# Spoken at the end of a conditions answer. The long licence lines stay in
# ``attributions`` so the credit itself can stay short.
DATA_CREDIT = "Open-Meteo and LINZ"

# How many hours of a long window to show. The full count is still reported.
HOUR_SAMPLE = 3

WHENS = (
    "now",
    "this_morning",
    "this_afternoon",
    "this_evening",
    "tomorrow_morning",
    "tomorrow_afternoon",
    "next_12_hours",
    "next_24_hours",
)

SKILLS = ("beginner", "intermediate", "advanced")

# Clock hours in Pacific/Auckland. The end hour is exclusive.
_CLOCKS = {
    "this_morning": (5, 11),
    "this_afternoon": (12, 18),
    "this_evening": (17, 21),
    "tomorrow_morning": (5, 11),
    "tomorrow_afternoon": (12, 18),
}

_TODAY = ("this_morning", "this_afternoon", "this_evening")

# Spoken in the tool result. The parameter name stays on the tool call only.
_SPOKEN = {
    "now": "the next three hours",
    "this_morning": "this morning",
    "this_afternoon": "this afternoon",
    "this_evening": "this evening",
    "tomorrow_morning": "tomorrow morning",
    "tomorrow_afternoon": "tomorrow afternoon",
    "next_12_hours": "the next 12 hours",
    "next_24_hours": "the next 24 hours",
    "rest_of_today": "the rest of today",
}

_GONE = {
    "this_morning": "The morning's gone.",
    "this_afternoon": "The afternoon's gone.",
    "this_evening": "The evening's gone.",
}

# Once the evening window has started, a passed request moves to tomorrow
# morning. Earlier than that, it moves to whatever is left of today, which
# runs until the evening window ends.
_EVENING_HOUR = 17
_SURF_DAY_END = 21

WHEN_HELP = (
    "Pacific/Auckland window. now is the next 3 hours. "
    "this_morning is 05:00-11:00, this_afternoon is 12:00-18:00, "
    "this_evening is 17:00-21:00. tomorrow_morning and tomorrow_afternoon "
    "use those clocks tomorrow. next_12_hours and next_24_hours start at "
    "the current hour. If that part of today has already passed, the tool "
    "checks the rest of today, or tomorrow morning once it is evening."
)


@dataclass(frozen=True)
class TimeWindow:
    """A half-open Auckland window.

    ``end`` is exclusive. ``message`` is set only when this named window has
    already passed. The answer then uses a later window, and says so.
    """

    name: str
    start: datetime
    end: datetime
    message: str | None = None

    @property
    def passed(self) -> bool:
        return self.message is not None


def resolve_when(when: str, now: datetime) -> TimeWindow:
    """Turn a window name into Pacific/Auckland start and end.

    The window named ``now`` is the next three hours from the current hour.
    Named parts of today keep their clocks. Once that clock has passed,
    ``message`` says so in ordinary words. Tomorrow's windows are the next
    calendar day. The clocks are built in Pacific/Auckland, so a
    daylight-saving morning gets that morning's real offset.
    """
    if when not in WHENS:
        raise ValueError(f"unknown when: {when}")
    local = _aware(now)

    if when == "now":
        start = _floor_hour(local)
        return TimeWindow(when, start, start + timedelta(hours=3))
    if when == "next_12_hours":
        start = _floor_hour(local)
        return TimeWindow(when, start, start + timedelta(hours=12))
    if when == "next_24_hours":
        start = _floor_hour(local)
        return TimeWindow(when, start, start + timedelta(hours=24))

    start_hour, end_hour = _CLOCKS[when]
    day = local.date()
    if when not in _TODAY:
        day += timedelta(days=1)
    start = _clock(day, start_hour)
    end = _clock(day, end_hour)
    if when in _TODAY and local >= end:
        return TimeWindow(when, start, end, message=_passed_message(when, end))
    return TimeWindow(when, start, end)


def _passed_message(name: str, end: datetime) -> str:
    clock = end.strftime("%H:%M")
    return f"{_GONE[name]} It ended at {clock}."


def window_for_answer(when: str, now: datetime) -> tuple[TimeWindow, str | None]:
    """The window to rate, plus a spoken note when the request had passed.

    Before evening, a passed morning or afternoon is answered with the rest
    of today. From 17:00, the next sensible check is tomorrow morning. The
    note is what the surfer should hear, with no parameter names in it.
    """
    requested = resolve_when(when, now)
    if not requested.passed:
        return requested, None

    local = _aware(now)
    gone = _GONE[when]
    if local.hour >= _EVENING_HOUR:
        later = resolve_when("tomorrow_morning", local)
        return later, f"{gone} Here's tomorrow morning."

    start = _floor_hour(local)
    end = _clock(local.date(), _SURF_DAY_END)
    if start >= end:
        later = resolve_when("tomorrow_morning", local)
        return later, f"{gone} Here's tomorrow morning."
    return (
        TimeWindow("rest_of_today", start, end),
        f"{gone} Here's the rest of today.",
    )


def _aware(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(AUCKLAND)


def _floor_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def _clock(day: date, hour: int) -> datetime:
    # ZoneInfo picks the offset for that civil hour, so a morning after the
    # April fallback is standard time and a morning after the September
    # change is daylight time.
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=AUCKLAND)


def _hours_until(now: datetime, end: datetime) -> int:
    """How many forecast hours to request so the window is covered.

    The forecast starts at the current hour, not at the window, so a
    question about tomorrow still has to fetch the hours in between.
    """
    start = _floor_hour(now.astimezone(AUCKLAND))
    count = math.ceil((end - start).total_seconds() / 3600)
    return max(count, 1)


def load_forecast(spot: Spot, hours: int) -> SpotForecast:
    """Download one spot's forecast. This is the network call for a check."""
    with make_client() as client:
        return fetch_forecast(client, spot, hours)


def load_tide_events(start: datetime, end: datetime) -> list[TideEvent]:
    """Load every Tauranga year the window touches.

    A window that crosses New Year needs the next file as well, or the last
    hours would have no tide. Matches the check command.
    """
    if end <= start:
        return []
    last = end - timedelta(microseconds=1)
    events: list[TideEvent] = []
    for year in range(start.year, last.year + 1):
        text = download_year(year).read_text(encoding="utf-8-sig")
        events.extend(parse_predictions(text))
    return events


@dataclass
class ToolDeps:
    """Where a tool reads spots, forecasts and tides.

    Tests pass fakes. The defaults are the live loaders, and the only path
    that touches the network.
    """

    spots: Callable[[], list[Spot]] = load_spots
    forecast: Callable[[Spot, int], SpotForecast] = load_forecast
    tides: Callable[[datetime, datetime], list[TideEvent]] = load_tide_events


def list_spots(*, deps: ToolDeps | None = None) -> dict:
    """Ids and names the model can match against a place the surfer said."""
    loaded = (deps or ToolDeps()).spots()
    return {
        "spots": [
            {
                "id": spot.id,
                "name": spot.name,
                "region": spot.region,
                "min_skill": spot.min_skill,
                "access": spot.access,
            }
            for spot in loaded
        ]
    }


def check_spot(
    spot_id: str,
    when: str,
    *,
    deps: ToolDeps | None = None,
    now: datetime | None = None,
) -> dict:
    """The conditions report for one spot, as compact JSON."""
    source = deps or ToolDeps()
    try:
        local = _aware(now or datetime.now(AUCKLAND))
        window, passed_note = window_for_answer(when, local)
    except ValueError as exc:
        return {"error": str(exc)}

    spots = source.spots()
    try:
        spot = get_spot(spots, spot_id)
    except ValueError:
        return _unknown_spot(spot_id, spots)

    try:
        events = source.tides(window.start, window.end)
        forecast = source.forecast(spot, _hours_until(local, window.end))
        report = build_report(spot, forecast, events, window.start, window.end)
    except (httpx.HTTPError, ValueError, OSError) as exc:
        return {"error": f"could not check {spot.id}: {exc}"}

    payload = _spot_payload(report)
    payload.update(_window_fields(window, local, when, passed_note))
    payload["attributions"] = list(report.attributions)
    return payload


def rank_spots(
    when: str,
    skill: Skill | None = None,
    *,
    deps: ToolDeps | None = None,
    now: datetime | None = None,
) -> dict:
    """Every spot ordered by its best hour, with harder spots set aside."""
    source = deps or ToolDeps()
    try:
        local = _aware(now or datetime.now(AUCKLAND))
        window, passed_note = window_for_answer(when, local)
    except ValueError as exc:
        return {"error": str(exc)}

    spots = source.spots()
    try:
        events = source.tides(window.start, window.end)
        reports = [
            build_report(
                spot,
                source.forecast(spot, _hours_until(local, window.end)),
                events,
                window.start,
                window.end,
            )
            for spot in spots
        ]
        ranking = order_spots(reports, skill)
    except (httpx.HTTPError, ValueError, OSError) as exc:
        return {"error": f"could not rank spots: {exc}"}

    payload = _window_fields(window, local, when, passed_note)
    payload["skill"] = skill
    payload["ranked"] = [_ranked_row(row) for row in ranking.ranked]
    payload["above_level"] = [_above_row(report) for report in ranking.above_level]
    payload["attributions"] = _attributions(reports)
    return payload


def _unknown_spot(spot_id: str, spots: list[Spot]) -> dict:
    return {
        "error": f"Unknown spot id: {spot_id}",
        "valid_ids": [spot.id for spot in spots],
    }


def _window_fields(
    window: TimeWindow,
    now: datetime,
    asked: str,
    passed_note: str | None,
) -> dict:
    # ``checked`` is ordinary speech. The parameter name is not repeated
    # here, or the model reads it out to the surfer.
    fields = {
        "checked": _SPOKEN[window.name],
        "timezone": "Pacific/Auckland",
        "now": now.strftime("%Y-%m-%d %H:%M"),
        "window": {
            "start": window.start.strftime("%Y-%m-%d %H:%M"),
            "end": window.end.strftime("%Y-%m-%d %H:%M"),
        },
    }
    if passed_note is not None:
        fields["asked"] = _SPOKEN[asked]
        fields["passed_note"] = passed_note
    return fields


def _spot_payload(report: ConditionsReport) -> dict:
    return {
        "spot_id": report.spot_id,
        "name": report.spot_name,
        "min_skill": report.min_skill,
        "access": report.access,
        "hazards": list(report.hazards),
        "uncertainties": _cap_notes(report.uncertainties),
        "best_hour": _best_hour(report),
        "hour_count": len(report.hours),
        "hours": [_hour_payload(hour) for hour in _sample(report)],
    }


def _ranked_row(row: RankedSpot) -> dict:
    payload = _spot_payload(row.report)
    payload["rank"] = row.rank
    return payload


def _above_row(report: ConditionsReport) -> dict:
    # The phrase is fixed so the model says "above your level" rather than
    # inventing a softer warning.
    payload = _spot_payload(report)
    payload["note"] = "above your level"
    return payload


def _best_hour(report: ConditionsReport) -> dict | str:
    # A zero score is not a session. Naming that hour would sound like a
    # recommendation to paddle out when it is flat.
    best = report.best_hour
    if best is None:
        return "no forecast hours"
    if best.score == 0:
        return "no surfable hours"
    return _hour_payload(best)


def _sample(report: ConditionsReport) -> list[HourRating]:
    """A few hours, always including the best one when there is one."""
    hours = report.hours
    if len(hours) <= HOUR_SAMPLE:
        return list(hours)
    chosen = [hours[0], hours[-1]]
    if report.best_hour is not None:
        chosen.append(report.best_hour)
    seen: set[datetime] = set()
    unique: list[HourRating] = []
    for hour in chosen:
        if hour.time in seen:
            continue
        seen.add(hour.time)
        unique.append(hour)
    if len(unique) < HOUR_SAMPLE:
        rest = sorted(hours, key=lambda hour: (-hour.score, hour.time))
        for hour in rest:
            if hour.time in seen:
                continue
            seen.add(hour.time)
            unique.append(hour)
            if len(unique) == HOUR_SAMPLE:
                break
    unique.sort(key=lambda hour: hour.time)
    return unique


def _hour_payload(hour: HourRating) -> dict:
    parts = (
        hour.contributions.swell,
        hour.contributions.wind,
        hour.contributions.window,
        hour.contributions.tide,
    )
    reasons = [part.reason for part in parts if part.points != 0]
    if not reasons:
        reasons = [hour.contributions.swell.reason]
    return {
        "time": hour.time.strftime("%Y-%m-%d %H:%M"),
        "score": hour.score,
        "label": hour.label,
        "swell": hour.swell.reason,
        "wind": hour.wind.reason,
        "tide": hour.tide.reason,
        "reasons": reasons,
    }


def _cap_notes(notes: list[str], limit: int = 4) -> list[str]:
    """Keep the profile notes and the fetch time, and shorten a long middle.

    A day of missing tides would otherwise repeat one line per hour.
    """
    if len(notes) <= limit:
        return list(notes)
    hidden = len(notes) - limit
    return notes[: limit - 1] + [f"{hidden} more notes were left out.", notes[-1]]


def _attributions(reports: list[ConditionsReport]) -> list[str]:
    seen: list[str] = []
    for report in reports:
        for line in report.attributions:
            if line not in seen:
                seen.append(line)
    return seen


def _check_when(value: str) -> str:
    if value not in WHENS:
        raise ValueError(f"when must be one of: {', '.join(WHENS)}")
    return value


class CheckSpotArgs(BaseModel):
    spot_id: str = Field(min_length=1)
    when: str

    @field_validator("when")
    @classmethod
    def _when(cls, value: str) -> str:
        return _check_when(value)


class RankSpotsArgs(BaseModel):
    when: str
    skill: Skill | None = None

    @field_validator("when")
    @classmethod
    def _when(cls, value: str) -> str:
        return _check_when(value)


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


_WHEN_PROPERTY = {"type": "string", "enum": list(WHENS), "description": WHEN_HELP}

TOOLS = [
    _schema(
        "list_spots",
        "List surf spots the conditions check knows. Call this to map a name "
        "such as the Mount or Papamoa to a spot id before checking conditions.",
        {},
        [],
    ),
    _schema(
        "check_spot",
        "Rate one spot for a time window. The score is already decided. "
        "Phrase this result, and do not invent a different score.",
        {
            "spot_id": {
                "type": "string",
                "description": "Spot id from list_spots.",
            },
            "when": _WHEN_PROPERTY,
        },
        ["spot_id", "when"],
    ),
    _schema(
        "rank_spots",
        "Rank every spot for a time window. Spots harder than skill are listed "
        "separately as above your level. Omit skill to rank every spot.",
        {
            "when": _WHEN_PROPERTY,
            "skill": {
                "type": "string",
                "enum": list(SKILLS),
                "description": "Surfer's level. Omit it when they have not said.",
            },
        },
        ["when"],
    ),
]


def dispatch(
    name: str,
    arguments: dict | str | None = None,
    *,
    deps: ToolDeps | None = None,
    now: datetime | None = None,
) -> str:
    """Run one tool and return its JSON result.

    Bad arguments and unknown tools come back as an error object. They do
    not raise, so a muddled tool call cannot crash the chat.
    """
    try:
        payload = _object(arguments)
    except (TypeError, ValueError) as exc:
        return _dump({"error": str(exc)})

    try:
        if name == "list_spots":
            result = list_spots(deps=deps)
        elif name == "check_spot":
            args = CheckSpotArgs.model_validate(payload)
            result = check_spot(args.spot_id, args.when, deps=deps, now=now)
        elif name == "rank_spots":
            args = RankSpotsArgs.model_validate(payload)
            result = rank_spots(args.when, args.skill, deps=deps, now=now)
        else:
            result = {
                "error": f"Unknown tool: {name}",
                "tools": ["list_spots", "check_spot", "rank_spots"],
            }
    except ValidationError as exc:
        detail = exc.errors()[0]["msg"] if exc.errors() else "invalid arguments"
        result = {"error": f"Invalid arguments for {name}.", "detail": detail}
    return _dump(result)


def _object(arguments: dict | str | None) -> dict:
    if arguments is None or arguments == "":
        return {}
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str):
        raise TypeError("tool arguments must be a JSON object")
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise ValueError("tool arguments are not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise TypeError("tool arguments must be a JSON object")
    return parsed


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)
