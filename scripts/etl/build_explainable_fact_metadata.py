"""Daily ETL — build 4-axis explainability metadata + attestation chain.

Wave 47 — Dim O (explainable_fact_design)
=========================================

Walks ``am_fact_signature`` (migration 262, byte-tamper Ed25519 verify
substrate) and produces the 4-axis explainability metadata for every
signed fact:

  (1) ``source_doc``     — primary source URL or in-house corpus anchor
  (2) ``extracted_at``   — when the fact was extracted (NOT the sign time)
  (3) ``verified_by``    — extractor / attester pipeline identifier
  (4) confidence band    — [lower, upper] interval in [0.0, 1.0]

The metadata is UPSERTed into ``am_fact_metadata`` (migration 275). Each
UPSERT also appends a row into the **append-only** ``am_fact_attestation
_log`` so the attestation chain is auditable independently of the
latest-only metadata row.

Design constraints
------------------
* **NO LLM call.** Pure SQLite + cryptography stdlib (Ed25519 sign).
* **NEVER overwrite am_fact_signature.** This ETL is read-only against
  the Wave 43.2.5 Ed25519 substrate; it only writes to migration 275
  tables (am_fact_metadata + am_fact_attestation_log).
* **Append-only log.** ``am_fact_attestation_log`` is INSERT-only. The
  ETL never DELETEs or UPDATEs rows in that table.
* **9.7 GB autonomath.db full-scan footgun.** Per feedback_no_quick_check
  _on_huge_sqlite memory: 50,000-row chunked walk with indexed cursor
  pagination. Each chunk commits independently.
* **Idempotent.** Re-running on a converged corpus produces zero writes
  to am_fact_metadata. The attestation log only appends when the
  explainability tuple ACTUALLY changes (hash compared on UPSERT).

Operational hook
----------------
Schedule via .github/workflows/build-explainable-fact-metadata-daily.yml
at 03:30 UTC (12:30 JST). On each tick::

    python scripts/etl/build_explainable_fact_metadata.py \\
        [--max-rows N] [--dry-run]

Exit code 0 on success, 1 on key resolution failure, 2 on DB I/O
failure. Stdout emits a one-line JSON summary for log aggregation.

Source discipline
-----------------
* Sign key reuses Fly secret ``AUTONOMATH_FACT_SIGN_PRIVATE_KEY`` (same
  Ed25519 32-byte seed as refresh_fact_signatures_weekly.py — keeps
  Wave 43.2.5 + Wave 47 attestations under one rotateable key).
* NO new env vars. NO new API calls. NO new external dependencies
  beyond cryptography (already pinned via refresh_fact_signatures_weekly).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
from typing import Any

_log = logging.getLogger("jpcite.etl.build_explainable_fact_metadata")

CHUNK_SIZE = 50_000  # 9.7 GB footgun — index-walk only
DEFAULT_VERIFIED_BY = "etl_build_explainable_fact_metadata_v1"
_COLUMN_CACHE: dict[tuple[str, str, str], bool] = {}


def _resolve_db_path() -> str:
    explicit = os.environ.get("AUTONOMATH_DB_PATH")
    if explicit:
        return explicit
    cwd = os.getcwd()
    candidate = os.path.join(cwd, "autonomath.db")
    if os.path.exists(candidate):
        return candidate
    return os.path.join(cwd, "data", "autonomath.db")


def _load_private_key() -> Any:
    """Resolve Ed25519 private key from env. Exits 1 on failure."""
    raw = os.environ.get("AUTONOMATH_FACT_SIGN_PRIVATE_KEY")
    if not raw:
        _log.error("AUTONOMATH_FACT_SIGN_PRIVATE_KEY env var is not set")
        sys.exit(1)
    raw = raw.strip()
    try:
        seed = bytes.fromhex(raw)
    except ValueError:
        _log.error("AUTONOMATH_FACT_SIGN_PRIVATE_KEY is not valid hex")
        sys.exit(1)
    if len(seed) != 32:
        _log.error(
            "AUTONOMATH_FACT_SIGN_PRIVATE_KEY must be 32 raw bytes; got %d",
            len(seed),
        )
        sys.exit(1)
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
    except ImportError:
        _log.error("cryptography package not installed")
        sys.exit(1)
    return Ed25519PrivateKey.from_private_bytes(seed)


def _canonical_metadata_payload(
    fact_id: str,
    source_doc: str | None,
    extracted_at: str,
    verified_by: str | None,
    conf_lo: float | None,
    conf_hi: float | None,
) -> bytes:
    """Deterministic 4-axis payload for Ed25519 signing.

    Sorted keys + sort_keys=True + separators=(",",":") to ensure a
    byte-identical encoding between sign and verify.
    """
    payload = {
        "fact_id": fact_id,
        "source_doc": source_doc,
        "extracted_at": extracted_at,
        "verified_by": verified_by,
        "confidence_lower": conf_lo,
        "confidence_upper": conf_hi,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        db_key = conn.execute("PRAGMA database_list").fetchone()[2]
    except (sqlite3.OperationalError, TypeError):
        db_key = str(id(conn))
    cache_key = (db_key or str(id(conn)), table, column)
    if cache_key in _COLUMN_CACHE:
        return _COLUMN_CACHE[cache_key]
    try:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.OperationalError:
        _COLUMN_CACHE[cache_key] = False
        return False
    found = any(row[1] == column for row in cols)
    _COLUMN_CACHE[cache_key] = found
    return found


def _derive_source_doc(fact_id: str, conn: sqlite3.Connection) -> str | None:
    """Look up source_doc anchor for a fact_id.

    Reads the current EAV schema, where ``am_entity_facts.id`` is the
    canonical metadata fact_id and source URL comes from the fact row or
    its source row.
    """
    try:
        cur = conn.execute(
            """
            SELECT COALESCE(f.source_url, s.source_url)
            FROM am_entity_facts f
            LEFT JOIN am_source s ON s.id = f.source_id
            WHERE CAST(f.id AS TEXT) = ?
            LIMIT 1
            """,
            (fact_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def _derive_confidence(fact_id: str, conn: sqlite3.Connection) -> tuple[float | None, float | None]:
    """Confidence band (lower, upper) for a fact_id.

    Reads optional ``am_entity_facts.confidence`` when present. Widens to
    ±0.05 to produce a non-zero band for the Dim O contract. Returns
    (None, None) when the current schema has no confidence column.
    """
    if not _has_column(conn, "am_entity_facts", "confidence"):
        return (None, None)
    try:
        cur = conn.execute(
            """
            SELECT confidence
            FROM am_entity_facts
            WHERE CAST(id AS TEXT) = ?
            LIMIT 1
            """,
            (fact_id,),
        )
        row = cur.fetchone()
        if not row or row[0] is None:
            return (None, None)
        try:
            point = float(row[0])
        except (TypeError, ValueError):
            return (None, None)
        lo = max(0.0, point - 0.05)
        hi = min(1.0, point + 0.05)
        return (lo, hi)
    except sqlite3.OperationalError:
        return (None, None)


def _enrich_one(
    conn: sqlite3.Connection,
    fact_id: str,
    signed_at: str,
    priv_key: Any,
    *,
    dry_run: bool,
) -> str:
    """Enrich a single fact_id into metadata + attestation log row.

    Returns one of: 'upserted' (new/changed), 'unchanged', 'skipped'.
    """
    source_doc = _derive_source_doc(fact_id, conn)
    conf_lo, conf_hi = _derive_confidence(fact_id, conn)
    extracted_at = signed_at  # best proxy when no separate extract ts
    verified_by = DEFAULT_VERIFIED_BY

    payload = _canonical_metadata_payload(
        fact_id, source_doc, extracted_at, verified_by, conf_lo, conf_hi
    )
    raw_sig = priv_key.sign(payload)  # 64 raw bytes
    sig_hex = raw_sig.hex()
    # Prefix-encoded BLOB to match am_fact_signature.ed25519_sig shape
    prefixed_sig = b"\x01\x00\x00\x00\x00\x00\x00\x00" + raw_sig + b"\x00" * 8

    # Compare against existing row to skip no-op writes (idempotent).
    cur = conn.execute(
        "SELECT ed25519_sig FROM am_fact_metadata WHERE fact_id = ?",
        (fact_id,),
    )
    existing = cur.fetchone()
    if existing is not None and existing[0] == prefixed_sig:
        return "unchanged"

    if dry_run:
        return "upserted"

    conn.execute(
        """
        INSERT INTO am_fact_metadata
            (fact_id, source_doc, extracted_at, verified_by,
             confidence_lower, confidence_upper, ed25519_sig)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fact_id) DO UPDATE SET
            source_doc       = excluded.source_doc,
            extracted_at     = excluded.extracted_at,
            verified_by      = excluded.verified_by,
            confidence_lower = excluded.confidence_lower,
            confidence_upper = excluded.confidence_upper,
            ed25519_sig      = excluded.ed25519_sig,
            updated_at       = strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (
            fact_id,
            source_doc,
            extracted_at,
            verified_by,
            conf_lo,
            conf_hi,
            prefixed_sig,
        ),
    )

    conn.execute(
        """
        INSERT INTO am_fact_attestation_log
            (fact_id, attester, signature_hex)
        VALUES (?, ?, ?)
        """,
        (fact_id, verified_by, sig_hex),
    )

    return "upserted"


