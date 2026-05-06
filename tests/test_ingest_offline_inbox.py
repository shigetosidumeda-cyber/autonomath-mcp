"""End-to-end tests for `scripts/cron/ingest_offline_inbox.py`.

Per-tool happy-path: writes a minimal valid JSONL line into a temp inbox,
runs the cron with isolated SQLite databases (autonomath + jpintel),
asserts the production table has the expected row count.

Quarantine path: writes a JSONL with one bad row + one good row,
asserts the bad row lands under `_quarantine/{tool}/`, the good row is
applied, and the file is left in place (because n_quarantined > 0).

LLM-FREE guard: the existing `tests/test_offline_inbox_workflow.py`
already AST-checks the cron for forbidden imports; we re-assert here on
the schema package as a belt-and-suspenders measure.
"""

from __future__ import annotations

import ast
import importlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
SCRIPTS_ROOT = REPO_ROOT / "scripts"

# Ensure import path
sys.path.insert(0, str(SRC_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))


# ---------------------------------------------------------------------------
# Schema-shape constants — minimal valid rows for each of the 8 tool keys
# (+ amount_conditions for completeness). Field names mirror the Pydantic
# v2 models in src/jpintel_mcp/ingest/schemas/.
# ---------------------------------------------------------------------------

VALID_ROWS: dict[str, dict[str, Any]] = {
    "exclusion_rules": {
        "program_id": 100,
        "program_uid": "program-0100",
        "rules": [
            {
                "kind": "exclude",
                "target_program_uid": "program-0200",
                "clause_quote": "本事業は他の補助事業との重複受給はできない",
                "source_url": "https://example.go.jp/koubo.pdf",
                "confidence": "high",
            }
        ],
        "subagent_run_id": "test-run-001",
        "evaluated_at": "2026-05-04T00:00:00Z",
    },
    "enforcement_amount": {
        "enforcement_id": 999999,  # not in test DB, UPDATE will be 0-row
        "amount_yen": 1000000,
        "amount_kind": "fine",
        "currency": "JPY",
        "clause_quote": "違反者に対し金100万円を課す",
        "source_url": "https://example.go.jp/shobun.html",
        "source_fetched_at": "2026-05-04T00:00:00Z",
        "confidence": "high",
        "subagent_run_id": "test-run-002",
        "evaluated_at": "2026-05-04T00:00:00Z",
    },
    "jsic_tags": {
        "program_unified_id": "program-0100",
        "jsic_major": "E",
        "jsic_middle": "24",
        "jsic_minor": "242",
        "jsic_assigned_method": "classifier",
        "rationale": "製造業 keyword 一致",
        "confidence": "high",
        "subagent_run_id": "test-run-003",
        "assigned_at": "2026-05-04T00:00:00Z",
    },
    "program_narrative": {
        "program_id": 100,
        "program_unified_id": "program-0100",
        "lang": "ja",
        "section": "overview",
        "body_text": "本制度は中小企業の設備投資を支援する補助金である。詳細は公募要領を確認すること。",
        "source_url_json": ["https://example.go.jp/program-100.html"],
        "model_id": "claude-code-subagent",
        "literal_quote_check_passed": 0,
        "subagent_run_id": "test-run-004",
        "generated_at": "2026-05-04T00:00:00Z",
    },
    "houjin_360_narrative": {
        "houjin_bangou": "1234567890123",
        "lang": "ja",
        "body_text": "当法人は東京都内に本社を構える中堅企業である。",
        "source_url_json": ["https://www.houjin-bangou.nta.go.jp/"],
        "model_id": "claude-code-subagent",
        "subagent_run_id": "test-run-005",
        "generated_at": "2026-05-04T00:00:00Z",
    },
    "enforcement_summary": {
        "enforcement_id": 12345,
        "lang": "ja",
        "body_text": "本件は補助金不正受給に係る指名停止処分である。",
        "source_url_json": ["https://example.go.jp/shobun-12345.html"],
        "model_id": "claude-code-subagent",
        "subagent_run_id": "test-run-006",
        "generated_at": "2026-05-04T00:00:00Z",
    },
    "program_application_documents": {
        "program_unified_id": "program-0100",
        "documents": [
            {
                "program_unified_id": "program-0100",
                "doc_name": "事業計画書",
                "doc_kind": "計画書",
                "yoshiki_no": "様式第1号",
                "is_required": 1,
                "url": "https://example.go.jp/yoshiki1.pdf",
                "source_clause_quote": "事業計画書(様式第1号)を提出すること",
                "notes": None,
                "subagent_run_id": "test-run-007",
                "extracted_at": "2026-05-04T00:00:00Z",
            }
        ],
        "subagent_run_id": "test-run-007",
        "evaluated_at": "2026-05-04T00:00:00Z",
    },
    "eligibility_predicates": {
        "program_unified_id": "program-0100",
        "predicates": [
            {
                "program_unified_id": "program-0100",
                "predicate_kind": "capital_max",
                "operator": "<=",
                "value_text": None,
                "value_num": 300000000.0,
                "value_json": None,
                "is_required": 1,
                "source_url": "https://example.go.jp/program-100.html",
                "source_clause_quote": "資本金3億円以下の中小企業者",
                "subagent_run_id": "test-run-008",
                "extracted_at": "2026-05-04T00:00:00Z",
            }
        ],
        "subagent_run_id": "test-run-008",
        "evaluated_at": "2026-05-04T00:00:00Z",
    },
    "edinet_relations": {
        "seller_houjin_bangou": "1111111111111",
        "buyer_houjin_bangou": "2222222222222",
        "confidence": 0.85,
        "confidence_band": "high",
        "inferred_industry": "manufacturing",
        "evidence_kind": "public_disclosure",
        "evidence_count": 3,
        "source_url_json": ["https://disclosure.edinet-fsa.go.jp/example.xbrl"],
        "first_seen_at": "2026-01-01T00:00:00Z",
        "last_seen_at": "2026-04-30T00:00:00Z",
        "subagent_run_id": "test-run-009",
        "computed_at": "2026-05-04T00:00:00Z",
    },
    "amount_conditions": {
        "entity_id": "program-0100",
        "condition_label": "sme",
        "condition_kind": "subsidy_rate",
        "numeric_value": 0.5,
        "numeric_value_max": None,
        "unit": "ratio",
        "currency": None,
        "qualifier": None,
        "confidence": "high",
        "extracted_text": "中小企業者は補助率1/2以内とする",
        "source_url": "https://example.go.jp/program-100.html",
        "subagent_run_id": "test-run-010",
        "evaluated_at": "2026-05-04T00:00:00Z",
    },
}

