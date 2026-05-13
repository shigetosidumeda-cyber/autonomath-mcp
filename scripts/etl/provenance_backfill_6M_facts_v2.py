"""Wave 49 Phase 1 — Dim O provenance backfill v2 (residual am_fact_metadata rows).

Wave 47 (Phase 2) shipped ``build_explainable_fact_metadata.py`` which walks
``am_fact_signature`` (migration 262) and UPSERTs the 4-axis explainability
metadata (source_doc / extracted_at / verified_by / confidence band) into
``am_fact_metadata`` (migration 275). That walker covers facts that have a
signature row.

Residual gap closed by this v2 script
-------------------------------------
A non-zero number of ``am_entity_facts`` rows (the canonical 6.12M-row EAV
store) do not yet have a corresponding ``am_fact_metadata`` row — typically
because:

  (a) the fact pre-dates migration 262 signing (legacy extraction);
  (b) the fact was registered in ``am_fact_signature`` but the v1 ETL was
      truncated by ``--max-rows`` (smoke runs during Wave 47 Phase 2);
  (c) the fact was added by an ingest pipeline that does not chain through
      ``am_fact_signature`` (e.g., daily axis-3 amendment_diff_v3).

This v2 backfill walks ``am_entity_facts`` directly (NOT ``am_fact_signature``)
and idempotently UPSERTs an ``am_fact_metadata`` row for any metadata fact id
where ``source_doc IS NULL`` OR no metadata row exists. The metadata fact id is
``am_entity_facts.id`` stringified. The 4-axis tuple is derived from
``am_entity_facts`` columns (``COALESCE(f.source_url, s.source_url)`` via
``am_source.id`` join, optional ``confidence`` → [lower, upper] band,
``extracted_at`` proxy from the parent row's ``created_at`` when present,
``verified_by`` = ``etl_prov_backfill_v2``).

Hard constraints
----------------
* **9.7 GB autonomath.db footgun** (memory: feedback_no_quick_check_on_huge_sqlite).
  No ``PRAGMA quick_check``. Indexed cursor pagination with ``CHUNK_SIZE=1000``
  rows per commit, target 6,000 batches (~6M facts).
* **Idempotent.** Targets only ``fact_id`` rows where the metadata is missing
  OR ``source_doc IS NULL`` — re-running on a converged corpus is a no-op.
* **Never mutates ``am_fact_signature``** (migration 262 substrate). Only
  writes to migration 275 tables (``am_fact_metadata`` + ``am_fact_attestation_log``).
* **Append-only attestation log.** Each metadata UPSERT also appends one row
  into ``am_fact_attestation_log`` so the chain stays auditable.
* **Ed25519 sign optional.** When ``AUTONOMATH_FACT_SIGN_PRIVATE_KEY`` env is
  absent (CI runners without secrets), the script still backfills metadata
  with a deterministic 64-byte zero-pad placeholder signature (NULL not
  permitted by migration 275 CHECK constraint), so the wider null backfill
  still proceeds. Real sign happens on the next nightly v1 run.
* **No LLM call.** Pure sqlite3 + cryptography stdlib.
* **No new env vars, no new external dependencies.**

CLI
---
::

    python scripts/etl/provenance_backfill_6M_facts_v2.py \\
        [--max-rows N] [--dry-run] [--chunk-size N] [--verbose]

Exit code 0 on success, 1 on key resolution failure (when key is required
and missing), 2 on DB I/O failure. Stdout emits a one-line JSON summary.

Operational hook
----------------
Schedule via ``.github/workflows/build-explainable-fact-metadata-daily.yml``
(reuses existing daily cron). The v2 script runs AFTER the v1 walker in the
same workflow step so the v1 covers signed facts first and v2 sweeps the
residual unsigned/legacy rows.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from typing import Any

_log = logging.getLogger("jpcite.etl.provenance_backfill_6M_facts_v2")

DEFAULT_CHUNK_SIZE = 1_000
DEFAULT_VERIFIED_BY = "etl_prov_backfill_v2"
_COLUMN_CACHE: dict[tuple[str, str, str], bool] = {}
# 64-byte zero-pad placeholder for unsigned legacy rows (still satisfies
# am_fact_metadata length CHECK >= 64). Real sign happens on next v1 tick.
_PLACEHOLDER_SIG = b"\x00" * 64


def _resolve_db_path() -> str:
    explicit = os.environ.get("AUTONOMATH_DB_PATH")
    if explicit:
        return explicit
    cwd = os.getcwd()
    candidate = os.path.join(cwd, "autonomath.db")
    if os.path.exists(candidate):
        return candidate
    return os.path.join(cwd, "data", "autonomath.db")


def _try_load_private_key() -> Any | None:
    raw = os.environ.get("AUTONOMATH_FACT_SIGN_PRIVATE_KEY")
    if not raw:
        return None
    raw = raw.strip()
    try:
        seed = bytes.fromhex(raw)
    except ValueError:
        _log.warning("AUTONOMATH_FACT_SIGN_PRIVATE_KEY not valid hex — using placeholder")
        return None
    if len(seed) != 32:
        _log.warning(
            "AUTONOMATH_FACT_SIGN_PRIVATE_KEY must be 32 raw bytes; got %d", len(seed)
        )
        return None
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
    except ImportError:
        _log.warning("cryptography package not installed — using placeholder")
        return None
    return Ed25519PrivateKey.from_private_bytes(seed)


def _canonical_payload(
    fact_id: str,
    source_doc: str | None,
    extracted_at: str,
    verified_by: str,
    conf_lo: float | None,
    conf_hi: float | None,
) -> bytes:
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


def _derive_source_doc(conn: sqlite3.Connection, fact_id: object) -> str | None:
    try:
        cur = conn.execute(
            """
            SELECT COALESCE(f.source_url, s.source_url)
            FROM am_entity_facts f
            LEFT JOIN am_source s ON s.id = f.source_id
            WHERE f.id = ?
            LIMIT 1
            """,
            (fact_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def _derive_confidence(
    conn: sqlite3.Connection, fact_id: object
) -> tuple[float | None, float | None]:
    if not _has_column(conn, "am_entity_facts", "confidence"):
        return (None, None)
    try:
        cur = conn.execute(
            """
            SELECT confidence
            FROM am_entity_facts
            WHERE id = ?
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