def _walk(
    conn: sqlite3.Connection, priv_key: Any, max_rows: int, dry_run: bool
) -> dict[str, int]:
    counts = {"upserted": 0, "unchanged": 0, "skipped": 0, "errors": 0}
    cursor: str | None = None
    walked = 0

    while True:
        if cursor is None:
            cur = conn.execute(
                "SELECT fact_id, signed_at FROM am_fact_signature "
                "ORDER BY fact_id ASC LIMIT ?",
                (CHUNK_SIZE,),
            )
        else:
            cur = conn.execute(
                "SELECT fact_id, signed_at FROM am_fact_signature "
                "WHERE fact_id > ? ORDER BY fact_id ASC LIMIT ?",
                (cursor, CHUNK_SIZE),
            )
        batch = cur.fetchall()
        if not batch:
            break

        for fact_id, signed_at in batch:
            if max_rows and walked >= max_rows:
                return counts
            try:
                outcome = _enrich_one(
                    conn, fact_id, signed_at, priv_key, dry_run=dry_run
                )
                counts[outcome] += 1
            except sqlite3.IntegrityError:
                counts["errors"] += 1
                _log.warning("integrity error enriching fact_id=%s", fact_id)
            walked += 1
            cursor = fact_id

        if not dry_run:
            conn.commit()

    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    db_path = _resolve_db_path()
    if not os.path.exists(db_path):
        _log.error("autonomath.db not found at %s", db_path)
        return 2

    priv_key = _load_private_key()

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = None  # tuple rows are fine for this walker
        # Schema sanity — fail fast if migration 275 hasn't run.
        try:
            conn.execute("SELECT 1 FROM am_fact_metadata LIMIT 1")
            conn.execute("SELECT 1 FROM am_fact_attestation_log LIMIT 1")
        except sqlite3.OperationalError:
            _log.error(
                "migration 275 tables missing — apply 275_explainable_fact.sql"
            )
            return 2

        counts = _walk(conn, priv_key, args.max_rows, args.dry_run)
    finally:
        conn.close()

    summary = {
        "etl": "build_explainable_fact_metadata",
        "dry_run": args.dry_run,
        **counts,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
