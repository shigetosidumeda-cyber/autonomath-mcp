#!/usr/bin/env python3
"""Wave 49 G4/G5 first-transaction observation watchdog.

Background
----------
Wave 49 closes the agent-funnel 6-stage loop with two parallel revenue
rails:

  * **G4 — x402 USDC payment**: `am_x402_payment_log` (migration 282)
    receives one append-only row per HTTP-402 challenge that the agent
    settled on Base L2. Production payer addresses are `0x...` EOAs and
    `txn_hash` is the 66-char Base txn hash; mock proofs are disabled
    in production by the `_mock_proof_enabled()` guard in
    `src/jpintel_mcp/api/x402_payment.py`.
  * **G5 — Wallet ¥ topup**: `am_credit_transaction_log` (migration
    281, txn_type='topup') receives one row per successful Stripe-side
    auto-topup or operator-confirmed manual topup against
    `am_credit_wallet`.

Until the first real transaction lands on either rail the funnel is
"discoverable but unproven" — Wave 49 needs an explicit observation
moment so that the operator (and the AX rollout dashboard) can pin
the "first ¥ flowed in" timestamp instead of inferring it from
weekly billing rollups.

Contract
--------
This script is **observation only** — it NEVER writes to
`am_x402_payment_log` or `am_credit_transaction_log`, NEVER fakes a
synthetic row, and NEVER calls a paid LLM API
(`feedback_no_operator_llm_api`). It only:

  1. Counts rows in the two ledgers (index-only walk; no PRAGMA
     quick_check / integrity_check on the 9.7 GB autonomath.db per
     `feedback_no_quick_check_on_huge_sqlite`).
  2. If a count crosses 0 → ≥1 since the last invocation, writes a
     single JSON detection event to
     `monitoring/first_txn_detected.json`.
  3. Idempotent: once the file exists with a `rail` already marked,
     re-runs will NOT overwrite it. The companion `--reset` flag is
     reserved for DR drills and prints a refusal unless
     `--i-am-resetting-detection-state` is also passed.

Detection event shape (idempotent single file)
----------------------------------------------
``monitoring/first_txn_detected.json``::

    {
      "schema_version": 1,
      "first_detected_at_utc": "2026-05-16T12:34:56.789Z",
      "rails": {
        "g4_x402_payment": {
          "table": "am_x402_payment_log",
          "first_row_count": 1,
          "first_detected_at_utc": "2026-05-16T12:34:56.789Z",
          "earliest_row_occurred_at": "2026-05-16T12:33:00.000Z",
          "endpoint_path_sample": "/v1/case-studies/search"
        },
        "g5_wallet_topup": {
          "table": "am_credit_transaction_log",
          "first_row_count": 0,
          "first_detected_at_utc": null,
          "earliest_row_occurred_at": null,
          "txn_type_filter": "topup"
        }
      },
      "history": [
        {"rail": "g4_x402_payment", "detected_at_utc": "...", "row_count": 1}
      ]
    }

Each rail entry transitions once: ``first_row_count == 0`` →
``first_row_count == N>=1``. After transition, that rail's entry is
sealed (idempotent). The ``history`` list appends one record per
transition for audit. ``first_detected_at_utc`` at the top level is
the earliest rail transition.

Slack notification
------------------
If ``SLACK_WEBHOOK_URL`` is set in the environment AND a transition
just fired in this invocation (i.e. not a sealed replay), the script
POSTs a short message to the webhook. Failures POST-side are warned
but never red-line the cron (exit 0).

Usage
-----
    # observation-only, default behavior
    python scripts/cron/detect_first_g4_g5_txn.py --check

    # alias for --check
    python scripts/cron/detect_first_g4_g5_txn.py

    # dry-run: probe counts + print what *would* be written without
    # touching disk or hitting Slack
    python scripts/cron/detect_first_g4_g5_txn.py --dry-run

    # override db path / output path (test fixtures + DR drills)
    python scripts/cron/detect_first_g4_g5_txn.py --db /tmp/test.db \
        --output /tmp/first_txn_detected.json

CI gating
---------
On GitHub Actions, the companion workflow
``.github/workflows/detect-first-g4-g5-txn.yml`` runs this script
every 30 min via ``flyctl ssh console -a autonomath-api`` so the
observation walks the production volume DB, not the runner's missing
copy. The runner-local invocation only fires when
``JPCITE_PREFLIGHT_ALLOW_MISSING_DB=1`` and ``--dry-run`` are set.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("jpcite.cron.detect_first_g4_g5_txn")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "monitoring" / "first_txn_detected.json"

SCHEMA_VERSION = 1
RAIL_G4 = "g4_x402_payment"
RAIL_G5 = "g5_wallet_topup"
TABLE_G4 = "am_x402_payment_log"
TABLE_G5 = "am_credit_transaction_log"
G5_TXN_TYPE_FILTER = "topup"


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the DB read-only via URI; never mutate.

    Uses ``mode=ro`` so an accidental INSERT would raise rather than
    silently fake a row.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def probe_g4_x402_payment(conn: sqlite3.Connection) -> dict[str, Any]:
    """Index-only walk of am_x402_payment_log.

    Returns a snapshot dict with row_count + earliest_row_occurred_at +
    endpoint_path_sample. Never writes.
    """
    if not _table_exists(conn, TABLE_G4):
        return {
            "table": TABLE_G4,
            "row_count": 0,
            "earliest_row_occurred_at": None,
            "endpoint_path_sample": None,
            "schema_present": False,
        }
    row = conn.execute(
        f"SELECT COUNT(*) AS c FROM {TABLE_G4}"  # noqa: S608 — literal table
    ).fetchone()
    row_count = int(row["c"]) if row else 0
    earliest: str | None = None
    endpoint_sample: str | None = None
    if row_count > 0:
        first = conn.execute(
            f"SELECT occurred_at, endpoint_path FROM {TABLE_G4} "  # noqa: S608
            "ORDER BY payment_id ASC LIMIT 1"
        ).fetchone()
        if first is not None:
            earliest = first["occurred_at"]
            endpoint_sample = first["endpoint_path"]
    return {
        "table": TABLE_G4,
        "row_count": row_count,
        "earliest_row_occurred_at": earliest,
        "endpoint_path_sample": endpoint_sample,
        "schema_present": True,
    }


def probe_g5_wallet_topup(conn: sqlite3.Connection) -> dict[str, Any]:
    """Index-only walk of am_credit_transaction_log filtered to topup."""
    if not _table_exists(conn, TABLE_G5):
        return {
            "table": TABLE_G5,
            "row_count": 0,
            "earliest_row_occurred_at": None,
            "txn_type_filter": G5_TXN_TYPE_FILTER,
            "schema_present": False,
        }
    row = conn.execute(
        f"SELECT COUNT(*) AS c FROM {TABLE_G5} WHERE txn_type = ?",  # noqa: S608
        (G5_TXN_TYPE_FILTER,),
    ).fetchone()
    row_count = int(row["c"]) if row else 0
    earliest: str | None = None
    if row_count > 0:
        first = conn.execute(
            f"SELECT occurred_at FROM {TABLE_G5} WHERE txn_type = ? "  # noqa: S608
            "ORDER BY txn_id ASC LIMIT 1",
            (G5_TXN_TYPE_FILTER,),
        ).fetchone()
        if first is not None:
            earliest = first["occurred_at"]
    return {
        "table": TABLE_G5,
        "row_count": row_count,
        "earliest_row_occurred_at": earliest,
        "txn_type_filter": G5_TXN_TYPE_FILTER,
        "schema_present": True,
    }


def load_previous_state(path: Path) -> dict[str, Any]:
    """Return the previous detection event JSON, or a fresh skeleton."""
    if not path.exists():
        return _empty_state()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("could not parse %s (%s); starting fresh", path, exc)
        return _empty_state()


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "first_detected_at_utc": None,
        "rails": {
            RAIL_G4: {
                "table": TABLE_G4,
                "first_row_count": 0,
                "first_detected_at_utc": None,
                "earliest_row_occurred_at": None,
                "endpoint_path_sample": None,
            },
            RAIL_G5: {
                "table": TABLE_G5,
                "first_row_count": 0,
                "first_detected_at_utc": None,
                "earliest_row_occurred_at": None,
                "txn_type_filter": G5_TXN_TYPE_FILTER,
            },
        },
        "history": [],
    }


def compute_transitions(
    previous: dict[str, Any],
    g4_probe: dict[str, Any],
    g5_probe: dict[str, Any],
    now_iso: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (new_state, new_transitions).

    A transition fires exactly once per rail — when the previously
    stored ``first_row_count == 0`` and the current probe reports
    ``row_count >= 1``. Once a rail has a non-zero
    ``first_row_count``, subsequent re-runs do not modify that rail.
    """
    state = json.loads(json.dumps(previous))  # deep copy
    state.setdefault("schema_version", SCHEMA_VERSION)
    state.setdefault("rails", _empty_state()["rails"])
    state.setdefault("history", [])
    transitions: list[dict[str, Any]] = []

    rail_inputs = (
        (RAIL_G4, g4_probe, ("endpoint_path_sample",)),
        (RAIL_G5, g5_probe, ("txn_type_filter",)),
    )
    for rail_name, probe, extra_keys in rail_inputs:
        rail = state["rails"].setdefault(rail_name, _empty_state()["rails"][rail_name])
        prior_count = int(rail.get("first_row_count") or 0)
        if prior_count > 0:
            continue  # sealed — observation only, no re-fire
        if probe["row_count"] < 1:
            continue
        # Transition: 0 → N>=1.
        rail["first_row_count"] = probe["row_count"]
        rail["first_detected_at_utc"] = now_iso
        rail["earliest_row_occurred_at"] = probe["earliest_row_occurred_at"]
        for key in extra_keys:
            if key in probe:
                rail[key] = probe[key]
        transitions.append(
            {
                "rail": rail_name,
                "detected_at_utc": now_iso,
                "row_count": probe["row_count"],
                "earliest_row_occurred_at": probe["earliest_row_occurred_at"],
            }
        )

    if transitions:
        state["history"].extend(transitions)
        if not state.get("first_detected_at_utc"):
            state["first_detected_at_utc"] = now_iso
    return state, transitions


