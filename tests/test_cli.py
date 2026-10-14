from contextlib import nullcontext
from datetime import UTC, datetime

import pytest

from swellsense.cli import main
from swellsense.ingest.run import RunReport, SourceReport


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
