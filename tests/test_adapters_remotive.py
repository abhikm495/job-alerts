import json
from pathlib import Path

import httpx

from job_radar.adapters import remotive
from job_radar.models import Company

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = json.loads((FIXTURES / "remotive_search.json").read_text())


def test_remotive_parse():
    posts = remotive.parse("remotive", SEARCH["jobs"])
    assert len(posts) == 2
    assert posts[0].uid == "remotive:101"
    assert posts[0].location == "Remote (Worldwide)"
    assert posts[0].raw["countries"] == []
    assert "ASP.NET Core" in posts[0].description
    assert posts[1].raw["countries"] == ["in"]


def test_remotive_search_params_default_wide():
    params = remotive._search_params()
    assert params["limit"] == "100"
    assert "category" not in params
    assert "search" not in params


async def test_remotive_fetch(monkeypatch):
    captured = []

    async def fake_get_json(client, url, **kwargs):
        captured.append(url)
        return SEARCH

    monkeypatch.setattr(remotive, "get_json", fake_get_json)

    async with httpx.AsyncClient() as client:
        posts = await remotive.fetch(client, Company(slug="remotive", ats="remotive"))
    assert len(posts) == 2
    assert "remotive.com/api/remote-jobs" in captured[0]
    assert "category=" not in captured[0]
    assert "search=" not in captured[0]
