"""Remotive remote jobs API — full dev feed, no category filter (no API key)."""

from __future__ import annotations

import os
from urllib.parse import urlencode

from ..models import Company, Posting
from .base import get_json, strip_html, to_dt

API_URL = "https://remotive.com/api/remote-jobs"
LIMIT_DEFAULT = 100

_COUNTRY_HINTS = (
    ("united states", "us"),
    ("united kingdom", "gb"),
    ("india", "in"),
    ("canada", "ca"),
    ("germany", "de"),
    ("france", "fr"),
    ("australia", "au"),
    ("singapore", "sg"),
    ("netherlands", "nl"),
    ("spain", "es"),
    ("italy", "it"),
    ("brazil", "br"),
    ("mexico", "mx"),
    ("poland", "pl"),
    ("ireland", "ie"),
    ("sweden", "se"),
    ("switzerland", "ch"),
)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _search_params() -> dict[str, str]:
    params: dict[str, str] = {
        "limit": str(_env_int("REMOTIVE_LIMIT", LIMIT_DEFAULT)),
    }
    category = os.environ.get("REMOTIVE_CATEGORY", "").strip()
    if category:
        params["category"] = category
    search = os.environ.get("REMOTIVE_SEARCH", "").strip()
    if search:
        params["search"] = search
    return params


def _countries_from_location(location: str) -> list[str]:
    loc = (location or "").strip().lower()
    if not loc or "worldwide" in loc or "anywhere" in loc:
        return []
    out: list[str] = []
    for phrase, code in _COUNTRY_HINTS:
        if phrase in loc and code not in out:
            out.append(code)
    return out


def _location_label(item: dict) -> str:
    loc = (item.get("candidate_required_location") or "").strip()
    if loc:
        return f"Remote ({loc})"
    return "Remote"


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out: list[Posting] = []
    for item in items:
        job_id = str(item.get("id") or "").strip()
        if not job_id:
            continue
        company_name = (item.get("company_name") or "").strip()
        title = (item.get("title") or "").strip()
        if company_name and company_name.lower() not in title.lower():
            title = f"{company_name}: {title}" if title else company_name
        loc_raw = (item.get("candidate_required_location") or "").strip()
        desc = item.get("description") or ""
        if desc and "<" in desc:
            desc = strip_html(desc)
        out.append(Posting(
            uid=f"remotive:{job_id}",
            ats="remotive",
            company=slug,
            title=title,
            location=_location_label(item),
            url=(item.get("url") or "").strip(),
            posted_at=to_dt(item.get("publication_date")),
            description=desc,
            raw={
                "job_id": job_id,
                "countries": _countries_from_location(loc_raw),
                "visa_sponsored": False,
                "workplace": "remote",
                "category": item.get("category"),
            },
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    params = _search_params()
    url = f"{API_URL}?{urlencode(params)}"
    payload = await get_json(client, url)
    return parse(company.slug, payload.get("jobs") or [])
