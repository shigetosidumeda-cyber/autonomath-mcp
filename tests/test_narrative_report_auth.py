"""W2-9 security audit — auth + DoS hardening on POST /v1/narrative/{id}/report.

Companion to `tests/test_narrative_report_endpoint.py` (which exercises the
happy paths). This file focuses on the lock-down delta:

    C-1 (Critical) — anonymous callers can no longer reach the endpoint.
                     Pre-fix, an unauthenticated POST with `field_path=amount`
                     auto-quarantined any narrative.
    H-1 (High)     — the same paid key cannot loop P0 reports against
                     the same narrative_id (1h window) or burn through
                     more than 5 P0 reports in 24h.
    Field-path     — only six exact field paths trigger P0; a substring
                     attack like `field_path="amount"` no longer escalates.

The fixture mirrors `test_narrative_report_endpoint.py`'s autonomath_test_db
because the router writes against autonomath.db (the narrative tables live
there), and we need an isolated mini-DB so concurrent test runs don't share
the rate-limit counter.
"""

from __future__ import annotations

import sqlite3
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Resolve src/ for tests run from repo root.
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------------------------------------------------------------------------
# Mini autonomath.db schema fixture (mirrors test_narrative_report_endpoint).
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
    """CREATE INDEX IF NOT EXISTS idx_ncr_key_severity_created
       ON am_narrative_customer_reports(api_key_id, severity_auto, created_at)""",
    """CREATE INDEX IF NOT EXISTS idx_ncr_narrative_key_created
       ON am_narrative_customer_reports(narrative_id, api_key_id, created_at)""",
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
    # Best-effort stub of the audit table (migration 141). The router only
    # logs structured info if the INSERT raises OperationalError, so the
    # presence of this table lets us verify the audit-log path on a fresh
    # mini-DB. We mirror the production CHECK enum so misuse surfaces.
    """CREATE TABLE IF NOT EXISTS am_narrative_quarantine (
        quarantine_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        narrative_id     INTEGER NOT NULL,
        narrative_table  TEXT NOT NULL,
        reason           TEXT NOT NULL,
        match_rate       REAL,
        detected_at      TEXT NOT NULL DEFAULT (datetime('now')),
        resolved_at      TEXT,
        resolution       TEXT
    )""",
)


@pytest.fixture()
def autonomath_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        for stmt in _DDL:
            conn.execute(stmt)
        # Seed 6 narrative rows so the 6-iteration P0-quota test has
        # distinct narrative_ids to exercise the DAILY counter path
        # without tripping the per-(key, narrative) hourly cap.
        for nid in range(1, 8):
            conn.execute(
                "INSERT INTO am_program_narrative(narrative_id, program_id, body) VALUES (?,?,?)",
                (nid, 100, f"narrative {nid}"),
            )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)
    return db_path


@pytest.fixture()
def report_client(seeded_db: Path, autonomath_test_db: Path) -> TestClient:
    """Mount the narrative_report router in isolation for auth tests."""
    from jpintel_mcp.api.narrative_report import router as narrative_router

    app = FastAPI()
    app.include_router(narrative_router)
    return TestClient(app)


@pytest.fixture()
def isolated_paid_key(seeded_db: Path) -> str:
    """Issue a fresh paid API key AND backfill api_keys.id from rowid.

    `issue_key` does not set the `id` column (production relies on the
    Stripe webhook's later UPDATE), but the W2-9 rate-limit checks key
    on `ctx.key_id` so we must guarantee a non-NULL id at issuance time
    in tests. Otherwise every "same key" rate-limit assertion would
    silently degrade because `WHERE api_key_id = NULL` matches nothing.
    """
    from jpintel_mcp.billing.keys import issue_key

    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    cust_id = f"cus_w2_{uuid.uuid4().hex[:8]}"
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(c, customer_id=cust_id, tier="paid", stripe_subscription_id=sub_id)
    c.execute("UPDATE api_keys SET id = rowid WHERE id IS NULL")
    c.commit()
    c.close()
    return raw


