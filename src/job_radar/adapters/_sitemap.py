"""Shared helpers for ATS adapters that expose jobs via XML sitemaps."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .base import get_text


def normalize_host(token: str) -> str:
    raw = token.strip().rstrip("/")
    if raw.startswith("http"):
        return urlparse(raw).netloc or raw
    return raw


def base_url(token: str) -> str:
    return f"https://{normalize_host(token)}"


def extract_locs(xml: str) -> list[str]:
    return re.findall(r"<loc>([^<]+)</loc>", xml or "")


async def discover_sitemap_indexes(client, base: str) -> list[str]:
    base = base.rstrip("/")
    indexes: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        if url and url not in seen:
            seen.add(url)
            indexes.append(url)

    try:
        robots = await get_text(client, f"{base}/robots.txt")
        for line in robots.splitlines():
            if line.lower().startswith("sitemap:"):
                add(line.split(":", 1)[1].strip())
    except Exception:
        pass

    if not indexes:
        for path in ("/global/en/sitemap_index.xml", "/sitemap_index.xml", "/sitemap.xml"):
            add(base + path)
    else:
        en_indexes = [u for u in indexes if "/global/en/" in u or "/en_US/" in u or "/en/" in u]
        if en_indexes:
            indexes = en_indexes

    return indexes


async def collect_job_urls_from_sitemaps(
    client,
    base: str,
    *,
    job_path_hint: str | list[str] = "/job/",
) -> list[str]:
    hints = [job_path_hint] if isinstance(job_path_hint, str) else list(job_path_hint)
    jobs: list[str] = []
    seen: set[str] = set()
    visited_sitemaps: set[str] = set()

    def matches(url: str) -> bool:
        lower = url.lower()
        return any(h.lower() in lower for h in hints)

    def add_urls(urls: list[str]) -> None:
        for url in urls:
            if not matches(url):
                continue
            if url not in seen:
                seen.add(url)
                jobs.append(url)

    async def walk(sitemap_url: str) -> None:
        if sitemap_url in visited_sitemaps:
            return
        visited_sitemaps.add(sitemap_url)
        try:
            xml = await get_text(client, sitemap_url)
        except Exception:
            return
        locs = extract_locs(xml)
        child_xml = [loc for loc in locs if loc.endswith(".xml")]
        if child_xml:
            for child in child_xml:
                await walk(child)
        else:
            add_urls(locs)

    for index_url in await discover_sitemap_indexes(client, base):
        await walk(index_url)

    return jobs


def slug_to_title(slug: str) -> str:
    return slug.replace("-", " ").strip()


def parse_sf_job_url(url: str) -> tuple[str, str]:
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if "job" not in parts:
        return "", ""
    idx = parts.index("job")
    slug = parts[idx + 1] if idx + 1 < len(parts) else ""
    if not slug or slug.isdigit():
        return slug_to_title(slug), ""

    m = re.match(r"^([A-Za-z][A-Za-z\s]*?)-(.+)-([A-Z]{2,3})-\d+$", slug)
    if m:
        return slug_to_title(m.group(2)), m.group(1)

    if re.match(r"^[A-Za-z]+-\d+-", slug):
        chunk = slug.split("-", 2)
        if len(chunk) >= 3:
            return slug_to_title(chunk[2]), chunk[0]

    return slug_to_title(slug), ""


def parse_phenom_job_url(url: str) -> tuple[str, str]:
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if "job" not in parts:
        return "", ""
    idx = parts.index("job")
    slug = parts[idx + 2] if idx + 2 < len(parts) else parts[-1]
    title = slug_to_title(slug)
    loc = ""
    m = re.search(r"-([A-Za-z]+-(?:[A-Z]{2}|\w+))$", slug)
    if m:
        loc = m.group(1).replace("-", ", ")
    return title, loc
