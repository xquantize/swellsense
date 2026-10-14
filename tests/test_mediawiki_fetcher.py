from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from swellsense.config import Settings, get_settings
from swellsense.ingest.fetchers.mediawiki import fetch_article, make_client
from swellsense.ingest.models import count_words, hash_text
from swellsense.ingest.registry import Source
from swellsense.ingest.store import slugify

_API = "https://en.wikipedia.org/w/api.php"
_TEXT = "Surfing is a surface water sport."
_URL = "https://en.wikipedia.org/wiki/Surfing"


def _source() -> Source:
    return Source(
        id="wikipedia",
        type="mediawiki",
        api_url=_API,
        license="CC BY-SA 4.0",
        attribution="Wikipedia contributors",
        usage="open",
        titles=["Surfing"],
    )


def _page(title: str, text: str, url: str, **flags: str) -> dict:
    page = {"title": title, "extract": text, "fullurl": url, **flags}
    return {"query": {"pages": {"123": page}}}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_page_becomes_a_raw_document():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_page("Swell (ocean)", _TEXT, _URL))

    before = datetime.now(UTC)
    with _client(handler) as client:
        doc = fetch_article(client, _source(), "Swell (ocean)")
    after = datetime.now(UTC)

    assert doc is not None
    assert doc.id == f"wikipedia/{slugify('Swell (ocean)')}"
    assert doc.source_id == "wikipedia"
    assert doc.title == "Swell (ocean)"
    assert doc.url == _URL
    assert doc.license == "CC BY-SA 4.0"
    assert doc.attribution == "Wikipedia contributors"
    assert doc.usage == "open"
    assert doc.text == _TEXT
    assert doc.content_hash == hash_text(_TEXT)
    assert doc.word_count == count_words(_TEXT)
    assert before <= doc.fetched_at <= after
    assert doc.fetched_at.utcoffset() == timedelta(0)


def test_redirect_uses_the_resolved_title():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_page("Surfing", _TEXT, _URL))

    with _client(handler) as client:
        doc = fetch_article(client, _source(), "Surf")

    assert doc is not None
    assert doc.title == "Surfing"
    assert doc.url == _URL
    assert doc.id == "wikipedia/surfing"
    assert doc.text == _TEXT


@pytest.mark.parametrize(
    "payload",
    [
        {"query": {"pages": {"-1": {"title": "Not a page", "missing": ""}}}},
        {"query": {"pages": {"-1": {"title": "Bad::title", "invalid": ""}}}},
    ],
)
def test_missing_or_invalid_page_returns_none(payload):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with _client(handler) as client:
        assert fetch_article(client, _source(), "Not a page") is None


def test_http_error_is_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with _client(handler) as client, pytest.raises(httpx.HTTPStatusError):
        fetch_article(client, _source(), "Surfing")


def test_request_sends_user_agent_and_expected_params(monkeypatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_page("Surfing", _TEXT, _URL))

    real_client = httpx.Client

    def client_with_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    # make_client builds the client; the mock transport keeps the test offline.
    monkeypatch.setattr(
        "swellsense.ingest.fetchers.mediawiki.httpx.Client",
        client_with_transport,
    )

    with make_client() as client:
        fetch_article(client, _source(), "Surfing")

    assert len(captured) == 1
    request = captured[0]
    assert request.method == "GET"
    assert str(request.url.copy_with(query=None)) == _API
    assert request.headers["user-agent"] == get_settings().http_user_agent
    assert dict(request.url.params) == {
        "action": "query",
        "prop": "extracts|info",
        "explaintext": "1",
        "inprop": "url",
        "redirects": "1",
        "format": "json",
        "titles": "Surfing",
    }


def test_http_settings_defaults(monkeypatch):
    monkeypatch.delenv("HTTP_USER_AGENT", raising=False)
    monkeypatch.delenv("HTTP_TIMEOUT_S", raising=False)

    settings = Settings(_env_file=None)

    assert settings.http_user_agent == (
        "SwellSense/0.1 (learning project; contact: set HTTP_USER_AGENT)"
    )
    assert settings.http_timeout_s == 30


def test_make_client_uses_settings_user_agent_and_timeout(monkeypatch):
    monkeypatch.setenv(
        "HTTP_USER_AGENT", "SwellSense/0.1 (test; contact: test@example.com)"
    )
    monkeypatch.setenv("HTTP_TIMEOUT_S", "12")
    get_settings.cache_clear()
    try:
        with make_client() as client:
            assert client.headers["user-agent"] == (
                "SwellSense/0.1 (test; contact: test@example.com)"
            )
            assert client.timeout == httpx.Timeout(12.0)
    finally:
        get_settings.cache_clear()
