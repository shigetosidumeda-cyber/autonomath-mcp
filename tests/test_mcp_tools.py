"""MCP tool handler tests — fills src/jpintel_mcp/mcp/server.py coverage gap.

The @mcp.tool() decorator keeps the wrapped callable as a plain Python
function, so we can call it directly without spinning up an MCP transport.
These tests share the `seeded_db` fixture from conftest.py so the connect()
inside each tool hits the same test DB the REST-layer tests use.

Goal: exercise the 5 public MCP tools the way a real client (Claude
Desktop, Cursor, Cline, etc.) would, not the REST mirrors. Parity
between MCP + REST is documented in `research/mcp_rest_parity.md`; this
file is the test-level guarantee.
"""

from __future__ import annotations

import pytest

# Import every tool once at module level so coverage sees them even if a
# subset of tests are skipped.
from jpintel_mcp.mcp.server import (
    _resolve_fields,
    _row_to_dict,
    _trim_to_fields,
    batch_get_programs,
    check_exclusions,
    enum_values,
    get_meta,
    get_program,
    list_exclusion_rules,
    regulatory_prep_pack,
    search_programs,
)

# ---------------------------------------------------------------------------
# _resolve_fields — the only non-tool helper with actual branching logic.
# ---------------------------------------------------------------------------


def test_resolve_fields_defaults_to_default():
    assert _resolve_fields(None) == "default"


def test_resolve_fields_accepts_whitelisted_values():
    for v in ("minimal", "default", "full"):
        assert _resolve_fields(v) == v


def test_resolve_fields_rejects_unknown_with_descriptive_error():
    with pytest.raises(ValueError) as exc:
        _resolve_fields("everything")
    msg = str(exc.value)
    assert "fields must be one of" in msg
    assert "'everything'" in msg


# ---------------------------------------------------------------------------
# search_programs
# ---------------------------------------------------------------------------


def test_search_programs_returns_seeded_rows_with_pagination_envelope(client, seeded_db):
    """Baseline: no filters → every non-excluded seeded program, paginated."""
    # `client` fixture is required here ONLY so the app import runs before
    # we touch the DB from the MCP side. It also ensures the test DB path
    # env is applied to the module under test.
    res = search_programs()
    # Required envelope keys (dd_v4_08 / v8 P3-L adds meta + retrieval_note;
    # callers may see additional optional keys like input_warnings).
    assert {"total", "limit", "offset", "results"} <= set(res.keys())
    assert "data_as_of" in res.get("meta", {})
    assert res["limit"] == 20
    assert res["offset"] == 0
    # 3 non-excluded programs in conftest (S, A, B); X is excluded by default.
    assert res["total"] == 3
    ids = {r["unified_id"] for r in res["results"]}
    assert "UNI-test-s-1" in ids
    assert "UNI-test-a-1" in ids
    assert "UNI-test-b-1" in ids
    assert "UNI-test-x-1" not in ids


def test_search_programs_tier_filter_narrows_results(client, seeded_db):
    res = search_programs(tier=["S"])
    assert res["total"] == 1
    assert res["results"][0]["unified_id"] == "UNI-test-s-1"


def test_search_programs_prefecture_filter(client, seeded_db):
    res = search_programs(prefecture="青森県")
    assert res["total"] == 1
    assert res["results"][0]["unified_id"] == "UNI-test-a-1"


def test_search_programs_short_query_falls_back_to_substring_like(client, seeded_db):
    """Query <3 chars: LIKE fallback path (not FTS5)."""
    # Single-char query triggers the `len(q_clean) < 3` branch.
    res = search_programs(q="B")
    assert res["total"] >= 1
    assert any("B-tier" in r["primary_name"] for r in res["results"])


def test_search_programs_long_query_uses_fts_match(client, seeded_db):
    """3+ chars → FTS5 MATCH path."""
    # Seeded enriched_text == primary_name, so a substring works through FTS.
    res = search_programs(q="青森")
    assert res["total"] >= 1
    assert any("青森" in r["primary_name"] for r in res["results"])


