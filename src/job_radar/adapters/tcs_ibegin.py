from ..models import Company, Posting
from .base import get_text

BASE_URL = "https://ibegin.tcsapps.com/candidate"
SEARCH_URL = f"{BASE_URL}/api/v1/jobs/searchJ"
JOBS_PAGE = f"{BASE_URL}/jobs"
PAGE_SIZE = 10
MAX_PAGES = 400
_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://ibegin.tcsapps.com",
    "Referer": JOBS_PAGE,
    "User-Agent": "job-radar/0.1",
}


def _parse_token(token: str) -> str | None:
    raw = (token or "in").strip().lower()
    if raw in {"", "in", "india", "tcs-ibegin"}:
        return None
    if raw in {"bengaluru", "bangalore", "blr"}:
        return "Bengaluru"
    return token.strip()


def _payload(page: str, city: str | None) -> dict:
    return {
        "jobTitle": None, "jobCity": city, "jobFunction": None,
        "jobExperience": None, "jobSkill": None, "pageNumber": page,
        "userText": "", "jobTitleOrder": None, "jobCityOrder": None,
        "jobFunctionOrder": None, "jobExperienceOrder": None,
        "applyByOrder": None, "regular": True, "walkin": True,
    }


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out = []
    for item in items:
        title = (item.get("jobTitle") or "").strip()
        if not title:
            continue
        job_id = item.get("id") or ""
        skills = (item.get("skills") or "").strip()
        experience = (item.get("experience") or "").strip()
        out.append(Posting(
            uid=f"tcs_ibegin:{slug}:{job_id or title}",
            ats="tcs_ibegin", company=slug,
            title=title,
            location=(item.get("location") or "").strip(),
            url=f"{BASE_URL}/jobs/{job_id}" if job_id else JOBS_PAGE,
            posted_at=None,
            description=" · ".join(p for p in (skills, experience) if p),
            raw=item,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    city = _parse_token(token)
    await client.get(JOBS_PAGE, headers=_HEADERS, timeout=30.0)
    items: list[dict] = []
    total = None
    for page_num in range(1, MAX_PAGES + 1):
        resp = await client.post(
            SEARCH_URL, json=_payload(str(page_num), city),
            headers=_HEADERS, timeout=30.0,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("result") != "Y":
            raise ValueError(payload.get("message") or "search failed")
        data = payload.get("data") or {}
        if total is None:
            total = int(data.get("totalJobs") or 0)
        batch = data.get("jobs") or []
        if not batch:
            break
        items.extend(batch)
        if total and len(items) >= total:
            break
        if len(batch) < PAGE_SIZE:
            break
    return parse(company.slug, items)
