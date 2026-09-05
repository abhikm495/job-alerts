import json

from ..models import Company, Posting
from .base import to_dt

MAX_PAGES = 200


def _parse_token(token: str) -> tuple[str, str | None]:
    if ":" in token:
        domain, tenant = token.rsplit(":", 1)
        return domain.strip(), tenant.strip() or None
    return token.strip(), None


def _job_url(domain: str, slug: str) -> str:
    base = f"https://{domain.rstrip('/')}"
    if "coforge.com" in domain:
        return f"{base}/coforge/#!/job-view/{slug}"
    return f"{base}/#!/job-view/{slug}"


def parse(slug: str, domain: str, data: dict) -> list[Posting]:
    out = []
    for item in data.get("data") or []:
        src = item.get("_source") or item
        title = (src.get("jobTitle") or "").strip()
        if not title:
            continue
        location = (src.get("location") or src.get("officeLocation") or src.get("city") or "").strip()
        job_slug = (src.get("jobUrl") or "").strip()
        posted_raw = src.get("createdDate") or src.get("modifiedDate") or ""
        out.append(Posting(
            uid=f"zwayam:{slug}:{job_slug or title}",
            ats="zwayam", company=slug,
            title=title, location=location,
            url=_job_url(domain, job_slug) if job_slug else f"https://{domain}",
            posted_at=to_dt(posted_raw) if posted_raw else None,
            description=(src.get("skills") or src.get("departmentName") or "")[:300],
            raw=src,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    domain, tenant = _parse_token(token)
    jobs: list[Posting] = []
    start = 0
    page_size = 25
    for _ in range(MAX_PAGES):
        filter_cri = {
            "paginationStartNo": start,
            "selectedCall": "sort",
            "sortCriteria": {"name": "modifiedDate", "isAscending": False},
            "anyOfTheseWords": "",
        }
        headers = {"Accept": "application/json", "User-Agent": "job-radar/0.1"}
        if tenant:
            headers["TenantGroupId"] = tenant
        resp = await client.post(
            "https://public.zwayam.com/jobs/search",
            data={"filterCri": json.dumps(filter_cri), "domain": domain},
            headers=headers, timeout=60.0,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") not in (None, 200):
            raise ValueError(payload.get("message") or "search failed")
        data = payload.get("data") or {}
        batch = data.get("data") or []
        if not batch:
            break
        jobs.extend(parse(company.slug, domain, data))
        cfg = data.get("facetedSearchConfig") or {}
        page_size = int(cfg.get("paginationHowMuch") or len(batch) or 25)
        if len(batch) < page_size:
            break
        start += page_size
    return jobs