VALID_SOURCE_PROFILE: dict[str, Any] = {
    "source_id": "p_portal_chotatsu",
    "priority": "P1",
    "official_owner": "デジタル庁",
    "source_url": "https://www.p-portal.go.jp/",
    "source_type": "html+bulk_download",
    "data_objects": ["procurement_notice", "award_result"],
    "acquisition_method": "bulk ZIP download",
    "auth_needed": False,
    "rate_limits": "none documented",
    "robots_policy": "robots.txt 404; no published crawl restriction",
    "license_or_terms": "government standard terms 2.0",
    "attribution_required": "出典: 調達ポータル",
    "redistribution_risk": "low",
    "update_frequency": "daily",
    "join_keys": ["procurement_item_no", "houjin_bangou"],
    "target_tables": ["bids"],
    "new_tables_needed": ["procurement_award (procurement_item_no, houjin_bangou, award_date)"],
    "artifact_outputs_enabled": ["houjin_dd_pack", "procurement_intel"],
    "sample_urls": ["https://www.p-portal.go.jp/"],
    "sample_fields": ["procurementItemNo", "corporationNo"],
    "known_gaps": [],
    "next_probe": "download latest ZIP",
    "checked_at": "2026-05-06T08:32:00+09:00",
}


# ---------------------------------------------------------------------------
# Test database setup — minimal isolated schemas mirroring production
# tables that the cron INSERTs / UPDATEs into.
# ---------------------------------------------------------------------------


