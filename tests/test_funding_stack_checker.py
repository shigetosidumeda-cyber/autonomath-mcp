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

import contextlib
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


@pytest.fixture(autouse=True)
def _ensure_audit_seal_tables(seeded_db: Path) -> None:
    """Layer audit seal migrations onto the baseline seeded jpintel DB."""
    migrations = Path(__file__).resolve().parents[1] / "scripts" / "migrations"
    for mig in ("089_audit_seal_table.sql", "119_audit_seal_seal_id_columns.sql"):
        conn = sqlite3.connect(seeded_db)
        try:
            with contextlib.suppress(sqlite3.OperationalError):
                conn.executescript((migrations / mig).read_text(encoding="utf-8"))
            conn.commit()
        finally:
            conn.close()

    from jpintel_mcp.api._audit_seal import _reset_corpus_snapshot_cache_for_tests

    _reset_corpus_snapshot_cache_for_tests()


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
        (
            "P20",
            "P21",
            "incompatible",
            "重複受給禁止 (適正化法 17 条)",
            "https://example.test/i1",
            0.95,
            0,
        ),
        # unknown / heuristic rows (case_by_case + inferred_only=1 — covers test 3 / 4)
        ("P1", "P2", "case_by_case", "heuristic — 経費分離可なら併用可", None, 0.4, 1),
        ("P30", "P31", "case_by_case", "heuristic", None, 0.3, 1),
        # Heuristic incompatible without source_url: must not become a hard blocker.
        ("P40", "P41", "incompatible", "heuristic — 併用不可推定", None, 0.25, 1),
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


def _action_ids(actions: list[dict[str, object]]) -> list[str]:
    ids: list[str] = []
    for action in actions:
        assert isinstance(action, dict)
        assert {
            "action_id",
            "label_ja",
            "detail_ja",
            "reason",
            "source_fields",
        } <= set(action)
        assert isinstance(action["label_ja"], str)
        assert isinstance(action["detail_ja"], str)
        assert isinstance(action["reason"], str)
        assert isinstance(action["source_fields"], list)
        ids.append(str(action["action_id"]))
    return ids


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
    assert _action_ids(v.next_actions) == [
        "keep_evidence",
        "retain_cost_allocation_docs",
    ]
    body = v.to_dict()
    assert body["next_actions"] == v.next_actions
    assert "_disclaimer" in body
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
    assert v.hard_blocker is True
    assert v.rule_chain[0]["source"] == "am_compat_matrix"
    assert v.rule_chain[0]["compat_status"] == "incompatible"
    assert v.rule_chain[0]["evidence_level"] == "authoritative"
    assert v.rule_chain[0]["hard_blocker"] is True
    assert _action_ids(v.next_actions) == [
        "same_expense_check",
        "split_cost_basis",
        "choose_alternative_bundle",
        "verify_primary_rule",
    ]
    assert v.to_dict()["next_actions"] == v.next_actions


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
    assert decisive["hard_blocker"] is True


def test_check_pair_heuristic_incompatible_without_source_requires_review(
    checker: FundingStackChecker,
) -> None:
    """inferred_only=1 かつ source_url なしの incompatible は、推定由来の
    warning/requires_review として扱い、hard blocker にはしない。"""

    v = checker.check_pair("P40", "P41")

    assert v.verdict == "requires_review"
    assert v.confidence == 0.3
    assert v.hard_blocker is False
    step = v.rule_chain[0]
    assert step["source"] == "am_compat_matrix"
    assert step["compat_status"] == "incompatible"
    assert step["inferred_only"] == 1
    assert step["source_url"] is None
    assert step["evidence_level"] == "heuristic"
    assert step["hard_blocker"] is False
    assert _action_ids(v.next_actions) == [
        "verify_inferred_incompatibility",
        "contact_program_office",
        "add_manual_review",
    ]
    body = v.to_dict()
    assert body["hard_blocker"] is False


