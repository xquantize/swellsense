import pytest

from swellsense.conditions.angles import angle_diff, in_window


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (370, 10, 0),
        (720, 0, 0),
        (-10, 10, 20),
        (-90, 90, 180),
        (0, 181, 179),
        (0, 190, 170),
        (359.5, 0.5, 1.0),
    ],
)
def test_angle_diff_edge_cases(a: float, b: float, expected: float) -> None:
    assert angle_diff(a, b) == expected
    assert angle_diff(b, a) == expected


@pytest.mark.parametrize(
    ("deg", "start", "end", "expected"),
    [
        (-10, 330, 60, True),
        (-31, 330, 60, False),
        (359.5, 330, 60, True),
        (60.5, 330, 60, False),
        (45, 390, 60, True),
        (20, 390, 60, False),
        (10, -30, 60, True),
        (329, -30, 60, False),
        (0, 0, 0, True),
        (1, 0, 0, False),
        (359, 0, 0, False),
    ],
)
def test_in_window_edge_cases(
    deg: float, start: float, end: float, expected: bool
) -> None:
    assert in_window(deg, start, end) is expected
