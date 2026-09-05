from ..models import Company, Posting
from .base import get_json, strip_html, to_dt

LIST_TMPL = "https://{token}.bamboohr.com/careers/list"
CAREERS_TMPL = "https://{token}.bamboohr.com/careers"

_BROWSER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _format_location(job: dict) -> str:
    loc = job.get("atsLocation") or job.get("location") or {}
    if isinstance(loc, str):
        text = loc
    elif isinstance(loc, dict):
        parts = [loc.get("city"), loc.get("state"), loc.get("country")]
        text = ", ".join(p for p in parts if p)
    else:
        text = ""
    location_type = job.get("locationType")
    if location_type in (1, "1", "remote", "Remote"):
        text = f"{text} (Remote)".strip(" ()") if text else "Remote"
    elif location_type in (2, "2", "hybrid", "Hybrid"):
        text = f"{text} (Hybrid)".strip(" ()") if text else "Hybrid"
    return text


def parse(slug: str, payload: dict) -> list[Posting]:
    out = []
    for item in payload.get("result") or []:
        job_id = item.get("id")
        if job_id is None:
            continue
        url = f"https://{slug}.bamboohr.com/careers/{job_id}"
        out.append(Posting(
            uid=f"bamboohr:{slug}:{job_id}",
            ats="bamboohr", company=slug,
            title=item.get("jobOpeningName") or item.get("title") or "",
            location=_format_location(item), url=url,
            posted_at=to_dt(item.get("datePosted") or item.get("postedDate")),
            description=strip_html(item.get("jobOpeningDescription") or ""),
            raw=item,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    headers = dict(_BROWSER_HEADERS)
    headers["Referer"] = CAREERS_TMPL.format(token=token)
    await client.get(CAREERS_TMPL.format(token=token), headers=headers, timeout=30.0)
    resp = await client.get(LIST_TMPL.format(token=token), headers=headers, timeout=30.0)
    if "www.bamboohr.com" in str(resp.url) and f"{token}.bamboohr.com" not in str(resp.url):
        raise ValueError(f"subdomain '{token}' unavailable (redirected)")
    resp.raise_for_status()
    return parse(company.slug, resp.json())
