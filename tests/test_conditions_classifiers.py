from datetime import UTC, datetime

import pytest

from swellsense.conditions.angles import angle_diff, in_window
from swellsense.conditions.swell import classify_swell
from swellsense.conditions.tide import classify_tide
from swellsense.conditions.wind import classify_wind
from swellsense.spots.models import Spot
from swellsense.tides.models import TideEvent, TidePhase, TideState

# A beach facing north-east. Offshore wind comes from the south-west.
FACING = 45
OFFSHORE = (FACING + 180) % 360


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
        "tide_notes": "No settled tide call.",
        "min_skill": "beginner",
        "hazards": [],
        "access": "road",
        "notes": "A test spot.",
        "sources": [{"name": "Example", "url": "https://example.com/spot"}],
        "verified": False,
    }
    data.update(overrides)
    return Spot.model_validate(data)


def _tide(phase: TidePhase, rising: bool) -> TideState:
    earlier = TideEvent(
        time=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        height_m=0.4 if rising else 1.6,
        kind="low" if rising else "high",
    )
    later = TideEvent(
        time=datetime(2026, 1, 1, 6, 0, tzinfo=UTC),
        height_m=1.6 if rising else 0.4,
        kind="high" if rising else "low",
    )
    return TideState(
        height_m=1.0,
        rising=rising,
        phase=phase,
        previous_event=earlier,
        next_event=later,
    )


def test_angle_diff_across_north_is_the_short_way():
    assert angle_diff(350, 10) == 20
    assert angle_diff(10, 350) == 20
    assert angle_diff(0, 180) == 180
    assert angle_diff(20, 20) == 0


def test_in_window_crosses_north_and_keeps_its_ends():
    assert in_window(0, 330, 60)
    assert in_window(360, 330, 60)
    assert in_window(330, 330, 60)
    assert in_window(60, 330, 60)
    assert not in_window(61, 330, 60)
    assert not in_window(329, 330, 60)
    assert in_window(0, 0, 90)
    assert in_window(90, 0, 90)
    assert not in_window(91, 0, 90)


@pytest.mark.parametrize(
    ("offset", "relation"),
    [
        (0, "offshore"),
        (45, "offshore"),
        (-45, "offshore"),
        (45.1, "cross-offshore"),
        (67.5, "cross-offshore"),
        (-67.5, "cross-offshore"),
        (67.6, "cross-shore"),
        (112.5, "cross-shore"),
        (-112.5, "cross-shore"),
        (112.6, "cross-onshore"),
        (135, "cross-onshore"),
        (-135, "cross-onshore"),
        (135.1, "onshore"),
        (180, "onshore"),
    ],
)
def test_wind_relation_at_each_boundary(offset: float, relation: str):
    judgement = classify_wind(_spot(), (OFFSHORE + offset) % 360, 12)

    assert judgement.relation == relation
    assert judgement.quality == relation
    assert judgement.strength == "moderate"


@pytest.mark.parametrize(
    ("speed", "strength", "quality"),
    [
        (0, "calm", "glassy"),
        (4.9, "calm", "glassy"),
        (5, "light", "offshore"),
        (9.9, "light", "offshore"),
        (10, "moderate", "offshore"),
        (14.9, "moderate", "offshore"),
        (15, "strong", "offshore"),
        (24.9, "strong", "offshore"),
        (25, "very strong", "offshore"),
        (40, "very strong", "offshore"),
    ],
)
def test_wind_strength_at_each_boundary(speed: float, strength: str, quality: str):
    judgement = classify_wind(_spot(), OFFSHORE, speed)

    assert judgement.strength == strength
    assert judgement.quality == quality
    assert judgement.relation == "offshore"


def test_calm_overrides_an_onshore_wind():
    judgement = classify_wind(_spot(), FACING, 3)

    assert judgement.relation == "onshore"
    assert judgement.strength == "calm"
    assert judgement.quality == "glassy"
    assert judgement.reason == "3 kn from 45°, glassy for a beach facing 45°"


def test_wind_reason_names_the_relation_and_the_facing():
    judgement = classify_wind(_spot(), 225, 12)

    assert judgement.reason == "12 kn from 225°, offshore for a beach facing 45°"


def test_offshore_direction_wraps_past_north():
    spot = _spot(facing_deg=200)
    judgement = classify_wind(spot, 20, 12)

    assert (200 + 180) % 360 == 20
    assert judgement.relation == "offshore"
    assert judgement.reason == "12 kn from 20°, offshore for a beach facing 200°"


@pytest.mark.parametrize(
    ("direction", "speed"),
    [(None, 12.0), (225.0, None), (None, None)],
)
def test_missing_wind_is_unknown(direction: float | None, speed: float | None):
    judgement = classify_wind(_spot(), direction, speed)

    assert judgement.relation == "unknown"
    assert judgement.strength == "unknown"
    assert judgement.quality == "unknown"
    assert "unknown" in judgement.reason


def test_missing_spot_does_not_crash():
    assert classify_wind(None, 225, 12).relation == "unknown"
    assert classify_swell(None, 1.2, 14, 40).in_window == "unknown"
    assert classify_tide(None, _tide("low", True)).phase == "unknown"


