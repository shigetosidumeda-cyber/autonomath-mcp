"""Seed AX Layer 3 substrate for Dim W (Wave 47): WebMCP + A2A + observability.

Materialises the initial three-axis seed for the Dim W "AX Layer 3"
surface (per ``feedback_ax_4_pillars.md``) on top of the storage layer
added by ``scripts/migrations/283_ax_layer3.sql``.

Three axes seeded
-----------------
  * am_webmcp_endpoint:        3 endpoints (sse / streamable_http / sse health)
  * am_a2a_handshake_log:      2 handshake template rows (claude/cursor)
  * am_observability_metric:   8 metric rows (Layer 3 dashboard seed)

LLM-0 discipline
----------------
Pure config + audit seed. NO LLM API ever invoked. Per
``feedback_no_operator_llm_api`` and ``feedback_autonomath_no_api_use``.

Idempotency
-----------
Re-running is a no-op for `am_webmcp_endpoint` (UNIQUE on (path, transport))
and an append for the two append-only audit tables. ``--dry-run`` plans
only. ``--force`` re-inserts handshake / metric rows even if a same-day
row already exists (operator forensics only).

Usage
-----
    python scripts/etl/seed_ax_layer3.py            # apply
    python scripts/etl/seed_ax_layer3.py --dry-run  # plan only
    python scripts/etl/seed_ax_layer3.py --force    # append new audit rows
    python scripts/etl/seed_ax_layer3.py --db PATH  # custom db

JSON output (final stdout line)
-------------------------------
    {
      "dim": "W",
      "wave": 47,
      "dry_run": <bool>,
      "force": <bool>,
      "webmcp_endpoints": [...],
      "a2a_handshakes": [...],
      "observability_metrics": [...]
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
LOG = logging.getLogger("seed_ax_layer3")

# Canonical 3 WebMCP endpoint seed. Stable order (alphabetical by path)
# so review diffs are trivial.
_WEBMCP_ENDPOINTS: tuple[dict[str, str], ...] = (
    {
        "path": "/v1/mcp/sse",
        "transport": "sse",
        "capability_tag": "tools",
        "description": "WebMCP SSE transport (browser embed; default for MCP 2025-06-18 clients).",
    },
    {
        "path": "/v1/mcp/sse/health",
        "transport": "sse",
        "capability_tag": "access",
        "description": "WebMCP SSE health probe (transport liveness, no tool invocation).",
    },
    {
        "path": "/v1/mcp/streamable_http",
        "transport": "streamable_http",
        "capability_tag": "tools",
        "description": "WebMCP Streamable HTTP transport (Wave 16 A8; long-poll fallback).",
    },
)

# 2 A2A handshake template rows. These are SEED rows showing the
# canonical capability negotiation shape; real production handshakes
# get appended by runtime. We seed them with succeeded_at set so the
# initial dashboard tile is non-empty.
_A2A_HANDSHAKES: tuple[dict[str, str], ...] = (
    {
        "source_agent": "claude-3.5-sonnet",
        "target_agent": "jpcite-mcp",
        "capability_negotiated": "tools/search_programs",
    },
    {
        "source_agent": "cursor-mcp-client",
        "target_agent": "jpcite-mcp",
        "capability_negotiated": "resources/list",
    },
)

# 8 observability metric rows (initial dashboard seed). One per AX
# pillar (4) plus four Layer 3 specific signals (webmcp / a2a /
# handshake_success / handshake_failure).
_OBSERVABILITY_METRICS: tuple[dict[str, str | float], ...] = (
    {"metric_name": "ax.layer3.webmcp.endpoints_active", "value": 3.0, "unit": "count"},
    {"metric_name": "ax.layer3.a2a.handshakes_total", "value": 2.0, "unit": "count"},
    {"metric_name": "ax.layer3.a2a.handshake_success_rate", "value": 1.0, "unit": "ratio"},
    {"metric_name": "ax.layer3.observability.metrics_emitted", "value": 8.0, "unit": "count"},
    {"metric_name": "ax.pillar.access.surfaces_active", "value": 12.0, "unit": "count"},
    {"metric_name": "ax.pillar.context.surfaces_active", "value": 9.0, "unit": "count"},
    {"metric_name": "ax.pillar.tools.surfaces_active", "value": 139.0, "unit": "count"},
    {"metric_name": "ax.pillar.orchestration.surfaces_active", "value": 6.0, "unit": "count"},
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed Dim W AX Layer 3 substrate")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--force",
        action="store_true",
        help="Append new handshake/metric rows even if a same-day seed row exists",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _upsert_webmcp_endpoint(
    conn: sqlite3.Connection,
    row: dict[str, str],
    *,
    dry_run: bool,
) -> str:
    cur = conn.execute(
        "SELECT endpoint_id FROM am_webmcp_endpoint WHERE path = ? AND transport = ?",
        (row["path"], row["transport"]),
    )
    existing = cur.fetchone()
    if existing is not None:
        return "noop"
    if not dry_run:
        conn.execute(
            "INSERT INTO am_webmcp_endpoint "
            "(path, transport, capability_tag, description) "
            "VALUES (?, ?, ?, ?)",
            (row["path"], row["transport"], row["capability_tag"], row["description"]),
        )
    return "inserted"


def _maybe_append_handshake(
    conn: sqlite3.Connection,
    row: dict[str, str],
    *,
    dry_run: bool,
    force: bool,
) -> str:
    # Skip if a same-day seed row already exists (idempotent under
    # daily re-run). --force always appends a new audit row.
    if not force:
        cur = conn.execute(
            "SELECT handshake_id FROM am_a2a_handshake_log "
            "WHERE source_agent = ? AND target_agent = ? "
            "  AND capability_negotiated = ? "
            "  AND date(initiated_at) = date('now') "
            "LIMIT 1",
            (row["source_agent"], row["target_agent"], row["capability_negotiated"]),
        )
        if cur.fetchone() is not None:
            return "noop"
    if not dry_run:
        conn.execute(
            "INSERT INTO am_a2a_handshake_log "
            "(source_agent, target_agent, capability_negotiated, "
            " succeeded_at) "
            "VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
            (row["source_agent"], row["target_agent"], row["capability_negotiated"]),
        )
    return "inserted"


def _maybe_append_metric(
    conn: sqlite3.Connection,
    row: dict[str, str | float],
    *,
    dry_run: bool,
    force: bool,
) -> str:
    if not force:
        cur = conn.execute(
            "SELECT metric_id FROM am_observability_metric "
            "WHERE metric_name = ? "
            "  AND date(recorded_at) = date('now') "
            "LIMIT 1",
            (row["metric_name"],),
        )
        if cur.fetchone() is not None:
            return "noop"
    if not dry_run:
        conn.execute(
            "INSERT INTO am_observability_metric (metric_name, value, unit) VALUES (?, ?, ?)",
            (row["metric_name"], row["value"], row["unit"]),
        )
    return "inserted"


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
            "dim": "W",
            "wave": 47,
            "dry_run": ns.dry_run,
            "force": ns.force,
            "webmcp_endpoints": [],
            "a2a_handshakes": [],
            "observability_metrics": [],
        }
        print(json.dumps(report, ensure_ascii=False))
        return 0

    webmcp_actions: list[dict[str, str]] = []
    a2a_actions: list[dict[str, str]] = []
    metric_actions: list[dict[str, str]] = []

    conn = _connect(db_path)
    try:
        for ep in _WEBMCP_ENDPOINTS:
            act = _upsert_webmcp_endpoint(conn, ep, dry_run=ns.dry_run)
            webmcp_actions.append({"path": ep["path"], "transport": ep["transport"], "action": act})
        for hs in _A2A_HANDSHAKES:
            act = _maybe_append_handshake(conn, hs, dry_run=ns.dry_run, force=ns.force)
            a2a_actions.append(
                {
                    "source_agent": hs["source_agent"],
                    "target_agent": hs["target_agent"],
                    "capability_negotiated": hs["capability_negotiated"],
                    "action": act,
                }
            )
        for m in _OBSERVABILITY_METRICS:
            act = _maybe_append_metric(conn, m, dry_run=ns.dry_run, force=ns.force)
            metric_actions.append(
                {
                    "metric_name": str(m["metric_name"]),
                    "value": float(m["value"]),
                    "action": act,
                }
            )
        if not ns.dry_run:
            conn.commit()
    finally:
        conn.close()

    report = {
        "dim": "W",
        "wave": 47,
        "dry_run": ns.dry_run,
        "force": ns.force,
        "webmcp_endpoints": webmcp_actions,
        "a2a_handshakes": a2a_actions,
        "observability_metrics": metric_actions,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
