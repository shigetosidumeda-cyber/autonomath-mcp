#!/usr/bin/env python3
"""Daily eligibility-history rebuild for tier S/A programs.

MASTER_PLAN_v1 章 3 §D1 (b) implementation.

Why this exists
---------------
The existing `am_amendment_snapshot` corpus (14,596 rows) is structurally
fake as a time-series surface: eligibility_hash is sha256-of-empty on
82.3% of rows and NOT A SINGLE entity carries hash drift between
version_seq=1 and version_seq=2 (CLAUDE.md gotcha + agent SQL verify).
`track_amendment_lineage_am` already surfaces an honesty caveat per
response; this ETL builds a real time-series substrate so the caveat can
be retired program-by-program as drift accumulates.

What it does (no LLM, structured extraction only)
-------------------------------------------------
For every tier S / tier A program in `jpi_programs` (1,554 rows on the
2026-05-04 snapshot):

  1. Pull the program metadata + structured eligibility surfaces from
     `jpi_programs`, `am_subsidy_rule`, `am_target_profile`,
     `am_amount_condition`, `am_application_round`, `am_program_summary`.
     ALL fields are already-structured rows; we do NO body-text parsing
     and NO LLM call. This is the "structured extraction only" contract
     from the plan — assemble a canonical JSON envelope from the existing
     normalized facts.

  2. Hash the canonicalized body (`content_hash` = sha256 of the sorted
     JSON envelope minus the eligibility predicates) and the eligibility
     predicates (`eligibility_hash` = sha256 of the sorted predicate
     subtree).

  3. INSERT OR IGNORE into `am_program_eligibility_history`. The
     UNIQUE(program_id, content_hash) constraint makes the run idempotent
     within a content-stable window — re-running on the same day is a
     no-op for unchanged programs.

  4. When a new content_hash lands for a program that already has at
     least one prior row, compute `diff_from_prev` (per-field {prev,new}
     map) + `diff_reason` (initial / content_drift / eligibility_drift /
     noop) and persist them on the new row.

The 30-day rolling window argument (`--window 30d`) caps how far back
we re-fetch in a single run — the daily cron only needs to look at the
freshest snapshot per program plus its immediate predecessor for diff
computation. The window is applied at the diff-compute step, NOT at the
INSERT step (we always INSERT today's row when content drifts).

Hard constraints (memory `feedback_no_operator_llm_api`)
-------------------------------------------------------
* NO `import anthropic` / `import openai` / `import google.generativeai` /
  `import claude_agent_sdk`. CI guard `tests/test_no_llm_in_production.py`
  scans this file (it is under `scripts/etl/`).
* NO `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` /
  `GOOGLE_API_KEY` env-var reads.
* No network egress. The structured extractor reads rows that already
  landed via earlier cron passes.

Usage
-----
    # Daily cron entry (matches .github/workflows/eligibility-history-daily.yml)
    python scripts/etl/rebuild_amendment_snapshot.py --tier S,A --window 30d

    # Local dry-run
    python scripts/etl/rebuild_amendment_snapshot.py --tier S,A --window 30d --dry-run

    # Single-program backfill
    python scripts/etl/rebuild_amendment_snapshot.py --tier S,A --program-id UNI-...

Exit codes
----------
0  success
1  fatal (db missing, schema drift)
2  no candidate programs (tier filter empty)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"

logger = logging.getLogger("jpcite.etl.rebuild_amendment_snapshot")

# Diff reason enum — kept narrow on purpose; downstream KPIs filter on
# this value via the partial index `idx_apeh_diff` (see migration 106).
DIFF_REASON_INITIAL = "initial"
DIFF_REASON_CONTENT_DRIFT = "content_drift"
DIFF_REASON_ELIGIBILITY_DRIFT = "eligibility_drift"
DIFF_REASON_NOOP = "noop"

# Fields that compose the canonical body envelope (ordering matters for
# stable hashing). The eligibility-predicate subtree is computed
# separately so we can derive eligibility_hash independently.
_BODY_FIELDS_ORDER = (
    "primary_name",
    "authority_level",
    "authority_name",
    "prefecture",
    "municipality",
    "program_kind",
    "official_url",
    "amount_max_man_yen",
    "amount_min_man_yen",
    "subsidy_rate",
    "target_types",
    "funding_purpose",
    "amount_band",
    "tier",
)

_WINDOW_RE = re.compile(r"^(\d+)([dwm])$")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_window(window: str) -> timedelta:
    """Parse the --window arg ('30d', '4w', '6m'). Returns timedelta."""
    m = _WINDOW_RE.match(window.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError(f"--window {window!r} must match <N>(d|w|m), e.g. '30d'.")
    n = int(m.group(1))
    unit = m.group(2)
    if unit == "d":
        return timedelta(days=n)
    if unit == "w":
        return timedelta(weeks=n)
    # 'm' = 30-day month approximation; used for diff-compute lookback only.
    return timedelta(days=n * 30)


def _parse_tier_csv(tier_csv: str) -> tuple[str, ...]:
    tiers = tuple(t.strip().upper() for t in tier_csv.split(",") if t.strip())
    if not tiers:
        raise argparse.ArgumentTypeError("--tier must be a non-empty CSV (e.g. 'S,A').")
    for t in tiers:
        if t not in ("S", "A", "B", "C"):
            raise argparse.ArgumentTypeError(f"--tier value {t!r} not in S/A/B/C.")
    return tiers


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Daily eligibility-history rebuild (MASTER_PLAN_v1 §D1). "
            "No LLM; structured extraction only."
        )
    )
    p.add_argument(
        "--tier",
        type=_parse_tier_csv,
        default=("S", "A"),
        help="Comma-separated tier filter (default: S,A).",
    )
    p.add_argument(
        "--window",
        type=_parse_window,
        default=timedelta(days=30),
        help="Rolling diff window (default: 30d). Applied at diff-compute step.",
    )
    p.add_argument(
        "--program-id",
        type=str,
        default=None,
        help="Optional single-program override (skips tier filter scan).",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"autonomath.db path (default: {DEFAULT_DB}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute hashes + diffs but do NOT INSERT.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="DEBUG-level logging.",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Structured extraction (no LLM, no network)
# ---------------------------------------------------------------------------


def _canonical_json(value: Any) -> str:
    """Stable JSON encoding (sorted keys, no spaces, ensure_ascii=False)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_list_json(raw: Any) -> list[Any]:
    """Decode a *_json column to a sorted, deduped list. Empty on null/junk."""
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        if parsed is None:
            return []
        if isinstance(parsed, list):
            items = parsed
        else:
            items = [parsed]
    # sort+dedupe by stable string repr
    seen: set[str] = set()
    out: list[Any] = []
    for v in items:
        key = _canonical_json(v) if not isinstance(v, str) else v
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    out.sort(key=lambda v: _canonical_json(v) if not isinstance(v, str) else v)
    return out


