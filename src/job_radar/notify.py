import re
from datetime import datetime

import httpx

from .filters import visa_note
from .models import Company, Posting, Score, Urgency
from .regions import Region, classify_region
from .report import RunReport

COLORS = {Urgency.HIGH: 0xE74C3C, Urgency.MEDIUM: 0xF1C40F, Urgency.LOW: 0x2ECC71}
_TAG = re.compile(r"<[^>]+>")


def _snippet(text: str, n: int = 320) -> str:
    """A clean, truncated plain-text preview of a job description (HTML stripped)."""
    t = _TAG.sub(" ", text or "").replace("&nbsp;", " ").replace("&amp;", "&")
    t = re.sub(r"\s+", " ", t).strip()
    return (t[: n - 1] + "…") if len(t) > n else t


def _age(posting: Posting, now: datetime) -> str:
    if posting.posted_at is None:
        return "unknown"
    secs = (now - posting.posted_at).total_seconds()
    if secs < 3600:
        return f"{int(secs / 60)}m ago"
    if secs < 48 * 3600:
        return f"{int(secs / 3600)}h ago"
    return f"{int(secs / 86400)}d ago"


def build_embed(posting: Posting, score: Score, urgency: Urgency,
                company: Company | None, now: datetime) -> dict:
    tier = company.tier if company else "target"
    visa = visa_note(posting.location)
    loc = (posting.location or "n/a")[:200] + (f"  ⚠️ {visa}" if visa else "")
    fields = [
        {"name": "Company", "value": f"{posting.company} ({posting.ats})", "inline": True},
        {"name": "Location", "value": loc[:240], "inline": True},
        {"name": "Posted", "value": _age(posting, now), "inline": True},
        {"name": f"Fit {score.value}/100 — why", "value": (score.reason or "n/a")[:600], "inline": False},
    ]
    snip = _snippet(posting.description)
    if snip:
        fields.append({"name": "About the role", "value": snip[:1024], "inline": False})
    embed = {
        "title": (posting.title or "(untitled)")[:240],
        "color": COLORS[urgency],
        "fields": fields,
        "footer": {"text": (", ".join(score.tags) or tier)[:200]},
    }
    if posting.url:
        embed["url"] = posting.url
    return embed


class _WebhookPoster:
    def __init__(self, webhook_url: str, role_id: str | None = None, client=None):
        self.webhook_url = webhook_url
        self.role_id = role_id
        self.client = client

    async def _post(self, payload: dict) -> None:
        owns = self.client is None
        client = self.client or httpx.AsyncClient(timeout=20.0)
        try:
            r = await client.post(self.webhook_url, json=payload)
            r.raise_for_status()
        finally:
            if owns:
                await client.aclose()


class DiscordNotifier(_WebhookPoster):
    async def send_one(self, posting, score, urgency, company, now) -> None:
        content = f"<@&{self.role_id}>" if (urgency == Urgency.HIGH and self.role_id) else None
        await self._post({"content": content,
                          "embeds": [build_embed(posting, score, urgency, company, now)]})

    async def send_digest(self, items, now) -> None:
        if not items:
            return
        lines = []
        for (p, s, c) in items[:25]:
            label = f"[{p.title}]({p.url})" if p.url else p.title
            lines.append(f"- {label} | {p.company} ({s.value}/100)")
        if len(items) > 25:
            lines.append(f"...and {len(items) - 25} more")
        await self._post({"embeds": [{
            "title": f"Daily digest: {len(items)} lower-priority matches",
            "description": "\n".join(lines)[:4000],
            "color": COLORS[Urgency.LOW],
        }]})

    async def send_embed(self, title: str, description: str, color: int = 0xE67E22) -> None:
        await self._post({"embeds": [{"title": title[:240],
                                      "description": description[:4000], "color": color}]})


