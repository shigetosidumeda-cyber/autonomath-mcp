"""Tests for FundingStackChecker (Plan §8.4 + §28.7 — no LLM rule engine).

Covers:

  1. check_pair (sourced compatible) → compatible, confidence=1.0.
  2. check_pair (sourced incompatible) → incompatible, confidence=1.0.
  3. check_pair (am_compat unknown + exclusion_rule absolute) → incompatible
     (rule fallback wins).
  4. check_pair (no data anywhere) → unknown, confidence=0.0.
  5. check_pair (prerequisite chain) → requires_review.
  6. check_stack of 3 programs with one incompat pair → all_pairs_status =
     'incompatible' + non-empty blockers.
  7. REST endpoint with 5 programs returns 10 pair entries.
  8. REST endpoint with 6 programs → 422.
  9. log_usage called with quantity=10 (10 pairs) for 5 programs.

Each test builds a tmp jpintel.db (with the slim schema needed by
``exclusion_rules``) and a tmp autonomath.db (with ``am_compat_matrix``)
so we never touch the production 9.4 GB DB.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.services.funding_stack_checker import (
    FundingStackChecker,
    StackResult,
    StackVerdict,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_jpintel_db(path: Path) -> None:
    """Create a slim jpintel.db with just an exclusion_rules table.

    Schema mirrors ``data/jpintel.db`` post-migration 051.
    """
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE exclusion_rules (
            rule_id              TEXT PRIMARY KEY,
            kind                 TEXT NOT NULL,
            severity             TEXT,
            program_a            TEXT,
            program_b            TEXT,
            program_b_group_json TEXT,
            description          TEXT,
            source_notes         TEXT,
            source_urls_json     TEXT,
            extra_json           TEXT,
            source_excerpt       TEXT,
            condition            TEXT,
            program_a_uid        TEXT,
            program_b_uid        TEXT
        );
        CREATE INDEX idx_exclusion_program_a ON exclusion_rules(program_a);
        CREATE INDEX idx_exclusion_program_b ON exclusion_rules(program_b);
        """
    )
    rules = [
        # P1 ↔ P2 absolute incompatibility (covers test 3).
        {
            "rule_id": "excl-P1-vs-P2-absolute",
            "kind": "absolute",
            "severity": "critical",
            "program_a": "P1",
            "program_b": "P2",
            "description": "P1 と P2 は絶対併用不可 (テスト固定)",
            "source_urls_json": json.dumps(["https://example.test/abs"]),
        },
        # P3 requires P4 (covers test 5 prerequisite chain).
        {
            "rule_id": "excl-P3-requires-P4",
            "kind": "prerequisite",
            "severity": "high",
            "program_a": "P3",
            "program_b": "P4",
            "description": "P3 は P4 を前提とする (テスト固定)",
            "source_urls_json": json.dumps([]),
        },
        # Group-style exclude rule using program_b_group_json (additional
        # coverage of the matcher beyond the (a, b) form).
        {
            "rule_id": "excl-P5-vs-group",
            "kind": "exclude",
            "severity": "high",
            "program_a": "P5",
            "program_b": None,
            "program_b_group_json": json.dumps(["P6", "P7"]),
            "description": "P5 は P6 / P7 と併用不可 (group-style)",
            "source_urls_json": json.dumps([]),
        },
        # UID-keyed rule (post-migration 051) — proves _uid columns are
        # honoured. Maps "プログラム1" → P1 / "プログラム2" → P2.
        {
            "rule_id": "excl-uid-mapped",
            "kind": "absolute",
            "severity": "high",
            "program_a": "プログラム1",
            "program_b": "プログラム2",
            "description": "uid-keyed テスト排他",
            "source_urls_json": json.dumps([]),
            "program_a_uid": "P1",
            "program_b_uid": "P2",
        },
    ]
    for r in rules:
        conn.execute(
            """
            INSERT INTO exclusion_rules(
                rule_id, kind, severity, program_a, program_b,
                program_b_group_json, description, source_urls_json,
                program_a_uid, program_b_uid
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                r["rule_id"],
                r["kind"],
                r.get("severity"),
                r.get("program_a"),
                r.get("program_b"),
                r.get("program_b_group_json"),
                r["description"],
                r.get("source_urls_json"),
                r.get("program_a_uid"),
                r.get("program_b_uid"),
            ),
        )
    conn.commit()
    conn.close()


def _build_autonomath_db(path: Path) -> None:
    """Create a slim autonomath.db with just am_compat_matrix.

    Schema mirrors ``autonomath.db`` (43,966-row production table).
    """
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE am_compat_matrix (
            program_a_id      TEXT NOT NULL,
            program_b_id      TEXT NOT NULL,
            compat_status     TEXT NOT NULL CHECK(compat_status IN
                ('compatible','incompatible','case_by_case','unknown')),
            combined_max_yen  INTEGER,
            conditions_text   TEXT,
            rationale_short   TEXT,
            evidence_relation TEXT,
            source_url        TEXT,
            confidence        REAL,
            generated_at      TEXT DEFAULT (datetime('now')),
            inferred_only     INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (program_a_id, program_b_id)
        );
        """
    )
    rows = [
        # 3 sourced (inferred_only=0) compatible
        ("P10", "P11", "compatible", "経費分離可で併用可", "https://example.test/c1", 0.9, 0),
        ("P12", "P13", "compatible", "前後関係で併用可", "https://example.test/c2", 0.9, 0),
        ("P14", "P15", "compatible", "対象経費分離可", "https://example.test/c3", 0.9, 0),
        # 1 sourced incompatible (covers test 2)
        ("P20", "P21", "incompatible", "重複受給禁止 (適正化法 17 条)", "https://example.test/i1", 0.95, 0),
        # 2 unknown / heuristic (case_by_case + inferred_only=1 — covers test 3 / 4)
        ("P1", "P2", "case_by_case", "heuristic — 経費分離可なら併用可", None, 0.4, 1),
        ("P30", "P31", "case_by_case", "heuristic", None, 0.3, 1),
    ]
    for r in rows:
        conn.execute(
            """
            INSERT INTO am_compat_matrix(
                program_a_id, program_b_id, compat_status,
                rationale_short, source_url, confidence, inferred_only
            ) VALUES (?,?,?,?,?,?,?)
            """,
            r,
        )
    conn.commit()
    conn.close()