def _extract_program_envelope(conn: sqlite3.Connection, program_id: str) -> dict[str, Any] | None:
    """Pull the full structured envelope for a program. NO LLM, NO network.

    Returns None if the program does not exist (caller skips it).
    """
    row = conn.execute(
        """
        SELECT unified_id, primary_name, authority_level, authority_name,
               prefecture, municipality, program_kind, official_url,
               amount_max_man_yen, amount_min_man_yen, subsidy_rate, tier,
               target_types_json, funding_purpose_json, amount_band,
               source_url, source_fetched_at
          FROM jpi_programs
         WHERE unified_id = ?
        """,
        (program_id,),
    ).fetchone()
    if row is None:
        return None

    target_types = _normalize_list_json(row["target_types_json"])
    funding_purpose = _normalize_list_json(row["funding_purpose_json"])

    # Body envelope — fields used to derive content_hash. Excludes the
    # eligibility-predicate subtree (handled separately) so we can hash
    # the two independently.
    body: dict[str, Any] = {
        "primary_name": row["primary_name"],
        "authority_level": row["authority_level"],
        "authority_name": row["authority_name"],
        "prefecture": row["prefecture"],
        "municipality": row["municipality"],
        "program_kind": row["program_kind"],
        "official_url": row["official_url"],
        "amount_max_man_yen": row["amount_max_man_yen"],
        "amount_min_man_yen": row["amount_min_man_yen"],
        "subsidy_rate": row["subsidy_rate"],
        "target_types": target_types,
        "funding_purpose": funding_purpose,
        "amount_band": row["amount_band"],
        "tier": row["tier"],
    }

    # ---- Subsidy rules (already structured) ----
    subsidy_rules: list[dict[str, Any]] = []
    try:
        for r in conn.execute(
            """
            SELECT rule_type, base_rate_pct, cap_yen, per_unit_yen, unit_type,
                   eligibility_cond_json, payment_schedule, effective_from,
                   effective_until, article_ref
              FROM am_subsidy_rule
             WHERE program_entity_id = ?
             ORDER BY subsidy_rule_id
            """,
            (program_id,),
        ).fetchall():
            cond = r["eligibility_cond_json"]
            try:
                cond_parsed = json.loads(cond) if cond else {}
            except json.JSONDecodeError:
                cond_parsed = {"_raw": cond}
            subsidy_rules.append(
                {
                    "rule_type": r["rule_type"],
                    "base_rate_pct": r["base_rate_pct"],
                    "cap_yen": r["cap_yen"],
                    "per_unit_yen": r["per_unit_yen"],
                    "unit_type": r["unit_type"],
                    "eligibility_cond": cond_parsed,
                    "payment_schedule": r["payment_schedule"],
                    "effective_from": r["effective_from"],
                    "effective_until": r["effective_until"],
                    "article_ref": r["article_ref"],
                }
            )
    except sqlite3.Error:
        # Table absent on dev mirrors — soft-skip; the envelope still
        # carries program metadata which is the critical drift surface.
        pass

    # ---- Application rounds ----
    application_rounds: list[dict[str, Any]] = []
    try:
        for r in conn.execute(
            """
            SELECT open_at, close_at, round_label, status
              FROM am_application_round
             WHERE program_entity_id = ?
             ORDER BY open_at
            """,
            (program_id,),
        ).fetchall():
            application_rounds.append(
                {
                    "open_at": r["open_at"],
                    "close_at": r["close_at"],
                    "round_label": r["round_label"],
                    "status": r["status"],
                }
            )
    except sqlite3.Error:
        pass

    # ---- Amount conditions (filter to authoritative if column exists) ----
    amount_conditions: list[dict[str, Any]] = []
    try:
        # Probe for the is_authoritative column landed by mig 109 — fall
        # back to all rows if the column does not exist yet.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(am_amount_condition)")}
        if "is_authoritative" in cols:
            sql = (
                "SELECT condition_kind, amount_yen, unit_type "
                "FROM am_amount_condition WHERE program_entity_id = ? "
                "AND is_authoritative = 1 ORDER BY condition_kind"
            )
        else:
            sql = (
                "SELECT condition_kind, amount_yen, unit_type "
                "FROM am_amount_condition WHERE program_entity_id = ? "
                "ORDER BY condition_kind"
            )
        for r in conn.execute(sql, (program_id,)).fetchall():
            amount_conditions.append(
                {
                    "condition_kind": r["condition_kind"],
                    "amount_yen": r["amount_yen"],
                    "unit_type": r["unit_type"],
                }
            )
    except sqlite3.Error:
        pass

    # ---- Target profile (eligibility predicate surface) ----
    target_profile: dict[str, Any] = {}
    try:
        tp = conn.execute(
            """
            SELECT target_kind, criteria_json
              FROM am_target_profile
             WHERE program_entity_id = ?
             ORDER BY target_kind
            """,
            (program_id,),
        ).fetchall()
        for r in tp:
            crit = r["criteria_json"]
            try:
                target_profile[r["target_kind"]] = json.loads(crit) if crit else None
            except json.JSONDecodeError:
                target_profile[r["target_kind"]] = {"_raw": crit}
    except sqlite3.Error:
        pass

    # ---- Eligibility predicate subtree (hashed independently) ----
    eligibility_predicates: dict[str, Any] = {
        "subsidy_rules": subsidy_rules,
        "application_rounds": application_rounds,
        "amount_conditions": amount_conditions,
        "target_profile": target_profile,
        "target_types": target_types,
        "funding_purpose": funding_purpose,
    }

    envelope: dict[str, Any] = {
        "program_id": program_id,
        "body": body,
        "eligibility": eligibility_predicates,
        "source_url": row["source_url"],
        "source_fetched_at": row["source_fetched_at"],
    }
    return envelope


