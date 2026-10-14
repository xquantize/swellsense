"""Command line for SwellSense.

``ingest`` downloads sources and prints one count line per source.
``tides`` prints Tauranga high and low waters for one day.
"""

import argparse
import sys
from datetime import date, datetime

import httpx

from swellsense.ingest.fetchers.mediawiki import make_client
from swellsense.ingest.registry import load_sources
from swellsense.ingest.run import SourceReport, ingest
from swellsense.tides.linz import (
    AUCKLAND,
    LINZ_ATTRIBUTION,
    download_year,
    parse_predictions,
)
from swellsense.tides.models import TideEvent


def main(argv: list[str] | None = None) -> None:
    """Run the command and exit with its status code."""
    raise SystemExit(_main(argv))


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swellsense")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser(
        "ingest", help="Download sources into data/raw"
    )
    ingest_parser.add_argument(
        "--source", metavar="ID", help="Download only this source"
    )

    tides_parser = subparsers.add_parser(
        "tides", help="Print Tauranga high and low waters for one day"
    )
    tides_parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        type=_date_arg,
        help="Day to print (default: today in New Zealand)",
    )

    args = parser.parse_args(argv)
    if args.command == "ingest":
        return _ingest(args.source)
    if args.command == "tides":
        return _tides(args.date)
    return 2


def _ingest(source_id: str | None) -> int:
    sources = load_sources()
    if source_id is not None:
        sources = [source for source in sources if source.id == source_id]
        if not sources:
            print(f"unknown source: {source_id}", file=sys.stderr)
            return 2

    with make_client() as client:
        report = ingest(sources, client)

    for name, source_report in report.sources.items():
        print(_summary(name, source_report))

    if any(source_report.failed for source_report in report.sources.values()):
        return 1
    return 0


def _date_arg(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def _today_nz() -> date:
    return datetime.now(AUCKLAND).date()


def _tides(day: date | None) -> int:
    """Print one day's highs and lows, then LINZ's acknowledgement."""
    if day is None:
        day = _today_nz()
    try:
        text = download_year(day.year).read_text(encoding="utf-8-sig")
        events = parse_predictions(text)
    except httpx.HTTPError as exc:
        print(f"could not download Tauranga {day.year} tides: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    day_events = [event for event in events if event.time.date() == day]
    if not day_events:
        print(f"no Tauranga tides on {day.isoformat()}", file=sys.stderr)
        return 1

    _print_tides(day, day_events)
    return 0


def _print_tides(day: date, events: list[TideEvent]) -> None:
    # Times are New Zealand civil time, the clock LINZ published.
    print(f"Tauranga {day.isoformat()} (Pacific/Auckland)")
    for event in events:
        clock = event.time.strftime("%H:%M")
        print(f"{clock}  {event.kind:<4}  {event.height_m:.1f} m")
    print(LINZ_ATTRIBUTION)


def _summary(source_id: str, report: SourceReport) -> str:
    line = (
        f"{source_id}: {report.saved} saved, {report.unchanged} unchanged, "
        f"{len(report.missing)} missing, {len(report.failed)} failed"
    )
    if report.skipped_reason is not None:
        return f"{line} ({report.skipped_reason})"
    return line


if __name__ == "__main__":
    main()
