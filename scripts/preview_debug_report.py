"""Post a sample debug run report to Discord (preview the new format).

Run from repo root:
    .venv/bin/python scripts/preview_debug_report.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_radar.config import Settings
from job_radar.notify import RegionalDiscordNotifier
from job_radar.report import BoardResult, RunReport, ScoredJobSummary


def _sample_report() -> RunReport:
    now = datetime.now(timezone.utc)
    report = RunReport(
        started_at=now,
        duration_sec=431.7,
        boards_total=508,
        postings_fetched=40307,
        new=2757,
        primed=17524,
        survivors=150,
        deferred=2396,
        scored=150,
        score_errors=0,
        llm_provider="gemini",
        ping_threshold=70,
        digest_threshold=55,
        high_score=80,
        score_cap=150,
        filter_rejects={"freshness": 3, "title_exclude": 69, "title_include": 139},
        notifications={
            "india": {"pinged": 0, "digest": 2},
            "germany": {"pinged": 1, "digest": 4},
            "other": {"pinged": 0, "digest": 1},
        },
    )

    # Board samples mirroring a real run
    samples = [
        ("greenhouse", "stripe", "ok", 142, None),
        ("personio", "alteos", "ok", 8, None),
        ("join_com", "onfuel", "error", 0, "HTTPStatusError('404 Not Found' for join.com/companies/onfuel)"),
        ("personio", "gymondo-gmbh", "error", 0, "HTTPStatusError('307 Temporary Redirect' ...)"),
        ("eightfold", "morganstanley", "error", 0, "HTTPStatusError('429 TOO MANY REQUESTS' ...)"),
        ("join_com", "acme", "empty", 0, None),
        ("recruitee", "atheneum", "ok", 12, None),
        ("lever", "ramp", "ok", 34, None),
    ]
    for ats, slug, status, jobs, err in samples:
        report.add_board(ats, slug, status, jobs, err)

    report.scored_jobs = [
        ScoredJobSummary("Senior Software Engineer", "stripe", "greenhouse", 78,
                         "Strong React/TS match", "Berlin, Germany", "https://example.com/1"),
        ScoredJobSummary("Frontend Developer", "alteos", "personio", 62,
                         "Good fit, mid-level", "Munich", "https://example.com/2"),
        ScoredJobSummary("Platform Engineer", "ramp", "lever", 54,
                         "Backend-heavy but transferable", "Remote DE", "https://example.com/3"),
        ScoredJobSummary("DevOps Engineer", "acme", "greenhouse", 38,
                         "Limited frontend overlap", "Frankfurt", "https://example.com/4"),
        ScoredJobSummary("Hardware Engineer", "chipco", "greenhouse", 12,
                         "Embedded focus", "Stuttgart", "https://example.com/5"),
        ScoredJobSummary("Staff Engineer", "bigco", "greenhouse", 8,
                         "Too senior", "Berlin", "https://example.com/6"),
    ]
    report.finalize_status()
    return report


async def main() -> int:
    url = os.environ.get("DISCORD_WEBHOOK_URL_DEBUG")
    if not url:
        print("error: set DISCORD_WEBHOOK_URL_DEBUG in .env", file=sys.stderr)
        return 1

    settings = Settings(
        llm_api_key=None, llm_model="", llm_provider="gemini",
        role_id=None, seen_path=".state/seen.json", dry_run=False,
        webhook_url_debug=url,
    )
    report = _sample_report()
    notifier = RegionalDiscordNotifier(settings)
    await notifier.send_run_report(report)
    print("Posted sample debug run report to Discord DEBUG channel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
