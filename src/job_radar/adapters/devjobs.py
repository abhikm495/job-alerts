"""DEVjobs.de aggregator — paginated search HTML + optional job detail enrich."""

from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from html import unescape
from ..models import Company, Posting
from ._html import truncate
from .base import get_text, strip_html, to_dt

SEARCH_URL = "https://en.devjobs.de/jobs/search"
JOB_URL = "https://en.devjobs.de/job/{job_id}"
MAX_PAGES_DEFAULT = 30  # ~450 jobs/run; set DEVJOBS_MAX_PAGES=0 for full catalog
JOB_ID_RE = r"[a-f0-9]{32}"
_JOB_LINK_RE = re.compile(
    rf'href="/job/({JOB_ID_RE})"[^>]*>.*?<h2[^>]*>(.*?)</h2>',
    re.S,
)
_COMPANY_RE = re.compile(
    r'<p class="[^"]*font-semibold[^"]*">(.*?)</p>',
    re.S,
)
_LOCATION_RE = re.compile(
    r'<span class="[^"]*truncate[^"]*text-ellipsis[^"]*">(.*?)</span>',
    re.S,
)
_TEASER_RE = re.compile(
    r'<p class="[^"]*line-clamp-2[^"]*">(.*?)</p>',
    re.S,
)
_JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)
_DIRECT_APPLY_RE = re.compile(r'"directApply","(https?://[^"]+)"')

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _max_pages() -> int | None:
    raw = os.environ.get("DEVJOBS_MAX_PAGES", str(MAX_PAGES_DEFAULT)).strip()
    if not raw or raw == "0":
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return MAX_PAGES_DEFAULT


def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _location_from_ld(data: dict) -> str:
    parts: list[str] = []
    for loc in data.get("jobLocation") or []:
        if not isinstance(loc, dict):
            continue
        addr = loc.get("address") or {}
        if not isinstance(addr, dict):
            continue
        city = (addr.get("addressLocality") or addr.get("addressRegion") or "").strip()
        country = (addr.get("addressCountry") or "").strip()
        if city and country:
            parts.append(f"{city}, {country}")
        elif city or country:
            parts.append(city or country)
    return "; ".join(parts)


def _description_from_ld(data: dict) -> str:
    desc = data.get("description") or ""
    if "<" in desc:
        return truncate(strip_html(desc))
    return truncate(desc)


def parse_search_cards(html: str) -> list[dict]:
    """Extract job rows from a /jobs/search HTML page."""
    rows: list[dict] = []
    seen: set[str] = set()
    for match in _JOB_LINK_RE.finditer(html):
        job_id = match.group(1)
        if job_id in seen:
            continue
        seen.add(job_id)
        tail = html[match.end() : match.end() + 4000]
        company_m = _COMPANY_RE.search(tail)
        location_m = _LOCATION_RE.search(tail)
        teaser_m = _TEASER_RE.search(tail)
        rows.append({
            "id": job_id,
            "title": _clean_html(match.group(2)),
            "employer": _clean_html(company_m.group(1)) if company_m else "",
            "location": _clean_html(location_m.group(1)) if location_m else "",
            "teaser": _clean_html(teaser_m.group(1)) if teaser_m else "",
        })
    return rows


def _parse_job_posting_ld(html: str) -> dict | None:
    for match in _JSON_LD_RE.finditer(html):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return None


def _direct_apply_url(html: str, job_id: str) -> str:
    anchor = html.find(job_id)
    if anchor < 0:
        return ""
    window = html[anchor : anchor + 8000]
    match = _DIRECT_APPLY_RE.search(window)
    return match.group(1) if match else ""


def parse(slug: str, rows: list[dict]) -> list[Posting]:
    out: list[Posting] = []
    for row in rows:
        job_id = row["id"]
        job_url = JOB_URL.format(job_id=job_id)
        out.append(Posting(
            uid=f"devjobs:{slug}:{job_id}",
            ats="devjobs",
            company=slug,
            title=row.get("title") or "",
            location=row.get("location") or "",
            url=job_url,
            posted_at=to_dt(row.get("posted_at")),
            description=row.get("teaser") or "",
            raw={
                "job_id": job_id,
                "employer": row.get("employer") or "",
                "devjobs_url": job_url,
            },
        ))
    return out


async def _fetch_page(client, page: int) -> str:
    url = SEARCH_URL if page <= 1 else f"{SEARCH_URL}?page={page}"
    return await get_text(client, url, headers=_BROWSER_HEADERS)


async def fetch(client, company: Company) -> list[Posting]:
    slug = company.slug
    max_pages = _max_pages()
    rows: list[dict] = []
    seen_ids: set[str] = set()
    page = 1
    while max_pages is None or page <= max_pages:
        html = await _fetch_page(client, page)
        batch = parse_search_cards(html)
        if not batch:
            break
        new = [row for row in batch if row["id"] not in seen_ids]
        if not new:
            break
        for row in new:
            seen_ids.add(row["id"])
        rows.extend(new)
        page += 1
    return parse(slug, rows)


async def enrich(client, posting: Posting, company: Company) -> Posting:
    job_id = posting.raw.get("job_id") or posting.uid.rsplit(":", 1)[-1]
    if not job_id:
        return posting
    try:
        html = await get_text(client, JOB_URL.format(job_id=job_id), headers=_BROWSER_HEADERS)
    except Exception:
        return posting

    employer = posting.raw.get("employer") or ""
    location = posting.location
    description = posting.description
    posted_at = posting.posted_at
    apply_url = _direct_apply_url(html, job_id)

    ld = _parse_job_posting_ld(html)
    if ld:
        org = ld.get("hiringOrganization") or {}
        if isinstance(org, dict) and org.get("name"):
            employer = org["name"]
        loc = _location_from_ld(ld)
        if loc:
            location = loc
        desc = _description_from_ld(ld)
        if desc:
            description = desc
        if ld.get("datePosted"):
            posted_at = to_dt(ld["datePosted"]) or posted_at

    url = apply_url or posting.url
    raw = dict(posting.raw)
    raw["employer"] = employer
    raw["devjobs_url"] = posting.raw.get("devjobs_url") or posting.url
    if apply_url:
        raw["apply_url"] = apply_url

    return replace(
        posting,
        location=location,
        url=url,
        posted_at=posted_at,
        description=description,
        raw=raw,
    )
