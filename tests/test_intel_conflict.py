"""Tests for POST /v1/intel/conflict — combo conflict detector + alternatives.

Coverage (≥3 tests):

  1. test_conflict_detects_two_program_pair_via_empirical_stack:
     2 program ids that the empirical stack table flags conflict_flag=1
     return has_conflict=True with the right pair surfaced.
  2. test_conflict_extracts_compatible_subset_from_three_plus_programs:
     3+ program inputs return compatible_subset that excludes the
     conflicting members, plus alternative_bundles ranked by ¥ amount.
  3. test_conflict_returns_top3_alternative_bundles_with_amounts:
     Up to 3 alternative_bundles each with a `bundle` list, an
     `expected_total_amount`, and a `rationale` string.

Plus structural extras covered:
  * 422 path on a single-program payload.
  * Graceful degradation when am_funding_stack_empirical is missing.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures: programs in jpintel.db + autonomath.db with conflict tables
# ---------------------------------------------------------------------------


def _seed_conflict_programs(seeded_db: Path) -> None:
    """Seed three programs with distinct amount_max_man_yen so the greedy
    bundler has a deterministic ordering."""
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        now = datetime.now(UTC).isoformat()
        rows = [
            (
                "UNI-conflict-A",
                "コンフリクトテスト 補助金 A",
                "A",
                "東京都",
                "都道府県",
                "東京都産業労働局",
                "補助金",
                3000,  # 3,000 万円 = 30,000,000 円
            ),
            (
                "UNI-conflict-B",
                "コンフリクトテスト 補助金 B",
                "A",
                "東京都",
                "都道府県",
                "東京都産業労働局",
                "補助金",
                2000,  # 2,000 万円 = 20,000,000 円
            ),
            (
                "UNI-conflict-C",
                "コンフリクトテスト 補助金 C",
                "B",
                "東京都",
                "都道府県",
                "東京都産業労働局",
                "補助金",
                1000,  # 1,000 万円 = 10,000,000 円
            ),
            (
                "UNI-conflict-D",
                "コンフリクトテスト 補助金 D",
                "B",
                "東京都",
                "都道府県",
                "東京都産業労働局",
                "補助金",
                500,  # 500 万円 = 5,000,000 円
            ),
        ]
        for uid, name, tier, pref, lvl, authority, kind, amax in rows:
            conn.execute(
                "INSERT OR IGNORE INTO programs("
                "  unified_id, primary_name, aliases_json, "
                "  authority_level, authority_name, prefecture, municipality, "
                "  program_kind, official_url, "
                "  amount_max_man_yen, amount_min_man_yen, subsidy_rate, "
                "  trust_level, tier, coverage_score, gap_to_tier_s_json, "
                "  a_to_j_coverage_json, excluded, exclusion_reason, "
                "  crop_categories_json, equipment_category, "
                "  target_types_json, funding_purpose_json, "
                "  amount_band, application_window_json, "
                "  enriched_json, source_mentions_json, updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uid,
                    name,
                    None,
                    lvl,
                    authority,
                    pref,
                    None,
                    kind,
                    None,
                    amax,
                    None,
                    None,
                    None,
                    tier,
                    None,
                    None,
                    None,
                    0,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def conflict_autonomath_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Build a tmp autonomath.db with the W22-6 + W26-6 + W25 tables seeded.

    Conflict layout (program ordering — A < B < C < D lexically because
    'UNI-conflict-A' < 'UNI-conflict-B' < ...):
      * (A, B): empirical conflict_flag=1 (matrix says 'incompatible',
        co_adoption_count=12) → severity=high.
      * (C, D): legal predicate exclusion — D declares NOT_IN against C.
      * (A, C): am_compat_matrix says 'incompatible' (guideline tier).
      * (A, D), (B, C), (B, D): clean / no conflict.
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE am_funding_stack_empirical (
                program_a_id        TEXT NOT NULL,
                program_b_id        TEXT NOT NULL,
                co_adoption_count   INTEGER NOT NULL DEFAULT 0,
                mean_days_between   INTEGER,
                compat_matrix_says  TEXT,
                conflict_flag       INTEGER NOT NULL DEFAULT 0,
                generated_at        TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (program_a_id, program_b_id),
                CHECK (program_a_id < program_b_id)
            );
            CREATE TABLE am_program_eligibility_predicate (
                predicate_id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_unified_id TEXT NOT NULL,
                predicate_kind TEXT NOT NULL,
                operator TEXT NOT NULL,
                value_text TEXT,
                value_num REAL,
                value_json TEXT,
                is_required INTEGER NOT NULL DEFAULT 1,
                source_url TEXT,
                source_clause_quote TEXT,
                extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE am_compat_matrix (
                program_a_id   TEXT NOT NULL,
                program_b_id   TEXT NOT NULL,
                compat_status  TEXT NOT NULL,
                source_notes   TEXT,
                generated_at   TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (program_a_id, program_b_id)
            );
            """
        )

        # Pair (A, B) — empirical conflict.
        conn.execute(
            "INSERT INTO am_funding_stack_empirical "
            "(program_a_id, program_b_id, co_adoption_count, "
            " compat_matrix_says, conflict_flag) "
            "VALUES (?,?,?,?,?)",
            ("UNI-conflict-A", "UNI-conflict-B", 12, "incompatible", 1),
        )
        # Empirical row (B, C) with conflict_flag=0 — should NOT surface.
        conn.execute(
            "INSERT INTO am_funding_stack_empirical "
            "(program_a_id, program_b_id, co_adoption_count, "
            " compat_matrix_says, conflict_flag) "
            "VALUES (?,?,?,?,?)",
            ("UNI-conflict-B", "UNI-conflict-C", 7, "compatible", 0),
        )

        # Pair (A, C) — guideline-tier conflict via am_compat_matrix only.
        conn.execute(
            "INSERT INTO am_compat_matrix "
            "(program_a_id, program_b_id, compat_status) "
            "VALUES (?,?,?)",
            ("UNI-conflict-A", "UNI-conflict-C", "incompatible"),
        )

        # Pair (C, D) — legal predicate: D declares NOT_IN against C.
        conn.execute(
            "INSERT INTO am_program_eligibility_predicate "
            "(program_unified_id, predicate_kind, operator, "
            " value_text, source_url, source_clause_quote) "
            "VALUES (?,?,?,?,?,?)",
            (
                "UNI-conflict-D",
                "other",
                "NOT_IN",
                "UNI-conflict-C",
                "https://example.gov/d-rule.pdf",
                "本補助金は C と併用不可。",
            ),
        )

        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)

    # Reset the thread-local connection cache in autonomath_tools.db so
    # the new path actually gets opened (the previous test may have
    # cached a connection to a different DB).
    from jpintel_mcp.mcp.autonomath_tools import db as am_db

    if hasattr(am_db, "_local"):
        am_db._local = type(am_db._local)()

    return db_path