def _hash_envelope(envelope: dict[str, Any]) -> tuple[str, str]:
    """Returns (content_hash, eligibility_hash) — both sha256 hex digests."""
    body_canon = _canonical_json(envelope["body"])
    elig_canon = _canonical_json(envelope["eligibility"])
    content_hash = hashlib.sha256(body_canon.encode("utf-8")).hexdigest()
    eligibility_hash = hashlib.sha256(elig_canon.encode("utf-8")).hexdigest()
    return content_hash, eligibility_hash


# ---------------------------------------------------------------------------
# Diff vs previous row
# ---------------------------------------------------------------------------


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    """Flatten a nested dict to dotted keys for stable per-field diffing."""
    if isinstance(value, dict):
        for k in sorted(value.keys()):
            _flatten(f"{prefix}.{k}" if prefix else k, value[k], out)
    elif isinstance(value, list):
        out[prefix] = _canonical_json(value)
    else:
        out[prefix] = value


def _compute_diff(
    prev_envelope: dict[str, Any] | None,
    new_envelope: dict[str, Any],
    *,
    prev_eligibility_hash: str | None,
    new_eligibility_hash: str,
) -> tuple[dict[str, Any] | None, str]:
    """Returns (diff_from_prev_json, diff_reason).

    diff_from_prev is None on initial capture; otherwise a dict of
    {flattened_field: {"prev": x, "new": y}} for fields that drifted.
    """
    if prev_envelope is None:
        return None, DIFF_REASON_INITIAL

    prev_flat: dict[str, Any] = {}
    new_flat: dict[str, Any] = {}
    _flatten("", prev_envelope.get("body") or {}, prev_flat)
    _flatten("", new_envelope.get("body") or {}, new_flat)
    _flatten("eligibility", prev_envelope.get("eligibility") or {}, prev_flat)
    _flatten("eligibility", new_envelope.get("eligibility") or {}, new_flat)

    keys = sorted(set(prev_flat) | set(new_flat))
    diff: dict[str, Any] = {}
    for k in keys:
        p = prev_flat.get(k)
        n = new_flat.get(k)
        if p != n:
            diff[k] = {"prev": p, "new": n}

    if not diff:
        # Should not happen if content_hash actually drifted, but defensive.
        return None, DIFF_REASON_NOOP

    if prev_eligibility_hash != new_eligibility_hash:
        return diff, DIFF_REASON_ELIGIBILITY_DRIFT
    return diff, DIFF_REASON_CONTENT_DRIFT


