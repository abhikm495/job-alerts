"""Himalayas remote jobs API — worldwide and India feeds (no API key)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlencode

from ..models import Company, Posting
from .base import from_ms, get_json, strip_html, to_dt

SEARCH_URL = "https://himalayas.app/jobs/api/search"
MAX_PAGES_DEFAULT = 5


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _board_mode(company: Company) -> str:
    slug = (company.slug or "").lower()
    if slug.endswith("-in") or slug == "himalayas-in":
        return "india"
    token = (company.token or "").lower().strip()
    if token in ("india", "in", "india_all"):
        return "india"
    return "worldwide"


def _search_params(company: Company, page: int) -> dict[str, str]:
    mode = _board_mode(company)
    params: dict[str, str] = {
        "employment_type": "Full Time",
        "sort": "recent",
        "page": str(page),
    }
    if mode == "india":
        params["country"] = "IN"
    else:
        params["worldwide"] = "true"
    q = os.environ.get("HIMALAYAS_Q", "").strip()
    if q:
        params["q"] = q
    return params


def _posted_at(value) -> datetime | None:
    if value is None:
        return None
    try:
        n = int(value)
        if n > 1_000_000_000_000:
            return from_ms(n)
        return datetime.fromtimestamp(n, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return to_dt(value)


def _countries(item: dict) -> list[str]:
    out: list[str] = []
    for loc in item.get("locationRestrictions") or []:
        code = str(loc.get("alpha2") or "").strip().lower()
        if code and code not in out:
            out.append(code)
    return out


def _location_label(item: dict) -> str:
    restrictions = item.get("locationRestrictions") or []
    if not restrictions:
        return "Remote (Worldwide)"
    names = []
    for loc in restrictions:
        name = (loc.get("name") or loc.get("alpha2") or "").strip()
        if name:
            names.append(name)
    if not names:
        return "Remote"
    return f"Remote ({', '.join(names[:5])})"


def _job_id(item: dict) -> str:
    guid = (item.get("guid") or "").strip()
    if guid:
        return guid
    link = (item.get("applicationLink") or "").strip()
    if link:
        return link
    company = (item.get("companySlug") or "").strip()
    title = (item.get("title") or "").strip()
    if company and title:
        return f"{company}:{title}"
    return ""


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out: list[Posting] = []
    for item in items:
        job_id = _job_id(item)
        if not job_id:
            continue
        company_name = (item.get("companyName") or "").strip()
        title = (item.get("title") or "").strip()
        if company_name and company_name.lower() not in title.lower():
            title = f"{company_name}: {title}" if title else company_name
        desc = item.get("description") or item.get("excerpt") or ""
        if desc and "<" in desc:
            desc = strip_html(desc)
        url = (item.get("applicationLink") or item.get("guid") or "").strip()
        out.append(Posting(
            uid=f"himalayas:{job_id}",
            ats="himalayas",
            company=slug,
            title=title,
            location=_location_label(item),
            url=url,
            posted_at=_posted_at(item.get("pubDate")),
            description=desc,
            raw={
                "guid": job_id,
                "countries": _countries(item),
                "visa_sponsored": False,
                "workplace": "remote",
            },
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    slug = company.slug
    max_pages = _env_int("HIMALAYAS_MAX_PAGES", MAX_PAGES_DEFAULT)
    items: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        params = _search_params(company, page)
        url = f"{SEARCH_URL}?{urlencode(params)}"
        payload = await get_json(client, url)
        batch = payload.get("jobs") or []
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
        if new == 0:
            break
        total = int(payload.get("totalCount") or 0)
        if total and page * len(batch) >= total:
            break
    return parse(slug, items)
