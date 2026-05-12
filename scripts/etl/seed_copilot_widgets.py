"""Seed 4 host-SaaS embed widgets for the Dim S copilot scaffold (Wave 47).

Materialises the initial widget catalogue for the Dim S "embedded copilot
scaffold" surface (per ``feedback_copilot_scaffold_only_no_llm.md``) on
top of the storage layer added by ``scripts/migrations/279_copilot_scaffold.sql``.

Seeded widgets
--------------
  * freee          (会計freee 内 embed)
  * moneyforward   (MF クラウド会計 内 embed)
  * notion         (Notion ページ内 embed)
  * slack          (Slack DM/Channel 内 embed via App Home)

Each row registers ``embed_url`` + ``mcp_proxy_url`` + ``oauth_scope``
only — the widget itself runs on the customer side and calls our MCP
proxy. **No LLM API is ever invoked from operator-side** (per
``feedback_copilot_scaffold_only_no_llm`` / ``feedback_no_operator_llm_api``).

Idempotency
-----------
Re-running the seeder is a no-op if the rows already exist. ``--dry-run``
plans only. ``--force`` upserts even when the row already exists (used
when ``embed_url`` / ``mcp_proxy_url`` rotates).

Usage
-----
    python scripts/etl/seed_copilot_widgets.py            # apply
    python scripts/etl/seed_copilot_widgets.py --dry-run  # plan only
    python scripts/etl/seed_copilot_widgets.py --force    # upsert
    python scripts/etl/seed_copilot_widgets.py --db PATH  # custom db

JSON output (final stdout line)
-------------------------------
    {
      "dim": "S",
      "wave": 47,
      "dry_run": <bool>,
      "force": <bool>,
      "widgets": [
        {"host_saas": "...", "action": "inserted|updated|noop"}
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

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
LOG = logging.getLogger("seed_copilot_widgets")

_BASE = "https://jpcite.ai"

# Canonical 4-widget seed. Order is stable across runs (alphabetical by
# host_saas) so a diff stays trivial to review.
_WIDGETS: tuple[dict[str, str], ...] = (
    {
        "host_saas": "freee",
        "embed_url": f"{_BASE}/embed/copilot/freee",
        "mcp_proxy_url": f"{_BASE}/mcp/proxy/freee",
        "oauth_scope": "read:invoice read:journal read:taxrate",
    },
    {
        "host_saas": "moneyforward",
        "embed_url": f"{_BASE}/embed/copilot/moneyforward",
        "mcp_proxy_url": f"{_BASE}/mcp/proxy/moneyforward",
        "oauth_scope": "read:bookkeeping read:tax read:expense",
    },
    {
        "host_saas": "notion",
        "embed_url": f"{_BASE}/embed/copilot/notion",
        "mcp_proxy_url": f"{_BASE}/mcp/proxy/notion",
        "oauth_scope": "read:database read:page",
    },
    {
        "host_saas": "slack",
        "embed_url": f"{_BASE}/embed/copilot/slack",
        "mcp_proxy_url": f"{_BASE}/mcp/proxy/slack",
        "oauth_scope": "chat:write commands users:read",
    },
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed Dim S copilot scaffold widgets")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="Upsert even when row exists")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _upsert_widget(
    conn: sqlite3.Connection,
    widget: dict[str, str],
    *,
    dry_run: bool,
    force: bool,
) -> str:
    """Return action: inserted | updated | noop."""
    cur = conn.execute(
        "SELECT widget_id, embed_url, mcp_proxy_url, oauth_scope "
        "FROM am_copilot_widget_config WHERE host_saas = ?",
        (widget["host_saas"],),
    )
    row = cur.fetchone()
    if row is None:
        if not dry_run:
            conn.execute(
                "INSERT INTO am_copilot_widget_config "
                "(host_saas, embed_url, mcp_proxy_url, oauth_scope) "
                "VALUES (?, ?, ?, ?)",
                (
                    widget["host_saas"],
                    widget["embed_url"],
                    widget["mcp_proxy_url"],
                    widget["oauth_scope"],
                ),
            )
        return "inserted"

    # Row exists. Are the values identical?
    _wid, embed_url, mcp_proxy_url, oauth_scope = row
    if (
        embed_url == widget["embed_url"]
        and mcp_proxy_url == widget["mcp_proxy_url"]
        and oauth_scope == widget["oauth_scope"]
    ):
        return "noop"

    if not force:
        # Drift but no --force: report noop and keep current row.
        return "noop"

    if not dry_run:
        conn.execute(
            "UPDATE am_copilot_widget_config "
            "SET embed_url = ?, mcp_proxy_url = ?, oauth_scope = ?, "
            "    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE host_saas = ?",
            (
                widget["embed_url"],
                widget["mcp_proxy_url"],
                widget["oauth_scope"],
                widget["host_saas"],
            ),
        )
    return "updated"


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
            "dim": "S",
            "wave": 47,
            "dry_run": ns.dry_run,
            "force": ns.force,
            "widgets": [],
        }
        print(json.dumps(report, ensure_ascii=False))
        return 0

    actions: list[dict[str, str]] = []
    conn = _connect(db_path)
    try:
        for widget in _WIDGETS:
            act = _upsert_widget(conn, widget, dry_run=ns.dry_run, force=ns.force)
            actions.append({"host_saas": widget["host_saas"], "action": act})
        if not ns.dry_run:
            conn.commit()
    finally:
        conn.close()

    report = {
        "dim": "S",
        "wave": 47,
        "dry_run": ns.dry_run,
        "force": ns.force,
        "widgets": actions,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
