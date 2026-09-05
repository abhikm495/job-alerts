import asyncio
import json
import re
from dataclasses import replace

from ..models import Company, Posting
from ._html import extract_join_description, load_next_data
from .base import get_text, to_dt

PAGE_TMPL = "https://join.com/companies/{token}"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ENRICH_CONCURRENCY = 8


def _format_location(item: dict) -> str:
    city = item.get("city") or {}
    if isinstance(city, dict):
        parts = [city.get("cityName"), city.get("countryName")]
        text = ", ".join(p for p in parts if p)
    else:
        text = str(city)
    workplace = (item.get("workplaceType") or "").replace("_", " ").title()
    if workplace == "Remote":
        text = f"{text} (Remote)".strip(" ()") if text else "Remote"
    elif workplace == "Hybrid":
        text = f"{text} (Hybrid)".strip(" ()") if text else "Hybrid"
    return text


def _job_url(token: str, item: dict) -> str:
    slug = item.get("idParam") or item.get("id") or ""
    if slug:
        return f"https://join.com/companies/{token}/{slug}"
    return PAGE_TMPL.format(token=token)


def parse(slug: str, token: str, items: list[dict]) -> list[Posting]:
    out = []
    for item in items:
        jid = item.get("id") or item.get("idParam")
        if jid is None:
            continue
        out.append(Posting(
            uid=f"join_com:{slug}:{jid}",
            ats="join_com", company=slug,
            title=item.get("title", "") or "",
            location=_format_location(item),
            url=_job_url(token, item),
            posted_at=to_dt(item.get("createdAt")),
            description="",
            raw=item,
        ))
    return out


async def _enrich_one(client, posting: Posting) -> Posting:
    try:
        html = await get_text(client, posting.url)
        data = load_next_data(html)
        if data:
            desc = extract_join_description(data)
            if desc:
                return replace(posting, description=desc)
    except Exception:
        pass
    return posting


async def enrich(client, posting: Posting, company: Company) -> Posting:
    return await _enrich_one(client, posting)


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    html = await get_text(client, PAGE_TMPL.format(token=token))
    match = _NEXT_DATA.search(html)
    if not match:
        raise ValueError("Join.com page missing __NEXT_DATA__")
    page_data = json.loads(match.group(1))
    items = page_data["props"]["pageProps"]["initialState"]["jobs"].get("items") or []
    postings = parse(company.slug, token, items)
    if not postings:
        return postings
    sem = asyncio.Semaphore(_ENRICH_CONCURRENCY)

    async def one(p):
        async with sem:
            return await _enrich_one(client, p)

    return list(await asyncio.gather(*[one(p) for p in postings]))
