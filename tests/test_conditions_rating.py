"""Hourly ratings and the conditions report. Fixtures only: no network."""

from datetime import UTC, datetime, timedelta

import pytest

from swellsense.conditions.rating import rate_hour, score_label
from swellsense.conditions.report import build_report, rank_spots
from swellsense.conditions.thresholds import (
    EPIC_MIN,
    FAIR_MIN,
    GOOD_MIN,
    GREAT_MIN,
    MARGINAL_WINDOW_PENALTY,
    OFFSHORE_BONUS_CUT,
    OUTSIDE_WINDOW_CAP,
    SWELL_KIND_ADJUST,
    SWELL_SIZE_BASE,
    TIDE_MISMATCH_PENALTY,
    TIDE_SUITS_BONUS,
    WIND_QUALITY_ADJUST,
)
from swellsense.forecast.models import AUCKLAND, HourlyConditions, SpotForecast
from swellsense.forecast.openmeteo import OPEN_METEO_ATTRIBUTION
from swellsense.spots.models import Spot
from swellsense.tides.linz import LINZ_ATTRIBUTION
from swellsense.tides.models import TideEvent, TideState
from swellsense.tides.state import tide_at

FACING = 45
OFFSHORE = (FACING + 180) % 360
WHEN = datetime(2026, 1, 15, 13, tzinfo=AUCKLAND)


def _spot(**overrides: object) -> Spot:
    data = {
        "id": "example",
        "name": "Example Beach",
        "region": "Bay of Plenty",
        "lat": -37.6,
        "lon": 176.2,
        "facing_deg": FACING,
        "break_type": "beach",
        "bottom": "sand",
        "swell_window": {"start_deg": 0, "end_deg": 90},
        "best_tides": ["low"],
        "tide_rising_better": None,
        "tide_confidence": "agreed",
        "tide_notes": "Low tide.",
        "min_skill": "beginner",
        "hazards": [],
        "access": "road",
        "notes": "A test spot.",
        "sources": [{"name": "Example", "url": "https://example.com/spot"}],
        "verified": False,
    }
    data.update(overrides)
    return Spot.model_validate(data)


def _hour(
    *,
    time: datetime = WHEN,
    height: float | None = 1.2,
    period: float | None = 14,
    direction: float | None = 40,
    wind_speed: float | None = 12,
    wind_direction: float | None = OFFSHORE,
) -> HourlyConditions:
    return HourlyConditions(
        time=time,
        swell_height_m=height,
        swell_period_s=period,
        swell_direction_deg=direction,
        wind_speed_kn=wind_speed,
        wind_direction_deg=wind_direction,
    )


def _tide(phase: str, rising: bool) -> TideState:
    earlier = TideEvent(
        time=datetime(2026, 1, 15, 8, tzinfo=AUCKLAND),
        height_m=0.4 if rising else 1.6,
        kind="low" if rising else "high",
    )
    later = TideEvent(
        time=datetime(2026, 1, 15, 14, tzinfo=AUCKLAND),
        height_m=1.6 if rising else 0.4,
        kind="high" if rising else "low",
    )
    return TideState(
        height_m=1.0,
        rising=rising,
        phase=phase,  # type: ignore[arg-type]
        previous_event=earlier,
        next_event=later,
    )


def _forecast(
    spot: Spot, hours: list[HourlyConditions], **overrides: object
) -> SpotForecast:
    data = {
        "spot_id": spot.id,
        "fetched_at": datetime(2026, 1, 15, 12, 30, tzinfo=AUCKLAND),
        "hours": hours,
        "attribution": OPEN_METEO_ATTRIBUTION,
    }
    data.update(overrides)
    return SpotForecast.model_validate(data)


def _points(rating: object) -> int:
    parts = rating.contributions
    return (
        parts.swell.points + parts.wind.points + parts.window.points + parts.tide.points
    )


@pytest.mark.parametrize(
    ("score", "label"),
    [
        (0, "poor"),
        (2, "poor"),
        (3, "fair"),
        (4, "fair"),
        (5, "good"),
        (6, "good"),
        (7, "great"),
        (8, "great"),
        (9, "epic"),
        (10, "epic"),
    ],
)
def test_labels_follow_the_bands(score: int, label: str):
    assert score_label(score) == label
    assert FAIR_MIN == 3
    assert GOOD_MIN == 5
    assert GREAT_MIN == 7
    assert EPIC_MIN == 9


