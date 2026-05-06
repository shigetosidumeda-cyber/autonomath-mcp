"""Tests for §10.10 (3) — POST /v1/narrative/{narrative_id}/report.

Verifies:
    * 201 happy path with severity auto-classified to P3.
    * P0 auto-quarantines the narrative row (is_active=0).
    * P1 fires when evidence_url is on .go.jp / .lg.jp.
    * P2 fires when claimed_correct is supplied.
    * SLA due timestamps honor 24h (P0/P1) vs 72h (P2/P3).
    * narrative_table whitelist rejects unknown tables (422).
    * claimed_wrong length validation rejects < 4 / > 4000.

Per the §10.10 spec the router file is owned by this agent (W1-narrative-guard);
the main.py mount is owned by W1-18. To stay decoupled we mount the router on
an isolated FastAPI app inside the test module.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure jpintel_mcp imports resolve when pytest runs from repo root.
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Test env fixtures inherited from conftest.py initialize JPINTEL_DB_PATH +
# API_KEY_SALT before any jpintel_mcp import.


# ---------------------------------------------------------------------------
# Fixture: minimal autonomath.db with §10.10 schema only (the migrations
# 140-142 land via a sibling agent; we materialize the same DDL inline here
# so this test does not depend on that other agent's migration files.)
# ---------------------------------------------------------------------------


_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS am_narrative_customer_reports (
        report_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        narrative_id    INTEGER NOT NULL,
        narrative_table TEXT NOT NULL,
        api_key_id      INTEGER,
        severity_auto   TEXT NOT NULL,
        field_path      TEXT,
        claimed_wrong   TEXT NOT NULL,
        claimed_correct TEXT,
        evidence_url    TEXT,
        state           TEXT NOT NULL DEFAULT 'inbox',
        operator_note   TEXT,
        created_at      TEXT NOT NULL,
        sla_due_at      TEXT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_ncr_state_due
       ON am_narrative_customer_reports(state, sla_due_at)""",
    # Mirror of the parent narrative table (one row, used to verify is_active=0).
    """CREATE TABLE IF NOT EXISTS am_program_narrative (
        narrative_id INTEGER PRIMARY KEY AUTOINCREMENT,
        program_id   INTEGER NOT NULL,
        lang         TEXT NOT NULL DEFAULT 'ja',
        section      TEXT NOT NULL DEFAULT 'overview',
        body         TEXT NOT NULL,
        is_active    INTEGER NOT NULL DEFAULT 1,
        quarantine_id INTEGER,
        content_hash TEXT
    )""",
)


@pytest.fixture()
def autonomath_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        for stmt in _DDL:
            conn.execute(stmt)
        conn.execute(
            "INSERT INTO am_program_narrative(narrative_id, program_id, body) VALUES (?,?,?)",
            (1, 100, "テスト本文 1,000万円 令和5年 https://example.go.jp"),
        )
        conn.execute(
            "INSERT INTO am_program_narrative(narrative_id, program_id, body) VALUES (?,?,?)",
            (2, 100, "二件目 narrative"),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)
    return db_path


# ---------------------------------------------------------------------------
# Mount narrative_report router in isolation so the test stays decoupled from
# main.py wiring (which is owned by W1-18 per the §10.10 plan).
# ---------------------------------------------------------------------------


@pytest.fixture()
def report_client(seeded_db: Path, autonomath_test_db: Path) -> TestClient:
    # Late import — the autonomath path env var must be set before the
    # router module is imported so settings picks it up.
    from jpintel_mcp.api.narrative_report import router as narrative_router

    app = FastAPI()
    app.include_router(narrative_router)
    return TestClient(app)


