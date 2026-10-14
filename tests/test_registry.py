from typing import Literal

import pytest
from pydantic import ValidationError

from swellsense.ingest.registry import Source, load_sources, public_sources

VALID = """
- id: wikipedia
  type: mediawiki
  api_url: https://en.wikipedia.org/w/api.php
  license: CC BY-SA 4.0
  attribution: Wikipedia contributors
  usage: open
  titles: [Surfing, Surfboard]
"""


def test_load_sources(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(VALID)

    sources = load_sources(path)

    assert len(sources) == 1
    source = sources[0]
    assert source.id == "wikipedia"
    assert source.type == "mediawiki"
    assert source.usage == "open"
    assert source.api_url == "https://en.wikipedia.org/w/api.php"
    assert source.titles == ["Surfing", "Surfboard"]
    assert source.urls == []


def test_rejects_invalid_usage(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(VALID.replace("usage: open", "usage: stolen"))

    with pytest.raises(ValidationError):
        load_sources(path)


def test_rejects_mediawiki_without_api_url(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        VALID.replace("  api_url: https://en.wikipedia.org/w/api.php\n", "")
    )

    with pytest.raises(ValidationError, match="wikipedia requires api_url"):
        load_sources(path)


def test_rejects_blank_mediawiki_api_url(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(VALID.replace("https://en.wikipedia.org/w/api.php", '"   "'))

    with pytest.raises(ValidationError, match="wikipedia requires api_url"):
        load_sources(path)


def test_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(VALID + VALID)

    with pytest.raises(ValueError, match="Duplicate source id: wikipedia"):
        load_sources(path)


def _source(source_id: str, usage: Literal["open", "permission", "private"]) -> Source:
    return Source(
        id=source_id,
        type="web",
        license="CC BY 4.0",
        attribution="Example",
        usage=usage,
        urls=["https://example.com"],
    )


def test_public_sources_keeps_open_and_permission():
    sources = [
        _source("wiki", "open"),
        _source("notes", "private"),
        _source("club", "permission"),
    ]

    public = public_sources(sources)

    assert [source.id for source in public] == ["wiki", "club"]
    assert all(source.usage in {"open", "permission"} for source in public)


def test_public_sources_drops_every_private_source():
    sources = [_source("draft", "private"), _source("scratch", "private")]

    assert public_sources(sources) == []


def test_public_sources_empty_list():
    assert public_sources([]) == []
