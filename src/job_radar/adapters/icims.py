import re

from ..models import Company, Posting
from ._sitemap import base_url, collect_job_urls_from_sitemaps, normalize_host
from .base import get_text

MAX_JOBS = 8000
_JOB_PATH = re.compile(r"/jobs/\d+", re.I)


def parse(slug: str, urls: list[str]) -> list[Posting]:
    out = []
    for url in urls:
        job_id = url.rstrip("/").split("/")[-1].split("?")[0]
        out.append(Posting(
            uid=f"icims:{slug}:{job_id}",
            ats="icims", company=slug,
            title=f"Job {job_id}",
            location="", url=url,
            posted_at=None, description="",
            raw={"url": url},
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    host = normalize_host(token)
    urls = await collect_job_urls_from_sitemaps(client, base_url(host), job_path_hint="/jobs/")
    if not urls:
        try:
            xml = await get_text(client, f"{base_url(host)}/sitemap1.xml")
            urls = [u for u in re.findall(r"<loc>([^<]+)</loc>", xml) if _JOB_PATH.search(u)]
        except Exception:
            urls = []
    return parse(company.slug, urls[:MAX_JOBS])