@pytest.mark.parametrize(
    ("speed", "direction"),
    [
        (3, OFFSHORE),
        (8, OFFSHORE),
        (20, OFFSHORE),
        (30, OFFSHORE),
        (12, FACING),
        (12, (OFFSHORE + 90) % 360),
        (None, None),
    ],
)
def test_flat_swell_scores_0_whatever_the_wind(
    speed: float | None,
    direction: float | None,
):
    rating = rate_hour(
        _spot(),
        _hour(height=0.1, wind_speed=speed, wind_direction=direction),
        _tide("low", True),
    )

    assert rating.score == 0
    assert rating.label == "poor"
    assert rating.swell.size == "flat"
    assert rating.contributions.swell.points == 0
    assert rating.contributions.wind.points == 0
    assert rating.contributions.window.points == 0
    assert rating.contributions.tide.points == 0
    assert _points(rating) == rating.score


def test_glassy_groundswell_in_the_window_beats_the_same_swell_onshore():
    spot = _spot()
    glassy = rate_hour(
        spot,
        _hour(wind_speed=3, wind_direction=OFFSHORE),
        None,
    )
    onshore = rate_hour(
        spot,
        _hour(wind_speed=12, wind_direction=FACING),
        None,
    )

    assert glassy.swell.kind == "groundswell"
    assert glassy.swell.in_window == "in"
    assert glassy.wind.quality == "glassy"
    assert onshore.wind.quality == "onshore"
    assert glassy.score > onshore.score
    assert glassy.label in {"great", "epic"}


def test_small_windswell_is_low_and_fun_groundswell_is_high():
    spot = _spot()
    # Cross-shore is the neutral wind, so the score is the swell base.
    low = rate_hour(
        spot,
        _hour(height=0.5, period=6, wind_direction=(OFFSHORE + 90) % 360),
        None,
    )
    high = rate_hour(
        spot,
        _hour(height=1.2, period=14, wind_direction=(OFFSHORE + 90) % 360),
        None,
    )

    assert low.swell.size == "small"
    assert low.swell.kind == "windswell"
    assert high.swell.size == "fun"
    assert high.swell.kind == "groundswell"
    assert low.score < FAIR_MIN
    assert high.score >= GOOD_MIN
    assert low.contributions.swell.points == (
        SWELL_SIZE_BASE["small"] + SWELL_KIND_ADJUST["windswell"]
    )
    assert high.contributions.swell.points == (
        SWELL_SIZE_BASE["fun"] + SWELL_KIND_ADJUST["groundswell"]
    )


def test_outside_window_caps_the_score_and_does_not_lift_a_poor_hour():
    spot = _spot()
    inside = rate_hour(spot, _hour(direction=40, wind_speed=3), None)
    outside = rate_hour(spot, _hour(direction=180, wind_speed=3), None)
    poor = rate_hour(
        spot,
        _hour(
            height=0.5, period=6, direction=180, wind_direction=(OFFSHORE + 90) % 360
        ),
        None,
    )

    assert inside.score > OUTSIDE_WINDOW_CAP
    assert outside.score == OUTSIDE_WINDOW_CAP
    assert outside.label == "poor"
    assert outside.contributions.window.points == OUTSIDE_WINDOW_CAP - (
        outside.contributions.swell.points
        + outside.contributions.wind.points
        + outside.contributions.tide.points
    )
    assert poor.score < OUTSIDE_WINDOW_CAP
    assert poor.contributions.window.points == 0
    assert _points(outside) == outside.score
    assert _points(poor) == poor.score


def test_marginal_window_reduces_the_score():
    spot = _spot()
    inside = rate_hour(spot, _hour(direction=40, wind_speed=3), None)
    marginal = rate_hour(spot, _hour(direction=105, wind_speed=3), None)

    assert marginal.swell.in_window == "marginal"
    assert marginal.score == inside.score - MARGINAL_WINDOW_PENALTY
    assert marginal.contributions.window.points == -MARGINAL_WINDOW_PENALTY


