import re
from fractions import Fraction

_FEET = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(?:'|’|′|ft|feet|foot)\s*(.*)$", re.IGNORECASE
)
_INCH_MARKS = re.compile(r'inches|inch|in\b|"|”|″', re.IGNORECASE)


def parse_inches(text: str) -> float:
    """'2 5/8' -> 2.625, '19 3/4"' -> 19.75, '22.5in' -> 22.5"""
    cleaned = _INCH_MARKS.sub("", text).strip()
    if not cleaned:
        return 0.0
    parts = re.split(r"[\s-]+", cleaned)
    return float(sum(Fraction(p) for p in parts if p))


def parse_dimension(text: str) -> float:
    """Feet and/or inches to decimal inches: "5'8" -> 68, '8ft' -> 96, "7' 4 1/2" -> 88.5"""
    match = _FEET.match(text)
    if match:
        feet, rest = match.groups()
        return float(feet) * 12 + parse_inches(rest)
    return parse_inches(text)
