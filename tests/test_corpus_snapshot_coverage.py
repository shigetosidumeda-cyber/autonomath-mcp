"""Corpus snapshot coverage across all 11 customer-facing routers.

Audit-trail contract: every customer-facing read endpoint embeds
``corpus_snapshot_id`` + ``corpus_checksum`` so a 会計士 work-paper can
quote a single pair of identifiers and reproduce the underlying corpus
state later (公認会計士法 §47条の2 retention obligation).

Before this test, only 6 of 11 routers carried the fields:

  programs / laws / tax_rulesets / court_decisions / audit / ma_dd

This file pins the contract for the full 11:

  programs, laws, tax_rulesets, court_decisions, audit (cite_chain),
  ma_dd (group_graph), loan_programs, case_studies, enforcement,
  bids, invoice_registrants

For each, the test seeds one minimal row (or relies on conftest's
seeded_db when the table is already populated), GETs the detail-shape
endpoint, and asserts ``corpus_snapshot_id`` + ``corpus_checksum`` are
both non-empty strings AND match what
``_corpus_snapshot.compute_corpus_snapshot()`` returns at the same
instant. The cache TTL is 5 minutes so a single-process test run sees
identical values across the 11 round-trips.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture()
def snapshot_seed(seeded_db: Path) -> Path:
    """Seed one row per audit-relevant table so every detail GET hits 200.

    The session-scoped ``seeded_db`` fixture only writes ``programs`` +
    ``exclusion_rules``. The 11-router contract needs at least:

      - ``laws`` (LAW-5a0a000001)
      - ``tax_rulesets`` (TAX-snapshot01)
      - ``court_decisions`` (HAN-snapshot01)
      - ``loan_programs`` (auto id)
      - ``case_studies`` (CS-snapshot-001)
      - ``enforcement_cases`` (ENF-snapshot-001)
      - ``bids`` (BID-snapshot01)
      - ``invoice_registrants`` (T9999999999992)

    All inserts are idempotent — INSERT OR IGNORE on the natural keys
    so repeated test runs against the session-scoped DB are no-ops.
    """
    now = datetime.now(UTC).isoformat()
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        # laws
        c.execute(
            """INSERT OR IGNORE INTO laws(unified_id, law_number, law_title,
                   law_type, revision_status, summary,
                   source_url, fetched_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                "LAW-5a0a000001",
                "テスト法律第1号",
                "テスト法",
                "act",
                "current",
                "snapshot test seed",
                "https://elaws.e-gov.go.jp/test",
                now,
                now,
            ),
        )
        # tax_rulesets
        c.execute(
            """INSERT OR IGNORE INTO tax_rulesets(
                   unified_id, ruleset_name, tax_category, ruleset_kind,
                   effective_from, related_law_ids_json,
                   eligibility_conditions, eligibility_conditions_json,
                   rate_or_amount, calculation_formula, filing_requirements,
                   authority, source_url, fetched_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "TAX-5e500a0001",
                "snapshot test ruleset",
                "consumption",
                "registration",
                "2024-04-01",
                json.dumps(["LAW-5a0a000001"]),
                "snapshot test eligibility",
                json.dumps({"op": "always_true"}),
                "10%",
                "課税売上 × 10%",
                "確定申告書",
                "国税庁",
                "https://www.nta.go.jp/test",
                now,
                now,
            ),
        )
        # court_decisions
        c.execute(
            """INSERT OR IGNORE INTO court_decisions(
                   unified_id, case_name, case_number, court, court_level,
                   decision_date, decision_type, subject_area,
                   related_law_ids_json, key_ruling, source_url,
                   fetched_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "HAN-5a0a050001",
                "snapshot test 判例",
                "令和X年テスト第1号",
                "東京高等裁判所",
                "high",
                "2024-03-10",
                "判決",
                "租税",
                json.dumps(["LAW-5a0a000001"]),
                "snapshot test ruling",
                "https://www.courts.go.jp/test",
                now,
                now,
            ),
        )
        # loan_programs (uses (program_name, provider) UNIQUE)
        c.execute(
            """INSERT OR IGNORE INTO loan_programs(
                   program_name, provider, loan_type, amount_max_yen,
                   official_url, fetched_at, confidence,
                   collateral_required, personal_guarantor_required,
                   third_party_guarantor_required)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                "snapshot test loan",
                "テスト公庫",
                "general",
                10_000_000,
                "https://www.jfc.go.jp/test",
                now,
                0.9,
                "negotiable",
                "negotiable",
                "not_required",
            ),
        )
        # case_studies
        c.execute(
            """INSERT OR IGNORE INTO case_studies(
                   case_id, company_name, prefecture, industry_jsic,
                   case_title, case_summary, programs_used_json,
                   total_subsidy_received_yen, source_url,
                   publication_date, fetched_at, confidence)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "CS-snapshot-001",
                "snapshot test 株式会社",
                "東京都",
                "0111",
                "snapshot test case",
                "snapshot test summary",
                json.dumps(["snapshot test program"]),
                1_000_000,
                "https://example.go.jp/case/snap001",
                "2024-12-15",
                now,
                0.9,
            ),
        )
        # enforcement_cases
        c.execute(
            """INSERT OR IGNORE INTO enforcement_cases(
                   case_id, event_type, recipient_name, recipient_kind,
                   ministry, prefecture, reason_excerpt, source_url,
                   source_title, disclosed_date, fetched_at, confidence)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "ENF-snapshot-001",
                "排除措置命令",
                "snapshot test corporation",
                "houjin",
                "公正取引委員会",
                "東京都",
                "snapshot test reason",
                "https://www.jftc.go.jp/test",
                "snapshot test title",
                "2024-02-15",
                now,
                0.95,
            ),
        )
        # bids
        c.execute(
            """INSERT OR IGNORE INTO bids(
                   unified_id, bid_title, bid_kind, procuring_entity,
                   ministry, prefecture, source_url, fetched_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                "BID-5b0d050002",
                "snapshot test 入札",
                "open",
                "snapshot test 機関",
                "総務省",
                "東京都",
                "https://example.go.jp/bid/snap002",
                now,
                now,
            ),
        )
        # invoice_registrants
        c.execute(
            """INSERT OR IGNORE INTO invoice_registrants(
                   invoice_registration_number, houjin_bangou,
                   normalized_name, address_normalized, prefecture,
                   registered_date, registrant_kind, source_url,
                   fetched_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                "T9999999999992",
                "9999999999992",
                "snapshot test 株式会社",
                "東京都千代田区テスト町1-1",
                "東京都",
                "2024-01-15",
                "corporation",
                "https://www.invoice-kohyo.nta.go.jp/test",
                now,
                now,
            ),
        )
        c.commit()
    finally:
        c.close()
    # Drop the snapshot helper's process-local cache so the freshly-seeded
    # rows participate in the live snapshot computation.
    from jpintel_mcp.api._corpus_snapshot import _reset_cache_for_tests

    _reset_cache_for_tests()
    return seeded_db


def _live_snapshot(seeded_db: Path) -> tuple[str, str]:
    """Compute the (snapshot_id, checksum) the routers will see right now.

    Opens a fresh sqlite3 connection on the same DB the API uses; the
    helper's process-local cache means every subsequent compute call in
    the same 5-minute window collapses to identical values, so a single
    snapshot computed here is what every router will emit.
    """
    from jpintel_mcp.api._corpus_snapshot import compute_corpus_snapshot

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        return compute_corpus_snapshot(conn)
    finally:
        conn.close()


def _assert_snapshot_fields(
    body: dict[str, Any],
    expected_snapshot_id: str,
    expected_checksum: str,
    *,
    where: str,
) -> None:
    """Pin the corpus-snapshot contract on a single response body.

    Body MUST be a dict (no list-shape responses qualify). The two keys
    must be present at the top level, both non-empty strings, both
    matching the live snapshot computed at test-start.
    """
    assert isinstance(body, dict), f"{where}: body must be a dict, got {type(body)!r}"
    assert "corpus_snapshot_id" in body, (
        f"{where}: corpus_snapshot_id missing — body keys={list(body.keys())}"
    )
    assert "corpus_checksum" in body, (
        f"{where}: corpus_checksum missing — body keys={list(body.keys())}"
    )
    snap_id = body["corpus_snapshot_id"]
    checksum = body["corpus_checksum"]
    assert isinstance(snap_id, str) and snap_id, (
        f"{where}: corpus_snapshot_id must be a non-empty string, got {snap_id!r}"
    )
    assert isinstance(checksum, str) and checksum, (
        f"{where}: corpus_checksum must be a non-empty string, got {checksum!r}"
    )
    assert snap_id == expected_snapshot_id, (
        f"{where}: corpus_snapshot_id drift — got {snap_id!r} vs live {expected_snapshot_id!r}"
    )
    assert checksum == expected_checksum, (
        f"{where}: corpus_checksum drift — got {checksum!r} vs live {expected_checksum!r}"
    )


def test_corpus_snapshot_coverage_all_11_routers(client, snapshot_seed, paid_key):
    """Hit all 11 customer-facing detail endpoints; assert snapshot fields.

    Coverage map:

      1. programs            GET /v1/programs/{unified_id}
      2. laws                GET /v1/laws/{unified_id}
      3. tax_rulesets        GET /v1/tax_rulesets/{unified_id}
      4. court_decisions     GET /v1/court-decisions/{unified_id}
      5. audit               GET /v1/audit/cite_chain/{ruleset_id}
      6. ma_dd               GET /v1/am/group_graph?houjin_bangou=...
      7. loan_programs       GET /v1/loan-programs/{loan_id}
      8. case_studies        GET /v1/case-studies/{case_id}
      9. enforcement         GET /v1/enforcement-cases/{case_id}
     10. bids                GET /v1/bids/{unified_id}
     11. invoice_registrants GET /v1/invoice_registrants/{T-num}

    Each row's body must carry both audit-trail keys at the top level.
    """
    expected_snap, expected_ck = _live_snapshot(snapshot_seed)
    headers = {"X-API-Key": paid_key}

    # ---- 1. programs (already wired pre-2026-04-29) ----
    r = client.get("/v1/programs/UNI-test-s-1", headers=headers)
    assert r.status_code == 200, r.text
    _assert_snapshot_fields(r.json(), expected_snap, expected_ck, where="programs")

    # ---- 2. laws (already wired) ----
    r = client.get("/v1/laws/LAW-5a0a000001", headers=headers)
    assert r.status_code == 200, r.text
    _assert_snapshot_fields(r.json(), expected_snap, expected_ck, where="laws")

    # ---- 3. tax_rulesets (already wired) ----
    r = client.get("/v1/tax_rulesets/TAX-5e500a0001", headers=headers)
    assert r.status_code == 200, r.text
    _assert_snapshot_fields(r.json(), expected_snap, expected_ck, where="tax_rulesets")

    # ---- 4. court_decisions (already wired) ----
    r = client.get("/v1/court-decisions/HAN-5a0a050001", headers=headers)
    assert r.status_code == 200, r.text
    _assert_snapshot_fields(r.json(), expected_snap, expected_ck, where="court_decisions")

    # ---- 5. audit cite_chain (already wired) ----
    # Uses the seeded TAX-5e500a0001 ruleset id; chain may be 1 hop deep
    # since we only wired LAW-5a0a000001 as a related_law_id reference.
    r = client.get("/v1/audit/cite_chain/TAX-5e500a0001", headers=headers)
    assert r.status_code == 200, r.text
    _assert_snapshot_fields(r.json(), expected_snap, expected_ck, where="audit")

    # ---- 6. ma_dd group_graph (already wired) ----
    # autonomath.db isn't populated in tests (am_conn returns None on the
    # connect path) — the handler still emits the snapshot envelope with
    # an empty graph. That's exactly what we need to test.
    r = client.get(
        "/v1/am/group_graph",
        params={"houjin_bangou": "9999999999992"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    _assert_snapshot_fields(r.json(), expected_snap, expected_ck, where="ma_dd")

    # ---- 7. loan_programs (newly wired) ----
    # Resolve the auto-incremented id for our seed row, then GET it.
    conn = sqlite3.connect(snapshot_seed)
    try:
        loan_row = conn.execute(
            "SELECT id FROM loan_programs WHERE program_name = ? AND provider = ?",
            ("snapshot test loan", "テスト公庫"),
        ).fetchone()
    finally:
        conn.close()
    assert loan_row is not None, "loan_programs seed row missing"
    r = client.get(f"/v1/loan-programs/{loan_row[0]}", headers=headers)
    assert r.status_code == 200, r.text
    _assert_snapshot_fields(r.json(), expected_snap, expected_ck, where="loan_programs")

    # ---- 8. case_studies (newly wired) ----
    r = client.get("/v1/case-studies/CS-snapshot-001", headers=headers)
    assert r.status_code == 200, r.text
    _assert_snapshot_fields(r.json(), expected_snap, expected_ck, where="case_studies")

    # ---- 9. enforcement (newly wired) ----
    r = client.get("/v1/enforcement-cases/ENF-snapshot-001", headers=headers)
    assert r.status_code == 200, r.text
    _assert_snapshot_fields(r.json(), expected_snap, expected_ck, where="enforcement")

    # ---- 10. bids (newly wired) ----
    r = client.get("/v1/bids/BID-5b0d050002", headers=headers)
    assert r.status_code == 200, r.text
    _assert_snapshot_fields(r.json(), expected_snap, expected_ck, where="bids")

    # ---- 11. invoice_registrants (newly wired) ----
    # Snapshot fields appear at the top level alongside `result` +
    # `attribution` so PDL v1.0 compliance and the audit trail compose.
    r = client.get("/v1/invoice_registrants/T9999999999992", headers=headers)
    assert r.status_code == 200, r.text
    _assert_snapshot_fields(r.json(), expected_snap, expected_ck, where="invoice_registrants")