def test_check_stack_heuristic_incompatible_without_source_is_warning(
    checker: FundingStackChecker,
) -> None:
    """推定のみの incompatible pair だけなら stack 全体も blocker ではなく
    requires_review として返す。"""

    result = checker.check_stack(["P40", "P41"])

    assert result.all_pairs_status == "requires_review"
    assert result.blockers == []
    assert len(result.warnings) == 1
    assert result.warnings[0]["program_a"] == "P40"
    assert result.warnings[0]["program_b"] == "P41"
    assert result.warnings[0]["hard_blocker"] is False
    assert result.pairs[0]["hard_blocker"] is False
    assert _action_ids(result.next_actions) == [
        "verify_inferred_incompatibility",
        "contact_program_office",
        "add_manual_review",
    ]


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
    assert _action_ids(v.next_actions) == [
        "contact_program_office",
        "confirm_prerequisite_certification",
        "separate_expense_categories",
    ]


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
    assert any(b["program_a"] == "P20" and b["program_b"] == "P21" for b in result.blockers)
    assert _action_ids(result.next_actions)[:4] == [
        "same_expense_check",
        "split_cost_basis",
        "choose_alternative_bundle",
        "verify_primary_rule",
    ]
    assert "fetch_primary_source" in _action_ids(result.next_actions)
    body = result.to_dict()
    assert body["next_actions"] == result.next_actions
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
        (
            "excl-fs-P1-vs-P2",
            "absolute",
            "critical",
            "P1",
            "P2",
            None,
            "P1 と P2 は絶対併用不可",
            json.dumps([]),
        ),
        (
            "excl-fs-P3-requires-P4",
            "prerequisite",
            "high",
            "P3",
            "P4",
            None,
            "P3 は P4 を前提とする",
            json.dumps([]),
        ),
        (
            "excl-fs-P5-vs-group",
            "exclude",
            "high",
            "P5",
            None,
            json.dumps(["P6", "P7"]),
            "P5 は P6 / P7 と併用不可",
            json.dumps([]),
        ),
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

    monkeypatch.setattr(fs_module.settings, "autonomath_db_path", am, raising=False)
    fs_module.reset_checker()

    # MCP-side checker (used by tool-level tests) shares the same singleton
    # contract; reset for safety.
    try:
        from jpintel_mcp.mcp.autonomath_tools import funding_stack_tools as fst_module

        monkeypatch.setattr(fst_module.settings, "autonomath_db_path", am, raising=False)
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
    assert _action_ids(body["next_actions"]) == [
        "same_expense_check",
        "split_cost_basis",
        "choose_alternative_bundle",
        "verify_primary_rule",
        "fetch_primary_source",
        "mark_unknown_not_safe",
        "add_manual_review",
    ]
    pair_by_ids = {(pair["program_a"], pair["program_b"]): pair for pair in body["pairs"]}
    assert _action_ids(pair_by_ids[("P10", "P11")]["next_actions"]) == [
        "keep_evidence",
        "retain_cost_allocation_docs",
    ]
    assert _action_ids(pair_by_ids[("P20", "P21")]["next_actions"]) == [
        "same_expense_check",
        "split_cost_basis",
        "choose_alternative_bundle",
        "verify_primary_rule",
    ]
    assert _action_ids(pair_by_ids[("P10", "P20")]["next_actions"]) == [
        "fetch_primary_source",
        "mark_unknown_not_safe",
        "add_manual_review",
    ]
    assert all(pair["next_actions"] for pair in body["pairs"])
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


def test_rest_endpoint_quantity_logged_per_pair(rest_client, seeded_db: Path, paid_key) -> None:
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
    body = r.json()
    assert body["total_pairs"] == 10
    assert len(body["pairs"]) == 10
    assert body["next_actions"]
    assert all(pair["next_actions"] for pair in body["pairs"])

    # TestClient runs BackgroundTasks synchronously after the response,
    # so by the time we get here the deferred row has been committed via
    # _record_usage_async's own connection.
    c = sqlite3.connect(seeded_db)
    try:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT quantity, result_count FROM usage_events "
            "WHERE key_hash = ? AND endpoint = 'funding_stack.check' "
            "ORDER BY id DESC LIMIT 1",
            (key_hash,),
        ).fetchall()
    finally:
        c.close()

    assert len(rows) == 1
    assert int(rows[0]["quantity"]) == 10
    assert int(rows[0]["result_count"]) == 10


