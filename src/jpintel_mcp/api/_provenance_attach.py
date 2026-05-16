"""Wave 49 Dim O — provenance attach middleware (4-axis JSON-LD).

Surfaces ``am_fact_metadata`` (migration 275) explainability metadata as a
JSON-LD-compatible ``provenance`` envelope on REST responses that cite
``fact_id`` values. The 4 axes (source_doc / extracted_at / verified_by /
confidence band) are attached as a sidecar block under the existing
response envelope so:

  * Existing fields are UNTOUCHED (additive only).
  * LLM agents reading the response can cite the source URL deterministically.
  * The Ed25519 attestation chain length (``attestation_count`` from
    ``v_am_fact_attestation_latest``) is included as an auditability signal.

Design constraints
------------------
* **NO LLM call.** Pure sqlite3 SELECT, no inference.
* **NO new env vars.** Reads from existing ``AUTONOMATH_DB_PATH``.
* **NEVER mutates** ``am_fact_signature`` / ``am_fact_metadata`` /
  ``am_fact_attestation_log``. Read-only.
* **Append-mode envelope.** ``attach()`` returns a NEW dict; the input
  payload is not mutated in-place.
* **Soft-fail.** If ``am_fact_metadata`` is missing (migration 275 not
  applied) or the fact_id has no metadata row, the helper returns the
  payload unchanged. No exception propagates to the request handler.
* **¥3/req billing posture.** Adding the provenance block does NOT change
  the per-call price — it's the same metered response with one extra
  JSON-LD sidecar.

JSON-LD schema (additive)
-------------------------
The middleware adds (when fact_id(s) resolve)::

    {
      ... existing envelope ...,
      "provenance": {
        "@context": "https://schema.org/",
        "@type": "Dataset",
        "facts": [
          {
            "fact_id": "...",
            "source_doc": "https://elaws.e-gov.go.jp/...",
            "extracted_at": "2026-05-12T01:23:45.000Z",
            "verified_by": "etl_build_explainable_fact_metadata_v1",
            "confidence": {"lower": 0.85, "upper": 0.95},
            "attestation_count": 3,
            "latest_signed_at": "2026-05-12T01:23:45.000Z",
            "ed25519_sig_present": true
          }
        ]
      }
    }
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

_log = logging.getLogger("jpcite.api._provenance_attach")

_JSONLD_CONTEXT = "https://schema.org/"
_JSONLD_TYPE = "Dataset"


def _resolve_db_path() -> str:
    explicit = os.environ.get("AUTONOMATH_DB_PATH")
    if explicit:
        return explicit
    cwd = os.getcwd()
    candidate = os.path.join(cwd, "autonomath.db")
    if os.path.exists(candidate):
        return candidate
    return os.path.join(cwd, "data", "autonomath.db")


def _lookup_one(conn: sqlite3.Connection, fact_id: str) -> dict[str, Any] | None:
    """Return a JSON-LD-compatible provenance dict for a single fact_id.

    Returns None when no metadata row exists. Reads from the helper view
    ``v_am_fact_explainability`` (joins ``am_fact_metadata`` +
    ``v_am_fact_attestation_latest``).
    """
    try:
        cur = conn.execute(
            """
            SELECT fact_id, source_doc, extracted_at, verified_by,
                   confidence_lower, confidence_upper, sig_byte_length,
                   latest_signed_at, attestation_count
            FROM v_am_fact_explainability
            WHERE fact_id = ?
            LIMIT 1
            """,
            (fact_id,),
        )
        row = cur.fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    (
        fid,
        source_doc,
        extracted_at,
        verified_by,
        conf_lo,
        conf_hi,
        sig_len,
        latest_signed_at,
        attestation_count,
    ) = row
    out: dict[str, Any] = {
        "fact_id": fid,
        "source_doc": source_doc,
        "extracted_at": extracted_at,
        "verified_by": verified_by,
        "ed25519_sig_present": bool(sig_len and sig_len > 0),
    }
    if conf_lo is not None or conf_hi is not None:
        out["confidence"] = {"lower": conf_lo, "upper": conf_hi}
    if attestation_count is not None:
        out["attestation_count"] = int(attestation_count)
    if latest_signed_at is not None:
        out["latest_signed_at"] = latest_signed_at
    return out


def lookup(fact_ids: list[str], *, db_path: str | None = None) -> list[dict[str, Any]]:
    """Resolve provenance for a list of fact_ids. Soft-fails to []."""
    if not fact_ids:
        return []
    path = db_path or _resolve_db_path()
    if not os.path.exists(path):
        _log.debug("autonomath.db missing at %s — skipping provenance", path)
        return []
    out: list[dict[str, Any]] = []
    conn = sqlite3.connect(path)
    try:
        for fid in fact_ids:
            if not isinstance(fid, str) or not fid:
                continue
            row = _lookup_one(conn, fid)
            if row is not None:
                out.append(row)
    finally:
        conn.close()
    return out


def attach(
    payload: dict[str, Any],
    fact_ids: list[str] | None = None,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Return a NEW dict = payload + ``provenance`` sidecar (JSON-LD).

    The input payload is not mutated. When no fact_ids resolve to a
    metadata row, the payload is returned unchanged (no empty sidecar).
    """
    if not isinstance(payload, dict):
        return payload  # nothing safe to do
    ids = fact_ids if fact_ids is not None else _extract_fact_ids(payload)
    if not ids:
        return payload
    facts = lookup(ids, db_path=db_path)
    if not facts:
        return payload
    enriched = dict(payload)
    enriched["provenance"] = {
        "@context": _JSONLD_CONTEXT,
        "@type": _JSONLD_TYPE,
        "facts": facts,
    }
    return enriched


def _extract_fact_ids(payload: dict[str, Any]) -> list[str]:
    """Best-effort fact_id discovery from a typical jpcite envelope.

    Looks at: top-level ``fact_id``, top-level ``fact_ids``, and
    ``results[*].fact_id`` for the common list-response shape.
    """
    out: list[str] = []
    fid = payload.get("fact_id")
    if isinstance(fid, str) and fid:
        out.append(fid)
    fids = payload.get("fact_ids")
    if isinstance(fids, list):
        out.extend(x for x in fids if isinstance(x, str) and x)
    results = payload.get("results")
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict):
                ifid = item.get("fact_id")
                if isinstance(ifid, str) and ifid:
                    out.append(ifid)
    # dedupe preserving order
    seen: set[str] = set()
    dedup: list[str] = []
    for x in out:
        if x not in seen:
            dedup.append(x)
            seen.add(x)
    return dedup


__all__ = ["attach", "lookup"]
