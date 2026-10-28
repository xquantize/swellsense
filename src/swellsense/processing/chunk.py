"""Split cleaned sections into overlapping word-budget chunks with citation metadata."""

from __future__ import annotations

import re

from swellsense.ingest.models import RawDocument, count_words, hash_text
from swellsense.processing.clean import clean_sections
from swellsense.processing.models import Chunk

# Splits after ., !, or ? when followed by whitespace. Misses abbreviations (Dr. Smith)
# and some quoted or parenthetical boundaries; good enough for plain Wikipedia prose.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_paragraphs(section_text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", section_text.strip())
    return [block.strip() for block in blocks if block.strip()]


def _split_sentences(paragraph: str) -> list[str]:
    parts = _SENTENCE_SPLIT_RE.split(paragraph.strip())
    return [part for part in parts if part]


def _last_n_words(text: str, n: int) -> str:
    words = text.split()
    if n <= 0 or not words:
        return ""
    return " ".join(words[-n:])


def _sentences_for_section(section_text: str, max_words: int) -> list[str]:
    """Packing units for one section: lines first, then sentences only on long lines."""
    units: list[str] = []
    for paragraph in _split_paragraphs(section_text):
        lines = [line.strip() for line in paragraph.split("\n") if line.strip()]
        for line in lines:
            if count_words(line) <= max_words:
                units.append(line)
            else:
                units.extend(_split_sentences(line))
    return units


def _merge_short_tail(
    chunk_texts: list[str],
    prefix_lengths: list[int],
    overlap_words: int,
) -> list[str]:
    if len(chunk_texts) < 2:
        return chunk_texts
    last = chunk_texts[-1]
    prev = chunk_texts[-2]
    tail_prefix = prefix_lengths[-1]
    last_word_list = last.split()
    new_word_count = len(last_word_list) - tail_prefix
    suffix = " ".join(last_word_list[tail_prefix:]) if tail_prefix else last
    if new_word_count >= overlap_words:
        return chunk_texts
    if suffix:
        chunk_texts[-2] = f"{prev} {suffix}".strip()
    prefix_lengths.pop()
    chunk_texts.pop()
    return chunk_texts


def _chunk_section(
    section_text: str,
    max_words: int,
    overlap_words: int,
) -> list[str]:
    """Return chunk texts for one section; may exceed max_words only per documented rules."""
    if count_words(section_text) <= max_words:
        return [section_text]

    sentences = _sentences_for_section(section_text, max_words)
    if not sentences:
        return []

    chunk_texts: list[str] = []
    prefix_lengths: list[int] = []
    index = 0
    while index < len(sentences):
        if not chunk_texts:
            prefix = ""
            prefix_words = 0
        else:
            prefix = _last_n_words(chunk_texts[-1], overlap_words)
            prefix_words = count_words(prefix)

        packed: list[str] = []
        packed_words = prefix_words
        start = index
        while index < len(sentences):
            sentence = sentences[index]
            sentence_words = count_words(sentence)
            if sentence_words > max_words:
                if packed_words == prefix_words and not packed:
                    chunk_texts.append(sentence)
                    prefix_lengths.append(0)
                    index += 1
                break
            if packed_words + sentence_words > max_words:
                break
            packed.append(sentence)
            packed_words += sentence_words
            index += 1

        if packed:
            body = " ".join(packed)
            chunk_texts.append(f"{prefix} {body}".strip() if prefix else body)
            prefix_lengths.append(prefix_words)
        elif start == index and index < len(sentences):
            sentence = sentences[index]
            sentence_words = count_words(sentence)
            if sentence_words > max_words:
                chunk_texts.append(sentence)
                prefix_lengths.append(0)
                index += 1
            elif prefix:
                allowed_prefix = max(0, max_words - sentence_words)
                if prefix_words > allowed_prefix:
                    prefix = _last_n_words(chunk_texts[-1], allowed_prefix)
                    prefix_words = allowed_prefix
                chunk_texts.append(
                    f"{prefix} {sentence}".strip() if prefix else sentence
                )
                prefix_lengths.append(prefix_words)
                index += 1
            else:
                break

    return _merge_short_tail(chunk_texts, prefix_lengths, overlap_words)


def chunk_document(
    doc: RawDocument,
    max_words: int,
    overlap_words: int,
) -> list[Chunk]:
    """Split a raw document into chunks that carry citation metadata for retrieval.

    Chunks never cross section boundaries. After the first chunk in a section, each
    chunk normally starts with the last ``overlap_words`` words of the previous chunk
    (word-based, so the boundary may fall mid-sentence). If that full overlap plus the
    next sentence would exceed ``max_words``, the prefix is shortened so the chunk stays
    within ``max_words`` (possibly to zero overlap words). A chunk may exceed
    ``max_words`` only when a single sentence is longer than ``max_words``, or when a
    short trailing chunk is merged into the previous one (by less than ``overlap_words``
    words).
    """
    if overlap_words < 0 or overlap_words >= max_words:
        raise ValueError("overlap_words must satisfy 0 <= overlap_words < max_words")

    sections = clean_sections(doc.text)
    if not sections:
        return []

    chunks: list[Chunk] = []
    index = 0
    for section in sections:
        for text in _chunk_section(section.text, max_words, overlap_words):
            chunks.append(
                Chunk(
                    id=f"{doc.id}#{index}",
                    document_id=doc.id,
                    index=index,
                    section=section.heading,
                    text=text,
                    word_count=count_words(text),
                    content_hash=hash_text(text),
                    title=doc.title,
                    url=doc.url,
                    license=doc.license,
                    attribution=doc.attribution,
                    usage=doc.usage,
                )
            )
            index += 1

    return chunks
