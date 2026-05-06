"""Tests for POST /v1/intel/bundle/optimal — optimal program bundle.

Covers (≥3 tests):

  1. Happy path — 5-program bundle returned, no conflicts within bundle,
     standard envelope (corpus_snapshot_id + _disclaimer + _billing_unit).
  2. exclude filter respected — IDs in exclude_program_ids never appear
     in bundle nor runner-up bundles.
  3. objective="max_count" returns more / equal programs vs "max_amount"
     when conflict structure permits, and `optimization_log.algorithm`
     surfaces the requested objective family.

Plus structural extras:
  * 422 on a malformed houjin_id string.
  * Greedy IS skips the conflict-flagged pair from
    am_funding_stack_empirical.
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


_HOUJIN = "1234567890123"


# ---------------------------------------------------------------------------
# Helpers — seed jpintel.db programs + autonomath.db substrate.
# ---------------------------------------------------------------------------


def _seed_bundle_programs(seeded_db: Path) -> None:
    """Seed a small program portfolio with deterministic amount ordering.

    The bundle endpoint resolves either jpi_programs (production) or
    programs (test fixture) — we seed `programs` since the shared
    `seeded_db` fixture only ships that surface.
    """
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        now = datetime.now(UTC).isoformat()
        rows = [
            ("UNI-bundle-A", "バンドルテスト 補助金 A", "S", 5000),  # 5,000 万円 = 50M円
            ("UNI-bundle-B", "バンドルテスト 補助金 B", "A", 4000),
            ("UNI-bundle-C", "バンドルテスト 補助金 C", "A", 3000),
            ("UNI-bundle-D", "バンドルテスト 補助金 D", "B", 2000),
            ("UNI-bundle-E", "バンドルテスト 補助金 E", "B", 1500),
            ("UNI-bundle-F", "バンドルテスト 補助金 F", "B", 1000),
            ("UNI-bundle-G", "バンドルテスト 補助金 G", "C", 800),
            ("UNI-bundle-H", "バンドルテスト 補助金 H", "C", 500),
        ]
        for uid, name, tier, amax in rows:
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
                    "都道府県",
                    "東京都産業労働局",
                    "東京都",
                    None,
                    "補助金",
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
def bundle_autonomath_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Build a tmp autonomath.db with W22-6 + W26-6 + W29-8 substrate.

    Tables seeded:
      * am_recommended_programs — top-N per houjin precomputed (one
        row per UNI-bundle-X for our test houjin).
      * am_program_eligibility_predicate — empty-body cache so
        predicate filter passes through (tests the missing-axis path).
      * am_funding_stack_empirical — exactly one conflict edge between
        UNI-bundle-A and UNI-bundle-B, so the optimizer must drop one.
      * programs (mirror of jpintel) — joined for amount data so the
        endpoint resolves the program_table fallback when jpi_programs
        is absent.
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE am_recommended_programs (
                houjin_bangou      TEXT NOT NULL,
                program_unified_id TEXT NOT NULL,
                rank               INTEGER NOT NULL,
                score              REAL NOT NULL,
                reason_json        TEXT,
                computed_at        TEXT NOT NULL DEFAULT (datetime('now')),
                source_snapshot_id TEXT,
                PRIMARY KEY (houjin_bangou, program_unified_id)
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
            CREATE TABLE programs (
                unified_id TEXT PRIMARY KEY,
                primary_name TEXT NOT NULL,
                aliases_json TEXT,
                authority_level TEXT,
                authority_name TEXT,
                prefecture TEXT,
                municipality TEXT,
                program_kind TEXT,
                official_url TEXT,
                amount_max_man_yen REAL,
                amount_min_man_yen REAL,
                subsidy_rate REAL,
                tier TEXT,
                excluded INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )

        program_rows = [
            ("UNI-bundle-A", "バンドルテスト 補助金 A", "S", 5000.0, 1000.0),
            ("UNI-bundle-B", "バンドルテスト 補助金 B", "A", 4000.0, 800.0),
            ("UNI-bundle-C", "バンドルテスト 補助金 C", "A", 3000.0, 600.0),
            ("UNI-bundle-D", "バンドルテスト 補助金 D", "B", 2000.0, 400.0),
            ("UNI-bundle-E", "バンドルテスト 補助金 E", "B", 1500.0, 300.0),
            ("UNI-bundle-F", "バンドルテスト 補助金 F", "B", 1000.0, 200.0),
            ("UNI-bundle-G", "バンドルテスト 補助金 G", "C", 800.0, 150.0),
            ("UNI-bundle-H", "バンドルテスト 補助金 H", "C", 500.0, 100.0),
        ]
        now = datetime.now(UTC).isoformat()
        for uid, name, tier, amax, amin in program_rows:
            conn.execute(
                "INSERT INTO programs(unified_id, primary_name, "
                "authority_level, authority_name, prefecture, "
                "program_kind, amount_max_man_yen, amount_min_man_yen, "
                "tier, excluded, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uid,
                    name,
                    "都道府県",
                    "東京都産業労働局",
                    "東京都",
                    "補助金",
                    amax,
                    amin,
                    tier,
                    0,
                    now,
                ),
            )

        # Recommendations — every bundle program ranked for our test houjin.
        # Ranks ascending so highest tier (S) is rank=1.
        recs = [
            (1, "UNI-bundle-A", 0.95),
            (2, "UNI-bundle-B", 0.90),
            (3, "UNI-bundle-C", 0.85),
            (4, "UNI-bundle-D", 0.75),
            (5, "UNI-bundle-E", 0.70),
            (6, "UNI-bundle-F", 0.65),
            (7, "UNI-bundle-G", 0.55),
            (8, "UNI-bundle-H", 0.45),
        ]
        for rank, pid, score in recs:
            conn.execute(
                "INSERT INTO am_recommended_programs "
                "(houjin_bangou, program_unified_id, rank, score) "
                "VALUES (?, ?, ?, ?)",
                (_HOUJIN, pid, rank, score),
            )

        # Single conflict edge: A and B can't co-occur. Means the
        # max_amount greedy must pick A (5000) and skip B (4000).
        conn.execute(
            "INSERT INTO am_funding_stack_empirical "
            "(program_a_id, program_b_id, co_adoption_count, "
            " compat_matrix_says, conflict_flag) "
            "VALUES (?,?,?,?,?)",
            ("UNI-bundle-A", "UNI-bundle-B", 8, "incompatible", 1),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)

    # Reset the autonomath_tools.db thread-local cache between fixture runs.
    from jpintel_mcp.mcp.autonomath_tools import db as am_db

    if hasattr(am_db, "_local"):
        am_db._local = type(am_db._local)()

    return db_path


@pytest.fixture()
def bundle_client(
    seeded_db: Path,
    bundle_autonomath_db: Path,  # noqa: ARG001 — autouse to seed AM DB
) -> TestClient:
    """TestClient backed by seeded jpintel.db + bundle autonomath.db."""
    _seed_bundle_programs(seeded_db)
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


def _assert_decision_support_shape(body: dict) -> dict:
    support = body["decision_support"]
    assert support["schema_version"] == "v1"
    assert "pool" in support["generated_from"]
    assert "eligible" in support["generated_from"]
    assert "data_quality" in support["generated_from"]

    for section in ("why_this_matters", "decision_insights", "next_actions"):
        assert isinstance(support[section], list)
        assert support[section]
        for item in support[section]:
            assert item["signal"]
            assert item["message_ja"]
            assert isinstance(item["basis"], list)
            assert item["basis"]
    return support


# ---------------------------------------------------------------------------
# Test 1 — happy path: 5-program bundle, no in-bundle conflicts, envelope shape
# ---------------------------------------------------------------------------


def test_bundle_optimal_happy_path_returns_5_programs(
    bundle_client: TestClient,
) -> None:
    """A 5-program bundle is returned, with the standard envelope shape
    and no conflicts between selected programs."""
    resp = bundle_client.post(
        "/v1/intel/bundle/optimal",
        json={
            "houjin_id": _HOUJIN,
            "bundle_size": 5,
            "objective": "max_amount",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Envelope invariants.
    assert body["_billing_unit"] == 1
    assert "_disclaimer" in body and body["_disclaimer"]
    assert "税理士法 §52" in body["_disclaimer"]
    assert "corpus_snapshot_id" in body
    assert body["houjin_id"] == _HOUJIN

    # Bundle shape.
    bundle = body["bundle"]
    assert isinstance(bundle, list)
    # 8 candidates, A↔B conflict, so we can always reach 5 programs
    # (drop one of A/B → 7 left → 5 fits).
    assert len(bundle) == 5
    selected_ids = {row["program_id"] for row in bundle}
    # A is preferred over B by amount.
    assert "UNI-bundle-A" in selected_ids
    assert "UNI-bundle-B" not in selected_ids

    # Per-row shape.
    for row in bundle:
        assert "program_id" in row
        assert "name" in row
        assert "eligibility_score" in row
        assert "expected_amount_min" in row
        assert "expected_amount_max" in row
        # Optimal output → no in-bundle conflicts (always [] by spec).
        assert row["conflict_with_others_in_bundle"] == []

    # bundle_total rollup.
    total = body["bundle_total"]
    assert total["expected_amount_max"] > 0
    assert total["expected_amount_min"] >= 0
    assert 0.0 <= float(total["eligibility_avg"]) <= 1.0

    # conflict_avoidance reflects the seeded edge.
    conflict = body["conflict_avoidance"]
    assert conflict["conflict_pairs_avoided"] >= 1
    assert "alternative_considered" in conflict

    # optimization_log.
    olog = body["optimization_log"]
    assert olog["algorithm"] in {"greedy_amount", "ilp_relaxation"}
    assert olog["iterations"] >= len(bundle)
    assert olog["time_ms"] >= 0

    # decision_support is additive top-level guidance for caller LLMs.
    support = _assert_decision_support_shape(body)
    why_signals = {item["signal"] for item in support["why_this_matters"]}
    insight_signals = {item["signal"] for item in support["decision_insights"]}
    action_signals = {item["signal"] for item in support["next_actions"]}
    assert "candidate_pool_shortlist" in why_signals
    assert "conflict_avoidance" in why_signals
    assert "predicate_filter" in insight_signals
    assert "runner_up_alternatives" in insight_signals
    assert "verify_primary_sources" in action_signals
    assert "confirm_professional_review" in action_signals

    # runner_up_bundles is a list of swap alternatives.
    assert isinstance(body["runner_up_bundles"], list)
    for ru in body["runner_up_bundles"]:
        assert "bundle" in ru
        assert "total_amount" in ru
        assert "why_not_chosen" in ru


# ---------------------------------------------------------------------------
# Test 2 — exclude_program_ids respected
# ---------------------------------------------------------------------------


def test_bundle_optimal_excludes_listed_program_ids(
    bundle_client: TestClient,
) -> None:
    """Programs in exclude_program_ids never appear in bundle nor in any
    runner-up bundle."""
    excluded = ["UNI-bundle-A", "UNI-bundle-C"]
    resp = bundle_client.post(
        "/v1/intel/bundle/optimal",
        json={
            "houjin_id": _HOUJIN,
            "bundle_size": 5,
            "objective": "max_amount",
            "exclude_program_ids": excluded,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    bundle_ids = {row["program_id"] for row in body["bundle"]}
    assert not (set(excluded) & bundle_ids), (
        f"excluded ids leaked into bundle: {bundle_ids & set(excluded)}"
    )

    # Runner-ups must also honor the exclusion (they are derived from the
    # same candidate pool that already had the excludes filtered out).
    for ru in body["runner_up_bundles"]:
        ru_ids = set(ru["bundle"])
        assert not (set(excluded) & ru_ids), (
            f"excluded ids leaked into runner_up: {ru_ids & set(excluded)}"
        )

    # Without A in the pool, the conflict edge (A, B) is moot, so B *can*
    # appear (no longer blocked by A).
    assert "UNI-bundle-B" in bundle_ids


# ---------------------------------------------------------------------------
# Test 3 — objective="max_count" yields >= count of "max_amount" bundle
# ---------------------------------------------------------------------------


def test_bundle_optimal_max_count_returns_more_or_equal_programs(
    bundle_client: TestClient,
) -> None:
    """With the same constraints, max_count selects at least as many
    programs as max_amount (it ignores ¥ rank in favor of fitting more
    programs into the bundle_size budget)."""
    payload_amount = {
        "houjin_id": _HOUJIN,
        "bundle_size": 5,
        "objective": "max_amount",
    }
    payload_count = {
        "houjin_id": _HOUJIN,
        "bundle_size": 5,
        "objective": "max_count",
    }
    r_amount = bundle_client.post("/v1/intel/bundle/optimal", json=payload_amount)
    r_count = bundle_client.post("/v1/intel/bundle/optimal", json=payload_count)
    assert r_amount.status_code == 200, r_amount.text
    assert r_count.status_code == 200, r_count.text

    n_amount = len(r_amount.json()["bundle"])
    n_count = len(r_count.json()["bundle"])
    assert n_count >= n_amount, (
        f"max_count returned fewer programs ({n_count}) than max_amount ({n_amount}) — should be >="
    )

    # max_amount always returns the highest-amount candidate first.
    body_amount = r_amount.json()
    assert body_amount["bundle"][0]["program_id"] == "UNI-bundle-A"


# ---------------------------------------------------------------------------
# Test 4 — malformed houjin_id string returns 422.
# ---------------------------------------------------------------------------


def test_bundle_optimal_malformed_houjin_string_returns_422(
    bundle_client: TestClient,
) -> None:
    """A non-13-digit houjin_id string yields a structured 422 error."""
    resp = bundle_client.post(
        "/v1/intel/bundle/optimal",
        json={
            "houjin_id": "not-a-real-bangou",
            "bundle_size": 3,
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "invalid_houjin_bangou"
    assert detail["field"] == "houjin_id"


# ---------------------------------------------------------------------------
# Test 5 — compact=true keeps decision_support.
# ---------------------------------------------------------------------------


def test_bundle_optimal_compact_retains_decision_support(
    bundle_client: TestClient,
) -> None:
    """The shared compact projection drops unknown top-level fields, so this
    endpoint re-attaches decision_support after compaction."""
    resp = bundle_client.post(
        "/v1/intel/bundle/optimal?compact=true",
        json={
            "houjin_id": _HOUJIN,
            "bundle_size": 5,
            "objective": "max_amount",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["_c"] == 1
    support = _assert_decision_support_shape(body)
    assert "predicate_filter" in {item["signal"] for item in support["decision_insights"]}


# ---------------------------------------------------------------------------
# Test 6 — paid final cap failure must fail closed without billing.
# ---------------------------------------------------------------------------


def test_bundle_optimal_paid_final_cap_failure_returns_503_without_usage_event(
    bundle_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A paid bundle response must not be delivered if final cap billing fails."""
    import jpintel_mcp.api.deps as deps

    key_hash = hash_api_key(paid_key)
    endpoint = "intel.bundle_optimal"

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(count)
        finally:
            conn.close()

    def _reject_final_cap(*_args, **_kwargs):
        return False, False

    before = usage_count()
    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    resp = bundle_client.post(
        "/v1/intel/bundle/optimal",
        json={
            "houjin_id": _HOUJIN,
            "bundle_size": 5,
            "objective": "max_amount",
        },
        headers={"X-API-Key": paid_key},
    )

    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before
