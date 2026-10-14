"""Compass arithmetic for swell windows and wind direction.

Degrees wrap at north. These two helpers are the only place that wrap is
handled, so a classifier can compare directions without re-implementing it.
"""


def angle_diff(a: float, b: float) -> float:
    """Smallest angle between two directions, from 0 to 180.

    350° and 10° are 20° apart. The long way around, 340°, is never returned.
    """
    diff = (a - b) % 360
    if diff > 180:
        return 360 - diff
    return diff


def in_window(deg: float, start: float, end: float) -> bool:
    """True when ``deg`` lies on the closed arc from ``start`` to ``end``.

    The arc runs in the direction of increasing degrees. When ``end`` is
    numerically smaller than ``start``, the arc crosses north, for example
    330° to 60°.
    """
    deg = deg % 360
    start = start % 360
    end = end % 360
    if start <= end:
        return start <= deg <= end
    return deg >= start or deg <= end