def _create_autonomath_schema(conn: sqlite3.Connection) -> None:
    """Create the subset of am_* tables the cron writes to.

    Mirrors production migrations under scripts/migrations/wave24_*.sql
    (only the columns the cron actually touches).
    """
    conn.executescript("""
    CREATE TABLE jpi_programs (
        unified_id TEXT PRIMARY KEY,
        jsic_major TEXT,
        jsic_middle TEXT,
        jsic_minor TEXT,
        jsic_assigned_at TEXT,
        jsic_assigned_method TEXT
    );

    CREATE TABLE am_program_narrative (
        narrative_id INTEGER PRIMARY KEY AUTOINCREMENT,
        program_id INTEGER NOT NULL,
        lang TEXT NOT NULL,
        section TEXT NOT NULL,
        body_text TEXT NOT NULL,
        source_url_json TEXT,
        model_id TEXT,
        generated_at TEXT NOT NULL,
        literal_quote_check_passed INTEGER NOT NULL DEFAULT 0,
        content_hash TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        UNIQUE (program_id, lang, section)
    );

    CREATE TABLE am_houjin_360_narrative (
        houjin_bangou TEXT NOT NULL,
        lang TEXT NOT NULL,
        body_text TEXT NOT NULL,
        source_url_json TEXT,
        generated_at TEXT NOT NULL,
        UNIQUE (houjin_bangou, lang)
    );

    CREATE TABLE am_enforcement_summary (
        enforcement_id INTEGER NOT NULL,
        lang TEXT NOT NULL,
        body_text TEXT NOT NULL,
        source_url_json TEXT,
        generated_at TEXT NOT NULL,
        UNIQUE (enforcement_id, lang)
    );

    CREATE TABLE am_program_documents (
        doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
        program_unified_id TEXT NOT NULL,
        doc_name TEXT NOT NULL,
        doc_kind TEXT,
        yoshiki_no TEXT,
        is_required INTEGER NOT NULL DEFAULT 1,
        url TEXT,
        source_clause_quote TEXT,
        notes TEXT,
        computed_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX uq_apd_document
        ON am_program_documents(program_unified_id, doc_name, COALESCE(yoshiki_no, ''));

    CREATE TABLE am_program_eligibility_predicate (
        pred_id INTEGER PRIMARY KEY AUTOINCREMENT,
        program_unified_id TEXT NOT NULL,
        predicate_kind TEXT NOT NULL,
        operator TEXT NOT NULL,
        value_text TEXT,
        value_num REAL,
        value_json TEXT,
        is_required INTEGER NOT NULL DEFAULT 1,
        source_url TEXT,
        source_clause_quote TEXT,
        extracted_at TEXT NOT NULL
    );

    CREATE TABLE am_invoice_buyer_seller_graph (
        seller_houjin_bangou TEXT NOT NULL,
        buyer_houjin_bangou TEXT NOT NULL,
        confidence REAL NOT NULL,
        confidence_band TEXT NOT NULL,
        inferred_industry TEXT,
        evidence_kind TEXT NOT NULL,
        evidence_count INTEGER NOT NULL,
        source_url_json TEXT,
        first_seen_at TEXT,
        last_seen_at TEXT,
        computed_at TEXT NOT NULL,
        PRIMARY KEY (seller_houjin_bangou, buyer_houjin_bangou)
    );

    CREATE TABLE am_enforcement_detail (
        enforcement_id INTEGER PRIMARY KEY,
        amount_yen INTEGER,
        enforcement_kind TEXT,
        source_url TEXT,
        source_fetched_at TEXT
    );

    CREATE TABLE am_amount_condition (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_id TEXT NOT NULL,
        condition_label TEXT NOT NULL,
        source_field TEXT NOT NULL DEFAULT 'raw.subsidy_rate_sme',
        condition_kind TEXT,
        numeric_value REAL,
        numeric_value_max REAL,
        unit TEXT,
        currency TEXT,
        qualifier TEXT,
        confidence TEXT,
        extracted_text TEXT,
        is_authoritative INTEGER NOT NULL DEFAULT 0,
        authority_source TEXT,
        authority_evaluated_at TEXT,
        UNIQUE (entity_id, condition_label, source_field)
    );
    """)
    # seed program-0100 + houjin / amount_condition rows that updates land on
    conn.execute("INSERT INTO jpi_programs(unified_id) VALUES (?)", ("program-0100",))
    conn.execute(
        "INSERT INTO am_amount_condition(entity_id, condition_label, source_field) VALUES (?,?,?)",
        ("program-0100", "sme", "raw.subsidy_rate_sme"),
    )
    conn.commit()