def test_search_programs_fields_minimal_returns_whitelist_only(client, seeded_db):
    from jpintel_mcp.models import MINIMAL_FIELD_WHITELIST

    res = search_programs(fields="minimal")
    assert res["results"], "need at least one row to inspect shape"
    row = res["results"][0]
    assert set(row.keys()) == set(MINIMAL_FIELD_WHITELIST)


def test_search_programs_fields_full_includes_enriched_and_lineage_keys(client, seeded_db):
    res = search_programs(fields="full")
    row = res["results"][0]
    # `full` guarantees these keys are present (even if null).
    for k in ("enriched", "source_mentions", "source_url", "source_fetched_at", "source_checksum"):
        assert k in row


def test_search_programs_invalid_fields_raises_valueerror(client, seeded_db):
    res = search_programs(fields="garbage")
    assert res["total"] == 0
    assert res["results"] == []
    assert res["error"]["code"] == "internal"
    assert res["error"]["incident_id"]
    assert "garbage" not in res["error"]["message"]


def test_search_programs_limit_clamps_above_100(client, seeded_db):
    """Limit >100 must cap at the token-shaping cap of 20 (dd_v3_09 / v8 P3-K).

    Pydantic field validation rejects limit>100 at the schema layer, but
    MCP tool calls bypass schema validation; _enforce_limit_cap() then
    drops it to 20 with an input_warnings entry.
    """
    res = search_programs(limit=10_000)
    assert res["limit"] == 20
    warns = res.get("input_warnings", [])
    assert any(w.get("code") == "limit_capped" for w in warns)


def test_search_programs_limit_clamps_below_1(client, seeded_db):
    res = search_programs(limit=0)
    assert res["limit"] == 1


def test_search_programs_amount_filter_inclusive_bound(client, seeded_db):
    """amount_min_man_yen=500 → UNI-test-a-1 (500) and UNI-test-s-1 (1000)."""
    res = search_programs(amount_min_man_yen=500)
    ids = {r["unified_id"] for r in res["results"]}
    # Seeded B-tier has amount_max=30000 which is >=500 too.
    assert ids == {"UNI-test-s-1", "UNI-test-a-1", "UNI-test-b-1"}


def test_search_programs_funding_purpose_filter_matches_json_substring(client, seeded_db):
    res = search_programs(funding_purpose=["設備投資"])
    ids = {r["unified_id"] for r in res["results"]}
    assert "UNI-test-s-1" in ids


def test_search_programs_target_type_filter_matches_json_substring(client, seeded_db):
    res = search_programs(target_type=["認定新規就農者"])
    ids = {r["unified_id"] for r in res["results"]}
    assert "UNI-test-a-1" in ids


# ---------------------------------------------------------------------------
# get_program
# ---------------------------------------------------------------------------


def test_get_program_returns_detail_shape(client, seeded_db):
    rec = get_program("UNI-test-s-1")
    assert rec["unified_id"] == "UNI-test-s-1"
    assert rec["primary_name"] == "テスト S-tier 補助金"
    assert rec["tier"] == "S"


def test_get_program_returns_error_envelope_on_missing_id(client, seeded_db):
    rec = get_program("UNI-does-not-exist")
    assert rec.get("code") == "no_matching_records"
    assert "not found" in rec.get("error", "")


def test_get_program_minimal_fields_returns_whitelist(client, seeded_db):
    from jpintel_mcp.models import MINIMAL_FIELD_WHITELIST

    rec = get_program("UNI-test-s-1", fields="minimal")
    # Production wraps the response in an additive envelope (status,
    # api_version, tool_name, latency_ms, ...); subset assertion verifies
    # the whitelist is present without rejecting envelope additions.
    assert set(MINIMAL_FIELD_WHITELIST).issubset(set(rec.keys()))


# ---------------------------------------------------------------------------
# batch_get_programs — parity contract with REST /v1/programs/batch
# ---------------------------------------------------------------------------


