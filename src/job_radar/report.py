"""Per-run audit report for the debug Discord channel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

STATUS_COLOR = {"ok": 0x2ECC71, "partial": 0xF1C40F, "failed": 0xE74C3C}
_SECTION_COLOR = {
    "overview": 0x3498DB,
    "boards": 0x9B59B6,
    "scores": 0xE67E22,
    "engineering": 0x95A5A6,
}
_SCORE_BUCKET_RANGES = [(lo, lo + 9) for lo in range(1, 100, 10)]  # 1-10 … 91-100


@dataclass
class BoardResult:
    ats: str
    slug: str
    status: str  # ok | empty | error
    job_count: int
    error: str | None = None


@dataclass
class ScoredJobSummary:
    title: str
    company: str
    ats: str
    score: int
    reason: str
    location: str
    url: str
    ok: bool = True


@dataclass
class RunReport:
    started_at: datetime
    duration_sec: float = 0.0
    status: str = "ok"  # ok | partial | failed

    boards_total: int = 0
    boards_ok: int = 0
    boards_empty: int = 0
    boards_error: int = 0
    boards_by_ats: dict[str, dict[str, int]] = field(default_factory=dict)
    board_results: list[BoardResult] = field(default_factory=list)

    postings_fetched: int = 0
    new: int = 0
    primed: int = 0
    survivors: int = 0
    deferred: int = 0
    scored: int = 0
    score_errors: int = 0
    scored_jobs: list[ScoredJobSummary] = field(default_factory=list)

    filter_rejects: dict[str, int] = field(default_factory=dict)
    notifications: dict[str, dict[str, int]] = field(default_factory=dict)

    errors: list[tuple[str, str, str]] = field(default_factory=list)  # ats, slug, msg
    unreachable: list[tuple[str, str, str]] = field(default_factory=list)

    llm_provider: str = ""
    heuristic_fallbacks: int = 0
    sheet_tracked: int = 0
    sheet_closed: int = 0

    ping_threshold: int = 70
    digest_threshold: int = 55
    high_score: int = 80
    score_cap: int = 0

    def record_board(self, ats: str, status: str) -> None:
        bucket = self.boards_by_ats.setdefault(ats, {"ok": 0, "empty": 0, "error": 0})
        if status in bucket:
            bucket[status] += 1
        if status == "ok":
            self.boards_ok += 1
        elif status == "empty":
            self.boards_empty += 1
        else:
            self.boards_error += 1

    def add_board(self, ats: str, slug: str, status: str, job_count: int,
                  error: str | None = None) -> None:
        self.record_board(ats, status)
        self.board_results.append(BoardResult(ats, slug, status, job_count, error))

    def finalize_status(self) -> None:
        if self.boards_error == self.boards_total and self.boards_total > 0:
            self.status = "failed"
        elif self.boards_error > 0 or self.score_errors > 0 or self.errors:
            self.status = "partial"
        else:
            self.status = "ok"


def _pct(n: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{100 * n / total:.0f}%"


def _bar(n: int, total: int, width: int = 12) -> str:
    if total <= 0:
        return "░" * width
    filled = max(0, min(width, round(width * n / total)))
    return "█" * filled + "░" * (width - filled)


def _score_bucket(score: int) -> str:
    if score <= 0:
        return "0 / error"
    for lo, hi in _SCORE_BUCKET_RANGES:
        if lo <= score <= hi:
            return f"{lo}-{hi}"
    return "91-100"


def _job_line(job: ScoredJobSummary, max_title: int = 42) -> str:
    title = (job.title or "(untitled)")[:max_title]
    loc = (job.location or "n/a")[:28]
    flag = "⚠️" if not job.ok else "•"
    label = f"[{title}]({job.url})" if job.url else title
    return f"{flag} **{job.score:>3}** `{job.company}` — {label}\n   ↳ {loc}"


def _chunk_job_lines(jobs: list[ScoredJobSummary], max_chars: int = 1000) -> list[str]:
    """Split job lines into Discord field-sized chunks (all jobs, no truncation)."""
    chunks: list[str] = []
    lines: list[str] = []
    length = 0
    for job in jobs:
        line = _job_line(job)
        add = len(line) + (1 if lines else 0)
        if lines and length + add > max_chars:
            chunks.append("\n".join(lines))
            lines = [line]
            length = len(line)
        else:
            lines.append(line)
            length += add
    if lines:
        chunks.append("\n".join(lines))
    return chunks


def _score_bucket_fields(buckets: dict[str, list[ScoredJobSummary]]) -> list[dict]:
    """One or more embed fields per bucket, listing every scored job."""
    fields: list[dict] = []
    order = ["91-100", "81-90", "71-80", "61-70", "51-60", "41-50", "31-40", "21-30", "11-20", "1-10", "0 / error"]
    for label in order:
        jobs = buckets.get(label, [])
        if not jobs:
            continue
        for i, chunk in enumerate(_chunk_job_lines(jobs)):
            suffix = f" pt {i + 1}" if i else ""
            fields.append({
                "name": f"🎯 Score {label} ({len(jobs)}){suffix}",
                "value": chunk[:1024],
                "inline": False,
            })
    return fields


def _score_cap_label(score_cap: int) -> str:
    return "none (all)" if score_cap <= 0 else str(score_cap)


def _bucket_jobs(jobs: list[ScoredJobSummary]) -> dict[str, list[ScoredJobSummary]]:
    out: dict[str, list[ScoredJobSummary]] = {}
    for job in jobs:
        out.setdefault(_score_bucket(job.score), []).append(job)
    for bucket in out:
        out[bucket].sort(key=lambda j: j.score, reverse=True)
    return out


def _embed_char_len(embed: dict) -> int:
    n = len(embed.get("title") or "") + len(embed.get("description") or "")
    for f in embed.get("fields") or []:
        n += len(f.get("name") or "") + len(f.get("value") or "")
    if footer := embed.get("footer"):
        n += len(footer.get("text") or "")
    return n


def _split_embed_messages(embeds: list[dict], max_embeds: int = 10, max_chars: int = 5800) -> list[list[dict]]:
    """Group embeds into webhook payloads respecting Discord limits."""
    if not embeds:
        return []
    messages: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0
    for embed in embeds:
        elen = _embed_char_len(embed)
        if current and (len(current) >= max_embeds or current_chars + elen > max_chars):
            messages.append(current)
            current = []
            current_chars = 0
        current.append(embed)
        current_chars += elen
    if current:
        messages.append(current)
    return messages


def build_run_report_embeds(report: RunReport) -> list[dict]:
    """Build rich, human-readable embeds for the debug Discord channel."""
    status_emoji = {"ok": "✅", "partial": "⚠️", "failed": "❌"}.get(report.status, "❓")
    total = report.boards_total or 1
    pinged = sum(c.get("pinged", 0) for c in report.notifications.values())
    digested = sum(c.get("digest", 0) for c in report.notifications.values())

    overview = {
        "title": f"{status_emoji} Run Report — {report.status.upper()}",
        "color": STATUS_COLOR.get(report.status, 0x3498DB),
        "description": (
            f"**Started** {report.started_at.strftime('%Y-%m-%d %H:%M UTC')}  "
            f"**Duration** {report.duration_sec:.1f}s\n\n"
            "```\n"
            "PIPELINE FUNNEL\n"
            "────────────────────────────────────────\n"
            f"Jobs fetched      {report.postings_fetched:>6}\n"
            f"New this run      {report.new:>6}\n"
            f"Silently primed   {report.primed:>6}\n"
            f"Passed filters    {report.survivors:>6}\n"
            f"Deferred (cap)    {report.deferred:>6}\n"
            f"LLM scored        {report.scored:>6}\n"
            f"Pings sent        {pinged:>6}  (≥{report.ping_threshold})\n"
            f"Digest sent       {digested:>6}  (≥{report.digest_threshold})\n"
            "```"
        ),
        "fields": [
            {
                "name": "🟢 Boards OK (jobs found)",
                "value": f"`{report.boards_ok:>4}` {_bar(report.boards_ok, total)} {_pct(report.boards_ok, total)}",
                "inline": True,
            },
            {
                "name": "🟡 Boards empty (reachable)",
                "value": f"`{report.boards_empty:>4}` {_bar(report.boards_empty, total)} {_pct(report.boards_empty, total)}",
                "inline": True,
            },
            {
                "name": "🔴 Boards failed",
                "value": f"`{report.boards_error:>4}` {_bar(report.boards_error, total)} {_pct(report.boards_error, total)}",
                "inline": True,
            },
        ],
        "footer": {"text": f"LLM: {report.llm_provider or 'heuristic'} | score cap: {_score_cap_label(report.score_cap)}"},
    }

    # ATS summary table
    ats_lines = ["ATS            OK  EMPTY  ERR  JOBS", "────────────────────────────────"]
    for ats, counts in sorted(report.boards_by_ats.items()):
        ok = counts.get("ok", 0)
        empty = counts.get("empty", 0)
        err = counts.get("error", 0)
        jobs = sum(b.job_count for b in report.board_results if b.ats == ats)
        ats_lines.append(f"{ats[:14]:<14} {ok:>3} {empty:>5} {err:>4} {jobs:>5}")
    boards_embed = {
        "title": "📋 Board health by ATS",
        "color": _SECTION_COLOR["boards"],
        "description": "```\n" + "\n".join(ats_lines) + "\n```",
    }

    failed = [b for b in report.board_results if b.status == "error"]
    empty = [b for b in report.board_results if b.status == "empty"]
    ok_boards = [b for b in report.board_results if b.status == "ok"]

    fail_lines = []
    for b in failed[:25]:
        err = (b.error or "unknown")[:100]
        fail_lines.append(f"🔴 `{b.ats}/{b.slug}`\n   {err}")
    if len(failed) > 25:
        fail_lines.append(f"_…and {len(failed) - 25} more (see engineering log)_")

    top_ok = sorted(ok_boards, key=lambda b: b.job_count, reverse=True)[:12]
    top_lines = [f"🟢 `{b.ats}/{b.slug}` — **{b.job_count}** jobs" for b in top_ok]

    boards_embed["fields"] = [
        {
            "name": f"🔴 Failed boards ({len(failed)}) — not accessible",
            "value": "\n".join(fail_lines)[:1024] if fail_lines else "_none_",
            "inline": False,
        },
        {
            "name": f"🟡 Empty boards ({len(empty)}) — reachable, 0 jobs",
            "value": (", ".join(f"`{b.slug}`" for b in empty[:30])
                      + (f" …+{len(empty) - 30}" if len(empty) > 30 else ""))[:1024] or "_none_",
            "inline": False,
        },
        {
            "name": "🟢 Top boards by job count",
            "value": "\n".join(top_lines)[:1024] if top_lines else "_none_",
            "inline": False,
        },
    ]

    embeds: list[dict] = [overview, boards_embed]

    # Score buckets — list every scored job; split across embeds when needed
    buckets = _bucket_jobs(report.scored_jobs)
    score_fields = _score_bucket_fields(buckets) if buckets else []
    if score_fields:
        score_desc = (
            f"Thresholds: ping **≥{report.ping_threshold}** | "
            f"digest **≥{report.digest_threshold}** | urgent **≥{report.high_score}**"
        )
        for i in range(0, len(score_fields), 25):
            part = score_fields[i:i + 25]
            title = f"🎯 LLM scores ({len(report.scored_jobs)} jobs scored)"
            if i:
                title += f" (cont. {i // 25 + 1})"
            embeds.append({
                "title": title,
                "color": _SECTION_COLOR["scores"],
                **({"description": score_desc} if i == 0 else {}),
                "fields": part,
            })

    # Filters + notifications
    if report.filter_rejects or report.notifications:
        fr_lines = [f"• `{k}`: **{v}**" for k, v in sorted(report.filter_rejects.items())]
        notif_lines = [
            f"• **{region}**: {c.get('pinged', 0)} pings, {c.get('digest', 0)} digest"
            for region, c in sorted(report.notifications.items())
        ]
        embeds.append({
            "title": "🔍 Filters & notifications",
            "color": _SECTION_COLOR["overview"],
            "fields": [
                {"name": "Filter rejects", "value": "\n".join(fr_lines)[:1024] or "_none_", "inline": True},
                {"name": "Regional notify", "value": "\n".join(notif_lines)[:1024] or "_none_", "inline": True},
            ],
        })

    # Engineering appendix
    eng_lines = [
        f"status={report.status}",
        f"duration_sec={report.duration_sec:.2f}",
        f"boards_total={report.boards_total}",
        f"boards_ok={report.boards_ok} boards_empty={report.boards_empty} boards_error={report.boards_error}",
        f"postings_fetched={report.postings_fetched} new={report.new} primed={report.primed}",
        f"survivors={report.survivors} deferred={report.deferred} scored={report.scored}",
        f"score_errors={report.score_errors} heuristic_fallbacks={report.heuristic_fallbacks}",
        f"ping_threshold={report.ping_threshold} digest_threshold={report.digest_threshold} high_score={report.high_score}",
        f"score_cap={_score_cap_label(report.score_cap)}",
        f"llm_provider={report.llm_provider or 'heuristic'}",
        f"sheet_tracked={report.sheet_tracked} sheet_closed={report.sheet_closed}",
    ]
    if report.unreachable:
        eng_lines.append("")
        eng_lines.append("unreachable_boards:")
        for ats, slug, msg in report.unreachable:
            eng_lines.append(f"  {ats}/{slug}: {msg[:200]}")
    if report.errors:
        eng_lines.append("")
        eng_lines.append("run_errors:")
        for ats, slug, msg in report.errors:
            eng_lines.append(f"  {ats}/{slug}: {msg[:200]}")

    embeds.append({
        "title": "🛠 Engineering log",
        "color": _SECTION_COLOR["engineering"],
        "description": "```\n" + "\n".join(eng_lines)[:3900] + "\n```",
    })

    return embeds


def build_run_report_messages(report: RunReport) -> list[list[dict]]:
    """Return embed groups ready for sequential webhook posts."""
    return _split_embed_messages(build_run_report_embeds(report))
