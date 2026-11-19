from horizondb_readiness.checks import Severity, SourceFacts, assess, summary


def codes(findings, severity=None):
    return {f.code for f in findings if severity is None or f.severity is severity}


def test_clean_pg17_source_has_no_blockers():
    f = SourceFacts(server_version_num=170006, extensions={"plpgsql": "1.0", "vector": "0.8.0", "pg_trgm": "1.6"})
    out = assess(f)
    assert codes(out, Severity.BLOCKER) == set()
    assert {"allowlist:vector", "allowlist:pg_trgm"} <= codes(out, Severity.INFO)
    assert "allowlist:plpgsql" not in codes(out)


def test_major_versions():
    assert "major_version" in codes(assess(SourceFacts(160004, {})), Severity.BLOCKER)
    assert "major_version" in codes(assess(SourceFacts(180001, {})), Severity.ACTION)
    assert "major_version" not in codes(assess(SourceFacts(170002, {})))


def test_extensions_missing_unsupported_older_and_newer():
    out = assess(SourceFacts(170002, {
        "timescaledb": "2.17.0",        # not offered
        "pg_failover_slots": "1.1.0",   # listed as not supported
        "vector": "0.8.1",              # newer than offered 0.8.0
        "postgis": "3.4.2",             # older than offered 3.5.2
    }))
    assert {"extension:timescaledb", "extension:pg_failover_slots"} <= codes(out, Severity.BLOCKER)
    assert "extension:vector" in codes(out, Severity.ACTION)
    assert "extension:postgis" in codes(out, Severity.INFO)


def test_version_comparison_is_numeric_not_textual():
    # "1.10" is newer than "1.6": a string comparison would get this wrong.
    out = assess(SourceFacts(170002, {"citext": "1.10"}))
    assert "extension:citext" in codes(out, Severity.ACTION)


def test_replication_keys_pooling_and_inventory_items():
    out = assess(SourceFacts(
        170002, {}, logical_slots=2, tables_without_pk=[f"public.t{i}" for i in range(7)],
        max_connections=500, peak_connections=420,
        uses_geo_replica=True, needs_vnet_injection=True, needs_cmk_and_geo_backup=True, backup_retention_days=365,
    ))
    assert {"logical_slots", "no_primary_key", "connection_pooling"} <= codes(out, Severity.ACTION)
    assert {"cross_region_readers", "vnet_injection", "cmk_with_geo_backup", "long_term_retention"} <= codes(out, Severity.BLOCKER)
    msg = next(f.message for f in out if f.code == "no_primary_key")
    assert "7 table(s)" in msg and "and 2 more" in msg


def test_low_connection_use_is_not_flagged_and_summary_counts():
    out = assess(SourceFacts(160004, {"vector": "0.8.0"}, max_connections=200, peak_connections=40))
    assert "connection_pooling" not in codes(out)
    assert summary(out) == {"blocker": 1, "action": 0, "info": 1}