def _create_jpintel_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE exclusion_rules (
        rule_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        severity TEXT,
        program_a TEXT,
        program_b TEXT,
        program_b_group_json TEXT,
        description TEXT,
        source_notes TEXT,
        source_urls_json TEXT,
        extra_json TEXT,
        source_excerpt TEXT,
        condition TEXT,
        program_a_uid TEXT,
        program_b_uid TEXT
    );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Cron module loader (path injected) + isolated inbox/quarantine fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cron_module(tmp_path, monkeypatch):
    """Load the cron with INBOX_ROOT + QUARANTINE_ROOT pointed at tmp_path.

    Re-imports cleanly per test so module-level constants get rebound.
    """
    inbox = tmp_path / "_inbox"
    quarantine = tmp_path / "_quarantine"
    inbox.mkdir()
    quarantine.mkdir()
    # Drop any cached module so monkeypatch on module-level constants sticks.
    sys.modules.pop("ingest_offline_inbox", None)
    spec = importlib.util.spec_from_file_location(
        "ingest_offline_inbox",
        SCRIPTS_ROOT / "cron" / "ingest_offline_inbox.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ingest_offline_inbox"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "INBOX_ROOT", inbox)
    monkeypatch.setattr(mod, "QUARANTINE_ROOT", quarantine)
    # also reset kobo cache probe (cleared on import but be explicit)
    mod._KOBO_CACHE_PROBE.clear()
    return mod


@pytest.fixture()
def dbs(tmp_path):
    """Pair of empty isolated SQLite files preloaded with cron-target schemas."""
    autonomath = tmp_path / "autonomath.db"
    jpintel = tmp_path / "jpintel.db"
    a = sqlite3.connect(autonomath)
    j = sqlite3.connect(jpintel)
    try:
        _create_autonomath_schema(a)
        _create_jpintel_schema(j)
    finally:
        a.close()
        j.close()
    return autonomath, jpintel


def _write_inbox(cron_module, tool: str, rows: list[dict[str, Any]]) -> Path:
    inbox_dir = cron_module.INBOX_ROOT / tool
    inbox_dir.mkdir(parents=True, exist_ok=True)
    fp = inbox_dir / f"{tool}.jsonl"
    with fp.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return fp


def _row_count(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Per-tool happy path — 1 row each ingested into the right table
# ---------------------------------------------------------------------------

TOOL_TABLE_DB: dict[str, tuple[str, str]] = {
    "exclusion_rules": ("exclusion_rules", "jpintel"),
    "jsic_tags": ("jpi_programs", "autonomath"),  # UPDATE, count stays 1
    "program_narrative": ("am_program_narrative", "autonomath"),
    "houjin_360_narrative": ("am_houjin_360_narrative", "autonomath"),
    "enforcement_summary": ("am_enforcement_summary", "autonomath"),
    "program_application_documents": ("am_program_documents", "autonomath"),
    "eligibility_predicates": ("am_program_eligibility_predicate", "autonomath"),
    "edinet_relations": ("am_invoice_buyer_seller_graph", "autonomath"),
    "amount_conditions": ("am_amount_condition", "autonomath"),
}


@pytest.mark.parametrize("tool", list(TOOL_TABLE_DB.keys()))
def test_happy_path_inserts_one_row(cron_module, dbs, tool, monkeypatch):
    autonomath_db, jpintel_db = dbs
    _write_inbox(cron_module, tool, [VALID_ROWS[tool]])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_offline_inbox.py",
            "--tool",
            tool,
            "--autonomath-db",
            str(autonomath_db),
            "--jpintel-db",
            str(jpintel_db),
        ],
    )
    rc = cron_module.main()
    assert rc == 0
    table, db_tag = TOOL_TABLE_DB[tool]
    db_path = autonomath_db if db_tag == "autonomath" else jpintel_db
    if tool == "jsic_tags":
        # UPDATE-style — verify jsic_major populated
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT jsic_major FROM jpi_programs WHERE unified_id=?",
                ("program-0100",),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == "E"
    elif tool == "amount_conditions":
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT is_authoritative, confidence FROM am_amount_condition "
                "WHERE entity_id=? AND condition_label=?",
                ("program-0100", "sme"),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == 1
        assert row[1] == "high"
    elif tool == "enforcement_amount":
        # there's no seeded enforcement_id 999999 → 0 row update is OK
        # (tested separately below for the seeded id case)
        pass
    else:
        assert _row_count(db_path, table) >= 1