class RegionalDiscordNotifier:
    """Routes job pings/digests to region-specific webhooks; posts RunReport to debug."""

    def __init__(self, settings, client=None):
        fallback = settings.webhook_url
        self.role_id = settings.role_id
        self.client = client
        self._webhooks: dict[Region, str | None] = {
            "india": settings.webhook_url_in or fallback,
            "germany": settings.webhook_url_de or fallback,
            "other": settings.webhook_url_other or fallback,
        }
        self._debug = settings.webhook_url_debug or fallback
        self._posters: dict[Region, _WebhookPoster] = {}

    def _poster(self, region: Region) -> _WebhookPoster | None:
        url = self._webhooks.get(region)
        if not url:
            return None
        if region not in self._posters:
            self._posters[region] = _WebhookPoster(url, self.role_id, self.client)
        return self._posters[region]

    def _region_for(self, posting: Posting, company: Company | None) -> Region:
        hint = company.region if company else None
        return classify_region(posting.location, hint=hint)

    async def send_one(self, posting, score, urgency, company, now) -> None:
        region = self._region_for(posting, company)
        poster = self._poster(region)
        if poster is None:
            return
        content = f"<@&{self.role_id}>" if (urgency == Urgency.HIGH and self.role_id) else None
        await poster._post({"content": content,
                            "embeds": [build_embed(posting, score, urgency, company, now)]})

    async def send_digest(self, items, now) -> None:
        if not items:
            return
        by_region: dict[Region, list] = {"india": [], "germany": [], "other": []}
        for p, s, c in items:
            by_region[self._region_for(p, c)].append((p, s, c))
        for region, group in by_region.items():
            if not group:
                continue
            poster = self._poster(region)
            if poster is None:
                continue
            lines = []
            for (p, s, _c) in group[:25]:
                label = f"[{p.title}]({p.url})" if p.url else p.title
                lines.append(f"- {label} | {p.company} ({s.value}/100)")
            if len(group) > 25:
                lines.append(f"...and {len(group) - 25} more")
            title = f"Digest ({region}): {len(group)} lower-priority matches"
            await poster._post({"embeds": [{
                "title": title[:240],
                "description": "\n".join(lines)[:4000],
                "color": COLORS[Urgency.LOW],
            }]})

    async def send_embed(self, title: str, description: str, color: int = 0xE67E22) -> None:
        if not self._debug:
            return
        poster = _WebhookPoster(self._debug, self.role_id, self.client)
        await poster._post({"embeds": [{"title": title[:240],
                                       "description": description[:4000], "color": color}]})

    async def send_run_report(self, report: RunReport) -> None:
        if not self._debug:
            return
        lines = [
            f"**Status:** {report.status} | **Duration:** {report.duration_sec:.1f}s",
            f"**Boards:** {report.boards_total} total — {report.boards_ok} ok, "
            f"{report.boards_empty} empty, {report.boards_error} error",
            f"**Postings:** fetched {report.postings_fetched} | new {report.new} | "
            f"primed {report.primed} | survivors {report.survivors} | deferred {report.deferred}",
            f"**Scored:** {report.scored} ({report.score_errors} errors) | "
            f"LLM: {report.llm_provider or 'n/a'} | heuristic fallbacks: {report.heuristic_fallbacks}",
        ]
        if report.filter_rejects:
            fr = ", ".join(f"{k}={v}" for k, v in sorted(report.filter_rejects.items()))
            lines.append(f"**Filter rejects:** {fr}")
        if report.notifications:
            for region, counts in sorted(report.notifications.items()):
                lines.append(f"**Notify {region}:** pinged {counts.get('pinged', 0)}, "
                             f"digest {counts.get('digest', 0)}")
        if report.sheet_tracked or report.sheet_closed:
            lines.append(f"**Sheet:** tracked {report.sheet_tracked}, closed {report.sheet_closed}")
        if report.boards_by_ats:
            ats_lines = []
            for ats, counts in sorted(report.boards_by_ats.items()):
                ats_lines.append(f"- {ats}: ok {counts.get('ok', 0)}, empty {counts.get('empty', 0)}, "
                                 f"err {counts.get('error', 0)}")
            lines.append("**Boards by ATS:**\n" + "\n".join(ats_lines))
        if report.unreachable:
            lines.append("**Unreachable boards:**")
            for ats, slug, msg in report.unreachable:
                lines.append(f"- `{ats}/{slug}`: {msg[:120]}")
        if report.errors:
            lines.append("**Errors:**")
            for ats, slug, msg in report.errors:
                lines.append(f"- `{ats}/{slug}`: {msg[:120]}")

        body = "\n".join(lines)
        chunks = [body[i:i + 3900] for i in range(0, len(body), 3900)] or [body]
        poster = _WebhookPoster(self._debug, self.role_id, self.client)
        for i, chunk in enumerate(chunks):
            title = "Run report" if i == 0 else f"Run report (cont. {i + 1})"
            await poster._post({"embeds": [{"title": title, "description": chunk, "color": 0x3498DB}]})


class ConsoleNotifier:
    """Used in dry-run / local. Prints instead of posting."""

    async def send_one(self, posting, score, urgency, company, now) -> None:
        print(f"[{urgency.value.upper()}] {posting.title} @ {posting.company} "
              f"({score.value}/100) {posting.url} :: {score.reason}")

    async def send_digest(self, items, now) -> None:
        if not items:
            return
        print(f"[DIGEST] {len(items)} lower-priority matches")
        for (p, s, c) in items:
            print(f"   - {p.title} @ {p.company} ({s.value}/100) {p.url}")

    async def send_embed(self, title: str, description: str, color: int = 0xE67E22) -> None:
        print(f"[{title}]\n{description}")

    async def send_run_report(self, report: RunReport) -> None:
        print(f"[RUN REPORT] status={report.status} boards={report.boards_total} "
              f"postings={report.postings_fetched} new={report.new} pinged="
              f"{sum(c.get('pinged', 0) for c in report.notifications.values())}")
