"""Arbeitnow job board API — Europe tech jobs (Germany-heavy)."""

from __future__ import annotations

import os
import re

from ..models import Company, Posting
from .base import get_json, strip_html, to_dt

API = "https://www.arbeitnow.com/api/job-board-api"
MAX_PAGES_DEFAULT = 10

# Rough filter: keep Germany/Europe-remote; drop obvious US/UK-only postings.
_NON_DE = re.compile(
    r"\b(united states|usa|u\.s\.|seattle|san francisco|new york|austin|boston|"
    r"chicago|denver|london|manchester|birmingham|edinburgh)\b",
    re.I,
)
_DE_HINT = re.compile(
    r"\b(germany|deutschland|berlin|munich|münchen|hamburg|frankfurt|köln|koln|"
    r"cologne|stuttgart|düsseldorf|dusseldorf|leipzig|dresden|hannover|nürnberg|"
    r"nuremberg|bremen|essen|bonn|karlsruhe|remote|hybrid)\b",
    re.I,
)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _germany_only() -> bool:
    return os.environ.get("ARBEITNOW_GERMANY_ONLY", "true").strip().lower() in ("1", "true", "yes")


def _keep_location(location: str, remote: bool) -> bool:
    if not _germany_only():
        return True
    loc = (location or "").strip()
    if _NON_DE.search(loc):
        return False
    if not loc or loc.lower() == "remote":
        return True
    if remote:
        return True
    return bool(_DE_HINT.search(loc))


def _posted_at(value):
    if value is None:
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return to_dt(value)
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OSError, ValueError):
        return None


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out: list[Posting] = []
    for item in items:
        job_id = (item.get("slug") or "").strip()
        if not job_id:
            continue
        remote = bool(item.get("remote"))
        location = (item.get("location") or "").strip()
        if not _keep_location(location, remote):
            continue
        company_name = (item.get("company_name") or "").strip()
        title = (item.get("title") or "").strip()
        if company_name:
            title = f"{company_name}: {title}" if title else company_name
        if remote and location.lower() != "remote":
            location = f"{location} (Remote)".strip()
        desc = strip_html(item.get("description") or "")
        out.append(Posting(
            uid=f"arbeitnow:{slug}:{job_id}",
            ats="arbeitnow",
            company=slug,
            title=title,
            location=location,
            url=item.get("url") or "",
            posted_at=_posted_at(item.get("created_at")),
            description=desc,
            raw={
                "slug": job_id,
                "employer": company_name,
                "remote": remote,
                "tags": item.get("tags") or [],
            },
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    slug = company.slug
    max_pages = _env_int("ARBEITNOW_MAX_PAGES", MAX_PAGES_DEFAULT)
    items: list[dict] = []
    seen: set[str] = set()
    page = 1
    while page <= max_pages:
        payload = await get_json(client, f"{API}?page={page}")
        batch = payload.get("data") or []
        if not batch:
            break
        new = 0
        for item in batch:
            job_id = (item.get("slug") or "").strip()
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            items.append(item)
            new += 1
        if new == 0:
            break
        links = payload.get("links") or {}
        if not links.get("next"):
            break
        page += 1
    return parse(slug, items)