@pytest.fixture
def tmp_dbs(tmp_path: Path) -> tuple[Path, Path]:
    """Build a fresh (jpintel.db, autonomath.db) pair under ``tmp_path``."""
    jp = tmp_path / "jpintel.db"
    am = tmp_path / "autonomath.db"
    _build_jpintel_db(jp)
    _build_autonomath_db(am)
    return jp, am


@pytest.fixture
def checker(tmp_dbs: tuple[Path, Path]) -> FundingStackChecker:
    jp, am = tmp_dbs
    return FundingStackChecker(jpintel_db=jp, autonomath_db=am)


# ---------------------------------------------------------------------------
# Test 1 — sourced compatible
# ---------------------------------------------------------------------------


def test_check_pair_sourced_compatible(checker: FundingStackChecker) -> None:
    """A pair with am_compat_matrix.inferred_only=0 + status=compatible
    must return verdict='compatible' at confidence=1.0."""

    v = checker.check_pair("P10", "P11")

    assert isinstance(v, StackVerdict)
    assert v.verdict == "compatible"
    assert v.confidence == 1.0
    assert v.rule_chain[0]["source"] == "am_compat_matrix"
    assert v.rule_chain[0]["compat_status"] == "compatible"
    assert v.rule_chain[0]["inferred_only"] == 0
    assert "_disclaimer" in v.to_dict()
    # Order independence.
    v_swapped = checker.check_pair("P11", "P10")
    assert v_swapped.verdict == "compatible"
    assert v_swapped.confidence == 1.0


# ---------------------------------------------------------------------------
# Test 2 — sourced incompatible
# ---------------------------------------------------------------------------


def test_check_pair_sourced_incompatible(checker: FundingStackChecker) -> None:
    """A pair with sourced incompatible row → confidence=1.0."""

    v = checker.check_pair("P20", "P21")

    assert v.verdict == "incompatible"
    assert v.confidence == 1.0
    assert v.rule_chain[0]["source"] == "am_compat_matrix"
    assert v.rule_chain[0]["compat_status"] == "incompatible"


# ---------------------------------------------------------------------------
# Test 3 — am_compat unknown + exclusion_rule absolute → rule fallback
# ---------------------------------------------------------------------------


def test_check_pair_rule_fallback_wins_over_heuristic(
    checker: FundingStackChecker,
) -> None:
    """When am_compat_matrix has only a heuristic case_by_case row but
    an exclusion_rules absolute rule pins (a, b) as incompatible, the
    rule fallback must WIN. Verdict=incompatible at confidence=0.9."""

    v = checker.check_pair("P1", "P2")

    assert v.verdict == "incompatible"
    assert v.confidence == 0.9
    sources = [step["source"] for step in v.rule_chain]
    assert "am_compat_matrix" in sources
    assert "exclusion_rules" in sources
    # Last step (the deciding one) is the exclusion rule.
    decisive = v.rule_chain[-1]
    assert decisive["source"] == "exclusion_rules"
    assert decisive["kind"] == "absolute"


# ---------------------------------------------------------------------------
# Test 4 — no data anywhere → unknown, confidence=0
# ---------------------------------------------------------------------------