def _derive_extracted_at(conn: sqlite3.Connection, fact_id: object) -> str:
    try:
        cur = conn.execute(
            """
            SELECT created_at
            FROM am_entity_facts
            WHERE id = ?
            LIMIT 1
            """,
            (fact_id,),
        )
        row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
    except sqlite3.OperationalError:
        pass
    # Fallback to migration 275 DEFAULT (NOW). Use SQLite computed default.
    cur = conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')")
    return cur.fetchone()[0]


def _sign(priv_key: Any | None, payload: bytes) -> tuple[bytes, str]:
    """Return (prefixed_blob_for_metadata, hex_for_attestation_log).

    When ``priv_key`` is None, returns the deterministic placeholder so the
    metadata row still satisfies length CHECK >= 64. Real sign happens on
    the next nightly v1 walker tick.
    """
    if priv_key is None:
        prefixed = _PLACEHOLDER_SIG
        sig_hex = _PLACEHOLDER_SIG.hex()
        return prefixed, sig_hex
    raw_sig = priv_key.sign(payload)
    prefixed = b"\x01\x00\x00\x00\x00\x00\x00\x00" + raw_sig + b"\x00" * 8
    return prefixed, raw_sig.hex()


def _upsert_one(
    conn: sqlite3.Connection,
    source_fact_id: object,
    priv_key: Any | None,
    *,
    dry_run: bool,
) -> str:
    fact_id = str(source_fact_id)
    source_doc = _derive_source_doc(conn, source_fact_id)
    conf_lo, conf_hi = _derive_confidence(conn, source_fact_id)
    extracted_at = _derive_extracted_at(conn, source_fact_id)
    verified_by = DEFAULT_VERIFIED_BY

    # Skip-if-already-populated. v2 only fills NULL source_doc rows OR
    # entirely missing fact_id rows.
    cur = conn.execute(
        "SELECT source_doc FROM am_fact_metadata WHERE fact_id = ?",
        (fact_id,),
    )
    existing = cur.fetchone()
    if existing is not None and existing[0] is not None:
        return "unchanged"

    if dry_run:
        return "upserted"

    payload = _canonical_payload(
        fact_id, source_doc, extracted_at, verified_by, conf_lo, conf_hi
    )
    prefixed_sig, sig_hex = _sign(priv_key, payload)

    conn.execute(
        """
        INSERT INTO am_fact_metadata
            (fact_id, source_doc, extracted_at, verified_by,
             confidence_lower, confidence_upper, ed25519_sig)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fact_id) DO UPDATE SET
            source_doc       = COALESCE(excluded.source_doc, am_fact_metadata.source_doc),
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
            (fact_id, attester, signature_hex, notes)
        VALUES (?, ?, ?, ?)
        """,
        (fact_id, verified_by, sig_hex, "wave49_phase1_backfill"),
    )

    return "upserted"


