import json
from pathlib import Path

import httpx

from job_radar.adapters import jobsbase
from job_radar.models import Company, Posting

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = json.loads((FIXTURES / "jobsbase_search.json").read_text())
DETAIL = json.loads((FIXTURES / "jobsbase_detail.json").read_text())


def test_jobsbase_parse():
    posts = jobsbase.parse("jobsbase-visa", SEARCH["jobs"])
    assert len(posts) == 2
    assert posts[0].uid == "jobsbase:senior-engineer-visa-de-abc"
    assert posts[0].raw["visa_sponsored"] is True
    assert posts[0].raw["countries"] == ["de"]
    assert "TechCo" in posts[0].title
    assert "Berlin" in posts[0].location
    assert "TypeScript" in posts[0].description
    assert posts[1].raw["countries"] == ["in"]
    assert posts[1].raw["visa_sponsored"] is False


def test_jobsbase_search_params_visa():
    params = jobsbase._search_params(Company(slug="jobsbase-visa", ats="jobsbase"))
    assert params["visa_sponsorship"] == "true"
    assert params["type"] == "full-time"
    assert params["posted_within"] == "30d"
    assert "country" not in params


def test_jobsbase_search_params_india():
    params = jobsbase._search_params(Company(slug="jobsbase-in", ats="jobsbase", region="in"))
    assert params["country"] == "IN"
    assert "visa_sponsorship" not in params


async def test_jobsbase_fetch_paginates(monkeypatch):
    calls = []
    monkeypatch.setenv("JOBSBASE_PAGE_SIZE", "2")

    async def fake_get_json(client, url, **kwargs):
        calls.append(url)
        if "cursor=" not in url:
            return {**SEARCH, "has_more": True, "next_cursor": "page2"}
        return {"jobs": [], "has_more": False, "next_cursor": None}

    monkeypatch.setattr(jobsbase, "get_json", fake_get_json)

    async with httpx.AsyncClient() as client:
        posts = await jobsbase.fetch(client, Company(slug="jobsbase-visa", ats="jobsbase"))
    assert len(posts) == 2
    assert "visa_sponsorship=true" in calls[0]
    assert any("cursor=page2" in u for u in calls)


async def test_jobsbase_enrich_fetches_description(monkeypatch):
    async def fake_get_json(client, url, **kwargs):
        assert url.endswith("senior-engineer-visa-de-abc")
        return DETAIL

    monkeypatch.setattr(jobsbase, "get_json", fake_get_json)
    posting = Posting(
        uid="jobsbase:senior-engineer-visa-de-abc",
        ats="jobsbase",
        company="jobsbase-visa",
        title="Senior Software Engineer",
        location="Berlin",
        url="https://jobsbase.io/jobs/senior-engineer-visa-de-abc",
        posted_at=None,
        description="Skills: TypeScript",
        raw={"job_id": "senior-engineer-visa-de-abc"},
    )
    async with httpx.AsyncClient() as client:
        enriched = await jobsbase.enrich(client, posting, Company(slug="jobsbase-visa", ats="jobsbase"))
    assert "Build scalable APIs" in enriched.description
    assert "<" not in enriched.description
