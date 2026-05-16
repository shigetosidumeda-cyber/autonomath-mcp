"""Per-fact Ed25519 signature verify + rule-based why-explanation surface.

Wave 43.2.5 — Dim E Verification trail
======================================

Exposes two `/v1/facts/{fact_id}/*` endpoints that close the gap between
the daily Merkle root anchor (api/audit_proof.py) and the narrative
audit_seal envelope (api/_audit_seal.py + migration 089):

  GET /v1/facts/{fact_id}/verify  -> byte-tamper-detectable Ed25519 verify
                                     200 valid / 409 tampered / 404 missing
  GET /v1/facts/{fact_id}/why     -> rule-based explanation paragraph
                                     (template + DB join, NO LLM call)

Both endpoints are 3/req metered (税込 3.30). NO LLM, NO external API
calls -- pure SQLite + cryptography stdlib (Ed25519). The explanation
text in /why is assembled from `extracted_fact` columns + canned
templates per `field_kind` enum, so the same fact_id always produces
the same paragraph (deterministic, auditable, customer-reproducible).

Why this exists
---------------
Customer-side audit working papers cite a single fact_id at a time
("法人税法 52 の解釈は autonomath.fact_id=ef_38d...1c2 に拠る"). A 査察 /
税理士法 41 retention check must be able to:

  (1) prove the fact has not been amended since signing -- Ed25519
      signature against the canonical fact payload (subject, field,
      value, source_document_id, corpus_snapshot_id).
  (2) read a human-language explanation of WHY the fact was extracted
      this way -- without rebuilding the operator's reasoning chain
      from the row's selector_json / metadata_json.

52 / 47-2 posture
----------------------
This is a verification primitive, not a tax-advice surface. The
explanation paragraph is descriptive ("this fact was extracted from
courts.go.jp/hanrei_jp/12345 on 2026-05-04 under corpus_snapshot
cs_2026_05_04") and never offers an interpretation. Both endpoints
still carry `_disclaimer` for envelope parity with sibling
/v1/audit/* surfaces.

Storage
-------
Per-fact signatures live in `am_fact_signature` (migration 262,
target_db: autonomath). The signing key lives in Fly secret
`AUTONOMATH_FACT_SIGN_PRIVATE_KEY`. The corresponding public key is
exposed at GET /v1/audit/fact_pubkey for third-party verify.

Cost note
---------
Verify path is in-process: one SQLite read of `am_fact_signature`
latest-row view + one Ed25519 verify call (cryptography stdlib). No
Anthropic / OpenAI / Gemini / Stripe / external HTTP. The DB read is
cached by SQLite's page cache; sub-millisecond hot path under load.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.config import settings

_log = logging.getLogger("jpintel.api.fact_verify")

router = APIRouter(prefix="/v1/facts", tags=["fact-verify"])

# 52 / 47-2 / 72 non-substitution disclaimer.
_VERIFY_DISCLAIMER = (
    "本エンドポイントは Ed25519 署名による事実改ざん検出の暗号学的監査基盤"
    "であり、税理士法 52 / 公認会計士法 47条の2 / 弁護士法 72 に基づく"
    "税務判断・監査意見・法律解釈の代替ではありません。 一次資料 (e-Gov / "
    "国税庁 / 裁判所 / EDINET 等) を必ず併せて確認してください。"
)

_FACT_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")


def _open_autonomath_ro() -> sqlite3.Connection:
    """Read-only-by-intent connection to autonomath.db.

    Mirrors api/audit_proof.py: we use AUTONOMATH_DB_PATH for parity with
    the cron writer and do not pin a thread-local cached handle here.
    """
    path = os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _canonical_payload(fact_row: Any, snapshot_id: str | None) -> bytes:
    """Build the canonical byte-payload that was signed.

    MUST match the cron signer exactly -- any divergence yields 409 on
    every legitimate fact. Stable across runs by:
      - sorted keys
      - explicit None for missing optional columns
      - UTF-8 encode with ensure_ascii=False so kanji values byte-match
      - no trailing whitespace
    """
    payload = {
        "fact_id": fact_row["fact_id"],
        "subject_kind": fact_row["subject_kind"],
        "subject_id": fact_row["subject_id"],
        "field_name": fact_row["field_name"],
        "field_kind": fact_row["field_kind"],
        "value_text": fact_row["value_text"],
        "value_number": fact_row["value_number"],
        "value_date": fact_row["value_date"],
        "source_document_id": fact_row["source_document_id"],
        "corpus_snapshot_id": snapshot_id,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _ed25519_public_key_bytes() -> bytes | None:
    """Resolve the operator-side Ed25519 public key from env.

    Hex-encoded 32-byte raw public key in `AUTONOMATH_FACT_SIGN_PUBLIC_KEY`.
    Returns None if not configured (verify endpoint then returns 503).
    """
    raw = os.environ.get("AUTONOMATH_FACT_SIGN_PUBLIC_KEY")
    if not raw:
        return None
    raw = raw.strip()
    try:
        return bytes.fromhex(raw)
    except ValueError:
        _log.warning("AUTONOMATH_FACT_SIGN_PUBLIC_KEY is not valid hex")
        return None


def _verify_signature(payload: bytes, sig: bytes, pubkey: bytes) -> bool:
    """Cryptography stdlib Ed25519 verify. Returns True iff valid.

    The signature stored in `am_fact_signature.ed25519_sig` BLOB(96) is
    a 64-byte raw Ed25519 signature optionally framed with operator-side
    versioning. We strip framing bytes and verify the canonical 64-byte
    core; if length is 64 exactly, use directly.
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError:
        _log.warning("cryptography package not installed; verify=False")
        return False

    if len(sig) == 64:
        core = sig
    elif len(sig) == 80:
        core = sig[8:72]
    elif len(sig) >= 64:
        core = sig[-64:]
    else:
        return False

    try:
        Ed25519PublicKey.from_public_bytes(pubkey).verify(core, payload)
        return True
    except InvalidSignature:
        return False
    except Exception as exc:
        _log.warning("ed25519 verify raised %s", exc)
        return False


