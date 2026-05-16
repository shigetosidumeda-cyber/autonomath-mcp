"""Tests for Dim F fact_signature_v2 discovery surface (Wave 46).

Companion to Wave 43.2.5 Dim E ``fact_verify``: the verify endpoint runs
Ed25519 byte-tamper detection; ``fact_signature_v2`` is the cheap
metadata-only discovery surface (list latest signatures + per-id lookup)
that does NOT copy the 96-byte sig BLOB onto the wire.

Audit gap (dim 19, dim F = 2.50/10):
    - REST api file MISSING  <-- this PR closes this sub-criterion
    - ETL MISSING
    - cron MISSING (refresh_fact_signatures_weekly already exists upstream)
    - test(s): 1 (this file lands the second + dimension-F coverage)
    - MCP grep miss

This test focuses on:
  * File presence + correct FastAPI router prefix/tag
  * LLM SDK import count == 0 (production constraint)
  * Helper ``_shape_signature_row`` projection contract
    (no BLOB, integer sig_byte_length, all metadata fields surface)
  * Disclaimer envelope parity with sibling fact endpoints
    (§52 / §47条の2 / §72 non-substitution string present)
"""

from __future__ import annotations

import ast
import pathlib
import re
import sqlite3

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_FACT_SIGNATURE_V2 = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "fact_signature_v2.py"


# ---------------------------------------------------------------------------
# Module-load tests
# ---------------------------------------------------------------------------


def test_fact_signature_v2_file_exists() -> None:
    """The Wave 46 Dim F module file must exist on disk."""
    assert SRC_FACT_SIGNATURE_V2.exists(), (
        "src/jpintel_mcp/api/fact_signature_v2.py is required to close "
        "dim 19 / dim F REST sub-criterion."
    )
    src = SRC_FACT_SIGNATURE_V2.read_text(encoding="utf-8")
    assert 'router = APIRouter(prefix="/v1/facts"' in src
    assert 'tags=["fact-signature-discovery"]' in src


def test_fact_signature_v2_no_llm_imports() -> None:
    """fact_signature_v2.py must NOT import any LLM SDK."""
    src = SRC_FACT_SIGNATURE_V2.read_text(encoding="utf-8")
    banned = (
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
    )
    for needle in banned:
        pattern = rf"^\s*(import|from)\s+{re.escape(needle)}\b"
        assert not re.search(pattern, src, re.MULTILINE), f"LLM SDK import detected: {needle}"


def test_fact_signature_v2_disclaimer_present() -> None:
    """Discovery surface must carry the §52 / §47条の2 / §72 disclaimer.

    Without the non-substitution disclaimer, the envelope drifts from
    sibling fact endpoints (verify / why / agreement) and would fail the
    Wave 30 §52 hardening grep.
    """
    src = SRC_FACT_SIGNATURE_V2.read_text(encoding="utf-8")
    assert "税理士法" in src and "52" in src
    assert "公認会計士法" in src and "47条の2" in src
    assert "弁護士法" in src and "72" in src


def test_fact_signature_v2_no_blob_on_wire() -> None:
    """Response shaper must never copy the raw signature BLOB.

    The whole point of the discovery surface is that the 96-byte sig
    stays in the DB; only ``sig_byte_length`` (int) and the metadata
    columns surface.
    """
    src = SRC_FACT_SIGNATURE_V2.read_text(encoding="utf-8")
    # The shaper function returns a dict with ``sig_byte_length``,
    # NOT ``ed25519_sig``. Grep both directions to be conservative.
    assert "sig_byte_length" in src
    # Ensure no JSON return path includes the BLOB field name as a key.
    # The function reads row["ed25519_sig"] only to compute length.
    assert '"ed25519_sig":' not in src
    assert "'ed25519_sig':" not in src


# ---------------------------------------------------------------------------
# Helper contract via AST stub (avoid importing FastAPI runtime)
# ---------------------------------------------------------------------------


def _load_shape_helper() -> dict:
    """Compile only the ``_shape_signature_row`` helper in isolation."""
    src = SRC_FACT_SIGNATURE_V2.read_text(encoding="utf-8")
    tree = ast.parse(src)
    keep: list = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (
            node.module and node.module.startswith(("jpintel_mcp", "fastapi"))
        ):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
            isinstance(node, ast.FunctionDef) and node.name == "_shape_signature_row"
        ):
            keep.append(node)
    stub = ast.Module(body=keep, type_ignores=[])
    code = compile(stub, str(SRC_FACT_SIGNATURE_V2), "exec")
    ns: dict = {}
    exec(code, ns)  # noqa: S102 — controlled AST subset, no user input
    return ns


