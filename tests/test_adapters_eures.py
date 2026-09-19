import json
from pathlib import Path

import httpx

from job_radar.adapters import eures
from job_radar.models import Company

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = json.loads((FIXTURES / "eures_search.json").read_text())


def test_eures_parse():
    posts = eures.parse("eures-de", SEARCH["jvs"])
    assert len(posts) == 2
    assert posts[0].uid == "eures:MTAwMDAtMTIwNzg5MDc5Ni1TIDE"
    assert posts[0].raw["eures_flag"] is True
    assert posts[0].raw["countries"] == ["de"]
    assert "Tech GmbH" in posts[0].title
    assert "Develop backend services" in posts[0].description
    assert "europa.eu/eures/portal" in posts[0].url
    assert posts[1].raw["countries"] == ["fr"]


def test_eures_country_code_from_region():
    assert eures._country_code(Company(slug="eures-fr", ats="eures", region="fr")) == "fr"
    assert eures._country_code(Company(slug="eures-nl", ats="eures", region="nl")) == "nl"


def test_eures_search_body():
    body = eures._search_body(Company(slug="eures-de", ats="eures", region="de"), 1)
    assert body["locationCodes"] == ["de"]
    assert body["euresFlagCodes"] == ["WITH"]
    assert body["positionScheduleCodes"] == ["fulltime"]
    assert body["keywords"] == []
    assert body["publicationPeriod"] == "LAST_WEEK"


async def test_eures_fetch_paginates(monkeypatch):
    calls = []

    async def fake_get_json(client, url, **kwargs):
        calls.append(kwargs.get("json_body", {}))
        page = kwargs.get("json_body", {}).get("page", 1)
        if page == 1:
            return {**SEARCH, "numberRecords": 100}
        return {"numberRecords": 100, "jvs": [], "facets": {}}

    monkeypatch.setattr(eures, "get_json", fake_get_json)

    async with httpx.AsyncClient() as client:
        posts = await eures.fetch(client, Company(slug="eures-de", ats="eures", region="de"))
    assert len(posts) == 2
    assert calls[0]["locationCodes"] == ["de"]
    assert calls[0]["euresFlagCodes"] == ["WITH"]
