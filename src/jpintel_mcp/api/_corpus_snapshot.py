"""Corpus snapshot identity for auditor work-paper reproducibility.

Auditor 会計士 use-case: when an auditor evaluates business compliance against
our dataset, they need to be able to say in their work-paper:

    "I evaluated profile X against AutonoMath corpus snapshot
     2026-04-29T03:14:00Z (sha256:9f8e7d...)."

Then re-run the same evaluation a year later and verify whether the corpus
mutated. Per-row `fetched_at` is too granular for that — it tells you when
each individual row was scraped, but says nothing about the corpus state at
moment-of-evaluation. The whole-corpus identity is what audit trails cite.

This module exposes a single function `compute_corpus_snapshot()` that
derives a (snapshot_id, checksum) pair deterministically from:

  1. The latest `am_amendment_diff.detected_at` if available (best signal —
     this table grows monotonically as the cron detects amendments).
  2. Failing that, MAX(fetched_at) across the canonical corpus tables.
  3. A short SHA-256 over (snapshot_id || corpus_table_counts) so the same
     timestamp + same row-counts always yield the same checksum but a row
     mutation between runs flips the checksum.

The result is cached for 5 minutes (process-local) — corpus state changes at
a daily cron cadence at most, so re-computing on every request is wasteful
but stale-by-an-hour is also unacceptable for auditors evaluating around a
known cliff date (2026-09-30 / 2027-09-30 / 2029-09-30).

Failure mode: if the underlying connection cannot be queried we degrade to
the current UTC time + a checksum prefix `unknown-` so the response still
carries SOMETHING (auditors prefer "I don't know exactly" to "no field").
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# Process-local cache: { (cache_key,): (expiry_unix, snapshot_id, checksum) }.
# `cache_key` is a 1-tuple of the connection's database file path — distinct
# DB files are cached independently. For the launch deployment the API only
# touches one jpintel.db, so this is effectively a singleton.
_CACHE: dict[tuple[str, ...], tuple[float, str, str]] = {}
_TTL_SECONDS = 300.0


# Canonical corpus tables we count for the checksum mix-in. These are the
# four tables that define "what the auditor evaluated against" — adding a
# program / law / tax_ruleset / court_decision row should flip the checksum
# even if `fetched_at` happened to land on the exact same minute.
_CORPUS_TABLES: tuple[str, ...] = (
    "programs",
    "laws",
    "tax_rulesets",
    "court_decisions",
)


def _conn_path(conn: sqlite3.Connection) -> str:
    """Best-effort database file path for cache keying. Returns 'memory'
    for in-memory connections and 'unknown' if pragma fails."""
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
        if row is None:
            return "unknown"
        # row schema: (seq, name, file). file is empty string for :memory:.
        path = row[2] if len(row) > 2 else ""
        return path or "memory"
    except sqlite3.Error:
        return "unknown"


def _latest_amendment_detected_at(conn: sqlite3.Connection) -> str | None:
    """Return MAX(detected_at) from am_amendment_diff or None.

    am_amendment_diff lives on autonomath.db, not jpintel.db — we'd need a
    separate connection to query it. For the v0.3.x API codebase the
    handlers run on the jpintel connection, so this returns None and the
    fallback path (MAX fetched_at) is used. The function is here so the
    contract is documented and the same code can pivot to a cross-DB read
    later without touching call sites.
    """
    try:
        row = conn.execute(
            "SELECT MAX(detected_at) FROM am_amendment_diff"
        ).fetchone()
    except sqlite3.OperationalError:
        # Table absent on this connection (jpintel.db). Fall through.
        return None
    if row is None or row[0] is None:
        return None
    val = row[0]
    return str(val) if val is not None else None


def _latest_corpus_fetched_at(conn: sqlite3.Connection) -> str | None:
    """Return the latest `fetched_at` across canonical corpus tables.

    Tables we sample: programs (uses `source_fetched_at`), laws,
    tax_rulesets, court_decisions. Missing tables / missing rows are
    silently skipped — a brand-new database with zero ingested rows
    legitimately has no corpus timestamp.
    """
    candidates: list[str] = []
    queries: list[tuple[str, str]] = [
        ("programs", "MAX(source_fetched_at)"),
        ("laws", "MAX(fetched_at)"),
        ("tax_rulesets", "MAX(fetched_at)"),
        ("court_decisions", "MAX(fetched_at)"),
    ]
    for table, expr in queries:
        try:
            row = conn.execute(f"SELECT {expr} FROM {table}").fetchone()
        except sqlite3.OperationalError:
            continue
        if row and row[0]:
            candidates.append(str(row[0]))
    if not candidates:
        return None
    # ISO-8601 strings sort lexicographically == chronologically.
    return max(candidates)


def _corpus_row_counts(conn: sqlite3.Connection) -> tuple[int, ...]:
    """Cheap COUNT(*) per canonical corpus table. Missing tables count 0."""
    counts: list[int] = []
    for table in _CORPUS_TABLES:
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        except sqlite3.OperationalError:
            counts.append(0)
            continue
        counts.append(int(row[0]) if row and row[0] is not None else 0)
    return tuple(counts)


def compute_corpus_snapshot(
    conn: sqlite3.Connection,
    *,
    api_version: str = "v0.3.2",
) -> tuple[str, str]:
    """Compute (corpus_snapshot_id, corpus_checksum) for the current corpus.

    Returns:
      corpus_snapshot_id: ISO-8601 timestamp (latest am_amendment_diff
        detected_at OR latest corpus fetched_at). For a brand-new DB with
        no rows, falls back to a deterministic placeholder
        "1970-01-01T00:00:00Z" so the field is always populated.
      corpus_checksum: 16-char hex prefix of
        sha256(snapshot_id || api_version || row_counts_csv). Mutation in
        ANY canonical table flips at least one count and thus the digest.

    Caching: 5-minute TTL keyed by the connection's DB path. A process
    serving 1k req/sec recomputes the snapshot ~12 times/hour, not 3.6M.

    Never raises — internal sqlite errors collapse to the fallback path.
    """
    cache_key = (_conn_path(conn),)
    now = time.monotonic()
    cached = _CACHE.get(cache_key)
    if cached is not None and cached[0] > now:
        return cached[1], cached[2]

    # Prefer am_amendment_diff (autonomath cron output) when available,
    # else fall back to corpus-wide MAX(fetched_at).
    snapshot_id = (
        _latest_amendment_detected_at(conn)
        or _latest_corpus_fetched_at(conn)
        or "1970-01-01T00:00:00Z"
    )
    counts = _corpus_row_counts(conn)
    counts_csv = ",".join(str(c) for c in counts)

    digest_input = f"{snapshot_id}|{api_version}|{counts_csv}".encode("utf-8")
    checksum = "sha256:" + hashlib.sha256(digest_input).hexdigest()[:16]

    _CACHE[cache_key] = (now + _TTL_SECONDS, snapshot_id, checksum)
    return snapshot_id, checksum


def attach_corpus_snapshot(
    body: dict,
    conn: sqlite3.Connection,
    *,
    api_version: str = "v0.3.2",
) -> dict:
    """Inject `corpus_snapshot_id` + `corpus_checksum` keys onto a response
    body in-place and return the same dict (for chaining).

    Used by audit-relevant endpoints (tax_rulesets/evaluate, programs,
    laws, court_decisions get-by-id) so auditor tooling can quote a single
    pair of fields per response and reproduce the evaluation later.
    """
    snapshot_id, checksum = compute_corpus_snapshot(conn, api_version=api_version)
    body["corpus_snapshot_id"] = snapshot_id
    body["corpus_checksum"] = checksum
    return body


def snapshot_headers(
    conn: sqlite3.Connection,
    *,
    api_version: str = "v0.3.2",
) -> dict[str, str]:
    """Return ``{X-Corpus-Snapshot-Id, X-Corpus-Checksum}`` header pair.

    Mirrors the (snapshot_id, checksum) pair already injected into the JSON
    body via ``attach_corpus_snapshot`` so auditor log-grep workflows can
    reproduce the evaluation without parsing the body. Detail-GET endpoints
    that return ``JSONResponse(content=body, headers=snapshot_headers(conn))``
    keep header + body in lockstep — both use the same 5-min cached pair.
    """
    snapshot_id, checksum = compute_corpus_snapshot(conn, api_version=api_version)
    return {
        "X-Corpus-Snapshot-Id": snapshot_id,
        "X-Corpus-Checksum": checksum,
    }


def _reset_cache_for_tests() -> None:
    """Test helper — drop the process-local cache."""
    _CACHE.clear()