def test_enforcement_amount_updates_seeded_row(cron_module, dbs, monkeypatch):
    autonomath_db, jpintel_db = dbs
    conn = sqlite3.connect(autonomath_db)
    try:
        conn.execute(
            "INSERT INTO am_enforcement_detail(enforcement_id) VALUES (?)",
            (12345,),
        )
        conn.commit()
    finally:
        conn.close()
    row = dict(VALID_ROWS["enforcement_amount"])
    row["enforcement_id"] = 12345
    _write_inbox(cron_module, "enforcement_amount", [row])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_offline_inbox.py",
            "--tool",
            "enforcement_amount",
            "--autonomath-db",
            str(autonomath_db),
            "--jpintel-db",
            str(jpintel_db),
        ],
    )
    rc = cron_module.main()
    assert rc == 0
    conn = sqlite3.connect(autonomath_db)
    try:
        amt = conn.execute(
            "SELECT amount_yen FROM am_enforcement_detail WHERE enforcement_id=?",
            (12345,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert amt == 1_000_000


# ---------------------------------------------------------------------------
# Quarantine path — bad row + good row in same file
# ---------------------------------------------------------------------------


def test_quarantine_bad_row(cron_module, dbs, monkeypatch):
    autonomath_db, jpintel_db = dbs
    bad = {"program_unified_id": "program-0100"}  # missing required fields
    good = VALID_ROWS["jsic_tags"]
    _write_inbox(cron_module, "jsic_tags", [bad, good])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_offline_inbox.py",
            "--tool",
            "jsic_tags",
            "--autonomath-db",
            str(autonomath_db),
            "--jpintel-db",
            str(jpintel_db),
        ],
    )
    rc = cron_module.main()
    assert rc == 1  # non-zero because quarantine occurred
    quarantined = list((cron_module.QUARANTINE_ROOT / "jsic_tags").glob("*.jsonl"))
    assert len(quarantined) >= 1
    payload = json.loads(quarantined[0].read_text(encoding="utf-8"))
    assert "pydantic_validation_error" in payload["reason"]
    # good row still applied → jpi_programs.jsic_major populated
    conn = sqlite3.connect(autonomath_db)
    try:
        major = conn.execute(
            "SELECT jsic_major FROM jpi_programs WHERE unified_id=?",
            ("program-0100",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert major == "E"


def test_dry_run_does_not_write_or_move(cron_module, dbs, monkeypatch):
    autonomath_db, jpintel_db = dbs
    fp = _write_inbox(cron_module, "jsic_tags", [VALID_ROWS["jsic_tags"]])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_offline_inbox.py",
            "--tool",
            "jsic_tags",
            "--dry-run",
            "--autonomath-db",
            str(autonomath_db),
            "--jpintel-db",
            str(jpintel_db),
        ],
    )
    rc = cron_module.main()
    assert rc == 0
    # file stays in inbox (no _done/ move)
    assert fp.exists()
    # and DB unchanged (no jsic_major)
    conn = sqlite3.connect(autonomath_db)
    try:
        major = conn.execute(
            "SELECT jsic_major FROM jpi_programs WHERE unified_id=?",
            ("program-0100",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert major is None


def test_public_source_foundation_writes_backlogs_without_db(
    cron_module,
    dbs,
    monkeypatch,
):
    autonomath_db, jpintel_db = dbs
    fp = _write_inbox(
        cron_module,
        "public_source_foundation",
        [VALID_SOURCE_PROFILE],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_offline_inbox.py",
            "--tool",
            "public_source_foundation",
            "--autonomath-db",
            str(autonomath_db),
            "--jpintel-db",
            str(jpintel_db),
        ],
    )
    rc = cron_module.main()
    assert rc == 0
    assert not fp.exists()
    assert (fp.parent / "_done" / fp.name).exists()

    backlog_dir = cron_module.INBOX_ROOT / "public_source_foundation" / "_backlog"
    source_doc = json.loads(
        (backlog_dir / "source_document_backlog.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    schema = json.loads(
        (backlog_dir / "schema_backlog.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert source_doc["source_id"] == "p_portal_chotatsu"
    assert source_doc["status"] == "ready"
    assert schema["requested_table"] == "procurement_award"


def test_public_source_foundation_dry_run_does_not_write_or_move(
    cron_module,
    dbs,
    monkeypatch,
):
    autonomath_db, jpintel_db = dbs
    fp = _write_inbox(
        cron_module,
        "public_source_foundation",
        [VALID_SOURCE_PROFILE],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_offline_inbox.py",
            "--tool",
            "public_source_foundation",
            "--dry-run",
            "--autonomath-db",
            str(autonomath_db),
            "--jpintel-db",
            str(jpintel_db),
        ],
    )
    rc = cron_module.main()
    assert rc == 0
    assert fp.exists()
    assert not (fp.parent / "_backlog").exists()


def test_public_source_foundation_dry_run_invalid_is_read_only(
    cron_module,
    dbs,
    monkeypatch,
):
    autonomath_db, jpintel_db = dbs
    fp = _write_inbox(
        cron_module,
        "public_source_foundation",
        [{"source": "missing-required-fields"}],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_offline_inbox.py",
            "--tool",
            "public_source_foundation",
            "--dry-run",
            "--autonomath-db",
            str(autonomath_db),
            "--jpintel-db",
            str(jpintel_db),
        ],
    )

    rc = cron_module.main()

    assert rc == 1
    assert fp.exists()
    assert not (fp.parent / "_backlog").exists()
    qdir = cron_module.QUARANTINE_ROOT / "public_source_foundation"
    assert not qdir.exists()


# ---------------------------------------------------------------------------
# kobo_text_cache literal-quote substring check (when cache table present)
# ---------------------------------------------------------------------------


def test_literal_quote_substring_check_with_cache(cron_module, dbs, monkeypatch):
    """When kobo_text_cache exists and cached text does NOT contain the
    quote, the row is silently skipped (literal-quote fail).
    """
    autonomath_db, jpintel_db = dbs
    # add the cache table to jpintel.db (exclusion_rules db)
    conn = sqlite3.connect(jpintel_db)
    try:
        conn.execute(
            "CREATE TABLE kobo_text_cache(source_url TEXT PRIMARY KEY, text_body TEXT NOT NULL)"
        )
        # cached text does NOT contain "他の補助事業との重複受給"
        conn.execute(
            "INSERT INTO kobo_text_cache(source_url, text_body) VALUES (?,?)",
            ("https://example.go.jp/koubo.pdf", "全く別の文言しかない公募要領のテキスト本文"),
        )
        conn.commit()
    finally:
        conn.close()
    _write_inbox(cron_module, "exclusion_rules", [VALID_ROWS["exclusion_rules"]])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_offline_inbox.py",
            "--tool",
            "exclusion_rules",
            "--autonomath-db",
            str(autonomath_db),
            "--jpintel-db",
            str(jpintel_db),
        ],
    )
    rc = cron_module.main()
    assert rc == 0  # no quarantine — literal-quote fail is a silent skip
    assert _row_count(jpintel_db, "exclusion_rules") == 0


