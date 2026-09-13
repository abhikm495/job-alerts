"""Classify job locations into notification regions."""

from __future__ import annotations

from typing import Literal

# Adzuna-supported ISO country codes (also used as Discord webhook region keys).
ADZUNA_COUNTRIES = frozenset({
    "au", "at", "be", "br", "ca", "fr", "de", "in", "it", "mx",
    "nl", "nz", "pl", "sg", "za", "es", "ch", "gb",
})

Region = Literal[
    "india", "germany", "other",
    "au", "at", "be", "br", "ca", "fr", "de", "in", "it", "mx",
    "nl", "nz", "pl", "sg", "za", "es", "ch", "gb",
]

_INDIA = (
    "india", "bengaluru", "bangalore", "blr", "hyderabad", "mumbai", "pune",
    "chennai", "noida", "gurgaon", "gurugram", "delhi", "kolkata", "remote - india",
    "remote india", "india remote", "work from india",
)
_GERMANY = (
    "germany", "deutschland", "berlin", "munich", "münchen", "munchen", "hamburg",
    "frankfurt", "cologne", "köln", "stuttgart", "düsseldorf", "dusseldorf",
    "remote - germany", "remote germany", "germany remote",
)

_HINT_ALIASES = {
    "uk": "gb",
    "united kingdom": "gb",
}


def webhook_region(region: str) -> str:
    """Normalize a region label to the env-var suffix (DISCORD_WEBHOOK_URL_{X})."""
    key = (region or "").lower().strip()
    if key == "india":
        return "in"
    if key == "germany":
        return "de"
    return _HINT_ALIASES.get(key, key)


def classify_region(location: str, *, hint: str | None = None) -> str:
    """Return a region key for Discord routing.

    Adzuna boards set ``region`` to a 2-letter country code; that hint wins when valid.
    Legacy boards use ``india`` / ``germany``. Otherwise fall back to location parsing.
    """
    raw_hint = (hint or "").lower().strip()
    if raw_hint == "india":
        return "india"
    if raw_hint == "germany":
        return "germany"
    hint_key = webhook_region(raw_hint)
    if hint_key in ADZUNA_COUNTRIES:
        return hint_key

    loc = (location or "").lower().strip()
    if loc:
        if any(h in loc for h in _INDIA):
            return "india"
        if any(h in loc for h in _GERMANY):
            return "germany"
        return "other"
    return "other"
