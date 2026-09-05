import xml.etree.ElementTree as ET

from ..models import Company, Posting
from ._html import personio_position_description
from .base import get_xml, to_dt

_TLDS = ("de", "com")


def _job_page(token: str, tld: str, job_id: str) -> str:
    return f"https://{token}.jobs.personio.{tld}/job/{job_id}"


def parse(slug: str, xml_text: str, tld: str = "de") -> list[Posting]:
    root = ET.fromstring(xml_text)
    out = []
    for pos in root.findall("position"):
        fields = {child.tag: (child.text or "").strip() for child in pos}
        job_id = fields.get("id") or ""
        if not (job_id or fields.get("name")):
            continue
        office = fields.get("office") or ""
        department = fields.get("department") or ""
        location = office
        if department and office:
            location = f"{office} · {department}"
        elif department:
            location = department
        url = _job_page(slug, tld, job_id) if job_id else f"https://{slug}.jobs.personio.{tld}/xml"
        out.append(Posting(
            uid=f"personio:{slug}:{job_id or fields.get('name')}",
            ats="personio", company=slug,
            title=fields.get("name") or "",
            location=location, url=url,
            posted_at=to_dt(fields.get("createdAt")),
            description=personio_position_description(pos),
            raw=fields,
        ))
    return out


async def _fetch_xml(client, token: str) -> tuple[str, str]:
    last_exc = None
    for tld in _TLDS:
        try:
            text = await get_xml(client, f"https://{token}.jobs.personio.{tld}/xml")
            if "<position>" in text or "<workzag-jobs>" in text:
                return text, tld
        except Exception as e:
            last_exc = e
    if last_exc:
        raise last_exc
    raise ValueError(f"Personio board not found for '{token}'")


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    xml_text, tld = await _fetch_xml(client, token)
    return parse(company.slug, xml_text, tld)
