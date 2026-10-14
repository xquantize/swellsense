from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class Source(BaseModel):
    id: str
    type: Literal["mediawiki", "web"]
    license: str
    attribution: str
    usage: Literal["open", "permission", "private"]
    api_url: str | None = None
    titles: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)


def load_sources(path: str | Path = "data/sources.yaml") -> list[Source]:
    """Load and validate every source. Duplicate ids are an error."""
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, list):
        raise TypeError(f"{path} must contain a list of sources")

    sources = [Source.model_validate(entry) for entry in raw]
    seen: set[str] = set()
    for source in sources:
        if source.id in seen:
            raise ValueError(f"Duplicate source id: {source.id}")
        seen.add(source.id)
    return sources


def public_sources(sources: list[Source]) -> list[Source]:
    """Return sources that may appear in public output.

    ``open`` and ``permission`` sources can be used anywhere, with attribution.
    ``private`` sources are local development only and must never leave the machine.
    """
    return [source for source in sources if source.usage in {"open", "permission"}]
