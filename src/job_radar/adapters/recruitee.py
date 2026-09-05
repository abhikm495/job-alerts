from ..models import Company, Posting
from .base import get_json, strip_html, to_dt

API = "https://{token}.recruitee.com/api/offers/"


def _format_location(item: dict) -> str:
    loc = (item.get("location") or "").strip()
    if loc:
        return loc
    parts = [item.get("city"), item.get("country")]
    text = ", ".join(p for p in parts if p)
    if item.get("remote"):
        text = f"{text} (Remote)".strip(" ()") if text else "Remote"
    elif item.get("hybrid"):
        text = f"{text} (Hybrid)".strip(" ()") if text else "Hybrid"
    return text


def parse(slug: str, payload: dict) -> list[Posting]:
    out = []
    for item in payload.get("offers") or []:
        if (item.get("status") or "").lower() == "archived":
            continue
        oid = item.get("id")
        if oid is None:
            continue
        out.append(Posting(
            uid=f"recruitee:{slug}:{oid}",
            ats="recruitee", company=slug,
            title=item.get("title", "") or "",
            location=_format_location(item),
            url=item.get("careers_url") or "",
            posted_at=to_dt(item.get("published_at") or item.get("created_at")),
            description=strip_html(item.get("description") or ""),
            raw=item,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    payload = await get_json(client, API.format(token=token))
    return parse(company.slug, payload)
