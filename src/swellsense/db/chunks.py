"""Upsert, prune, and nearest-neighbour search for chunk embeddings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgvector import Vector
from pydantic import BaseModel

from swellsense.config import get_settings
from swellsense.ingest.models import RawDocument
from swellsense.ingest.registry import Usage
from swellsense.processing.models import Chunk

if TYPE_CHECKING:
    import psycopg


class ChunkHit(BaseModel):
    """One chunk row from a nearest-neighbour query, with citation fields and distance."""

    id: str
    document_id: str
    index: int
    section: str
    text: str
    title: str
    url: str
    license: str
    attribution: str
    usage: Usage
    distance: float


def upsert_document(conn: psycopg.Connection, doc: RawDocument) -> None:
    """Insert or update a document row from a raw page."""
    conn.execute(
        """
        INSERT INTO documents (
            id, source_id, title, url, license, attribution, usage
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            source_id = EXCLUDED.source_id,
            title = EXCLUDED.title,
            url = EXCLUDED.url,
            license = EXCLUDED.license,
            attribution = EXCLUDED.attribution,
            usage = EXCLUDED.usage
        """,
        (
            doc.id,
            doc.source_id,
            doc.title,
            doc.url,
            doc.license,
            doc.attribution,
            doc.usage,
        ),
    )


def existing_hashes(
    conn: psycopg.Connection, document_id: str
) -> dict[str, tuple[str, str]]:
    """Map chunk id to (content_hash, embedding_model) for one document."""
    rows = conn.execute(
        """
        SELECT id, content_hash, embedding_model
        FROM chunks
        WHERE document_id = %s
        """,
        (document_id,),
    ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def upsert_chunks(
    conn: psycopg.Connection,
    chunks: list[Chunk],
    embeddings: list[list[float]],
    model: str,
) -> None:
    """Insert or update chunk rows with embeddings; lengths must match settings."""
    if len(chunks) != len(embeddings):
        msg = f"chunks length {len(chunks)} != embeddings length {len(embeddings)}"
        raise ValueError(msg)
    expected_dim = get_settings().embedding_dimensions
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        if len(embedding) != expected_dim:
            msg = (
                f"embedding for chunk {chunk.id!r} has length {len(embedding)}, "
                f"expected {expected_dim}"
            )
            raise ValueError(msg)
        conn.execute(
            """
            INSERT INTO chunks (
                id, document_id, "index", section, text, word_count,
                content_hash, title, url, license, attribution, usage,
                embedding, embedding_model
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (id) DO UPDATE SET
                document_id = EXCLUDED.document_id,
                "index" = EXCLUDED.index,
                section = EXCLUDED.section,
                text = EXCLUDED.text,
                word_count = EXCLUDED.word_count,
                content_hash = EXCLUDED.content_hash,
                title = EXCLUDED.title,
                url = EXCLUDED.url,
                license = EXCLUDED.license,
                attribution = EXCLUDED.attribution,
                usage = EXCLUDED.usage,
                embedding = EXCLUDED.embedding,
                embedding_model = EXCLUDED.embedding_model
            """,
            (
                chunk.id,
                chunk.document_id,
                chunk.index,
                chunk.section,
                chunk.text,
                chunk.word_count,
                chunk.content_hash,
                chunk.title,
                chunk.url,
                chunk.license,
                chunk.attribution,
                chunk.usage,
                Vector(embedding),
                model,
            ),
        )


def delete_chunks_except(
    conn: psycopg.Connection, document_id: str, keep_ids: list[str]
) -> None:
    """Remove chunks for one document whose ids are not in keep_ids."""
    conn.execute(
        """
        DELETE FROM chunks
        WHERE document_id = %s
          AND NOT (id = ANY(%s))
        """,
        (document_id, keep_ids),
    )


def nearest(
    conn: psycopg.Connection,
    embedding: list[float],
    k: int,
    public_only: bool = True,
) -> list[ChunkHit]:
    """Return the k closest chunks by cosine distance (lower is closer)."""
    expected_dim = get_settings().embedding_dimensions
    if len(embedding) != expected_dim:
        msg = f"query embedding length {len(embedding)}, expected {expected_dim}"
        raise ValueError(msg)
    usage_filter = "AND usage <> 'private'" if public_only else ""
    rows = conn.execute(
        f"""
        SELECT
            id, document_id, "index", section, text,
            title, url, license, attribution, usage,
            embedding <=> %s AS distance
        FROM chunks
        WHERE TRUE {usage_filter}
        ORDER BY embedding <=> %s
        LIMIT %s
        """,
        (Vector(embedding), Vector(embedding), k),
    ).fetchall()
    return [
        ChunkHit(
            id=row[0],
            document_id=row[1],
            index=row[2],
            section=row[3],
            text=row[4],
            title=row[5],
            url=row[6],
            license=row[7],
            attribution=row[8],
            usage=row[9],
            distance=float(row[10]),
        )
        for row in rows
    ]
