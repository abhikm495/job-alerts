"""EURES EU job mobility API — per-country EURES-flagged vacancies (no API key)."""

from __future__ import annotations

import os

from ..models import Company, Posting
from .base import from_ms, get_json, strip_html

SEARCH_URL = "https://europa.eu/eures/api/jv-searchengine/public/jv-search/search"
DETAIL_URL = "https://europa.eu/eures/portal/jv-se/jv-details/{id}?lang=en"
MAX_PAGES_DEFAULT = 5
RESULTS_PER_PAGE_DEFAULT = 50
PUBLICATION_PERIOD_DEFAULT = "LAST_WEEK"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _publication_period() -> str | None:
    raw = os.environ.get("EURES_PUBLICATION_PERIOD", PUBLICATION_PERIOD_DEFAULT).strip()
    if not raw or raw.lower() in ("none", "null", "all"):
        return None
    return raw


def _country_code(company: Company) -> str:
    if company.region:
        return company.region.lower().strip()
    slug = (company.slug or "").lower()
    if slug.startswith("eures-") and len(slug) > 6:
        return slug[6:]
    token = (company.token or "").strip().lower()
    if token:
        return token.split(",")[0]
    return "de"


def _search_body(company: Company, page: int) -> dict:
    return {
        "resultsPerPage": min(50, _env_int("EURES_RESULTS_PER_PAGE", RESULTS_PER_PAGE_DEFAULT)),
        "page": page,
        "sortSearch": "MOST_RECENT",
        "keywords": [],
        "publicationPeriod": _publication_period(),
        "occupationUris": [],
        "skillUris": [],
        "requiredExperienceCodes": [],
        "positionScheduleCodes": ["fulltime"],
        "sectorCodes": [],
        "educationAndQualificationLevelCodes": [],
        "positionOfferingCodes": [],
        "locationCodes": [_country_code(company)],
        "euresFlagCodes": ["WITH"],
        "otherBenefitsCodes": [],
        "requiredLanguages": [],
        "minNumberPost": None,
        "sessionId": os.environ.get("EURES_SESSION_ID", "job-radar"),
        "requestLanguage": os.environ.get("EURES_REQUEST_LANGUAGE", "en"),
    }


def _countries(item: dict) -> list[str]:
    loc_map = item.get("locationMap") or {}
    return [str(k).lower() for k in loc_map if k]


def _location_label(item: dict) -> str:
    countries = _countries(item)
    if not countries:
        return "EU"
    return ", ".join(c.upper() for c in countries[:5])


def _job_id(item: dict) -> str:
    return str(item.get("id") or "").strip()


def _description(item: dict) -> str:
    desc = item.get("description") or ""
    if desc and "<" in desc:
        desc = strip_html(desc)
    return desc


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out: list[Posting] = []
    for item in items:
        job_id = _job_id(item)
        if not job_id:
            continue
        employer = (item.get("employer") or {}).get("name") or ""
        title = (item.get("title") or "").strip()
        if employer and employer.lower() not in title.lower():
            title = f"{employer}: {title}" if title else employer
        countries = _countries(item)
        out.append(Posting(
            uid=f"eures:{job_id}",
            ats="eures",
            company=slug,
            title=title,
            location=_location_label(item),
            url=DETAIL_URL.format(id=job_id),
            posted_at=from_ms(item.get("lastModificationDate") or item.get("creationDate")),
            description=_description(item),
            raw={
                "job_id": job_id,
                "countries": countries,
                "eures_flag": bool(item.get("euresFlag")),
                "visa_sponsored": False,
            },
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    slug = company.slug
    max_pages = _env_int("EURES_MAX_PAGES", MAX_PAGES_DEFAULT)
    page_size = min(50, _env_int("EURES_RESULTS_PER_PAGE", RESULTS_PER_PAGE_DEFAULT))
    items: list[dict] = []
    seen: set[str] = set()
    total_records = 0
    for page in range(1, max_pages + 1):
        body = _search_body(company, page)
        payload = await get_json(client, SEARCH_URL, method="POST", json_body=body)
        total_records = int(payload.get("numberRecords") or 0)
        batch = payload.get("jvs") or []
        if not batch:
            break
        new = 0
        for item in batch:
            job_id = _job_id(item)
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            items.append(item)
            new += 1
        if new == 0 or len(batch) < page_size:
            break
        if total_records and page * page_size >= total_records:
            break
    return parse(slug, items)
