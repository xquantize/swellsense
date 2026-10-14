from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, Field, model_validator

Usage = Literal["open", "permission", "private"]


class Source(BaseModel):
    id: str
    type: Literal["mediawiki", "web"]
    license: str
    attribution: str
    usage: Usage
    api_url: str | None = None
    titles: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def mediawiki_source_needs_api_url(self) -> Self:
        """MediaWiki pages are downloaded from the API, so the URL is required."""
        if self.type == "mediawiki" and not (self.api_url and self.api_url.strip()):
            raise ValueError(f"mediawiki source {self.id} requires api_url")
        return self


def load_sources(path: str | Path = "data/sources.yaml") -> list[Source]:
    """Load and validate every source.

    Duplicate ids are an error. A mediawiki source with no api_url is an error.
    """
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