# ---------------------------------------------------------------------------
# DB I/O
# ---------------------------------------------------------------------------


def _select_target_programs(
    conn: sqlite3.Connection,
    tiers: tuple[str, ...],
    program_id: str | None,
) -> list[str]:
    if program_id:
        # Verify it exists at all (regardless of tier).
        row = conn.execute(
            "SELECT unified_id FROM jpi_programs WHERE unified_id = ?",
            (program_id,),
        ).fetchone()
        return [row["unified_id"]] if row else []

    placeholders = ",".join("?" for _ in tiers)
    rows = conn.execute(
        f"""
        SELECT unified_id FROM jpi_programs
         WHERE tier IN ({placeholders})
           AND COALESCE(excluded, 0) = 0
         ORDER BY unified_id
        """,
        tiers,
    ).fetchall()
    return [r["unified_id"] for r in rows]


def _latest_history_for(
    conn: sqlite3.Connection, program_id: str, *, since: datetime | None = None
) -> sqlite3.Row | None:
    sql = (
        "SELECT history_id, content_hash, eligibility_hash, eligibility_struct, "
        "captured_at FROM am_program_eligibility_history "
        "WHERE program_id = ?"
    )
    params: list[Any] = [program_id]
    if since is not None:
        sql += " AND captured_at >= ?"
        params.append(since.isoformat(timespec="seconds"))
    sql += " ORDER BY captured_at DESC, history_id DESC LIMIT 1"
    return conn.execute(sql, params).fetchone()