# ---------------------------------------------------------------------------
# LLM-SDK guard — assert script + schema package import 0 LLM SDKs
# ---------------------------------------------------------------------------


def test_no_llm_sdk_imports_in_cron_or_schemas():
    forbidden = {"anthropic", "openai", "claude_agent_sdk"}
    targets = [
        SCRIPTS_ROOT / "cron" / "ingest_offline_inbox.py",
        SRC_ROOT / "jpintel_mcp" / "ingest" / "schemas" / "__init__.py",
        *sorted((SRC_ROOT / "jpintel_mcp" / "ingest" / "schemas").glob("*.py")),
    ]
    hits: list[str] = []
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    head = alias.name.split(".")[0]
                    if head in forbidden or alias.name.startswith("google.generativeai"):
                        hits.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                head = mod.split(".")[0]
                if head in forbidden or mod.startswith("google.generativeai"):
                    hits.append(f"{path}: from {mod} import ...")
    assert hits == []


# ---------------------------------------------------------------------------
# Schema alias resolution — the 8 canonical *Row aliases must map back to
# their underlying class via the `SCHEMAS` registry.
# ---------------------------------------------------------------------------


def test_canonical_row_aliases_resolve():
    from jpintel_mcp.ingest.schemas import (
        SCHEMAS,
        AppDocsRow,
        EdinetRelationRow,
        EligibilityPredicateRow,
        EnforcementSummaryRow,
        ExclusionRulesRow,
        Houjin360NarrativeRow,
        JsicTagsRow,
        NarrativeRow,
        SourceProfileRow,
    )

    pairs = [
        ("jsic_tags", JsicTagsRow),
        ("program_narrative", NarrativeRow),
        ("houjin_360_narrative", Houjin360NarrativeRow),
        ("enforcement_summary", EnforcementSummaryRow),
        ("program_application_documents", AppDocsRow),
        ("eligibility_predicates", EligibilityPredicateRow),
        ("edinet_relations", EdinetRelationRow),
        ("exclusion_rules", ExclusionRulesRow),
        ("public_source_foundation", SourceProfileRow),
    ]
    for tool, alias_cls in pairs:
        assert SCHEMAS[tool] is alias_cls, f"{tool} alias mismatch"
