from pathlib import Path

import yaml

from swellsense.spots.models import Spot


def load_spots(path: str | Path = "data/spots.yaml") -> list[Spot]:
    """Load and validate every spot profile.

    Duplicate ids are an error. Two spots with the same id would make a
    conditions check ambiguous.
    """
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, list):
        raise TypeError(f"{path} must contain a list of spots")

    spots = [Spot.model_validate(entry) for entry in raw]
    seen: set[str] = set()
    for spot in spots:
        if spot.id in seen:
            raise ValueError(f"Duplicate spot id: {spot.id}")
        seen.add(spot.id)
    return spots


def get_spot(spots: list[Spot], spot_id: str) -> Spot:
    """Return the spot with this id.

    An unknown id raises ValueError naming the id, so a typo is obvious.
    """
    for spot in spots:
        if spot.id == spot_id:
            return spot
    raise ValueError(f"Unknown spot id: {spot_id}")