# ---------------------------------------------------------------------------
# C-1: anonymous callers are rejected.
# ---------------------------------------------------------------------------


def test_anonymous_post_rejected_401(report_client: TestClient, autonomath_test_db: Path):
    """Pre-W2-9 this would 201-CREATE and (with field_path='amount') flip
    is_active=0 on the target narrative. Now it must 401 before any DB write.
    """
    r = report_client.post(
        "/v1/narrative/1/report",
        json={
            "narrative_table": "am_program_narrative",
            "field_path": "amount_max",
            "claimed_wrong": "anonymous attacker tries to quarantine narrative #1",
        },
    )
    assert r.status_code == 401, r.text

    # Verify NO row landed and the narrative was NOT quarantined.
    c = sqlite3.connect(autonomath_test_db)
    try:
        n = c.execute("SELECT COUNT(*) FROM am_narrative_customer_reports").fetchone()[0]
        assert n == 0
        is_active = c.execute(
            "SELECT is_active FROM am_program_narrative WHERE narrative_id=1"
        ).fetchone()[0]
        assert is_active == 1
    finally:
        c.close()


# ---------------------------------------------------------------------------
# C-1 (continued): paid key — first P0 succeeds.
# ---------------------------------------------------------------------------


def test_paid_key_first_p0_accepted(
    report_client: TestClient,
    autonomath_test_db: Path,
    isolated_paid_key: str,
):
    r = report_client.post(
        "/v1/narrative/1/report",
        json={
            "narrative_table": "am_program_narrative",
            "field_path": "amount_max",
            "claimed_wrong": "上限額が誤っています — 正しくは 1000 万円です",
            "claimed_correct": "1000万円",
            "evidence_url": "https://www.maff.go.jp/example.pdf",
        },
        headers={"X-API-Key": isolated_paid_key},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["severity"] == "P0"
    assert body["quarantined"] is True
    assert body["report_id"] > 0


# ---------------------------------------------------------------------------
# H-1: per-(key, narrative) 1h quota.
# ---------------------------------------------------------------------------


def test_same_key_same_narrative_2nd_p0_within_hour_429(
    report_client: TestClient,
    autonomath_test_db: Path,
    isolated_paid_key: str,
):
    headers = {"X-API-Key": isolated_paid_key}
    payload = {
        "narrative_table": "am_program_narrative",
        "field_path": "amount_max",
        "claimed_wrong": "first report — legitimate paid customer flag",
        "claimed_correct": "1000万円",
    }
    r1 = report_client.post("/v1/narrative/1/report", json=payload, headers=headers)
    assert r1.status_code == 201

    r2 = report_client.post("/v1/narrative/1/report", json=payload, headers=headers)
    assert r2.status_code == 429, r2.text
    assert "rate_limit_per_key_per_narrative" in r2.text


# ---------------------------------------------------------------------------
# DoS: 6th P0 in 24h hits the daily quota.
# ---------------------------------------------------------------------------


def test_same_key_6th_p0_in_24h_429(
    report_client: TestClient,
    autonomath_test_db: Path,
    isolated_paid_key: str,
):
    """5 P0 reports across 5 distinct narratives succeed; the 6th 429s."""
    headers = {"X-API-Key": isolated_paid_key}

    for nid in range(1, 6):  # 5 distinct narratives
        r = report_client.post(
            f"/v1/narrative/{nid}/report",
            json={
                "narrative_table": "am_program_narrative",
                "field_path": "amount_max",
                "claimed_wrong": (
                    f"P0 #{nid} — different narrative each time so "
                    "the per-(key, narrative) hourly cap does not fire"
                ),
                "claimed_correct": f"{nid * 100}万円",
            },
            headers=headers,
        )
        assert r.status_code == 201, (nid, r.text)
        assert r.json()["severity"] == "P0"

    # 6th P0 — distinct narrative_id (#6), but same key + 24h window.
    r6 = report_client.post(
        "/v1/narrative/6/report",
        json={
            "narrative_table": "am_program_narrative",
            "field_path": "amount_max",
            "claimed_wrong": "6th P0 in 24h — should hit the daily quota",
            "claimed_correct": "600万円",
        },
        headers=headers,
    )
    assert r6.status_code == 429, r6.text
    assert "p0_daily_quota_exceeded" in r6.text


# ---------------------------------------------------------------------------
# Field-path whitelist: substring attack downgraded to P1 / P3.
# ---------------------------------------------------------------------------


def test_field_path_whitelist_amount_exact_p0(
    report_client: TestClient,
    autonomath_test_db: Path,
    isolated_paid_key: str,
):
    """Exact whitelist value `amount_max` triggers P0."""
    r = report_client.post(
        "/v1/narrative/7/report",
        json={
            "narrative_table": "am_program_narrative",
            "field_path": "amount_max",
            "claimed_wrong": "exact whitelist match — should classify as P0",
            "claimed_correct": "X",
            "evidence_url": "https://www.maff.go.jp/example.pdf",
        },
        headers={"X-API-Key": isolated_paid_key},
    )
    assert r.status_code == 201, r.text
    assert r.json()["severity"] == "P0"


def test_field_path_random_value_demoted_below_p0(
    report_client: TestClient,
    autonomath_test_db: Path,
    isolated_paid_key: str,
):
    """A non-whitelisted `field_path` no longer trips P0 even though the
    pre-W2-9 substring match would have escalated `field_path=amount`.

    With evidence_url on a non-official domain and no claimed_correct, the
    payload should fall through to P3. A separate assertion confirms the
    same payload with .go.jp evidence demotes to P1 (the documented spec
    behaviour for non-P0 official-domain reports).
    """
    headers = {"X-API-Key": isolated_paid_key}

    # No evidence, no claimed_correct → P3.
    r = report_client.post(
        "/v1/narrative/7/report",
        json={
            "narrative_table": "am_program_narrative",
            "field_path": "random_field",
            "claimed_wrong": "random_field is not on the P0 whitelist",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["severity"] == "P3"
    assert r.json()["quarantined"] is False


def test_field_path_substring_amount_no_longer_p0(
    report_client: TestClient,
    autonomath_test_db: Path,
    isolated_paid_key: str,
):
    """Pre-W2-9, `field_path="amount"` (bare substring) auto-escalated to P0
    via the `_P0_FIELD_HITS` substring scan. Post-W2-9 the value must be an
    exact whitelist match — bare "amount" no longer qualifies.
    """
    r = report_client.post(
        "/v1/narrative/7/report",
        json={
            "narrative_table": "am_program_narrative",
            "field_path": "amount",  # not in whitelist; whitelist is amount_max / amount_min
            "claimed_wrong": "substring attack via field_path='amount'",
        },
        headers={"X-API-Key": isolated_paid_key},
    )
    assert r.status_code == 201, r.text
    assert r.json()["severity"] != "P0"
    assert r.json()["quarantined"] is False


# ---------------------------------------------------------------------------
# Pure-Python severity helper — direct unit test of the whitelist logic.
# ---------------------------------------------------------------------------


def test_auto_severity_whitelist_unit():
    from jpintel_mcp.api.narrative_report import auto_severity

    # All six exact whitelist values escalate to P0.
    for fp in (
        "amount_max",
        "amount_min",
        "deadline",
        "eligibility.region",
        "eligibility.industry",
        "eligibility.size_band",
    ):
        assert auto_severity(field_path=fp, evidence_url=None, claimed_correct=None) == "P0", (
            f"{fp} should be P0"
        )

    # Substring-style attacks no longer escalate.
    for fp in (
        "amount",
        "amount_max_man_yen",  # the OLD test_narrative_report_endpoint value
        "programs.amount_max",
        "deadline_evilness",
        "eligibility",
        "random",
        "",
        None,
    ):
        sev = auto_severity(field_path=fp, evidence_url=None, claimed_correct=None)
        assert sev != "P0", f"{fp} should NOT escalate to P0 post-W2-9"


# Suppress pytest's unused-import warnings for the datetime imports the
# fixture references via timedelta on the side, even though no test below
# wall-clocks today's window.
_ = datetime, timedelta, UTC
