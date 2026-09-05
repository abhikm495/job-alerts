import json
from dataclasses import replace

from ..models import Company, Posting
from .base import to_dt

PAGE_SIZE = 500


def _parse_token(token: str) -> tuple[str, str, str | None]:
    parts = token.split(":")
    if len(parts) < 2:
        raise ValueError(f"RippleHire token must be host:portal_token[:geo], got {token!r}")
    host = parts[0]
    portal_token = parts[1]
    geo = parts[2] if len(parts) > 2 and parts[2] else None
    return host, portal_token, geo


def _job_url(host: str, portal_token: str, job_seq: str) -> str:
    return (
        f"https://{host}/candidate/?token={portal_token}"
        f"&lang=en&source=CAREERSITE#detail/job/{job_seq}"
    )


def parse(slug: str, host: str, portal_token: str, payload: dict) -> list[Posting]:
    out = []
    for item in payload.get("jobVoList") or []:
        title = (item.get("jobTitle") or "").strip()
        if not title:
            continue
        job_seq = str(item.get("jobSeq") or "")
        location = (item.get("jobLocation") or item.get("jobLocationList") or "").strip()
        posted_raw = item.get("jobPostingDate") or item.get("openDate") or ""
        out.append(Posting(
            uid=f"ripplehire:{slug}:{job_seq or title}",
            ats="ripplehire", company=slug,
            title=title, location=location,
            url=_job_url(host, portal_token, job_seq) if job_seq else f"https://{host}/candidate/",
            posted_at=to_dt(posted_raw) if posted_raw else None,
            description=(item.get("jobDesc") or "")[:500],
            raw=item,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    host, portal_token, geo = _parse_token(token)
    params = {
        "page": 0, "search": "*:*", "token": portal_token,
        "source": "CAREERSITE", "pagesize": PAGE_SIZE,
    }
    if geo:
        params["geo"] = geo
    data = {"careerSiteUrlParams": json.dumps(params), "lang": "en"}
    resp = await client.post(
        f"https://{host}/candidate/candidatejobsearch",
        data=data,
        headers={"User-Agent": "job-radar/0.1", "Accept": "application/json"},
        timeout=60.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    return parse(company.slug, host, portal_token, payload)
