"""Convert job-automation/companies.yaml into a job-radar seed CSV.

Reads the nested job-automation watch-list, keeps supported ATS types,
converts tokens to the seed CSV format, and writes data/seed_job_automation.csv.

Run from the repo root:
    python scripts/import_job_automation.py
    python -m job_radar.seed data/seed_job_automation.csv
    python -m job_radar.validate --prune
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ATS_MAP = {
    "greenhouse": "greenhouse",
    "lever": "lever",
    "ashby": "ashby",
    "smartrecruiters": "smartrecruiters",
    "workable": "workable",
    "workday": "workday",
    "oracle_hcm": "oracle",
    "personio": "personio",
    "recruitee": "recruitee",
    "eightfold": "eightfold",
    "ripplehire": "ripplehire",
    "zwayam": "zwayam",
    "bamboohr": "bamboohr",
    "join_com": "join_com",
    "breezy": "breezy",
    "phenom": "phenom",
    "successfactors": "successfactors",
    "icims": "icims",
    "avature": "avature",
    "talentbrew": "talentbrew",
    "linkedin": "linkedin",
    "techmahindra": "techmahindra",
    "deloitte": "deloitte",
    "mercedes": "mercedes",
    "beesite": "beesite",
    "higher_gs": "higher_gs",
    "jobstream": "jobstream",
    "infosys": "infosys",
    "tcs_ibegin": "tcs_ibegin",
    "publicissapient": "publicissapient",
}

SKIP_ATS = {"custom", "taleo"}

INDIA_SECTIONS = {"bengaluru", "remote_india"}
GERMANY_SECTIONS = {"europe_germany"}

SRC = Path("job-automation/companies.yaml")
OUT = Path("data/seed_job_automation.csv")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "company"


def _oracle_slug(host: str) -> str | None:
    host = host.strip().lower()
    suffix = ".oraclecloud.com"
    if not host.endswith(suffix):
        return None
    slug = host[: -len(suffix)]
    return slug or None


def _region_for_section(section_id: str, section_region: str) -> str | None:
    if section_id in INDIA_SECTIONS or section_region == "india":
        return "india"
    if section_id in GERMANY_SECTIONS or section_region == "germany":
        return "germany"
    return None


def _base_slug(token: str, ats: str) -> str:
    if ats in {"phenom", "successfactors", "icims", "talentbrew"}:
        host = token.strip().lower()
        if host.startswith("http"):
            host = host.split("//", 1)[-1].split("/", 1)[0]
        return _slugify(host.split(".")[0] if "." in host else host)
    if ats == "workday":
        return token.split(":")[0]
    if ats == "oracle":
        host = token.rsplit(":", 1)[0]
        return _oracle_slug(host) or _slugify(host)
    if ats in {"eightfold", "ripplehire", "avature", "mercedes", "zwayam"}:
        return _slugify(token.split(":")[0].split(".")[0])
    if ats == "higher_gs":
        return "goldman-sachs"
    if ats == "jobstream":
        return f"capgemini-{token.replace('-', '')}"
    if ats == "infosys":
        return "infosys"
    if ats == "tcs_ibegin":
        return "tcs"
    if ats == "techmahindra":
        return "techmahindra"
    if ats == "publicissapient":
        return "publicissapient"
    if ats == "deloitte":
        return "deloitte"
    if ats == "beesite":
        return token.strip().lower()
    return _slugify(token.split(":")[0] if ":" in token else token)


def convert(company: dict, section_id: str, section_region: str) -> str | None:
    ja_ats = (company.get("ats") or "").lower()
    if ja_ats in SKIP_ATS:
        return None
    ats = ATS_MAP.get(ja_ats)
    if ats is None:
        return None

    token = (company.get("token") or "").strip()
    if not token:
        return None

    slug = _base_slug(token, ats)
    tier = "target"
    region = _region_for_section(section_id, section_region or "")

    if ats == "workday":
        parts = token.split(":")
        if len(parts) != 3 or not all(parts):
            return None
        _, wd_host, wd_site = parts
        return f"{slug},{ats},{tier},{wd_host},{wd_site}"

    if ats == "oracle":
        if ":" not in token:
            return None
        host, site = token.rsplit(":", 1)
        oslug = _oracle_slug(host)
        if not oslug or not site:
            return None
        return f"{oslug},{ats},{tier},{site}"

    # slug-only or token in 4th column
    needs_token = ats in {
        "eightfold", "ripplehire", "zwayam", "avature", "mercedes",
        "jobstream", "infosys", "tcs_ibegin", "techmahindra", "deloitte",
        "publicissapient", "beesite", "phenom", "successfactors", "icims",
        "talentbrew", "higher_gs",
    } or token != slug
    if needs_token:
        line = f"{slug},{ats},{tier},{token}"
    else:
        line = f"{slug},{ats},{tier}"
    if region:
        line = f"{line},{region}"
    return line


def main() -> int:
    if not SRC.exists():
        print(f"error: {SRC} not found (run from feed-pipeline repo root)", file=sys.stderr)
        return 1

    data = yaml.safe_load(SRC.read_text())
    sections = data.get("sections") or []
    lines: list[str] = [
        "# Imported from job-automation/companies.yaml",
        "# slug,ats,tier[,token][,region]",
        "# workday: slug,workday,tier,wd_host,wd_site",
        "# oracle: slug,oracle,tier,site",
    ]
    seen: set[tuple[str, str]] = set()
    skipped = 0

    for section in sections:
        section_id = section.get("id") or ""
        section_region = section.get("region") or ""
        for company in section.get("companies") or []:
            line = convert(company, section_id, section_region)
            if line is None:
                skipped += 1
                continue
            slug = line.split(",", 1)[0]
            ats = line.split(",", 3)[1]
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
