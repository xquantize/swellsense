from collections.abc import Callable

import httpx

from swellsense.config import get_settings
from swellsense.ingest.models import RawDocument
from swellsense.ingest.registry import Source
from swellsense.ingest.run import RunReport, ingest
from swellsense.ingest.store import load_all

_API = "https://en.wikipedia.org/w/api.php"


def _source(*titles: str, source_id: str = "wikipedia") -> Source:
    return Source(
        id=source_id,
        type="mediawiki",
        api_url=_API,
        license="CC BY-SA 4.0",
        attribution="Wikipedia contributors",
        usage="open",
        titles=list(titles),
    )


def _web_source() -> Source:
    return Source(
        id="blog",
        type="web",
        license="CC BY 4.0",
        attribution="Example",
        usage="open",
        urls=["https://example.com/surf"],
    )


def _page(title: str, text: str, url: str) -> dict:
    return {
        "query": {"pages": {"1": {"title": title, "extract": text, "fullurl": url}}}
    }


def _handler(request: httpx.Request) -> httpx.Response:
    title = request.url.params["titles"]
    if title == "Broken":
        return httpx.Response(500)
    if title == "Missing":
        return httpx.Response(
            200,
            json={"query": {"pages": {"-1": {"title": title, "missing": ""}}}},
        )
    slug = title.replace(" ", "_")
    return httpx.Response(
        200,
        json=_page(
            title, f"{title} is a page.", f"https://en.wikipedia.org/wiki/{slug}"
        ),
    )


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_counts_saved_unchanged_missing_and_failed(tmp_path):
    with _client(_handler) as client:
        ingest([_source("Surfing")], client, tmp_path, sleep=lambda _seconds: None)
        report = ingest(
            [_source("Surfing", "Surfboard", "Missing", "Broken")],
            client,
            tmp_path,
            sleep=lambda _seconds: None,
        )

    counts = report.sources["wikipedia"]
    assert counts.saved == 1
    assert counts.unchanged == 1
    assert counts.missing == ["Missing"]
    assert [item["title"] for item in counts.failed] == ["Broken"]
    assert counts.failed[0]["error"]
    assert set(counts.failed[0]) == {"title", "error"}
    assert counts.skipped_reason is None

    written = RunReport.model_validate_json((tmp_path / "_last_run.json").read_text())
    assert written == report
    assert written.started_at <= written.finished_at
    assert [doc.title for doc in load_all(tmp_path)] == ["Surfboard", "Surfing"]


def test_one_failing_title_does_not_stop_the_others(tmp_path, monkeypatch):
    from swellsense.ingest.fetchers.mediawiki import fetch_article as real_fetch

    def fetch(client, source, title):
        if title == "Bad":
            RawDocument.model_validate({})
        return real_fetch(client, source, title)

    monkeypatch.setattr("swellsense.ingest.run.fetch_article", fetch)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        title = request.url.params["titles"]
        seen.append(title)
        if title == "Broken":
            return httpx.Response(503)
        return httpx.Response(
            200,
            json=_page(
                title, "A surfboard floats.", "https://en.wikipedia.org/wiki/Surfboard"
            ),
        )

    with _client(handler) as client:
        report = ingest(
            [_source("Broken", "Bad", "Surfboard")],
            client,
            tmp_path,
            sleep=lambda _seconds: None,
        )

    counts = report.sources["wikipedia"]
    assert [item["title"] for item in counts.failed] == ["Broken", "Bad"]
    assert counts.saved == 1
    assert (tmp_path / "wikipedia" / "surfboard.json").is_file()
    assert seen == ["Broken", "Surfboard"]


def test_sleep_is_called_between_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("REQUEST_DELAY_S", "0.25")
    get_settings.cache_clear()
    pauses: list[float] = []
    events: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        title = request.url.params["titles"]
        events.append(f"request:{title}")
        slug = title.replace(" ", "_")
        return httpx.Response(
            200,
            json=_page(
                title, f"{title} is a page.", f"https://en.wikipedia.org/wiki/{slug}"
            ),
        )

    def fake_sleep(seconds: float) -> None:
        pauses.append(seconds)
        events.append("sleep")

    notes = _source("Wind", source_id="notes")
    try:
        with _client(handler) as client:
            report = ingest(
                [_source("Swell", "Tide"), _web_source(), notes],
                client,
                tmp_path,
                sleep=fake_sleep,
            )
    finally:
        get_settings.cache_clear()

    assert pauses == [0.25, 0.25]
    assert events == [
        "request:Swell",
        "sleep",
        "request:Tide",
        "sleep",
        "request:Wind",
    ]
    assert report.sources["blog"].skipped_reason == "web fetcher not implemented"
    assert report.sources["wikipedia"].saved == 2
    assert report.sources["notes"].saved == 1


def test_web_source_is_skipped_without_fetching(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a web source must not be fetched")

    pauses: list[float] = []
    with _client(handler) as client:
        report = ingest([_web_source()], client, tmp_path, sleep=pauses.append)

    assert report.sources["blog"].skipped_reason == "web fetcher not implemented"
    assert report.sources["blog"].saved == 0
    assert report.sources["blog"].missing == []
    assert report.sources["blog"].failed == []
    assert pauses == []
    assert list(tmp_path.glob("*/*.json")) == []
    assert (tmp_path / "_last_run.json").is_file()
