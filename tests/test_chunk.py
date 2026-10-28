import hashlib
import itertools
from datetime import UTC, datetime

import pytest

from swellsense.ingest.models import RawDocument, hash_text
from swellsense.ingest.store import slugify
from swellsense.processing.chunk import chunk_document


def _document(**overrides) -> RawDocument:
    text = overrides.pop("text", "Lead only.")
    title = overrides.pop("title", "Chunk test")
    source_id = overrides.pop("source_id", "wikipedia")
    values = {
        "id": f"{source_id}/{slugify(title)}",
        "source_id": source_id,
        "title": title,
        "url": "https://example.com/wiki/chunk_test",
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


def _sentences(word_counts: list[int]) -> str:
    parts = []
    for count in word_counts:
        parts.append(f"{_words(count)}.")
    return " ".join(parts)


def test_no_sections_returns_empty_list():
    text = "== References ==\nA citation."
    assert chunk_document(_document(text=text), max_words=10, overlap_words=2) == []


def test_short_section_is_one_chunk():
    text = "One small section without headings."
    doc = _document(text=text)
    chunks = chunk_document(doc, max_words=20, overlap_words=3)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].section == ""
    assert chunks[0].index == 0
    assert chunks[0].id == f"{doc.id}#0"


def test_section_at_max_words_is_one_chunk():
    body = _words(10)
    text = f"== Surf ==\n{body}"
    chunks = chunk_document(_document(text=text), max_words=10, overlap_words=2)
    assert len(chunks) == 1
    assert chunks[0].section == "Surf"
    assert chunks[0].text == body


def test_no_chunk_exceeds_max_words_except_documented_cases():
    max_words = 15
    overlap = 3
    # Three sentences of 6 words each -> multiple chunks with overlap.
    text = f"== Body ==\n{_sentences([6, 6, 6, 6])}"
    chunks = chunk_document(
        _document(text=text), max_words=max_words, overlap_words=overlap
    )
    for chunk in chunks:
        if chunk.word_count > max_words:
            # Over-long single sentence or merged tail exception.
            assert chunk.word_count < max_words + overlap


def test_overlap_between_neighbours_in_section():
    max_words = 12
    overlap = 4
    text = f"== A ==\n{_sentences([5, 5, 5])}"
    chunks = chunk_document(
        _document(text=text), max_words=max_words, overlap_words=overlap
    )
    section_chunks = [c for c in chunks if c.section == "A"]
    assert len(section_chunks) >= 2
    for prev, nxt in itertools.pairwise(section_chunks):
        prev_tail = prev.text.split()[-overlap:]
        nxt_head = nxt.text.split()[:overlap]
        assert prev_tail == nxt_head


def test_chunks_do_not_cross_sections():
    text = (
        "Lead text here.\n\n"
        "== One ==\n"
        f"{_sentences([8, 8])}\n"
        "== Two ==\n"
        f"{_sentences([8, 8])}"
    )
    chunks = chunk_document(_document(text=text), max_words=10, overlap_words=2)
    headings = [c.section for c in chunks]
    assert "" in headings
    assert "One" in headings
    assert "Two" in headings
    for chunk in chunks:
        if chunk.section == "One":
            assert "Two" not in chunk.text
        if chunk.section == "Two":
            assert "One" not in chunk.text.split()[0]


def test_short_tail_is_merged():
    max_words = 20
    overlap = 5
    # Sized so the final chunk would have fewer than overlap new words.
    text = f"== Tail ==\n{_sentences([8, 8, 3])}"
    chunks = chunk_document(
        _document(text=text), max_words=max_words, overlap_words=overlap
    )
    section_chunks = [c for c in chunks if c.section == "Tail"]
    assert len(section_chunks) >= 1
    last = section_chunks[-1]
    last_words = last.text.split()
    if len(section_chunks) >= 2:
        prev = section_chunks[-2]
        assert last_words[:overlap] == prev.text.split()[-overlap:]


def test_overlong_single_sentence_is_kept_whole():
    max_words = 5
    overlap = 2
    long_sentence = f"{_words(12)}."
    text = f"== Long ==\nIntro short. {long_sentence} After that."
    chunks = chunk_document(
        _document(text=text), max_words=max_words, overlap_words=overlap
    )
    long_chunks = [c for c in chunks if long_sentence.rstrip(".") in c.text]
    assert any(c.word_count > max_words for c in long_chunks)


def test_ids_run_zero_through_n_minus_one():
    text = f"Lead.\n== A ==\n{_sentences([6, 6, 6])}\n== B ==\nShort."
    doc = _document(text=text)
    chunks = chunk_document(doc, max_words=8, overlap_words=2)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert [c.id for c in chunks] == [f"{doc.id}#{i}" for i in range(len(chunks))]


def test_metadata_matches_source_document():
    doc = _document(text="== Only ==\nSome body text here.")
    chunk = chunk_document(doc, max_words=50, overlap_words=5)[0]
    assert chunk.document_id == doc.id
    assert chunk.title == doc.title
    assert chunk.url == doc.url
    assert chunk.license == doc.license
    assert chunk.attribution == doc.attribution
    assert chunk.usage == doc.usage
    assert chunk.content_hash == hash_text(chunk.text)


def test_two_calls_are_identical():
    doc = _document(text=f"== Repeat ==\n{_sentences([7, 7, 7])}")
    first = chunk_document(doc, max_words=10, overlap_words=3)
    second = chunk_document(doc, max_words=10, overlap_words=3)
    assert first == second


@pytest.mark.parametrize("overlap_words", [10, -1])
def test_invalid_overlap_raises(overlap_words: int):
    with pytest.raises(ValueError, match="overlap_words"):
        chunk_document(_document(), max_words=10, overlap_words=overlap_words)


def test_overlap_equal_to_max_words_raises():
    with pytest.raises(ValueError, match="overlap_words"):
        chunk_document(_document(), max_words=10, overlap_words=10)