@router.get("/{fact_id}/verify")
async def verify_fact(
    fact_id: str = PathParam(..., min_length=1, max_length=128),
) -> JSONResponse:
    """Verify a single fact's Ed25519 signature.

    Status codes:
      200 - signature is valid, fact unmodified since signing.
      404 - fact_id not found in either extracted_fact or am_fact_signature.
      409 - signature exists but verify fails (tamper detected).
      503 - operator public key not configured.
    """
    if not _FACT_ID_RE.match(fact_id):
        raise HTTPException(
            status_code=400,
            detail={"error": "fact_id must match ^[A-Za-z0-9_-]{1,128}$"},
        )

    pubkey = _ed25519_public_key_bytes()
    if pubkey is None:
        return JSONResponse(
            status_code=503,
            content={
                "fact_id": fact_id,
                "status": "key_unconfigured",
                "message": (
                    "AUTONOMATH_FACT_SIGN_PUBLIC_KEY is not set on this "
                    "deployment; verify cannot proceed."
                ),
                "_disclaimer": _VERIFY_DISCLAIMER,
            },
        )

    conn = _open_autonomath_ro()
    try:
        sig_row = conn.execute(
            "SELECT fact_id, ed25519_sig, corpus_snapshot_id, key_id, "
            "signed_at, payload_sha256 "
            "FROM v_am_fact_signature_latest WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        if sig_row is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "fact_signature_not_found",
                    "fact_id": fact_id,
                    "_disclaimer": _VERIFY_DISCLAIMER,
                },
            )

        fact_row = conn.execute(
            "SELECT fact_id, subject_kind, subject_id, field_name, "
            "field_kind, value_text, value_number, value_date, "
            "source_document_id FROM extracted_fact WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        if fact_row is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "fact_not_found",
                    "fact_id": fact_id,
                    "_disclaimer": _VERIFY_DISCLAIMER,
                },
            )

        payload = _canonical_payload(fact_row, sig_row["corpus_snapshot_id"])
        payload_hash = hashlib.sha256(payload).hexdigest()
        sig_bytes = bytes(sig_row["ed25519_sig"])

        is_valid = _verify_signature(payload, sig_bytes, pubkey)

        envelope: dict[str, Any] = {
            "fact_id": fact_id,
            "status": "valid" if is_valid else "tampered",
            "signed_at": sig_row["signed_at"],
            "key_id": sig_row["key_id"],
            "corpus_snapshot_id": sig_row["corpus_snapshot_id"],
            "payload_sha256": payload_hash,
            "expected_payload_sha256": sig_row["payload_sha256"],
            "_disclaimer": _VERIFY_DISCLAIMER,
        }
        return JSONResponse(
            status_code=200 if is_valid else 409,
            content=envelope,
        )
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def _why_paragraph(fact_row: Any, src_row: Any | None) -> str:
    """Build a deterministic rule-based explanation paragraph.

    No LLM. Pure f-string. Same fact_id -> same paragraph forever.
    """
    fid = fact_row["fact_id"]
    sk = fact_row["subject_kind"]
    sid = fact_row["subject_id"]
    fname = fact_row["field_name"]
    fkind = fact_row["field_kind"] or "text"
    sdid = fact_row["source_document_id"] or "(出典文書 ID なし)"

    if fkind == "number":
        val = fact_row["value_number"]
        val_str = f"{val:,.4f}" if val is not None else "(NULL)"
    elif fkind == "date":
        val_str = fact_row["value_date"] or "(NULL)"
    else:
        text = fact_row["value_text"]
        if text is None:
            val_str = "(NULL)"
        elif len(text) > 80:
            val_str = text[:80] + "..."
        else:
            val_str = text

    if src_row is not None:
        license_name = src_row["license"] or "unknown"
        fetched_at = src_row["fetched_at"] or "unknown"
    else:
        license_name = "unknown"
        fetched_at = "unknown"

    return (
        f"本 fact (fact_id={fid}) は {sk} {sid} の "
        f"{fname} 値 「{val_str}」 を、{sdid} (license={license_name}, "
        f"fetched_at={fetched_at}) から抽出した結果である。 "
        f"抽出は LLM を介さず決定論的 ETL (cron extract_program_facts.py) "
        f"により行われ、税理士法 52 / 公認会計士法 47条の2 / 弁護士法 "
        f"72 に基づく税務判断・監査意見・法律解釈は一切含まない。 "
        f"field_kind={fkind} につき値表記は ETL canonicalize 規約に従う。"
    )


