from datetime import datetime, timezone

from .models import Company, Posting, Profile, Score, Urgency


def _is_fresh(posting: Posting, profile: Profile, now: datetime) -> bool:
    if posting.posted_at is None:
        return False
    return (now - posting.posted_at).total_seconds() <= profile.high_fresh_hours * 3600


def classify(posting: Posting, score: Score, company: Company | None,
             profile: Profile, now: datetime | None = None) -> Urgency | None:
    """Return Discord urgency level, or None to not notify. Purely score-based now: a high
    LLM fit is the signal, even at a 'dream' company (a top company posting a role that's a
    bad fit for Taka shouldn't force a ping; it still lands in the Sheet). `company` is kept
    for signature stability but no longer overrides the score."""
    now = now or datetime.now(timezone.utc)

    if score.value >= profile.ping_threshold:
        if _is_fresh(posting, profile, now) and score.value >= profile.high_score:
            return Urgency.HIGH
        return Urgency.MEDIUM

    if score.value >= profile.digest_threshold:
        return Urgency.LOW

    return None


_URGENCY_RANK = {Urgency.HIGH: 3, Urgency.MEDIUM: 2, Urgency.LOW: 1}


def _score_for_profile(score: Score, profile: Profile) -> Score:
    if score.profile_scores and profile.name in score.profile_scores:
        val = score.profile_scores[profile.name]
    elif len(score.profile_scores) == 0:
        val = score.value
    else:
        val = 0
    return Score(value=val, reason=score.reason, tags=score.tags, ok=score.ok,
                 resume=score.resume, term=score.term, profile_scores=score.profile_scores)


def classify_for_profiles(posting: Posting, score: Score, company: Company | None,
                          profiles: list[Profile], eligible_names: set[str],
                          now: datetime | None = None) -> Urgency | None:
    """Pick the highest urgency level across profiles that passed rules. Each profile uses
    its own thresholds on its individual score from a multi-profile LLM response."""
    now = now or datetime.now(timezone.utc)
    best: Urgency | None = None
    for profile in profiles:
        if profile.name not in eligible_names:
            continue
        level = classify(posting, _score_for_profile(score, profile), company, profile, now)
        if level is None:
            continue
        if best is None or _URGENCY_RANK[level] > _URGENCY_RANK[best]:
            best = level
    return best
