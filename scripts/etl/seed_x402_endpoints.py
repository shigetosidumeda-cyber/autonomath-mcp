"""Seed x402-gated endpoint configs for the micropayment surface.

Materialises the initial endpoint catalogue for the Dim V "x402 protocol
micropayment" surface (per ``feedback_agent_x402_protocol.md``) on top of
the storage layer added by ``scripts/migrations/282_x402_payment.sql``.

Seeded x402-gated endpoints
---------------------------
  * /v1/audit/workpaper        (audit workpaper composition, 0.01 USDC)
  * /v1/case-studies/search    (awarded case-study search, 0.002 USDC)
  * /v1/programs/prescreen     (profile-based candidate prescreen, 0.002 USDC)
  * /v1/search/semantic        (hybrid semantic search, 0.005 USDC)

Each row registers ``endpoint_path`` + ``required_amount_usdc`` +
``expires_after_seconds`` only. The actual on-chain settlement is handled
by the CF Pages edge function (``functions/x402_handler.ts``); this ETL
seeds the per-endpoint pricing config that the edge handler reads. **No
LLM API is ever invoked from operator-side** (per
``feedback_no_operator_llm_api`` and ``feedback_agent_x402_protocol``).

Idempotency
-----------
Re-running the seeder is a no-op if the rows already exist. ``--dry-run``
plans only. ``--force`` upserts even when the row already exists (used
when ``required_amount_usdc`` / ``expires_after_seconds`` is repriced).

Usage
-----
    python scripts/etl/seed_x402_endpoints.py            # apply
    python scripts/etl/seed_x402_endpoints.py --dry-run  # plan only
    python scripts/etl/seed_x402_endpoints.py --force    # upsert
    python scripts/etl/seed_x402_endpoints.py --db PATH  # custom db

JSON output (final stdout line)
-------------------------------
    {
      "dim": "V",
      "wave": 47,
      "dry_run": <bool>,
      "force": <bool>,
      "endpoints": [
        {"endpoint_path": "...", "action": "inserted|updated|noop"}
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.api.x402_payment import X402_CANONICAL_ENDPOINT_SEEDS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
LOG = logging.getLogger("seed_x402_endpoints")

# Canonical endpoint seed lives with the middleware to prevent registry drift.
_ENDPOINTS = X402_CANONICAL_ENDPOINT_SEEDS
_RETIRED_ENDPOINTS = frozenset({"/v1/programs/search"})


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed Dim V x402 endpoint configs")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="Upsert even when row exists")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _upsert_endpoint(
    conn: sqlite3.Connection,
    endpoint: dict[str, object],
    *,
    dry_run: bool,
    force: bool,
) -> str:
    """Return action: inserted | updated | noop."""
    cur = conn.execute(
        "SELECT required_amount_usdc, expires_after_seconds "
        "FROM am_x402_endpoint_config WHERE endpoint_path = ?",
        (endpoint["endpoint_path"],),
    )
    row = cur.fetchone()
    if row is None:
        if not dry_run:
            conn.execute(
                "INSERT INTO am_x402_endpoint_config "
                "(endpoint_path, required_amount_usdc, expires_after_seconds) "
                "VALUES (?, ?, ?)",
                (
                    endpoint["endpoint_path"],
                    endpoint["required_amount_usdc"],
                    endpoint["expires_after_seconds"],
                ),
            )
        return "inserted"

    existing_amount, existing_ttl = row
    if (
        existing_amount == endpoint["required_amount_usdc"]
        and existing_ttl == endpoint["expires_after_seconds"]
    ):
        return "noop"

    if not force:
        return "noop"

    if not dry_run:
        conn.execute(
            "UPDATE am_x402_endpoint_config "
            "SET required_amount_usdc = ?, expires_after_seconds = ?, "
            "    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE endpoint_path = ?",
            (
                endpoint["required_amount_usdc"],
                endpoint["expires_after_seconds"],
                endpoint["endpoint_path"],
            ),
        )
    return "updated"


def _retire_endpoint(
    conn: sqlite3.Connection,
    endpoint_path: str,
    *,
    dry_run: bool,
) -> str:
    """Disable stale x402 rows that are now owned by route-level gates."""
    row = conn.execute(
        "SELECT enabled FROM am_x402_endpoint_config WHERE endpoint_path = ?",
        (endpoint_path,),
    ).fetchone()
    if row is None:
        return "absent"
    if int(row[0]) == 0:
        return "already_disabled"
    if not dry_run:
        conn.execute(
            "UPDATE am_x402_endpoint_config "
            "SET enabled = 0, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE endpoint_path = ?",
            (endpoint_path,),
        )
    return "disabled"


def main(argv: list[str] | None = None) -> int:
    ns = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if ns.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db_path = Path(ns.db)
    if not db_path.exists():
        LOG.warning("db path %s does not exist; nothing to seed", db_path)
        report = {
            "dim": "V",
            "wave": 47,
            "dry_run": ns.dry_run,
            "force": ns.force,
            "endpoints": [],
        }
        print(json.dumps(report, ensure_ascii=False))
        return 0

    actions: list[dict[str, str]] = []
    conn = _connect(db_path)
    try:
        for endpoint in _ENDPOINTS:
            act = _upsert_endpoint(conn, endpoint, dry_run=ns.dry_run, force=ns.force)
            actions.append(
                {
                    "endpoint_path": str(endpoint["endpoint_path"]),
                    "action": act,
                }
            )
        for endpoint_path in sorted(_RETIRED_ENDPOINTS):
            act = _retire_endpoint(conn, endpoint_path, dry_run=ns.dry_run)
            actions.append(
                {
                    "endpoint_path": endpoint_path,
                    "action": f"retired_{act}",
                }
            )
        if not ns.dry_run:
            conn.commit()
    finally:
        conn.close()

    report = {
        "dim": "V",
        "wave": 47,
        "dry_run": ns.dry_run,
        "force": ns.force,
        "endpoints": actions,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
