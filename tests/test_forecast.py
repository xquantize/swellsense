import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from swellsense.forecast.models import AUCKLAND, HourlyConditions
from swellsense.forecast.openmeteo import OPEN_METEO_ATTRIBUTION, fetch_forecast
from swellsense.spots.models import Spot

MARINE_KEYS = (
    "wave_height",
    "wave_period",
    "wave_direction",
    "swell_wave_height",
    "swell_wave_period",
    "swell_wave_direction",
    "wind_wave_height",
    "wind_wave_period",
    "wind_wave_direction",
)
WIND_KEYS = ("wind_speed_10m", "wind_gusts_10m", "wind_direction_10m")

_ATTRIBUTION = (
    "Weather data by Open-Meteo.com (https://open-meteo.com/), "
    "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). "
    "Free API for non-commercial use only."
)


def _spot(**overrides: object) -> Spot:
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
    data.update(overrides)
    return Spot.model_validate(data)


def _series(times: list[str], keys: tuple[str, ...], **columns: list) -> dict:
    hourly = {"time": times}
    for key in keys:
        hourly[key] = columns.get(key, [1.0] * len(times))
    return {"hourly": hourly}


def test_attribution_is_the_open_meteo_credit():
    assert OPEN_METEO_ATTRIBUTION == _ATTRIBUTION


def test_combines_both_apis_by_hour_and_converts_daylight_saving(tmp_path):
    # January is NZDT (UTC+13). July is NZST (UTC+12). Wind times are reversed
    # so a zip by index would attach July's wind to January's swell.
    marine_times = ["2026-01-15T00:00", "2026-07-15T00:00"]
    wind_times = ["2026-07-15T00:00", "2026-01-15T00:00"]
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        params = request.url.params
        assert params["timezone"] == "GMT"
        assert params["forecast_hours"] == "2"
        assert float(params["latitude"]) == pytest.approx(-37.58)
        assert float(params["longitude"]) == pytest.approx(176.22)
        if request.url.host == "marine-api.open-meteo.com":
            assert request.url.path == "/v1/marine"
            assert params["hourly"] == ",".join(MARINE_KEYS)
            return httpx.Response(
                200,
                json=_series(
                    marine_times,
                    MARINE_KEYS,
                    swell_wave_height=[1.5, 2.5],
                    swell_wave_period=[None, 11.0],
                    swell_wave_direction=[40, 90],
                    wind_wave_height=[0.0, 0.4],
                ),
            )
        assert request.url.host == "api.open-meteo.com"
        assert request.url.path == "/v1/forecast"
        assert params["wind_speed_unit"] == "kn"
        assert params["hourly"] == ",".join(WIND_KEYS)
        return httpx.Response(
            200,
            json=_series(
                wind_times,
                WIND_KEYS,
                wind_speed_10m=[3.0, 8.0],
                wind_gusts_10m=[9.0, None],
                wind_direction_10m=[180, 220],
            ),
        )

    spot = _spot(forecast_lat=-37.58, forecast_lon=176.22)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    forecast = fetch_forecast(client, spot, hours=2, cache_dir=tmp_path)

    january, july = forecast.hours
    assert january.time == datetime(2026, 1, 15, 13, 0, tzinfo=AUCKLAND)
    assert january.time.utcoffset() == timedelta(hours=13)
    assert january.swell_height_m == 1.5
    assert january.swell_period_s is None
    assert january.swell_direction_deg == 40
    assert january.wind_wave_height_m == 0.0
    assert january.wind_speed_kn == 8.0
    assert january.wind_gust_kn is None
    assert january.wind_direction_deg == 220

    assert july.time == datetime(2026, 7, 15, 12, 0, tzinfo=AUCKLAND)
    assert july.time.utcoffset() == timedelta(hours=12)
    assert july.swell_height_m == 2.5
    assert july.swell_period_s == 11.0
    assert july.wind_speed_kn == 3.0
    assert july.wind_direction_deg == 180
    assert forecast.spot_id == "example"
    assert forecast.attribution == OPEN_METEO_ATTRIBUTION
    assert forecast.fetched_at.tzinfo is not None
    assert seen == ["marine-api.open-meteo.com", "api.open-meteo.com"]


def test_all_null_marine_data_names_the_spot(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        times = ["2026-01-15T00:00"]
        if request.url.host == "marine-api.open-meteo.com":
            columns = {key: [None] for key in MARINE_KEYS}
            return httpx.Response(200, json=_series(times, MARINE_KEYS, **columns))
        return httpx.Response(200, json=_series(times, WIND_KEYS))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="Example Beach.*forecast_lat"):
        fetch_forecast(client, _spot(), hours=1, cache_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_fresh_cache_is_used_without_a_network_call(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        times = ["2026-01-15T00:00"]
        if request.url.host == "marine-api.open-meteo.com":
            return httpx.Response(
                200,
                json=_series(times, MARINE_KEYS, swell_wave_height=[1.2]),
            )
        return httpx.Response(200, json=_series(times, WIND_KEYS, wind_speed_10m=[6]))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    spot = _spot()
    first = fetch_forecast(client, spot, hours=1, cache_dir=tmp_path)
    second = fetch_forecast(client, spot, hours=1, cache_dir=tmp_path)

    assert calls["n"] == 2
    assert second.hours[0].swell_height_m == 1.2
    assert second.hours[0].wind_speed_kn == 6
    assert second.fetched_at == first.fetched_at
    assert (tmp_path / "example.json").is_file()
    assert not (tmp_path / "example.json.partial").exists()


def test_stale_cache_is_fetched_again(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        times = ["2026-01-15T00:00"]
        if request.url.host == "marine-api.open-meteo.com":
            return httpx.Response(200, json=_series(times, MARINE_KEYS))
        return httpx.Response(200, json=_series(times, WIND_KEYS))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    spot = _spot()
    fetch_forecast(client, spot, hours=1, cache_dir=tmp_path)
    path = tmp_path / "example.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["fetched_at"] = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")

    fetch_forecast(client, spot, hours=1, cache_dir=tmp_path)

    assert calls["n"] == 4


def test_naive_forecast_time_is_rejected():
    with pytest.raises(ValidationError, match="timezone-aware"):
        HourlyConditions(time=datetime(2026, 1, 15, 13, 0))