@pytest.fixture()
def paid_headers(seeded_db: Path) -> dict[str, str]:
    """Issue a paid API key + return the X-API-Key header dict.

    W2-9 lock-down: the narrative-report endpoint now rejects anonymous
    callers (401). Every test in this module must authenticate as a
    paid metered key to exercise the happy-path / P0-quarantine logic.

    `id = rowid` backfill is required because the W2-9 in-handler
    rate-limit logic keys on `ctx.key_id`; `issue_key` does not set it.
    """
    import uuid

    from jpintel_mcp.billing.keys import issue_key

    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    cust_id = f"cus_w2_{uuid.uuid4().hex[:8]}"
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(c, customer_id=cust_id, tier="paid", stripe_subscription_id=sub_id)
    c.execute("UPDATE api_keys SET id = rowid WHERE id IS NULL")
    c.commit()
    c.close()
    return {"X-API-Key": raw}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_post_report_p3_happy_path(
    report_client: TestClient, autonomath_test_db: Path, paid_headers: dict[str, str]
):
    r = report_client.post(
        "/v1/narrative/1/report",
        json={
            "narrative_table": "am_program_narrative",
            "claimed_wrong": "本文の表現が不明瞭です。修正案はありません。",
        },
        headers=paid_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["received"] is True
    assert body["severity"] == "P3"
    assert body["quarantined"] is False
    assert body["report_id"] > 0

    # SLA = 72h for P3.
    sla = datetime.fromisoformat(body["sla_due_at"])
    delta_hours = (sla - datetime.now(UTC)).total_seconds() / 3600
    assert 71 <= delta_hours <= 73

    # Row landed.
    c = sqlite3.connect(autonomath_test_db)
    c.row_factory = sqlite3.Row
    try:
        row = c.execute(
            "SELECT severity_auto, state, narrative_id, narrative_table "
            "FROM am_narrative_customer_reports WHERE report_id=?",
            (body["report_id"],),
        ).fetchone()
        assert row["severity_auto"] == "P3"
        assert row["state"] == "inbox"
        assert row["narrative_id"] == 1
        # Narrative was NOT auto-quarantined (P3).
        is_active = c.execute(
            "SELECT is_active FROM am_program_narrative WHERE narrative_id=1"
        ).fetchone()[0]
        assert is_active == 1
    finally:
        c.close()


def test_post_report_p0_quarantines_narrative(
    report_client: TestClient,
    autonomath_test_db: Path,
    paid_headers: dict[str, str],
):
    """field_path on the W2-9 P0 whitelist (`amount_max` etc.) → P0,
    AND the parent narrative row's is_active flips to 0."""
    r = report_client.post(
        "/v1/narrative/1/report",
        json={
            "narrative_table": "am_program_narrative",
            # W2-9: must be an EXACT whitelist value to escalate to P0.
            # The legacy "programs.amount_max_man_yen" substring trick no
            # longer works (covered by tests/test_narrative_report_auth.py).
            "field_path": "amount_max",
            "claimed_wrong": "上限額が誤っています (本文では1000万円と書かれていますが正しくは100万円)。",
            "claimed_correct": "100万円",
            "evidence_url": "https://www.maff.go.jp/example.pdf",
        },
        headers=paid_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["severity"] == "P0"
    assert body["quarantined"] is True

    # SLA = 24h for P0.
    sla = datetime.fromisoformat(body["sla_due_at"])
    delta_hours = (sla - datetime.now(UTC)).total_seconds() / 3600
    assert 23 <= delta_hours <= 25

    c = sqlite3.connect(autonomath_test_db)
    try:
        is_active = c.execute(
            "SELECT is_active FROM am_program_narrative WHERE narrative_id=1"
        ).fetchone()[0]
        assert is_active == 0
    finally:
        c.close()


def test_post_report_p1_official_evidence(
    report_client: TestClient,
    autonomath_test_db: Path,
    paid_headers: dict[str, str],
):
    """No P0 field hit, but evidence_url ends in .go.jp → P1, 24h SLA."""
    r = report_client.post(
        "/v1/narrative/2/report",
        json={
            "narrative_table": "am_program_narrative",
            "field_path": "programs.summary",
            "claimed_wrong": "事業者要件の記述が不正確と思われます。",
            "evidence_url": "https://www.meti.go.jp/policy/example.html",
        },
        headers=paid_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["severity"] == "P1"
    assert body["quarantined"] is False

    sla = datetime.fromisoformat(body["sla_due_at"])
    delta_hours = (sla - datetime.now(UTC)).total_seconds() / 3600
    assert 23 <= delta_hours <= 25


def test_post_report_p2_claimed_correct(
    report_client: TestClient,
    autonomath_test_db: Path,
    paid_headers: dict[str, str],
):
    """No P0 field hit, no .go.jp/.lg.jp evidence, but claimed_correct → P2."""
    r = report_client.post(
        "/v1/narrative/2/report",
        json={
            "narrative_table": "am_program_narrative",
            "field_path": "programs.target_industry",
            "claimed_wrong": "業種カテゴリの説明が古い情報です。",
            "claimed_correct": "2026年度以降は建設業(JSIC D)も対象です。",
            "evidence_url": "https://example.com/article",
        },
        headers=paid_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["severity"] == "P2"

    sla = datetime.fromisoformat(body["sla_due_at"])
    delta_hours = (sla - datetime.now(UTC)).total_seconds() / 3600
    assert 71 <= delta_hours <= 73


def test_post_report_unknown_table_rejected(
    report_client: TestClient, paid_headers: dict[str, str]
):
    r = report_client.post(
        "/v1/narrative/1/report",
        json={
            "narrative_table": "am_made_up_table",
            "claimed_wrong": "本文に誤りがあると思います。",
        },
        headers=paid_headers,
    )
    # Pydantic regex rejects table names not matching am_..._narrative/_summary.
    assert r.status_code == 422, r.text


def test_post_report_off_whitelist_table_rejected(
    report_client: TestClient, paid_headers: dict[str, str]
):
    """A table name that matches the regex but is not in the whitelist → 422."""
    r = report_client.post(
        "/v1/narrative/1/report",
        json={
            "narrative_table": "am_some_other_narrative",
            "claimed_wrong": "本文に誤りがあると思います。",
        },
        headers=paid_headers,
    )
    assert r.status_code == 422, r.text


def test_post_report_too_short_claimed_wrong_rejected(
    report_client: TestClient, paid_headers: dict[str, str]
):
    r = report_client.post(
        "/v1/narrative/1/report",
        json={
            "narrative_table": "am_program_narrative",
            "claimed_wrong": "x",  # < 4 chars
        },
        headers=paid_headers,
    )
    assert r.status_code == 422


def test_post_report_too_long_claimed_wrong_rejected(
    report_client: TestClient, paid_headers: dict[str, str]
):
    r = report_client.post(
        "/v1/narrative/1/report",
        json={
            "narrative_table": "am_program_narrative",
            "claimed_wrong": "x" * 4001,
        },
        headers=paid_headers,
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Module-level guards: NO LLM SDK import in any §10.10 file.
# ---------------------------------------------------------------------------


def test_no_llm_imports_in_router_file():
    """Real AST scan (matches `tests/test_no_llm_in_production.py`).
    Docstring mentions of forbidden names are tolerated; only actual
    `import X` / `from X import ...` statements are flagged."""
    import ast

    src = (
        Path(__file__).resolve().parent.parent / "src/jpintel_mcp/api/narrative_report.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"anthropic", "openai", "claude_agent_sdk"}
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                if head in forbidden or alias.name.startswith("google.generativeai"):
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            head = mod.split(".")[0]
            if head in forbidden or mod.startswith("google.generativeai"):
                hits.append(f"from {mod} import ...")
    assert not hits, f"LLM SDK imports leaked into narrative_report.py: {hits}"


def test_severity_helper_returns_expected_class():
    from jpintel_mcp.api.narrative_report import auto_severity

    # W2-9: P0 requires an EXACT match against the six-value whitelist.
    # The legacy substring trick (`programs.amount_max_man_yen`) is a
    # regression and must NOT escalate to P0 — see
    # tests/test_narrative_report_auth.py for the substring-attack tests.
    assert (
        auto_severity(
            field_path="amount_max",
            evidence_url=None,
            claimed_correct=None,
        )
        == "P0"
    )
    assert (
        auto_severity(
            field_path="deadline",
            evidence_url=None,
            claimed_correct=None,
        )
        == "P0"
    )
    assert (
        auto_severity(
            field_path="programs.summary",
            evidence_url="https://example.lg.jp/x",
            claimed_correct=None,
        )
        == "P1"
    )
    assert (
        auto_severity(
            field_path="programs.summary",
            evidence_url=None,
            claimed_correct="正しくはX",
        )
        == "P2"
    )
    assert (
        auto_severity(
            field_path="programs.summary",
            evidence_url=None,
            claimed_correct=None,
        )
        == "P3"
    )
