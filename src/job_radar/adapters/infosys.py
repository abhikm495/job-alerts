from ..models import Company, Posting
from .base import get_json, to_dt

DEFAULT_BASE = "https://intapgateway.infosysapps.com/careersci/search/intapjbsrch/"
JOB_URL = "https://career.infosys.com/jobdesc?jobReferenceCode={reference_code}&sourceId={source_id}"
_HEADERS = {
    "Origin": "https://career.infosys.com",
    "Referer": "https://career.infosys.com/joblist",
    "Accept": "application/json",
    "User-Agent": "job-radar/0.1",
}


def _parse_token(token: str) -> tuple[str, str]:
    raw = token.strip()
    if "://" in raw:
        base, _, source_id = raw.partition(":")
        if not base.endswith("/"):
            base += "/"
        return base, source_id or "1"
    return DEFAULT_BASE, raw or "1"


def _description(item: dict) -> str:
    parts = [
        item.get("postingDescription") or "",
        item.get("rolesResponsibilities") or "",
        item.get("technicalRequirement") or "",
        item.get("additionalResponsibility") or "",
    ]
    return "\n".join(p.strip() for p in parts if p and p.strip())


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out = []
    for item in items:
        title = (item.get("postingTitle") or item.get("roleDesignation") or "").strip()
        if not title:
            continue
        ref = item.get("referenceCode") or ""
        source_id = item.get("sourceId") or 1
        if ref:
            url = JOB_URL.format(reference_code=ref, source_id=source_id)
        elif item.get("postingId"):
            url = f"https://career.infosys.com/jobdesc?postingId={item['postingId']}"
        else:
            url = "https://career.infosys.com/joblist"
        out.append(Posting(
            uid=f"infosys:{slug}:{ref or item.get('postingId') or title}",
            ats="infosys", company=slug,
            title=title,
            location=(item.get("location") or item.get("country") or "").strip(),
            url=url,
            posted_at=to_dt(item.get("createdOn")),
            description=_description(item),
            raw=item,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    base, source_id = _parse_token(token)
    resp = await client.get(
        f"{base}getCareerSearchJobs",
        params={"sourceId": source_id, "searchText": "ALL"},
        headers=_HEADERS, timeout=30.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    items = payload if isinstance(payload, list) else []
    return parse(company.slug, items)
