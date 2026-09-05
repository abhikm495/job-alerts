"""Convert job-automation/companies.yaml into a job-radar seed CSV.

Reads the nested job-automation watch-list, keeps only ATS types that
job-radar already supports, converts tokens to the seed CSV format, and
writes data/seed_job_automation.csv.

Run from the repo root:
    python scripts/import_job_automation.py
    python -m job_radar.seed data/seed_job_automation.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

# job-automation ATS -> job-radar seed ATS
ATS_MAP = {
    "greenhouse": "greenhouse",
    "lever": "lever",
    "ashby": "ashby",
    "smartrecruiters": "smartrecruiters",
    "workable": "workable",
    "workday": "workday",
    "oracle_hcm": "oracle",
}

SRC = Path("job-automation/companies.yaml")
OUT = Path("data/seed_job_automation.csv")


def _oracle_slug(host: str) -> str | None:
    """Return Fusion host code for oracle adapter, or None if unsupported."""
    host = host.strip().lower()
    suffix = ".oraclecloud.com"
    if not host.endswith(suffix):
        return None
    slug = host[: -len(suffix)]
    return slug or None


def convert(company: dict) -> str | None:
    """Return one seed CSV line, or None to skip."""
    ja_ats = (company.get("ats") or "").lower()
    ats = ATS_MAP.get(ja_ats)
    if ats is None:
        return None

    token = (company.get("token") or "").strip()
    if not token:
        return None

    tier = "target"

    if ats == "workday":
        parts = token.split(":")
        if len(parts) != 3 or not all(parts):
            return None
        slug, wd_host, wd_site = parts
        return f"{slug},{ats},{tier},{wd_host},{wd_site}"

    if ats == "oracle":
        if ":" not in token:
            return None
        host, site = token.rsplit(":", 1)
        slug = _oracle_slug(host)
        if not slug or not site:
            return None
        return f"{slug},{ats},{tier},{site}"

    # slug-only ATS: preserve SmartRecruiters casing, lower others for consistency
    slug = token if ats == "smartrecruiters" else token
    return f"{slug},{ats},{tier}"


def main() -> int:
    if not SRC.exists():
        print(f"error: {SRC} not found (run from feed-pipeline repo root)", file=sys.stderr)
        return 1

    data = yaml.safe_load(SRC.read_text())
    sections = data.get("sections") or []
    lines: list[str] = [
        "# Imported from job-automation/companies.yaml",
        "# slug,ats[,tier]  |  workday: slug,workday,tier,wd_host,wd_site",
        "#                  |  oracle: slug,oracle,tier,site",
    ]
    seen: set[tuple[str, str]] = set()
    skipped = 0

    for section in sections:
        for company in section.get("companies") or []:
            line = convert(company)
            if line is None:
                skipped += 1
                continue
            slug, ats = line.split(",", 2)[0], line.split(",", 2)[1]
            key = (ats, slug.lower())
            if key in seen:
                continue
            seen.add(key)
            lines.append(line)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {len(lines) - 3} rows to {OUT} (skipped {skipped} unsupported/malformed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
