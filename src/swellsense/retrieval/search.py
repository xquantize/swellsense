"""Vector retrieval over embedded knowledge chunks."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from swellsense.db.chunks import ChunkHit, nearest
from swellsense.llm.embeddings import embed

if TYPE_CHECKING:
    import psycopg


def retrieve(
    conn: psycopg.Connection,
    query: str,
    k: int = 5,
    *,
    embed_fn: Callable[..., list[list[float]]] = embed,
    search_fn: Callable[..., list[ChunkHit]] = nearest,
) -> list[ChunkHit]:
    """Return the k nearest public chunks for a natural-language query.

    Vector search only for now; keyword search, hybrid fusion and a relevance
    gate arrive in later roadmap slices.
    """
    if k < 1:
        msg = f"k must be at least 1, got {k}"
        raise ValueError(msg)

    stripped = query.strip()
    if not stripped:
        return []

    vector = embed_fn([stripped], "query")[0]
    return search_fn(conn, vector, k, public_only=True)
