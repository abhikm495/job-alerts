import re

from ..models import Company, Posting
from .base import get_json, strip_html, to_dt

API_BASE = "https://cg-jobstream-api.azurewebsites.net/api"
PAGE_SIZE = 100
MAX_PAGES = 100
_TAG_RE = re.compile(r"<[^>]+>")


def _locale_prefix(country_code: str) -> str:
    lang, _, region = country_code.lower().partition("-")
    if region:
        return f"{region}-{lang}"
    return country_code.lower()


def _job_url(item: dict, country_code: str) -> str:
    apply_url = item.get("apply_job_url")
    if apply_url:
        return apply_url
    ref = item.get("ref") or item.get("id") or ""
    source = (item.get("source") or "").lower()
    if ref and source:
        locale = _locale_prefix(country_code)
        return (
            f"https://www.capgemini.com/{locale}/careers/join-capgemini/job/"
            f"{ref}+{source.lower()}"
        )
    return "https://www.capgemini.com/careers/join-capgemini/job-search/"


def parse(slug: str, country_code: str, items: list[dict]) -> list[Posting]:
    out = []
    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        ref = item.get("ref") or item.get("id") or title
        desc = item.get("description_stripped") or strip_html(item.get("description") or "")
        posted = item.get("indexed_at") or item.get("created_at")
        out.append(Posting(
            uid=f"jobstream:{slug}:{ref}",
            ats="jobstream", company=slug,
            title=title,
            location=(item.get("location") or item.get("country_name") or "").strip(),
            url=_job_url(item, country_code),
            posted_at=to_dt(posted) if posted else None,
            description=desc,
            raw=item,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    country_code = (company.token or company.slug).strip()
    items: list[dict] = []
    page = 1
    total = None
    for _ in range(MAX_PAGES):
        url = f"{API_BASE}/job-search?country_code={country_code}&page={page}&size={PAGE_SIZE}"
        data = await get_json(client, url)
        if total is None:
            total = int(data.get("total") or 0)
        batch = data.get("data") or []
        if not batch:
            break
        items.extend(batch)
        if len(items) >= total or len(batch) < PAGE_SIZE:
            break
        page += 1
    return parse(company.slug, country_code, items)