def test_artifact_compatibility_table_wraps_funding_stack(rest_client) -> None:
    payload = {
        "program_ids": ["P10", "P11", "P20", "P21", "P-ALONE"],
    }
    r = rest_client.post("/v1/artifacts/compatibility_table", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["artifact_type"] == "compatibility_table"
    assert body["endpoint"] == "artifacts.compatibility_table"
    assert body["summary"]["total_pairs"] == 10
    assert body["summary"]["all_pairs_status"] == "incompatible"
    assert body["summary"]["verdict_counts"]["incompatible"] == 1
    assert body["summary"]["verdict_counts"]["unknown"] >= 1
    assert "corpus_snapshot_id" in body
    assert "corpus_checksum" in body
    assert body["packet_id"].startswith("pkt_compatibility_table_")
    assert body["_evidence"]["source_count"] == len(body["sources"])
    assert body["copy_paste_parts"]
    assert body["markdown_display"].startswith("# compatibility_table")
    assert body["recommended_followup"]
    assert body["human_review_required"]
    assert body["billing_metadata"]["endpoint"] == "artifacts.compatibility_table"
    assert body["billing_metadata"]["unit_type"] == "compatibility_pair"
    assert body["billing_metadata"]["quantity"] == 10
    assert body["billing_metadata"]["result_count"] == 10
    assert body["billing_metadata"]["pair_count"] == 10
    assert body["billing_metadata"]["metered"] is False
    assert body["billing_metadata"]["strict_metering"] is True
    assert body["billing_metadata"]["pricing_note"] == body["billing_note"]
    assert body["billing_metadata"]["audit_seal"]["authenticated_key_present"] is False
    assert body["billing_metadata"]["audit_seal"]["requested_for_metered_key"] is False
    assert (
        body["billing_metadata"]["audit_seal"]["billing_metadata_covered_by_response_hash"] is False
    )
    assert body["billing_metadata"]["audit_seal"]["seal_field_excluded_from_response_hash"] is False
    assert any(
        gap.get("gap_id") == "source_missing" and gap.get("message") == "source_missing:pair_003"
        for gap in body["known_gaps"]
    )
    claim_coverage = body["_evidence"]["claim_coverage"]
    assert claim_coverage["claim_count"] == body["summary"]["total_pairs"]
    assert claim_coverage["source_missing_claim_count"] >= 1

    sections = {section["section_id"]: section for section in body["sections"]}
    rows = sections["compatibility_pairs"]["rows"]
    assert len(rows) == 10
    assert rows[0]["row_id"] == "pair_001"
    assert all(row["next_actions"] for row in rows)
    assert sections["blockers"]["rows"]
    assert any(source["source_url"] == "https://example.test/c1" for source in body["sources"])


def test_artifact_compatibility_table_6_programs_returns_422(rest_client) -> None:
    r = rest_client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["A", "B", "C", "D", "E", "F"]},
    )
    assert r.status_code == 422, r.text


def test_artifact_compatibility_table_usage_logged_per_pair(
    rest_client, seeded_db: Path, paid_key
) -> None:
    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(paid_key)
    payload = {
        "program_ids": ["P10", "P11", "P20", "P21", "P-ALONE"],
    }
    r = rest_client.post(
        "/v1/artifacts/compatibility_table",
        json=payload,
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["total_pairs"] == 10
    assert "audit_seal" in body
    assert body["billing_metadata"]["endpoint"] == "artifacts.compatibility_table"
    assert body["billing_metadata"]["unit_type"] == "compatibility_pair"
    assert body["billing_metadata"]["quantity"] == 10
    assert body["billing_metadata"]["result_count"] == 10
    assert body["billing_metadata"]["pair_count"] == 10
    assert body["billing_metadata"]["metered"] is True
    assert body["billing_metadata"]["audit_seal"]["authenticated_key_present"] is True
    assert body["billing_metadata"]["audit_seal"]["requested_for_metered_key"] is True
    assert body["billing_metadata"]["audit_seal"]["included_when_available"] is True
    assert (
        body["billing_metadata"]["audit_seal"]["billing_metadata_covered_by_response_hash"] is True
    )

    from jpintel_mcp.api._audit_seal import _canonical_json, _sha256_hex

    sealed_body = dict(body)
    seal = sealed_body.pop("audit_seal")
    assert seal["response_hash"] == _sha256_hex(_canonical_json(sealed_body))
    without_billing = dict(sealed_body)
    without_billing.pop("billing_metadata")
    assert seal["response_hash"] != _sha256_hex(_canonical_json(without_billing))

    c = sqlite3.connect(seeded_db)
    try:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT quantity, result_count FROM usage_events "
            "WHERE key_hash = ? AND endpoint = 'artifacts.compatibility_table' "
            "ORDER BY id DESC LIMIT 1",
            (key_hash,),
        ).fetchall()
    finally:
        c.close()

    assert len(rows) == 1
    assert int(rows[0]["quantity"]) == 10
    assert int(rows[0]["result_count"]) == 10


