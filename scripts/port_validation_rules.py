#!/usr/bin/env python3
"""Port 6 generic check_* predicates from Autonomath intake_consistency_rules.py
into the jpintel-mcp am_validation_rule table (migration 047).

Selection criteria (汎用 = generic):
  * No reference to 'agri', '農', stage codes, crop enums, certification names,
    entity_type values, or any other agri-specific vocabulary inside the
    function body.
  * Pure value-domain or relational checks: amount >0, date plausibility,
    physical-time impossibility, band-vs-amount consistency, etc.
  * Reading from a typed dict path (e.g. ``behavioral.weekly_work_hours``) is
    OK because predicate_ref is stored as a future-dispatch reference; the
    check **logic** itself is what must be domain-agnostic.

The script does NOT execute the predicate at port time. It only registers a
dispatch reference (``autonomath.intake.<function_name>``) that downstream
evaluators may resolve later.

Usage::

    # 1. List candidates only (no DB writes)
    python scripts/port_validation_rules.py --dry-run

    # 2. Apply rows to the DB (refuses without --confirm)
    python scripts/port_validation_rules.py --apply --confirm

    # 3. Target a specific DB
    python scripts/port_validation_rules.py --dry-run --db data/jpintel.db

Environment:
    JPINTEL_DB_PATH overrides the default ``data/jpintel.db``.
"""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_LOG = logging.getLogger("port_validation_rules")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"

SOURCE_NAME = "autonomath_intake_rules"
SOURCE_LICENSE = "proprietary"
SOURCE_URL = "internal://autonomath/backend/services/intake_consistency_rules.py"
PREDICATE_PREFIX = "autonomath.intake."


@dataclass(frozen=True)
class Candidate:
    """One generic check_* predicate to register as a validation rule."""

    function_name: str          # check_weekly_work_hours_over -> registered as predicate_ref tail
    description: str            # 1-line English summary for operator visibility
    rationale_ja: str           # why it qualifies as 汎用
    severity: str               # 'info' | 'warning' | 'critical'
    message_ja: str             # operator-visible message at violation


# ---------------------------------------------------------------------------
# Selected 6 generic predicates
# ---------------------------------------------------------------------------
# Each one was reviewed against the full intake_consistency_rules.py listing.
# Functions that touch agri-specific tokens (stage, crop, entity_type, certs,
# 法人, 農, etc.) inside their *body* are excluded even if their input path
# happens to live under qualifications/_phase1.

