"""Tests for am_compat_matrix full-surface API + MCP tools (R8, 2026-05-07).

Covers:
  * POST /v1/programs/portfolio_optimize — multi-program portfolio optimizer.
  * GET  /v1/programs/{a}/compatibility/{b} — pair verdict.
  * MCP impls (portfolio_optimize_impl / program_compatibility_pair_impl).

Coverage is via a tmp autonomath.db seeded with the four backing tables
(am_compat_matrix + am_funding_stack_empirical +
am_program_eligibility_predicate + am_relation) plus three programs in the
jpintel test DB so amount + tier rollups work.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_compat_programs(seeded_db: Path) -> None:
    """Insert four programs with distinct amount + tier + program_kind so
    the portfolio optimizer has a deterministic ordering across all axes."""
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        now = datetime.now(UTC).isoformat()
        rows = [
            ("UNI-compat-A", "互換テスト 補助金 A", "S", "補助金", 5000),  # ¥50M
            ("UNI-compat-B", "互換テスト 融資 B", "A", "融資", 3000),  # ¥30M
            ("UNI-compat-C", "互換テスト 税制 C", "B", "税制", 1000),  # ¥10M
            ("UNI-compat-D", "互換テスト 認定 D", "C", "認定", 500),  # ¥5M
        ]
        for uid, name, tier, kind, amax in rows:
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
def compat_autonomath_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """tmp autonomath.db with the four backing tables seeded.

    Pair layout (ids ordered A < B < C < D):
      * (A, B): am_compat_matrix.compat_status='compatible' (sourced).
      * (A, C): am_program_eligibility_predicate — C declares NOT_IN A.
      * (B, C): am_funding_stack_empirical conflict_flag=1 (matrix says
        'incompatible', co_adoption_count=8).
      * (C, D): am_compat_matrix.compat_status='incompatible' (rule-based).
      * (A, D): am_relation 'requires_before' edge — sequential.
      * (B, D): no row in any source — unknown.
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE am_compat_matrix (
                program_a_id      TEXT NOT NULL,
                program_b_id      TEXT NOT NULL,
                compat_status     TEXT NOT NULL,
                combined_max_yen  INTEGER,
                conditions_text   TEXT,
                rationale_short   TEXT,
                evidence_relation TEXT,
                source_url        TEXT,
                confidence        REAL,
                generated_at      TEXT NOT NULL DEFAULT (datetime('now')),
                inferred_only     INTEGER NOT NULL DEFAULT 0,
                visibility        TEXT NOT NULL DEFAULT 'public',
                PRIMARY KEY (program_a_id, program_b_id)
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
            CREATE TABLE am_relation (
                relation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                src_id TEXT NOT NULL,
                dst_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        # (A, B) compatible — sourced.
        conn.execute(
            "INSERT INTO am_compat_matrix"
            "(program_a_id, program_b_id, compat_status, combined_max_yen, "
            " rationale_short, source_url, confidence, inferred_only, visibility) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "UNI-compat-A",
                "UNI-compat-B",
                "compatible",
                80_000_000,
                "補助金 + 融資、原則併用可",
                "https://example.gov/ab.pdf",
                0.9,
                0,
                "public",
            ),
        )
        # (C, D) incompatible — guideline tier.
        conn.execute(
            "INSERT INTO am_compat_matrix"
            "(program_a_id, program_b_id, compat_status, source_url, "
            " confidence, inferred_only, visibility) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                "UNI-compat-C",
                "UNI-compat-D",
                "incompatible",
                "https://example.gov/cd.pdf",
                0.7,
                0,
                "public",
            ),
        )
        # (B, C) empirical conflict.
        conn.execute(
            "INSERT INTO am_funding_stack_empirical"
            "(program_a_id, program_b_id, co_adoption_count, "
            " compat_matrix_says, conflict_flag) VALUES (?,?,?,?,?)",
            ("UNI-compat-B", "UNI-compat-C", 8, "incompatible", 1),
        )
        # (A, C) legal predicate — C declares NOT_IN A.
        conn.execute(
            "INSERT INTO am_program_eligibility_predicate"
            "(program_unified_id, predicate_kind, operator, value_text, "
            " source_url, source_clause_quote) VALUES (?,?,?,?,?,?)",
            (
                "UNI-compat-C",
                "other",
                "NOT_IN",
                "UNI-compat-A",
                "https://example.gov/c-rule.pdf",
                "本制度は A と併用不可。",
            ),
        )
        # (A, D) sequential edge.
        conn.execute(
            "INSERT INTO am_relation(src_id, dst_id, relation_type) VALUES (?,?,?)",
            ("UNI-compat-A", "UNI-compat-D", "requires_before"),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)

    # Reset thread-local conn cache so the new path is picked up.
    from jpintel_mcp.mcp.autonomath_tools import db as am_db

    if hasattr(am_db, "_local"):
        am_db._local = type(am_db._local)()

    return db_path


