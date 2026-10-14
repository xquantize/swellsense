"""Download every source and write a run report.

One bad article is recorded and the rest still download. The counts show what
changed since the last run, and the report file is what a human reviews.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, ValidationError

from swellsense.config import get_settings
from swellsense.ingest.fetchers.mediawiki import fetch_article
from swellsense.ingest.registry import Source
from swellsense.ingest.store import save

_WEB_SKIPPED = "web fetcher not implemented"


class SourceReport(BaseModel):
    """Counts for one source in a single run."""

    saved: int = 0
    unchanged: int = 0
    missing: list[str] = Field(default_factory=list)
    failed: list[dict[str, str]] = Field(default_factory=list)
    skipped_reason: str | None = None


class RunReport(BaseModel):
    """Every source from one ingest, with the time the run started and finished."""

    started_at: datetime
    finished_at: datetime
    sources: dict[str, SourceReport]


def ingest(
    sources: list[Source],
    client: httpx.Client,
    root: Path = Path("data/raw"),
    sleep: Callable[[float], None] = time.sleep,
) -> RunReport:
    """Fetch each source and save new pages.

    ``sleep`` runs between requests so a full run stays polite to source sites.
    Web sources are skipped until a fetcher exists. The report is written to
    ``root/_last_run.json``.
    """
    started_at = datetime.now(UTC)
    delay_s = get_settings().request_delay_s
    reports: dict[str, SourceReport] = {}
    requests_made = 0

    for source in sources:
        if source.type == "web":
            reports[source.id] = SourceReport(skipped_reason=_WEB_SKIPPED)
            continue

        report = SourceReport()
        for title in source.titles:
            if requests_made:
                sleep(delay_s)
            requests_made += 1
            _fetch_title(client, source, title, root, report)
        reports[source.id] = report

    run = RunReport(
        started_at=started_at,
        finished_at=datetime.now(UTC),
        sources=reports,
    )
    _write_report(run, root)
    return run


def _fetch_title(
    client: httpx.Client,
    source: Source,
    title: str,
    root: Path,
    report: SourceReport,
) -> None:
    """Fetch and save one title. A failure is recorded and the run continues."""
    try:
        document = fetch_article(client, source, title)
        if document is None:
            report.missing.append(title)
            return
        if save(document, root):
            report.saved += 1
        else:
            report.unchanged += 1
    except (httpx.HTTPError, ValidationError) as exc:
        report.failed.append({"title": title, "error": str(exc)})


def _write_report(report: RunReport, root: Path) -> None:
    """Leave the report next to the downloads so a run can be reviewed later."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "_last_run.json"
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
