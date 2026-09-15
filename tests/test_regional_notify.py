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
        "region_webhooks": {},
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


async def test_regional_notifier_routes_freehire_country():
    sent = []

    def handler(request):
        sent.append(str(request.url))
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        n = RegionalDiscordNotifier(_settings(), client=client)
        p = Posting(
            uid="freehire:x", ats="freehire", company="freehire-visa", title="SWE",
            location="Berlin", url="https://j", posted_at=NOW, description="d",
            raw={"countries": ["de"], "visa_sponsored": True},
        )
        co = Company(slug="freehire-visa", ats="freehire")
        await n.send_one(p, Score(80, "r"), Urgency.MEDIUM, co, NOW)
    assert sent == ["https://de"]


async def test_regional_notifier_routes_freehire_india_board():
    sent = []

    def handler(request):
        sent.append(str(request.url))
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        n = RegionalDiscordNotifier(_settings(), client=client)
        p = Posting(
            uid="freehire:x", ats="freehire", company="freehire-in", title="Java Dev",
            location="Remote", url="https://j", posted_at=NOW, description="d",
            raw={"countries": ["us"], "visa_sponsored": False},
        )
        co = Company(slug="freehire-in", ats="freehire", region="in")
        await n.send_one(p, Score(80, "r"), Urgency.MEDIUM, co, NOW)
    assert sent == ["https://in"]


async def test_regional_notifier_routes_adzuna_country():
    sent = []

    def handler(request):
        sent.append(str(request.url))
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        n = RegionalDiscordNotifier(_settings(webhook_url_other=None, region_webhooks={"gb": "https://gb"}), client=client)
        p = Posting(uid="x:1", ats="adzuna", company="adzuna-gb", title="SWE",
                    location="London", url="https://j", posted_at=NOW, description="d")
        co = Company(slug="adzuna-gb", ats="adzuna", region="gb")
        await n.send_one(p, Score(80, "r"), Urgency.MEDIUM, co, NOW)
    assert sent == ["https://gb"]


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
