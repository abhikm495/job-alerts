from job_radar.seed import parse_line, merge, main, repair_token_region


def test_parse_line_valid_and_invalid():
    assert parse_line("stripe, greenhouse, dream") == {"slug": "stripe", "ats": "greenhouse", "tier": "dream"}
    assert parse_line("ramp,ashby") == {"slug": "ramp", "ats": "ashby", "tier": "target"}
    assert parse_line("acme\tlever") == {"slug": "acme", "ats": "lever", "tier": "target"}
    assert parse_line("# a comment") is None
    assert parse_line("") is None
    assert parse_line("onlyslug") is None
    assert parse_line("acme, notarealats") is None  # unknown ats rejected


def test_parse_line_workday_needs_host_and_site():
    assert parse_line("nvidia,workday,dream,wd5,NVIDIASite") == {
        "slug": "nvidia", "ats": "workday", "tier": "dream",
        "wd_host": "wd5", "wd_site": "NVIDIASite"}
    assert parse_line("nvidia,workday,dream") is None  # missing host/site -> rejected
    # An empty field must be rejected, not silently shifted into a later column.
    assert parse_line("nvidia,workday,dream,,NVIDIASite") is None  # empty wd_host
    assert parse_line("nvidia,workday,dream,wd5,") is None         # empty wd_site


def test_merge_dedups_and_adds():
    existing = [{"slug": "stripe", "ats": "greenhouse", "tier": "target"}]
    lines = [
        "stripe, greenhouse",          # dup -> skipped
        "ramp, ashby, target",         # new
        "stripe, lever",               # same slug, different ats -> new
        "# comment",                   # ignored
    ]
    out, added = merge(existing, lines)
    assert added == 2
    keys = {(c["slug"], c["ats"]) for c in out}
    assert ("ramp", "ashby") in keys and ("stripe", "lever") in keys


def test_parse_line_region_and_token_columns():
    assert parse_line("atheneum,recruitee,target,,germany") == {
        "slug": "atheneum", "ats": "recruitee", "tier": "target", "region": "germany",
    }
    assert parse_line("alteos,personio,target,germany") == {
        "slug": "alteos", "ats": "personio", "tier": "target", "region": "germany",
    }
    assert parse_line("chargebee,linkedin,target,,india") == {
        "slug": "chargebee", "ats": "linkedin", "tier": "target", "region": "india",
    }
    assert parse_line("acme,eightfold,target,acme.eightfold.ai,germany") == {
        "slug": "acme", "ats": "eightfold", "tier": "target",
        "token": "acme.eightfold.ai", "region": "germany",
    }


def test_repair_token_region_moves_misplaced_hints():
    companies = [
        {"slug": "alteos", "ats": "personio", "tier": "target", "token": "germany"},
        {"slug": "chargebee", "ats": "linkedin", "tier": "target", "token": "india"},
        {"slug": "publicissapient", "ats": "publicissapient", "tier": "target", "token": "India"},
    ]
    assert repair_token_region(companies) == 2
    assert companies[0] == {"slug": "alteos", "ats": "personio", "tier": "target", "region": "germany"}
    assert companies[1] == {
        "slug": "chargebee", "ats": "linkedin", "tier": "target", "token": "chargebee", "region": "india",
    }
    assert companies[2]["token"] == "India"


def test_main_writes_yaml(tmp_path):
    src = tmp_path / "list.csv"
    src.write_text("ramp, ashby, dream\ncohere, ashby\n# skip me\n")
    cfg = tmp_path / "companies.yaml"
    cfg.write_text("companies:\n  - {slug: stripe, ats: greenhouse, tier: target}\n")

    rc = main([str(src), str(cfg)])
    assert rc == 0

    import yaml
    data = yaml.safe_load(cfg.read_text())
    slugs = {(c["slug"], c["ats"]) for c in data["companies"]}
    assert ("stripe", "greenhouse") in slugs
    assert ("ramp", "ashby") in slugs
    assert ("cohere", "ashby") in slugs


def test_main_repair_flag(tmp_path):
    cfg = tmp_path / "companies.yaml"
    cfg.write_text(
        "companies:\n"
        "  - {slug: alteos, ats: personio, tier: target, token: germany}\n"
    )
    rc = main(["--repair", str(cfg)])
    assert rc == 0

    import yaml
    data = yaml.safe_load(cfg.read_text())
    assert data["companies"][0] == {"slug": "alteos", "ats": "personio", "tier": "target", "region": "germany"}
