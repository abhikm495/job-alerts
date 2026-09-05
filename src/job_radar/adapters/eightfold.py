from datetime import datetime, timezone

from ..models import Company, Posting
from .base import get_json, from_ms

PAGE_SIZE = 10
MAX_PAGES = 200


def _parse_token(token: str) -> tuple[str, str]:
    host, domain = token.rsplit(":", 1)
    if not host or not domain:
        raise ValueError(f"Eightfold token must be host:domain, got {token!r}")
    return host, domain


def _posted_at(position: dict) -> datetime | None:
    ts = position.get("postedTs") or position.get("creationTs")
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


def _job_url(host: str, position: dict) -> str:
    path = position.get("positionUrl") or ""
    if path.startswith("http"):
        return path
    if path.startswith("/"):
        return f"https://{host}{path}"
    job_id = position.get("id")
    return f"https://{host}/careers/job/{job_id}"


def parse(slug: str, host: str, data: dict) -> list[Posting]:
    out = []
    for item in data.get("positions") or []:
        jid = item.get("id")
        if jid is None:
            continue
        locations = item.get("locations") or item.get("standardizedLocations") or []
        location = "; ".join(locations) if isinstance(locations, list) else str(locations)
        out.append(Posting(
            uid=f"eightfold:{slug}:{jid}",
            ats="eightfold", company=slug,
            title=item.get("name") or "",
            location=location,
            url=_job_url(host, item),
            posted_at=_posted_at(item),
            description=item.get("department") or "",
            raw=item,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    host, domain = _parse_token(token)
    all_posts: list[Posting] = []
    start = 0
    total = None
    for _ in range(MAX_PAGES):
        url = f"https://{host}/api/pcsx/search?domain={domain}&start={start}&num={PAGE_SIZE}"
        payload = await get_json(client, url)
        block = payload.get("data") or {}
        if total is None:
            total = int(block.get("count") or 0)
        batch = block.get("positions") or []
        if not batch:
            break
        all_posts.extend(parse(company.slug, host, block))
        start += len(batch)
        if start >= (total or 0):
            break
    return all_posts
