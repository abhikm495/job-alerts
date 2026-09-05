import re

from ..models import Company, Posting
from .base import get_text

BASE_URL = "https://careers.techmahindra.com"
SEARCH_PAGE = f"{BASE_URL}/CurrentOpportunity.aspx"

_LOCATION_FILTERS: dict[str, frozenset[str]] = {
    "bengaluru": frozenset({"BENGALURU", "BANGALORE"}),
    "bangalore": frozenset({"BENGALURU", "BANGALORE"}),
    "hyderabad": frozenset({"HYDERABAD"}),
    "pune": frozenset({"PUNE"}),
    "chennai": frozenset({"CHENNAI"}),
    "mumbai": frozenset({"MUMBAI", "NAVI MUMBAI"}),
    "noida": frozenset({"NOIDA"}),
    "kolkata": frozenset({"KOLKATA"}),
}

_INPUT_RE = re.compile(r'<input[^>]+name="([^"]+)"[^>]*>', re.I)
_SELECT_RE = re.compile(r'<select[^>]+name="([^"]+)"[^>]*>([\s\S]*?)</select>', re.I)
_OPTION_RE = re.compile(r'<option[^>]+value="([^"]*)"', re.I)
_JOB_LINK_RE = re.compile(r'href="(JobDetails\.aspx\?JobCode=[^"]+)"[^>]*>\s*Apply/Shortlist', re.I)
_TITLE_RE = re.compile(
    r'<div style="margin-bottom: 5px; margin-top: 5px; font-size: 13px;">\s*([^<]+)', re.I)
_LOCATION_RE = re.compile(r"<b>Location</b>\s*:\s*([^<\n]+)", re.I)
_EXPERIENCE_RE = re.compile(r"<b>Experience</b>\s*:\s*([^<\n]+)", re.I)
_SKILLS_RE = re.compile(r"<b>Skill Set\s*</b>\s*:\s*([^<\n]+)", re.I)


def _parse_token(token: str) -> frozenset[str] | None:
    raw = (token or "in").strip().lower()
    if raw in {"", "in", "india", "it", "tech-mahindra"}:
        return None
    if raw in _LOCATION_FILTERS:
        return _LOCATION_FILTERS[raw]
    return frozenset({raw.upper()})


def _parse_form_fields(html: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in _INPUT_RE.finditer(html):
        tag = match.group(0)
        name = match.group(1)
        if re.search(r'type="submit"', tag, re.I):
            continue
        value_match = re.search(r'value="([^"]*)"', tag)
        fields[name] = value_match.group(1) if value_match else ""
    for name, body in _SELECT_RE.findall(html):
        selected = re.search(r'<option[^>]+selected[^>]+value="([^"]*)"', body, re.I)
        if selected:
            fields[name] = selected.group(1)
            continue
        first = _OPTION_RE.search(body)
        fields[name] = first.group(1) if first else ""
    return fields


def _parse_jobs(html: str) -> list[dict]:
    jobs: list[dict] = []
    for match in _JOB_LINK_RE.finditer(html):
        chunk = html[max(0, match.start() - 1200): match.start()]
        title_match = _TITLE_RE.search(chunk)
        location_match = _LOCATION_RE.search(chunk)
        experience_match = _EXPERIENCE_RE.search(chunk)
        skills_match = _SKILLS_RE.search(chunk)
        path = match.group(1).replace("&amp;", "&")
        jobs.append({
            "title": title_match.group(1).strip() if title_match else "",
            "location": location_match.group(1).strip() if location_match else "",
            "experience": experience_match.group(1).strip() if experience_match else "",
            "skills": skills_match.group(1).strip() if skills_match else "",
            "url": f"{BASE_URL}/{path}",
        })
    return jobs


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out = []
    for item in items:
        title = item.get("title") or ""
        if not title:
            continue
        desc = " · ".join(p for p in (item.get("skills"), item.get("experience")) if p)
        out.append(Posting(
            uid=f"techmahindra:{slug}:{item['url']}",
            ats="techmahindra", company=slug,
            title=title, location=item.get("location") or "",
            url=item.get("url") or SEARCH_PAGE,
            posted_at=None, description=desc,
            raw=item,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    allowed = _parse_token(token)
    headers = {"User-Agent": "job-radar/0.1", "Content-Type": "application/x-www-form-urlencoded"}
    html = await get_text(client, SEARCH_PAGE, headers=headers)
    data = _parse_form_fields(html)
    data["__EVENTTARGET"] = "ctl00$ContentPlaceHolder1$ddlCountry"
    data["__EVENTARGUMENT"] = ""
    data["ctl00$ContentPlaceHolder1$ddlCountry"] = "IND"
    resp = await client.post(SEARCH_PAGE, data=data, headers=headers, timeout=60.0)
    resp.raise_for_status()
    html = resp.text
    data = _parse_form_fields(html)
    data["ctl00$ContentPlaceHolder1$btnFreeSearch"] = "Search"
    data["ctl00$ContentPlaceHolder1$txtAdvanceSearch"] = ""
    data["ctl00$ContentPlaceHolder1$ddlCountry"] = "IND"
    data["ctl00$ContentPlaceHolder1$ddlState"] = "0"
    data["ctl00$ContentPlaceHolder1$ddlCity"] = "0"
    resp = await client.post(SEARCH_PAGE, data=data, headers=headers, timeout=60.0)
    resp.raise_for_status()
    jobs = _parse_jobs(resp.text)
    if allowed:
        jobs = [j for j in jobs if j.get("location", "").strip().upper() in allowed]
    return parse(company.slug, jobs)