@pytest.fixture()
def conflict_client(
    seeded_db: Path,
    conflict_autonomath_db: Path,  # noqa: ARG001 — autouse to seed the AM DB
) -> TestClient:
    """TestClient backed by the seeded jpintel.db + conflict autonomath.db."""
    _seed_conflict_programs(seeded_db)
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Test 1 — 2-program empirical conflict detected
# ---------------------------------------------------------------------------


def test_conflict_detects_two_program_pair_via_empirical_stack(
    conflict_client: TestClient,
) -> None:
    """A + B is the empirical-stack conflict; expect has_conflict=True with
    severity='high' and the empirical evidence surfaced."""
    resp = conflict_client.post(
        "/v1/intel/conflict",
        json={
            "program_ids": ["UNI-conflict-A", "UNI-conflict-B"],
            "houjin_id": "1234567890123",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Envelope invariants.
    assert body["_billing_unit"] == 1
    assert "_disclaimer" in body and body["_disclaimer"]
    assert "税理士法 §52" in body["_disclaimer"]
    assert "corpus_snapshot_id" in body
    assert body["houjin_id"] == "1234567890123"
    assert sorted(body["input_program_ids"]) == [
        "UNI-conflict-A",
        "UNI-conflict-B",
    ]

    # Conflict shape.
    assert body["has_conflict"] is True
    assert isinstance(body["conflict_pairs"], list)
    assert len(body["conflict_pairs"]) == 1
    pair = body["conflict_pairs"][0]
    assert pair["a"] == "UNI-conflict-A"
    assert pair["b"] == "UNI-conflict-B"
    assert pair["severity"] == "high"
    assert pair["evidence"]["source"] == "stack_empirical"
    assert pair["evidence"]["co_adoption_count"] == 12

    # Conflict score is a single-pair / one-pair-total => 1.0 (sev high).
    assert body["conflict_score"] == pytest.approx(1.0, abs=0.01)

    # Compatible subset drops one of the two — the greedy walk by amount
    # picks A (3000 万円) over B (2000 万円).
    assert body["compatible_subset"] == ["UNI-conflict-A"]

    # Alternative bundles.
    assert isinstance(body["alternative_bundles"], list)
    assert len(body["alternative_bundles"]) >= 1


# ---------------------------------------------------------------------------
# Test 2 — 3+ program compatible subset extraction
# ---------------------------------------------------------------------------


def test_conflict_extracts_compatible_subset_from_three_plus_programs(
    conflict_client: TestClient,
) -> None:
    """A, B, C, D — multiple conflicts.  compatible_subset must drop the
    conflicting nodes and the bundle ranking must respect ¥ amounts."""
    resp = conflict_client.post(
        "/v1/intel/conflict",
        json={
            "program_ids": [
                "UNI-conflict-A",
                "UNI-conflict-B",
                "UNI-conflict-C",
                "UNI-conflict-D",
            ],
            "houjin_id": "1234567890123",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["has_conflict"] is True

    # Three conflict pairs expected:
    # (A, B) empirical, (A, C) guideline, (C, D) legal predicate.
    pair_keys = {(p["a"], p["b"]) for p in body["conflict_pairs"]}
    assert ("UNI-conflict-A", "UNI-conflict-B") in pair_keys
    assert ("UNI-conflict-A", "UNI-conflict-C") in pair_keys
    assert ("UNI-conflict-C", "UNI-conflict-D") in pair_keys

    # Source per pair.
    by_pair = {(p["a"], p["b"]): p for p in body["conflict_pairs"]}
    assert by_pair[("UNI-conflict-A", "UNI-conflict-B")]["evidence"]["source"] == "stack_empirical"
    assert by_pair[("UNI-conflict-A", "UNI-conflict-C")]["evidence"]["source"] == "guideline"
    assert by_pair[("UNI-conflict-C", "UNI-conflict-D")]["evidence"]["source"] == "law"

    # compatible_subset:
    # Greedy by amount picks A first (3000 万円); A conflicts with B and C
    # → drop them. D is clean against A → accepted. B has no conflict
    # against the *accepted* set after C is dropped, but B was already
    # excluded because A is in the set and (A, B) conflicts. Final:
    # {A, D}.
    subset = set(body["compatible_subset"])
    assert subset == {"UNI-conflict-A", "UNI-conflict-D"}

    # data_quality block populated.
    dq = body["data_quality"]
    assert dq["total_pairs_evaluated"] == 6  # n=4, n*(n-1)/2 = 6
    assert dq["conflict_pairs_found"] == 3


# ---------------------------------------------------------------------------
# Test 3 — alternative bundles top-3 with amounts
# ---------------------------------------------------------------------------


def test_conflict_returns_top3_alternative_bundles_with_amounts(
    conflict_client: TestClient,
) -> None:
    """alternative_bundles is a list of up to 3 distinct bundles each
    carrying bundle / expected_total_amount / rationale."""
    resp = conflict_client.post(
        "/v1/intel/conflict",
        json={
            "program_ids": [
                "UNI-conflict-A",
                "UNI-conflict-B",
                "UNI-conflict-C",
                "UNI-conflict-D",
            ],
            "houjin_id": "1234567890123",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    bundles = body["alternative_bundles"]
    assert isinstance(bundles, list)
    assert 1 <= len(bundles) <= 3

    # Each bundle has the required keys + an int amount.
    for b in bundles:
        assert isinstance(b["bundle"], list)
        assert len(b["bundle"]) >= 1
        assert isinstance(b["expected_total_amount"], int)
        assert b["expected_total_amount"] >= 0
        assert isinstance(b["rationale"], str) and b["rationale"]

    # Bundles ranked descending by expected_total_amount.
    amounts = [b["expected_total_amount"] for b in bundles]
    assert amounts == sorted(amounts, reverse=True)

    # The top bundle should match the compatible_subset (max-amount).
    primary = body["compatible_subset"]
    top_bundle = bundles[0]["bundle"]
    assert sorted(top_bundle) == sorted(primary)

    # Top bundle's expected_total_amount = sum of A (30M) + D (5M) = 35M.
    assert bundles[0]["expected_total_amount"] == 35_000_000


# ---------------------------------------------------------------------------
# Extra: 422 on insufficient program_ids
# ---------------------------------------------------------------------------


def test_conflict_422_on_single_program(conflict_client: TestClient) -> None:
    """Pydantic min_length=2 must fire before the route body runs."""
    resp = conflict_client.post(
        "/v1/intel/conflict",
        json={
            "program_ids": ["UNI-conflict-A"],
            "houjin_id": "1234567890123",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Extra: graceful degradation when conflict tables are missing
# ---------------------------------------------------------------------------


def test_conflict_graceful_degradation_when_tables_missing(
    seeded_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare autonomath.db (no conflict tables) returns has_conflict=False
    + missing_tables populated, never a 500."""
    _seed_conflict_programs(seeded_db)

    bare_db = tmp_path / "bare_autonomath.db"
    conn = sqlite3.connect(bare_db)
    # Create an unrelated table so the file is non-empty (so that any
    # `stat().st_size == 0` guards in client code do not skip the open).
    conn.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    conn.commit()
    conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(bare_db))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(bare_db))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", bare_db)

    # Reset thread-local cache so the new path is opened.
    from jpintel_mcp.mcp.autonomath_tools import db as am_db

    if hasattr(am_db, "_local"):
        am_db._local = type(am_db._local)()

    from jpintel_mcp.api.main import create_app

    bare_client = TestClient(create_app())

    resp = bare_client.post(
        "/v1/intel/conflict",
        json={
            "program_ids": ["UNI-conflict-A", "UNI-conflict-B"],
            "houjin_id": "1234567890123",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_conflict"] is False
    assert body["conflict_pairs"] == []
    # Both empirical + predicate tables flagged missing.
    missing = set(body["data_quality"]["missing_tables"])
    assert "am_funding_stack_empirical" in missing
    assert "am_program_eligibility_predicate" in missing
    # The compatible_subset should be the entire (de-duped) input set
    # since no conflicts were detected.
    assert sorted(body["compatible_subset"]) == [
        "UNI-conflict-A",
        "UNI-conflict-B",
    ]


def test_conflict_paid_final_cap_failure_returns_503_without_usage_event(
    conflict_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A final cap rejection must fail closed before delivering a paid 2xx."""
    key_hash = hash_api_key(paid_key)
    endpoint = "intel.conflict"

    def _reject_final_cap(*_args: object, **_kwargs: object) -> tuple[bool, bool]:
        return False, False

    import jpintel_mcp.api.deps as deps

    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    conn = sqlite3.connect(seeded_db)
    try:
        (before,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()

    resp = conflict_client.post(
        "/v1/intel/conflict",
        json={
            "program_ids": ["UNI-conflict-A", "UNI-conflict-B"],
            "houjin_id": "1234567890123",
        },
        headers={"X-API-Key": paid_key},
    )

    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"]["code"] == "billing_cap_final_check_failed"

    conn = sqlite3.connect(seeded_db)
    try:
        (after,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()
    assert after == before
