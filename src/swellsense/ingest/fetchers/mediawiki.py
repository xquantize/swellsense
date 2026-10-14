"""Download one MediaWiki article into a raw document.

File saving and the ingest command come later. This module only fetches.
"""

from datetime import UTC, datetime

import httpx

from swellsense.config import get_settings
from swellsense.ingest.models import RawDocument, count_words, hash_text
from swellsense.ingest.registry import Source
from swellsense.ingest.store import slugify

# Plain text plus the canonical URL. redirects=1 stores the page a title lands on.
_QUERY = {
    "action": "query",
    "prop": "extracts|info",
    "explaintext": "1",
    "inprop": "url",
    "redirects": "1",
    "format": "json",
}


def make_client() -> httpx.Client:
    """Client that names this project and stops waiting after the timeout.

    MediaWiki asks every client to send a User-Agent with a contact, so
    downloads share the one configured in settings.
    """
    settings = get_settings()
    return httpx.Client(
        headers={"User-Agent": settings.http_user_agent},
        timeout=settings.http_timeout_s,
    )


def fetch_article(
    client: httpx.Client, source: Source, title: str
) -> RawDocument | None:
    """Download one article, or return None when that page does not exist.

    The stored title and URL are the ones MediaWiki resolved, so a redirect
    is kept under the page it lands on. HTTP errors are raised; the caller
    decides whether to retry or skip.
    """
    response = client.get(source.api_url, params={**_QUERY, "titles": title})
    response.raise_for_status()

    article = _article(response.json())
    if article is None:
        return None

    resolved_title, url, text = article
    return RawDocument(
        id=f"{source.id}/{slugify(resolved_title)}",
        source_id=source.id,
        title=resolved_title,
        url=url,
        license=source.license,
        attribution=source.attribution,
        usage=source.usage,
        fetched_at=datetime.now(UTC),
        content_hash=hash_text(text),
        word_count=count_words(text),
        text=text,
    )


def _article(payload: object) -> tuple[str, str, str] | None:
    """Return the resolved title, full URL and plain text, or None.

    A missing or invalid title is still HTTP 200. MediaWiki marks it on the
    page object, and the page id is the key under ``query.pages``.
    """
    if not isinstance(payload, dict):
        return None
    query = payload.get("query")
    if not isinstance(query, dict):
        return None
    pages = query.get("pages")
    if not isinstance(pages, dict) or len(pages) != 1:
        return None

    page = next(iter(pages.values()))
    if not isinstance(page, dict) or "missing" in page or "invalid" in page:
        return None

    resolved_title = page.get("title")
    url = page.get("fullurl")
    text = page.get("extract")
    if (
        not isinstance(resolved_title, str)
        or not isinstance(url, str)
        or not isinstance(text, str)
        or slugify(resolved_title) == ""
    ):
        return None
    return resolved_title, url, text
