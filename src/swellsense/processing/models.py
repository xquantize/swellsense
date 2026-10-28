"""Pydantic models for processed chunks used in retrieval and citation."""

from pydantic import BaseModel

from swellsense.ingest.registry import Usage


class Chunk(BaseModel):
    """One searchable text span with citation fields copied from its source document."""

    id: str
    document_id: str
    index: int
    section: str
    text: str
    word_count: int
    content_hash: str
    title: str
    url: str
    license: str
    attribution: str
    usage: Usage