def write_state(path: Path, state: dict[str, Any]) -> None:
    """Atomic write — temp file + rename so partial writes never land."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def post_slack_notification(transitions: list[dict[str, Any]]) -> bool:
    """POST a short Slack message; return True on success, False otherwise.

    Failures are warned and swallowed — Slack outage must NOT red-line
    the cron and must NOT block detection-event persistence.
    """
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        logger.info("SLACK_WEBHOOK_URL not set; skipping notification")
        return False
    if not transitions:
        return False
    lines = ["[jpcite Wave 49] first real transaction observed"]
    for tr in transitions:
        rail_label = "G4 — x402 USDC payment" if tr["rail"] == RAIL_G4 else "G5 — Wallet ¥ topup"
        lines.append(
            f"  - {rail_label}: row_count={tr['row_count']} "
            f"earliest={tr.get('earliest_row_occurred_at')}"
        )
    body = {"text": "\n".join(lines)}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — operator-configured webhook
        webhook,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            ok = 200 <= int(resp.status) < 300
            if not ok:
                logger.warning("slack POST returned status=%s", resp.status)
            return ok
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        logger.warning("slack POST failed: %s", exc)
        return False


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Wave 49 G4/G5 first-transaction observation watchdog "
            "(observation only, never writes to ledger tables)."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run the probe + state transition (default behaviour).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Probe counts + print proposed state without touching disk or Slack.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("AUTONOMATH_DB_PATH") or DEFAULT_DB_PATH),
        help="Path to autonomath.db (read-only).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to first_txn_detected.json detection event file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose logging.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    _setup_logging(args.verbose)

    db_path: Path = args.db
    output_path: Path = args.output
    now_iso = _utcnow_iso()

    if not db_path.exists():
        if args.dry_run:
            logger.info(
                "dry-run: db not present at %s; emitting synthetic zero-state",
                db_path,
            )
            g4_probe = {
                "table": TABLE_G4,
                "row_count": 0,
                "earliest_row_occurred_at": None,
                "endpoint_path_sample": None,
                "schema_present": False,
            }
            g5_probe = {
                "table": TABLE_G5,
                "row_count": 0,
                "earliest_row_occurred_at": None,
                "txn_type_filter": G5_TXN_TYPE_FILTER,
                "schema_present": False,
            }
        else:
            logger.error("db not found: %s", db_path)
            return 2
    else:
        with _connect_readonly(db_path) as conn:
            g4_probe = probe_g4_x402_payment(conn)
            g5_probe = probe_g5_wallet_topup(conn)

    previous = load_previous_state(output_path)
    new_state, transitions = compute_transitions(previous, g4_probe, g5_probe, now_iso)

    logger.info(
        "probe g4=%s rows / g5=%s rows / transitions=%d",
        g4_probe["row_count"],
        g5_probe["row_count"],
        len(transitions),
    )
    if args.verbose:
        logger.debug("g4_probe=%s", json.dumps(g4_probe))
        logger.debug("g5_probe=%s", json.dumps(g5_probe))

    if args.dry_run:
        report = {
            "dry_run": True,
            "now_utc": now_iso,
            "db_path": str(db_path),
            "output_path": str(output_path),
            "g4_probe": g4_probe,
            "g5_probe": g5_probe,
            "transitions": transitions,
            "proposed_state": new_state,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))  # noqa: T201
        return 0

    write_state(output_path, new_state)
    if transitions:
        ok = post_slack_notification(transitions)
        logger.info(
            "wrote %s with %d new transition(s); slack=%s",
            output_path,
            len(transitions),
            "ok" if ok else "skipped/failed",
        )
    else:
        logger.info("wrote %s (no new transitions)", output_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.check and not args.dry_run:
        # default to --check behaviour when neither flag is set
        args.check = True
    try:
        return run(args)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2
    except sqlite3.OperationalError as exc:
        logger.error("sqlite error: %s", exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())
