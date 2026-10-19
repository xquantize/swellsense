"""Time windows and conditions tools. No network and no model."""

import json
from datetime import datetime, timedelta

import pytest

from swellsense.chat.tools import (
    ToolDeps,
    check_spot,
    dispatch,
    list_spots,
    rank_spots,
    resolve_when,
)
from swellsense.forecast.models import AUCKLAND, HourlyConditions, SpotForecast
from swellsense.forecast.openmeteo import OPEN_METEO_ATTRIBUTION
from swellsense.spots.models import Spot
from swellsense.tides.linz import LINZ_ATTRIBUTION

NOW = datetime(2026, 1, 15, 9, 40, tzinfo=AUCKLAND)


def _spot(**updates) -> Spot:
    data = {
        "id": "example",
        "name": "Example Beach",
        "region": "Bay of Plenty",
        "lat": -37.6,
        "lon": 176.2,
        "facing_deg": 45,
        "break_type": "beach",
        "bottom": "sand",
        "swell_window": {"start_deg": 0, "end_deg": 90},
        "best_tides": ["low"],
        "tide_rising_better": None,
        "tide_confidence": "unknown",
        "tide_notes": "No settled tide call.",
        "min_skill": "beginner",
        "hazards": [],
        "access": "road",
        "notes": "A test spot.",
        "sources": [{"name": "Example", "url": "https://example.com/spot"}],
        "verified": False,
    }
    data.update(updates)
    return Spot.model_validate(data)


def _hour(when: datetime, **values) -> HourlyConditions:
    fields = {
        "swell_height_m": 1.2,
        "swell_period_s": 7,
        "swell_direction_deg": 40,
        "wind_speed_kn": 3,
        "wind_direction_deg": 225,
    }
    fields.update(values)
    return HourlyConditions(time=when, **fields)


def _forecast(spot_id: str, *hours: HourlyConditions) -> SpotForecast:
    return SpotForecast(
        spot_id=spot_id,
        fetched_at=datetime(2026, 1, 15, 8, 0, tzinfo=AUCKLAND),
        attribution=OPEN_METEO_ATTRIBUTION,
        hours=list(hours),
    )


def _deps(spots=None, forecast=None, tides=None) -> ToolDeps:
    def boom(*args, **kwargs):
        raise AssertionError("this loader must not be called")

    loaded = [_spot()] if spots is None else spots
    return ToolDeps(
        spots=lambda: loaded,
        forecast=forecast or boom,
        tides=tides or (lambda start, end: []),
    )


def test_windows_use_auckland_clocks_in_daylight_time():
    morning = resolve_when("this_morning", NOW)
    assert morning.passed is False
    assert morning.start == datetime(2026, 1, 15, 5, 0, tzinfo=AUCKLAND)
    assert morning.end == datetime(2026, 1, 15, 11, 0, tzinfo=AUCKLAND)
    assert morning.start.utcoffset() == timedelta(hours=13)

    current = resolve_when("now", NOW)
    assert current.start == datetime(2026, 1, 15, 9, 0, tzinfo=AUCKLAND)
    assert current.end == datetime(2026, 1, 15, 12, 0, tzinfo=AUCKLAND)

    assert resolve_when("next_12_hours", NOW).end == datetime(
        2026, 1, 15, 21, 0, tzinfo=AUCKLAND
    )
    assert resolve_when("next_24_hours", NOW).end == datetime(
        2026, 1, 16, 9, 0, tzinfo=AUCKLAND
    )

    tomorrow = resolve_when("tomorrow_morning", NOW)
    assert tomorrow.start == datetime(2026, 1, 16, 5, 0, tzinfo=AUCKLAND)
    assert tomorrow.end == datetime(2026, 1, 16, 11, 0, tzinfo=AUCKLAND)

    late = datetime(2026, 1, 15, 23, 10, tzinfo=AUCKLAND)
    afternoon = resolve_when("tomorrow_afternoon", late)
    assert afternoon.start == datetime(2026, 1, 16, 12, 0, tzinfo=AUCKLAND)
    assert afternoon.end == datetime(2026, 1, 16, 18, 0, tzinfo=AUCKLAND)


def test_windows_use_standard_time_in_winter():
    now = datetime(2026, 7, 15, 9, 0, tzinfo=AUCKLAND)
    window = resolve_when("this_afternoon", now)
    assert window.start == datetime(2026, 7, 15, 12, 0, tzinfo=AUCKLAND)
    assert window.end == datetime(2026, 7, 15, 18, 0, tzinfo=AUCKLAND)
    assert window.start.utcoffset() == timedelta(hours=12)


