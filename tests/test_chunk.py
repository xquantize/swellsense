import hashlib
import itertools
from datetime import UTC, datetime

import pytest

from swellsense.ingest.models import RawDocument, count_words, hash_text
from swellsense.ingest.store import slugify
from swellsense.processing.chunk import (
    _chunk_section,
    _sentences_for_section,
    chunk_document,
)


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


def test_chunk_section_carries_full_heading_path():
    text = "== Parent ==\nLead.\n=== Child ===\nNested body here."
    chunks = chunk_document(_document(text=text), max_words=50, overlap_words=3)
    nested = [c for c in chunks if c.text == "Nested body here."]
    assert len(nested) == 1
    assert nested[0].section == "Parent > Child"


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
    cases = [
        [6, 6, 6, 6],
        # Sentence lengths in (max - overlap, max]: prefix shrink must cap chunks.
        [10, 10],
        [12, 12],
        [14, 14],
        [15],
    ]
    for word_counts in cases:
        text = f"== Body ==\n{_sentences(word_counts)}"
        chunks = chunk_document(
            _document(text=text), max_words=max_words, overlap_words=overlap
        )
        for chunk in chunks:
            if chunk.word_count > max_words:
                # Over-long single sentence or merged tail exception.
                assert chunk.word_count < max_words + overlap


def test_two_max_sized_sentences_stay_within_cap():
    max_words = 10
    overlap = 3
    text = f"== Cap ==\n{_sentences([10, 10])}"
    chunks = chunk_document(
        _document(text=text), max_words=max_words, overlap_words=overlap
    )
    assert [c.word_count for c in chunks] == [10, 10]


def test_prefix_shrinks_when_overlap_plus_sentence_exceeds_max():
    max_words = 10
    overlap = 3
    section = _sentences([10, 10])
    chunks = _chunk_section(section, max_words=max_words, overlap_words=overlap)
    assert len(chunks) == 2
    assert all(len(c.split()) <= max_words for c in chunks)
    second = chunks[1].split()
    first = chunks[0].split()
    # Second chunk: 10-word sentence; only 0 prefix words fit (10 + 10 > max).
    assert second[-10:] == first[-10:]
    assert second[:3] != first[-3:]


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
    # Splits then merges: [10, 9] in first chunk, tail has < overlap new words.
    text = f"== Tail ==\n{_sentences([10, 9, 3])}"
    chunks = chunk_document(
        _document(text=text), max_words=max_words, overlap_words=overlap
    )
    section_chunks = [c for c in chunks if c.section == "Tail"]
    assert len(section_chunks) == 1
    merged = section_chunks[0]
    assert max_words < merged.word_count < max_words + overlap


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


def test_glossary_lines_are_separate_packing_units():
    max_words = 30
    close_out = "Close-out: A wave that breaks all at once"
    drop_in = "Drop-in: The surfer with priority catches the wave"
    section = f"{close_out}\n{drop_in}"
    assert _sentences_for_section(section, max_words=max_words) == [
        close_out,
        drop_in,
    ]


def test_glossary_line_keeps_multiple_sentences_on_one_line():
    max_words = 30
    entry = "Close-out: A wave that breaks all at once. This leaves no shoulder."
    assert _sentences_for_section(entry, max_words=max_words) == [entry]


def test_glossary_lines_space_joined_when_packed_in_one_chunk():
    lines = [
        "Close-out: A wave that breaks all at once",
        "Drop-in: The surfer with priority catches the wave",
        "Frothing: Very excited about surfing",
        "Grom: A young beginner surfer",
    ]
    section = "\n".join(lines)
    max_words = 25
    assert count_words(section) > max_words
    chunks = _chunk_section(section, max_words=max_words, overlap_words=2)
    packed = f"{lines[0]} {lines[1]} {lines[2]}"
    assert any(packed in chunk for chunk in chunks)
    assert not any(f"{lines[0]}\n{lines[1]}" in chunk for chunk in chunks)
