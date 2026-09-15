import asyncio
import json

import httpx

from .models import Posting, Profile, Score

# --- shared prompt pieces (provider-neutral) ---

SINGLE_INSTRUCTIONS = (
    "You screen job postings for ONE specific candidate (described below). Read the role's "
    "actual requirements and qualifications, then score 0-100 by judging TWO things together:\n"
    "1) REALISTIC CHANCE: would this candidate plausibly be competitive? Compare the stated "
    "requirements to the candidate's real skills and experience level. Heavily penalize roles "
    "that need a domain or skill the candidate does NOT list (e.g. Android/iOS/mobile, "
    "embedded/firmware/hardware, kernel, game/graphics, a specific language they never mention), "
    "or experience far above/below their level.\n"
    "2) GOOD FOR THEM: reward strong overlap with the candidate's listed strengths and target "
    "roles. Give PARTIAL credit to sensible tangential stretches. Be calibrated: most postings "
    "should land 30-70; reserve 80+ for genuinely strong, realistic matches.\n"
    "Respond as JSON {score, reason, tags, resume, term}; reason = one short sentence naming "
    "the key fit or gap; tags = a few lowercase labels; resume = \"swe\" for general software-"
    "engineering roles or \"ai\" for AI/ML/data roles; term = work-term timing EXACTLY as stated "
    "(e.g. \"Summer 2027\", \"full-time\", \"not stated\")."
)

MULTI_INSTRUCTIONS = (
    "You screen job postings for MULTIPLE candidates (listed below). Score EACH candidate "
    "independently 0-100 using the same criteria: realistic chance given their experience "
    "and skills, plus how good the role is for them. Calibrate per candidate — a senior .NET "
    "lead role may score high for a 9-year backend lead and low for a 2-year React developer.\n"
    "Respond as JSON {scores, reason, tags, term} where:\n"
    "- scores = object mapping each candidate id (given below) to an integer 0-100\n"
    "- reason = one short sentence noting who fits best and the key fit or gap\n"
    "- tags = a few lowercase labels\n"
    "- term = work-term timing as stated (\"full-time\", \"not stated\", or season/year if intern)\n"
    "Most postings should land 30-70 per candidate; reserve 80+ for genuinely strong matches."
)


def _candidate_block(profile: Profile) -> str:
    return f"CANDIDATE ({profile.name}):\n{profile.summary}"


def _candidates_block(profiles: list[Profile]) -> str:
    return "\n\n".join(_candidate_block(p) for p in profiles)


def _posting_block(posting: Posting) -> str:
    desc = (posting.description or "")[:1500]
    return (f"POSTING:\nCompany: {posting.company}\nTitle: {posting.title}\n"
            f"Location: {posting.location}\nDescription: {desc}")


def _instructions(profiles: list[Profile]) -> str:
    if len(profiles) <= 1:
        return SINGLE_INSTRUCTIONS
    ids = ", ".join(p.name for p in profiles)
    return f"{MULTI_INSTRUCTIONS}\nCandidate ids: {ids}"


def build_prompt(posting: Posting, profiles: list[Profile]) -> str:
    """Single-string prompt (used by Gemini). `profiles` is one or more candidates."""
    if len(profiles) == 1:
        body = _candidate_block(profiles[0])
    else:
        body = _candidates_block(profiles)
    return f"{_instructions(profiles)}\n\n{body}\n\n{_posting_block(posting)}\n"


def _as_dict(obj) -> dict:
    """Normalize a parsed JSON value to a dict. LLMs sometimes wrap the object in a
    single-element array or return a bare scalar; anything non-dict-shaped -> {}."""
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return obj[0]
    return {}


