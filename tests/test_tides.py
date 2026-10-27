from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from swellsense.tides.linz import LINZ_ATTRIBUTION, download_year, parse_predictions
from swellsense.tides.models import TideEvent
from swellsense.tides.state import tide_at

FIXTURE = Path(__file__).parent / "fixtures" / "tauranga_tides.csv"
AUCKLAND = ZoneInfo("Pacific/Auckland")

_ATTRIBUTION = (
    "This work is based on/includes Toitū Te Whenua Land Information New Zealand "
    "data which are licensed by Toitū Te Whenua Land Information New Zealand "
    "for re-use under the Creative Commons Attribution 4.0 International licence."
)


def _at(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=AUCKLAND)


def test_attribution_is_the_linz_wording():
    assert LINZ_ATTRIBUTION == _ATTRIBUTION


def test_parse_predictions_reads_times_heights_and_kinds():
    events = parse_predictions(FIXTURE.read_text(encoding="utf-8"))

    assert [(event.time, event.height_m, event.kind) for event in events] == [
        (_at(2026, 1, 1, 5, 31), 1.8, "high"),
        (_at(2026, 1, 1, 11, 33), 0.5, "low"),
        (_at(2026, 1, 1, 17, 47), 1.9, "high"),
        (_at(2026, 1, 2, 0, 5), 0.2, "low"),
        (_at(2026, 1, 2, 6, 34), 1.9, "high"),
        (_at(2026, 1, 2, 12, 37), 0.4, "low"),
        (_at(2026, 1, 2, 18, 49), 1.9, "high"),
        (_at(2026, 7, 15, 1, 5), 0.3, "low"),
        (_at(2026, 7, 15, 7, 18), 1.9, "high"),
        (_at(2026, 7, 15, 13, 26), 0.2, "low"),
        (_at(2026, 7, 15, 19, 54), 2.1, "high"),
    ]


def test_daylight_saving_and_standard_time_both_convert():
    events = parse_predictions(FIXTURE.read_text(encoding="utf-8"))
    january = events[0]
    july = next(event for event in events if event.time.month == 7)

    assert january.time == _at(2026, 1, 1, 5, 31)
    assert january.time.utcoffset() == timedelta(hours=13)
    assert july.time == _at(2026, 7, 15, 1, 5)
    assert july.time.utcoffset() == timedelta(hours=12)


def test_parse_accepts_the_bom_and_crlf_of_a_linz_download():
    text = "\ufeff" + FIXTURE.read_text(encoding="utf-8").replace("\n", "\r\n")

    assert parse_predictions(text) == parse_predictions(
        FIXTURE.read_text(encoding="utf-8")
    )


def test_download_skips_a_cached_file(tmp_path, monkeypatch):
    cached = tmp_path / "Tauranga 2026.csv"
    cached.write_text("already here", encoding="utf-8")

    def fail():
        raise AssertionError("a cached year must not be downloaded")

    monkeypatch.setattr("swellsense.tides.linz.make_client", fail)

    assert download_year(2026, tmp_path) == cached


def test_download_writes_the_linz_csv(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == (
            "https://static.charts.linz.govt.nz/tide-tables/maj-ports/csv/"
            "Tauranga%202026.csv"
        )
        return httpx.Response(200, content=b"tide-bytes")

    monkeypatch.setattr(
        "swellsense.tides.linz.make_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    path = download_year(2026, tmp_path / "tides")

    assert path.name == "Tauranga 2026.csv"
    assert path.read_bytes() == b"tide-bytes"
    assert not path.with_name(path.name + ".partial").exists()


def test_failed_download_is_not_cached(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    monkeypatch.setattr(
        "swellsense.tides.linz.make_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(httpx.HTTPStatusError):
        download_year(2026, tmp_path)

    assert list(tmp_path.iterdir()) == []


def _curve() -> list[TideEvent]:
    return [
        TideEvent(time=_at(2026, 1, 15, 0), height_m=0.0, kind="low"),
        TideEvent(time=_at(2026, 1, 15, 6), height_m=3.0, kind="high"),
        TideEvent(time=_at(2026, 1, 15, 12), height_m=0.0, kind="low"),
    ]


def test_tide_at_a_high_is_that_height_and_phase():
    state = tide_at(_curve(), _at(2026, 1, 15, 6))

    assert state.height_m == 3.0
    assert state.phase == "high"
    assert state.rising is False
    assert state.previous_event.kind == "high"
    assert state.next_event.kind == "low"


def test_halfway_from_low_to_high_is_mid_and_rising():
    state = tide_at(_curve(), _at(2026, 1, 15, 3))

    assert state.height_m == pytest.approx(1.5)
    assert state.phase == "mid"
    assert state.rising is True


def test_after_a_high_the_tide_is_falling():
    state = tide_at(_curve(), _at(2026, 1, 15, 9))

    assert state.height_m == pytest.approx(1.5)
    assert state.phase == "mid"
    assert state.rising is False
    assert state.previous_event.time == _at(2026, 1, 15, 6)
    assert state.next_event.time == _at(2026, 1, 15, 12)


def test_tide_at_outside_the_loaded_events_raises():
    events = _curve()

    with pytest.raises(ValueError, match="outside"):
        tide_at(events, _at(2026, 1, 14, 23))
    with pytest.raises(ValueError, match="outside"):
        tide_at(events, _at(2026, 1, 15, 13))


def test_naive_when_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        tide_at(_curve(), datetime(2026, 1, 15, 3, 0))
