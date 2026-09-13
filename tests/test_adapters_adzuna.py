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
    adzuna.reset_pool()
    calls = []

    async def fake_page(client, country, params, page):
        calls.append((country, page, params.get("what")))
        if page == 1:
            return ADZUNA_SEARCH
        return {"results": []}

    monkeypatch.setattr(adzuna, "_search_page", fake_page)

    async with httpx.AsyncClient() as client:
        posts = await adzuna.fetch(
            client, Company(slug="adzuna-de", ats="adzuna", token="software"),
        )
    assert len(posts) == 2
    assert calls == [("de", 1, "software")]


def test_adzuna_country_from_slug():
    assert adzuna._country_code(Company(slug="adzuna-gb", ats="adzuna", token="software")) == "gb"
    assert adzuna._country_code(Company(slug="adzuna-de", ats="adzuna", region="de")) == "de"


async def test_adzuna_fetch_without_credentials(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    adzuna.reset_pool()

    async with httpx.AsyncClient() as client:
        posts = await adzuna.fetch(client, Company(slug="adzuna-de", ats="adzuna"))
    assert posts == []


def test_adzuna_base_search_params(monkeypatch):
    monkeypatch.setenv("ADZUNA_MAX_DAYS_OLD", "21")
    params = adzuna._base_search_params(Company(slug="adzuna-de", ats="adzuna", token="software"))
    assert params["what"] == "software"
    assert params["max_days_old"] == 21
    assert params["results_per_page"] == 50
    assert params["sort_by"] == "date"
    assert params["sort_direction"] == "down"
    assert "app_id" not in params


def test_load_credentials_shared_app_id(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "shared-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key1")
    monkeypatch.setenv("ADZUNA_APP_KEY_2", "key2")
    monkeypatch.setenv("ADZUNA_APP_KEY_3", "key3")
    monkeypatch.delenv("ADZUNA_CREDENTIALS", raising=False)
    creds = adzuna.load_credentials()
    assert creds == [("shared-id", "key1"), ("shared-id", "key2"), ("shared-id", "key3")]


def test_load_credentials_per_slot_app_id_override(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "shared-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key1")
    monkeypatch.setenv("ADZUNA_APP_ID_2", "other-id")
    monkeypatch.setenv("ADZUNA_APP_KEY_2", "key2")
    monkeypatch.delenv("ADZUNA_CREDENTIALS", raising=False)
    creds = adzuna.load_credentials()
    assert creds == [("shared-id", "key1"), ("other-id", "key2")]


def test_load_credentials_bulk_fallback(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    monkeypatch.setenv("ADZUNA_CREDENTIALS", "bulk1:secret1,bulk2:secret2")
    creds = adzuna.load_credentials()
    assert creds == [("bulk1", "secret1"), ("bulk2", "secret2")]


async def test_credential_pool_round_robin():
    pool = adzuna.CredentialPool([("a", "1"), ("b", "2"), ("c", "3")])
    starts = [await pool.start_index() for _ in range(6)]
    assert starts == [0, 1, 2, 0, 1, 2]
