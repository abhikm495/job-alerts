"""JobsBase builder-jobs API — visa sponsorship and regional feeds (no API key)."""

from __future__ import annotations

import os
from dataclasses import replace
from urllib.parse import urlencode

from ..models import Company, Posting
from ._html import truncate
from .base import get_json, strip_html, to_dt

SEARCH_URL = "https://jobsbase.io/api/v1/jobs"
MAX_PAGES_DEFAULT = 5
PAGE_SIZE_DEFAULT = 100
POSTED_WITHIN_DEFAULT = "7d"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _posted_within() -> str:
    raw = os.environ.get("JOBSBASE_POSTED_WITHIN", POSTED_WITHIN_DEFAULT).strip()
    return raw or POSTED_WITHIN_DEFAULT


def _board_mode(company: Company) -> str:
    slug = (company.slug or "").lower()
    if slug.endswith("-in") or slug == "jobsbase-in":
        return "india"
    if "visa" in slug:
        return "visa_global"
    token = (company.token or "").lower().strip()
    if token in ("india", "in", "india_all"):
        return "india"
    if token in ("visa", "visa_global"):
        return "visa_global"
    return "visa_global"


def _search_params(company: Company) -> dict[str, str]:
    mode = _board_mode(company)
    params: dict[str, str] = {
        "type": "full-time",
        "posted_within": _posted_within(),
        "limit": str(min(100, _env_int("JOBSBASE_PAGE_SIZE", PAGE_SIZE_DEFAULT))),
        "sort": "posted_at",
    }
    if mode == "visa_global":
        params["visa_sponsorship"] = "true"
    elif mode == "india":
        params["country"] = "IN"
    return params


def _countries(item: dict) -> list[str]:
    out: list[str] = []
    for loc in item.get("locations") or []:
        code = str(loc.get("country") or "").strip().lower()
        if code and code not in out:
            out.append(code)
    if not out:
        code = str(item.get("country") or "").strip().lower()
        if code:
            out.append(code)
    return out


def _location_label(item: dict) -> str:
    loc = (item.get("display_location") or "").strip()
    workplace = (item.get("workplace") or "").strip()
    if workplace and workplace.lower() not in loc.lower():
        loc = f"{loc} ({workplace})" if loc else workplace
    if not loc:
        countries = _countries(item)
        if countries:
            loc = ", ".join(c.upper() for c in countries[:3])
    return loc


def _skills_text(item: dict) -> str:
    skills = item.get("skills")
    if isinstance(skills, list):
        return ", ".join(str(s) for s in skills if s)
    return str(skills or "").strip()


def _visa_flag(item: dict) -> bool:
    if item.get("visa_sponsorship") is True:
        return True
    return str(item.get("visa_sponsorship", "")).lower() == "true"


def _job_id(item: dict) -> str:
    return str(item.get("id") or "").strip()


def _description_stub(item: dict) -> str:
    parts = []
    skills = _skills_text(item)
    if skills:
        parts.append(f"Skills: {skills}")
    seniority = (item.get("seniority_level") or "").strip()
    if seniority:
        parts.append(f"Seniority: {seniority}")
    return "\n".join(parts)


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out: list[Posting] = []
    for item in items:
        job_id = _job_id(item)
        if not job_id:
            continue
        company_name = (item.get("company") or "").strip()
        title = (item.get("title") or "").strip()
        if company_name and company_name.lower() not in title.lower():
            title = f"{company_name}: {title}" if title else company_name
        countries = _countries(item)
        visa = _visa_flag(item)
        url = (item.get("job_url") or "").strip()
        out.append(Posting(
            uid=f"jobsbase:{job_id}",
            ats="jobsbase",
            company=slug,
            title=title,
            location=_location_label(item),
            url=url,
            posted_at=to_dt(item.get("posted_at")),
            description=_description_stub(item),
            raw={
                "job_id": job_id,
                "countries": countries,
                "visa_sponsored": visa,
                "workplace": item.get("workplace"),
            },
        ))
    return out


async def enrich(client, posting: Posting, company: Company) -> Posting:
    job_id = (posting.raw or {}).get("job_id") or posting.uid.rsplit(":", 1)[-1]
    if not job_id:
        return posting
    try:
        detail = await get_json(client, f"{SEARCH_URL}/{job_id}")
    except Exception:
        return posting
    desc = detail.get("description") or ""
    if desc and "<" in desc:
        desc = strip_html(desc)
    if not desc:
        return posting
    loc = _location_label(detail) or posting.location
    return replace(posting, location=loc, description=truncate(desc.strip()))


async def fetch(client, company: Company) -> list[Posting]:
    slug = company.slug
    base_params = _search_params(company)
    max_pages = _env_int("JOBSBASE_MAX_PAGES", MAX_PAGES_DEFAULT)
    page_size = int(base_params["limit"])
    items: list[dict] = []
    seen: set[str] = set()
    cursor: str | None = None
    for _ in range(max_pages):
        params = dict(base_params)
        if cursor:
            params["cursor"] = cursor
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
        if new == 0 or not payload.get("has_more"):
            break
        cursor = payload.get("next_cursor")
        if not cursor or len(batch) < page_size:
            break
    return parse(slug, items)
