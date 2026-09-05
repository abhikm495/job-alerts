"""Per-run audit report for the debug Discord channel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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

    postings_fetched: int = 0
    new: int = 0
    primed: int = 0
    survivors: int = 0
    deferred: int = 0
    scored: int = 0
    score_errors: int = 0

    filter_rejects: dict[str, int] = field(default_factory=dict)
    notifications: dict[str, dict[str, int]] = field(default_factory=dict)

    errors: list[tuple[str, str, str]] = field(default_factory=list)  # ats, slug, msg
    unreachable: list[tuple[str, str, str]] = field(default_factory=list)

    llm_provider: str = ""
    heuristic_fallbacks: int = 0
    sheet_tracked: int = 0
    sheet_closed: int = 0

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

    def finalize_status(self) -> None:
        if self.boards_error == self.boards_total and self.boards_total > 0:
            self.status = "failed"
        elif self.boards_error > 0 or self.score_errors > 0 or self.errors:
            self.status = "partial"
        else:
            self.status = "ok"
