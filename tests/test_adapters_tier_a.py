import json
from pathlib import Path

import httpx

from job_radar.models import Company
from job_radar.adapters import personio, recruitee, eightfold

FIX_RECRUITEE = {
    "offers": [{
        "id": 42, "title": "Engineer", "location": "Berlin",
        "careers_url": "https://x.recruitee.com/o/engineer",
        "published_at": "2026-06-01T00:00:00Z", "description": "<p>Build</p>",
    }]
}

PERSONIO_XML = """<?xml version="1.0"?>
<workzag-jobs>
  <position>
    <id>9</id>
    <name>Developer</name>
    <office>Berlin</office>
    <createdAt>2026-06-01T00:00:00Z</createdAt>
  </position>
</workzag-jobs>"""


def test_personio_parse():
    posts = personio.parse("alteos", PERSONIO_XML)
    assert len(posts) == 1
    assert posts[0].uid == "personio:alteos:9"
    assert posts[0].title == "Developer"


def test_recruitee_parse():
    posts = recruitee.parse("atheneum", FIX_RECRUITEE)
    assert posts[0].uid == "recruitee:atheneum:42"
    assert "Build" in posts[0].description


def test_eightfold_parse():
    data = {"positions": [{"id": 7, "name": "Analyst", "locations": ["Mumbai"]}]}
    posts = eightfold.parse("ms", "morganstanley.eightfold.ai", data)
    assert posts[0].location == "Mumbai"


async def test_recruitee_fetch():
    def handler(request):
        return httpx.Response(200, json=FIX_RECRUITEE)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        posts = await recruitee.fetch(client, Company(slug="atheneum", ats="recruitee"))
    assert len(posts) == 1