@pytest.mark.parametrize(
    ("path", "endpoint", "payload"),
    [
        pytest.param(
            "/v1/artifacts/compatibility_table",
            "artifacts.compatibility_table",
            {"program_ids": ["P10", "P11", "P20", "P21", "P-ALONE"]},
            id="compatibility_table",
        ),
        pytest.param(
            "/v1/artifacts/application_strategy_pack",
            "artifacts.application_strategy_pack",
            {
                "profile": {"prefecture": "Tokyo"},
                "max_candidates": 2,
                "compatibility_top_n": 0,
            },
            id="application_strategy_pack",
        ),
    ],
)
def test_paid_artifact_seal_persist_failure_not_billed(
    rest_client,
    seeded_db: Path,
    paid_key,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    endpoint: str,
    payload: dict[str, object],
) -> None:
    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(paid_key)

    def usage_totals() -> tuple[int, int]:
        c = sqlite3.connect(seeded_db)
        try:
            row = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(quantity), 0) FROM usage_events "
                "WHERE key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(row[0]), int(row[1])
        finally:
            c.close()

    def audit_seal_count() -> int:
        c = sqlite3.connect(seeded_db)
        try:
            row = c.execute(
                "SELECT COUNT(*) FROM audit_seals WHERE api_key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(row[0])
        finally:
            c.close()

    before_usage = usage_totals()
    before_seals = audit_seal_count()

    def fail_persist(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        raise sqlite3.OperationalError("forced seal persist failure")

    monkeypatch.setattr("jpintel_mcp.api._audit_seal.persist_seal", fail_persist)

    r = rest_client.post(
        path,
        json=payload,
        headers={"X-API-Key": paid_key},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "audit_seal_persist_failed"
    assert usage_totals() == before_usage
    assert audit_seal_count() == before_seals


@pytest.mark.parametrize(
    ("path", "endpoint", "payload"),
    [
        pytest.param(
            "/v1/artifacts/compatibility_table",
            "artifacts.compatibility_table",
            {"program_ids": ["P10", "P11", "P20", "P21", "P-ALONE"]},
            id="compatibility_table",
        ),
        pytest.param(
            "/v1/artifacts/application_strategy_pack",
            "artifacts.application_strategy_pack",
            {
                "profile": {"prefecture": "Tokyo"},
                "max_candidates": 2,
                "compatibility_top_n": 0,
            },
            id="application_strategy_pack",
        ),
    ],
)
def test_paid_artifact_final_metering_cap_failure_not_billed_or_sealed(
    rest_client,
    seeded_db: Path,
    paid_key,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    endpoint: str,
    payload: dict[str, object],
) -> None:
    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.api.middleware import customer_cap

    key_hash = hash_api_key(paid_key)

    def usage_totals() -> tuple[int, int]:
        c = sqlite3.connect(seeded_db)
        try:
            row = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(quantity), 0) FROM usage_events "
                "WHERE key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(row[0]), int(row[1])
        finally:
            c.close()

    def audit_seal_count() -> int:
        c = sqlite3.connect(seeded_db)
        try:
            row = c.execute(
                "SELECT COUNT(*) FROM audit_seals WHERE api_key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(row[0])
        finally:
            c.close()

    before_usage = usage_totals()
    before_seals = audit_seal_count()
    monkeypatch.setattr(
        customer_cap,
        "metered_charge_within_cap",
        lambda *args, **kwargs: False,
    )

    r = rest_client.post(
        path,
        json=payload,
        headers={"X-API-Key": paid_key},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_totals() == before_usage
    assert audit_seal_count() == before_seals


@pytest.mark.parametrize("tier", ["trial", "free"])
def test_artifact_compatibility_table_non_metered_seal_persist_failure_returns_200(
    rest_client,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    tier: str,
) -> None:
    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.billing.keys import issue_key

    conn = sqlite3.connect(seeded_db)
    try:
        raw_key = issue_key(
            conn,
            customer_id=f"cus_{tier}_artifact_seal_failure",
            tier=tier,
            stripe_subscription_id=None,
        )
        conn.commit()
    finally:
        conn.close()

    key_hash = hash_api_key(raw_key)

    def usage_rows() -> list[sqlite3.Row]:
        c = sqlite3.connect(seeded_db)
        try:
            c.row_factory = sqlite3.Row
            return c.execute(
                "SELECT id, metered, quantity, result_count FROM usage_events "
                "WHERE key_hash = ? AND endpoint = 'artifacts.compatibility_table' "
                "ORDER BY id",
                (key_hash,),
            ).fetchall()
        finally:
            c.close()

    before_usage = usage_rows()

    def fail_persist(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        raise sqlite3.OperationalError("forced seal persist failure")

    monkeypatch.setattr("jpintel_mcp.api._audit_seal.persist_seal", fail_persist)

    r = rest_client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["P10", "P11", "P20", "P21", "P-ALONE"]},
        headers={"X-API-Key": raw_key},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["_seal_unavailable"] is True
    assert "audit_seal" not in body
    assert body["billing_metadata"]["metered"] is False
    audit_metadata = body["billing_metadata"]["audit_seal"]
    assert audit_metadata["authenticated_key_present"] is True
    assert audit_metadata["requested_for_metered_key"] is False
    assert audit_metadata["seal_unavailable"] is True
    assert audit_metadata["included_when_available"] is False
    assert audit_metadata["billing_metadata_covered_by_response_hash"] is False
    assert audit_metadata["seal_field_excluded_from_response_hash"] is False
    assert "authenticated_response_audit_seal" not in body["billing_metadata"]["value_basis"]
    assert "metered_response_audit_seal" not in body["billing_metadata"]["value_basis"]

    after_usage = usage_rows()
    assert len(after_usage) == len(before_usage) + 1
    usage = after_usage[-1]
    assert int(usage["metered"]) == 0
    assert int(usage["quantity"]) == 10
    assert int(usage["result_count"]) == 10


def test_artifact_compatibility_table_trial_key_not_marked_metered(
    rest_client,
    seeded_db: Path,
) -> None:
    from jpintel_mcp.billing.keys import issue_key

    conn = sqlite3.connect(seeded_db)
    try:
        trial_key = issue_key(conn, customer_id="cus_trial_artifact", tier="trial")
        conn.commit()
    finally:
        conn.close()

    r = rest_client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["P10", "P11", "P20", "P21", "P-ALONE"]},
        headers={"X-API-Key": trial_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["billing_metadata"]["metered"] is False
    assert body["billing_metadata"]["audit_seal"]["authenticated_key_present"] is True
    assert body["billing_metadata"]["audit_seal"]["requested_for_metered_key"] is False
    assert body["billing_metadata"]["audit_seal"]["included_when_available"] is True
    assert (
        body["billing_metadata"]["audit_seal"]["billing_metadata_covered_by_response_hash"] is True
    )
    assert body["billing_metadata"]["audit_seal"]["seal_field_excluded_from_response_hash"] is True
    assert "authenticated_response_audit_seal" in body["billing_metadata"]["value_basis"]
    assert "metered_response_audit_seal" not in body["billing_metadata"]["value_basis"]


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
