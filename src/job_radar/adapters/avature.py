import html
import re

from ..models import Company, Posting
from .base import get_text

PAGE_SIZE = 6
MAX_PAGES = 500

_ARTICLE_RE = re.compile(r"<article[^>]*>([\s\S]*?)</article>", re.I)
_JOB_LINK_RE = re.compile(
    r'href="(https?://[^"]+/JobDetail/(\d+))"[^>]*>\s*([\s\S]*?)\s*</a>', re.I)
_CITY_RE = re.compile(r'class="list-item-jobCity"[^>]*>([^<]+)', re.I)
_STATE_RE = re.compile(r'class="list-item-jobState"[^>]*>([^<]+)', re.I)
_COUNTRY_RE = re.compile(r'class="list-item-jobCountry"[^>]*>([^<]+)', re.I)
_TOTAL_RE = re.compile(r"of\s+(\d+)\s*$", re.M)
_TOTAL_PLUS_RE = re.compile(r"(\d+)\+\s*results", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _parse_token(token: str) -> tuple[str, str, str]:
    parts = token.split(":")
    if len(parts) < 3:
        raise ValueError(f"Avature token must be host:locale:portal, got {token!r}")
    return parts[0], parts[1], parts[2]


def _clean(text: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", text or "")).strip()


def _search_url(host: str, locale: str, portal: str, offset: int) -> str:
    base = f"https://{host}/{locale}/{portal}/SearchJobs/"
    params = f"?listFilterMode=1&folderRecordsPerPage={PAGE_SIZE}"
    if offset:
        params += f"&folderOffset={offset}"
    return base + params


def _parse_page(html_text: str) -> list[dict]:
    jobs: list[dict] = []
    for block in _ARTICLE_RE.findall(html_text):
        link_match = _JOB_LINK_RE.search(block)
        if not link_match:
            continue
        url, job_id, title_raw = link_match.groups()
        title = _clean(title_raw)
        if not title:
            continue
        parts = []
        for pat in (_CITY_RE, _STATE_RE, _COUNTRY_RE):
            m = pat.search(block)
            if m:
                parts.append(_clean(m.group(1)))
        location = ", ".join(p for p in parts if p)
        jobs.append({"title": title, "location": location, "url": url.split("?")[0], "job_id": job_id})
    return jobs


def _parse_total(html_text: str) -> int | None:
    plus = _TOTAL_PLUS_RE.search(html_text)
    if plus:
        return int(plus.group(1))
    for match in _TOTAL_RE.finditer(html_text):
        value = int(match.group(1))
        if value > 0:
            return value
    return None


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out = []
    for item in items:
        out.append(Posting(
            uid=f"avature:{slug}:{item['job_id']}",
            ats="avature", company=slug,
            title=item["title"], location=item["location"],
            url=item["url"], posted_at=None, description="",
            raw=item,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    host, locale, portal = _parse_token(token)
    items: list[dict] = []
    seen: set[str] = set()
    offset = 0
    expected = None
    for _ in range(MAX_PAGES):
        html_text = await get_text(client, _search_url(host, locale, portal, offset))
        if expected is None:
            expected = _parse_total(html_text)
        batch = _parse_page(html_text)
        if not batch:
            break
        for item in batch:
            if item["job_id"] not in seen:
                seen.add(item["job_id"])
                items.append(item)
        if expected and len(items) >= expected:
            break
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return parse(company.slug, items)
