import re
from urllib.parse import quote

from ..models import Company, Posting
from .base import get_text

BASE_URL = "https://southasiacareers.deloitte.com"
PAGE_SIZE = 25
MAX_PAGES = 80

_JOB_ROW_RE = re.compile(r'<tr[^>]*class="[^"]*data-row[^"]*"[^>]*>([\s\S]*?)</tr>', re.I)
_JOB_LINK_RE = re.compile(r'href="(/job/[^"]+)"', re.I)
_TITLE_RE = re.compile(r'class="jobTitle"[^>]*>([\s\S]*?)</span>', re.I)
_LOCATION_RE = re.compile(r'class="jobLocation"[^>]*>([\s\S]*?)</span>', re.I)
_TOTAL_RE = re.compile(r"Results \d+ to \d+ of (\d+)", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _parse_token(token: str) -> tuple[str, str | None]:
    raw = (token or "718244").strip()
    if ":" in raw:
        category, location = raw.split(":", 1)
        return category.strip(), location.strip() or None
    return raw, None


def _clean(text: str) -> str:
    return _TAG_RE.sub(" ", text or "").strip()


def _listing_url(category: str, offset: int, location: str | None) -> str:
    path = f"/go/Deloitte-India/{category}/"
    if offset:
        path = f"/go/Deloitte-India/{category}/{offset}/"
    query = f"?q=&locationsearch={quote(location)}" if location else "?q="
    return f"{BASE_URL}{path}{query}"


def _parse_page(html: str) -> tuple[list[dict], int | None]:
    jobs: list[dict] = []
    for row in _JOB_ROW_RE.findall(html):
        link_match = _JOB_LINK_RE.search(row)
        if not link_match:
            continue
        path = link_match.group(1).replace("&amp;", "&")
        title = _clean(_TITLE_RE.search(row).group(1) if _TITLE_RE.search(row) else "")
        if not title:
            continue
        loc_m = _LOCATION_RE.search(row)
        location = _clean(loc_m.group(1) if loc_m else "")
        jobs.append({"title": title, "location": location, "url": f"{BASE_URL}{path}"})
    total_match = _TOTAL_RE.search(html)
    total = int(total_match.group(1)) if total_match else None
    return jobs, total


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out = []
    for item in items:
        out.append(Posting(
            uid=f"deloitte:{slug}:{item['url']}",
            ats="deloitte", company=slug,
            title=item["title"], location=item["location"],
            url=item["url"], posted_at=None, description="",
            raw=item,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    category, location = _parse_token(token)
    items: list[dict] = []
    seen: set[str] = set()
    offset = 0
    total = None
    headers = {"User-Agent": "job-radar/0.1", "Accept": "text/html"}
    for _ in range(MAX_PAGES):
        html = await get_text(client, _listing_url(category, offset, location), headers=headers)
        batch, page_total = _parse_page(html)
        if total is None:
            total = page_total
        if not batch:
            break
        for item in batch:
            if item["url"] not in seen:
                seen.add(item["url"])
                items.append(item)
        if total and len(items) >= total:
            break
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return parse(company.slug, items)
