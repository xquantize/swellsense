"""Tide height and phase at an arbitrary time.

Heights between a low and a high follow a cosine, the usual shape of one
tide. Phase splits that same vertical range into thirds: the bottom third is
low, the top third is high, and the rest is mid.
"""

import math
from datetime import datetime

from swellsense.tides.models import TideEvent, TidePhase, TideState

_LOW_PHASE = 1 / 3
_HIGH_PHASE = 2 / 3


def tide_at(events: list[TideEvent], when: datetime) -> TideState:
    """Return the tide at ``when``.

    ``when`` must fall on the closed span of the loaded events. An exact
    event time starts the interval toward the next event, so high water is
    already falling. The final event is the end of the last interval.
    """
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("when must be a timezone-aware datetime")
    if len(events) < 2:
        raise ValueError("need at least two tide events")

    ordered = sorted(events, key=lambda event: event.time)
    first = ordered[0].time
    last = ordered[-1].time
    if when < first or when > last:
        raise ValueError(
            f"{when.isoformat()} is outside the loaded tide events "
            f"({first.isoformat()} to {last.isoformat()})"
        )

    earlier, later = _bracket(ordered, when)
    height = _height(earlier, later, when)
    return TideState(
        height_m=height,
        rising=later.height_m > earlier.height_m,
        phase=_phase(height, earlier.height_m, later.height_m),
        previous_event=earlier,
        next_event=later,
    )


def _bracket(events: list[TideEvent], when: datetime) -> tuple[TideEvent, TideEvent]:
    start = 0
    for index, event in enumerate(events):
        if event.time <= when:
            start = index
        else:
            break
    if start == len(events) - 1:
        start -= 1
    return events[start], events[start + 1]


def _height(earlier: TideEvent, later: TideEvent, when: datetime) -> float:
    # The recorded high or low is returned unchanged. Cosine is only used
    # between the two times, where halfway is the mean of the two heights.
    if when == earlier.time:
        return earlier.height_m
    if when == later.time:
        return later.height_m

    span_s = (later.time - earlier.time).total_seconds()
    if span_s <= 0:
        raise ValueError("tide events must be in increasing order")
    fraction = (when - earlier.time).total_seconds() / span_s
    change = later.height_m - earlier.height_m
    return earlier.height_m + change * (1 - math.cos(math.pi * fraction)) / 2


def _phase(height_m: float, earlier: float, later: float) -> TidePhase:
    low = min(earlier, later)
    high = max(earlier, later)
    span = high - low
    if span == 0:
        return "mid"
    position = (height_m - low) / span
    if position < _LOW_PHASE:
        return "low"
    if position > _HIGH_PHASE:
        return "high"
    return "mid"
