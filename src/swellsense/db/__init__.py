"""Local Postgres access for processed documents and chunk embeddings."""

from swellsense.db.connection import connect, init_schema

__all__ = ["connect", "init_schema"]
