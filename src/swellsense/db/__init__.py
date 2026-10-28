"""Local Postgres access for processed documents and chunk embeddings."""

from swellsense.db.chunks import (
    ChunkHit,
    delete_chunks_except,
    existing_hashes,
    nearest,
    upsert_chunks,
    upsert_document,
)
from swellsense.db.connection import connect, init_schema

__all__ = [
    "ChunkHit",
    "connect",
    "delete_chunks_except",
    "existing_hashes",
    "init_schema",
    "nearest",
    "upsert_chunks",
    "upsert_document",
]
