import json
from pathlib import Path

import httpx

from job_radar.adapters import himalayas
from job_radar.models import Company

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = json.loads((FIXTURES / "himalayas_search.json").read_text())


def test_himalayas_parse():
    posts = himalayas.parse("himalayas-worldwide", SEARCH["jobs"])
    assert len(posts) == 2
    assert posts[0].uid.startswith("himalayas:")
    assert posts[0].location == "Remote (Worldwide)"
    assert posts[0].raw["countries"] == []
    assert "Remote backend role." in posts[0].description
    assert posts[1].raw["countries"] == ["in"]
    assert "India" in posts[1].location


def test_himalayas_search_params_worldwide():
    params = himalayas._search_params(Company(slug="himalayas-worldwide", ats="himalayas"), 1)
    assert params["worldwide"] == "true"
    assert params["employment_type"] == "Full Time"
    assert params["sort"] == "recent"
    assert "country" not in params
    assert "q" not in params


def test_himalayas_search_params_india():
    params = himalayas._search_params(Company(slug="himalayas-in", ats="himalayas", region="in"), 2)
    assert params["country"] == "IN"
    assert params["page"] == "2"
    assert "worldwide" not in params


async def test_himalayas_fetch_paginates(monkeypatch):
    calls = []

    async def fake_get_json(client, url, **kwargs):
        calls.append(url)
        if "page=1" in url:
            return {**SEARCH, "totalCount": 100}
        return {"jobs": [], "totalCount": 100}

    monkeypatch.setattr(himalayas, "get_json", fake_get_json)

    async with httpx.AsyncClient() as client:
        posts = await himalayas.fetch(client, Company(slug="himalayas-worldwide", ats="himalayas"))
    assert len(posts) == 2
    assert "worldwide=true" in calls[0]
    assert "employment_type=Full+Time" in calls[0] or "employment_type=Full%20Time" in calls[0]
