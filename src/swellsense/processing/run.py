"""Clean, chunk, embed and store raw documents.

One bad document is recorded and the rest still process, mirroring ingest runs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import openai
import psycopg
from pydantic import BaseModel, Field

from swellsense.config import get_settings
from swellsense.ingest.models import RawDocument
from swellsense.processing.chunk import chunk_document
from swellsense.processing.models import Chunk


class ChunkStore(Protocol):
    """Persistence for documents and chunk rows; no commit (caller's job)."""

    def upsert_document(self, doc: RawDocument) -> None: ...

    def existing_hashes(self, document_id: str) -> dict[str, tuple[str, str]]: ...

    def upsert_chunks(
        self, chunks: list[Chunk], embeddings: list[list[float]], model: str
    ) -> None: ...

    def delete_chunks_except(self, document_id: str, keep_ids: list[str]) -> None: ...


class ProcessReport(BaseModel):
    """Counts from one process run over a set of raw documents."""

    documents: int
    embedded: int = 0
    unchanged: int = 0
    removed: int = 0
    failed: list[dict[str, str]] = Field(default_factory=list)


class PostgresChunkStore:
    """Forwards chunk store operations to ``swellsense.db.chunks``."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert_document(self, doc: RawDocument) -> None:
        from swellsense.db.chunks import upsert_document

        upsert_document(self._conn, doc)

    def existing_hashes(self, document_id: str) -> dict[str, tuple[str, str]]:
        from swellsense.db.chunks import existing_hashes

        return existing_hashes(self._conn, document_id)

    def upsert_chunks(
        self, chunks: list[Chunk], embeddings: list[list[float]], model: str
    ) -> None:
        from swellsense.db.chunks import upsert_chunks

        upsert_chunks(self._conn, chunks, embeddings, model)

    def delete_chunks_except(self, document_id: str, keep_ids: list[str]) -> None:
        from swellsense.db.chunks import delete_chunks_except

        delete_chunks_except(self._conn, document_id, keep_ids)


def process(
    docs: list[RawDocument],
    embed_fn: Callable[[list[str]], list[list[float]]],
    store: ChunkStore,
) -> ProcessReport:
    """Chunk each document, embed only new or changed chunks, upsert and prune."""
    settings = get_settings()
    report = ProcessReport(documents=len(docs))

    for doc in docs:
        try:
            embedded, unchanged, removed = _process_document(
                doc,
                embed_fn,
                store,
                settings.chunk_words,
                settings.chunk_overlap_words,
                settings.embedding_model,
            )
        except (openai.APIError, psycopg.Error):
            raise
        except Exception as exc:  # noqa: BLE001
            report.failed.append({"id": doc.id, "error": str(exc)})
            continue
        report.embedded += embedded
        report.unchanged += unchanged
        report.removed += removed

    return report


def _process_document(
    doc: RawDocument,
    embed_fn: Callable[[list[str]], list[list[float]]],
    store: ChunkStore,
    chunk_words: int,
    chunk_overlap_words: int,
    embedding_model: str,
) -> tuple[int, int, int]:
    chunks = chunk_document(doc, chunk_words, chunk_overlap_words)
    store.upsert_document(doc)
    existing = store.existing_hashes(doc.id)
    keep_ids = {chunk.id for chunk in chunks}

    to_embed: list[Chunk] = []
    for chunk in chunks:
        prior = existing.get(chunk.id)
        if prior == (chunk.content_hash, embedding_model):
            continue
        to_embed.append(chunk)

    unchanged = len(chunks) - len(to_embed)
    embedded = 0
    if to_embed:
        texts = [chunk.text for chunk in to_embed]
        embeddings = embed_fn(texts)
        store.upsert_chunks(to_embed, embeddings, embedding_model)
        embedded = len(to_embed)

    removed = sum(1 for chunk_id in existing if chunk_id not in keep_ids)
    store.delete_chunks_except(doc.id, [chunk.id for chunk in chunks])
    return embedded, unchanged, removed
