"""Bundesagentur für Arbeit Jobsuche API (Germany federal job board)."""

from __future__ import annotations

import base64
import os
from dataclasses import replace
from urllib.parse import urlencode

from ..models import Company, Posting
from ._html import truncate
from .base import get_json, to_dt

SEARCH_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
DETAIL_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{code}"
PUBLIC_JOB_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{code}"
API_KEY = "jobboerse-jobsuche"
PAGE_SIZE = 50
MAX_PAGES_DEFAULT = 20

_HEADERS = {
    "X-API-Key": API_KEY,
    "Accept": "application/json",
}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _search_params(company: Company) -> dict:
    """Search knobs via env; company.token overrides the keyword (`was`)."""
    return {
        "was": (company.token or os.environ.get("BA_WAS", "software")).strip(),
        "wo": os.environ.get("BA_WO", "Deutschland").strip(),
        "veroeffentlichtseit": _env_int("BA_VEROEFFENTLICHTSEIT", 7),
        "angebotsart": 1,
        "size": PAGE_SIZE,
    }


def _location(item: dict) -> str:
    parts: list[str] = []
    for loc in item.get("stellenlokationen") or []:
        addr = loc.get("adresse") or {}
        city = (addr.get("ort") or "").strip()
        region = (addr.get("region") or "").replace("_", " ").strip()
        land = (addr.get("land") or "").replace("_", " ").strip()
        chunk = ", ".join(x for x in (city, region, land) if x)
        if chunk and chunk not in parts:
            parts.append(chunk)
    return "; ".join(parts)


def _posted_at(item: dict):
    period = item.get("veroeffentlichungszeitraum") or {}
    return to_dt(period.get("von") or item.get("datumErsteVeroeffentlichung"))


def _public_url(refnr: str, externe: str | None) -> str:
    if externe and externe.startswith("http"):
        return externe
    code = base64.b64encode(refnr.encode()).decode()
    return PUBLIC_JOB_URL.format(code=code)


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out: list[Posting] = []
    for item in items:
        refnr = (item.get("referenznummer") or item.get("refnr") or "").strip()
        if not refnr:
            continue
        employer = (item.get("firma") or item.get("arbeitgeber") or "").strip()
        title = (item.get("stellenangebotsTitel") or item.get("beruf") or "").strip()
        if employer and employer.lower() not in title.lower():
            title = f"{employer}: {title}" if title else employer
        out.append(Posting(
            uid=f"bundesagentur:{slug}:{refnr}",
            ats="bundesagentur",
            company=slug,
            title=title,
            location=_location(item),
            url=_public_url(refnr, item.get("externeURL")),
            posted_at=_posted_at(item),
            description="",
            raw={
                "refnr": refnr,
                "employer": employer,
                "beruf": item.get("hauptberuf") or item.get("beruf") or "",
            },
        ))
    return out


async def _search_page(client, params: dict, page: int) -> dict:
    query = {**params, "page": page}
    url = f"{SEARCH_URL}?{urlencode(query)}"
    return await get_json(client, url, headers=_HEADERS)


async def fetch(client, company: Company) -> list[Posting]:
    slug = company.slug
    params = _search_params(company)
    max_pages = _env_int("BA_MAX_PAGES", MAX_PAGES_DEFAULT)
    items: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        payload = await _search_page(client, params, page)
        batch = payload.get("ergebnisliste") or payload.get("stellenangebote") or []
        if not batch:
            break
        new = 0
        for item in batch:
            refnr = (item.get("referenznummer") or item.get("refnr") or "").strip()
            if not refnr or refnr in seen:
                continue
            seen.add(refnr)
            items.append(item)
            new += 1
        if new == 0:
            break
        total = int(payload.get("maxErgebnisse") or 0)
        if total and len(seen) >= total:
            break
    return parse(slug, items)


async def enrich(client, posting: Posting, company: Company) -> Posting:
    refnr = posting.raw.get("refnr") or posting.uid.rsplit(":", 1)[-1]
    if not refnr:
        return posting
    code = base64.b64encode(refnr.encode()).decode()
    try:
        detail = await get_json(client, DETAIL_URL.format(code=code), headers=_HEADERS)
    except Exception:
        return posting
    desc = (
        detail.get("stellenangebotsBeschreibung")
        or detail.get("stellenbeschreibung")
        or ""
    )
    if not desc:
        return posting
    loc = _location(detail) or posting.location
    return replace(posting, location=loc, description=truncate(desc.strip()))
