"""LINZ yearly tide predictions for the Port of Tauranga.

LINZ publishes one CSV per standard port per year. The file starts with three
preamble lines (port, constituent reference, unit note) and then one row per
day. A row is day, weekday, month, year, then up to four time/height pairs.
There is no high/low column. A tide is high when its height is greater than
the next prediction, which matches LINZ's own reading of the file.

The preamble says "Local Std or Daylight Time". Checked against the 2026
Tauranga CSV: a January time is UTC+13 and a July time is UTC+12, and the
LINZ tide page says the times are adjusted while daylight saving is observed.
These are New Zealand civil times, not standard time all year, so each one is
read as Pacific/Auckland.

Every Bay of Plenty spot uses this port for now. Secondary-port offsets, such
as Bowentown, come later.
"""

from csv import reader
from datetime import datetime
from io import StringIO
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from swellsense.ingest.fetchers.mediawiki import make_client
from swellsense.tides.models import TideEvent, TideKind

# Yearly standard-port file. The published name contains a space.
TAURANGA_CSV_URL = (
    "https://static.charts.linz.govt.nz/tide-tables/maj-ports/csv/Tauranga {year}.csv"
)

# Wording LINZ requires when linz.govt.nz content is adapted or included in
# another work. https://www.linz.govt.nz/copyright
LINZ_ATTRIBUTION = (
    "This work is based on/includes Toitū Te Whenua Land Information New Zealand "
    "data which are licensed by Toitū Te Whenua Land Information New Zealand "
    "for re-use under the Creative Commons Attribution 4.0 International licence."
)

AUCKLAND = ZoneInfo("Pacific/Auckland")


def download_year(year: int, root: Path = Path("data/cache/tides")) -> Path:
    """Download one year of Tauranga predictions, unless that file is cached.

    The CSV is fetched once and kept under data/cache, which is never
    committed. A later call for the same year does not touch the network.
    """
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"Tauranga {year}.csv"
    if path.exists():
        return path

    url = quote(TAURANGA_CSV_URL.format(year=year), safe=":/")
    with make_client() as client:
        response = client.get(url)
        response.raise_for_status()
        # Replace only after a full write, so a failed download is not cached.
        partial = path.with_name(path.name + ".partial")
        partial.write_bytes(response.content)
        partial.replace(path)
    return path


def parse_predictions(csv_text: str) -> list[TideEvent]:
    """Turn one LINZ yearly CSV into chronological high and low waters."""
    text = csv_text.lstrip("\ufeff")
    samples: list[tuple[datetime, float]] = []
    for row in reader(StringIO(text)):
        parts = [cell.strip() for cell in row]
        if not _is_day(parts):
            continue
        samples.extend(_row_tides(parts))

    if len(samples) < 2:
        raise ValueError("tide file has fewer than two predictions")

    samples.sort(key=lambda sample: sample[0])
    kinds = _kinds([height for _, height in samples])
    return [
        TideEvent(time=when, height_m=height, kind=kind)
        for (when, height), kind in zip(samples, kinds, strict=True)
    ]


def _is_day(parts: list[str]) -> bool:
    """True for a prediction row, false for the three preamble lines.

    The weekday is only a label. The day, month and year columns are the date.
    """
    if len(parts) < 6:
        return False
    day, weekday, month, year = parts[:4]
    return (
        day.isdigit()
        and weekday.isalpha()
        and month.isdigit()
        and len(year) == 4
        and year.isdigit()
    )


def _row_tides(parts: list[str]) -> list[tuple[datetime, float]]:
    year = int(parts[3])
    month = int(parts[2])
    day = int(parts[0])
    cells = parts[4:]
    if len(cells) % 2 != 0:
        raise ValueError(f"incomplete tide row for {year:04d}-{month:02d}-{day:02d}")

    tides: list[tuple[datetime, float]] = []
    for time_text, height_text in zip(cells[0::2], cells[1::2], strict=True):
        if time_text == "" and height_text == "":
            continue
        if time_text == "" or height_text == "":
            raise ValueError(f"incomplete tide on {year:04d}-{month:02d}-{day:02d}")
        hour_text, minute_text = time_text.split(":")
        when = datetime(
            year,
            month,
            day,
            int(hour_text),
            int(minute_text),
            tzinfo=AUCKLAND,
        )
        tides.append((when, float(height_text)))
    return tides


def _kinds(heights: list[float]) -> list[TideKind]:
    """High when this height is above the next one.

    The last prediction has no following tide in the file, so it is compared
    with the one before it. A full LINZ year alternates, which is what makes
    that last comparison the opposite of its neighbour.
    """
    kinds: list[TideKind] = []
    for index, height in enumerate(heights):
        neighbour = (
            heights[index + 1] if index + 1 < len(heights) else heights[index - 1]
        )
        if height == neighbour:
            raise ValueError(
                "adjacent tide heights are equal; high and low are unclear"
            )
        kinds.append("high" if height > neighbour else "low")
    return kinds