def test_uncertain_tide_changes_nothing():
    hour = _hour(wind_speed=3)
    agreed = _spot(best_tides=["low"], tide_confidence="agreed")
    conflicting = _spot(best_tides=["low"], tide_confidence="conflicting")
    unknown = _spot(best_tides=["low"], tide_confidence="unknown")
    suits = _tide("low", True)
    misses = _tide("high", False)

    base = rate_hour(agreed, hour, None)
    conflict = rate_hour(conflicting, hour, suits)
    unsettled = rate_hour(unknown, hour, suits)
    matched = rate_hour(agreed, hour, suits)
    missed = rate_hour(agreed, hour, misses)

    assert base.tide.uncertain is True
    assert conflict.tide.uncertain is True
    assert conflict.tide.suits_spot is True
    assert conflict.score == base.score
    assert unsettled.score == base.score
    assert conflict.contributions.tide.points == 0
    assert unsettled.contributions.tide.points == 0
    assert matched.score == base.score + TIDE_SUITS_BONUS
    assert missed.score == base.score - TIDE_MISMATCH_PENALTY
    assert matched.contributions.tide.points == TIDE_SUITS_BONUS
    assert missed.contributions.tide.points == -TIDE_MISMATCH_PENALTY


def test_strong_wind_reduces_the_offshore_bonus_without_making_it_a_penalty():
    spot = _spot()
    light = rate_hour(spot, _hour(wind_speed=8, wind_direction=OFFSHORE), None)
    strong = rate_hour(spot, _hour(wind_speed=15, wind_direction=OFFSHORE), None)
    severe = rate_hour(spot, _hour(wind_speed=25, wind_direction=OFFSHORE), None)

    assert light.wind.quality == "offshore"
    assert strong.wind.strength == "strong"
    assert severe.wind.strength == "very strong"
    assert severe.contributions.wind.points <= strong.contributions.wind.points
    assert strong.contributions.wind.points < light.contributions.wind.points
    assert severe.contributions.wind.points == max(
        0,
        WIND_QUALITY_ADJUST["offshore"] - OFFSHORE_BONUS_CUT["very strong"],
    )
    assert strong.score < light.score


def test_cross_shore_wind_is_neutral():
    spot = _spot()
    cross = rate_hour(
        spot,
        _hour(wind_speed=12, wind_direction=(OFFSHORE + 90) % 360),
        None,
    )
    missing = rate_hour(spot, _hour(wind_speed=None, wind_direction=None), None)

    assert cross.wind.quality == "cross-shore"
    assert cross.contributions.wind.points == 0
    assert cross.score == missing.score


@pytest.mark.parametrize(
    "hour",
    [
        _hour(height=0.1, wind_speed=3),
        _hour(wind_speed=3),
        _hour(wind_speed=12, wind_direction=FACING),
        _hour(direction=180, wind_speed=3),
        _hour(direction=105, wind_speed=3),
        _hour(height=0.5, period=6, wind_speed=12, wind_direction=FACING),
        _hour(height=None, period=None, direction=None),
    ],
)
def test_contributions_add_up_to_the_score(hour: HourlyConditions):
    rating = rate_hour(_spot(), hour, _tide("low", True))

    assert _points(rating) == rating.score
    assert rating.label == score_label(rating.score)
    assert rating.score == (
        rating.contributions.swell.points
        + rating.contributions.wind.points
        + rating.contributions.window.points
        + rating.contributions.tide.points
    )


def test_a_penalty_cannot_push_the_score_below_zero():
    rating = rate_hour(
        _spot(),
        _hour(height=0.5, period=6, wind_speed=12, wind_direction=FACING),
        None,
    )

    assert rating.swell.size == "small"
    assert rating.swell.kind == "windswell"
    assert rating.wind.quality == "onshore"
    assert rating.score == 0
    assert rating.contributions.swell.points == (
        SWELL_SIZE_BASE["small"] + SWELL_KIND_ADJUST["windswell"]
    )
    assert rating.contributions.wind.points == -rating.contributions.swell.points
    assert _points(rating) == 0
    assert "leaves it at 0" in rating.contributions.wind.reason


