"""Integration tests for Dim W AX Layer 3 (Wave 47).

Closes the AX 4-pillars Layer 3 storage gap: migration 283 adds
``am_webmcp_endpoint`` (registry of WebMCP transport endpoints),
``am_a2a_handshake_log`` (append-only handshake audit), and
``am_observability_metric`` (append-only metric stream) per
``feedback_ax_4_pillars.md``. Pairs with
``scripts/etl/seed_ax_layer3.py`` (3 WebMCP endpoints + 2 A2A handshake
templates + 8 observability metrics).

Case bundles
------------
  1. Migration 283 applies cleanly on a fresh SQLite db (idempotent re-apply).
  2. Migration 283 rollback drops every artefact created.
  3. CHECK constraints reject malformed rows (transport out of enum,
     capability_tag out of enum, path missing leading '/', handshake
     succeeded_at < initiated_at, handshake both succeeded_at + failed_at
     non-null, observability metric_name length out of range).
  4. UNIQUE (path, transport) prevents duplicate endpoint rows.
  5. ETL seeds 3 endpoints + 2 handshakes + 8 metrics on a fresh DB
     and is idempotent on re-run (--force re-appends audit rows).
  6. Helper views (v_webmcp_endpoint_active, v_observability_recent)
     surface the seeded rows.
  7. Boot manifest registration (jpcite + autonomath mirror).
  8. **LLM-0 verify** — `grep -E "anthropic|openai" seed_ax_layer3.py` = 0.
  9. **Brand verify** — no 税務会計AI / zeimu-kaikei.ai legacy strings.

Hard constraints exercised
--------------------------
  * No LLM SDK import in any new file (Layer 3 is config + audit only).
  * Schema is config + audit only; no summary / ai_explanation column.
  * Brand: only jpcite. No legacy ``税務会計AI`` / ``zeimu-kaikei.ai``.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_283 = REPO_ROOT / "scripts" / "migrations" / "283_ax_layer3.sql"
MIG_283_RB = REPO_ROOT / "scripts" / "migrations" / "283_ax_layer3_rollback.sql"
ETL = REPO_ROOT / "scripts" / "etl" / "seed_ax_layer3.py"
MANIFEST_JPCITE = REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
MANIFEST_AM = REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply(db_path: pathlib.Path, sql_path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql_path.read_text(encoding="utf-8"))
    finally:
        conn.close()


def _fresh_db(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "dim_w.db"
    _apply(db, MIG_283)
    return db


def _run_etl(db: pathlib.Path, *extra: str) -> dict:
    """Run the seed_ax_layer3.py ETL and return parsed JSON output."""
    cmd = [sys.executable, str(ETL), "--db", str(db), *extra]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    # The JSON report is the FINAL stdout line.
    last_line = proc.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


# ---------------------------------------------------------------------------
# Migration apply / rollback / idempotency
# ---------------------------------------------------------------------------


def test_mig_283_applies_clean(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view','index')"
            )
        }
    finally:
        conn.close()
    for required in (
        "am_webmcp_endpoint",
        "am_a2a_handshake_log",
        "am_observability_metric",
        "uq_am_webmcp_endpoint_path_transport",
        "idx_am_webmcp_endpoint_capability",
        "idx_am_a2a_handshake_target",
        "idx_am_a2a_handshake_capability",
        "idx_am_observability_metric_name_time",
        "v_observability_recent",
        "v_webmcp_endpoint_active",
    ):
        assert required in names, f"missing artefact: {required}"


def test_mig_283_is_idempotent(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    # Re-apply: must not raise.
    _apply(db, MIG_283)


def test_mig_283_rollback_clean(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _apply(db, MIG_283_RB)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view','index')"
            )
        }
    finally:
        conn.close()
    for dropped in (
        "am_webmcp_endpoint",
        "am_a2a_handshake_log",
        "am_observability_metric",
        "v_observability_recent",
        "v_webmcp_endpoint_active",
    ):
        assert dropped not in names, f"rollback failed to drop: {dropped}"


# ---------------------------------------------------------------------------
# CHECK constraint surface
# ---------------------------------------------------------------------------


def test_webmcp_transport_enum(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_webmcp_endpoint "
                "(path, transport, capability_tag) VALUES (?, ?, ?)",
                ("/v1/mcp/bad", "websocket", "tools"),  # 'websocket' not in enum
            )
    finally:
        conn.close()


def test_webmcp_capability_enum(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_webmcp_endpoint "
                "(path, transport, capability_tag) VALUES (?, ?, ?)",
                ("/v1/mcp/bad2", "sse", "billing"),  # 'billing' not in enum
            )
    finally:
        conn.close()


def test_webmcp_path_must_be_rooted(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_webmcp_endpoint "
                "(path, transport, capability_tag) VALUES (?, ?, ?)",
                ("v1/mcp/bad3", "sse", "tools"),  # no leading '/'
            )
    finally:
        conn.close()


def test_webmcp_path_transport_unique(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO am_webmcp_endpoint "
            "(path, transport, capability_tag) VALUES (?, ?, ?)",
            ("/v1/mcp/sse", "sse", "tools"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_webmcp_endpoint "
                "(path, transport, capability_tag) VALUES (?, ?, ?)",
                ("/v1/mcp/sse", "sse", "tools"),  # duplicate (path, transport)
            )
    finally:
        conn.close()


def test_a2a_handshake_exclusive_state(tmp_path: pathlib.Path) -> None:
    """succeeded_at and failed_at cannot both be set."""
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_a2a_handshake_log "
                "(source_agent, target_agent, capability_negotiated, "
                " succeeded_at, failed_at) VALUES "
                "(?, ?, ?, ?, ?)",
                (
                    "claude",
                    "jpcite",
                    "tools/list",
                    "2026-05-12T00:00:00Z",
                    "2026-05-12T00:00:01Z",
                ),
            )
    finally:
        conn.close()


def test_a2a_handshake_succeeded_after_initiated(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_a2a_handshake_log "
                "(source_agent, target_agent, capability_negotiated, "
                " initiated_at, succeeded_at) VALUES "
                "(?, ?, ?, ?, ?)",
                (
                    "claude",
                    "jpcite",
                    "tools/list",
                    "2026-05-12T10:00:00Z",
                    "2026-05-12T09:00:00Z",  # succeeded BEFORE initiated
                ),
            )
    finally:
        conn.close()


def test_observability_metric_name_length(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_observability_metric "
                "(metric_name, value) VALUES (?, ?)",
                ("", 1.0),  # empty metric_name
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_observability_metric "
                "(metric_name, value) VALUES (?, ?)",
                ("x" * 129, 1.0),  # too long
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# ETL seed verify
# ---------------------------------------------------------------------------


def test_etl_seed_dry_run(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    report = _run_etl(db, "--dry-run")
    assert report["dim"] == "W"
    assert report["wave"] == 47
    assert report["dry_run"] is True
    assert len(report["webmcp_endpoints"]) == 3
    assert len(report["a2a_handshakes"]) == 2
    assert len(report["observability_metrics"]) == 8
    # On a fresh DB, every dry-run plans an insert (no actual writes).
    for row in report["webmcp_endpoints"]:
        assert row["action"] == "inserted"
    for row in report["a2a_handshakes"]:
        assert row["action"] == "inserted"
    for row in report["observability_metrics"]:
        assert row["action"] == "inserted"


def test_etl_seed_apply_then_idempotent(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    # First apply: every row inserts.
    report1 = _run_etl(db)
    assert all(r["action"] == "inserted" for r in report1["webmcp_endpoints"])
    assert all(r["action"] == "inserted" for r in report1["a2a_handshakes"])
    assert all(r["action"] == "inserted" for r in report1["observability_metrics"])
    # Re-run is a no-op (UNIQUE for endpoints; date-of-day dedup for audits).
    report2 = _run_etl(db)
    assert all(r["action"] == "noop" for r in report2["webmcp_endpoints"])
    assert all(r["action"] == "noop" for r in report2["a2a_handshakes"])
    assert all(r["action"] == "noop" for r in report2["observability_metrics"])

    # Verify the row counts from the DB itself.
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM am_webmcp_endpoint"
        ).fetchone()[0] == 3
        assert conn.execute(
            "SELECT COUNT(*) FROM am_a2a_handshake_log"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM am_observability_metric"
        ).fetchone()[0] == 8
    finally:
        conn.close()


def test_etl_seed_force_appends_audit_rows(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _run_etl(db)
    # --force appends new audit rows even when same-day row exists.
    # WebMCP endpoint table stays at 3 (UNIQUE backstop) — only audit
    # tables (handshake / metric) grow.
    report = _run_etl(db, "--force")
    assert all(r["action"] == "noop" for r in report["webmcp_endpoints"])
    assert all(r["action"] == "inserted" for r in report["a2a_handshakes"])
    assert all(r["action"] == "inserted" for r in report["observability_metrics"])

    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM am_webmcp_endpoint"
        ).fetchone()[0] == 3
        assert conn.execute(
            "SELECT COUNT(*) FROM am_a2a_handshake_log"
        ).fetchone()[0] == 4  # 2 seed + 2 force-append
        assert conn.execute(
            "SELECT COUNT(*) FROM am_observability_metric"
        ).fetchone()[0] == 16  # 8 seed + 8 force-append
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helper view surface
# ---------------------------------------------------------------------------


def test_view_v_webmcp_endpoint_active(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _run_etl(db)
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT path, transport, capability_tag FROM v_webmcp_endpoint_active"
        ).fetchall()
    finally:
        conn.close()
    paths = {r[0] for r in rows}
    assert "/v1/mcp/sse" in paths
    assert "/v1/mcp/streamable_http" in paths
    transports = {r[1] for r in rows}
    assert transports == {"sse", "streamable_http"}


def test_view_v_observability_recent(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _run_etl(db)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT metric_name FROM v_observability_recent"
            )
        }
    finally:
        conn.close()
    # 4 AX pillar metrics + 4 Layer-3-specific signals.
    assert "ax.layer3.webmcp.endpoints_active" in names
    assert "ax.layer3.a2a.handshakes_total" in names
    assert "ax.pillar.access.surfaces_active" in names
    assert "ax.pillar.tools.surfaces_active" in names


# ---------------------------------------------------------------------------
# Boot manifest registration + hygiene
# ---------------------------------------------------------------------------


def test_boot_manifest_jpcite_lists_283() -> None:
    assert "283_ax_layer3.sql" in MANIFEST_JPCITE.read_text(encoding="utf-8")


def test_boot_manifest_autonomath_lists_283() -> None:
    assert "283_ax_layer3.sql" in MANIFEST_AM.read_text(encoding="utf-8")


def test_etl_has_no_llm_sdk_import() -> None:
    """LLM-0 invariant: no anthropic / openai / google.generativeai import."""
    text = ETL.read_text(encoding="utf-8")
    for forbidden in (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "google.generativeai",
        "claude_agent_sdk",
    ):
        assert forbidden not in text, f"LLM SDK leaked into ETL: {forbidden}"


def test_etl_has_no_legacy_brand() -> None:
    """Brand hygiene: only jpcite, no 税務会計AI / zeimu-kaikei.ai legacy."""
    text = ETL.read_text(encoding="utf-8")
    for forbidden in ("税務会計AI", "zeimu-kaikei.ai", "autonomath.ai"):
        assert forbidden not in text, f"legacy brand leaked: {forbidden}"


def test_migration_has_no_llm_column() -> None:
    """Schema hygiene: no summary_text / ai_explanation columns.

    Inspects only NON-COMMENT lines so the test does not trip on the
    docstring that REFERENCES the forbidden column names while explaining
    why they are disallowed.
    """
    lines = MIG_283.read_text(encoding="utf-8").splitlines()
    non_comment_text = "\n".join(
        ln for ln in lines if not ln.lstrip().startswith("--")
    )
    for forbidden in ("summary_text", "ai_explanation", "ai_summary"):
        assert forbidden not in non_comment_text, (
            f"LLM-coupled column leaked: {forbidden}"
        )
