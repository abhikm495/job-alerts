from datetime import datetime, timezone

from job_radar.report import (
    RunReport,
    ScoredJobSummary,
    _score_bucket_fields,
    build_run_report_embeds,
    build_run_report_messages,
)


NOW = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


def _sample_report() -> RunReport:
    report = RunReport(
        started_at=NOW,
        duration_sec=120.5,
        boards_total=5,
        postings_fetched=500,
        new=10,
        survivors=3,
        scored=3,
        ping_threshold=70,
        digest_threshold=55,
        llm_provider="gemini",
    )
    report.add_board("greenhouse", "stripe", "ok", 100, None)
    report.add_board("personio", "alteos", "ok", 8, None)
    report.add_board("join_com", "deadco", "error", 0, "404 Not Found")
    report.add_board("join_com", "emptyco", "empty", 0, None)
    report.add_board("recruitee", "acme", "ok", 5, None)
    report.scored_jobs = [
        ScoredJobSummary("SWE", "stripe", "greenhouse", 75, "good", "Berlin", "https://x"),
        ScoredJobSummary("FE Dev", "alteos", "personio", 58, "ok", "Munich", "https://y"),
        ScoredJobSummary("HW Eng", "acme", "recruitee", 15, "bad fit", "Stuttgart", "https://z"),
    ]
    report.filter_rejects = {"title_include": 5}
    report.notifications = {"germany": {"pinged": 1, "digest": 1}}
    report.finalize_status()
    return report


def test_job_line_includes_link():
    from job_radar.report import _job_line

    line = _job_line(ScoredJobSummary(
        "Senior Software Engineer", "stripe", "greenhouse", 78,
        "good", "Berlin", "https://example.com/job/1",
    ))
    assert "[Senior Software Engineer](https://example.com/job/1)" in line


def test_score_bucket_fields_include_all_jobs():
    jobs = [
        ScoredJobSummary(f"Role {i}", "co", "greenhouse", 50 + i,
                         "reason", "loc", f"https://example.com/{i}")
        for i in range(12)
    ]
    buckets = {"51-60": jobs}
    fields = _score_bucket_fields(buckets)
    listed = "\n".join(f["value"] for f in fields)
    assert listed.count("https://example.com/") == 12


def test_build_run_report_embeds_has_sections():
    embeds = build_run_report_embeds(_sample_report())
    titles = [e["title"] for e in embeds]
    assert any("Run Report" in t for t in titles)
    assert any("Board health" in t for t in titles)
    assert any("LLM scores" in t for t in titles)
    assert any("Engineering log" in t for t in titles)


def test_score_buckets_grouped():
    embeds = build_run_report_embeds(_sample_report())
    score_embed = next(e for e in embeds if "LLM scores" in e["title"])
    field_names = [f["name"] for f in score_embed["fields"]]
    assert any("71-80" in n for n in field_names)
    assert any("51-60" in n for n in field_names)
    assert any("11-20" in n for n in field_names)


def test_split_messages_respects_limits():
    report = _sample_report()
    # Inflate to trigger splitting
    for i in range(40):
        report.scored_jobs.append(
            ScoredJobSummary(f"Role {i}", "co", "greenhouse", 50 + (i % 40),
                             "reason", "loc", f"https://{i}")
        )
    messages = build_run_report_messages(report)
    assert len(messages) >= 1
    for group in messages:
        assert len(group) <= 10