@pytest.fixture()
def compat_client(
    seeded_db: Path,
    compat_autonomath_db: Path,  # noqa: ARG001 — autouse to seed the AM DB
) -> TestClient:
    """TestClient backed by the seeded jpintel.db + compat autonomath.db."""
    _seed_compat_programs(seeded_db)
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# REST: GET /v1/programs/{a}/compatibility/{b}
# ---------------------------------------------------------------------------


def test_pair_compatibility_compatible_via_matrix(
    compat_client: TestClient,
) -> None:
    """(A, B) is compatible per am_compat_matrix; verdict = 'compatible'."""
    resp = compat_client.get("/v1/programs/UNI-compat-A/compatibility/UNI-compat-B")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["compatibility"] == "compatible"
    assert body["program_a"] == "UNI-compat-A"
    assert body["program_b"] == "UNI-compat-B"
    assert body["inferred_only"] is False
    assert body["_billing_unit"] == 1
    assert "_disclaimer" in body and body["_disclaimer"]
    assert "matrix" in body["evidence"]


def test_pair_compatibility_mutually_exclusive_via_legal_predicate(
    compat_client: TestClient,
) -> None:
    """(A, C) — C declares NOT_IN A. verdict = 'mutually_exclusive'."""
    resp = compat_client.get("/v1/programs/UNI-compat-A/compatibility/UNI-compat-C")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["compatibility"] == "mutually_exclusive"
    assert "legal_predicate" in body["evidence"]
    assert body["evidence"]["legal_predicate"]["owning_program"] == "UNI-compat-C"


def test_pair_compatibility_mutually_exclusive_via_empirical(
    compat_client: TestClient,
) -> None:
    """(B, C) empirical conflict_flag=1. verdict = 'mutually_exclusive'."""
    resp = compat_client.get("/v1/programs/UNI-compat-B/compatibility/UNI-compat-C")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["compatibility"] == "mutually_exclusive"
    assert "empirical" in body["evidence"]
    assert body["evidence"]["empirical"]["conflict_flag"] == 1


def test_pair_compatibility_sequential_via_am_relation(
    compat_client: TestClient,
) -> None:
    """(A, D) — am_relation 'requires_before' edge; no matrix row.
    Verdict = 'sequential'."""
    resp = compat_client.get("/v1/programs/UNI-compat-A/compatibility/UNI-compat-D")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["compatibility"] == "sequential"
    assert "sequential" in body["evidence"]
    assert body["evidence"]["sequential"]["relation_type"] == "requires_before"


def test_pair_compatibility_unknown_when_no_row(compat_client: TestClient) -> None:
    """(B, D) — no row anywhere. verdict = 'unknown'."""
    resp = compat_client.get("/v1/programs/UNI-compat-B/compatibility/UNI-compat-D")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["compatibility"] == "unknown"


def test_pair_compatibility_422_on_same_program(compat_client: TestClient) -> None:
    """a == b is rejected before DB hit."""
    resp = compat_client.get("/v1/programs/UNI-compat-A/compatibility/UNI-compat-A")
    assert resp.status_code == 422


def test_pair_compatibility_422_on_invalid_id(compat_client: TestClient) -> None:
    """Junk characters in program id are rejected."""
    resp = compat_client.get("/v1/programs/UNI-compat-A/compatibility/<script>")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# REST: POST /v1/programs/portfolio_optimize
# ---------------------------------------------------------------------------


