from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from swellsense.spots import Spot, get_spot, load_spots

SPOTS_PATH = Path(__file__).resolve().parents[1] / "data" / "spots.yaml"


def _base(**overrides: object) -> dict:
    spot = {
        "id": "example",
        "name": "Example",
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
    spot.update(overrides)
    return spot


def test_real_spots_yaml_loads():
    spots = load_spots(SPOTS_PATH)

    assert [spot.id for spot in spots] == [
        "mount-main-beach",
        "tay-street",
        "omanu",
        "papamoa",
        "matakana-island",
        "punis-farm",
        "waihi-beach",
    ]
    assert all(spot.verified is False for spot in spots)
    assert all(spot.facing_deg == 45 for spot in spots)
    assert all(spot.region == "Bay of Plenty" for spot in spots)
    assert all(spot.sources for spot in spots)

    mount = get_spot(spots, "mount-main-beach")
    assert mount.lat == pytest.approx(-37.632)
    assert mount.lon == pytest.approx(176.180)
    assert mount.forecast_point() == (mount.lat, mount.lon)
    assert mount.break_type == "beach"
    assert mount.bottom == "sand"
    assert mount.swell_window.start_deg == 0
    assert mount.swell_window.end_deg == 90
    assert mount.best_tides == ["low", "mid"]
    assert mount.tide_confidence == "conflicting"
    assert mount.min_skill == "beginner"

    matakana = get_spot(spots, "matakana-island")
    assert matakana.min_skill == "advanced"
    assert matakana.hazards == ["dangerous rips"]
    assert matakana.access == "boat"
    assert matakana.tide_rising_better is True

    assert get_spot(spots, "punis-farm").break_type == "point"
    assert get_spot(spots, "waihi-beach").best_tides == ["mid"]
    assert get_spot(spots, "papamoa").tide_confidence == "agreed"


def test_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "spots.yaml"
    path.write_text(yaml.safe_dump([_base(), _base()]))

    with pytest.raises(ValueError, match="Duplicate spot id: example"):
        load_spots(path)


@pytest.mark.parametrize(
    "overrides",
    [
        {"facing_deg": -1},
        {"facing_deg": 360},
        {"swell_window": {"start_deg": -1, "end_deg": 90}},
        {"swell_window": {"start_deg": 360, "end_deg": 90}},
        {"swell_window": {"start_deg": 0, "end_deg": -1}},
        {"swell_window": {"start_deg": 0, "end_deg": 360}},
    ],
)
def test_rejects_invalid_degrees(overrides):
    with pytest.raises(ValidationError):
        Spot.model_validate(_base(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"lat": -90.1},
        {"lat": 90.1},
        {"lon": -180.1},
        {"lon": 180.1},
    ],
)
def test_rejects_invalid_coordinates(overrides):
    with pytest.raises(ValidationError):
        Spot.model_validate(_base(**overrides))


def test_swell_window_may_cross_north():
    spot = Spot.model_validate(
        _base(
            facing_deg=0,
            swell_window={"start_deg": 330, "end_deg": 60},
        )
    )

    assert spot.facing_deg == 0
    assert spot.swell_window.start_deg == 330
    assert spot.swell_window.end_deg == 60

    at_top = Spot.model_validate(_base(facing_deg=359))
    assert at_top.facing_deg == 359


def test_forecast_point_defaults_to_the_beach_and_can_move_offshore():
    beach = Spot.model_validate(_base())
    assert beach.forecast_lat is None
    assert beach.forecast_point() == (-37.6, 176.2)

    offshore = Spot.model_validate(_base(forecast_lat=-37.58, forecast_lon=176.22))
    assert offshore.forecast_point() == (-37.58, 176.22)


def test_forecast_coordinates_must_be_set_together():
    with pytest.raises(ValidationError, match="forecast_lat and forecast_lon"):
        Spot.model_validate(_base(forecast_lat=-37.58))


def test_unknown_spot_id_is_a_clear_error():
    spots = load_spots(SPOTS_PATH)

    with pytest.raises(ValueError, match="Unknown spot id: not-a-spot"):
        get_spot(spots, "not-a-spot")
