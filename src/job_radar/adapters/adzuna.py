"""Adzuna job search API — multi-country aggregator."""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlencode

import httpx

from ..models import Company, Posting
from .base import BACKOFF_BASE, BACKOFF_MAX, TIMEOUT, strip_html, to_dt

SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
PAGE_SIZE = 50
MAX_PAGES_DEFAULT = 5
MAX_DAYS_OLD_DEFAULT = 7
WHAT_DEFAULT = "software"
MAX_KEY_SLOTS = 5

SUPPORTED_COUNTRIES = frozenset({
    "au", "at", "be", "br", "ca", "fr", "de", "in", "it", "mx",
    "nl", "nz", "pl", "sg", "za", "es", "ch", "gb",
})


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _parse_credential_pair(raw: str) -> tuple[str, str] | None:
    """Parse ``app_id:app_key`` from ADZUNA_CREDENTIALS entries."""
    part = (raw or "").strip()
    if not part or ":" not in part:
        return None
    app_id, app_key = part.split(":", 1)
    app_id = app_id.strip()
    app_key = app_key.strip()
    if not app_id or not app_key:
        return None
    return app_id, app_key


def load_credentials() -> list[tuple[str, str]]:
    """Load up to 5 Adzuna API keys from the environment.

    One shared app id with multiple keys (typical):
      ADZUNA_APP_ID + ADZUNA_APP_KEY, ADZUNA_APP_KEY_2, ... ADZUNA_APP_KEY_5

    Per-slot app ids are optional overrides (ADZUNA_APP_ID_N) for mixed setups.
    Bulk fallback: ADZUNA_CREDENTIALS=id1:key1,id2:key2
    """
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(app_id: str, app_key: str) -> None:
        pair = (app_id.strip(), app_key.strip())
        if pair[0] and pair[1] and pair not in seen:
            seen.add(pair)
            out.append(pair)

    shared_id = os.environ.get("ADZUNA_APP_ID", "").strip()
    for slot in range(1, MAX_KEY_SLOTS + 1):
        suffix = "" if slot == 1 else f"_{slot}"
        app_key = os.environ.get(f"ADZUNA_APP_KEY{suffix}", "").strip()
        if not app_key:
            continue
        app_id = os.environ.get(f"ADZUNA_APP_ID{suffix}", "").strip() or shared_id
        if app_id:
            add(app_id, app_key)

    if not out:
        bulk = os.environ.get("ADZUNA_CREDENTIALS", "").strip()
        for entry in bulk.split(","):
            pair = _parse_credential_pair(entry)
            if pair:
                add(pair[0], pair[1])
    return out


class CredentialPool:
    """Round-robin pool of Adzuna API credentials (async-safe)."""

    def __init__(self, creds: list[tuple[str, str]]):
        if not creds:
            raise ValueError("CredentialPool requires at least one credential pair")
        self._creds = creds
        self._lock = asyncio.Lock()
        self._next = 0

    def __len__(self) -> int:
        return len(self._creds)

    async def start_index(self) -> int:
        async with self._lock:
            idx = self._next % len(self._creds)
            self._next += 1
            return idx

    def pair(self, index: int) -> tuple[str, str]:
        return self._creds[index % len(self._creds)]


_pool: CredentialPool | None = None


def _get_pool() -> CredentialPool | None:
    global _pool
    if _pool is None:
        creds = load_credentials()
        if creds:
            _pool = CredentialPool(creds)
    return _pool


def reset_pool() -> None:
    """Clear the cached credential pool (for tests)."""
    global _pool
    _pool = None


def _country_code(company: Company) -> str:
    """Resolve Adzuna ISO country code from wd_site, region, or slug suffix."""
    for raw in (company.wd_site, company.region, company.slug.rsplit("-", 1)[-1]):
        code = (raw or "").strip().lower()
        if code in ("india",):
            code = "in"
        elif code in ("germany",):
            code = "de"
        if code in SUPPORTED_COUNTRIES:
            return code
    return "de"


def _base_search_params(company: Company) -> dict:
    return {
        "what": (company.token or os.environ.get("ADZUNA_WHAT", WHAT_DEFAULT)).strip(),
        "results_per_page": PAGE_SIZE,
        "max_days_old": _env_int("ADZUNA_MAX_DAYS_OLD", MAX_DAYS_OLD_DEFAULT),
        "sort_by": "date",
        "sort_direction": "down",
    }


def _location(item: dict) -> str:
    loc = item.get("location") or {}
    return (loc.get("display_name") or "").strip()


def _title(item: dict) -> str:
    title = (item.get("title") or "").strip()
    employer = ((item.get("company") or {}).get("display_name") or "").strip()
    if employer and employer.lower() not in title.lower():
        return f"{employer}: {title}" if title else employer
    return title


def parse(slug: str, items: list[dict]) -> list[Posting]:
    out: list[Posting] = []
    for item in items:
        job_id = str(item.get("id") or "").strip()
        if not job_id:
            continue
        employer = ((item.get("company") or {}).get("display_name") or "").strip()
        out.append(Posting(
            uid=f"adzuna:{slug}:{job_id}",
            ats="adzuna",
            company=slug,
            title=_title(item),
            location=_location(item),
            url=(item.get("redirect_url") or "").strip(),
            posted_at=to_dt(item.get("created")),
            description=strip_html(item.get("description") or ""),
            raw={
                "id": job_id,
                "employer": employer,
                "category": ((item.get("category") or {}).get("label") or "").strip(),
            },
        ))
    return out


async def _search_page(client, country: str, base_params: dict, page: int) -> dict:
    pool = _get_pool()
    if pool is None:
        return {}
    start = await pool.start_index()
    headers = {"User-Agent": "job-radar/0.1", "Accept": "application/json"}
    last_resp: httpx.Response | None = None
    for offset in range(len(pool)):
        app_id, app_key = pool.pair(start + offset)
        params = {**base_params, "app_id": app_id, "app_key": app_key}
        query = urlencode(params)
        url = f"{SEARCH_URL.format(country=country, page=page)}?{query}"
        for attempt in range(3):
            resp = await client.get(url, headers=headers, timeout=TIMEOUT)
            last_resp = resp
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if (retry_after and retry_after.isdigit()) else BACKOFF_BASE * (2 ** attempt)
                await asyncio.sleep(min(wait, BACKOFF_MAX))
                break
            if resp.status_code in {500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(min(BACKOFF_BASE * (2 ** attempt), BACKOFF_MAX))
                continue
            if resp.is_success:
                return resp.json()
            resp.raise_for_status()
    if last_resp is not None:
        last_resp.raise_for_status()
    return {}


async def fetch(client, company: Company) -> list[Posting]:
    slug = company.slug
    if _get_pool() is None:
        return []
    base_params = _base_search_params(company)
    country = _country_code(company)
    max_pages = _env_int("ADZUNA_MAX_PAGES", MAX_PAGES_DEFAULT)
    items: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        payload = await _search_page(client, country, base_params, page)
        batch = payload.get("results") or []
        if not batch:
            break
        new = 0
        for item in batch:
            job_id = str(item.get("id") or "").strip()
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            items.append(item)
            new += 1
        if new == 0:
            break
        total = int(payload.get("count") or 0)
        if total and len(seen) >= total:
            break
    return parse(slug, items)