def test_portfolio_optimize_returns_max_amount_subset(
    compat_client: TestClient,
) -> None:
    """A + B + C + D — optimizer must drop conflicting members. The
    duplicate_risk surface should expose (A, C) legal, (B, C) empirical,
    (C, D) matrix, (A, D) sequential."""
    resp = compat_client.post(
        "/v1/programs/portfolio_optimize",
        json={
            "candidate_program_ids": [
                "UNI-compat-A",
                "UNI-compat-B",
                "UNI-compat-C",
                "UNI-compat-D",
            ],
            "target_axes": ["coverage", "amount", "risk"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["_billing_unit"] == 1
    assert "_disclaimer" in body and body["_disclaimer"]
    assert sorted(body["input_program_ids"]) == [
        "UNI-compat-A",
        "UNI-compat-B",
        "UNI-compat-C",
        "UNI-compat-D",
    ]
    assert body["target_axes"] == ["coverage", "amount", "risk"]

    # Duplicate risk pairs surfaced.
    risk_pairs = {(p["program_a"], p["program_b"]): p for p in body["duplicate_risk"]}
    assert ("UNI-compat-A", "UNI-compat-C") in risk_pairs
    assert ("UNI-compat-A", "UNI-compat-D") in risk_pairs  # sequential
    assert ("UNI-compat-B", "UNI-compat-C") in risk_pairs
    assert ("UNI-compat-C", "UNI-compat-D") in risk_pairs
    assert risk_pairs[("UNI-compat-A", "UNI-compat-C")]["compatibility"] == ("mutually_exclusive")
    assert risk_pairs[("UNI-compat-A", "UNI-compat-D")]["compatibility"] == "sequential"

    # Greedy by amount picks A (¥50M) first; A excludes C (legal) and D
    # (sequential) and B remains compatible with A → portfolio = {A, B}.
    portfolio = set(body["portfolio"])
    assert portfolio == {"UNI-compat-A", "UNI-compat-B"}

    # Recommended_mix returns up to 3 distinct bundles ranked by score.
    mix = body["recommended_mix"]
    assert isinstance(mix, list)
    assert 1 <= len(mix) <= 3
    scores = [m["score"] for m in mix]
    assert scores == sorted(scores, reverse=True)
    assert all(isinstance(m["bundle"], list) and m["bundle"] for m in mix)
    assert all("axis_scores" in m for m in mix)


def test_portfolio_optimize_axis_scores_normalized(
    compat_client: TestClient,
) -> None:
    """axis_scores must be in [0, 1] for every requested axis."""
    resp = compat_client.post(
        "/v1/programs/portfolio_optimize",
        json={
            "candidate_program_ids": ["UNI-compat-A", "UNI-compat-B"],
            "target_axes": ["coverage", "amount", "risk"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for axis, score in body["axis_scores"].items():
        assert 0.0 <= score <= 1.0, f"{axis} score out of range: {score}"


def test_portfolio_optimize_422_on_single_program(compat_client: TestClient) -> None:
    """min_length=2 must trigger before the route body runs."""
    resp = compat_client.post(
        "/v1/programs/portfolio_optimize",
        json={"candidate_program_ids": ["UNI-compat-A"]},
    )
    assert resp.status_code == 422


def test_portfolio_optimize_unknown_axes_default_to_amount(
    compat_client: TestClient,
) -> None:
    """All-unknown axes collapse to ['amount']."""
    resp = compat_client.post(
        "/v1/programs/portfolio_optimize",
        json={
            "candidate_program_ids": ["UNI-compat-A", "UNI-compat-B"],
            "target_axes": ["nonsense"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["target_axes"] == ["amount"]


def test_portfolio_optimize_graceful_when_tables_missing(
    seeded_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare autonomath.db (no compat tables) → empty duplicate_risk +
    missing_tables populated, 200 not 500."""
    _seed_compat_programs(seeded_db)
    bare_db = tmp_path / "bare_autonomath.db"
    conn = sqlite3.connect(bare_db)
    conn.execute("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(bare_db))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", bare_db)
    from jpintel_mcp.mcp.autonomath_tools import db as am_db

    if hasattr(am_db, "_local"):
        am_db._local = type(am_db._local)()
    from jpintel_mcp.api.main import create_app

    bare_client = TestClient(create_app())
    resp = bare_client.post(
        "/v1/programs/portfolio_optimize",
        json={
            "candidate_program_ids": ["UNI-compat-A", "UNI-compat-B"],
            "target_axes": ["amount"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["duplicate_risk"] == []
    missing = set(body["data_quality"]["missing_tables"])
    assert "am_compat_matrix" in missing


# ---------------------------------------------------------------------------
# MCP impls — direct call shape
# ---------------------------------------------------------------------------


def test_mcp_pair_impl_returns_4_bucket_verdict(
    compat_autonomath_db: Path,  # noqa: ARG001
) -> None:
    from jpintel_mcp.mcp.autonomath_tools.compatibility_tools import (
        program_compatibility_pair_impl,
    )

    res = program_compatibility_pair_impl("UNI-compat-A", "UNI-compat-B")
    assert res["compatibility"] == "compatible"
    assert res["_billing_unit"] == 1
    assert "_disclaimer" in res

    res2 = program_compatibility_pair_impl("UNI-compat-A", "UNI-compat-D")
    assert res2["compatibility"] == "sequential"


def test_mcp_portfolio_impl_returns_recommended_mix(
    seeded_db: Path,
    compat_autonomath_db: Path,  # noqa: ARG001
) -> None:
    _seed_compat_programs(seeded_db)
    from jpintel_mcp.mcp.autonomath_tools.compatibility_tools import (
        portfolio_optimize_impl,
    )

    res = portfolio_optimize_impl(
        candidate_program_ids=[
            "UNI-compat-A",
            "UNI-compat-B",
            "UNI-compat-C",
            "UNI-compat-D",
        ],
        target_axes=["coverage", "amount", "risk"],
    )
    assert res.get("portfolio")
    assert res.get("_billing_unit") == 1
    assert res.get("recommended_mix")
    assert all(0.0 <= v <= 1.0 for v in res["axis_scores"].values())


def test_mcp_pair_impl_same_program_returns_error(
    compat_autonomath_db: Path,  # noqa: ARG001
) -> None:
    from jpintel_mcp.mcp.autonomath_tools.compatibility_tools import (
        program_compatibility_pair_impl,
    )

    res = program_compatibility_pair_impl("UNI-compat-A", "UNI-compat-A")
    err = res.get("error") or {}
    assert isinstance(err, dict)
    assert err.get("code") == "invalid_input"
    assert err.get("field") == "a|b"
