"""Freehire job search API — visa sponsorship and regional feeds (no API key)."""

from __future__ import annotations

import os
from urllib.parse import urlencode

from ..models import Company, Posting
from .base import get_json, strip_html, to_dt

AGENT_SEARCH_URL = "https://freehire.me/api/v1/agent/jobs/search"
MAX_PAGES_DEFAULT = 5
PAGE_SIZE_DEFAULT = 100
OPEN_WITHIN_DAYS_DEFAULT = 30
# Freehire ORs comma-separated categories — cover SWE roles both profiles target.
DEFAULT_CATEGORIES = (
    "software_engineering,backend,frontend,fullstack,architecture,solutions_engineering"
)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _board_mode(company: Company) -> str:
    """Derive fetch mode from slug: freehire-visa (global visa) or freehire-in (India all)."""
    slug = (company.slug or "").lower()
    if slug.endswith("-in") or slug == "freehire-in":
        return "india"
    if "visa" in slug:
        return "visa_global"
    token = (company.token or "").lower().strip()
    if token in ("india", "in", "india_all"):
        return "india"
    if token in ("visa", "visa_global"):
        return "visa_global"
    return "visa_global"


def _categories() -> str:
    raw = os.environ.get("FREEHIRE_CATEGORIES", DEFAULT_CATEGORIES).strip()
    return raw or DEFAULT_CATEGORIES


def _search_params(company: Company) -> dict[str, str]:
    mode = _board_mode(company)
    params: dict[str, str] = {
        "category": _categories(),
        "employment_type": "full_time",
        "seniority_exclude": "intern",
        "role_type_exclude": "people_manager",
        "limit": str(min(100, _env_int("FREEHIRE_PAGE_SIZE", PAGE_SIZE_DEFAULT))),
        "open_within_days": str(_env_int("FREEHIRE_OPEN_WITHIN_DAYS", OPEN_WITHIN_DAYS_DEFAULT)),
        "description_format": "text",
    }
    if mode == "visa_global":
        params["visa_sponsorship"] = "true"
    elif mode == "india":
        params["countries"] = "IN"
    return params


def _visa_flag(item: dict) -> bool:
    enrichment = item.get("enrichment") or {}
    if enrichment.get("visa_sponsorship") is True:
        return True
    if str(enrichment.get("visa_sponsorship", "")).lower() == "true":
        return True
    return False


def _location_label(item: dict) -> str:
    loc = (item.get("location") or "").strip()
    work_mode = (item.get("work_mode") or (item.get("enrichment") or {}).get("work_mode") or "").strip()
    if work_mode and work_mode.lower() not in loc.lower():
        loc = f"{loc} ({work_mode})" if loc else work_mode
    countries = item.get("countries") or []
    if countries and not loc:
        loc = ", ".join(str(c).upper() for c in countries[:3])
    return loc


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out: list[Posting] = []
    for item in items:
        public_slug = (item.get("public_slug") or "").strip()
        if not public_slug:
            continue
        company_name = (item.get("company") or "").strip()
        title = (item.get("title") or "").strip()
        if company_name and company_name.lower() not in title.lower():
            title = f"{company_name}: {title}" if title else company_name
        countries = [str(c).lower() for c in (item.get("countries") or []) if c]
        visa = _visa_flag(item)
        desc = item.get("description") or ""
        if desc and "<" in desc:
            desc = strip_html(desc)
        out.append(Posting(
            uid=f"freehire:{public_slug}",
            ats="freehire",
            company=slug,
            title=title,
            location=_location_label(item),
            url=(item.get("url") or "").strip(),
            posted_at=to_dt(item.get("posted_at") or item.get("created_at")),
            description=desc,
            raw={
                "public_slug": public_slug,
                "countries": countries,
                "visa_sponsored": visa,
                "work_mode": item.get("work_mode"),
                "source": item.get("source"),
            },
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    slug = company.slug
    base_params = _search_params(company)
    max_pages = _env_int("FREEHIRE_MAX_PAGES", MAX_PAGES_DEFAULT)
    page_size = int(base_params["limit"])
    items: list[dict] = []
    seen: set[str] = set()
    offset = 0
    for _ in range(max_pages):
        params = {**base_params, "offset": str(offset)}
        url = f"{AGENT_SEARCH_URL}?{urlencode(params)}"
        payload = await get_json(client, url)
        batch = payload.get("data") or []
        if not batch:
            break
        new = 0
        for item in batch:
            public_slug = (item.get("public_slug") or "").strip()
            if not public_slug or public_slug in seen:
                continue
            seen.add(public_slug)
            items.append(item)
            new += 1
        if new == 0 or len(batch) < page_size:
            break
        offset += page_size
        if offset + page_size > 10000:
            break
    return parse(slug, items)
