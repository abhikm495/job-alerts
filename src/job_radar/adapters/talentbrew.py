import json
import re
from html import unescape
from urllib.parse import urljoin

from ..models import Company, Posting
from .base import get_text

PAGE_SIZE = 100
MAX_PAGES = 100

_JOB_LINK = re.compile(
    r'<a class="sr-job-item__link" href="(?P<href>[^"]+)"[^>]*>\s*(?P<title>[^<]+?)\s*</a>', re.S)
_LOCATION = re.compile(r'sr-job-item__facet-icon sr-job-location">([^<]+)')
_TOTAL_RESULTS = re.compile(r'data-total-results="(\d+)"')
_TOTAL_PAGES = re.compile(r'data-total-pages="(\d+)"')
_META_TOTAL = re.compile(r'name="search-analytics-total-jobs"\s+content="(\d+)"', re.I)

_DEFAULT_CRITERIA = {
    "ActiveFacetID": 0, "Distance": 50, "RadiusUnitType": 0,
    "RecordsPerPage": PAGE_SIZE, "CurrentPage": 1, "TotalPages": 0,
    "TotalContentPages": 0, "Keywords": "", "Location": "",
    "Latitude": None, "Longitude": None, "ShowRadius": False,
    "FacetTerm": "", "FacetType": 0, "CustomFacetName": "",
    "FacetFilters": [], "SearchResultsModuleName": "Search Results",
    "SearchFiltersModuleName": "Search Filters", "SortCriteria": 5,
    "SortDirection": 1, "SearchType": 5, "CategoryFacetTerm": None,
    "CategoryFacetType": None, "LocationFacetTerm": None, "LocationFacetType": None,
    "KeywordType": "", "LocationType": "", "LocationPath": "",
    "OrganizationIds": "", "RefinedKeywords": [], "PostalCode": "",
    "ResultsType": 0, "fc": "", "fl": "", "fcf": "", "afc": "", "afl": "", "afcf": "",
    "IsPagination": "False",
}


def _base_url(token: str) -> str:
    host = token.strip().lower()
    if host.startswith("http"):
        return host.rstrip("/")
    return f"https://{host}"


def _search_path(token: str) -> str:
    host = token.strip()
    if "|" in host:
        _, path = host.split("|", 1)
        return path.strip("/")
    return "search-jobs"


def _parse_jobs(html: str, base: str) -> list[dict]:
    jobs: list[dict] = []
    for match in _JOB_LINK.finditer(html):
        block = html[match.start(): match.start() + 1200]
        title = unescape(re.sub(r"\s+", " ", match.group("title")).strip())
        href = match.group("href").strip()
        url = href if href.startswith("http") else urljoin(base + "/", href.lstrip("/"))
        loc_match = _LOCATION.search(block)
        location = unescape(loc_match.group(1).strip()) if loc_match else ""
        jobs.append({"title": title, "location": location, "url": url})
    return jobs


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out = []
    for i, item in enumerate(items):
        out.append(Posting(
            uid=f"talentbrew:{slug}:{item.get('url', i)}",
            ats="talentbrew", company=slug,
            title=item["title"], location=item["location"],
            url=item["url"], posted_at=None, description="",
            raw=item,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    base = _base_url(token)
    search_path = _search_path(token)
    headers = {
        "User-Agent": "job-radar/0.1",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }
    await get_text(client, f"{base}/{search_path.strip('/')}", headers=headers)
    all_items: list[dict] = []
    total_pages = MAX_PAGES
    for page in range(1, MAX_PAGES + 1):
        criteria = dict(_DEFAULT_CRITERIA)
        criteria["RecordsPerPage"] = PAGE_SIZE
        criteria["CurrentPage"] = page
        resp = await client.post(
            f"{base}/{search_path.strip('/')}/resultspost",
            content=json.dumps(criteria),
            headers=headers, timeout=30.0,
        )
        resp.raise_for_status()
        html = resp.json().get("results") or ""
        batch = _parse_jobs(html, base)
        total_m = _TOTAL_RESULTS.search(html)
        pages_m = _TOTAL_PAGES.search(html)
        if pages_m:
            total_pages = min(int(pages_m.group(1)), MAX_PAGES)
        elif total_m:
            total_pages = min((int(total_m.group(1)) + PAGE_SIZE - 1) // PAGE_SIZE, MAX_PAGES)
        if not batch:
            break
        all_items.extend(batch)
        if page >= total_pages:
            break
    seen: set[str] = set()
    unique = []
    for item in all_items:
        url = item.get("url") or ""
        if url and url not in seen:
            seen.add(url)
            unique.append(item)
    return parse(company.slug, unique)
