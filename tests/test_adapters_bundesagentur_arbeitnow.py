import json
from pathlib import Path

import httpx

from job_radar.adapters import arbeitnow, bundesagentur
from job_radar.models import Company, Posting

FIXTURES = Path(__file__).parent / "fixtures"
BA_SEARCH = json.loads((FIXTURES / "bundesagentur_search.json").read_text())
BA_DETAIL = json.loads((FIXTURES / "bundesagentur_detail.json").read_text())
AN_PAGE = json.loads((FIXTURES / "arbeitnow_page1.json").read_text())


def test_bundesagentur_parse():
    posts = bundesagentur.parse("bundesagentur-de", BA_SEARCH["ergebnisliste"])
    assert len(posts) == 2
    assert posts[0].uid == "bundesagentur:bundesagentur-de:13644-308913-S"
    assert posts[0].url == "https://example.com/jobs/308913"
    assert "Essen" in posts[0].location
    assert "easy software" in posts[0].title


def test_arbeitnow_parse_filters_us_location(monkeypatch):
    monkeypatch.setattr(arbeitnow, "_germany_only", lambda: True)
    posts = arbeitnow.parse("arbeitnow-de", AN_PAGE["data"])
    assert len(posts) == 1
    assert posts[0].uid.endswith("software-engineer-berlin-123")
    assert "Berlin" in posts[0].location
    assert "Build renewable energy" in posts[0].description


async def test_bundesagentur_fetch_paginates(monkeypatch):
    calls = []

    async def fake_page(client, params, page):
        calls.append(page)
        if page == 1:
            return BA_SEARCH
        return {"ergebnisliste": []}

    monkeypatch.setattr(bundesagentur, "_search_page", fake_page)

    async with httpx.AsyncClient() as client:
        posts = await bundesagentur.fetch(
            client, Company(slug="bundesagentur-de", ats="bundesagentur", token="software"),
        )
    assert len(posts) == 2
    assert calls == [1]


async def test_bundesagentur_enrich():
    posting = Posting(
        uid="bundesagentur:bundesagentur-de:13644-308913-S",
        ats="bundesagentur",
        company="bundesagentur-de",
        title="Software Engineer",
        location="",
        url="https://example.com",
        posted_at=None,
        description="",
        raw={"refnr": "13644-308913-S"},
    )

    def handler(request):
        return httpx.Response(200, json=BA_DETAIL)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await bundesagentur.enrich(
            client, posting, Company(slug="bundesagentur-de", ats="bundesagentur"),
        )
    assert "cloud-native" in enriched.description
    assert "Essen" in enriched.location


async def test_arbeitnow_fetch_stops_without_next_link(monkeypatch):
    monkeypatch.setattr(arbeitnow, "_env_int", lambda name, default: 5)
    monkeypatch.setattr(arbeitnow, "_germany_only", lambda: True)

    def handler(request):
        return httpx.Response(200, json=AN_PAGE)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        posts = await arbeitnow.fetch(client, Company(slug="arbeitnow-de", ats="arbeitnow"))
    assert len(posts) == 1
