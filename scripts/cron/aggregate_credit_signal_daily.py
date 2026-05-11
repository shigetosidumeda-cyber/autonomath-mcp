#!/usr/bin/env python3
"""Wave 41 Axis 7b: daily aggregate credit signals into am_credit_signal_aggregate.

What it does
------------
Walks the existing primary-source corpora (no aggregator, no LLM) and
emits one ``am_credit_signal`` row per qualifying event, then collapses
them per ``houjin_bangou`` into ``am_credit_signal_aggregate`` with a
rule-based score 0..100.

Source axes (autonomath.db only)
--------------------------------
* ``am_enforcement_detail`` (22,258 rows; 6,455 with houjin_bangou)
  → ``signal_type='enforcement'`` (severity weighted by enforcement_kind).
* ``invoice_registrants`` (13,801 rows; revoked rows have revoked_date)
  → ``signal_type='invoice_revoked'`` when revoked_date is non-null.
* ``adoption_records`` / ``jpi_adoption_records`` (~201k rows)
  → ``signal_type='subsidy_revoked'`` when status carries '取消' / '中止'.
* ``court_decisions`` (~2,065 rows on jpintel.db — NOT walked here per
  CLAUDE.md "no cross-DB ATTACH" rule; deferred to a future ETL that
  promotes 倒産確定 events into autonomath as a precomputed mirror.)

Memory constraints
------------------
* ``feedback_no_operator_llm_api`` — ZERO LLM API calls, ZERO ML model.
  Pure rule-based score using stdlib + sqlite3.
* ``feedback_no_quick_check_on_huge_sqlite`` — no PRAGMA quick_check /
  integrity_check on the 9.7 GB DB. Index-only walks.
* ``feedback_no_fake_data`` — every ``source_url`` is a first-party
  primary source URL carried verbatim from the corpus row.

Rule-based score 0..100 (deterministic, no ML)
----------------------------------------------
* per-signal severity weight:
    enforcement (refund)        : 35
    enforcement (other)         : 25
    invoice_revoked             : 20
    subsidy_revoked             : 25
    refund (sole)               : 30
    late_payment                : 15
    court_judgment              : 40
    sanction_extension          : 10
* aggregate score = min(100, sum_weighted_capped) where each signal
  contributes its severity weight, decayed by 12 months from
  ``signal_date`` (linear decay over 36 months).
* ``max_severity`` = the max of every signal's severity at write time.
* ``signal_count`` = total qualifying signals per houjin (undecayed).

Usage
-----
    python scripts/cron/aggregate_credit_signal_daily.py --dry-run
    python scripts/cron/aggregate_credit_signal_daily.py
    python scripts/cron/aggregate_credit_signal_daily.py --houjin-limit 5000
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import math
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("autonomath.cron.aggregate_credit_signal_daily")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
DEFAULT_HOUJIN_LIMIT = 100_000

# Severity weights — rule-based, deterministic. No ML, no LLM.
_SEVERITY_WEIGHTS: dict[str, int] = {
    "enforcement": 25,
    "refund": 30,
    "invoice_revoked": 20,
    "late_payment": 15,
    "court_judgment": 40,
    "subsidy_revoked": 25,
    "sanction_extension": 10,
}
# Severity escalation rules within enforcement kind.
_ENFORCEMENT_BUMP_KEYWORDS: tuple[tuple[str, int], ...] = (
    ("返還", 35),
    ("取消", 30),
    ("命令", 28),
    ("勧告", 22),
)

# Time-decay: signals older than 36 months contribute 0.
_DECAY_FLOOR_DAYS = 36 * 30


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("autonomath.cron.aggregate_credit_signal_daily")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


# --------------------------------------------------------------------------- #
# DB helpers
# --------------------------------------------------------------------------- #


def _db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    return Path(raw) if raw else DEFAULT_DB_PATH


def _open_rw(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-65536")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Idempotent CREATEs mirroring migration 246."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_credit_signal (
              signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
              houjin_bangou TEXT NOT NULL,
              signal_type TEXT NOT NULL,
              signal_date TEXT,
              severity INTEGER NOT NULL DEFAULT 0,
              source_url TEXT,
              source_kind TEXT,
              evidence_text TEXT,
              created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )"""
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_am_credit_signal_dedupe "
        "ON am_credit_signal("
        "  houjin_bangou, signal_type,"
        "  COALESCE(signal_date, '_undated'),"
        "  COALESCE(source_url, '_no_url')"
        ")"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_credit_signal_aggregate (
              houjin_bangou TEXT PRIMARY KEY,
              signal_count INTEGER NOT NULL DEFAULT 0,
              max_severity INTEGER NOT NULL DEFAULT 0,
              rule_based_score INTEGER NOT NULL DEFAULT 0,
              last_signal_date TEXT,
              refreshed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
              type_breakdown_json TEXT
            )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_credit_signal_run_log (
              run_id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              signals_seen INTEGER NOT NULL DEFAULT 0,
              houjin_aggregated INTEGER NOT NULL DEFAULT 0,
              error_text TEXT
            )"""
    )


# --------------------------------------------------------------------------- #
# Signal extractors
# --------------------------------------------------------------------------- #


def _extract_enforcement(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    """Pull enforcement events with non-null 13-digit houjin_bangou."""
    if not _table_exists(conn, "am_enforcement_detail"):
        return []
    try:
        rows = conn.execute(
            "SELECT houjin_bangou, enforcement_kind, reason_summary, issuance_date, "
            "       source_url, amount_yen "
            "FROM am_enforcement_detail "
            "WHERE houjin_bangou IS NOT NULL "
            "  AND length(houjin_bangou) = 13 "
            "ORDER BY issuance_date DESC NULLS LAST "
            "LIMIT ?",
            (int(limit),),
        ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("enforcement walk failed: %s", e)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        kind = (r["enforcement_kind"] or "").strip()
        reason = (r["reason_summary"] or "").strip()
        sig_type = "enforcement"
        if "返還" in kind or "返還" in reason:
            sig_type = "refund"
        sev = _SEVERITY_WEIGHTS.get(sig_type, 25)
        for kw, bump in _ENFORCEMENT_BUMP_KEYWORDS:
            if kw in reason or kw in kind:
                sev = max(sev, bump)
        out.append(
            {
                "houjin_bangou": str(r["houjin_bangou"]).zfill(13),
                "signal_type": sig_type,
                "signal_date": r["issuance_date"],
                "severity": sev,
                "source_url": r["source_url"],
                "source_kind": "ministry",
                "evidence_text": (reason or kind)[:280] or None,
            }
        )
    return out


def _extract_invoice_revoked(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    if not _table_exists(conn, "invoice_registrants"):
        return []
    try:
        rows = conn.execute(
            "SELECT houjin_bangou, revoked_date, source_url, registered_date "
            "FROM invoice_registrants "
            "WHERE houjin_bangou IS NOT NULL "
            "  AND length(houjin_bangou) = 13 "
            "  AND revoked_date IS NOT NULL "
            "ORDER BY revoked_date DESC "
            "LIMIT ?",
            (int(limit),),
        ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("invoice walk failed: %s", e)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "houjin_bangou": str(r["houjin_bangou"]).zfill(13),
                "signal_type": "invoice_revoked",
                "signal_date": r["revoked_date"],
                "severity": _SEVERITY_WEIGHTS["invoice_revoked"],
                "source_url": r["source_url"],
                "source_kind": "NTA",
                "evidence_text": "適格事業者登録取消",
            }
        )
    return out


def _extract_subsidy_revoked(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    table = (
        "jpi_adoption_records"
        if _table_exists(conn, "jpi_adoption_records")
        else "adoption_records"
        if _table_exists(conn, "adoption_records")
        else None
    )
    if table is None:
        return []
    try:
        rows = conn.execute(
            f"SELECT houjin_bangou, status, announced_at, source_url "
            f"FROM {table} "
            f"WHERE houjin_bangou IS NOT NULL "
            f"  AND length(houjin_bangou) = 13 "
            f"  AND status IS NOT NULL "
            f"  AND (status LIKE '%取消%' OR status LIKE '%中止%' OR status LIKE '%辞退%') "
            f"LIMIT ?",
            (int(limit),),
        ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("subsidy walk failed: %s", e)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "houjin_bangou": str(r["houjin_bangou"]).zfill(13),
                "signal_type": "subsidy_revoked",
                "signal_date": r["announced_at"],
                "severity": _SEVERITY_WEIGHTS["subsidy_revoked"],
                "source_url": r["source_url"],
                "source_kind": "METI",
                "evidence_text": str(r["status"])[:200],
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def _decay_factor(signal_date: str | None, now: datetime) -> float:
    """Linear decay over 36 months. Undated → 0.5 (mid-decay)."""
    if not signal_date:
        return 0.5
    try:
        # accept yyyy-mm-dd or full ISO
        parsed = datetime.fromisoformat(signal_date.split("T")[0]).replace(tzinfo=UTC)
    except ValueError:
        return 0.5
    days = max(0, (now - parsed).days)
    if days >= _DECAY_FLOOR_DAYS:
        return 0.0
    return max(0.0, 1.0 - days / _DECAY_FLOOR_DAYS)


def _aggregate(signals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    now = datetime.now(UTC)
    per_houjin: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in signals:
        per_houjin[s["houjin_bangou"]].append(s)

    out: dict[str, dict[str, Any]] = {}
    for h, sigs in per_houjin.items():
        weighted = 0.0
        max_sev = 0
        type_count: dict[str, int] = defaultdict(int)
        latest_date = ""
        for s in sigs:
            df = _decay_factor(s.get("signal_date"), now)
            weighted += s["severity"] * df
            max_sev = max(max_sev, int(s["severity"]))
            type_count[s["signal_type"]] += 1
            if s.get("signal_date") and s["signal_date"] > latest_date:
                latest_date = s["signal_date"]
        score = int(min(100, math.floor(weighted)))
        out[h] = {
            "signal_count": len(sigs),
            "max_severity": int(max_sev),
            "rule_based_score": score,
            "last_signal_date": latest_date or None,
            "type_breakdown_json": json.dumps(dict(type_count), ensure_ascii=False),
        }
    return out


# --------------------------------------------------------------------------- #
# Persist
# --------------------------------------------------------------------------- #


def _persist_signals(
    conn: sqlite3.Connection, signals: list[dict[str, Any]]
) -> int:
    written = 0
    for s in signals:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO am_credit_signal "
                "(houjin_bangou, signal_type, signal_date, severity, source_url, source_kind, evidence_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    s["houjin_bangou"],
                    s["signal_type"],
                    s.get("signal_date"),
                    int(s["severity"]),
                    s.get("source_url"),
                    s.get("source_kind"),
                    s.get("evidence_text"),
                ),
            )
            written += 1
        except sqlite3.Error as e:
            logger.warning("signal write failed: %s", e)
    return written


def _persist_aggregate(
    conn: sqlite3.Connection, aggregates: dict[str, dict[str, Any]]
) -> int:
    written = 0
    for h, agg in aggregates.items():
        try:
            conn.execute(
                "INSERT OR REPLACE INTO am_credit_signal_aggregate "
                "(houjin_bangou, signal_count, max_severity, rule_based_score, "
                " last_signal_date, refreshed_at, type_breakdown_json) "
                "VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'), ?)",
                (
                    h,
                    int(agg["signal_count"]),
                    int(agg["max_severity"]),
                    int(agg["rule_based_score"]),
                    agg.get("last_signal_date"),
                    agg["type_breakdown_json"],
                ),
            )
            written += 1
        except sqlite3.Error as e:
            logger.warning("agg write failed: %s", e)
    return written


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Aggregate credit signals daily (rule-based, NO ML).")
    p.add_argument("--houjin-limit", type=int, default=DEFAULT_HOUJIN_LIMIT)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    _configure_logging(verbose=args.verbose)
    started_at = datetime.now(UTC).isoformat()

    db_path = _db_path()
    if args.dry_run:
        logger.info("[dry-run] would open %s, walk 3 axes, limit=%d", db_path, args.houjin_limit)
        return 0

    if not db_path.exists():
        logger.error("autonomath.db missing at %s — run migration 246 first", db_path)
        return 2

    conn = _open_rw(db_path)
    try:
        _ensure_tables(conn)
        signals: list[dict[str, Any]] = []
        signals.extend(_extract_enforcement(conn, args.houjin_limit))
        signals.extend(_extract_invoice_revoked(conn, args.houjin_limit))
        signals.extend(_extract_subsidy_revoked(conn, args.houjin_limit))
        logger.info("signals_extracted=%d", len(signals))

        written_signals = _persist_signals(conn, signals)
        aggregates = _aggregate(signals)
        written_agg = _persist_aggregate(conn, aggregates)

        conn.execute(
            "INSERT INTO am_credit_signal_run_log "
            "(started_at, finished_at, signals_seen, houjin_aggregated, error_text) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                started_at,
                datetime.now(UTC).isoformat(),
                written_signals,
                written_agg,
                None,
            ),
        )
        result = {
            "signals_seen": len(signals),
            "signals_persisted": written_signals,
            "houjin_aggregated": written_agg,
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        with contextlib.suppress(Exception):
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