CANDIDATES: list[Candidate] = [
    Candidate(
        function_name="check_training_hours_per_year_over",
        description=(
            "training_hours_per_year > 8760 (24 hours x 365 days) is physically "
            "impossible regardless of industry."
        ),
        rationale_ja=(
            "24×365=8760 のハード上限のみ。業種・stage・品目に一切依存しない。"
        ),
        severity="critical",
        message_ja="年間研修時間が 8760 時間 (24 時間 × 365 日) を超過しており物理的に不可能です。",
    ),
    Candidate(
        function_name="check_annual_work_days_over",
        description="annual_work_days > 365 is calendar-impossible.",
        rationale_ja="365 日というカレンダー上限のみ。ジャンル非依存。",
        severity="critical",
        message_ja="年間労働日数が 365 日を超過しており不可能です。",
    ),
    Candidate(
        function_name="check_weekly_work_hours_over",
        description="weekly_work_hours > 168 (24 x 7) is physically impossible.",
        rationale_ja="24×7=168 の物理上限のみ。文脈依存ゼロ。",
        severity="critical",
        message_ja="週間労働時間が 168 時間 (24 時間 × 7 日) を超過しており物理的に不可能です。",
    ),
    Candidate(
        function_name="check_start_year_plausible",
        description=(
            "start_year must fall within current_year - 20 .. current_year + 10. "
            "Pure year-range sanity, no domain enum involved."
        ),
        rationale_ja=(
            "「過去 20 年〜未来 10 年」という一般 plausibility 窓のみ。"
            "農業・補助金・法人格に依らない汎用 sanity。"
        ),
        severity="warning",
        message_ja="開始年が許容範囲 (現在年の前後 20 年/10 年) を外れており入力ミスの可能性があります。",
    ),
    Candidate(
        function_name="check_birth_vs_age",
        description=(
            "Computed age from birth_date must match self-reported age within 1 year. "
            "Pure date arithmetic."
        ),
        rationale_ja=(
            "生年月日から計算した年齢と自己申告年齢の整合性チェック。"
            "純粋な日付算術のみ。"
        ),
        severity="info",
        message_ja="生年月日から計算した年齢と入力された年齢が 1 年以上ずれています。",
    ),
    Candidate(
        function_name="check_desired_amount_sanity_upper",
        description=(
            "desired_amount_man_yen > 500000 (50 億円) is a numeric-magnitude "
            "sanity ceiling, independent of program, sector, or applicant type."
        ),
        rationale_ja=(
            "50 億円 (500,000 万円) という桁数 sanity の上限のみ。"
            "制度・業種・申請者属性に依らないスカラー上限チェック。"
        ),
        severity="warning",
        message_ja="希望調達額が 50 億円を超過しており、桁数の入力ミスの可能性があります。",
    ),
]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("port_validation_rules")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _resolve_db_path(arg_db: Optional[str]) -> Path:
    if arg_db:
        return Path(arg_db).expanduser().resolve()
    env = os.environ.get("JPINTEL_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_DB


def _check_required_tables(conn: sqlite3.Connection) -> None:
    """Refuse to apply if migration 047 (and its dependency am_source) hasn't run."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name IN ('am_validation_rule', 'am_source')"
    ).fetchall()
    found = {r[0] for r in rows}
    missing = {"am_validation_rule", "am_source"} - found
    if missing:
        raise SystemExit(
            f"Required tables missing: {sorted(missing)}. "
            f"Apply migrations first (scripts/migrate.py) before running --apply."
        )


def _ensure_source(conn: sqlite3.Connection) -> int:
    """Insert the am_source row (idempotent) and return its id."""
    # Check column set so we can adapt to migration 049 (license column added later).
    cols = [r[1] for r in conn.execute("PRAGMA table_info(am_source)").fetchall()]
    has_license = "license" in cols
    url_col = "source_url" if "source_url" in cols else ("url" if "url" in cols else None)

    if not url_col:
        raise SystemExit("am_source has no source_url/url column — cannot identify source row")
    existing = conn.execute(
        f"SELECT id FROM am_source WHERE {url_col} = ? LIMIT 1", (SOURCE_URL,)
    ).fetchone()
    if existing:
        _LOG.info("source_exists url=%s id=%s", SOURCE_URL, existing[0])
        return int(existing[0])

    insert_cols = [url_col]
    insert_vals: list[object] = [SOURCE_URL]
    if has_license:
        insert_cols.append("license")
        insert_vals.append(SOURCE_LICENSE)

    sql = (
        f"INSERT INTO am_source ({', '.join(insert_cols)}) "
        f"VALUES ({', '.join('?' for _ in insert_vals)})"
    )
    cur = conn.execute(sql, insert_vals)
    sid = int(cur.lastrowid or 0)
    _LOG.info("source_inserted name=%s id=%s license=%s", SOURCE_NAME, sid, SOURCE_LICENSE if has_license else "(no column)")
    return sid


def _rule_exists(conn: sqlite3.Connection, predicate_ref: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM am_validation_rule "
        "WHERE predicate_kind = 'python_dispatch' AND predicate_ref = ? LIMIT 1",
        (predicate_ref,),
    ).fetchone()
    return row is not None


def _insert_rule(
    conn: sqlite3.Connection,
    candidate: Candidate,
    source_id: int,
) -> Optional[int]:
    predicate_ref = PREDICATE_PREFIX + candidate.function_name
    if _rule_exists(conn, predicate_ref):
        _LOG.info("skip_existing predicate_ref=%s", predicate_ref)
        return None

    cur = conn.execute(
        """
        INSERT INTO am_validation_rule (
            applies_to,
            scope,
            predicate_kind,
            predicate_ref,
            severity,
            message_ja,
            scope_entity_id,
            effective_from,
            effective_until,
            active,
            source_id
        ) VALUES (
            'intake', 'applicant', 'python_dispatch', ?, ?, ?,
            NULL, NULL, NULL, 1, ?
        )
        """,
        (predicate_ref, candidate.severity, candidate.message_ja, source_id),
    )
    rid = int(cur.lastrowid or 0)
    _LOG.info(
        "rule_inserted rule_id=%s predicate_ref=%s severity=%s",
        rid, predicate_ref, candidate.severity,
    )
    return rid


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_dry_run() -> None:
    print(f"\nCandidates ({len(CANDIDATES)}) — generic predicates from "
          f"autonomath.intake_consistency_rules:\n")
    for i, c in enumerate(CANDIDATES, 1):
        print(f"[{i}] {c.function_name}")
        print(f"    predicate_ref : {PREDICATE_PREFIX}{c.function_name}")
        print(f"    severity      : {c.severity}")
        print(f"    description   : {c.description}")
        print(f"    rationale (ja): {c.rationale_ja}")
        print(f"    message_ja    : {c.message_ja}")
        print()
    print("To apply: python scripts/port_validation_rules.py --apply --confirm")


def _do_apply(db_path: Path) -> None:
    if not db_path.is_file():
        raise SystemExit(f"DB not found: {db_path}")
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        _check_required_tables(conn)
        conn.execute("BEGIN")
        try:
            source_id = _ensure_source(conn)
            inserted = 0
            skipped = 0
            for c in CANDIDATES:
                rid = _insert_rule(conn, c, source_id)
                if rid is None:
                    skipped += 1
                else:
                    inserted += 1
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        _LOG.info(
            "apply_done db=%s source_id=%s inserted=%d skipped=%d total=%d",
            db_path, source_id, inserted, skipped, len(CANDIDATES),
        )
        print(f"\nApplied to {db_path}")
        print(f"  source_id : {source_id}")
        print(f"  inserted  : {inserted}")
        print(f"  skipped   : {skipped}")
        print(f"  total     : {len(CANDIDATES)}")
    finally:
        conn.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Port 6 generic intake validation predicates into am_validation_rule.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print candidate list and exit without touching the DB.")
    parser.add_argument("--apply", action="store_true",
                        help="Insert rows into am_validation_rule. Requires --confirm.")
    parser.add_argument("--confirm", action="store_true",
                        help="Required together with --apply to actually write.")
    parser.add_argument("--db", default=None,
                        help=f"SQLite DB path (default: {DEFAULT_DB} or $JPINTEL_DB_PATH).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")
    args = parser.parse_args(argv)

    _configure_logging(verbose=args.verbose)

    if args.apply and not args.confirm:
        raise SystemExit(
            "--apply requires --confirm. Re-run with: --apply --confirm"
        )
    if not args.dry_run and not args.apply:
        # Default behaviour = dry-run (safer)
        _LOG.info("no_mode_specified_defaulting_to_dry_run")
        args.dry_run = True

    if args.dry_run:
        _print_dry_run()
        return 0

    if args.apply:
        db_path = _resolve_db_path(args.db)
        _LOG.info("apply_begin db=%s", db_path)
        _do_apply(db_path)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
