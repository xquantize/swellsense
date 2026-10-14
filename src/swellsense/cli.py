"""Command line for SwellSense.

``ingest`` is the only command so far. It downloads sources and prints one
count line per source so a problem is visible without opening the report.
"""

import argparse
import sys

from swellsense.ingest.fetchers.mediawiki import make_client
from swellsense.ingest.registry import load_sources
from swellsense.ingest.run import SourceReport, ingest


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

    args = parser.parse_args(argv)
    if args.command == "ingest":
        return _ingest(args.source)
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