def test_check_pair_no_data_unknown(checker: FundingStackChecker) -> None:
    """A pair absent from both corpora returns unknown + confidence=0."""

    v = checker.check_pair("Q-NEVER-SEEN", "Q-ALSO-NEVER-SEEN")

    assert v.verdict == "unknown"
    assert v.confidence == 0.0
    assert "_disclaimer" in v.to_dict()
    assert v.rule_chain[-1]["source"] == "default"


# ---------------------------------------------------------------------------
# Test 5 — prerequisite chain → requires_review
# ---------------------------------------------------------------------------


def test_check_pair_prerequisite_requires_review(
    checker: FundingStackChecker,
) -> None:
    """When (a, b) appears in an exclusion_rules row of kind='prerequisite'
    and there is no overriding compat / absolute / exclude rule, the verdict
    must be requires_review (NOT auto-allowed)."""

    v = checker.check_pair("P3", "P4")

    assert v.verdict == "requires_review"
    assert 0.5 <= v.confidence <= 0.7
    decisive = v.rule_chain[-1]
    assert decisive["source"] == "exclusion_rules"
    assert decisive["kind"] == "prerequisite"


# ---------------------------------------------------------------------------
# Test 6 — check_stack with one incompatible pair
# ---------------------------------------------------------------------------


def test_check_stack_aggregates_to_incompatible(
    checker: FundingStackChecker,
) -> None:
    """3 programs (P10 / P11 / P20) yield 3 pairs:
       (P10, P11) → compatible (sourced)
       (P10, P20) → unknown (no data)
       (P11, P20) → unknown (no data)

    No incompat pair yet → expand to (P20, P21):
       4 programs P10/P11/P20/P21 → C(4,2)=6 pairs, one of which is
       sourced-incompatible (P20, P21). all_pairs_status must therefore
       roll up to 'incompatible' and blockers must contain that pair.
    """

    result = checker.check_stack(["P10", "P11", "P20", "P21"])

    assert isinstance(result, StackResult)
    assert result.all_pairs_status == "incompatible"
    assert len(result.pairs) == 6  # C(4, 2)
    assert any(
        b["program_a"] == "P20" and b["program_b"] == "P21"
        for b in result.blockers
    )
    body = result.to_dict()
    assert "_disclaimer" in body


def test_check_stack_three_programs_one_incompat() -> None:
    """The exact 3-program scenario from the spec: stack with one
    incompatible pair must surface all_pairs_status='incompatible' +
    non-empty blockers."""

    # Build a fresh DB pair where (P20, P21) is incompatible and
    # (P20, P10) / (P10, P21) are unknown — exactly mirrors the spec.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        jp = Path(td) / "jpintel.db"
        am = Path(td) / "autonomath.db"
        _build_jpintel_db(jp)
        _build_autonomath_db(am)
        c = FundingStackChecker(jpintel_db=jp, autonomath_db=am)

        result = c.check_stack(["P20", "P21", "P-ALONE"])

        assert result.all_pairs_status == "incompatible"
        assert len(result.pairs) == 3
        assert len(result.blockers) >= 1
        # The single blocker must reference both P20 and P21.
        bset = {(b["program_a"], b["program_b"]) for b in result.blockers}
        assert ("P20", "P21") in bset


# ---------------------------------------------------------------------------
# Test 7 + 8 + 9 — REST endpoint behaviour
# ---------------------------------------------------------------------------