def test_batch_get_programs_returns_results_and_not_found(client, seeded_db):
    res = batch_get_programs(["UNI-test-s-1", "UNI-missing-1", "UNI-test-a-1"])
    found_ids = [r["unified_id"] for r in res["results"]]
    assert "UNI-test-s-1" in found_ids
    assert "UNI-test-a-1" in found_ids
    assert res["not_found"] == ["UNI-missing-1"]


def test_batch_get_programs_dedupes_preserving_order(client, seeded_db):
    """Duplicate ids collapse; first-occurrence order preserved in results."""
    res = batch_get_programs(
        ["UNI-test-a-1", "UNI-test-s-1", "UNI-test-a-1"]  # 'a' repeated
    )
    order = [r["unified_id"] for r in res["results"]]
    assert order == ["UNI-test-a-1", "UNI-test-s-1"]


def test_batch_get_programs_empty_list_returns_error_envelope(client, seeded_db):
    res = batch_get_programs([])
    assert isinstance(res.get("error"), dict), "expected nested error envelope"
    assert res["error"]["code"] == "empty_input"
    assert "retry_with" in res["error"]
    # Empty payload fields still present so MCP clients can render them.
    assert res["results"] == []
    assert res["not_found"] == []


def test_batch_get_programs_over_50_returns_error_envelope(client, seeded_db):
    ids = [f"UNI-{i}" for i in range(51)]
    res = batch_get_programs(ids)
    assert isinstance(res.get("error"), dict), "expected nested error envelope"
    assert res["error"]["code"] == "limit_exceeded"
    assert "50" in res["error"]["message"]
    assert "retry_with" in res["error"]


def test_batch_get_programs_full_contract_always_has_enriched_keys(client, seeded_db):
    res = batch_get_programs(["UNI-test-s-1"])
    rec = res["results"][0]
    # Batch uses the "full" contract — keys always present even if null.
    for k in ("enriched", "source_mentions", "source_url", "source_fetched_at", "source_checksum"):
        assert k in rec


# ---------------------------------------------------------------------------
# list_exclusion_rules + check_exclusions
# ---------------------------------------------------------------------------


def test_list_exclusion_rules_returns_full_shape(client, seeded_db):
    # α11: list_exclusion_rules now always returns the unified envelope
    # `{"rules": [...], "total": int, "filters": {...}}` (was union of
    # bare list on hit + dict on miss).
    resp = list_exclusion_rules()
    assert isinstance(resp, dict)
    assert {"rules", "total", "filters"} <= set(resp.keys())
    rules = resp["rules"]
    assert resp["total"] == len(rules)
    assert len(rules) >= 2
    ids = {r["rule_id"] for r in rules}
    assert "excl-test-mutex" in ids
    assert "excl-test-prereq" in ids
    rule = next(r for r in rules if r["rule_id"] == "excl-test-mutex")
    # Shape parity: every expected key present.
    for k in (
        "rule_id",
        "kind",
        "severity",
        "program_a",
        "program_b",
        "program_b_group",
        "description",
        "source_notes",
        "source_urls",
        "extra",
    ):
        assert k in rule


def test_check_exclusions_detects_mutex_hit(client, seeded_db):
    """Both legs of the mutex in one candidate set → rule fires."""
    res = check_exclusions(["keiei-kaishi-shikin", "koyo-shuno-shikin"])
    assert res["checked_rules"] >= 2
    hits_ids = {h["rule_id"] for h in res["hits"]}
    assert "excl-test-mutex" in hits_ids
    hit = next(h for h in res["hits"] if h["rule_id"] == "excl-test-mutex")
    assert set(hit["programs_involved"]) == {"keiei-kaishi-shikin", "koyo-shuno-shikin"}


def test_check_exclusions_prerequisite_fires_on_single_hit(client, seeded_db):
    """kind=prerequisite triggers as long as *any* referenced program is in set."""
    res = check_exclusions(["seinen-shuno-shikin"])  # only the A leg
    hits_ids = {h["rule_id"] for h in res["hits"]}
    assert "excl-test-prereq" in hits_ids


