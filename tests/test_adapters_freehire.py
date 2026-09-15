import json
from pathlib import Path

import httpx

from job_radar.adapters import freehire
from job_radar.models import Company

FIXTURES = Path(__file__).parent / "fixtures"
FREEHIRE_SEARCH = json.loads((FIXTURES / "freehire_search.json").read_text())


def test_freehire_parse():
    posts = freehire.parse("freehire-visa", FREEHIRE_SEARCH["data"])
    assert len(posts) == 3
    assert posts[0].uid == "freehire:stripe-swe-berlin-visa"
    assert posts[0].ats == "freehire"
    assert "Stripe" in posts[0].title
    assert "Berlin" in posts[0].location
    assert posts[0].raw["visa_sponsored"] is True
    assert posts[0].raw["countries"] == ["de"]
    assert posts[1].raw["visa_sponsored"] is False
    assert "Go and Kubernetes" in posts[2].description
    assert "<" not in posts[2].description


def test_freehire_search_params_visa():
    params = freehire._search_params(Company(slug="freehire-visa", ats="freehire"))
    assert params["visa_sponsorship"] == "true"
    cats = params["category"].split(",")
    assert "software_engineering" in cats
    assert "backend" in cats
    assert "fullstack" in cats
    assert params["employment_type"] == "full_time"
    assert params["seniority_exclude"] == "intern"
    assert params["role_type_exclude"] == "people_manager"
    assert "countries" not in params


def test_freehire_categories_env_override(monkeypatch):
    monkeypatch.setenv("FREEHIRE_CATEGORIES", "backend,frontend")
    assert freehire._categories() == "backend,frontend"


def test_freehire_search_params_india():
    params = freehire._search_params(Company(slug="freehire-in", ats="freehire", region="in"))
    assert params["countries"] == "IN"
    assert "visa_sponsorship" not in params


def test_freehire_board_mode_from_token():
    assert freehire._board_mode(Company(slug="x", ats="freehire", token="india_all")) == "india"
    assert freehire._board_mode(Company(slug="x", ats="freehire", token="visa_global")) == "visa_global"


async def test_freehire_fetch_paginates(monkeypatch):
    calls = []

    async def fake_get_json(client, url):
        calls.append(url)
        if "offset=0" in url:
            return FREEHIRE_SEARCH
        return {"data": []}

    monkeypatch.setattr(freehire, "get_json", fake_get_json)

    async with httpx.AsyncClient() as client:
        posts = await freehire.fetch(client, Company(slug="freehire-visa", ats="freehire"))
    assert len(posts) == 3
    assert calls[0].startswith(freehire.AGENT_SEARCH_URL)
    assert "visa_sponsorship=true" in calls[0]


async def test_freehire_fetch_india_board(monkeypatch):
    captured = []

    async def fake_get_json(client, url):
        captured.append(url)
        return {"data": FREEHIRE_SEARCH["data"][:1]}

    monkeypatch.setattr(freehire, "get_json", fake_get_json)

    async with httpx.AsyncClient() as client:
        posts = await freehire.fetch(client, Company(slug="freehire-in", ats="freehire", region="in"))
    assert len(posts) == 1
    assert "countries=IN" in captured[0]
    assert "visa_sponsorship" not in captured[0]
