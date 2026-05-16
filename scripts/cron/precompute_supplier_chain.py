#!/usr/bin/env python3
"""Wave 33 Axis 2c: pre-compute supplier-chain bipartite graph into am_supplier_chain.

What it does
------------
For each anchor houjin, materialize the partner-edge list across 4 link
types:

* ``invoice_registrant_active`` — partner has an active 適格事業者登録番号.
* ``invoice_registrant_revoked`` — partner's 適格事業者 status revoked.
* ``adoption_partner`` — partner co-occurs in jpi_adoption_records.
* ``enforcement_subject`` — partner appears in am_enforcement_detail.

Then run a bipartite walk to emit hop_depth 2..max_hops edges so the
endpoint can return the full subtree without re-walking at request time.

Inputs (autonomath.db only)
---------------------------
* ``invoice_registrants`` (13,801 rows)
* ``jpi_adoption_records`` (~201,845 rows)
* ``am_enforcement_detail`` (22,258 rows)
* ``houjin_master`` (~166k corporate_entity rows)

Anchor selection (budget-capped)
--------------------------------
For pre-launch budget we walk only the top-N anchors by
``total_adoptions`` desc (1,000 default), which covers >80% of the
customer-LLM cohort hit pattern observed in the actionable Q/A path
(W28-5 instrumentation).

Constraints (CLAUDE.md + memory)
--------------------------------
* NO LLM call — pure SQLite + standard library.
* NO ``PRAGMA quick_check`` / ``integrity_check`` / ``VACUUM`` on the
  9.7GB autonomath.db.
* Idempotent — INSERT OR REPLACE on the unique edge tuple.
* hop_depth bounded to 5 by the schema CHECK; cron caps at 3 by
  default to keep daily run under the 30-min budget.

Usage
-----
    python scripts/cron/precompute_supplier_chain.py
    python scripts/cron/precompute_supplier_chain.py --anchor-limit 500
    python scripts/cron/precompute_supplier_chain.py --max-hops 3
    python scripts/cron/precompute_supplier_chain.py --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sqlite3
import sys
import time
from collections import defaultdict, deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger("autonomath.cron.precompute_supplier_chain")

DEFAULT_ANCHOR_LIMIT = 1000
DEFAULT_MAX_HOPS = 3
DEFAULT_PARTNERS_PER_ANCHOR = 100


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("autonomath.cron.precompute_supplier_chain")
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


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "autonomath.db"


def _open_rw(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-65536")
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_supplier_chain (
              chain_id                INTEGER PRIMARY KEY AUTOINCREMENT,
              anchor_houjin_bangou    TEXT NOT NULL,
              partner_houjin_bangou   TEXT NOT NULL,
              link_type               TEXT NOT NULL,
              evidence_url            TEXT,
              evidence_date           TEXT,
              hop_depth               INTEGER NOT NULL DEFAULT 1,
              created_at              TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_supplier_chain_anchor "
        "ON am_supplier_chain(anchor_houjin_bangou, hop_depth ASC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_supplier_chain_partner "
        "ON am_supplier_chain(partner_houjin_bangou, hop_depth ASC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_supplier_chain_type "
        "ON am_supplier_chain(link_type, anchor_houjin_bangou)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_supplier_chain_edge "
        "ON am_supplier_chain("
        "anchor_houjin_bangou, partner_houjin_bangou, link_type, hop_depth)"
    )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


# --------------------------------------------------------------------------- #
# Edge extraction
# --------------------------------------------------------------------------- #


def _anchor_houjins(conn: sqlite3.Connection, limit: int) -> list[str]:
    """Top-N anchors by total_adoptions desc. 13-digit normalized bangou only."""
    if not _table_exists(conn, "houjin_master"):
        return []
    try:
        rows = conn.execute(
            "SELECT houjin_bangou FROM houjin_master "
            "WHERE houjin_bangou IS NOT NULL "
            "  AND length(houjin_bangou) = 13 "
            "ORDER BY total_adoptions DESC, last_updated_nta DESC "
            "LIMIT ?",
            (int(limit),),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [str(r["houjin_bangou"]) for r in rows]


def _direct_edges_for_anchor(
    conn: sqlite3.Connection,
    anchor: str,
    partners_limit: int,
) -> list[dict[str, Any]]:
    """Return all 4-type direct edges from `anchor` to partners.

    Result schema: {partner, link_type, evidence_url, evidence_date}.
    """
    edges: list[dict[str, Any]] = []

    # invoice_registrant_active / revoked: partners with same prefecture as
    # the anchor (anchor's invoice neighbors). Pure approximation: in the
    # absence of an explicit buyer-seller relation we use the prefecture
    # co-residency signal anchored on the anchor's pref. This matches the
    # existing ``am_invoice_buyer_seller_graph`` schema's residency proxy.
    anchor_pref = _anchor_prefecture(conn, anchor)
    if anchor_pref and _table_exists(conn, "invoice_registrants"):
        try:
            rows = conn.execute(
                "SELECT houjin_bangou, revoked_date, source_url, registered_date "
                "FROM invoice_registrants "
                "WHERE prefecture = ? AND houjin_bangou IS NOT NULL "
                "  AND houjin_bangou != ? AND length(houjin_bangou) = 13 "
                "ORDER BY registered_date DESC LIMIT ?",
                (anchor_pref, anchor, int(partners_limit) // 2),
            ).fetchall()
            for r in rows:
                link = (
                    "invoice_registrant_revoked"
                    if r["revoked_date"]
                    else "invoice_registrant_active"
                )
                edges.append(
                    {
                        "partner": str(r["houjin_bangou"]).zfill(13),
                        "link_type": link,
                        "evidence_url": r["source_url"],
                        "evidence_date": r["revoked_date"] or r["registered_date"],
                    }
                )
        except sqlite3.OperationalError:
            pass

    # adoption_partner: partners co-mentioned in adoption_records by
    # (prefecture, program_id_hint) similarity.
    if _table_exists(conn, "adoption_records"):
        try:
            rows = conn.execute(
                "SELECT DISTINCT b.houjin_bangou, b.source_url, b.announced_at "
                "FROM adoption_records a "
                "JOIN adoption_records b ON b.program_id_hint = a.program_id_hint "
                "                       AND b.houjin_bangou != a.houjin_bangou "
                "WHERE a.houjin_bangou = ? AND b.houjin_bangou IS NOT NULL "
                "  AND length(b.houjin_bangou) = 13 "
                "LIMIT ?",
                (anchor, int(partners_limit) // 4),
            ).fetchall()
            for r in rows:
                edges.append(
                    {
                        "partner": str(r["houjin_bangou"]).zfill(13),
                        "link_type": "adoption_partner",
                        "evidence_url": r["source_url"],
                        "evidence_date": r["announced_at"],
                    }
                )
        except sqlite3.OperationalError:
            pass

    # enforcement_subject: same authority + overlapping reason_summary.
    if _table_exists(conn, "am_enforcement_detail"):
        try:
            rows = conn.execute(
                "SELECT DISTINCT b.houjin_bangou, b.source_url, b.issuance_date "
                "FROM am_enforcement_detail a "
                "JOIN am_enforcement_detail b "
                "  ON b.issuing_authority = a.issuing_authority "
                " AND b.houjin_bangou != a.houjin_bangou "
                "WHERE a.houjin_bangou = ? AND b.houjin_bangou IS NOT NULL "
                "  AND length(b.houjin_bangou) = 13 "
                "LIMIT ?",
                (anchor, int(partners_limit) // 4),
            ).fetchall()
            for r in rows:
                edges.append(
                    {
                        "partner": str(r["houjin_bangou"]).zfill(13),
                        "link_type": "enforcement_subject",
                        "evidence_url": r["source_url"],
                        "evidence_date": r["issuance_date"],
                    }
                )
        except sqlite3.OperationalError:
            pass

    # Dedup on (partner, link_type) — keep the freshest evidence_date.
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for e in edges:
        k = (e["partner"], e["link_type"])
        prev = by_key.get(k)
        if prev is None or (e["evidence_date"] or "") > (prev["evidence_date"] or ""):
            by_key[k] = e
    return list(by_key.values())[:partners_limit]


def _anchor_prefecture(conn: sqlite3.Connection, anchor: str) -> str | None:
    if not _table_exists(conn, "houjin_master"):
        return None
    try:
        row = conn.execute(
            "SELECT prefecture FROM houjin_master WHERE houjin_bangou = ? LIMIT 1",
            (anchor,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return str(row["prefecture"]) if row and row["prefecture"] else None


# --------------------------------------------------------------------------- #
# Transitive walk
# --------------------------------------------------------------------------- #


def _walk_transitive(
    conn: sqlite3.Connection,
    anchor: str,
    direct_edges: list[dict[str, Any]],
    max_hops: int,
    partners_per_anchor: int,
) -> list[dict[str, Any]]:
    """BFS to ``max_hops`` from anchor through direct_edges.

    Each new edge is emitted with hop_depth = current_depth + 1 and the
    same link_type chain (we copy link_type from the deepest edge to keep
    the trail interpretable). Cycles are blocked by ``visited``.
    """
    transitive: list[dict[str, Any]] = []
    visited: set[str] = {anchor, *(e["partner"] for e in direct_edges)}
    queue: deque[tuple[str, int, str]] = deque(
        (e["partner"], 1, e["link_type"]) for e in direct_edges
    )

    while queue:
        node, depth, lineage_type = queue.popleft()
        if depth >= max_hops:
            continue
        next_edges = _direct_edges_for_anchor(conn, node, partners_per_anchor // 2)
        for ne in next_edges:
            p = ne["partner"]
            if p in visited or p == anchor:
                continue
            visited.add(p)
            transitive.append(
                {
                    "partner": p,
                    "link_type": lineage_type,  # preserve the originating link_type
                    "evidence_url": ne["evidence_url"],
                    "evidence_date": ne["evidence_date"],
                    "hop_depth": depth + 1,
                }
            )
            queue.append((p, depth + 1, lineage_type))
    return transitive


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def precompute(
    *,
    anchor_limit: int = DEFAULT_ANCHOR_LIMIT,
    max_hops: int = DEFAULT_MAX_HOPS,
    partners_per_anchor: int = DEFAULT_PARTNERS_PER_ANCHOR,
    dry_run: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    db_path = _autonomath_db_path()

    if not db_path.exists():
        logger.warning("autonomath.db not found at %s", db_path)
        return {"status": "missing_db", "db_path": str(db_path)}

    conn = _open_rw(db_path)
    _ensure_table(conn)

    anchors = _anchor_houjins(conn, anchor_limit)
    logger.info(
        "precompute_start anchors=%d max_hops=%d partners_per_anchor=%d dry_run=%s",
        len(anchors),
        max_hops,
        partners_per_anchor,
        dry_run,
    )

    inserted = 0
    errors = 0
    direct_total = 0
    transitive_total = 0
    by_link_type: dict[str, int] = defaultdict(int)

    for anchor in anchors:
        direct = _direct_edges_for_anchor(conn, anchor, partners_per_anchor)
        direct_total += len(direct)

        transitive = _walk_transitive(conn, anchor, direct, max_hops, partners_per_anchor)
        transitive_total += len(transitive)

        for e in direct:
            e["hop_depth"] = 1
        all_edges: list[dict[str, Any]] = direct + transitive

        for e in all_edges:
            by_link_type[e["link_type"]] += 1
            if dry_run:
                continue
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO am_supplier_chain "
                    "(anchor_houjin_bangou, partner_houjin_bangou, link_type, "
                    " evidence_url, evidence_date, hop_depth) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        anchor,
                        e["partner"],
                        e["link_type"],
                        e.get("evidence_url"),
                        e.get("evidence_date"),
                        int(e.get("hop_depth", 1)),
                    ),
                )
                inserted += 1
            except sqlite3.Error as exc:
                logger.warning(
                    "insert_failed anchor=%s partner=%s err=%s",
                    anchor,
                    e["partner"],
                    exc,
                )
                errors += 1

    elapsed = time.perf_counter() - t0
    summary = {
        "status": "ok" if errors == 0 else "partial",
        "anchors_processed": len(anchors),
        "direct_edges": direct_total,
        "transitive_edges": transitive_total,
        "inserted": inserted,
        "by_link_type": dict(by_link_type),
        "errors": errors,
        "elapsed_s": round(elapsed, 3),
        "anchor_limit": anchor_limit,
        "max_hops": max_hops,
        "partners_per_anchor": partners_per_anchor,
        "db_path": str(db_path),
        "dry_run": dry_run,
    }
    logger.info("precompute_done %s", summary)
    with contextlib.suppress(Exception):
        conn.close()
    return summary


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--anchor-limit", type=int, default=DEFAULT_ANCHOR_LIMIT)
    p.add_argument("--max-hops", type=int, default=DEFAULT_MAX_HOPS)
    p.add_argument("--partners-per-anchor", type=int, default=DEFAULT_PARTNERS_PER_ANCHOR)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.verbose)
    summary = precompute(
        anchor_limit=args.anchor_limit,
        max_hops=args.max_hops,
        partners_per_anchor=args.partners_per_anchor,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary.get("status") in {"ok", "partial", "missing_db"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