def test_missing_swell_scores_0():
    rating = rate_hour(_spot(), _hour(height=None), None)

    assert rating.swell.size == "unknown"
    assert rating.score == 0
    assert rating.contributions.swell.points == 0
    assert rating.contributions.wind.points == 0


def test_best_hour_is_the_highest_score_and_the_earlier_tie():
    spot = _spot(verified=True)
    early = WHEN
    later = WHEN + timedelta(hours=2)
    forecast = _forecast(
        spot,
        [
            _hour(time=later, wind_speed=3),
            _hour(time=early, height=0.1, wind_speed=3),
            _hour(time=early + timedelta(hours=1), wind_speed=3),
        ],
    )

    report = build_report(spot, forecast, [], early, later + timedelta(hours=1))

    assert [hour.time for hour in report.hours] == [
        early,
        early + timedelta(hours=1),
        later,
    ]
    assert report.best_hour is not None
    assert report.best_hour.time == early + timedelta(hours=1)
    assert report.best_hour.score > report.hours[0].score


def test_tied_best_hours_keep_the_earlier_one():
    spot = _spot(verified=True)
    early = WHEN
    later = WHEN + timedelta(hours=2)
    forecast = _forecast(
        spot,
        [_hour(time=later, wind_speed=3), _hour(time=early, wind_speed=3)],
    )

    report = build_report(spot, forecast, [], early, later + timedelta(hours=1))

    assert report.best_hour is not None
    assert report.best_hour.time == early
    assert report.hours[0].score == report.hours[1].score


def test_hours_outside_the_window_are_left_out():
    spot = _spot(verified=True)
    forecast = _forecast(
        spot,
        [
            _hour(time=WHEN - timedelta(hours=1)),
            _hour(time=WHEN),
            _hour(time=WHEN + timedelta(hours=1)),
        ],
    )

    report = build_report(spot, forecast, [], WHEN, WHEN + timedelta(hours=1))

    assert [hour.time for hour in report.hours] == [WHEN]


def test_rank_spots_orders_by_best_hour_score():
    early = WHEN
    later = WHEN + timedelta(hours=3)
    low = _spot(id="low-spot", name="Low Spot")
    high = _spot(id="high-spot", name="High Spot")
    tied_later = _spot(id="tied-later", name="Tied Later")
    none = _spot(id="no-hours", name="No Hours")
    reports = [
        build_report(
            low,
            _forecast(low, [_hour(time=early, height=0.1)]),
            [],
            early,
            later,
        ),
        build_report(
            tied_later,
            _forecast(tied_later, [_hour(time=later, wind_speed=3)]),
            [],
            early,
            later + timedelta(hours=1),
        ),
        build_report(
            high,
            _forecast(high, [_hour(time=early, wind_speed=3)]),
            [],
            early,
            later,
        ),
        build_report(none, _forecast(none, []), [], early, later),
    ]

    ranked = rank_spots(reports)

    assert [report.spot_id for report in ranked] == [
        "high-spot",
        "tied-later",
        "low-spot",
        "no-hours",
    ]
    assert ranked[0].best_hour is not None
    assert ranked[1].best_hour is not None
    assert ranked[0].best_hour.score == ranked[1].best_hour.score
    assert ranked[0].best_hour.time < ranked[1].best_hour.time
    assert ranked[-1].best_hour is None


def test_equal_scores_at_the_same_time_break_by_spot_id():
    mango = _spot(id="mango", name="Mango")
    apple = _spot(id="apple", name="Apple")
    reports = [
        build_report(
            mango,
            _forecast(mango, [_hour(wind_speed=3)]),
            [],
            WHEN,
            WHEN + timedelta(hours=1),
        ),
        build_report(
            apple,
            _forecast(apple, [_hour(wind_speed=3)]),
            [],
            WHEN,
            WHEN + timedelta(hours=1),
        ),
    ]

    ranked = rank_spots(reports)

    assert [report.spot_id for report in ranked] == ["apple", "mango"]


