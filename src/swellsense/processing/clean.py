"""Split MediaWiki plain text into content sections for chunking."""

from __future__ import annotations

import re

from pydantic import BaseModel

# MediaWiki marks section levels with matching = runs on both sides.
_HEADING_RE = re.compile(r"^\s*(=+)\s*(.*?)\s*\1\s*$")

# Boilerplate sections are dropped so chunks stay on surf-relevant prose.
_DROPPED_HEADINGS = frozenset(
    {
        "references",
        "see also",
        "external links",
        "further reading",
        "notes",
        "bibliography",
    }
)


class Section(BaseModel):
    """One heading and its body after whitespace normalisation."""

    heading: str
    text: str


def _normalize_section_text(text: str) -> str:
    """Strip line endings, collapse extra blank lines, trim the block."""
    lines = [line.rstrip() for line in text.splitlines()]
    collapsed: list[str] = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run == 1:
                collapsed.append("")
        else:
            blank_run = 0
            collapsed.append(line)
    return "\n".join(collapsed).strip()


def _drop_heading(heading: str) -> bool:
    return heading.strip().casefold() in _DROPPED_HEADINGS


def clean_sections(text: str) -> list[Section]:
    """Split plain MediaWiki text into sections, dropping boilerplate blocks."""
    if text == "":
        return []

    sections: list[Section] = []
    current_heading = ""
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal body_lines
        body = _normalize_section_text("\n".join(body_lines))
        if not _drop_heading(current_heading) and body:
            sections.append(Section(heading=current_heading, text=body))
        body_lines = []

    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            current_heading = match.group(2).strip()
        else:
            body_lines.append(line)

    flush()
    return sections
