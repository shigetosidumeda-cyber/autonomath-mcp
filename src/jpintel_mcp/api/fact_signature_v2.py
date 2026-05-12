"""GET /v1/facts/signatures/* — Wave 46 Dim F signature discovery surface.

Companion to ``api/fact_verify.py`` (Wave 43.2.5). Where ``fact_verify``
runs the **byte-level Ed25519 verify** for a single fact_id, this
``fact_signature_v2`` module exposes the **metadata-only discovery**
surface so an auditor can:

  1. list which facts currently carry a published signature, paginated,
     without dragging the 96-byte sig BLOB across the wire on every row.
  2. fetch a single fact's signature metadata (signed_at, key_id,
     corpus_snapshot_id, payload_sha256) without running the Ed25519
     verify path — useful when the auditor only needs to confirm that
     a signature exists and was rotated under the expected key_id.

Both endpoints read from ``am_fact_signature`` (migration 262,
target_db: autonomath) via the ``v_am_fact_signature_latest`` view.

Hard constraints (Wave 43 / Wave 46 dim F)
------------------------------------------
* **NO LLM call.** Pure SQLite SELECT + Python dict shaping.
* **NO BLOB on the wire.** The ``ed25519_sig`` column is never copied
  into the JSON response — only the ``payload_sha256`` text digest and
  the metadata columns are surfaced. This keeps the response cacheable
  by CF Pages / browser cache and keeps the discovery cost flat at 1
  metered unit (¥3 / 税込 ¥3.30) regardless of payload size.
* **Single-DB.** Touches autonomath.db only. jpintel.db remains warm.
* **§52 / §47条の2 / §72 disclaimer parity** with sibling fact
  endpoints (verify / why / agreement). Output is a verification
  primitive, not a tax / 監査 / 法律 opinion.

Endpoints
---------
    GET /v1/facts/signatures/latest?limit=20&cursor=<fact_id>
        200 -> {"signatures": [ ...metadata only... ],
                 "next_cursor": "<fact_id>" | null,
                 "_billing_unit": 1, "_disclaimer": "..."}
        422 -> bad limit / cursor format

    GET /v1/facts/{fact_id}/signature
        200 -> {fact_id, signed_at, key_id, corpus_snapshot_id,
                 payload_sha256, sig_byte_length, _billing_unit: 1,
                 _disclaimer: "..."}
        404 -> fact_id has no signature row
        422 -> fact_id format invalid

The companion verify endpoint ``GET /v1/facts/{fact_id}/verify``
remains the source of truth for "is this fact byte-tamper-free?". The
new surface only answers "is this fact signed and under which key/at
which snapshot?".
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.api.fact_signature_v2")

router = APIRouter(prefix="/v1/facts", tags=["fact-signature-discovery"])

_FACT_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")

# 52 / 47条の2 / 72 non-substitution disclaimer; mirrors
# api/fact_verify.py:_VERIFY_DISCLAIMER for envelope parity. Kept
# in-file (not imported) so this module remains importable even when
# the migration 262 substrate is absent on import (experimental include).
_DISCOVERY_DISCLAIMER = (
    "本エンドポイントは autonomath.am_fact_signature (migration 262) の"
    "署名メタデータ (signed_at / key_id / corpus_snapshot_id / "
    "payload_sha256) を公開する発見系 API で、Ed25519 暗号検証は別途 "
    "GET /v1/facts/{fact_id}/verify を呼び出してください。 本サーフェスは"
    "税理士法 52 / 公認会計士法 47条の2 / 弁護士法 72 に基づく税務判断・"
    "監査意見・法律解釈の代替ではありません。"
)


def _open_autonomath_ro() -> sqlite3.Connection:
    """Open autonomath.db read-only-by-intent (no PRAGMA writes)."""
    path = os.environ.get(
        "AUTONOMATH_DB_PATH", str(settings.autonomath_db_path)
    )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _shape_signature_row(row: sqlite3.Row) -> dict[str, Any]:
    """Project the latest-view row into the public metadata envelope.

    Note: ``v_am_fact_signature_latest`` already strips off the index
    columns and the notes/internal columns. We additionally compute the
    signature byte length without copying the BLOB into the response
    (cryptography ed25519 raw signatures are 64 bytes; the column is
    BLOB(<=96) to accommodate the operator-side versioning frame).
    """
    sig = row["ed25519_sig"]
    sig_len = len(sig) if sig is not None else 0
    return {
        "fact_id": row["fact_id"],
        "signed_at": row["signed_at"],
        "key_id": row["key_id"],
        "corpus_snapshot_id": row["corpus_snapshot_id"],
        "payload_sha256": row["payload_sha256"],
        "sig_byte_length": int(sig_len),
    }


@router.get("/signatures/latest")
async def list_latest_signatures(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=128,
            description="Opaque cursor: last fact_id from previous page.",
        ),
    ] = None,
) -> JSONResponse:
    """List the latest published per-fact signature metadata.

    Pagination cursor is the ``fact_id`` of the last row in the previous
    page. Results are ordered by ``signed_at DESC, fact_id DESC`` so the
    most recently-signed facts surface first. Cursor compares on fact_id
    only (stable lex order); ties on signed_at are broken consistently.

    Pure metadata — the 96-byte signature BLOB is NEVER copied into the
    response. Only ``sig_byte_length`` (an integer) is surfaced.

    Cost: 1 metered unit (¥3 / 税込 ¥3.30), single autonomath read.
    """
    if cursor is not None and not _FACT_ID_RE.match(cursor):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_cursor",
                "message": (
                    "cursor must match ^[A-Za-z0-9_-]{1,128}$"
                ),
                "field": "cursor",
            },
        )

    sql_parts = [
        "SELECT fact_id, ed25519_sig, corpus_snapshot_id, key_id, "
        "signed_at, payload_sha256 "
        "FROM v_am_fact_signature_latest",
    ]
    params: list[Any] = []
    if cursor is not None:
        sql_parts.append("WHERE fact_id < ?")
        params.append(cursor)
    sql_parts.append("ORDER BY signed_at DESC, fact_id DESC")
    sql_parts.append("LIMIT ?")
    # +1 fetched to compute next_cursor without a second round-trip.
    params.append(limit + 1)
    sql = " ".join(sql_parts)

    conn = _open_autonomath_ro()
    try:
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            logger.warning("signature listing read failed err=%s", exc)
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "signature_store_unavailable",
                    "message": (
                        "autonomath am_fact_signature is not available "
                        "on this deployment; the cron signer may not "
                        "have populated the table yet."
                    ),
                },
            ) from exc
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    page = rows[:limit]
    next_cursor: str | None = None
    if len(rows) > limit:
        # The +1 sentinel row indicates more pages exist.
        next_cursor = page[-1]["fact_id"] if page else None

    body: dict[str, Any] = {
        "signatures": [_shape_signature_row(r) for r in page],
        "next_cursor": next_cursor,
        "count": len(page),
        "_billing_unit": 1,
        "_disclaimer": _DISCOVERY_DISCLAIMER,
    }
    return JSONResponse(content=body)


@router.get("/{fact_id}/signature")
async def get_signature_metadata(
    fact_id: str = PathParam(..., min_length=1, max_length=128),
) -> JSONResponse:
    """Return signature metadata for a single fact_id (no Ed25519 verify).

    Use ``GET /v1/facts/{fact_id}/verify`` when byte-tamper detection is
    required. This surface only confirms a signature exists and surfaces
    its discovery metadata (signed_at / key_id / corpus_snapshot_id /
    payload_sha256 / sig_byte_length).
    """
    if not _FACT_ID_RE.match(fact_id):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_fact_id",
                "message": "fact_id must match ^[A-Za-z0-9_-]{1,128}$",
                "field": "fact_id",
            },
        )

    conn = _open_autonomath_ro()
    try:
        try:
            row = conn.execute(
                "SELECT fact_id, ed25519_sig, corpus_snapshot_id, key_id, "
                "signed_at, payload_sha256 "
                "FROM v_am_fact_signature_latest WHERE fact_id = ?",
                (fact_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            logger.warning(
                "signature metadata read failed fact_id=%s err=%s",
                fact_id,
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "signature_store_unavailable",
                    "message": (
                        "autonomath am_fact_signature is not available "
                        "on this deployment."
                    ),
                },
            ) from exc
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "fact_signature_not_found",
                "message": (
                    "fact_id has no published signature. Either the "
                    "fact does not exist, or the weekly refresh cron "
                    "(scripts/cron/refresh_fact_signatures_weekly.py) "
                    "has not landed a signature yet."
                ),
                "fact_id": fact_id,
            },
        )

    body = _shape_signature_row(row)
    body["_billing_unit"] = 1
    body["_disclaimer"] = _DISCOVERY_DISCLAIMER
    return JSONResponse(content=body)


__all__ = ["router"]
