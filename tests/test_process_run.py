import hashlib
import struct
from datetime import UTC, datetime

import pytest

from swellsense.config import Settings
from swellsense.ingest.models import RawDocument
from swellsense.ingest.store import slugify
from swellsense.processing.run import process

_DIM = 768
_MODEL = "test-embed"


def _document(**overrides) -> RawDocument:
    text = overrides.pop("text", "Lead only.")
    title = overrides.pop("title", "Process test")
    source_id = overrides.pop("source_id", "wikipedia")
    values = {
        "id": f"{source_id}/{slugify(title)}",
        "source_id": source_id,
        "title": title,
        "url": "https://example.com/wiki/process_test",
        "license": "CC BY-SA 4.0",
        "attribution": "Test contributors",
        "usage": "open",
        "fetched_at": datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "word_count": len(text.split()),
        "text": text,
    }
    values.update(overrides)
    return RawDocument(**values)


def _words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def _vector_for(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    out: list[float] = []
    while len(out) < _DIM:
        for i in range(0, len(digest) - 3, 4):
            value = struct.unpack(">I", digest[i : i + 4])[0]
            out.append((value % 10_000) / 10_000.0)
            if len(out) == _DIM:
                break
        digest = hashlib.sha256(digest).digest()
    return out


class InMemoryChunkStore:
    """Minimal ChunkStore for unit tests."""

    def __init__(self) -> None:
        self.chunks: dict[str, tuple[str, str]] = {}

    def upsert_document(self, doc: RawDocument) -> None:
        del doc

    def existing_hashes(self, document_id: str) -> dict[str, tuple[str, str]]:
        prefix = f"{document_id}#"
        return {
            chunk_id: pair
            for chunk_id, pair in self.chunks.items()
            if chunk_id.startswith(prefix)
        }

    def upsert_chunks(self, chunks, embeddings: list[list[float]], model: str) -> None:
        if len(chunks) != len(embeddings):
            msg = "chunks and embeddings length mismatch"
            raise ValueError(msg)
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            if len(embedding) != _DIM:
                msg = f"bad embedding length for {chunk.id}"
                raise ValueError(msg)
            self.chunks[chunk.id] = (chunk.content_hash, model)

    def delete_chunks_except(self, document_id: str, keep_ids: list[str]) -> None:
        keep = set(keep_ids)
        prefix = f"{document_id}#"
        for chunk_id in list(self.chunks):
            if chunk_id.startswith(prefix) and chunk_id not in keep:
                del self.chunks[chunk_id]


@pytest.fixture
def chunk_settings(monkeypatch):
    settings = Settings(
        chunk_words=12,
        chunk_overlap_words=2,
        embedding_model=_MODEL,
        embedding_dimensions=_DIM,
    )
    monkeypatch.setattr("swellsense.processing.run.get_settings", lambda: settings)
    return settings


def _multi_chunk_doc() -> RawDocument:
    body = _words(24)
    text = f"Short lead.\n\n== Surf ==\n{body}"
    return _document(title="multi", text=text)


def _make_embed_fn(calls: list[list[str]], fail_if: str | None = None):
    def embed_fn(texts: list[str]) -> list[list[float]]:
        if fail_if is not None and any(fail_if in text for text in texts):
            raise RuntimeError("embed failed")
        calls.append(list(texts))
        return [_vector_for(text) for text in texts]

    return embed_fn


def test_empty_docs_returns_zeros(chunk_settings):
    store = InMemoryChunkStore()
    calls: list[list[str]] = []
    report = process([], _make_embed_fn(calls), store)
    assert report.documents == 0
    assert report.embedded == 0
    assert report.unchanged == 0
    assert report.removed == 0
    assert report.failed == []
    assert calls == []


def test_first_run_embeds_every_chunk(chunk_settings):
    doc = _multi_chunk_doc()
    store = InMemoryChunkStore()
    calls: list[list[str]] = []
    report = process([doc], _make_embed_fn(calls), store)
    assert report.failed == []
    assert report.documents == 1
    assert report.embedded > 0
    assert report.unchanged == 0
    assert report.removed == 0
    assert len(calls) == 1
    assert len(calls[0]) == report.embedded


def test_second_run_skips_embed(chunk_settings):
    doc = _multi_chunk_doc()
    store = InMemoryChunkStore()
    calls: list[list[str]] = []
    embed_fn = _make_embed_fn(calls)
    first = process([doc], embed_fn, store)
    assert first.embedded > 0
    calls.clear()
    second = process([doc], embed_fn, store)
    assert second.failed == []
    assert second.embedded == 0
    assert second.unchanged == first.embedded
    assert second.removed == 0
    assert calls == []


def test_changed_doc_reembeds_and_prunes(chunk_settings):
    doc = _multi_chunk_doc()
    store = InMemoryChunkStore()
    calls: list[list[str]] = []
    embed_fn = _make_embed_fn(calls)
    process([doc], embed_fn, store)
    old_ids = set(store.existing_hashes(doc.id))

    new_text = _words(4)
    changed = _document(
        title="multi",
        text=new_text,
        content_hash=hashlib.sha256(new_text.encode()).hexdigest(),
    )
    calls.clear()
    second = process([changed], embed_fn, store)
    new_ids = set(store.existing_hashes(doc.id))
    pruned = old_ids - new_ids

    assert second.failed == []
    assert pruned
    assert second.removed == len(pruned)
    assert second.embedded == len(new_ids)
    assert calls and len(calls[0]) == second.embedded


def test_model_change_reembeds_all_chunks(chunk_settings, monkeypatch):
    doc = _multi_chunk_doc()
    store = InMemoryChunkStore()
    calls: list[list[str]] = []
    first = process([doc], _make_embed_fn(calls), store)
    assert first.embedded > 0

    settings = Settings(
        chunk_words=12,
        chunk_overlap_words=2,
        embedding_model="other-model",
        embedding_dimensions=_DIM,
    )
    monkeypatch.setattr("swellsense.processing.run.get_settings", lambda: settings)
    calls.clear()
    second = process([doc], _make_embed_fn(calls), store)
    assert second.failed == []
    assert second.embedded == first.embedded
    assert second.unchanged == 0
    assert len(calls) == 1
    assert len(calls[0]) == second.embedded


def test_one_failing_document_continues(chunk_settings):
    good = _document(title="good", text="== Surf ==\n" + _words(10))
    bad = _document(title="bad", text="== Surf ==\n" + _words(10) + " FAILMARKER")
    after = _document(title="after", text="== Surf ==\n" + _words(10))
    store = InMemoryChunkStore()
    calls: list[list[str]] = []
    embed_fn = _make_embed_fn(calls, fail_if="FAILMARKER")
    report = process([good, bad, after], embed_fn, store)

    assert len(report.failed) == 1
    assert report.failed[0]["id"] == bad.id
    assert "embed failed" in report.failed[0]["error"]
    assert store.existing_hashes(good.id)
    assert store.existing_hashes(after.id)
    assert not store.existing_hashes(bad.id)


def test_store_value_error_is_recorded(chunk_settings):
    doc = _multi_chunk_doc()

    class BadStore(InMemoryChunkStore):
        def upsert_chunks(self, chunks, embeddings, model):
            raise ValueError("store rejected")

    store = BadStore()
    report = process([doc], _make_embed_fn([]), store)
    assert report.failed == [{"id": doc.id, "error": "store rejected"}]
