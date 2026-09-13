"""Adzuna job search API — Germany nationwide aggregator."""

from __future__ import annotations

import os
from urllib.parse import urlencode

from ..models import Company, Posting
from .base import get_json, strip_html, to_dt

SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/de/search/{page}"
PAGE_SIZE = 50
MAX_PAGES_DEFAULT = 10
MAX_DAYS_OLD_DEFAULT = 21
WHAT_DEFAULT = "software"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _credentials() -> tuple[str, str] | None:
    app_id = os.environ.get("ADZUNA_APP_ID", "").strip()
    app_key = os.environ.get("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        return None
    return app_id, app_key


def _search_params(company: Company) -> dict:
    creds = _credentials()
    if creds is None:
        return {}
    app_id, app_key = creds
    return {
        "app_id": app_id,
        "app_key": app_key,
        "what": (company.token or os.environ.get("ADZUNA_WHAT", WHAT_DEFAULT)).strip(),
        "results_per_page": PAGE_SIZE,
        "max_days_old": _env_int("ADZUNA_MAX_DAYS_OLD", MAX_DAYS_OLD_DEFAULT),
    }


def _location(item: dict) -> str:
    loc = item.get("location") or {}
    return (loc.get("display_name") or "").strip()


def _title(item: dict) -> str:
    title = (item.get("title") or "").strip()
    employer = ((item.get("company") or {}).get("display_name") or "").strip()
    if employer and employer.lower() not in title.lower():
        return f"{employer}: {title}" if title else employer
    return title


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out: list[Posting] = []
    for item in items:
        job_id = str(item.get("id") or "").strip()
        if not job_id:
            continue
        employer = ((item.get("company") or {}).get("display_name") or "").strip()
        out.append(Posting(
            uid=f"adzuna:{slug}:{job_id}",
            ats="adzuna",
            company=slug,
            title=_title(item),
            location=_location(item),
            url=(item.get("redirect_url") or "").strip(),
            posted_at=to_dt(item.get("created")),
            description=strip_html(item.get("description") or ""),
            raw={
                "id": job_id,
                "employer": employer,
                "category": ((item.get("category") or {}).get("label") or "").strip(),
            },
        ))
    return out


async def _search_page(client, params: dict, page: int) -> dict:
    query = urlencode(params)
    url = f"{SEARCH_URL.format(page=page)}?{query}"
    return await get_json(client, url)


async def fetch(client, company: Company) -> list[Posting]:
    slug = company.slug
    params = _search_params(company)
    if not params:
        return []
    max_pages = _env_int("ADZUNA_MAX_PAGES", MAX_PAGES_DEFAULT)
    items: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        payload = await _search_page(client, params, page)
        batch = payload.get("results") or []
        if not batch:
            break
        new = 0
        for item in batch:
            job_id = str(item.get("id") or "").strip()
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            items.append(item)
            new += 1
        if new == 0:
            break
        total = int(payload.get("count") or 0)
        if total and len(seen) >= total:
            break
    return parse(slug, items)
