from pathlib import Path

import httpx

from job_radar.adapters import devjobs
from job_radar.models import Company, Posting

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH_HTML = (FIXTURES / "devjobs_search_page1.html").read_text()
DETAIL_HTML = (FIXTURES / "devjobs_job_detail.html").read_text()


def test_parse_search_cards():
    rows = devjobs.parse_search_cards(SEARCH_HTML)
    assert len(rows) == 2
    assert rows[0]["id"] == "bfbfe12f721dcdcfa9b8fc87642d33dd"
    assert rows[0]["title"] == "System Engineer - AI Data Center Solutions"
    assert "Corning" in rows[0]["employer"]
    assert rows[0]["location"] == "Berlin"


def test_parse_builds_postings():
    rows = devjobs.parse_search_cards(SEARCH_HTML)
    posts = devjobs.parse("devjobs-de", rows)
    assert posts[0].uid == "devjobs:devjobs-de:bfbfe12f721dcdcfa9b8fc87642d33dd"
    assert posts[0].url.endswith("bfbfe12f721dcdcfa9b8fc87642d33dd")
    assert posts[0].raw["employer"].startswith("Corning")


async def test_fetch_paginates_until_empty(monkeypatch):
    calls = []

    async def fake_page(client, page):
        calls.append(page)
        if page == 1:
            return SEARCH_HTML
        return "<html></html>"

    monkeypatch.setattr(devjobs, "_fetch_page", fake_page)
    monkeypatch.setattr(devjobs, "_max_pages", lambda: None)

    async with httpx.AsyncClient() as client:
        posts = await devjobs.fetch(client, Company(slug="devjobs-de", ats="devjobs"))
    assert len(posts) == 2
    assert calls == [1, 2]


async def test_fetch_respects_max_pages(monkeypatch):
    async def fake_page(client, page):
        return SEARCH_HTML

    monkeypatch.setattr(devjobs, "_fetch_page", fake_page)
    monkeypatch.setattr(devjobs, "_max_pages", lambda: 1)

    async with httpx.AsyncClient() as client:
        posts = await devjobs.fetch(client, Company(slug="devjobs-de", ats="devjobs"))
    assert len(posts) == 2


async def test_enrich_fills_description_and_apply_url():
    posting = Posting(
        uid="devjobs:devjobs-de:bfbfe12f721dcdcfa9b8fc87642d33dd",
        ats="devjobs",
        company="devjobs-de",
        title="System Engineer - AI Data Center Solutions",
        location="",
        url="https://en.devjobs.de/job/bfbfe12f721dcdcfa9b8fc87642d33dd",
        posted_at=None,
        description="",
        raw={"job_id": "bfbfe12f721dcdcfa9b8fc87642d33dd"},
    )

    def handler(request):
        return httpx.Response(200, text=DETAIL_HTML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await devjobs.enrich(
            client, posting, Company(slug="devjobs-de", ats="devjobs"),
        )

    assert "Full job description body" in enriched.description
    assert enriched.location == "Berlin, DE"
    assert enriched.url == "https://boards.greenhouse.io/example/jobs/123"
    assert enriched.raw["apply_url"].startswith("https://boards.greenhouse.io/")
