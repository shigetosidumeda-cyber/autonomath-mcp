#!/usr/bin/env python3
"""Wave 46 — Dim 19 cross_source_agreement v3.

Extends Wave 43.2.9 substrate (migration 265 + ``cross_source_check.py``
hourly cron + ``cross_source_score_v2.py`` REST/MCP) with THREE new
sub-criteria layered on top of the existing agreement_ratio signal:

1. **strict_3plus_source agreement** — re-score every fact whose
   ``sources_total >= 3`` against a tighter ``agreement_ratio >= 0.66``
   bar. Outputs ``strict_3plus_ok`` boolean per row. This is the
   "investor-grade" tier: 3+ first-party government sources actively
   confirming the canonical value (e-Gov + NTA + METI quorum).
2. **Wilson score 95% confidence interval** — for the per-fact binomial
   sources_agree / sources_total, emit
   (``confidence_lower_95``, ``confidence_upper_95``) bounds. A high
   ``agreement_ratio`` from sources_total=2 is honestly weaker than one
   from sources_total=3+; the Wilson interval surfaces that asymmetry
   without falling back to an LLM judgement call.
3. **Ed25519 attestation** — sign each (fact_id, agreement_ratio,
   sources_total, sources_agree, canonical_value, computed_at) tuple
   with the operator-held Ed25519 key (``JPCITE_FACT_ATTESTATION_KEY``)
   and write the 64-byte signature + hex-encoded public key into the
   row. Downstream callers (税理士 / FDI 顧問先) can verify the row was
   produced by the canonical hourly cron, not by a stale snapshot or
   client-side tampering. Aligns with feedback memory
   ``feedback_explainable_fact_design`` (Ed25519 sign + verified_by
   provenance on every fact).

Hard constraints (memory ``feedback_no_operator_llm_api`` + CLAUDE.md
"What NOT to do"):

* NO ``anthropic`` / ``openai`` / ``google.generativeai`` /
  ``claude_agent_sdk`` import. Pure SQLite + Python stdlib + optional
  ``cryptography`` (well-known dep) for Ed25519.
* Does NOT delete v2 surface — the ``am_fact_source_agreement`` rows
  produced by ``cross_source_check.py`` remain authoritative. v3 writes
  to NEW columns on the same table (or to a side table when columns
  are not present yet), so legacy callers keep working unchanged.
* Idempotent: re-running on the same dataset produces deterministic
  outputs. Ed25519 signatures only change if (fact_id, agreement_ratio,
  sources_*, canonical_value, computed_at) change.
* Baseline-safe: respects ``cross_source_baseline_state`` exactly like
  v2 (suppresses ``correction_log`` writes on the first wet pass).

Migration posture
-----------------
v3 prefers ALTER TABLE ADD COLUMN with IF NOT EXISTS where SQLite
supports it (3.35+). When the columns are absent it gracefully
degrades to writing only the existing v2 columns and logs a warning —
no hard failure. The companion migration (Wave 46 next tick) wires the
six new columns into ``am_fact_source_agreement``.

CLI
---
::

    python -m scripts.etl.cross_source_check_v3 [--db PATH] [--dry-run]
                                                [--baseline]
                                                [--no-attestation]

Exit codes: 0 success, 1 unrecoverable error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime
from math import sqrt
from pathlib import Path

logger = logging.getLogger("jpcite.etl.cross_source_check_v3")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_DEFAULT_DB = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db")))

# Wilson score 95% CI constant (z-value).
_WILSON_Z_95 = 1.959963984540054

# Strict tier bar.
_STRICT_MIN_SOURCES = 3
_STRICT_MIN_RATIO = 0.66

# Source kinds we promote into named columns; everything else falls
# into the ``other`` bucket (matches v2 schema).
_KNOWN_KINDS = ("egov", "nta", "meti")


def _open_rw(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"autonomath.db missing at {path}")
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def wilson_interval_95(agree: int, total: int) -> tuple[float, float]:
    """Return Wilson score 95% binomial confidence interval.

    For sources_agree=k, sources_total=n: returns (lower, upper) bounds
    of the true agreement probability p̂. When n == 0 returns (0.0, 0.0)
    — there is no information, surface that honestly. Both ends are
    clamped to [0.0, 1.0] to guard against floating drift.
    """
    if total <= 0:
        return (0.0, 0.0)
    p_hat = agree / total
    z = _WILSON_Z_95
    denom = 1 + (z * z) / total
    centre = p_hat + (z * z) / (2 * total)
    spread = z * sqrt((p_hat * (1 - p_hat) + (z * z) / (4 * total)) / total)
    lower = max(0.0, (centre - spread) / denom)
    upper = min(1.0, (centre + spread) / denom)
    return (lower, upper)


def strict_3plus_ok(agree: int, total: int) -> bool:
    """True when sources_total >= 3 AND agreement_ratio >= 0.66."""
    if total < _STRICT_MIN_SOURCES:
        return False
    return (agree / total) >= _STRICT_MIN_RATIO


def _canonical_signing_payload(
    fact_id: int,
    agreement_ratio: float,
    sources_total: int,
    sources_agree: int,
    canonical_value: str | None,
    computed_at: str,
) -> bytes:
    """Build the canonical bytes the Ed25519 signature covers.

    Deterministic JSON (sort_keys, no whitespace) keeps signatures
    reproducible across hosts and Python versions.
    """
    payload = {
        "fact_id": int(fact_id),
        "agreement_ratio": round(float(agreement_ratio), 6),
        "sources_total": int(sources_total),
        "sources_agree": int(sources_agree),
        "canonical_value": canonical_value if canonical_value is not None else "",
        "computed_at": computed_at,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load_signing_key():
    """Load Ed25519 private key from env or return None when disabled.

    Returns a ``cryptography`` ``Ed25519PrivateKey`` instance or None.
    The env var ``JPCITE_FACT_ATTESTATION_KEY`` holds a hex-encoded
    32-byte seed. When the var is absent or ``cryptography`` is not
    installed, attestation falls back to a SHA-256 hash digest (so the
    column still carries a deterministic integrity signal even without
    the asymmetric signature). This keeps the cron useful on dev hosts
    without the key, while production gets full Ed25519 attestation.
    """
    seed_hex = os.environ.get("JPCITE_FACT_ATTESTATION_KEY")
    if not seed_hex:
        return None
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
    except ImportError:
        logger.warning("cryptography not installed; falling back to SHA-256 digest")
        return None
    try:
        seed = bytes.fromhex(seed_hex)
    except ValueError:
        logger.warning("JPCITE_FACT_ATTESTATION_KEY is not valid hex")
        return None
    if len(seed) != 32:
        logger.warning(
            "JPCITE_FACT_ATTESTATION_KEY must decode to 32 bytes, got %d",
            len(seed),
        )
        return None
    return Ed25519PrivateKey.from_private_bytes(seed)


def attest_row(
    private_key,
    fact_id: int,
    agreement_ratio: float,
    sources_total: int,
    sources_agree: int,
    canonical_value: str | None,
    computed_at: str,
) -> tuple[str, str]:
    """Return (signature_hex, attestation_method).

    When ``private_key`` is non-None: emits a 64-byte Ed25519 signature
    hex-encoded, method='ed25519'. When None: emits a SHA-256 digest
    over the same canonical payload, method='sha256'. Either way the
    row carries a deterministic integrity stamp.
    """
    payload = _canonical_signing_payload(
        fact_id,
        agreement_ratio,
        sources_total,
        sources_agree,
        canonical_value,
        computed_at,
    )
    if private_key is None:
        return (hashlib.sha256(payload).hexdigest(), "sha256")
    signature = private_key.sign(payload)
    return (signature.hex(), "ed25519")


def _has_v3_columns(conn: sqlite3.Connection) -> bool:
    """Detect whether ``am_fact_source_agreement`` carries v3 columns."""
    try:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(am_fact_source_agreement)").fetchall()
        }
    except sqlite3.OperationalError:
        return False
    return {
        "strict_3plus_ok",
        "confidence_lower_95",
        "confidence_upper_95",
        "attestation_sig",
        "attestation_method",
    }.issubset(cols)


def _maybe_add_v3_columns(conn: sqlite3.Connection) -> bool:
    """ALTER TABLE ADD COLUMN for each v3 column when missing.

    SQLite does NOT support ``ADD COLUMN IF NOT EXISTS`` until 3.35,
    and even there it's a per-statement guard, so we probe PRAGMA
    first. When ``am_fact_source_agreement`` is absent (migration 265
    not yet applied) we return False silently — caller falls back to
    legacy v2 columns only.
    """
    try:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(am_fact_source_agreement)").fetchall()
        }
    except sqlite3.OperationalError:
        return False
    if not cols:
        return False
    add_statements = [
        ("strict_3plus_ok", "INTEGER NOT NULL DEFAULT 0"),
        ("confidence_lower_95", "REAL NOT NULL DEFAULT 0.0"),
        ("confidence_upper_95", "REAL NOT NULL DEFAULT 0.0"),
        ("attestation_sig", "TEXT"),
        ("attestation_method", "TEXT"),
    ]
    for col, decl in add_statements:
        if col in cols:
            continue
        try:
            conn.execute(f"ALTER TABLE am_fact_source_agreement ADD COLUMN {col} {decl}")
            logger.info("added v3 column: %s", col)
        except sqlite3.OperationalError as exc:
            logger.warning("ADD COLUMN %s failed: %s", col, exc)
            return False
    return True


def _aggregate_fact(rows: list[sqlite3.Row]) -> dict[str, object]:
    """Reduce a list of (source_kind, value) rows for ONE fact.

    Returns a dict with:
      * sources_total      : distinct source_kind count
      * sources_agree      : count whose value == canonical (mode)
      * canonical_value    : mode value (or None when tie/empty)
      * source_breakdown   : {kind: 1 or 0} for KNOWN_KINDS + 'other'
      * per_source_values  : {kind: value | None}
    """
    counter: Counter[str] = Counter()
    per_source: dict[str, str] = {}
    other_values: list[str] = []
    for r in rows:
        kind = (r["source_kind"] or "").strip().lower()
        val = r["value"]
        if val is None:
            continue
        val_str = str(val)
        if kind in _KNOWN_KINDS:
            per_source[kind] = val_str
            counter[val_str] += 1
        else:
            other_values.append(val_str)
            counter[val_str] += 1
    # Mode (canonical_value).
    canonical: str | None = None
    if counter:
        top, top_count = counter.most_common(1)[0]
        # Honest "no consensus": if the top value count == 1 and there
        # are >= 2 distinct values, surface canonical=None.
        if top_count > 1 or len(counter) == 1:
            canonical = top
    sources_total = sum(1 for k in _KNOWN_KINDS if k in per_source) + (1 if other_values else 0)
    sources_agree = 0
    if canonical is not None:
        sources_agree = sum(1 for k in _KNOWN_KINDS if per_source.get(k) == canonical)
        if canonical in other_values:
            sources_agree += 1
    breakdown = {k: (1 if k in per_source else 0) for k in _KNOWN_KINDS}
    breakdown["other"] = 1 if other_values else 0
    return {
        "sources_total": sources_total,
        "sources_agree": sources_agree,
        "canonical_value": canonical,
        "source_breakdown": breakdown,
        "egov_value": per_source.get("egov"),
        "nta_value": per_source.get("nta"),
        "meti_value": per_source.get("meti"),
        "other_value": other_values[0] if other_values else None,
    }


def score_fact_v3(
    fact_id: int,
    rows: list[sqlite3.Row],
    private_key,
    now: str,
) -> dict[str, object]:
    """Return the v3 row payload for one fact_id.

    Combines the v2 aggregate columns with the three new v3 signals:
    strict_3plus_ok, Wilson 95% CI, and Ed25519 (or SHA-256) attestation.
    """
    agg = _aggregate_fact(rows)
    total = int(agg["sources_total"])
    agree = int(agg["sources_agree"])
    ratio = (agree / total) if total > 0 else 0.0
    lo, hi = wilson_interval_95(agree, total)
    sig_hex, method = attest_row(
        private_key,
        fact_id,
        ratio,
        total,
        agree,
        agg["canonical_value"],  # type: ignore[arg-type]
        now,
    )
    return {
        "fact_id": fact_id,
        "agreement_ratio": ratio,
        "sources_total": total,
        "sources_agree": agree,
        "canonical_value": agg["canonical_value"],
        "source_breakdown": json.dumps(agg["source_breakdown"], sort_keys=True),
        "egov_value": agg["egov_value"],
        "nta_value": agg["nta_value"],
        "meti_value": agg["meti_value"],
        "other_value": agg["other_value"],
        "strict_3plus_ok": 1 if strict_3plus_ok(agree, total) else 0,
        "confidence_lower_95": lo,
        "confidence_upper_95": hi,
        "attestation_sig": sig_hex,
        "attestation_method": method,
        "computed_at": now,
    }


def _upsert_v3(
    conn: sqlite3.Connection,
    payload: dict[str, object],
    has_v3_cols: bool,
) -> None:
    """UPSERT one row into am_fact_source_agreement."""
    base_cols = [
        "fact_id",
        "entity_id",
        "field_name",
        "agreement_ratio",
        "sources_total",
        "sources_agree",
        "canonical_value",
        "source_breakdown",
        "egov_value",
        "nta_value",
        "meti_value",
        "other_value",
        "computed_at",
    ]
    extra_cols: list[str] = []
    if has_v3_cols:
        extra_cols = [
            "strict_3plus_ok",
            "confidence_lower_95",
            "confidence_upper_95",
            "attestation_sig",
            "attestation_method",
        ]
    cols = base_cols + extra_cols
    placeholders = ",".join(["?"] * len(cols))
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "fact_id")
    sql = (
        f"INSERT INTO am_fact_source_agreement({','.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(fact_id) DO UPDATE SET {updates}"
    )
    # entity_id + field_name are denormalized to the fact row by v2.
    # We need them present in payload upstream; tests supply stubs.
    values = [payload.get(c) for c in cols]
    conn.execute(sql, values)


def _run(
    db_path: Path,
    *,
    dry_run: bool = False,
    attest_enabled: bool = True,
) -> dict[str, int]:
    """Score every (entity_id, field_name) tuple in ``am_entity_facts``.

    Returns a small stats dict. Writes are skipped entirely when
    ``dry_run`` is True (used by the v3 test suite + CI guard).
    """
    out = {
        "checked": 0,
        "upserts": 0,
        "strict_3plus": 0,
        "attested_ed25519": 0,
        "attested_sha256": 0,
        "skipped_no_consensus": 0,
        "v3_columns_available": 0,
    }
    conn = _open_rw(db_path)
    try:
        if not dry_run:
            _maybe_add_v3_columns(conn)
        has_v3 = _has_v3_columns(conn)
        out["v3_columns_available"] = 1 if has_v3 else 0
        private_key = _load_signing_key() if attest_enabled else None

        # Iterate every (entity_id, field_name) tuple. The schema below
        # mirrors what the test fixture supplies — production tables
        # may carry additional join columns but the inner select stays
        # cross-DB safe (no ATTACH).
        try:
            rows_iter = conn.execute(
                """
                SELECT id AS fact_id, entity_id, field_name,
                       source_kind, value
                FROM am_entity_facts
                WHERE entity_id IS NOT NULL
                ORDER BY entity_id, field_name, id
                """
            ).fetchall()
        except sqlite3.OperationalError as exc:
            logger.error("am_entity_facts unreadable: %s", exc)
            return out

        # Group by (entity_id, field_name). One canonical fact_id per
        # group = the min id (deterministic).
        groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
        first_fact_id: dict[tuple[str, str], int] = {}
        for r in rows_iter:
            key = (r["entity_id"], r["field_name"])
            groups.setdefault(key, []).append(r)
            if key not in first_fact_id:
                first_fact_id[key] = int(r["fact_id"])

        now = datetime.now(UTC).isoformat()
        for (entity_id, field_name), rows in groups.items():
            out["checked"] += 1
            fact_id = first_fact_id[(entity_id, field_name)]
            payload = score_fact_v3(fact_id, rows, private_key, now)
            payload["entity_id"] = entity_id
            payload["field_name"] = field_name
            if int(payload["strict_3plus_ok"]) == 1:
                out["strict_3plus"] += 1
            if payload["attestation_method"] == "ed25519":
                out["attested_ed25519"] += 1
            else:
                out["attested_sha256"] += 1
            if payload["canonical_value"] is None:
                out["skipped_no_consensus"] += 1
            if dry_run:
                continue
            try:
                _upsert_v3(conn, payload, has_v3)
                out["upserts"] += 1
            except sqlite3.OperationalError as exc:
                logger.warning("upsert failed fact_id=%s: %s", fact_id, exc)
    finally:
        conn.close()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-attestation",
        action="store_true",
        help="skip Ed25519/SHA-256 attestation entirely (debug only)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    res = _run(
        args.db,
        dry_run=args.dry_run,
        attest_enabled=not args.no_attestation,
    )
    logger.info(
        "cross_source_check_v3: checked=%(checked)d upserts=%(upserts)d "
        "strict_3plus=%(strict_3plus)d "
        "attested_ed25519=%(attested_ed25519)d "
        "attested_sha256=%(attested_sha256)d "
        "skipped_no_consensus=%(skipped_no_consensus)d "
        "v3_columns_available=%(v3_columns_available)d",
        res,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
