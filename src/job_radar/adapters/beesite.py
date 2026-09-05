import json
from urllib.parse import quote

from ..models import Company, Posting
from .base import get_json, to_dt

PAGE_SIZE = 100
MAX_JOBS = 5000
DB_CAREERS_JOB_URL = "https://careers.db.com/professionals/search-roles/#/professional/job/{job_id}"

MATCHED_FIELDS = [
    "PositionID", "PositionTitle", "PositionURI",
    "PositionFormattedDescription.Content",
    "PositionLocation.CountryName", "PositionLocation.CityName",
    "JobCategory.Name", "CareerLevel.Name", "PublicationStartDate",
]


def _search_url(token: str) -> str:
    tenant = token.strip().lower()
    if tenant.startswith("http"):
        base = tenant.rstrip("/")
        return base if base.endswith("/search") else f"{base}/search"
    return f"https://api-{tenant}.beesite.de/search/"


def _build_payload(first: int, count: int) -> dict:
    return {
        "LanguageCode": "EN",
        "SearchParameters": {
            "FirstItem": first, "CountItem": count,
            "MatchedObjectDescriptor": MATCHED_FIELDS,
            "Sort": [{"Criterion": "PublicationStartDate", "Direction": "DESC"}],
        },
        "SearchCriteria": [],
    }


def _location(descriptor: dict) -> str:
    parts: list[str] = []
    for loc in descriptor.get("PositionLocation") or []:
        city = (loc.get("CityName") or "").strip()
        country = (loc.get("CountryName") or "").strip()
        if city and country:
            parts.append(f"{city}, {country}")
        elif city or country:
            parts.append(city or country)
    if parts:
        return "; ".join(parts)
    city = (descriptor.get("PositionLocation.CityName") or "").strip()
    country = (descriptor.get("PositionLocation.CountryName") or "").strip()
    if city and country:
        return f"{city}, {country}"
    return city or country or ""


def _job_url(token: str, descriptor: dict) -> str:
    position_uri = (descriptor.get("PositionURI") or "").strip()
    if position_uri.startswith("http"):
        return position_uri
    job_id = descriptor.get("PositionID") or ""
    if token.strip().lower() == "deutschebank" and job_id:
        return DB_CAREERS_JOB_URL.format(job_id=job_id)
    if position_uri:
        base = _search_url(token).replace("/search/", "")
        return f"{base}/{position_uri.lstrip('/')}"
    return ""


def parse(slug: str, token: str, items: list[dict]) -> list[Posting]:
    out = []
    for descriptor in items:
        job_id = descriptor.get("PositionID")
        if job_id is None:
            continue
        out.append(Posting(
            uid=f"beesite:{slug}:{job_id}",
            ats="beesite", company=slug,
            title=descriptor.get("PositionTitle") or "",
            location=_location(descriptor),
            url=_job_url(token, descriptor),
            posted_at=to_dt(descriptor.get("PublicationStartDate")),
            description=descriptor.get("JobCategory.Name") or descriptor.get("CareerLevel.Name") or "",
            raw=descriptor,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    descriptors: list[dict] = []
    first = 1
    total = None
    while first <= MAX_JOBS:
        base = _search_url(token).rstrip("/")
        url = f"{base}/?data={quote(json.dumps(_build_payload(first, PAGE_SIZE), separators=(',', ':')))}"
        data = await get_json(client, url)
        result = data.get("SearchResult") or {}
        if total is None:
            total = int(result.get("SearchResultCountAll") or 0)
        batch = result.get("SearchResultItems") or []
        if not batch:
            break
        for item in batch:
            descriptors.append(item.get("MatchedObjectDescriptor") or {})
        first += len(batch)
        if total and first > total:
            break
    return parse(company.slug, token, descriptors)