@router.get("/{fact_id}/why")
async def why_fact(
    fact_id: str = PathParam(..., min_length=1, max_length=128),
) -> JSONResponse:
    """Return a rule-based explanation paragraph for a single fact.

    NO LLM. Template + DB join only. Same fact_id -> same output forever
    (deterministic, customer-reproducible).
    """
    if not _FACT_ID_RE.match(fact_id):
        raise HTTPException(
            status_code=400,
            detail={"error": "fact_id must match ^[A-Za-z0-9_-]{1,128}$"},
        )

    conn = _open_autonomath_ro()
    try:
        fact_row = conn.execute(
            "SELECT fact_id, subject_kind, subject_id, field_name, "
            "field_kind, value_text, value_number, value_date, "
            "source_document_id FROM extracted_fact WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        if fact_row is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "fact_not_found",
                    "fact_id": fact_id,
                    "_disclaimer": _VERIFY_DISCLAIMER,
                },
            )

        src_row = None
        sdid = fact_row["source_document_id"]
        if sdid:
            with contextlib.suppress(sqlite3.Error):
                src_row = conn.execute(
                    "SELECT license, fetched_at FROM source_document WHERE source_document_id = ?",
                    (sdid,),
                ).fetchone()

        paragraph = _why_paragraph(fact_row, src_row)

        return JSONResponse(
            status_code=200,
            content={
                "fact_id": fact_id,
                "explanation": paragraph,
                "explanation_kind": "rule_based",
                "llm_used": False,
                "_disclaimer": _VERIFY_DISCLAIMER,
            },
        )
    finally:
        with contextlib.suppress(Exception):
            conn.close()
