"""Minimal HTML/JSON description extraction helpers."""

from __future__ import annotations

import json
import re
from html import unescape

from .base import strip_html

MAX_DESC_LEN = 15_000
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_BREEZY_DESC = re.compile(r'"description"\s*:\s*"((?:\\.|[^"\\])*)"')
_META_DESC = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_META_DESC_REV = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']', re.I)
_META_OG = re.compile(
    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_JSON_LD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
_JOB_DESC_BLOCK = re.compile(
    r'(?:class|id)=["\'][^"\']*(?:job-description|jobdescription|posting-description|description-text)[^"\']*["\'][^>]*>([\s\S]*?)</(?:div|section)>',
    re.I,
)


def truncate(text: str, max_len: int = MAX_DESC_LEN) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def combine_parts(*parts: str) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        text = strip_html(part) if "<" in (part or "") else (part or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return "\n".join(out)


def _decode_json_string(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw.encode("utf-8", errors="ignore").decode("unicode_escape", errors="ignore")


def load_next_data(html: str) -> dict | None:
    match = _NEXT_DATA.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def extract_join_description(page_data: dict) -> str:
    state = page_data.get("props", {}).get("pageProps", {}).get("initialState", {})
    job = state.get("job") or {}
    return truncate(combine_parts(
        job.get("description") or "",
        job.get("intro") or "",
        job.get("tasks") or "",
        job.get("requirements") or "",
        job.get("schemaDescription") or "",
    ))


def extract_breezy_description(html: str) -> str:
    match = _BREEZY_DESC.search(html)
    if match:
        return truncate(strip_html(_decode_json_string(match.group(1))))
    return extract_from_html(html)


def extract_from_html(html: str) -> str:
    parts: list[str] = []
    for match in _JSON_LD.finditer(html):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                desc = item.get("description")
                if desc:
                    parts.append(strip_html(str(desc)))

    for pattern in (_META_OG, _META_DESC, _META_DESC_REV):
        match = pattern.search(html)
        if match:
            parts.append(strip_html(unescape(match.group(1))))

    block = _JOB_DESC_BLOCK.search(html)
    if block:
        parts.append(strip_html(block.group(1)))

    return truncate(combine_parts(*parts))


def personio_position_description(position) -> str:
    import xml.etree.ElementTree as ET

    descriptions = position.find("jobDescriptions")
    if descriptions is None:
        return ""
    parts: list[str] = []
    for node in descriptions.findall("jobDescription"):
        raw = ET.tostring(node, encoding="unicode", method="html")
        inner = re.sub(r"^<jobDescription[^>]*>|</jobDescription>$", "", raw, flags=re.S)
        text = strip_html(inner)
        if text:
            parts.append(text)
    return truncate(combine_parts(*parts))