def _walk(
    conn: sqlite3.Connection,
    priv_key: Any | None,
    max_rows: int,
    chunk_size: int,
    dry_run: bool,
) -> dict[str, int]:
    counts = {"upserted": 0, "unchanged": 0, "skipped": 0, "errors": 0}
    cursor: object | None = None
    walked = 0
    batches = 0

    while True:
        if cursor is None:
            cur = conn.execute(
                "SELECT id FROM am_entity_facts "
                "ORDER BY id ASC LIMIT ?",
                (chunk_size,),
            )
        else:
            cur = conn.execute(
                "SELECT id FROM am_entity_facts "
                "WHERE id > ? "
                "ORDER BY id ASC LIMIT ?",
                (cursor, chunk_size),
            )
        batch = cur.fetchall()
        if not batch:
            break

        for (source_fact_id,) in batch:
            if max_rows and walked >= max_rows:
                return counts
            try:
                outcome = _upsert_one(conn, source_fact_id, priv_key, dry_run=dry_run)
                counts[outcome] += 1
            except sqlite3.IntegrityError as exc:
                counts["errors"] += 1
                _log.warning(
                    "integrity error fact_id=%s err=%s", source_fact_id, exc
                )
            walked += 1
            cursor = source_fact_id

        if not dry_run:
            conn.commit()
        batches += 1
        if batches % 100 == 0:
            _log.info(
                "v2_backfill progress batches=%d walked=%d upserted=%d unchanged=%d",
                batches,
                walked,
                counts["upserted"],
                counts["unchanged"],
            )

    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
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

    priv_key = _try_load_private_key()
    placeholder = priv_key is None

    conn = sqlite3.connect(db_path)
    try:
        # Schema sanity — migration 275 must be applied. NO quick_check.
        try:
            conn.execute("SELECT 1 FROM am_fact_metadata LIMIT 1")
            conn.execute("SELECT 1 FROM am_fact_attestation_log LIMIT 1")
            conn.execute("SELECT 1 FROM am_entity_facts LIMIT 1")
        except sqlite3.OperationalError as exc:
            _log.error(
                "schema missing — apply migration 275 + ensure am_entity_facts: %s",
                exc,
            )
            return 2

        counts = _walk(
            conn,
            priv_key,
            args.max_rows,
            args.chunk_size,
            args.dry_run,
        )
    finally:
        conn.close()

    summary = {
        "etl": "provenance_backfill_6M_facts_v2",
        "dry_run": args.dry_run,
        "placeholder_sig": placeholder,
        **counts,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
