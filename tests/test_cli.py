from contextlib import nullcontext
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from swellsense.cli import main
from swellsense.ingest.run import RunReport, SourceReport
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


def test_tides_download_failure_exits_1(capsys, monkeypatch):
    def fail(year: int) -> Path:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("swellsense.cli.download_year", fail)

    with pytest.raises(SystemExit) as caught:
        main(["tides", "--date", "2026-01-01"])

    assert caught.value.code == 1
    assert "could not download" in capsys.readouterr().err
