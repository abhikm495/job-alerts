import asyncio
import re
from urllib.parse import urlparse

from ..models import Company, Posting
from ._sitemap import slug_to_title
from .base import get_text

MAX_JOBS = 8000
MAX_PROBE = 24
_JOB_URL_RE = re.compile(r"-\d{5,}-mer[a-z0-9]+$", re.I)
_LOCATION_TERMS = ("bangalore", "bengaluru")


def _parse_token(token: str) -> tuple[str, str, str | None]:
    parts = token.split(":")
    if len(parts) < 2:
        raise ValueError(f"Mercedes token must be host:locale[:location], got {token!r}")
    host = parts[0]
    locale = parts[1]
    location = parts[2] if len(parts) > 2 and parts[2] else None
    return host, locale, location


def _title_from_url(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    slug = _JOB_URL_RE.sub("", slug).rstrip("-")
    return slug_to_title(slug)


async def _collect_job_urls(client, host: str, locale: str) -> list[str]:
    xml = await get_text(client, f"https://{host}/{locale}-sitemap.xml")
    urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    return [u for u in urls if _JOB_URL_RE.search(urlparse(u).path.rstrip("/"))]


async def _matches_location(client, url: str, location: str) -> bool:
    terms = list(_LOCATION_TERMS) if location.lower() in {"bangalore", "bengaluru"} else [location.lower()]
    try:
        async with client.stream("GET", url, headers={"User-Agent": "job-radar/0.1"}, timeout=30.0) as resp:
            resp.raise_for_status()
            collected = ""
            async for chunk in resp.aiter_text(chunk_size=8192):
                collected += chunk
                lower = collected.lower()
                if any(term in lower for term in terms):
                    return True
                if "</head>" in lower or len(collected) > 65536:
                    break
    except Exception:
        return False
    return False


def parse(slug: str, urls: list[str], location: str = "") -> list[Posting]:
    out = []
    for url in urls:
        out.append(Posting(
            uid=f"mercedes:{slug}:{url}",
            ats="mercedes", company=slug,
            title=_title_from_url(url), location=location, url=url,
            posted_at=None, description="",
            raw={"url": url},
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    host, locale, location = _parse_token(token)
    urls = (await _collect_job_urls(client, host, locale))[:MAX_JOBS]
    if not location:
        return parse(company.slug, urls)
    sem = asyncio.Semaphore(MAX_PROBE)

    async def probe(url: str) -> str | None:
        async with sem:
            return url if await _matches_location(client, url, location) else None

    matched = [u for u in await asyncio.gather(*[probe(url) for url in urls]) if u]
    return parse(company.slug, matched, location)