def test_shape_signature_row_projection() -> None:
    """``_shape_signature_row`` must surface metadata + sig_byte_length only."""
    ns = _load_shape_helper()
    shape = ns["_shape_signature_row"]

    # Fixture DB row mimicking ``v_am_fact_signature_latest``.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE r (
            fact_id TEXT,
            ed25519_sig BLOB,
            corpus_snapshot_id TEXT,
            key_id TEXT,
            signed_at TEXT,
            payload_sha256 TEXT
        )
        """
    )
    blob = bytes(80)  # 80-byte fake sig (within the 64..96 schema range)
    conn.execute(
        "INSERT INTO r VALUES (?, ?, ?, ?, ?, ?)",
        (
            "ef_unit_w46_dimf_001",
            blob,
            "snap_2026_05_12",
            "k20260512_a",
            "2026-05-12T01:00:00.000Z",
            "a" * 64,
        ),
    )
    row = conn.execute("SELECT * FROM r").fetchone()

    out = shape(row)
    assert out["fact_id"] == "ef_unit_w46_dimf_001"
    assert out["signed_at"] == "2026-05-12T01:00:00.000Z"
    assert out["key_id"] == "k20260512_a"
    assert out["corpus_snapshot_id"] == "snap_2026_05_12"
    assert out["payload_sha256"] == "a" * 64
    assert out["sig_byte_length"] == 80
    # CRITICAL: the raw BLOB must not appear in the projection.
    assert "ed25519_sig" not in out


def test_shape_signature_row_handles_null_sig() -> None:
    """Null sig column must collapse to sig_byte_length=0 without crashing."""
    ns = _load_shape_helper()
    shape = ns["_shape_signature_row"]

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE r (
            fact_id TEXT,
            ed25519_sig BLOB,
            corpus_snapshot_id TEXT,
            key_id TEXT,
            signed_at TEXT,
            payload_sha256 TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO r VALUES (?, ?, ?, ?, ?, ?)",
        (
            "ef_unit_null_sig",
            None,
            None,
            "k20260512_a",
            "2026-05-12T02:00:00.000Z",
            "b" * 64,
        ),
    )
    row = conn.execute("SELECT * FROM r").fetchone()
    out = shape(row)
    assert out["sig_byte_length"] == 0
    assert out["corpus_snapshot_id"] is None


# ---------------------------------------------------------------------------
# Wiring sanity: main.py imports the experimental router
# ---------------------------------------------------------------------------


def test_main_py_includes_fact_signature_v2() -> None:
    """``api/main.py`` must wire the experimental router."""
    main = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "main.py"
    src = main.read_text(encoding="utf-8")
    assert "jpintel_mcp.api.fact_signature_v2" in src, (
        "main.py must include fact_signature_v2 via _include_experimental_router"
    )
    assert "_include_experimental_router(app," in src


# ---------------------------------------------------------------------------
# Cron wiring (Wave 46 dim 19 dim F round 2: cron MISSING axis close)
# ---------------------------------------------------------------------------


def test_refresh_fact_signatures_workflow_exists() -> None:
    """The weekly cron workflow YAML must wire the upstream Python script.

    The cron Python (`scripts/cron/refresh_fact_signatures_weekly.py`)
    has lived upstream since Wave 43.2.5 but its workflow wiring was
    missing — flagged as the "cron MISSING" axis of the 2026-05-12
    dim 19 dim F audit. This test asserts the wiring landed.
    """
    workflow = REPO_ROOT / ".github" / "workflows" / "refresh-fact-signatures-weekly.yml"
    assert workflow.exists(), "Wave 46 dim 19 dim F round 2 must land the cron workflow"
    src = workflow.read_text(encoding="utf-8")
    # Schedule, script reference, and operator-LLM-ban context must all be present.
    assert "schedule:" in src
    assert "cron:" in src
    assert "scripts/cron/refresh_fact_signatures_weekly.py" in src
    # Sunday-02:00-UTC matches the cron Python docstring claim.
    assert '"0 2 * * 0"' in src
    # workflow_dispatch override for ops + concurrency guard.
    assert "workflow_dispatch:" in src
    assert "concurrency:" in src


def test_refresh_fact_signatures_workflow_no_llm_secret() -> None:
    """The cron workflow must NOT reference any LLM-vendor secret.

    Per memory `feedback_no_operator_llm_api`: scripts/cron/ is
    PRODUCTION_DIRS and may not import or be wired to call any LLM SDK
    or LLM API key. The Ed25519 sign key lives in Fly machine env
    (NOT as a GHA secret), so the workflow should only reference
    `FLY_API_TOKEN` from `secrets.*`.
    """
    workflow = REPO_ROOT / ".github" / "workflows" / "refresh-fact-signatures-weekly.yml"
    src = workflow.read_text(encoding="utf-8")
    banned_secret_substrings = (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    )
    for needle in banned_secret_substrings:
        assert needle not in src, f"refresh-fact-signatures-weekly.yml must not reference {needle}"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