def test_check_exclusions_no_conflict_when_only_one_mutex_leg(client, seeded_db):
    """Only program_a of a mutex present → NOT a hit (needs both legs)."""
    res = check_exclusions(["keiei-kaishi-shikin"])
    hits_ids = {h["rule_id"] for h in res["hits"]}
    # Mutex rule requires len(candidates)>=2.
    assert "excl-test-mutex" not in hits_ids


def test_check_exclusions_empty_input_returns_error_envelope(client, seeded_db):
    res = check_exclusions([])
    assert isinstance(res.get("error"), dict), "expected nested error envelope"
    assert res["error"]["code"] == "empty_input"
    assert "retry_with" in res["error"]
    # Empty payload fields still surface.
    assert res["hits"] == []
    assert res["checked_rules"] == 0


def test_check_exclusions_dual_key_unified_id_hits_name_keyed_rule(client, seeded_db):
    """Migration 051 / P0-3: caller passes UNI-* but the rule's program_a
    is a Japanese name string. The rule's program_a_uid resolves to the
    same unified_id, so a hit must surface (no silent miss)."""
    res = check_exclusions(["UNI-test-s-1", "UNI-test-b-1"])
    hits_ids = {h["rule_id"] for h in res["hits"]}
    assert "excl-test-uid-mutex" in hits_ids, (
        f"unified_id input failed to resolve name-keyed rule via _uid: hits={hits_ids}"
    )


def test_check_exclusions_dual_key_primary_name_hits_uid_keyed_rule(client, seeded_db):
    """Reverse direction: caller passes the primary_name strings and the
    rule's _uid columns are populated. Either form must hit the rule."""
    res = check_exclusions(
        [
            "テスト S-tier 補助金",
            "B-tier 融資 スーパーL資金",
        ]
    )
    hits_ids = {h["rule_id"] for h in res["hits"]}
    assert "excl-test-uid-mutex" in hits_ids, (
        f"primary_name input failed to resolve uid-keyed rule: hits={hits_ids}"
    )


# ---------------------------------------------------------------------------
# get_meta
# ---------------------------------------------------------------------------


def test_get_meta_returns_tier_and_prefecture_counts(client, seeded_db):
    m = get_meta()
    assert m["total_programs"] >= 3  # Public searchable rows only: S, A, B.
    assert m["visible_programs"] == m["total_programs"]
    assert m["exclusion_rules_count"] >= 2
    assert "tier_counts" in m
    # Seeded non-excluded tiers present. The excluded=1 X row is filtered
    # out of tier_counts (matches search gate: COALESCE(tier,'X') != 'X').
    for t in ("S", "A", "B"):
        assert m["tier_counts"].get(t) is not None, f"missing tier {t}"
    assert "X" not in m["tier_counts"]
    assert m["total_programs"] == sum(m["tier_counts"].values())
    assert m["total_programs"] == sum(m["prefecture_counts"].values())
    assert m["canonical_programs"] + m["external_programs"] == m["total_programs"]
    assert "prefecture_counts" in m
    # Data-driven: actual corpus has many 東京都/青森県 rows beyond the seeded 1
    # — relax to >=1 so the assertion tracks live data rather than the seed.
    assert m["prefecture_counts"].get("東京都", 0) >= 1
    assert m["prefecture_counts"].get("青森県", 0) >= 1
    assert "last_ingested_at" in m


# ---------------------------------------------------------------------------
# Internal _row_to_dict / _trim_to_fields — exercise edge cases
# ---------------------------------------------------------------------------


def test_row_to_dict_handles_missing_lineage_columns(client, seeded_db):
    """When a very old DB skipped the 001 lineage migration, the helper must
    return None for source_url / source_fetched_at / source_checksum rather
    than KeyError."""
    import sqlite3

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    row = c.execute("SELECT * FROM programs WHERE unified_id = ?", ("UNI-test-s-1",)).fetchone()
    c.close()
    d = _row_to_dict(row, include_enriched=False)
    # Lineage keys always present in the output dict.
    assert "source_url" in d
    assert "source_fetched_at" in d
    assert "source_checksum" in d


