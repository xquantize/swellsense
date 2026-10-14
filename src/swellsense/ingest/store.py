import re
from pathlib import Path

from pydantic import ValidationError

from swellsense.ingest.models import RawDocument

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    """Turn a title into a filename stem.

    Letters and digits stay. A run of anything else becomes one underscore,
    and underscores at the ends are removed. ``Swell (ocean)`` is ``swell_ocean``.
    """
    return _NON_ALNUM.sub("_", title.lower()).strip("_")


def _stored_hash(path: Path) -> str | None:
    """Return the hash already on disk, or None when the file is not a document."""
    try:
        existing = RawDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, UnicodeError):
        return None
    return existing.content_hash


def save(doc: RawDocument, root: Path = Path("data/raw")) -> bool:
    """Write the page to ``root/<source_id>/<slug>.json``.

    Return False when that file is already there with the same content hash,
    so an unchanged download is left untouched. Any other case is written
    and returns True.
    """
    slug = slugify(doc.title)
    if slug == "":
        raise ValueError("title must contain a letter or number")
    path = root / doc.source_id / f"{slug}.json"
    if path.is_file() and _stored_hash(path) == doc.content_hash:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return True


def load_all(root: Path = Path("data/raw")) -> list[RawDocument]:
    """Read every saved page. A missing directory is an empty store."""
    if not root.is_dir():
        return []
    return [
        RawDocument.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("*/*.json"))
    ]