def test_unverified_profile_is_an_uncertainty():
    spot = _spot(verified=False)
    report = build_report(
        spot, _forecast(spot, [_hour()]), [], WHEN, WHEN + timedelta(hours=1)
    )

    assert any("not verified" in note for note in report.uncertainties)

    checked = _spot(verified=True)
    checked_report = build_report(
        checked,
        _forecast(checked, [_hour()]),
        [],
        WHEN,
        WHEN + timedelta(hours=1),
    )
    assert all("not verified" not in note for note in checked_report.uncertainties)


def test_conflicting_and_unknown_tides_are_uncertainties():
    hour = _hour()
    window = (WHEN, WHEN + timedelta(hours=1))
    conflicting = _spot(tide_confidence="conflicting", verified=True)
    unknown = _spot(tide_confidence="unknown", verified=True)
    agreed = _spot(tide_confidence="agreed", verified=True)

    conflict_report = build_report(
        conflicting, _forecast(conflicting, [hour]), [], *window
    )
    unknown_report = build_report(unknown, _forecast(unknown, [hour]), [], *window)
    agreed_report = build_report(agreed, _forecast(agreed, [hour]), [], *window)

    assert any("conflicting" in note for note in conflict_report.uncertainties)
    assert any("unknown" in note for note in unknown_report.uncertainties)
    assert all("conflicting" not in note for note in agreed_report.uncertainties)
    assert all(
        "tide call is unknown" not in note for note in agreed_report.uncertainties
    )


def test_missing_forecast_values_and_fetched_at_are_uncertainties():
    spot = _spot(verified=True, tide_confidence="agreed")
    missing = _hour(height=None, period=None, direction=None, wind_speed=None)
    fetched_at = datetime(2026, 1, 14, 23, 0, tzinfo=UTC)
    report = build_report(
        spot,
        _forecast(spot, [missing], fetched_at=fetched_at),
        [],
        WHEN,
        WHEN + timedelta(hours=1),
    )

    assert any("missing swell and wind" in note for note in report.uncertainties)
    assert any(
        "Forecast fetched at 2026-01-15 12:00 Pacific/Auckland." in note
        for note in report.uncertainties
    )


def test_a_settled_tide_from_events_changes_the_hour():
    events = [
        TideEvent(
            time=datetime(2026, 1, 15, 6, tzinfo=AUCKLAND), height_m=0.4, kind="low"
        ),
        TideEvent(
            time=datetime(2026, 1, 15, 12, tzinfo=AUCKLAND), height_m=1.8, kind="high"
        ),
        TideEvent(
            time=datetime(2026, 1, 15, 18, tzinfo=AUCKLAND), height_m=0.3, kind="low"
        ),
    ]
    state = tide_at(events, WHEN)
    spot = _spot(
        verified=True,
        tide_confidence="agreed",
        best_tides=[state.phase],
        tide_rising_better=None,
    )
    without = build_report(
        spot,
        _forecast(spot, [_hour(wind_speed=3)]),
        [],
        WHEN,
        WHEN + timedelta(hours=1),
    )
    with_tide = build_report(
        spot,
        _forecast(spot, [_hour(wind_speed=3)]),
        events,
        WHEN,
        WHEN + timedelta(hours=1),
    )

    assert with_tide.hours[0].tide.suits_spot is True
    assert with_tide.hours[0].tide.uncertain is False
    assert with_tide.hours[0].score == without.hours[0].score + TIDE_SUITS_BONUS
    assert all("no tide prediction" not in note for note in with_tide.uncertainties)


def test_hazards_and_attributions_come_from_the_profile_and_the_sources():
    spot = _spot(hazards=["dangerous rips"])
    report = build_report(
        spot, _forecast(spot, [_hour()]), [], WHEN, WHEN + timedelta(hours=1)
    )

    spot.hazards.append("shark")

    assert report.hazards == ["dangerous rips"]
    assert report.attributions == [OPEN_METEO_ATTRIBUTION, LINZ_ATTRIBUTION]


def test_forecast_for_another_spot_is_rejected():
    spot = _spot()
    other = _forecast(_spot(id="other"), [_hour()])

    with pytest.raises(ValueError, match="other"):
        build_report(spot, other, [], WHEN, WHEN + timedelta(hours=1))
