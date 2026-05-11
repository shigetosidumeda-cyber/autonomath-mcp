"""Weekly Ed25519 re-sign cron for the per-fact verification trail.

Wave 43.2.5 — Dim E Verification trail
======================================

Walks `extracted_fact` rows that are either:
  (1) new since the last cron tick (no row in am_fact_signature), or
  (2) amended since the last sign (extracted_fact.last_modified >
      am_fact_signature.signed_at)

…and produces a fresh Ed25519 signature over the canonical fact
payload. The signature is UPSERTed into `am_fact_signature` along
with the current `corpus_snapshot_id`.

Design constraints
------------------
* **NO LLM call.** Sign is pure cryptography stdlib (Ed25519). No
  Anthropic / OpenAI / Gemini / Stripe / external HTTP. The
  AUTONOMATH_FACT_SIGN_PRIVATE_KEY (32-byte hex Ed25519 seed) lives
  in Fly secret only.
* **9.7 GB autonomath.db full-scan footgun.** Per
  feedback_no_quick_check_on_huge_sqlite memory: we chunk the
  walk in 50,000-row batches with an indexed predicate (fact_id >
  $cursor) so no single SELECT pulls the entire 6.12M-row
  extracted_fact heap into memory. Each batch commits independently
  so a mid-run interrupt resumes cleanly on the next cron tick.
* **Idempotent.** Re-running the cron on a converged corpus produces
  zero writes. The (extracted_fact.last_modified >
  am_fact_signature.signed_at) predicate ensures only truly-changed
  rows are re-signed.

Operational hook
----------------
Schedule via .github/workflows/refresh-fact-signatures-weekly.yml at
Sunday 02:00 UTC (Monday 11:00 JST). On each tick:
  python scripts/cron/refresh_fact_signatures_weekly.py
       [--max-rows N] [--dry-run]

Exit code 0 on success, 1 on key resolution failure, 2 on DB I/O
failure. Stdout emits a one-line JSON summary for log aggregation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
from typing import Any

_log = logging.getLogger("jpcite.cron.refresh_fact_signatures")

CHUNK_SIZE = 50_000  # rows per indexed batch — see "9.7 GB footgun" note above
DEFAULT_KEY_ID = "k20260512_a"


def _resolve_db_path() -> str:
    """Resolve autonomath.db path from env or config default."""
    explicit = os.environ.get("AUTONOMATH_DB_PATH")
    if explicit:
        return explicit
    cwd = os.getcwd()
    candidate = os.path.join(cwd, "autonomath.db")
    if os.path.exists(candidate):
        return candidate
    return os.path.join(cwd, "data", "autonomath.db")


def _load_private_key() -> Any:
    """Resolve Ed25519 private key from env.

    Returns the cryptography Ed25519PrivateKey instance, or raises
    SystemExit(1) if not configured / invalid.
    """
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
            "AUTONOMATH_FACT_SIGN_PRIVATE_KEY must be 32 raw bytes "
            "(hex-encoded); got len=%d",
            len(seed),
        )
        sys.exit(1)

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
    except ImportError:
        _log.error("cryptography package not installed; cannot sign")
        sys.exit(1)

    return Ed25519PrivateKey.from_private_bytes(seed)


def _canonical_payload(
    fact_row: sqlite3.Row, snapshot_id: str | None
) -> bytes:
    """Canonical signing payload — MUST match api/fact_verify.py exactly.

    Any divergence between signer and verifier yields 409 on every
    legitimate fact. Keep the field ordering and JSON serializer
    settings in lockstep with `_canonical_payload` in fact_verify.py.
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
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _current_snapshot_id(conn: sqlite3.Connection) -> str | None:
    """Latest corpus_snapshot_id from corpus_snapshot table.

    Returns None when the snapshot table is empty (early-deployment
    state). The sign still proceeds with NULL snapshot binding.
    """
    try:
        row = conn.execute(
            "SELECT snapshot_id FROM corpus_snapshot "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return row["snapshot_id"] if row else None
    except sqlite3.OperationalError:
        return None


def _walk_pending_facts(
    conn: sqlite3.Connection, max_rows: int | None
) -> list[sqlite3.Row]:
    """Indexed walk of facts needing fresh signatures.

    Predicates:
      LEFT JOIN am_fact_signature ON fact_id
      WHERE signature missing OR signed_at < (proxy for last_modified)

    Uses fact_id range cursor + LIMIT CHUNK_SIZE so we never pull the
    full 6.12M-row heap. Caller iterates this once per cron tick;
    `--max-rows` lets ops cap a single run to avoid Fly machine memory
    pressure.
    """
    pending: list[sqlite3.Row] = []
    cursor = ""
    while True:
        batch = conn.execute(
            "SELECT f.fact_id, f.subject_kind, f.subject_id, "
            "f.field_name, f.field_kind, f.value_text, f.value_number, "
            "f.value_date, f.source_document_id, f.last_modified "
            "FROM extracted_fact f "
            "LEFT JOIN am_fact_signature s ON s.fact_id = f.fact_id "
            "WHERE f.fact_id > ? "
            "  AND ("
            "    s.fact_id IS NULL "
            "    OR (f.last_modified IS NOT NULL "
            "        AND f.last_modified > s.signed_at)"
            "  ) "
            "ORDER BY f.fact_id ASC LIMIT ?",
            (cursor, CHUNK_SIZE),
        ).fetchall()
        if not batch:
            break
        pending.extend(batch)
        cursor = batch[-1]["fact_id"]
        if max_rows is not None and len(pending) >= max_rows:
            return pending[:max_rows]
    return pending


def _sign_and_upsert(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    private_key: Any,
    snapshot_id: str | None,
    key_id: str,
    dry_run: bool,
) -> int:
    """Sign each row and UPSERT into am_fact_signature.

    Returns the count of rows successfully signed. Commit happens
    in CHUNK_SIZE batches so a mid-run interrupt resumes cleanly.
    """
    signed = 0
    batch_buffer: list[tuple[str, bytes, str | None, str, str]] = []
    for row in rows:
        payload = _canonical_payload(row, snapshot_id)
        payload_hash = hashlib.sha256(payload).hexdigest()
        sig_core = private_key.sign(payload)  # 64 bytes
        version_prefix = b"AMFSv1\x00\x00"  # 8 bytes
        key_suffix = key_id.encode("ascii")[:8].ljust(8, b"\x00")
        framed_sig = version_prefix + sig_core + key_suffix  # 80 bytes
        batch_buffer.append((
            row["fact_id"],
            framed_sig,
            snapshot_id,
            key_id,
            payload_hash,
        ))
        if len(batch_buffer) >= 5_000:
            if not dry_run:
                conn.executemany(
                    "INSERT INTO am_fact_signature "
                    "(fact_id, ed25519_sig, corpus_snapshot_id, "
                    " key_id, signed_at, payload_sha256) "
                    "VALUES (?, ?, ?, ?, "
                    "        strftime('%Y-%m-%dT%H:%M:%fZ','now'), ?) "
                    "ON CONFLICT(fact_id) DO UPDATE SET "
                    "  ed25519_sig=excluded.ed25519_sig, "
                    "  corpus_snapshot_id=excluded.corpus_snapshot_id, "
                    "  key_id=excluded.key_id, "
                    "  signed_at=excluded.signed_at, "
                    "  payload_sha256=excluded.payload_sha256",
                    batch_buffer,
                )
                conn.commit()
            signed += len(batch_buffer)
            batch_buffer.clear()

    if batch_buffer:
        if not dry_run:
            conn.executemany(
                "INSERT INTO am_fact_signature "
                "(fact_id, ed25519_sig, corpus_snapshot_id, "
                " key_id, signed_at, payload_sha256) "
                "VALUES (?, ?, ?, ?, "
                "        strftime('%Y-%m-%dT%H:%M:%fZ','now'), ?) "
                "ON CONFLICT(fact_id) DO UPDATE SET "
                "  ed25519_sig=excluded.ed25519_sig, "
                "  corpus_snapshot_id=excluded.corpus_snapshot_id, "
                "  key_id=excluded.key_id, "
                "  signed_at=excluded.signed_at, "
                "  payload_sha256=excluded.payload_sha256",
                batch_buffer,
            )
            conn.commit()
        signed += len(batch_buffer)

    return signed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Weekly Ed25519 re-sign of extracted_fact rows"
    )
    parser.add_argument(
        "--max-rows", type=int, default=None,
        help="cap a single run; None = sign all pending",
    )
    parser.add_argument(
        "--key-id", default=DEFAULT_KEY_ID,
        help=f"key rotation identifier (default {DEFAULT_KEY_ID})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="walk + sign but do not write am_fact_signature",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="emit DEBUG-level log lines",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db_path = _resolve_db_path()
    if not os.path.exists(db_path):
        _log.error("autonomath.db not found at %s", db_path)
        return 2

    private_key = _load_private_key()

    started = time.monotonic()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        snapshot_id = _current_snapshot_id(conn)
        _log.info(
            "weekly fact-signature refresh start db=%s snapshot=%s "
            "key_id=%s dry_run=%s",
            db_path, snapshot_id, args.key_id, args.dry_run,
        )

        pending = _walk_pending_facts(conn, args.max_rows)
        _log.info("pending facts needing (re)signature: %d", len(pending))

        if not pending:
            elapsed = time.monotonic() - started
            print(json.dumps({
                "status": "ok",
                "signed": 0,
                "pending": 0,
                "snapshot_id": snapshot_id,
                "elapsed_s": round(elapsed, 3),
                "dry_run": args.dry_run,
            }))
            return 0

        signed = _sign_and_upsert(
            conn, pending, private_key, snapshot_id, args.key_id, args.dry_run
        )
        elapsed = time.monotonic() - started
        _log.info(
            "weekly fact-signature refresh done signed=%d elapsed=%.3fs",
            signed, elapsed,
        )
        print(json.dumps({
            "status": "ok",
            "signed": signed,
            "pending": len(pending),
            "snapshot_id": snapshot_id,
            "elapsed_s": round(elapsed, 3),
            "dry_run": args.dry_run,
        }))
        return 0
    except sqlite3.Error as exc:
        _log.exception("sqlite I/O error: %s", exc)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
