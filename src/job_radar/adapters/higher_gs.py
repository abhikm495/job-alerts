from ..models import Company, Posting
from .base import get_json

GRAPHQL_URL = "https://api-higher.gs.com/gateway/api/v1/graphql"
PAGE_SIZE = 20
MAX_PAGES = 60

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://higher.gs.com",
    "Referer": "https://higher.gs.com/results",
    "User-Agent": "job-radar/0.1",
}

_QUERY = """
query GetRoles($searchQueryInput: RoleSearchQueryInput!) {
  roleSearch(searchQueryInput: $searchQueryInput) {
    totalCount
    items {
      roleId
      jobTitle
      jobFunction
      locations { city state country primary }
      externalSource { sourceId }
    }
  }
}
"""


def _format_location(locations: list[dict]) -> str:
    if not locations:
        return ""
    primary = next((loc for loc in locations if loc.get("primary")), locations[0])
    parts = [primary.get("city"), primary.get("state"), primary.get("country")]
    return ", ".join(p for p in parts if p)


def _job_url(source_id: str) -> str:
    if source_id:
        return f"https://higher.gs.com/roles/{source_id}"
    return "https://higher.gs.com/results"


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out = []
    for item in items:
        rid = item.get("roleId")
        if rid is None:
            continue
        source_id = ((item.get("externalSource") or {}).get("sourceId")) or ""
        out.append(Posting(
            uid=f"higher_gs:{slug}:{rid}",
            ats="higher_gs", company=slug,
            title=item.get("jobTitle", "") or "",
            location=_format_location(item.get("locations") or []),
            url=_job_url(source_id),
            posted_at=None,
            description=item.get("jobFunction") or "",
            raw=item,
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    items: list[dict] = []
    page_number = 0
    while page_number < MAX_PAGES:
        variables = {
            "searchQueryInput": {
                "page": {"pageSize": PAGE_SIZE, "pageNumber": page_number},
                "sort": {"sortStrategy": "RELEVANCE", "sortOrder": "DESC"},
                "filters": [],
                "experiences": ["EARLY_CAREER", "PROFESSIONAL"],
                "searchTerm": "",
            }
        }
        resp = await client.post(
            GRAPHQL_URL,
            json={"query": _QUERY, "variables": variables},
            headers=_HEADERS, timeout=30.0,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise ValueError(payload["errors"][0].get("message", "GraphQL error"))
        role_search = (payload.get("data") or {}).get("roleSearch") or {}
        batch = role_search.get("items") or []
        if not batch:
            break
        items.extend(batch)
        total = role_search.get("totalCount") or 0
        page_number += 1
        if page_number * PAGE_SIZE >= total:
            break
    return parse(company.slug, items)
