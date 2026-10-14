"""Command line for SwellSense.

``ingest`` downloads sources and prints one count line per source.
``tides`` prints Tauranga high and low waters for one day.
``forecast`` prints hourly swell and wind for one spot.
"""

import argparse
import sys
from datetime import date, datetime

import httpx

from swellsense.forecast.models import SpotForecast
from swellsense.forecast.openmeteo import fetch_forecast
from swellsense.ingest.fetchers.mediawiki import make_client
from swellsense.ingest.registry import load_sources
from swellsense.ingest.run import SourceReport, ingest
from swellsense.spots.models import Spot
from swellsense.spots.registry import get_spot, load_spots
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

    forecast_parser = subparsers.add_parser(
        "forecast", help="Print hourly swell and wind for one spot"
    )
    forecast_parser.add_argument("spot_id", metavar="SPOT")
    forecast_parser.add_argument(
        "--hours",
        type=_hours_arg,
        default=12,
        help="How many hours to fetch (default: 12)",
    )

    args = parser.parse_args(argv)
    if args.command == "ingest":
        return _ingest(args.source)
    if args.command == "tides":
        return _tides(args.date)
    if args.command == "forecast":
        return _forecast(args.spot_id, args.hours)
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


def _hours_arg(value: str) -> int:
    try:
        hours = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("hours must be a positive integer") from exc
    if hours < 1:
        raise argparse.ArgumentTypeError("hours must be a positive integer")
    return hours


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


def _forecast(spot_id: str, hours: int) -> int:
    """Print swell, wind waves and wind, then Open-Meteo's credit."""
    try:
        spot = get_spot(load_spots(), spot_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        with make_client() as client:
            forecast = fetch_forecast(client, spot, hours)
    except httpx.HTTPError as exc:
        print(f"could not download the forecast for {spot_id}: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    _print_forecast(spot, forecast)
    return 0


def _print_forecast(spot: Spot, forecast: SpotForecast) -> None:
    # Times are already Pacific/Auckland. The columns are the ones a surfer
    # scans: groundswell, the local wind chop, then the wind itself.
    print(f"{spot.name} ({spot.id}) (Pacific/Auckland)")
    print(
        f"{'time':<16}  {'swell':>8}  {'period':>8}  {'dir':>5}  "
        f"{'wind wave':>9}  {'wind':>8}  {'gust':>8}  {'dir':>5}"
    )
    for hour in forecast.hours:
        clock = hour.time.strftime("%Y-%m-%d %H:%M")
        print(
            f"{clock:<16}  "
            f"{_measure(hour.swell_height_m, 'm'):>8}  "
            f"{_measure(hour.swell_period_s, 's'):>8}  "
            f"{_degrees(hour.swell_direction_deg):>5}  "
            f"{_measure(hour.wind_wave_height_m, 'm'):>9}  "
            f"{_measure(hour.wind_speed_kn, 'kn'):>8}  "
            f"{_measure(hour.wind_gust_kn, 'kn'):>8}  "
            f"{_degrees(hour.wind_direction_deg):>5}"
        )
    print(forecast.attribution)


def _measure(value: float | None, unit: str) -> str:
    if value is None:
        return "-"
    return f"{value:.1f} {unit}"


def _degrees(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f}°"


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
