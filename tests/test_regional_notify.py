from datetime import datetime, timezone

import httpx

from job_radar.config import Settings
from job_radar.models import Company, Posting, Score, Urgency
from job_radar.notify import RegionalDiscordNotifier
from job_radar.report import RunReport

NOW = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


def _settings(**kw):
    base = {
        "llm_api_key": None, "llm_model": "", "llm_provider": "gemini",
        "role_id": None, "seen_path": ".state/seen.json", "dry_run": False,
        "webhook_url_in": "https://in",
        "webhook_url_de": "https://de",
        "webhook_url_other": "https://other",
        "webhook_url_debug": "https://debug",
    }
    base.update(kw)
    return Settings(**base)


async def test_regional_notifier_routes_india():
    sent = []

    def handler(request):
        sent.append(str(request.url))
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        n = RegionalDiscordNotifier(_settings(), client=client)
        p = Posting(uid="x:1", ats="greenhouse", company="c", title="SWE",
                    location="Bengaluru", url="https://j", posted_at=NOW, description="d")
        await n.send_one(p, Score(80, "r"), Urgency.MEDIUM, Company(slug="c", ats="greenhouse"), NOW)
    assert sent == ["https://in"]


async def test_send_run_report_posts_to_debug():
    sent = []

    def handler(request):
        sent.append(request.read().decode())
        return httpx.Response(204)

    report = RunReport(started_at=NOW, boards_total=10, postings_fetched=100)
    report.add_board("greenhouse", "stripe", "ok", 42, None)
    report.finalize_status()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await RegionalDiscordNotifier(_settings(), client=client).send_run_report(report)
    assert "Run Report" in sent[0]
    assert "Board health" in sent[0] or "PIPELINE FUNNEL" in sent[0]