@pytest.fixture
def rest_client(seeded_db: Path, tmp_path: Path, monkeypatch):
    """Build a TestClient whose funding_stack endpoint reads exclusion_rules
    from the existing seeded jpintel.db (which already has the auth tables
    + a couple of conftest exclusion_rules rows) and reads am_compat_matrix
    from a tmp autonomath.db with the fixture rows.

    We add the funding-stack-specific exclusion rules to the seeded DB so
    the (P1, P2) absolute and (P3, P4) prerequisite scenarios fire.
    """
    # Seed funding-stack-specific exclusion rules into the conftest DB.
    conn = sqlite3.connect(seeded_db)
    rules = [
        ("excl-fs-P1-vs-P2", "absolute", "critical", "P1", "P2", None,
         "P1 と P2 は絶対併用不可", json.dumps([])),
        ("excl-fs-P3-requires-P4", "prerequisite", "high", "P3", "P4", None,
         "P3 は P4 を前提とする", json.dumps([])),
        ("excl-fs-P5-vs-group", "exclude", "high", "P5", None,
         json.dumps(["P6", "P7"]),
         "P5 は P6 / P7 と併用不可", json.dumps([])),
    ]
    for r in rules:
        conn.execute(
            """
            INSERT OR REPLACE INTO exclusion_rules(
                rule_id, kind, severity, program_a, program_b,
                program_b_group_json, description, source_urls_json
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            r,
        )
    conn.commit()
    conn.close()

    # Build a tmp autonomath.db with our fixture rows.
    am = tmp_path / "autonomath.db"
    _build_autonomath_db(am)

    # Point only the AUTONOMATH_DB_PATH at the tmp file. JPINTEL_DB_PATH
    # stays on the conftest seeded DB so auth + log_usage continue to work.
    from jpintel_mcp.api import funding_stack as fs_module

    monkeypatch.setattr(
        fs_module.settings, "autonomath_db_path", am, raising=False
    )
    fs_module.reset_checker()

    # MCP-side checker (used by tool-level tests) shares the same singleton
    # contract; reset for safety.
    try:
        from jpintel_mcp.mcp.autonomath_tools import funding_stack_tools as fst_module
        monkeypatch.setattr(
            fst_module.settings, "autonomath_db_path", am, raising=False
        )
        fst_module._reset_checker()
    except Exception:
        pass

    from fastapi.testclient import TestClient

    from jpintel_mcp.api.main import create_app

    app = create_app()
    yield TestClient(app)
    fs_module.reset_checker()


def test_rest_endpoint_5_programs_returns_10_pairs(rest_client) -> None:
    """5 programs → C(5, 2) = 10 pair entries in the response."""

    payload = {
        "program_ids": ["P10", "P11", "P20", "P21", "P-ALONE"],
    }
    r = rest_client.post("/v1/funding_stack/check", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["pairs"]) == 10
    assert body["total_pairs"] == 10
    assert "_disclaimer" in body
    # all_pairs_status must roll up to 'incompatible' because (P20, P21)
    # is sourced-incompat in the fixture.
    assert body["all_pairs_status"] == "incompatible"


def test_rest_endpoint_6_programs_returns_422(rest_client) -> None:
    """6 programs exceeds the C(5, 2) cap and must 422."""

    payload = {
        "program_ids": ["A", "B", "C", "D", "E", "F"],
    }
    r = rest_client.post("/v1/funding_stack/check", json=payload)
    assert r.status_code == 422, r.text


def test_rest_endpoint_quantity_logged_per_pair(
    rest_client, seeded_db: Path, paid_key
) -> None:
    """5 programs (10 pairs) must result in a usage_events row whose
    ``quantity`` column = 10 — confirming we bill ¥3 per pair, not per
    request."""

    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(paid_key)
    payload = {
        "program_ids": ["P10", "P11", "P20", "P21", "P-ALONE"],
    }
    r = rest_client.post(
        "/v1/funding_stack/check",
        json=payload,
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200, r.text

    # TestClient runs BackgroundTasks synchronously after the response,
    # so by the time we get here the deferred row has been committed via
    # _record_usage_async's own connection.
    c = sqlite3.connect(seeded_db)
    try:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT quantity FROM usage_events "
            "WHERE key_hash = ? AND endpoint = 'funding_stack.check' "
            "ORDER BY id DESC LIMIT 1",
            (key_hash,),
        ).fetchall()
    finally:
        c.close()

    assert len(rows) == 1
    assert int(rows[0]["quantity"]) == 10


# ---------------------------------------------------------------------------
# Bonus: input-validation + group-style coverage
# ---------------------------------------------------------------------------


def test_check_pair_self_pair_short_circuits(checker: FundingStackChecker) -> None:
    v = checker.check_pair("P10", "P10")
    assert v.verdict == "incompatible"
    assert v.confidence == 1.0
    assert v.rule_chain[0]["source"] == "input_validation"


def test_check_pair_group_style_exclusion(checker: FundingStackChecker) -> None:
    """`program_b_group_json` array entries must trigger the exclusion."""
    v = checker.check_pair("P5", "P6")
    assert v.verdict == "incompatible"
    assert v.confidence == 0.9
    decisive = v.rule_chain[-1]
    assert decisive["source"] == "exclusion_rules"
    assert decisive["rule_id"] == "excl-P5-vs-group"


def test_check_pair_uid_match() -> None:
    """A rule keyed by program_a_uid / program_b_uid (migration 051) must
    fire when callers pass the resolved uid form."""

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        jp = Path(td) / "jpintel.db"
        am = Path(td) / "autonomath.db"
        _build_jpintel_db(jp)
        _build_autonomath_db(am)
        c = FundingStackChecker(jpintel_db=jp, autonomath_db=am)

        # Pass the uid keys directly (the rule_id "excl-uid-mapped" has
        # program_a="プログラム1" but program_a_uid="P1"). We also have a
        # heuristic case_by_case row for (P1, P2) so the chain has both
        # sources surfaced.
        v = c.check_pair("P1", "P2")
        assert v.verdict == "incompatible"
        # Two exclusion_rules absolute hits on (P1, P2): the first match
        # wins. Confidence floor is 0.9.
        assert v.confidence == 0.9
