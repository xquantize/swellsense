"""Hourly swell and wind for one spot, from Open-Meteo.

Two requests are combined. The Marine API supplies combined wave, swell and
wind-wave height, period and direction. The Forecast API supplies 10 m wind
speed, gusts and direction. Speed is requested in knots, so those numbers are
stored as returned. No unit is converted here.

Directions are where the swell or wind is coming from. A conditions check
compares them with a spot's swell window and with offshore, which is the
opposite of the direction the beach faces.

Open-Meteo's marine documentation says wave directions "are always reported
as the direction the waves come from. 0° = From north towards south; 90° =
From east". That sentence covers ``wave_direction``, ``swell_wave_direction``
and ``wind_wave_direction``.

Wind uses the same convention. Open-Meteo derives ``wind_direction_10m`` from
U and V components, and the inverse in ``Meteorology.uWind`` / ``vWind`` is
``u = -speed * sin(direction)`` and ``v = -speed * cos(direction)``. 0° is a
north wind, blowing toward the south, and 90° is an east wind. Ocean-current
direction is the exception they document separately: that one points where
the current is heading.

Times are requested in GMT and converted to Pacific/Auckland here. A daylight
saving hour is UTC+13 and a winter hour is UTC+12. Asking the API for a New
Zealand zone would freeze one offset across the whole response.

The free API is for non-commercial use only. Each spot's combined response is
cached for one hour so a repeated check does not call the service again.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from swellsense.forecast.models import AUCKLAND, HourlyConditions, SpotForecast
from swellsense.spots.models import Spot

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Metres and seconds. Directions are degrees the waves are coming from.
MARINE_HOURLY = (
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
# wind_speed_unit=kn applies to speed and gusts, so both are already knots.
WIND_HOURLY = (
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_direction_10m",
)

# Credit required next to displayed data, plus the non-commercial limit.
# https://open-meteo.com/en/license
# https://open-meteo.com/en/terms
OPEN_METEO_ATTRIBUTION = (
    "Weather data by Open-Meteo.com (https://open-meteo.com/), "
    "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). "
    "Free API for non-commercial use only."
)

CACHE_TTL = timedelta(hours=1)
_DEFAULT_CACHE = Path("data/cache/forecast")


def fetch_forecast(
    client: httpx.Client,
    spot: Spot,
    hours: int = 48,
    *,
    cache_dir: Path | None = None,
) -> SpotForecast:
    """Fetch an hourly forecast, using a cache newer than one hour.

    A land cell comes back with every marine value null. That raises, naming
    the spot, instead of looking like a flat sea. Set ``forecast_lat`` and
    ``forecast_lon`` offshore and try again.
    """
    if hours < 1:
        raise ValueError("hours must be at least 1")

    directory = _DEFAULT_CACHE if cache_dir is None else cache_dir
    cached = _read_cache(directory / f"{spot.id}.json", spot, hours)
    if cached is None:
        marine, wind = _download(client, spot, hours)
        fetched_at = datetime.now(UTC)
    else:
        marine = cached["marine"]
        wind = cached["wind"]
        fetched_at = datetime.fromisoformat(cached["fetched_at"])

    # Validate before caching, so a land cell or a broken payload is not kept.
    _reject_land_cell(marine, spot)
    hours_rows = _hours(marine, wind)
    if cached is None:
        _write_cache(
            directory / f"{spot.id}.json", spot, hours, fetched_at, marine, wind
        )

    return SpotForecast(
        spot_id=spot.id,
        fetched_at=fetched_at,
        hours=hours_rows,
        attribution=OPEN_METEO_ATTRIBUTION,
    )


def _download(client: httpx.Client, spot: Spot, hours: int) -> tuple[dict, dict]:
    lat, lon = spot.forecast_point()
    shared = {
        "latitude": lat,
        "longitude": lon,
        "timezone": "GMT",
        "forecast_hours": hours,
    }
    marine = _get(
        client,
        MARINE_URL,
        {**shared, "hourly": ",".join(MARINE_HOURLY)},
    )
    wind = _get(
        client,
        FORECAST_URL,
        {**shared, "hourly": ",".join(WIND_HOURLY), "wind_speed_unit": "kn"},
    )
    return marine, wind


def _get(client: httpx.Client, url: str, params: dict) -> dict:
    response = client.get(url, params=params)
    response.raise_for_status()
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise ValueError("Open-Meteo returned a response that is not JSON") from exc
    # A list or a string is still JSON, but it is not a forecast.
    if type(payload) is not dict:
        raise ValueError("Open-Meteo response has no forecast object")
    return payload


def _reject_land_cell(marine: dict, spot: Spot) -> None:
    hourly = _hourly(marine, "marine", MARINE_HOURLY)
    values = [value for key in MARINE_HOURLY for value in hourly[key]]
    if values and any(value is not None for value in values):
        return
    lat, lon = spot.forecast_point()
    raise ValueError(
        f"{spot.name} ({spot.id}) has no marine data at {lat:.4f}, {lon:.4f}. "
        "Set forecast_lat and forecast_lon slightly offshore."
    )


def _hours(marine: dict, wind: dict) -> list[HourlyConditions]:
    """Join the two payloads on the GMT timestamp, then convert the clock."""
    waves = _hourly(marine, "marine", MARINE_HOURLY)
    air = _hourly(wind, "wind", WIND_HOURLY)
    wave_at = {stamp: index for index, stamp in enumerate(waves["time"])}
    wind_at = {stamp: index for index, stamp in enumerate(air["time"])}
    # ISO-8601 GMT stamps sort in time order, including across the two APIs.
    stamps = sorted(set(wave_at) | set(wind_at))
    return [
        HourlyConditions(
            time=_auckland(stamp),
            wave_height_m=_value(waves, "wave_height", wave_at.get(stamp)),
            wave_period_s=_value(waves, "wave_period", wave_at.get(stamp)),
            wave_direction_deg=_value(waves, "wave_direction", wave_at.get(stamp)),
            swell_height_m=_value(waves, "swell_wave_height", wave_at.get(stamp)),
            swell_period_s=_value(waves, "swell_wave_period", wave_at.get(stamp)),
            swell_direction_deg=_value(
                waves, "swell_wave_direction", wave_at.get(stamp)
            ),
            wind_wave_height_m=_value(waves, "wind_wave_height", wave_at.get(stamp)),
            wind_wave_period_s=_value(waves, "wind_wave_period", wave_at.get(stamp)),
            wind_wave_direction_deg=_value(
                waves, "wind_wave_direction", wave_at.get(stamp)
            ),
            wind_speed_kn=_value(air, "wind_speed_10m", wind_at.get(stamp)),
            wind_gust_kn=_value(air, "wind_gusts_10m", wind_at.get(stamp)),
            wind_direction_deg=_value(air, "wind_direction_10m", wind_at.get(stamp)),
        )
        for stamp in stamps
    ]


def _hourly(payload: dict, label: str, keys: tuple[str, ...]) -> dict:
    try:
        hourly = payload["hourly"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{label} forecast has no hourly data") from exc
    times = hourly.get("time") if isinstance(hourly, dict) else None
    if not isinstance(times, list) or not all(isinstance(item, str) for item in times):
        raise ValueError(f"{label} forecast is missing hourly times")
    for key in keys:
        column = hourly.get(key)
        if not isinstance(column, list) or len(column) != len(times):
            raise ValueError(f"{label} forecast {key} does not match the time array")
    return hourly


def _value(hourly: dict, key: str, index: int | None) -> float | None:
    if index is None:
        return None
    value = hourly[key][index]
    if value is None:
        return None
    return float(value)


def _auckland(stamp: str) -> datetime:
    """Read a GMT timestamp and return the same instant in Pacific/Auckland."""
    parsed = datetime.fromisoformat(stamp)
    if parsed.tzinfo is None:
        # timezone=GMT returns a clock with no offset attached.
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(AUCKLAND)


def _read_cache(path: Path, spot: Spot, hours: int) -> dict | None:
    """Return a cached pair of responses when it is still the request we want."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        latitude = payload["latitude"]
        longitude = payload["longitude"]
        cached_hours = payload["hours"]
        marine = payload["marine"]
        wind = payload["wind"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        return None
    lat, lon = spot.forecast_point()
    if cached_hours != hours or payload.get("spot_id") != spot.id:
        return None
    if abs(float(latitude) - lat) > 1e-6 or abs(float(longitude) - lon) > 1e-6:
        return None
    if datetime.now(UTC) - fetched_at >= CACHE_TTL:
        return None
    if not isinstance(marine, dict) or not isinstance(wind, dict):
        return None
    return payload


def _write_cache(
    path: Path,
    spot: Spot,
    hours: int,
    fetched_at: datetime,
    marine: dict,
    wind: dict,
) -> None:
    lat, lon = spot.forecast_point()
    payload = {
        "spot_id": spot.id,
        "fetched_at": fetched_at.isoformat(),
        "latitude": lat,
        "longitude": lon,
        "hours": hours,
        "marine": marine,
        "wind": wind,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace only after a full write, so a failed download is not cached.
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(payload), encoding="utf-8")
    partial.replace(path)
