import pytest

from swellsense.extraction.units import parse_dimension


@pytest.mark.parametrize(
    "text, expected",
    [
        ("5'8", 68),
        ("6'0\"", 72),
        ("8ft", 96),
        ("7' 4 1/2", 88.5),
        ("2 5/8", 2.625),
        ('19 3/4"', 19.75),
        ("22.5in", 22.5),
        ("5′8″", 68),
    ],
)
def test_parse_dimension(text, expected):
    assert parse_dimension(text) == expected
