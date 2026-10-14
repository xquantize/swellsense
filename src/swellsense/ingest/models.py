import hashlib
from datetime import UTC, datetime, timedelta
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from swellsense.ingest.registry import Usage


def hash_text(text: str) -> str:
    """SHA-256 hex of the page text, so a repeat download can be recognised."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def count_words(text: str) -> int:
    """Whitespace-separated words. The same rule is used for every stored page."""
    return len(text.split())


class RawDocument(BaseModel):
    """One downloaded page, stored raw so later cleaning can be rerun.

    ``id`` is ``<source_id>/<slug>``. License, attribution and usage stay on the
    document so an answer can cite the page they came from.
    """

    id: str
    source_id: str
    title: str
    url: str
    license: str
    attribution: str
    usage: Usage
    fetched_at: datetime
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    word_count: int = Field(ge=0)
    text: str

    @field_validator("source_id")
    @classmethod
    def source_id_is_a_directory_name(cls, value: str) -> str:
        """The source id is a folder under data/raw, so it has to be one segment."""
        if value in {"", ".", ".."} or "/" in value or "\\" in value:
            raise ValueError("source_id must be a single directory name")
        return value

    @field_validator("fetched_at")
    @classmethod
    def fetched_at_must_be_utc(cls, value: datetime) -> datetime:
        """Fetch times are UTC so two machines can compare them."""
        offset = value.utcoffset()
        if offset != timedelta(0):
            raise ValueError("fetched_at must be UTC")
        return value.replace(tzinfo=UTC)

    @model_validator(mode="after")
    def stats_and_id_match_the_page(self) -> Self:
        """Keep the stored hash, word count and id tied to this page.

        The hash and word count are checked here so a file cannot claim a
        different text than the one it holds. The id is checked against the
        slug so the filename and the id stay the same string.
        """
        if self.content_hash != hash_text(self.text):
            raise ValueError("content_hash must be the sha256 hex of text")
        if self.word_count != count_words(self.text):
            raise ValueError("word_count must be the number of words in text")

        # Lazy import: store.py imports this class, and slugify lives there.
        from swellsense.ingest.store import slugify

        slug = slugify(self.title)
        if slug == "":
            raise ValueError("title must contain a letter or number")
        expected = f"{self.source_id}/{slug}"
        if self.id != expected:
            raise ValueError(f"id must be {expected}")
        return self