def test_trim_to_fields_full_sets_missing_keys_to_none():
    rec = {"unified_id": "UNI-a", "primary_name": "x"}
    out = _trim_to_fields(rec, "full")
    # full contract: enriched/source_mentions/lineage keys always set.
    for k in ("enriched", "source_mentions", "source_url", "source_fetched_at", "source_checksum"):
        assert k in out
        assert out[k] is None


# ---------------------------------------------------------------------------
# enum_values — guardrail against hallucinated filter values
# ---------------------------------------------------------------------------


def test_enum_values_target_type_returns_frequency_ranked(client, seeded_db):
    """target_types_json is a JSON array column; enum_values must expand
    it via json_each and return top-N by row-count, not alphabetical."""
    out = enum_values(field="target_type", limit=10)
    assert out["field"] == "target_type"
    assert out["limit"] == 10
    assert out["total_distinct"] >= 1
    vals = out["values"]
    assert isinstance(vals, list) and vals, "expected at least one target_type"
    # sorted DESC by count
    counts = [v["count"] for v in vals]
    assert counts == sorted(counts, reverse=True)
    # each row has the expected shape
    assert {"value", "count"} <= set(vals[0].keys())


def test_enum_values_program_kind_scalar_column(client, seeded_db):
    out = enum_values(field="program_kind", limit=5)
    assert out["field"] == "program_kind"
    # Seed has '補助金' + '融資', so at least 2 distinct kinds after excluded filter
    vals_list = [v["value"] for v in out["values"]]
    assert "補助金" in vals_list or "融資" in vals_list


def test_enum_values_clamps_limit(client, seeded_db):
    out_big = enum_values(field="authority_level", limit=999)
    assert out_big["limit"] == 200
    out_small = enum_values(field="authority_level", limit=0)
    assert out_small["limit"] == 1


def test_enum_values_event_type_from_enforcement_table(client, seeded_db):
    """event_type is sourced from enforcement_cases, not programs. The seed
    DB may not have enforcement rows; enum_values must degrade to empty
    values + total_distinct=0 rather than raise."""
    out = enum_values(field="event_type", limit=5)
    assert out["field"] == "event_type"
    assert out["total_distinct"] >= 0
    assert isinstance(out["values"], list)


def test_enum_values_rejects_unknown_field(client, seeded_db):
    """Unknown field returns a canonical error envelope with code and
    valid_fields list. Silent fallback to a default would mask LLM typos."""
    out = enum_values(field="not_a_real_field", limit=5)  # type: ignore[arg-type]
    assert out.get("code") == "invalid_field"
    assert "unknown field" in out.get("error", "")
    assert isinstance(out.get("valid_fields"), list) and out["valid_fields"]


# ---------------------------------------------------------------------------
# regulatory_prep_pack — one-shot compliance discovery (laws + certs +
# tax_rulesets + recent_enforcement). Hits the real test DB; the
# `_seed_regulatory_prep` fixture pre-loads 4 laws / 2 certifications
# (via programs.program_kind LIKE 'certification%') / 3 tax_rulesets / 2
# enforcement_cases — the smallest set that exercises every section,
# the include_expired toggle, and the empty-error branch.
# ---------------------------------------------------------------------------