def _extract_json(text: str) -> dict:
    """Parse a JSON object out of an LLM text response, tolerating ``` fences.
    Always returns a dict (never a list/scalar), so callers can safely .get()."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if "\n" in t:
            first, rest = t.split("\n", 1)
            t = rest if first.strip().lower() in ("json", "") else t
    try:
        return _as_dict(json.loads(t))
    except (json.JSONDecodeError, TypeError):
        i, j = t.find("{"), t.rfind("}")
        if 0 <= i < j:
            try:
                return _as_dict(json.loads(t[i:j + 1]))
            except json.JSONDecodeError:
                return {}
        return {}


def _parse_int_score(raw) -> int:
    try:
        val = int(round(float(str(raw).strip().rstrip("%") or 0)))
    except (TypeError, ValueError):
        val = 0
    return max(0, min(100, val))


def _coerce_score(obj, profiles: list[Profile] | None = None) -> Score:
    profiles = profiles or []
    if not isinstance(obj, dict) or not obj:
        return Score(value=0, reason="unparseable LLM response", tags=[], ok=False)

    profile_scores: dict[str, int] = {}
    scores_obj = obj.get("scores")
    if isinstance(scores_obj, dict) and profiles:
        for p in profiles:
            if p.name in scores_obj:
                profile_scores[p.name] = _parse_int_score(scores_obj[p.name])
    if not profile_scores and profiles:
        # Single-score shape: {"score": 72} — attribute to the sole profile.
        if len(profiles) == 1:
            profile_scores[profiles[0].name] = _parse_int_score(obj.get("score", 0))
        elif isinstance(scores_obj, dict):
            for key, val in scores_obj.items():
                profile_scores[str(key).lower()] = _parse_int_score(val)
    if not profile_scores:
        profile_scores = {"default": _parse_int_score(obj.get("score", 0))}

    val = max(profile_scores.values()) if profile_scores else 0
    reason = str(obj.get("reason", ""))[:300]
    tags = [str(t) for t in obj.get("tags", []) if isinstance(t, (str, int))][:8]
    resume = str(obj.get("resume", "")).strip().lower()
    resume = resume if resume in ("ai", "swe") else ""
    term = str(obj.get("term", "")).strip()[:80]
    return Score(value=val, reason=reason, tags=tags, resume=resume, term=term,
                 profile_scores=profile_scores)


# --- Gemini (REST) ---

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
def _gemini_schema(profiles: list[Profile]) -> dict:
    if len(profiles) <= 1:
        return {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER"},
                "reason": {"type": "STRING"},
                "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
                "resume": {"type": "STRING"},
                "term": {"type": "STRING"},
            },
            "required": ["score", "reason", "tags", "resume", "term"],
        }
    names = [p.name for p in profiles]
    return {
        "type": "OBJECT",
        "properties": {
            "scores": {
                "type": "OBJECT",
                "properties": {n: {"type": "INTEGER"} for n in names},
                "required": names,
            },
            "reason": {"type": "STRING"},
            "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
            "term": {"type": "STRING"},
        },
        "required": ["scores", "reason", "tags", "term"],
    }


def parse_score(data: dict, profiles: list[Profile] | None = None) -> Score:
    """Parse a Gemini generateContent response into a Score."""
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return Score(value=0, reason="unparseable LLM response", tags=[], ok=False)
    return _coerce_score(_extract_json(text), profiles)


class GeminiProvider:
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash", client=None):
        self.api_key = api_key
        self.model = model
        self.client = client

    async def score(self, posting: Posting, profiles: list[Profile]) -> Score:
        body = {
            "contents": [{"parts": [{"text": build_prompt(posting, profiles)}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": _gemini_schema(profiles),
                "temperature": 0.2,
            },
        }
        url = GEMINI_URL.format(model=self.model, key=self.api_key)
        owns = self.client is None
        client = self.client or httpx.AsyncClient(timeout=30.0)
        try:
            r = await client.post(url, json=body)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # never let a scoring error abort the run
            return Score(value=0, reason=f"LLM error: {e!r}"[:200], tags=[], ok=False)
        finally:
            if owns:
                await client.aclose()
        return parse_score(data, profiles)


# --- Claude (Anthropic Messages API, via httpx to match the SDK-free design) ---

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class ClaudeProvider:
    """Scores via the Anthropic Messages API. Uses httpx (not the SDK) to stay
    consistent with this project's dependency-light, mockable design. Default model
    is Haiku 4.5 (high-volume classification); override via LLM_MODEL."""

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5", client=None):
        self.api_key = api_key
        self.model = model
        self.client = client

    async def score(self, posting: Posting, profiles: list[Profile]) -> Score:
        # Stable instructions + candidate go in `system` (cacheable prefix); the
        # volatile posting goes in the user turn. Caching engages once the prefix
        # exceeds the model minimum; harmless below it.
        cands = _candidates_block(profiles) if len(profiles) > 1 else _candidate_block(profiles[0])
        system = [{
            "type": "text",
            "text": f"{_instructions(profiles)}\n\n{cands}",
            "cache_control": {"type": "ephemeral"},
        }]
        body = {
            "model": self.model,
            "max_tokens": 400,
            "system": system,
            "messages": [{"role": "user", "content": _posting_block(posting)}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        owns = self.client is None
        client = self.client or httpx.AsyncClient(timeout=30.0)
        try:
            r = await client.post(ANTHROPIC_URL, json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
            text = data["content"][0]["text"]
        except Exception as e:
            return Score(value=0, reason=f"LLM error: {e!r}"[:200], tags=[], ok=False)
        finally:
            if owns:
                await client.aclose()
        return _coerce_score(_extract_json(text), profiles)


# --- AWS Bedrock (Claude via the Converse API) ---

class BedrockProvider:
    """Scores via Amazon Bedrock's Converse API (model-agnostic; defaults to a Claude).
    Uses boto3 (lazy import) so AWS SigV4 auth and the default credential chain are handled
    for us: set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION (or an instance role).
    Bedrock isn't on Gemini's tiny free-tier daily quota, so it's the durable scorer."""

    def __init__(self, model: str = "anthropic.claude-3-5-haiku-20241022-v1:0",
                 region: str | None = None, client=None):
        self.model = model
        self.region = region
        self._client = client

    def _bedrock(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    async def score(self, posting: Posting, profiles: list[Profile]) -> Score:
        cands = _candidates_block(profiles) if len(profiles) > 1 else _candidate_block(profiles[0])
        system = [{"text": f"{_instructions(profiles)}\n\n{cands}"}]
        messages = [{"role": "user", "content": [{"text": _posting_block(posting)}]}]

        def call():
            return self._bedrock().converse(
                modelId=self.model, system=system, messages=messages,
                inferenceConfig={"maxTokens": 400, "temperature": 0.2})

        try:
            resp = await asyncio.to_thread(call)
            text = resp["output"]["message"]["content"][0]["text"]
        except Exception as e:
            return Score(value=0, reason=f"LLM error: {e!r}"[:200], tags=[], ok=False)
        return _coerce_score(_extract_json(text), profiles)


# --- Heuristic fallback (deterministic, no network) ---

_EARLY = ("intern", "internship", "new grad", "new-grad", "new graduate", "co-op", "co op",
          "coop", "junior", "early career", "early-career", "graduate", "entry level",
          "entry-level", "student", "apprentice", "university")
_SENIOR = ("senior", "sr.", "staff", "principal", " lead", "manager", "director", "head of",
           "vp ", "architect", " ii", " iii", " iv", "distinguished", "expert", "10+")
_CORE = ("software", "developer", "engineer", "swe", "backend", "back end", "back-end",
         "frontend", "front end", "full stack", "full-stack", "machine learning", " ml",
         " ai", "data", "platform", "infrastructure", " web")
_TECH = ("python", "java", "javascript", "typescript", "react", "node", "golang", "rust",
         "c++", "sql", "aws", "gcp", "azure", "docker", "kubernetes", "pytorch", "tensorflow",
         "llm", "nlp", "api", "fastapi", "django", "flask", "next.js", "postgres", "spark")
# Domains the candidate has NO background in: a title in one of these is a weak match even
# if it says "Software Engineer Intern". (Tracks this candidate's gaps; the LLM judges this
# properly from the description -- this just keeps the offline fallback from over-scoring.)
_MISMATCH = ("android", "ios", "mobile", "embedded", "firmware", "hardware", "fpga",
             "verilog", "rtl", "asic", "kernel", "device driver", "mechanical", "electrical",
             "analog", "silicon", "photonics", "rf ", "game", "graphics", "rendering",
             "unreal engine", "shader")


def heuristic_score(posting: Posting, profile: Profile) -> Score:
    """Deterministic 0-100 fit estimate from title and skill signals, for when the LLM is
    unavailable (rate-limited or no key). Lower precision than the LLM, but it keeps the
    radar useful: a rules-survivor still gets a sensible, sortable score instead of nothing.
    Marked ok=True (it's a real score) and tagged 'heuristic' so it's transparent."""
    title = (posting.title or "").lower()
    text = f"{title} {(posting.description or '')[:1500].lower()}"
    # Baseline sits just under digest_threshold (50): a generic full-time rules-survivor
    # lands ~45-53, while an early-career and/or techy role clears comfortably. This keeps
    # a heuristic-scored backfill focused on intern/co-op/new-grad roles, not everything.
    score = 40

    if any(s in title for s in _SENIOR):
        score -= 30
    if any(e in title for e in _EARLY):
        score += 28
    if any(c in title for c in _CORE):
        score += 8
    score += min(12, sum(3 for t in _TECH if t in text))
    if any(m in title for m in _MISMATCH):  # specialized domain the candidate lacks
        score -= 22

    score = max(0, min(100, score))
    return Score(value=score, reason="heuristic (LLM unavailable): title + skill match",
                 tags=["heuristic"], ok=True)


def heuristic_multi_score(posting: Posting, profiles: list[Profile]) -> Score:
    """Per-profile heuristic scores combined into one MultiScore-shaped Score."""
    profile_scores = {p.name: heuristic_score(posting, p).value for p in profiles}
    val = max(profile_scores.values()) if profile_scores else 0
    return Score(value=val, reason="heuristic (LLM unavailable): title + skill match",
                 tags=["heuristic"], ok=True, profile_scores=profile_scores)


class HeuristicProvider:
    """Scores deterministically, no network. Used keyless and as the LLM fallback."""

    async def score(self, posting: Posting, profiles: list[Profile]) -> Score:
        if len(profiles) <= 1:
            return heuristic_score(posting, profiles[0])
        return heuristic_multi_score(posting, profiles)


class FallbackProvider:
    """Try the primary (LLM) provider; if it errors (score.ok is False, e.g. a 429), fall
    back to the deterministic heuristic so an LLM outage degrades to lower-precision
    coverage instead of zero coverage."""

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback

    async def score(self, posting: Posting, profiles: list[Profile]) -> Score:
        s = await self.primary.score(posting, profiles)
        return s if s.ok else await self.fallback.score(posting, profiles)


class FakeProvider:
    """Constant-score provider for tests and keyless smoke runs."""

    def __init__(self, value: int = 70, reason: str = "fake", tags=None, profile_values=None):
        self.value = value
        self.reason = reason
        self.tags = tags or []
        self.profile_values = profile_values  # optional {name: score}

    async def score(self, posting: Posting, profiles: list[Profile]) -> Score:
        if self.profile_values:
            ps = {n: self.profile_values.get(n, self.value) for n in (p.name for p in profiles)}
            return Score(max(ps.values()), self.reason, list(self.tags), profile_scores=ps)
        if len(profiles) == 1:
            return Score(self.value, self.reason, list(self.tags),
                         profile_scores={profiles[0].name: self.value})
        ps = {p.name: self.value for p in profiles}
        return Score(self.value, self.reason, list(self.tags), profile_scores=ps)