def test_morning_keeps_the_offset_across_the_daylight_saving_change():
    # 5 April 2026: clocks go back at 03:00. 01:30 is still daylight time,
    # and 05:00 that same morning is standard time.
    before_fallback = datetime(2026, 4, 5, 1, 30, tzinfo=AUCKLAND)
    assert before_fallback.utcoffset() == timedelta(hours=13)
    april = resolve_when("this_morning", before_fallback)
    assert april.start == datetime(2026, 4, 5, 5, 0, tzinfo=AUCKLAND)
    assert april.end == datetime(2026, 4, 5, 11, 0, tzinfo=AUCKLAND)
    assert april.start.utcoffset() == timedelta(hours=12)

    # 27 September 2026: clocks go forward at 02:00. 01:30 is standard time,
    # and 05:00 that morning is daylight time.
    before_forward = datetime(2026, 9, 27, 1, 30, tzinfo=AUCKLAND)
    assert before_forward.utcoffset() == timedelta(hours=12)
    september = resolve_when("this_morning", before_forward)
    assert september.start.utcoffset() == timedelta(hours=13)
    assert september.end == datetime(2026, 9, 27, 11, 0, tzinfo=AUCKLAND)


def test_a_window_that_has_passed_says_so():
    passed = resolve_when("this_morning", datetime(2026, 1, 15, 11, 0, tzinfo=AUCKLAND))
    assert passed.passed is True
    assert passed.message == "The morning's gone. It ended at 11:00."

    still_open = resolve_when(
        "this_evening", datetime(2026, 1, 15, 20, 59, tzinfo=AUCKLAND)
    )
    assert still_open.passed is False
    assert still_open.start == datetime(2026, 1, 15, 17, 0, tzinfo=AUCKLAND)
    assert still_open.end == datetime(2026, 1, 15, 21, 0, tzinfo=AUCKLAND)

    evening = resolve_when(
        "this_evening", datetime(2026, 1, 15, 21, 0, tzinfo=AUCKLAND)
    )
    assert evening.passed is True
    assert evening.message == "The evening's gone. It ended at 21:00."


def test_a_passed_morning_checks_the_rest_of_today():
    seen = {}

    def forecast(spot, count):
        seen["hours"] = count
        return _forecast(spot.id, _hour(datetime(2026, 1, 15, 15, 0, tzinfo=AUCKLAND)))

    result = check_spot(
        "example",
        "this_morning",
        deps=_deps(forecast=forecast),
        now=datetime(2026, 1, 15, 14, 10, tzinfo=AUCKLAND),
    )

    assert result["asked"] == "this morning"
    assert result["checked"] == "the rest of today"
    assert result["passed_note"] == "The morning's gone. Here's the rest of today."
    assert result["window"] == {"start": "2026-01-15 14:00", "end": "2026-01-15 21:00"}
    assert seen["hours"] == 7
    assert "this_morning" not in json.dumps(result)


def test_a_passed_afternoon_in_the_evening_checks_tomorrow_morning():
    result = check_spot(
        "example",
        "this_afternoon",
        deps=_deps(
            forecast=lambda spot, count: _forecast(
                spot.id, _hour(datetime(2026, 1, 16, 8, 0, tzinfo=AUCKLAND))
            )
        ),
        now=datetime(2026, 1, 15, 19, 0, tzinfo=AUCKLAND),
    )

    assert result["asked"] == "this afternoon"
    assert result["checked"] == "tomorrow morning"
    assert result["passed_note"] == "The afternoon's gone. Here's tomorrow morning."
    assert result["window"] == {"start": "2026-01-16 05:00", "end": "2026-01-16 11:00"}
    assert "this_afternoon" not in json.dumps(result)


def test_naive_now_is_rejected():
    with pytest.raises(ValueError):
        resolve_when("now", datetime(2026, 1, 15, 9, 0))


def test_list_spots_returns_the_fields_a_name_maps_to():
    spots = [
        _spot(),
        _spot(id="papamoa", name="Papamoa", min_skill="intermediate", access="beach"),
    ]
    result = list_spots(deps=_deps(spots=spots))
    assert result["spots"] == [
        {
            "id": "example",
            "name": "Example Beach",
            "region": "Bay of Plenty",
            "min_skill": "beginner",
            "access": "road",
        },
        {
            "id": "papamoa",
            "name": "Papamoa",
            "region": "Bay of Plenty",
            "min_skill": "intermediate",
            "access": "beach",
        },
    ]


def test_unknown_spot_lists_valid_ids():
    spots = [_spot(), _spot(id="papamoa", name="Papamoa")]
    raw = dispatch(
        "check_spot",
        {"spot_id": "nope", "when": "now"},
        deps=_deps(spots=spots),
        now=NOW,
    )
    result = json.loads(raw)
    assert result["valid_ids"] == ["example", "papamoa"]
    assert "nope" in result["error"]


