"""Classify job locations into notification regions."""

from __future__ import annotations

from typing import Literal

Region = Literal["india", "germany", "other"]

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


def classify_region(location: str, *, hint: str | None = None) -> Region:
    """Return india / germany / other from a location string (and optional company hint)."""
    loc = (location or "").lower().strip()
    if loc:
        if any(h in loc for h in _INDIA):
            return "india"
        if any(h in loc for h in _GERMANY):
            return "germany"
        return "other"
    hint = (hint or "").lower().strip()
    if hint in ("india", "in"):
        return "india"
    if hint in ("germany", "de"):
        return "germany"
    return "other"
