import pytest
from pydantic import ValidationError

from swellsense.ingest.registry import load_sources

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


def test_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(VALID + VALID)

    with pytest.raises(ValueError, match="Duplicate source id: wikipedia"):
        load_sources(path)
