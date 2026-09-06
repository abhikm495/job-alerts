import os
from dataclasses import dataclass, replace

import yaml

from .models import Company, Profile


@dataclass(frozen=True)
class Settings:
    llm_api_key: str | None
    llm_model: str          # "" => provider default
    llm_provider: str       # "gemini" | "claude"
    role_id: str | None
    seen_path: str
    dry_run: bool
    webhook_url_in: str | None = None
    webhook_url_de: str | None = None
    webhook_url_other: str | None = None
    webhook_url_debug: str | None = None
    sheet_id: str | None = None    # Google Sheet to mirror matches into (None => off)
    creds_path: str | None = None  # service-account JSON for that Sheet


@dataclass(frozen=True)
class Config:
    profile: Profile
    companies: list[Company]
    settings: Settings


def load_profile(path: str) -> Profile:
    with open(path) as f:
        d = yaml.safe_load(f)
    low = lambda xs: [str(s).lower() for s in (xs or [])]
    return Profile(
        summary=d["summary"],
        title_include=low(d.get("title_include")),
        title_exclude=low(d.get("title_exclude")),
        locations_allow=low(d.get("locations_allow")),
        locations_block=low(d.get("locations_block")),
        freshness_days=int(d.get("freshness_days", 21)),
        ping_threshold=int(d.get("ping_threshold", 65)),
        digest_threshold=int(d.get("digest_threshold", 50)),
        high_score=int(d.get("high_score", 80)),
        high_fresh_hours=int(d.get("high_fresh_hours", 2)),
    )


def load_companies(path: str) -> list[Company]:
    with open(path) as f:
        d = yaml.safe_load(f)
    out = []
    for c in d.get("companies", []):
        out.append(Company(
            slug=c["slug"], ats=str(c["ats"]).lower(), tier=str(c.get("tier", "target")).lower(),
            wd_host=c.get("wd_host"), wd_site=c.get("wd_site"),
            token=c.get("token"), region=c.get("region"),
        ))
    return out


def _truthy(v: str) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on")


def any_discord_webhook(settings: Settings) -> bool:
    return bool(settings.webhook_url_in or settings.webhook_url_de
                or settings.webhook_url_other or settings.webhook_url_debug)


def remind_webhook(settings: Settings) -> str | None:
    """Webhook for non-regional messages (e.g. daily Sheet reminders)."""
    return settings.webhook_url_other or settings.webhook_url_in or settings.webhook_url_de


def load_settings() -> Settings:
    webhook_in = os.environ.get("DISCORD_WEBHOOK_URL_IN") or None
    webhook_de = os.environ.get("DISCORD_WEBHOOK_URL_DE") or None
    webhook_other = os.environ.get("DISCORD_WEBHOOK_URL_OTHER") or None
    webhook_debug = os.environ.get("DISCORD_WEBHOOK_URL_DEBUG") or None
    key = os.environ.get("LLM_API_KEY") or None
    settings = Settings(
        webhook_url_in=webhook_in,
        webhook_url_de=webhook_de,
        webhook_url_other=webhook_other,
        webhook_url_debug=webhook_debug,
        llm_api_key=key,
        llm_model=os.environ.get("LLM_MODEL", ""),
        llm_provider=(os.environ.get("LLM_PROVIDER") or "gemini").lower(),
        role_id=os.environ.get("DISCORD_ROLE_ID") or None,
        seen_path=os.environ.get("SEEN_PATH", ".state/seen.json"),
        dry_run=_truthy(os.environ.get("DRY_RUN", "")),
        sheet_id=os.environ.get("GOOGLE_SHEET_ID") or None,
        creds_path=os.environ.get("GOOGLE_CREDENTIALS_PATH") or None,
    )
    if settings.dry_run:
        return settings
    if not any_discord_webhook(settings):
        return replace(settings, dry_run=True)
    return settings


def load_config(profile_path: str = "config/profile.yaml",
                companies_path: str = "config/companies.yaml") -> Config:
    return Config(load_profile(profile_path), load_companies(companies_path), load_settings())