def test_flat_best_hour_is_no_surfable_hours():
    hours = [
        _hour(
            datetime(2026, 1, 15, 9, 0, tzinfo=AUCKLAND),
            swell_height_m=0.1,
            swell_period_s=6,
        ),
        _hour(
            datetime(2026, 1, 15, 10, 0, tzinfo=AUCKLAND),
            swell_height_m=0.2,
            swell_period_s=6,
        ),
    ]

    def forecast(spot, count):
        return _forecast(spot.id, *hours)

    spot = _spot(hazards=["dangerous rips"], min_skill="intermediate")
    raw = dispatch(
        "check_spot",
        {"spot_id": "example", "when": "this_morning"},
        deps=_deps(spots=[spot], forecast=forecast),
        now=datetime(2026, 1, 15, 9, 0, tzinfo=AUCKLAND),
    )
    result = json.loads(raw)

    assert result["best_hour"] == "no surfable hours"
    assert result["hour_count"] == 2
    assert result["min_skill"] == "intermediate"
    assert result["hazards"] == ["dangerous rips"]
    assert "0.1" in result["hours"][0]["swell"]
    assert "6" in result["hours"][0]["swell"]
    assert any("not verified" in note for note in result["uncertainties"])
    assert "credit" not in result
    assert OPEN_METEO_ATTRIBUTION in result["attributions"]
    assert LINZ_ATTRIBUTION in result["attributions"]


def test_a_surfable_hour_keeps_size_period_and_score():
    when = datetime(2026, 1, 15, 9, 0, tzinfo=AUCKLAND)

    def forecast(spot, count):
        return _forecast(spot.id, _hour(when))

    result = check_spot(
        "example",
        "this_morning",
        deps=_deps(forecast=forecast),
        now=when,
    )

    best = result["best_hour"]
    assert best["time"] == "2026-01-15 09:00"
    assert best["score"] > 0
    assert "1.2" in best["swell"]
    assert "windswell" in best["swell"]
    assert best["reasons"]
    assert result["window"] == {
        "start": "2026-01-15 05:00",
        "end": "2026-01-15 11:00",
    }


def test_rank_spots_marks_a_harder_spot_above_level():
    when = datetime(2026, 1, 15, 8, 0, tzinfo=AUCKLAND)
    spots = [
        _spot(),
        _spot(
            id="hard",
            name="Hard Reef",
            min_skill="advanced",
            access="boat",
            hazards=["rips"],
        ),
    ]

    def forecast(spot, count):
        return _forecast(spot.id, _hour(when))

    result = rank_spots(
        "this_morning",
        "beginner",
        deps=_deps(spots=spots, forecast=forecast),
        now=when,
    )

    assert [row["spot_id"] for row in result["ranked"]] == ["example"]
    assert result["above_level"][0]["spot_id"] == "hard"
    assert result["above_level"][0]["note"] == "above your level"
    assert result["above_level"][0]["min_skill"] == "advanced"
    assert result["skill"] == "beginner"


def test_dispatch_calls_list_spots(monkeypatch):
    monkeypatch.setattr(
        "swellsense.chat.tools.list_spots",
        lambda **kwargs: {"spots": [{"id": "example"}]},
    )
    assert json.loads(dispatch("list_spots")) == {"spots": [{"id": "example"}]}


def test_dispatch_calls_check_spot(monkeypatch):
    seen = {}

    def fake(spot_id, when, **kwargs):
        seen["args"] = (spot_id, when)
        return {"ok": True}

    monkeypatch.setattr("swellsense.chat.tools.check_spot", fake)
    assert json.loads(
        dispatch("check_spot", {"spot_id": "example", "when": "now"})
    ) == {"ok": True}
    assert seen["args"] == ("example", "now")


def test_dispatch_calls_rank_spots(monkeypatch):
    seen = {}

    def fake(when, skill=None, **kwargs):
        seen["args"] = (when, skill)
        return {"ranked": []}

    monkeypatch.setattr("swellsense.chat.tools.rank_spots", fake)
    raw = dispatch("rank_spots", '{"when": "this_afternoon", "skill": "beginner"}')
    assert json.loads(raw) == {"ranked": []}
    assert seen["args"] == ("this_afternoon", "beginner")


def test_dispatch_rejects_a_bad_window_without_calling_the_tool(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("bad arguments must not run the tool")

    monkeypatch.setattr("swellsense.chat.tools.check_spot", fail)
    result = json.loads(
        dispatch("check_spot", {"spot_id": "example", "when": "yesterday"})
    )
    assert "Invalid arguments" in result["error"]


def test_dispatch_rejects_arguments_that_are_not_json():
    result = json.loads(dispatch("check_spot", "{"))
    assert "not valid JSON" in result["error"]