@pytest.mark.parametrize(
    ("direction", "fit"),
    [
        (350, "in"),
        (0, "in"),
        (10, "in"),
        (330, "in"),
        (60, "in"),
        (315, "marginal"),  # 15° outside 330°, still marginal
        (75, "marginal"),  # 15° outside 60°, still marginal
        (314, "outside"),
        (76, "outside"),
        (180, "outside"),
    ],
)
def test_swell_window_crossing_north(direction: float, fit: str):
    spot = _spot(swell_window={"start_deg": 330, "end_deg": 60})
    judgement = classify_swell(spot, 1.2, 14, direction)

    assert judgement.in_window == fit
    assert judgement.kind == "groundswell"
    assert judgement.size == "fun"


@pytest.mark.parametrize(
    ("direction", "fit"),
    [
        (0, "in"),
        (90, "in"),
        (345, "marginal"),  # 15° outside the start
        (105, "marginal"),  # 15° outside the end
        (344, "outside"),
        (106, "outside"),
    ],
)
def test_swell_marginal_band_is_15_degrees(direction: float, fit: str):
    judgement = classify_swell(_spot(), 1.0, 10, direction)

    assert judgement.in_window == fit


def test_far_side_of_a_narrow_window_is_outside():
    spot = _spot(swell_window={"start_deg": 0, "end_deg": 10})

    assert classify_swell(spot, 1.0, 10, 180).in_window == "outside"


@pytest.mark.parametrize(
    ("period", "kind"),
    [
        (0, "windswell"),
        (7.9, "windswell"),
        (8, "mixed"),
        (11.9, "mixed"),
        (12, "groundswell"),
        (18, "groundswell"),
    ],
)
def test_swell_period_boundaries(period: float, kind: str):
    judgement = classify_swell(_spot(), 1.0, period, 45)

    assert judgement.kind == kind
    assert judgement.in_window == "in"


@pytest.mark.parametrize(
    ("height", "size"),
    [
        (0, "flat"),
        (0.29, "flat"),
        (0.3, "small"),
        (0.79, "small"),
        (0.8, "fun"),
        (1.49, "fun"),
        (1.5, "solid"),
        (2.49, "solid"),
        (2.5, "big"),
        (4, "big"),
    ],
)
def test_swell_size_boundaries(height: float, size: str):
    judgement = classify_swell(_spot(), height, 10, 45)

    assert judgement.size == size


def test_swell_reason_reports_the_three_calls():
    judgement = classify_swell(_spot(), 1.2, 14, 40)

    assert judgement.reason == (
        "1.2 m at 14 s from 40°, in the swell window, groundswell, fun size"
    )


def test_size_docstring_says_open_ocean_not_breaking_height():
    doc = classify_swell.__doc__ or ""

    assert "open-ocean" in doc
    assert "breaking wave" in doc


@pytest.mark.parametrize(
    ("height", "period", "direction"),
    [
        (None, 10.0, 45.0),
        (1.0, None, 45.0),
        (1.0, 10.0, None),
        (None, None, None),
    ],
)
def test_missing_swell_is_unknown(
    height: float | None,
    period: float | None,
    direction: float | None,
):
    judgement = classify_swell(_spot(), height, period, direction)

    assert judgement.in_window == "unknown"
    assert judgement.kind == "unknown"
    assert judgement.size == "unknown"
    assert "unknown" in judgement.reason


def test_tide_suits_when_the_phase_is_preferred():
    spot = _spot(best_tides=["low", "mid"], tide_confidence="agreed")
    judgement = classify_tide(spot, _tide("low", rising=True))

    assert judgement.phase == "low"
    assert judgement.rising is True
    assert judgement.suits_spot is True
    assert judgement.uncertain is False
    assert judgement.reason == "low and rising, suits this spot"


def test_tide_does_not_suit_on_another_phase():
    spot = _spot(best_tides=["low"], tide_confidence="agreed")
    judgement = classify_tide(spot, _tide("high", rising=False))

    assert judgement.phase == "high"
    assert judgement.rising is False
    assert judgement.suits_spot is False
    assert judgement.uncertain is False
    assert judgement.reason == "high and falling, does not suit this spot"


def test_rising_tide_is_required_only_when_the_spot_prefers_it():
    spot = _spot(
        best_tides=["mid"],
        tide_rising_better=True,
        tide_confidence="agreed",
    )

    assert classify_tide(spot, _tide("mid", rising=True)).suits_spot is True
    falling = classify_tide(spot, _tide("mid", rising=False))
    assert falling.suits_spot is False
    assert falling.uncertain is False
    assert falling.reason == "mid and falling, does not suit this spot"

    no_preference = _spot(best_tides=["mid"], tide_confidence="agreed")
    assert classify_tide(no_preference, _tide("mid", rising=False)).suits_spot is True


def test_conflicting_tide_is_uncertain_even_when_it_suits():
    spot = _spot(best_tides=["low", "mid"], tide_confidence="conflicting")
    judgement = classify_tide(spot, _tide("mid", rising=True))

    assert judgement.suits_spot is True
    assert judgement.uncertain is True
    assert judgement.reason == (
        "mid and rising, suits this spot (tide call is conflicting)"
    )


def test_unknown_tide_confidence_is_uncertain():
    spot = _spot(best_tides=["low"], tide_confidence="unknown")
    judgement = classify_tide(spot, _tide("low", rising=False))

    assert judgement.suits_spot is True
    assert judgement.uncertain is True
    assert "unknown" in judgement.reason


def test_missing_tide_is_unknown():
    judgement = classify_tide(_spot(tide_confidence="agreed"), None)

    assert judgement.phase == "unknown"
    assert judgement.rising is None
    assert judgement.suits_spot is None
    assert judgement.uncertain is True
    assert judgement.reason == "The tide is missing, so the tide is unknown."
