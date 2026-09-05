from ..models import Company, Posting
from .base import get_json, to_dt

BASE_URL = "https://careers.publicissapient.com"
SEARCH_URL = f"{BASE_URL}/bin/ps-redesign/careersJobsearch"
PAGE_SIZE = 100
MAX_PAGES = 20


def parse(slug: str, country: str, docs: list[dict]) -> list[Posting]:
    out = []
    for item in docs:
        title = (item.get("name") or "").strip()
        if not title:
            continue
        detail = (item.get("jobDetailUrl") or item.get("jobUrl") or "").strip()
        url = f"{BASE_URL}{detail}" if detail.startswith("/") else detail or BASE_URL
        location = (item.get("displayLocation") or item.get("city") or country).strip()
        posted_raw = item.get("releasedDate") or ""
        out.append(Posting(
            uid=f"publicissapient:{slug}:{detail or title}",
            ats="publicissapient", company=slug,
            title=title, location=location, url=url,
            posted_at=to_dt(posted_raw) if posted_raw else None,
            description=(item.get("teams") or item.get("psCraft") or "")[:200],
            raw=item,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    country = (company.token or company.slug or "India").strip()
    docs: list[dict] = []
    start = 0
    total = None
    for _ in range(MAX_PAGES):
        url = (
            f"{SEARCH_URL}?searchType=/search&lang=en&q=*&country={country}"
            f"&start={start}&rows={PAGE_SIZE}"
        )
        data = (await get_json(client, url)).get("response") or {}
        if total is None:
            total = int(data.get("numFound") or 0)
        batch = data.get("docs") or []
        if not batch:
            break
        docs.extend(batch)
        start += len(batch)
        if start >= total or len(batch) < PAGE_SIZE:
            break
    return parse(company.slug, country, docs)
