"""Command line for SwellSense.

``ingest`` downloads sources and prints one count line per source.
``tides`` prints Tauranga high and low waters for one day.
``forecast`` prints hourly swell and wind for one spot.
``check`` rates a spot, or ranks every spot by its best hour. Ties share a
rank. ``--skill`` keeps harder spots in a separate list.
"""

import argparse
import sys
from datetime import date, datetime, timedelta

import httpx

from swellsense.conditions.rating import HourRating
from swellsense.conditions.report import (
    ConditionsReport,
    SpotRanking,
    build_report,
    rank_spots,
)
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

    check_parser = subparsers.add_parser(
        "check",
        help="Rate one spot, or rank every spot by its best hour",
    )
    check_parser.add_argument(
        "spot_id",
        nargs="?",
        metavar="SPOT",
        help="Spot to rate (omit with --all)",
    )
    check_parser.add_argument(
        "--all",
        action="store_true",
        help="Rank every spot by its best hour",
    )
    check_parser.add_argument(
        "--hours",
        type=_hours_arg,
        default=12,
        help="How many hours to rate (default: 12)",
    )
    check_parser.add_argument(
        "--skill",
        choices=["beginner", "intermediate", "advanced"],
        metavar="LEVEL",
        help="With --all, rank spots at or below this level and list the rest",
    )

    args = parser.parse_args(argv)
    if args.command == "ingest":
        return _ingest(args.source)
    if args.command == "tides":
        return _tides(args.date)
    if args.command == "forecast":
        return _forecast(args.spot_id, args.hours)
    if args.command == "check":
        return _check(args.spot_id, args.all, args.hours, args.skill)
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


def _now_nz() -> datetime:
    return datetime.now(AUCKLAND)


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


def _check(
    spot_id: str | None,
    all_spots: bool,
    hours: int,
    skill: str | None,
) -> int:
    """Print one spot's hours, or every spot ranked by its best hour."""
    if all_spots and spot_id is not None:
        print("pass a spot id or --all, not both", file=sys.stderr)
        return 2
    if not all_spots and spot_id is None:
        print("pass a spot id or --all", file=sys.stderr)
        return 2
    if skill is not None and not all_spots:
        print("--skill is only used with --all", file=sys.stderr)
        return 2

    try:
        spots = load_spots()
        if spot_id is not None:
            spots = [get_spot(spots, spot_id)]
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    start, end = _check_window(hours)
    try:
        events = _load_tide_events(start, end)
    except httpx.HTTPError as exc:
        print(f"could not download Tauranga tides: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    forecasts: list[SpotForecast] = []
    try:
        with make_client() as client:
            for spot in spots:
                forecasts.append(fetch_forecast(client, spot, hours))
    except httpx.HTTPError as exc:
        print(f"could not download the forecast: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        reports = [
            build_report(spot, forecast, events, start, end)
            for spot, forecast in zip(spots, forecasts, strict=True)
        ]
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if all_spots:
        _print_ranking(rank_spots(reports, skill), skill)
    else:
        _print_check(reports[0])
    return 0


def _check_window(hours: int) -> tuple[datetime, datetime]:
    """The next ``hours`` clock hours, starting at the current Auckland hour."""
    start = _now_nz().replace(minute=0, second=0, microsecond=0)
    return start, start + timedelta(hours=hours)


def _load_tide_events(start: datetime, end: datetime) -> list[TideEvent]:
    """Load every Tauranga year the window touches.

    A check that starts on New Year's Eve needs the next year's file as well,
    or the last hours would have no tide.
    """
    last = end - timedelta(microseconds=1)
    events: list[TideEvent] = []
    for year in range(start.year, last.year + 1):
        text = download_year(year).read_text(encoding="utf-8-sig")
        events.extend(parse_predictions(text))
    return events


def _print_check(report: ConditionsReport) -> None:
    print(f"{report.spot_name} ({report.spot_id}) (Pacific/Auckland)")
    for hour in report.hours:
        clock = hour.time.strftime("%Y-%m-%d %H:%M")
        print(f"{clock}  {hour.score:>2}  {hour.label}")
        print(f"  wind: {hour.wind.reason}")
        print(f"  swell: {hour.swell.reason}")
        print(f"  tide: {hour.tide.reason}")
        print(f"  {_score_parts(hour)}")
    _print_notes(report)


def _score_parts(hour: HourRating) -> str:
    parts = hour.contributions
    return (
        f"score: swell {parts.swell.points:+d}, wind {parts.wind.points:+d}, "
        f"window {parts.window.points:+d}, tide {parts.tide.points:+d}"
    )


def _print_notes(report: ConditionsReport) -> None:
    print()
    print("Uncertainties")
    for item in report.uncertainties:
        print(f"- {item}")
    print()
    print("Hazards")
    if report.hazards:
        for hazard in report.hazards:
            print(f"- {hazard}")
    else:
        print("- none")
    print()
    for line in report.attributions:
        print(line)


def _print_ranking(ranking: SpotRanking, skill: str | None) -> None:
    print("Ranked by best hour (Pacific/Auckland)")
    print(f"{'rank':>4}  {_ranking_header()}")
    for row in ranking.ranked:
        print(f"{row.rank:>4}  {_ranking_fields(row.report)}")
    if skill is not None:
        print()
        print("Above your level")
        if ranking.above_level:
            print(_ranking_header())
            for report in ranking.above_level:
                print(_ranking_fields(report))
        else:
            print("none")
    print()
    seen: list[str] = []
    for report in [row.report for row in ranking.ranked] + list(ranking.above_level):
        for line in report.attributions:
            if line not in seen:
                seen.append(line)
    for line in seen:
        print(line)


def _ranking_header() -> str:
    return (
        f"{'score':>5}  {'label':<5}  {'best hour':<16}  "
        f"{'min_skill':<12}  {'access':<6}  {'hazards':>7}  spot"
    )


def _ranking_fields(report: ConditionsReport) -> str:
    best = report.best_hour
    if best is None:
        score, label, clock = "-", "-", "-"
    else:
        score = str(best.score)
        label = best.label
        clock = best.time.strftime("%Y-%m-%d %H:%M")
    return (
        f"{score:>5}  {label:<5}  {clock:<16}  {report.min_skill:<12}  "
        f"{report.access:<6}  {len(report.hazards):>7}  "
        f"{report.spot_name} ({report.spot_id})"
    )


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