@pytest.fixture
def _seed_regulatory_prep(seeded_db):
    import sqlite3
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    c = sqlite3.connect(seeded_db)
    try:
        # Idempotent: clean any leftover rows from a previous test run.
        c.execute("DELETE FROM laws WHERE unified_id LIKE 'LAW-aaaaaa%'")
        c.execute("DELETE FROM tax_rulesets WHERE unified_id LIKE 'TAX-aaaaaa%'")
        c.execute("DELETE FROM enforcement_cases WHERE case_id LIKE 'ENF-test%'")
        c.execute("DELETE FROM programs WHERE unified_id IN ('UNI-cert-1','UNI-cert-2')")
        # 2 laws that match '製造' (E=manufacturing) + 1 unrelated.
        for lid, title, summary, status in [
            ("LAW-aaaaaa0001", "製造業安全衛生法", "製造ラインの安全管理。", "current"),
            ("LAW-aaaaaa0002", "繊維製造監督令", "繊維製造の届出。", "current"),
            ("LAW-aaaaaa0003", "金融商品取引法", "投資商品 規制。", "current"),
            ("LAW-aaaaaa0004", "旧 製造業税法", "製造業 旧税制 (廃止)。", "repealed"),
        ]:
            c.execute(
                """INSERT INTO laws(unified_id, law_number, law_title, law_type,
                       revision_status, summary, source_url, fetched_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    lid,
                    "test法律第1号",
                    title,
                    "act",
                    status,
                    summary,
                    "https://example.com",
                    now,
                    now,
                ),
            )
        # 2 certifications via programs(program_kind='certification').
        for uid, name, kind, pref in [
            ("UNI-cert-1", "テスト製造業 認証", "certification", "東京都"),
            ("UNI-cert-2", "テスト IoT 認証", "certification", None),
        ]:
            c.execute(
                """INSERT INTO programs(unified_id, primary_name, program_kind,
                       prefecture, authority_name, official_url, tier, excluded,
                       updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (uid, name, kind, pref, "テスト省", "https://example.com/cert", "B", 0, now),
            )
        # 3 tax_rulesets: 1 current, 1 expired, 1 future-effective.
        for tid, rname, eff_from, eff_until in [
            ("TAX-aaaaaa0001", "テスト製造業現行税制", "2025-04-01", None),
            ("TAX-aaaaaa0002", "テスト製造業失効税制", "2020-04-01", "2024-03-31"),
            ("TAX-aaaaaa0003", "テスト製造業経過措置税制", "2026-10-01", "2029-09-30"),
        ]:
            c.execute(
                """INSERT INTO tax_rulesets(unified_id, ruleset_name, tax_category,
                       ruleset_kind, effective_from, effective_until, authority,
                       source_url, fetched_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    tid,
                    rname,
                    "consumption",
                    "credit",
                    eff_from,
                    eff_until,
                    "国税庁",
                    "https://nta.go.jp/test",
                    now,
                    now,
                ),
            )
        # 2 enforcement_cases — one matching 製造 in 東京都, one elsewhere.
        for cid, pref, ministry, reason, hint, dd in [
            (
                "ENF-test001",
                "東京都",
                "経済産業省",
                "製造工程の不正があった事案",
                "製造補助金",
                "2025-12-01",
            ),
            (
                "ENF-test002",
                "大阪府",
                "厚生労働省",
                "農業従事者の労務管理不備",
                "農業助成金",
                "2025-11-15",
            ),
        ]:
            c.execute(
                """INSERT INTO enforcement_cases(case_id, event_type,
                       program_name_hint, prefecture, ministry, reason_excerpt,
                       source_url, disclosed_date, fetched_at, confidence)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    cid,
                    "返還請求",
                    hint,
                    pref,
                    ministry,
                    reason,
                    "https://example.com/enf",
                    dd,
                    now,
                    0.9,
                ),
            )
        c.commit()
        yield seeded_db
        # Teardown: leave DB clean so unrelated tests aren't polluted.
        c.execute("DELETE FROM laws WHERE unified_id LIKE 'LAW-aaaaaa%'")
        c.execute("DELETE FROM tax_rulesets WHERE unified_id LIKE 'TAX-aaaaaa%'")
        c.execute("DELETE FROM enforcement_cases WHERE case_id LIKE 'ENF-test%'")
        c.execute("DELETE FROM programs WHERE unified_id IN ('UNI-cert-1','UNI-cert-2')")
        c.commit()
    finally:
        c.close()


