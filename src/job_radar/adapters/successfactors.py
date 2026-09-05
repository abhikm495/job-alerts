import re

from ..models import Company, Posting
from ._sitemap import (
    base_url, collect_job_urls_from_sitemaps, normalize_host,
    parse_sf_job_url, slug_to_title,
)
from .base import get_text

MAX_JOBS = 8000


def _parse_rss_items(xml: str) -> list[tuple[str, str, str]]:
    jobs: list[tuple[str, str, str]] = []
    for block in re.findall(r"<item>(.*?)</item>", xml, re.S):
        link_m = re.search(r"<link>([^<]+)</link>", block)
        title_m = re.search(r"<title>([^<]+)</title>", block)
        if not link_m:
            continue
        url = link_m.group(1).strip()
        raw_title = (title_m.group(1) if title_m else "").strip()
        title, location = raw_title, ""
        if "(" in raw_title and raw_title.endswith(")"):
            title = raw_title[: raw_title.index("(")].strip()
            location = raw_title[raw_title.index("(") + 1 : -1].strip()
        jobs.append((url, title, location))
    return jobs


def parse(slug: str, rows: list[tuple[str, str, str]]) -> list[Posting]:
    out = []
    for url, title, location in rows:
        if not title:
            title = slug_to_title(url.rstrip("/").split("/")[-1])
        out.append(Posting(
            uid=f"successfactors:{slug}:{url}",
            ats="successfactors", company=slug,
            title=title, location=location, url=url,
            posted_at=None, description="",
            raw={"url": url},
        ))
    return out


async def _fetch_rows(client, host: str) -> list[tuple[str, str, str]]:
    xml = await get_text(client, f"{base_url(host)}/sitemap.xml")
    if "<rss" in xml:
        return _parse_rss_items(xml)
    urls = await collect_job_urls_from_sitemaps(client, base_url(host), job_path_hint="/job/")
    if not urls:
        urls = [u for u in re.findall(r"<loc>([^<]+)</loc>", xml) if "/job/" in u.lower()]
    return [(url, *parse_sf_job_url(url)) for url in urls]


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    host = normalize_host(token)
    rows = (await _fetch_rows(client, host))[:MAX_JOBS]
    return parse(company.slug, rows)
