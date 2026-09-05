import re
from html import unescape

from ..models import Company, Posting
from .base import get_text, to_dt

COMPANY_JOBS_URL = "https://www.linkedin.com/company/{slug}/jobs/"
_JOB_SPLIT = re.compile(r'data-entity-urn="urn:li:jobPosting:(\d+)"')


def parse(slug: str, html: str) -> list[Posting]:
    parts = _JOB_SPLIT.split(html)
    out = []
    for i in range(1, len(parts), 2):
        job_id = parts[i]
        block = parts[i + 1] if i + 1 < len(parts) else ""
        title_m = re.search(r'class="sr-only">\s*([^<]+)', block)
        if not title_m:
            title_m = re.search(r"base-main-card__title[^>]*>\s*([^<]+)", block, re.S)
        if not title_m:
            continue
        loc_m = re.search(r"main-job-card__location[^>]*>\s*([^<]+)", block)
        if not loc_m:
            loc_m = re.search(r"job-search-card__location[^>]*>\s*([^<]+)", block)
        url_m = re.search(r'href="(https?://[^"]+/jobs/view/[^"?]+)', block)
        date_m = re.search(r'datetime="(\d{4}-\d{2}-\d{2})"', block)
        title = unescape(re.sub(r"\s+", " ", title_m.group(1)).strip())
        location = unescape(loc_m.group(1).strip()) if loc_m else ""
        url = url_m.group(1) if url_m else f"https://www.linkedin.com/jobs/view/{job_id}"
        posted_at = to_dt(date_m.group(1)) if date_m else None
        out.append(Posting(
            uid=f"linkedin:{slug}:{job_id}",
            ats="linkedin", company=slug,
            title=title, location=location, url=url,
            posted_at=posted_at, description="",
            raw={"job_id": job_id},
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    slug = company.token or company.slug
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = await client.get(COMPANY_JOBS_URL.format(slug=slug), headers=headers, timeout=30.0)
    if resp.status_code == 404:
        resp.raise_for_status()
    resp.raise_for_status()
    return parse(company.slug, resp.text)
