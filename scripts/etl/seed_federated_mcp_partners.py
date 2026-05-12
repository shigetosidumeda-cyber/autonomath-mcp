"""Seed the federated-MCP partner catalogue (Dim R, Wave 47).

Loads 6 curated partner rows into ``am_federated_mcp_partner``
(migration 278) so the Dim R recommendation surface can answer
"this query belongs to a different MCP server" handoffs.

Partner shortlist (per feedback_federated_mcp_recommendation)
-------------------------------------------------------------
* freee     -- accounting / invoice (JP)
* mf        -- MoneyForward accounting (JP)
* notion    -- doc / knowledge base
* slack     -- chat / notify
* github    -- code repository / issue / PR
* linear    -- product issue tracker

Hard constraints
----------------
* **NO external MCP server call.** Pure local INSERT into autonomath.db.
  The server_url is recorded for the agent client to call directly;
  jpcite never proxies that traffic.
* **NO LLM API call.** Pure deterministic seed.
* **Idempotent.** ON CONFLICT (partner_id) DO UPDATE refreshes the
  display name / endpoint / capability tag without erasing the historical
  last_health_at value.
* **No legacy brand.** Comments + identifiers use jpcite only.

Usage
-----
    python scripts/etl/seed_federated_mcp_partners.py            # apply
    python scripts/etl/seed_federated_mcp_partners.py --dry-run  # preview
    python scripts/etl/seed_federated_mcp_partners.py --db PATH  # custom db

The script verifies that migration 278 has been applied; if the
``am_federated_mcp_partner`` table is missing it exits non-zero with a
hint to run the migration first.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
LOG = logging.getLogger("seed_federated_mcp_partners")


# Curated 6-partner shortlist. Endpoints use the partner's documented
# canonical MCP server. server_url is intentionally schemeless-free so a
# downstream linter can spot drift. last_health_at is left NULL by the
# seed; the out-of-band health-check cron fills it.
PARTNERS: tuple[tuple[str, str, str, str], ...] = (
    (
        "freee",
        "freee 会計",
        "https://mcp.freee.co.jp/v1",
        "accounting|invoice|tax",
    ),
    (
        "mf",
        "マネーフォワード クラウド",
        "https://mcp.moneyforward.com/v1",
        "accounting|invoice|payroll",
    ),
    (
        "notion",
        "Notion",
        "https://mcp.notion.com/v1",
        "doc|kb|collab",
    ),
    (
        "slack",
        "Slack",
        "https://mcp.slack.com/v1",
        "chat|notify|workflow",
    ),
    (
        "github",
        "GitHub",
        "https://mcp.github.com/v1",
        "code|issue|pr|review",
    ),
    (
        "linear",
        "Linear",
        "https://mcp.linear.app/v1",
        "issue|product|cycle",
    ),
)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def seed(db_path: Path, *, dry_run: bool = False) -> dict[str, int]:
    """Seed the partner catalogue. Returns {'inserted': N, 'updated': M}."""
    conn = sqlite3.connect(str(db_path))
    try:
        if not _table_exists(conn, "am_federated_mcp_partner"):
            raise RuntimeError(
                "am_federated_mcp_partner missing — apply migration "
                "278_federated_mcp.sql first"
            )

        inserted = 0
        updated = 0
        for partner_id, name, server_url, capability_tag in PARTNERS:
            existing = conn.execute(
                "SELECT 1 FROM am_federated_mcp_partner WHERE partner_id = ?",
                (partner_id,),
            ).fetchone()
            if dry_run:
                if existing:
                    updated += 1
                else:
                    inserted += 1
                continue

            if existing:
                conn.execute(
                    """
                    UPDATE am_federated_mcp_partner
                       SET name = ?,
                           server_url = ?,
                           capability_tag = ?,
                           updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
                     WHERE partner_id = ?
                    """,
                    (name, server_url, capability_tag, partner_id),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO am_federated_mcp_partner
                        (partner_id, name, server_url, capability_tag)
                    VALUES (?, ?, ?, ?)
                    """,
                    (partner_id, name, server_url, capability_tag),
                )
                inserted += 1

        if not dry_run:
            conn.commit()
        return {"inserted": inserted, "updated": updated}
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="path to autonomath.db (default: repo root)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="DEBUG logging",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        stats = seed(args.db, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 - top-level CLI guard
        LOG.error("seed failed: %s", exc)
        return 1
    LOG.info(
        "federated_mcp partner seed %s: inserted=%d updated=%d (total=%d)",
        "dry-run" if args.dry_run else "applied",
        stats["inserted"],
        stats["updated"],
        len(PARTNERS),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
