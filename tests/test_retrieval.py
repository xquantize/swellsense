"""Unit tests for vector retrieval (no network, no database)."""

from __future__ import annotations

import pytest

from swellsense.db.chunks import ChunkHit
from swellsense.retrieval.search import retrieve


def _hit(index: int, *, text: str = "body") -> ChunkHit:
    return ChunkHit(
        id=f"doc#{index}",
        document_id="doc",
        index=index,
        section="Intro",
        text=text,
        title="Surfing",
        url="https://example.test/surfing",
        license="CC BY-SA 4.0",
        attribution="Wiki",
        usage="open",
        distance=0.1 * index,
    )


def test_empty_or_whitespace_query_skips_embed_and_search():
    calls: list[str] = []

    def embed_fn(texts, kind):
        calls.append("embed")
        return [[0.0]]

    def search_fn(conn, vector, k, public_only):
        calls.append("search")
        return []

    conn = object()
    assert retrieve(conn, "", embed_fn=embed_fn, search_fn=search_fn) == []
    assert retrieve(conn, "   \t\n", embed_fn=embed_fn, search_fn=search_fn) == []
    assert calls == []


def test_passes_query_kind_k_and_public_only():
    seen: dict[str, object] = {}

    def embed_fn(texts, kind):
        seen["texts"] = texts
        seen["kind"] = kind
        return [[1.0, 2.0]]

    def search_fn(conn, vector, k, public_only):
        seen["conn"] = conn
        seen["vector"] = vector
        seen["k"] = k
        seen["public_only"] = public_only
        return [_hit(0), _hit(1)]

    conn = object()
    hits = retrieve(
        conn, "  rip currents  ", k=3, embed_fn=embed_fn, search_fn=search_fn
    )

    assert seen["texts"] == ["rip currents"]
    assert seen["kind"] == "query"
    assert seen["conn"] is conn
    assert seen["vector"] == [1.0, 2.0]
    assert seen["k"] == 3
    assert seen["public_only"] is True
    assert [h.index for h in hits] == [0, 1]


def test_k_zero_raises():
    with pytest.raises(ValueError, match="k must be at least 1"):
        retrieve(object(), "swell", k=0)