def _insert_history_row(
    conn: sqlite3.Connection,
    *,
    program_id: str,
    captured_at: str,
    source_url: str | None,
    source_fetched_at: str | None,
    content_hash: str,
    eligibility_hash: str,
    eligibility_struct: dict[str, Any],
    diff_from_prev: dict[str, Any] | None,
    diff_reason: str,
) -> bool:
    """INSERT OR IGNORE — returns True iff a new row landed."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO am_program_eligibility_history (
            program_id, captured_at, source_url, source_fetched_at,
            content_hash, eligibility_hash, eligibility_struct,
            diff_from_prev, diff_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            program_id,
            captured_at,
            source_url,
            source_fetched_at,
            content_hash,
            eligibility_hash,
            _canonical_json(eligibility_struct),
            _canonical_json(diff_from_prev) if diff_from_prev is not None else None,
            diff_reason,
        ),
    )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _open_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"FATAL: autonomath.db not found at {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # Read-modify-write workload — keep a sensible busy_timeout so
    # concurrent ingest crons don't blow us up on WAL contention.
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    conn = _open_db(args.db)
    try:
        # Sanity: target table must exist (migration 106 applied).
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='am_program_eligibility_history' LIMIT 1"
        ).fetchone()
        if not exists:
            logger.error(
                "am_program_eligibility_history missing — apply migration "
                "wave24_106 before running this ETL."
            )
            return 1

        targets = _select_target_programs(conn, args.tier, args.program_id)
        if not targets:
            logger.warning(
                "no candidate programs (tier=%s program_id=%s)",
                ",".join(args.tier),
                args.program_id,
            )
            return 2

        logger.info(
            "rebuild starting: %d programs (tier=%s window=%dd dry_run=%s)",
            len(targets),
            ",".join(args.tier),
            args.window.days,
            args.dry_run,
        )

        captured_at = datetime.now(UTC).isoformat(timespec="seconds")
        since_dt = datetime.now(UTC) - args.window

        n_inserted = 0
        n_skipped_dup = 0
        n_initial = 0
        n_content_drift = 0
        n_eligibility_drift = 0
        n_missing = 0

        if not args.dry_run:
            conn.execute("BEGIN IMMEDIATE")
        try:
            for pid in targets:
                envelope = _extract_program_envelope(conn, pid)
                if envelope is None:
                    n_missing += 1
                    continue

                content_hash, eligibility_hash = _hash_envelope(envelope)

                prev_row = _latest_history_for(conn, pid, since=since_dt)
                if prev_row is None:
                    # No row in window — fall back to all-time latest for
                    # initial vs noop discrimination.
                    prev_row = _latest_history_for(conn, pid)

                prev_envelope: dict[str, Any] | None = None
                prev_eligibility_hash: str | None = None
                if prev_row is not None:
                    prev_eligibility_hash = prev_row["eligibility_hash"]
                    raw = prev_row["eligibility_struct"]
                    if raw:
                        try:
                            prev_struct = json.loads(raw)
                            # Reconstruct the envelope shape used by
                            # _compute_diff (body + eligibility split).
                            prev_envelope = {
                                "body": (prev_struct or {}).get("body") or {},
                                "eligibility": (prev_struct or {}).get("eligibility") or {},
                            }
                        except json.JSONDecodeError:
                            prev_envelope = None

                # Skip if content_hash has not drifted AND we already have
                # a row for this program (idempotent within stable window).
                if prev_row is not None and prev_row["content_hash"] == content_hash:
                    n_skipped_dup += 1
                    continue

                diff_json, diff_reason = _compute_diff(
                    prev_envelope,
                    envelope,
                    prev_eligibility_hash=prev_eligibility_hash,
                    new_eligibility_hash=eligibility_hash,
                )

                # Persist a compact eligibility_struct that the next run
                # can rehydrate cheaply (body + eligibility only — drop
                # the source_* metadata which moves at every fetch).
                struct_for_storage = {
                    "body": envelope["body"],
                    "eligibility": envelope["eligibility"],
                }

                if args.dry_run:
                    n_inserted += 1
                else:
                    landed = _insert_history_row(
                        conn,
                        program_id=pid,
                        captured_at=captured_at,
                        source_url=envelope.get("source_url"),
                        source_fetched_at=envelope.get("source_fetched_at"),
                        content_hash=content_hash,
                        eligibility_hash=eligibility_hash,
                        eligibility_struct=struct_for_storage,
                        diff_from_prev=diff_json,
                        diff_reason=diff_reason,
                    )
                    if landed:
                        n_inserted += 1
                    else:
                        # UNIQUE collision — another concurrent run
                        # already landed today's row.
                        n_skipped_dup += 1
                        continue

                if diff_reason == DIFF_REASON_INITIAL:
                    n_initial += 1
                elif diff_reason == DIFF_REASON_ELIGIBILITY_DRIFT:
                    n_eligibility_drift += 1
                elif diff_reason == DIFF_REASON_CONTENT_DRIFT:
                    n_content_drift += 1

            if not args.dry_run:
                conn.commit()
        except Exception:
            if not args.dry_run:
                conn.rollback()
            raise

        logger.info(
            "rebuild done: inserted=%d skipped_dup=%d initial=%d "
            "content_drift=%d eligibility_drift=%d missing=%d",
            n_inserted,
            n_skipped_dup,
            n_initial,
            n_content_drift,
            n_eligibility_drift,
            n_missing,
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
