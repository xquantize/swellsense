from contextlib import nullcontext
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from swellsense.cli import main
from swellsense.forecast.models import AUCKLAND, HourlyConditions, SpotForecast
from swellsense.forecast.openmeteo import OPEN_METEO_ATTRIBUTION
from swellsense.ingest.run import RunReport, SourceReport
from swellsense.spots.models import Spot
from swellsense.tides.linz import LINZ_ATTRIBUTION

FIXTURE = Path(__file__).parent / "fixtures" / "tauranga_tides.csv"


def _report(*sources: tuple[str, SourceReport]) -> RunReport:
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    return RunReport(started_at=now, finished_at=now, sources=dict(sources))


def test_unknown_source_exits_2(capsys, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("an unknown source must not be downloaded")

    monkeypatch.setattr("swellsense.cli.make_client", fail)

    with pytest.raises(SystemExit) as caught:
        main(["ingest", "--source", "not-a-source"])

    assert caught.value.code == 2
    assert "not-a-source" in capsys.readouterr().err


def test_summary_line_and_exit_1_when_an_article_fails(capsys, monkeypatch):
    report = _report(
        ("wikipedia", SourceReport(saved=8, failed=[{"title": "Tide", "error": "500"}]))
    )
    monkeypatch.setattr("swellsense.cli.make_client", lambda: nullcontext(object()))
    monkeypatch.setattr("swellsense.cli.ingest", lambda *args, **kwargs: report)

    with pytest.raises(SystemExit) as caught:
        main(["ingest", "--source", "wikipedia"])

    assert caught.value.code == 1
    assert capsys.readouterr().out == (
        "wikipedia: 8 saved, 0 unchanged, 0 missing, 1 failed\n"
    )


def test_prints_one_line_per_source_and_exits_0(capsys, monkeypatch):
    report = _report(
        ("wikipedia", SourceReport(saved=8, missing=["Tide"])),
        ("blog", SourceReport(skipped_reason="web fetcher not implemented")),
    )
    monkeypatch.setattr("swellsense.cli.make_client", lambda: nullcontext(object()))
    monkeypatch.setattr("swellsense.cli.ingest", lambda *args, **kwargs: report)

    with pytest.raises(SystemExit) as caught:
        main(["ingest"])

    assert caught.value.code == 0
    assert capsys.readouterr().out == (
        "wikipedia: 8 saved, 0 unchanged, 1 missing, 0 failed\n"
        "blog: 0 saved, 0 unchanged, 0 missing, 0 failed (web fetcher not implemented)\n"
    )


def test_tides_prints_one_day_and_the_attribution(capsys, monkeypatch):
    monkeypatch.setattr("swellsense.cli.download_year", lambda year: FIXTURE)

    with pytest.raises(SystemExit) as caught:
        main(["tides", "--date", "2026-01-01"])

    assert caught.value.code == 0
    assert capsys.readouterr().out == (
        "Tauranga 2026-01-01 (Pacific/Auckland)\n"
        "05:31  high  1.8 m\n"
        "11:33  low   0.5 m\n"
        "17:47  high  1.9 m\n"
        f"{LINZ_ATTRIBUTION}\n"
    )


def test_tides_defaults_to_today_in_new_zealand(capsys, monkeypatch):
    seen: dict[str, int] = {}

    def fake_download(year: int) -> Path:
        seen["year"] = year
        return FIXTURE

    monkeypatch.setattr("swellsense.cli.download_year", fake_download)
    monkeypatch.setattr("swellsense.cli._today_nz", lambda: date(2026, 7, 15))

    with pytest.raises(SystemExit) as caught:
        main(["tides"])

    assert caught.value.code == 0
    assert seen["year"] == 2026
    output = capsys.readouterr().out
    assert output.startswith("Tauranga 2026-07-15 (Pacific/Auckland)\n")
    assert "01:05  low   0.3 m\n" in output
    assert "2026-01-01" not in output


def test_tides_rejects_a_bad_date():
    with pytest.raises(SystemExit) as caught:
        main(["tides", "--date", "15/01/2026"])

    assert caught.value.code == 2


def _spot() -> Spot:
    return Spot.model_validate(
        {
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
    )


def _forecast() -> SpotForecast:
    return SpotForecast(
        spot_id="example",
        fetched_at=datetime(2026, 1, 15, 0, 0, tzinfo=UTC),
        attribution=OPEN_METEO_ATTRIBUTION,
        hours=[
            HourlyConditions(
                time=datetime(2026, 1, 15, 13, 0, tzinfo=AUCKLAND),
                swell_height_m=1.2,
                swell_period_s=12.5,
                swell_direction_deg=40,
                wind_wave_height_m=0.4,
                wind_speed_kn=8,
                wind_gust_kn=12,
                wind_direction_deg=220,
            ),
            HourlyConditions(
                time=datetime(2026, 1, 15, 14, 0, tzinfo=AUCKLAND),
                swell_height_m=None,
                swell_period_s=None,
                swell_direction_deg=None,
                wind_wave_height_m=None,
                wind_speed_kn=5,
                wind_gust_kn=None,
                wind_direction_deg=180,
            ),
        ],
    )


def test_forecast_prints_the_table_and_the_attribution(capsys, monkeypatch):
    seen: dict[str, int] = {}

    def fake_fetch(client, spot, hours=48):
        seen["hours"] = hours
        assert spot.id == "example"
        return _forecast()

    monkeypatch.setattr("swellsense.cli.load_spots", lambda: [_spot()])
    monkeypatch.setattr("swellsense.cli.make_client", lambda: nullcontext(object()))
    monkeypatch.setattr("swellsense.cli.fetch_forecast", fake_fetch)

    with pytest.raises(SystemExit) as caught:
        main(["forecast", "example", "--hours", "6"])

    assert caught.value.code == 0
    assert seen["hours"] == 6
    assert capsys.readouterr().out == (
        "Example Beach (example) (Pacific/Auckland)\n"
        "time                 swell    period    dir  wind wave      wind      gust    dir\n"
        "2026-01-15 13:00     1.2 m    12.5 s    40°      0.4 m    8.0 kn   12.0 kn   220°\n"
        "2026-01-15 14:00         -         -      -          -    5.0 kn         -   180°\n"
        f"{OPEN_METEO_ATTRIBUTION}\n"
    )


def test_forecast_defaults_to_12_hours(capsys, monkeypatch):
    seen: dict[str, int] = {}

    def fake_fetch(client, spot, hours=48):
        seen["hours"] = hours
        return _forecast()

    monkeypatch.setattr("swellsense.cli.load_spots", lambda: [_spot()])
    monkeypatch.setattr("swellsense.cli.make_client", lambda: nullcontext(object()))
    monkeypatch.setattr("swellsense.cli.fetch_forecast", fake_fetch)

    with pytest.raises(SystemExit) as caught:
        main(["forecast", "example"])

    assert caught.value.code == 0
    assert seen["hours"] == 12
    assert "Example Beach" in capsys.readouterr().out


def test_forecast_unknown_spot_exits_2(capsys, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("an unknown spot must not be downloaded")

    monkeypatch.setattr("swellsense.cli.load_spots", lambda: [_spot()])
    monkeypatch.setattr("swellsense.cli.make_client", fail)

    with pytest.raises(SystemExit) as caught:
        main(["forecast", "not-a-spot"])

    assert caught.value.code == 2
    assert "not-a-spot" in capsys.readouterr().err


def test_forecast_rejects_zero_hours():
    with pytest.raises(SystemExit) as caught:
        main(["forecast", "example", "--hours", "0"])

    assert caught.value.code == 2


def test_forecast_download_failure_exits_1(capsys, monkeypatch):
    def fail(client, spot, hours=48):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("swellsense.cli.load_spots", lambda: [_spot()])
    monkeypatch.setattr("swellsense.cli.make_client", lambda: nullcontext(object()))
    monkeypatch.setattr("swellsense.cli.fetch_forecast", fail)

    with pytest.raises(SystemExit) as caught:
        main(["forecast", "example"])

    assert caught.value.code == 1
    assert "could not download" in capsys.readouterr().err


def test_tides_download_failure_exits_1(capsys, monkeypatch):
    def fail(year: int) -> Path:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("swellsense.cli.download_year", fail)

    with pytest.raises(SystemExit) as caught:
        main(["tides", "--date", "2026-01-01"])

    assert caught.value.code == 1
    assert "could not download" in capsys.readouterr().err
