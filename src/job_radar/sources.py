import asyncio

import httpx

from .adapters import (amazonjobs, ashby, avature, bamboohr, beesite, breezy, deloitte,
                       eightfold, googlecareers, greenhouse, higher_gs, icims, infosys,
                       join_com, jobstream, lever, linkedin, mercedes, oracle, personio,
                       phenom, publicissapient, recruitee, ripplehire, simplify,
                       smartrecruiters, successfactors, talentbrew, tcs_ibegin, techmahindra,
                       workable, workday, zwayam)
from .adapters.base import TIMEOUT
from .models import Company, Posting

ADAPTERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "workday": workday,
    "smartrecruiters": smartrecruiters,
    "simplify": simplify,
    "workable": workable,
    "oracle": oracle,
    "googlecareers": googlecareers,
    "amazonjobs": amazonjobs,
    "personio": personio,
    "recruitee": recruitee,
    "eightfold": eightfold,
    "ripplehire": ripplehire,
    "zwayam": zwayam,
    "bamboohr": bamboohr,
    "join_com": join_com,
    "breezy": breezy,
    "phenom": phenom,
    "successfactors": successfactors,
    "icims": icims,
    "avature": avature,
    "talentbrew": talentbrew,
    "linkedin": linkedin,
    "techmahindra": techmahindra,
    "deloitte": deloitte,
    "mercedes": mercedes,
    "beesite": beesite,
    "higher_gs": higher_gs,
    "jobstream": jobstream,
    "infosys": infosys,
    "tcs_ibegin": tcs_ibegin,
    "publicissapient": publicissapient,
}


async def _fetch_one(client, sem, company, errors):
    adapter = ADAPTERS.get(company.ats)
    if adapter is None:
        errors.append((company.slug, repr(Exception(f"no adapter for ats={company.ats}"))))
        return company, [], "no-adapter"
    async with sem:
        try:
            posts = await adapter.fetch(client, company)
            status = "ok" if posts else "empty"
            return company, posts, status
        except Exception as e:
            errors.append((company.slug, repr(e)))
            return company, [], "error"


async def fetch_all(companies, *, concurrency=45, client=None):
    sem = asyncio.Semaphore(concurrency)
    errors: list[tuple[str, str]] = []
    owns = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        results = await asyncio.gather(
            *[_fetch_one(client, sem, c, errors) for c in companies]
        )
    finally:
        if owns:
            await client.aclose()
    board_status = [(c, status, len(posts)) for c, posts, status in results]
    postings = [p for _c, posts, _s in results for p in posts]
    return postings, errors, board_status


ENRICHERS = {"workday", "smartrecruiters", "oracle", "join_com", "breezy"}


async def enrich_postings(postings, cmap, *, concurrency=10, client=None):
    """Fill in descriptions for the given postings (typically the survivors) whose
    adapter needs a second call. Returns a new list in the same order; failures keep
    the original posting. No-op for adapters that already include descriptions."""
    targets = [p for p in postings if p.ats in ENRICHERS and not p.description]
    if not targets:
        return list(postings)

    sem = asyncio.Semaphore(concurrency)
    owns = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)

    async def one(p):
        company = cmap.get((p.ats, p.company))
        if company is None:
            return p
        adapter = ADAPTERS.get(p.ats)
        if adapter is None or not hasattr(adapter, "enrich"):
            return p
        async with sem:
            try:
                return await adapter.enrich(client, p, company)
            except Exception:
                return p

    try:
        enriched = await asyncio.gather(*[one(p) for p in targets])
    finally:
        if owns:
            await client.aclose()

    by_uid = {orig.uid: new for orig, new in zip(targets, enriched)}
    return [by_uid.get(p.uid, p) for p in postings]
