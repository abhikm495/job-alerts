import json
from pathlib import Path

import httpx

from job_radar.adapters import adzuna
from job_radar.models import Company

FIXTURES = Path(__file__).parent / "fixtures"
ADZUNA_SEARCH = json.loads((FIXTURES / "adzuna_search.json").read_text())


def test_adzuna_parse():
    posts = adzuna.parse("adzuna-de", ADZUNA_SEARCH["results"])
    assert len(posts) == 2
    assert posts[0].uid == "adzuna:adzuna-de:5878501683"
    assert posts[0].url == "https://www.adzuna.de/land/ad/5878501683"
    assert "Berlin" in posts[0].location
    assert "Ärzte ohne Grenzen" in posts[0].title
    assert "TypeScript" in posts[0].description
    assert posts[0].posted_at is not None


async def test_adzuna_fetch_paginates(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")
    calls = []

    async def fake_page(client, params, page):
        calls.append((page, params.get("what")))
        if page == 1:
            return ADZUNA_SEARCH
        return {"results": []}

    monkeypatch.setattr(adzuna, "_search_page", fake_page)

    async with httpx.AsyncClient() as client:
        posts = await adzuna.fetch(
            client, Company(slug="adzuna-de", ats="adzuna", token="software"),
        )
    assert len(posts) == 2
    assert calls == [(1, "software")]


async def test_adzuna_fetch_without_credentials(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)

    async with httpx.AsyncClient() as client:
        posts = await adzuna.fetch(client, Company(slug="adzuna-de", ats="adzuna"))
    assert posts == []


def test_adzuna_search_params(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    monkeypatch.setenv("ADZUNA_MAX_DAYS_OLD", "21")
    params = adzuna._search_params(Company(slug="adzuna-de", ats="adzuna", token="software"))
    assert params["what"] == "software"
    assert params["max_days_old"] == 21
    assert params["results_per_page"] == 50
    assert "where" not in params