def test_regulatory_prep_pack_happy_path(client, _seed_regulatory_prep):
    """製造業 + 東京都: laws kanji-LIKE + cert prefecture filter +
    current-only tax + 同業 enforcement, all four sections populated."""
    out = regulatory_prep_pack(industry="製造業", prefecture="東京都", limit_per_section=5)
    assert out["industry"] == "E"
    assert out["prefecture"] == "東京都"
    law_ids = {r["law_id"] for r in out["laws"]}
    # repealed row is excluded by revision_status='current'.
    assert "LAW-aaaaaa0001" in law_ids
    assert "LAW-aaaaaa0004" not in law_ids
    cert_ids = {r["program_id"] for r in out["certifications"]}
    # Tokyo-row + nationwide row both visible (prefecture IS NULL OR =).
    assert "UNI-cert-1" in cert_ids and "UNI-cert-2" in cert_ids
    tax_ids = {r["ruleset_id"] for r in out["tax_rulesets"]}
    # Expired row is excluded by default include_expired=False.
    assert "TAX-aaaaaa0002" not in tax_ids
    # Tokyo + manufacturing keyword → only ENF-test001 (Osaka excluded).
    enf_ids = {r["case_id"] for r in out["recent_enforcement"]}
    assert "ENF-test001" in enf_ids and "ENF-test002" not in enf_ids
    assert "generated_at" in out and out["generated_at"].endswith("Z")


def test_regulatory_prep_pack_industry_only_no_pref(client, _seed_regulatory_prep):
    """No prefecture: nationwide + Tokyo certs both visible; enforcement
    no longer prefecture-bound so any 製造 reason matches."""
    out = regulatory_prep_pack(industry="E")  # JSIC letter form
    assert out["prefecture"] is None
    cert_ids = {r["program_id"] for r in out["certifications"]}
    assert "UNI-cert-1" in cert_ids and "UNI-cert-2" in cert_ids
    enf_ids = {r["case_id"] for r in out["recent_enforcement"]}
    assert "ENF-test001" in enf_ids


def test_regulatory_prep_pack_empty_returns_nested_error(client, seeded_db):
    """All-zero query against the bare seeded_db (no laws / tax_rulesets /
    enforcement / certifications seeded by conftest): every section ends up
    empty, so the tool MUST surface the nested {error: {code, message, hint}}
    envelope rather than the partial-empty hint branch."""
    out = regulatory_prep_pack(industry="公務", prefecture="徳島県")
    assert "error" in out and isinstance(out["error"], dict)
    assert out["error"]["code"] == "no_matching_records"
    assert "hint" in out["error"]


def test_regulatory_prep_pack_include_expired_toggle(client, _seed_regulatory_prep):
    """include_expired=True surfaces TAX-aaaaaa0002 (effective_until=2024)."""
    out = regulatory_prep_pack(industry="製造業", include_expired=True, limit_per_section=20)
    tax_ids = {r["ruleset_id"] for r in out["tax_rulesets"]}
    assert "TAX-aaaaaa0002" in tax_ids
    out_default = regulatory_prep_pack(
        industry="製造業", include_expired=False, limit_per_section=20
    )
    tax_ids_default = {r["ruleset_id"] for r in out_default["tax_rulesets"]}
    assert "TAX-aaaaaa0002" not in tax_ids_default


def test_regulatory_prep_pack_limit_caps_sections(client, _seed_regulatory_prep):
    """limit_per_section=1 caps every array to ≤1 row."""
    out = regulatory_prep_pack(industry="製造業", prefecture="東京都", limit_per_section=1)
    assert len(out["laws"]) <= 1
    assert len(out["certifications"]) <= 1
    assert len(out["tax_rulesets"]) <= 1
    assert len(out["recent_enforcement"]) <= 1


def test_regulatory_prep_pack_company_size_echoed(client, _seed_regulatory_prep):
    """company_size is echoed back so callers can verify the parameter
    landed (it's currently a hint-only field, not a SQL filter)."""
    out = regulatory_prep_pack(industry="製造業", company_size="small")
    assert out["company_size"] == "small"
