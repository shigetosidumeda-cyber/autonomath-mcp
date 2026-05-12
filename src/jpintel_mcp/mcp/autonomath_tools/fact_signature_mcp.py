"""fact_signature_mcp — MCP wrapper for the Dim E / Dim F Ed25519 fact verify surface.

Wave 46 dim 19 FPQO booster (2026-05-12)
========================================

Single tool registered at import time when both
``AUTONOMATH_FACT_SIGNATURE_MCP_ENABLED`` (default ON) and
``settings.autonomath_enabled`` are truthy:

  * ``fact_signature_verify_am``
      MCP wrapper over the REST surface at ``GET /v1/facts/{fact_id}/verify``
      + ``GET /v1/facts/{fact_id}/why`` (api/fact_verify.py, Wave 43.2.5).
      Returns the Ed25519 signature verification verdict plus the rule-based
      ``why`` explanation paragraph in a single MCP call so an agent can
      get both audit primitives without round-tripping twice.

Hard constraints (CLAUDE.md):

  * NO LLM call. Pure SQLite SELECT + cryptography stdlib Ed25519 verify
    + deterministic f-string explanation.
  * 1 ¥3/req billing unit per call (verify + why served from the same
    SQLite handle, so single unit not double — diverges from REST which
    bills them separately).
  * 弁護士法 §72 / 行政書士法 §1 / 税理士法 §52 / 公認会計士法 §47条の2
    non-substitution disclaimer envelope.
  * MCP tool registration is import-time side-effect; safe with FastMCP
    deferred tool list snapshot.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.fact_signature_mcp")

_ENABLED = os.environ.get("AUTONOMATH_FACT_SIGNATURE_MCP_ENABLED", "1") == "1"


def _open_autonomath_ro_safe() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db RO-by-intent; mirror api/fact_verify._open_autonomath_ro."""
    try:
        path = os.environ.get(
            "AUTONOMATH_DB_PATH", str(settings.autonomath_db_path)
        )
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["fact_signature_verify_am"],
        )


def _fact_signature_verify_impl(fact_id: str) -> dict[str, Any]:
    """Compose verify + why in one in-process call. Mirrors REST shape.

    Imported lazily so test fixtures can monkeypatch the REST helpers
    without touching this wrapper's import side-effects.
    """
    # Lazy import — keeps MCP tool registration cheap at import time and
    # delegates the canonical payload / Ed25519 / explanation logic to
    # api/fact_verify so the two surfaces never drift.
    from jpintel_mcp.api import fact_verify as fv

    if not fv._FACT_ID_RE.match(fact_id):
        return make_error(
            code="invalid_input",
            message="fact_id must match ^[A-Za-z0-9_-]{1,128}$",
            field="fact_id",
        )

    pubkey = fv._ed25519_public_key_bytes()
    if pubkey is None:
        return {
            "fact_id": fact_id,
            "verify": {
                "status": "key_unconfigured",
                "message": (
                    "AUTONOMATH_FACT_SIGN_PUBLIC_KEY is not set; the MCP "
                    "verify path cannot proceed. Configure operator Fly secret."
                ),
            },
            "why": None,
            "_billing_unit": 1,
            "_disclaimer": fv._VERIFY_DISCLAIMER,
        }

    conn_or_err = _open_autonomath_ro_safe()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err

    try:
        sig_row = conn.execute(
            "SELECT fact_id, ed25519_sig, corpus_snapshot_id, key_id, "
            "signed_at, payload_sha256 "
            "FROM v_am_fact_signature_latest WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        fact_row = conn.execute(
            "SELECT fact_id, subject_kind, subject_id, field_name, "
            "field_kind, value_text, value_number, value_date, "
            "source_document_id FROM extracted_fact WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()

        if fact_row is None:
            return make_error(
                code="not_found",
                message=f"fact not found: {fact_id}",
                field="fact_id",
            )

        # Verify branch (only if signature row present).
        verify_block: dict[str, Any]
        if sig_row is None:
            verify_block = {
                "status": "no_signature",
                "message": (
                    "No am_fact_signature row for this fact. The weekly "
                    "refresh_fact_signatures cron may not have run yet, "
                    "or the fact predates v2 signing."
                ),
            }
        else:
            import hashlib

            payload = fv._canonical_payload(
                fact_row, sig_row["corpus_snapshot_id"]
            )
            payload_hash = hashlib.sha256(payload).hexdigest()
            sig_bytes = bytes(sig_row["ed25519_sig"])
            is_valid = fv._verify_signature(payload, sig_bytes, pubkey)
            verify_block = {
                "status": "valid" if is_valid else "tampered",
                "signed_at": sig_row["signed_at"],
                "key_id": sig_row["key_id"],
                "corpus_snapshot_id": sig_row["corpus_snapshot_id"],
                "payload_sha256": payload_hash,
                "expected_payload_sha256": sig_row["payload_sha256"],
            }

        # Why branch — always available even when signature absent.
        src_row = None
        sdid = fact_row["source_document_id"]
        if sdid:
            with contextlib.suppress(sqlite3.Error):
                src_row = conn.execute(
                    "SELECT license, fetched_at FROM source_document "
                    "WHERE source_document_id = ?",
                    (sdid,),
                ).fetchone()

        explanation = fv._why_paragraph(fact_row, src_row)

        return {
            "fact_id": fact_id,
            "verify": verify_block,
            "why": {
                "explanation": explanation,
                "explanation_kind": "rule_based",
                "llm_used": False,
            },
            "_billing_unit": 1,
            "_disclaimer": fv._VERIFY_DISCLAIMER,
        }
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def fact_signature_verify_am(
        fact_id: Annotated[
            str,
            Field(
                description=(
                    "Fact id (`ef_...`). Returned by `extracted_fact` rows / "
                    "evidence-packet citations. Pattern: ^[A-Za-z0-9_-]{1,128}$."
                ),
                min_length=4,
                max_length=128,
            ),
        ],
    ) -> dict[str, Any]:
        """[FACT-SIGNATURE] Ed25519 signature verify + rule-based 'why' explanation for one extracted_fact row in a single MCP call. Returns verify={status: valid|tampered|no_signature|key_unconfigured, signed_at, key_id, payload_sha256} + why={explanation paragraph, rule_based, llm_used=false}. Detects byte-level tamper since signing (查察/audit retention proof) and surfaces the deterministic 'why this fact was extracted' paragraph in the same envelope. NO LLM, NO external HTTP. 1 ¥3 unit. §52/§47条の2/§72/§1 envelope. REST companions at GET /v1/facts/{fact_id}/verify + /v1/facts/{fact_id}/why."""
        return _fact_signature_verify_impl(fact_id=fact_id)


__all__ = [
    "_fact_signature_verify_impl",
]
