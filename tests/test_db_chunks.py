"""Integration tests for chunk store upsert, prune, and nearest."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swellsense.db import (
    ChunkHit,
    connect,
    delete_chunks_except,
    existing_hashes,
    init_schema,
    nearest,
    upsert_chunks,
    upsert_document,
)
from swellsense.ingest.models import RawDocument, count_words, hash_text
from swellsense.ingest.registry import Usage
from swellsense.ingest.store import slugify
from swellsense.processing.models import Chunk

_DIM = 768
_MODEL = "nomic-embed-text"


def _unit_vector(primary: int, sign: float = 1.0) -> list[float]:
    vec = [0.0] * _DIM
    vec[primary] = sign
    return vec


def _raw_doc(source_id: str, title: str, *, usage: Usage = "open") -> RawDocument:
    slug = slugify(title)
    doc_id = f"{source_id}/{slug}"
    text = f"Body text for {doc_id}."
    return RawDocument(
        id=doc_id,
        source_id=source_id,
        title=title,
        url=f"https://example.test/{doc_id}",
        license="CC BY-SA 4.0",
        attribution="Test attribution",
        usage=usage,
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_hash=hash_text(text),
        word_count=count_words(text),
        text=text,
    )


def _chunk(
    doc: RawDocument,
    index: int,
    *,
    section: str = "Intro",
    text: str = "chunk text",
    content_hash: str = "deadbeef",
) -> Chunk:
    return Chunk(
        id=f"{doc.id}#{index}",
        document_id=doc.id,
        index=index,
        section=section,
        text=text,
        word_count=len(text.split()),
        content_hash=content_hash,
        title=doc.title,
        url=doc.url,
        license=doc.license,
        attribution=doc.attribution,
        usage=doc.usage,
    )


@pytest.fixture
def db_conn():
    conn = connect()
    init_schema(conn)
    conn.execute("BEGIN")
    try:
        yield conn
    finally:
        conn.execute("ROLLBACK")
        conn.close()


@pytest.mark.db
def test_nearest_returns_closest_first(db_conn) -> None:
    doc = _raw_doc("wikipedia", "Nearest Order Test")
    upsert_document(db_conn, doc)
    chunk_a = _chunk(doc, 0, text="alpha")
    chunk_b = _chunk(doc, 1, text="beta")
    vec_a = _unit_vector(0, 1.0)
    vec_b = _unit_vector(1, 1.0)
    upsert_chunks(db_conn, [chunk_a, chunk_b], [vec_a, vec_b], _MODEL)

    hits = nearest(db_conn, _unit_vector(0, 1.0), k=2)

    assert len(hits) == 2
    assert isinstance(hits[0], ChunkHit)
    assert hits[0].id == chunk_a.id
    assert hits[1].id == chunk_b.id
    assert hits[0].distance <= hits[1].distance


@pytest.mark.db
def test_nearest_public_only_hides_private(db_conn) -> None:
    open_doc = _raw_doc("wikipedia", "Nearest Open Test")
    private_doc = _raw_doc("wikipedia", "Nearest Private Test", usage="private")
    upsert_document(db_conn, open_doc)
    upsert_document(db_conn, private_doc)
    open_chunk = _chunk(open_doc, 0, text="open chunk")
    private_chunk = _chunk(private_doc, 0, text="private chunk")
    query = _unit_vector(2, 1.0)
    upsert_chunks(
        db_conn,
        [open_chunk, private_chunk],
        [_unit_vector(2, 1.0), _unit_vector(2, 1.0)],
        _MODEL,
    )

    public_hits = nearest(db_conn, query, k=10, public_only=True)
    all_hits = nearest(db_conn, query, k=10, public_only=False)

    assert {h.id for h in public_hits} == {open_chunk.id}
    assert private_chunk.id in {h.id for h in all_hits}


@pytest.mark.db
def test_upsert_document_and_chunks_are_idempotent(db_conn) -> None:
    doc = _raw_doc("wikipedia", "Idempotent Upsert Test")
    chunk = _chunk(doc, 0)
    embedding = _unit_vector(3)
    upsert_document(db_conn, doc)
    upsert_chunks(db_conn, [chunk], [embedding], _MODEL)
    upsert_document(db_conn, doc)
    upsert_chunks(db_conn, [chunk], [embedding], _MODEL)

    assert len(existing_hashes(db_conn, doc.id)) == 1
    count = db_conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE document_id = %s",
        (doc.id,),
    ).fetchone()[0]
    assert count == 1


@pytest.mark.db
def test_delete_chunks_except_prunes_stale_ids(db_conn) -> None:
    doc = _raw_doc("wikipedia", "Prune Stale Test")
    upsert_document(db_conn, doc)
    keep = _chunk(doc, 0, content_hash="keep")
    stale = _chunk(doc, 1, content_hash="stale")
    vec = _unit_vector(4)
    upsert_chunks(db_conn, [keep, stale], [vec, vec], _MODEL)

    delete_chunks_except(db_conn, doc.id, [keep.id])

    remaining = {
        row[0]
        for row in db_conn.execute(
            "SELECT id FROM chunks WHERE document_id = %s",
            (doc.id,),
        ).fetchall()
    }
    assert remaining == {keep.id}


@pytest.mark.db
def test_delete_chunks_except_empty_keep_removes_all_for_document_only(
    db_conn,
) -> None:
    doc_a = _raw_doc("wikipedia", "Prune Empty Doc A")
    doc_b = _raw_doc("wikipedia", "Prune Empty Doc B")
    upsert_document(db_conn, doc_a)
    upsert_document(db_conn, doc_b)
    chunk_a = _chunk(doc_a, 0)
    chunk_b = _chunk(doc_b, 0)
    vec = _unit_vector(5)
    upsert_chunks(db_conn, [chunk_a, chunk_b], [vec, vec], _MODEL)

    delete_chunks_except(db_conn, doc_a.id, [])

    count_a = db_conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE document_id = %s",
        (doc_a.id,),
    ).fetchone()[0]
    count_b = db_conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE document_id = %s",
        (doc_b.id,),
    ).fetchone()[0]
    assert count_a == 0
    assert count_b == 1
