import asyncio
from dataclasses import replace

from ..models import Company, Posting
from ._html import extract_breezy_description
from .base import get_json, get_text, to_dt

JSON_TMPL = "https://{token}.breezy.hr/json"
_ENRICH_CONCURRENCY = 8


def _format_location(item: dict) -> str:
    loc = item.get("location") or {}
    if isinstance(loc, dict):
        parts = [loc.get("city"), loc.get("state"), loc.get("country")]
        text = ", ".join(p for p in parts if p and isinstance(p, str))
    else:
        text = str(loc) if loc else ""
    locations = item.get("locations") or []
    if not text and locations:
        parts = []
        for entry in locations:
            if isinstance(entry, dict):
                chunk = ", ".join(
                    p for p in [entry.get("city"), entry.get("state"), entry.get("country")] if p
                )
                if chunk:
                    parts.append(chunk)
        text = "; ".join(parts)
    return text


def parse(slug: str, items: list) -> list[Posting]:
    out = []
    for item in items:
        jid = item.get("_id") or item.get("id")
        if jid is None:
            jid = item.get("url") or item.get("name")
        if jid is None:
            continue
        out.append(Posting(
            uid=f"breezy:{slug}:{jid}",
            ats="breezy", company=slug,
            title=item.get("name") or "",
            location=_format_location(item),
            url=item.get("url") or JSON_TMPL.format(token=slug),
            posted_at=to_dt(item.get("published_date")),
            description="",
            raw=item if isinstance(item, dict) else {},
        ))
    return out


async def _enrich_one(client, posting: Posting) -> Posting:
    try:
        html = await get_text(client, posting.url)
        desc = extract_breezy_description(html)
        if desc:
            return replace(posting, description=desc)
    except Exception:
        pass
    return posting


async def enrich(client, posting: Posting, company: Company) -> Posting:
    return await _enrich_one(client, posting)


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    payload = await get_json(client, JSON_TMPL.format(token=token))
    if not isinstance(payload, list):
        raise ValueError("expected JSON array from Breezy")
    postings = parse(company.slug, payload)
    if not postings:
        return postings
    sem = asyncio.Semaphore(_ENRICH_CONCURRENCY)

    async def one(p):
        async with sem:
            return await _enrich_one(client, p)

    return list(await asyncio.gather(*[one(p) for p in postings]))
