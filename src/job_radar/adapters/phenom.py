from ..models import Company, Posting
from ._sitemap import (
    base_url, collect_job_urls_from_sitemaps, normalize_host,
    parse_phenom_job_url, slug_to_title,
)

MAX_JOBS = 8000
PHENOM_JOB_HINTS = ("/job/", "job-detail", "open-positions/job-detail")


def parse(slug: str, urls: list[str]) -> list[Posting]:
    out = []
    for url in urls:
        title, location = parse_phenom_job_url(url)
        if not title:
            title = slug_to_title(url.rstrip("/").split("/")[-1])
        out.append(Posting(
            uid=f"phenom:{slug}:{url}",
            ats="phenom", company=slug,
            title=title, location=location, url=url,
            posted_at=None, description="",
            raw={"url": url},
        ))
    return out


async def fetch(client, company: Company) -> list[Posting]:
    token = company.token or company.slug
    host = normalize_host(token)
    urls = await collect_job_urls_from_sitemaps(
        client, base_url(host), job_path_hint=PHENOM_JOB_HINTS,
    )
    return parse(company.slug, urls[:MAX_JOBS])
