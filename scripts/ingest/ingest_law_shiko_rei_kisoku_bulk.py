#!/usr/bin/env python3
"""ingest_law_shiko_rei_kisoku_bulk.py — Bulk-ingest 政令 (施行令) and 施行規則
articles into am_law_article using the existing single-law ingestor as a library.

Strategy
--------
1. Select candidate laws from am_law where canonical_name suffix is 施行令 or 施行規則
   AND e_gov_lawid is populated AND the law currently has 0 articles ingested.
2. For each, decide article_kind by suffix:
     - 施行令  -> enforcement_order
     - 施行規則 -> enforcement_regulation
3. Fetch e-Gov XML, parse, UPSERT.
4. Sleep 1.1 s between fetches (e-Gov is public infra; be conservative).
5. Skip silently on 404 / parse failure / network error so the batch keeps moving.
6. Idempotent — re-runs touch nothing unless XML now parses more.

Also includes a --retag-existing pass that flips article_kind='main' to the
correct enforcement_* label for laws that were previously ingested via the
hardcoded-main-only version of the script.

NO Anthropic API. NO LLM.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ingest"))

from ingest_law_articles_egov import (  # noqa: E402
    fetch_law_xml,
    parse_articles,
)

DEFAULT_DB = REPO_ROOT / "autonomath.db"
SLEEP_BETWEEN = 1.0  # seconds between e-Gov requests (be conservative)

_LOG = logging.getLogger("ingest_law_shiko_rei_kisoku_bulk")


def kind_for(canonical_name: str) -> str | None:
    if canonical_name.endswith("施行令"):
        return "enforcement_order"
    if canonical_name.endswith("施行規則"):
        return "enforcement_regulation"
    return None


def select_candidates(con: sqlite3.Connection, *, only_empty: bool, limit: int | None):
    """Return (canonical_id, canonical_name, e_gov_lawid, kind) tuples to process."""
    sql = """
        SELECT l.canonical_id, l.canonical_name, l.e_gov_lawid
        FROM am_law l
        WHERE (l.canonical_name LIKE '%施行令' OR l.canonical_name LIKE '%施行規則')
          AND l.e_gov_lawid IS NOT NULL AND l.e_gov_lawid != ''
    """
    if only_empty:
        sql += """
          AND l.canonical_id NOT IN (SELECT DISTINCT law_canonical_id FROM am_law_article)
        """
    sql += " ORDER BY l.canonical_name"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = con.execute(sql).fetchall()
    out = []
    for cid, cname, lid in rows:
        kind = kind_for(cname)
        if kind is None:
            continue
        out.append((cid, cname, lid, kind))
    return out


def retag_existing(con: sqlite3.Connection) -> int:
    """Re-tag article_kind for laws whose name ends in 施行令/施行規則 but whose
    rows are tagged 'main'. Idempotent."""
    sql_order = """
        UPDATE am_law_article
        SET article_kind='enforcement_order'
        WHERE article_kind='main'
          AND law_canonical_id IN (
              SELECT canonical_id FROM am_law WHERE canonical_name LIKE '%施行令'
          )
    """
    sql_reg = """
        UPDATE am_law_article
        SET article_kind='enforcement_regulation'
        WHERE article_kind='main'
          AND law_canonical_id IN (
              SELECT canonical_id FROM am_law WHERE canonical_name LIKE '%施行規則'
          )
    """
    con.execute("BEGIN IMMEDIATE")
    try:
        cur = con.execute(sql_order)
        n_order = cur.rowcount
        cur = con.execute(sql_reg)
        n_reg = cur.rowcount
        con.commit()
    except Exception:
        con.rollback()
        raise
    print(f"[retag] enforcement_order +{n_order}  enforcement_regulation +{n_reg}")
    return n_order + n_reg


def fetch_and_parse(
    canonical_id: str,
    egov_lawid: str,
    kind: str,
) -> tuple[list[dict], str]:
    """Fetch e-Gov XML and parse to articles. Returns (articles, status).

    Pure I/O + parse, no DB. Safe to call without holding the DB lock.
    """
    try:
        xml_bytes = fetch_law_xml(egov_lawid)
    except FileNotFoundError:
        return ([], "404")
    except Exception as e:
        _LOG.warning("fetch_failed cid=%s err=%s", canonical_id, e)
        return ([], f"fetch_err:{type(e).__name__}")

    try:
        articles = parse_articles(xml_bytes)
    except Exception as e:
        _LOG.warning("parse_failed cid=%s err=%s", canonical_id, e)
        return ([], f"parse_err:{type(e).__name__}")

    if not articles:
        return ([], "no_articles")

    return (articles, "ok")


def write_all(
    db: str,
    plan: list[tuple[str, str, str, list[dict]]],
    fetched_at: str,
) -> tuple[int, dict[str, int], list[tuple[str, str]]]:
    """Take a fully-parsed plan and UPSERT it in a SINGLE BEGIN IMMEDIATE.

    plan = [(canonical_id, egov_lawid, kind, articles), ...]

    Returns (total_upserted, by_kind, failed_list).
    """
    con = sqlite3.connect(db, timeout=600)
    con.execute("PRAGMA busy_timeout = 600000")

    total = 0
    by_kind: dict[str, int] = {"enforcement_order": 0, "enforcement_regulation": 0}
    failed: list[tuple[str, str]] = []

    con.execute("BEGIN IMMEDIATE")
    try:
        for canonical_id, egov_lawid, kind, articles in plan:
            for art in articles:
                source_url = (
                    f"https://laws.e-gov.go.jp/law/{egov_lawid}#Mp-At_{art['article_number']}"
                )
                try:
                    con.execute(
                        """
                        INSERT INTO am_law_article (
                            law_canonical_id, article_number, article_number_sort,
                            title, text_summary, text_full,
                            source_url, source_fetched_at, article_kind
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(law_canonical_id, article_number) DO UPDATE SET
                            article_number_sort = excluded.article_number_sort,
                            title = excluded.title,
                            text_summary = excluded.text_summary,
                            text_full = excluded.text_full,
                            source_url = excluded.source_url,
                            source_fetched_at = excluded.source_fetched_at,
                            article_kind = excluded.article_kind
                    """,
                        (
                            canonical_id,
                            art["article_number"],
                            art["article_number_sort"],
                            art["title"],
                            art["text_full"][:500],
                            art["text_full"],
                            source_url,
                            fetched_at,
                            kind,
                        ),
                    )
                    total += 1
                    by_kind[kind] = by_kind.get(kind, 0) + 1
                except Exception as e:
                    failed.append((f"{canonical_id}:{art.get('article_number')}", str(e)))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return total, by_kind, failed


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument(
        "--limit", type=int, default=120, help="Max number of laws to ingest in this run."
    )
    p.add_argument(
        "--include-non-empty",
        action="store_true",
        help="Also re-fetch laws that already have any articles ingested.",
    )
    p.add_argument(
        "--retag-only",
        action="store_true",
        help="Skip ingestion; only re-tag main->enforcement_* on existing rows.",
    )
    p.add_argument(
        "--no-retag", action="store_true", help="Do not perform retag pass before ingestion."
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    con = sqlite3.connect(args.db, timeout=300)
    con.execute("PRAGMA busy_timeout = 300000")

    if not args.no_retag:
        retag_existing(con)

    if args.retag_only:
        con.close()
        return 0

    candidates = select_candidates(con, only_empty=not args.include_non_empty, limit=args.limit)
    print(f"[bulk] candidates={len(candidates)}  dry_run={args.dry_run}")
    con.close()  # release any read transaction held by select_candidates

    if args.dry_run:
        return 0

    # PHASE 1: fetch + parse all XMLs (no DB lock held during e-Gov I/O)
    fetched_at = datetime.now(UTC).isoformat()
    plan: list[tuple[str, str, str, list[dict]]] = []
    skipped: list[tuple[str, str]] = []

    for i, (cid, cname, lid, kind) in enumerate(candidates, 1):
        t0 = time.time()
        articles, status = fetch_and_parse(cid, lid, kind)
        dt = time.time() - t0
        print(
            f"[fetch {i:>3}/{len(candidates)}] {cid:<44} kind={kind:<22} "
            f"xml={len(articles):>4} status={status:<14} {dt:.1f}s",
            flush=True,
        )
        if status == "ok":
            plan.append((cid, lid, kind, articles))
        else:
            skipped.append((cid, status))
        if i < len(candidates):
            time.sleep(SLEEP_BETWEEN)

    print(f"[bulk] fetch_phase_done plan_size={len(plan)} skipped={len(skipped)}", flush=True)

    # PHASE 2: SINGLE write transaction for everything
    total_articles = sum(len(p[3]) for p in plan)
    print(f"[bulk] writing {total_articles} articles in single tx ...", flush=True)
    t_write = time.time()
    total_upserted, by_kind, failed = write_all(args.db, plan, fetched_at)
    print(f"[bulk] write_done in {time.time() - t_write:.1f}s", flush=True)

    print("=== summary ===")
    print(f"laws processed: {len(candidates)}  ok: {len(plan)}  skipped: {len(skipped)}")
    print(f"total upserted: {total_upserted}")
    for k, v in by_kind.items():
        print(f"  {k}: +{v}")
    if failed:
        print(f"failed rows: {len(failed)} (first 10)")
        for fk, fe in failed[:10]:
            print(f"  {fk}: {fe[:80]}")
    if skipped:
        print("skipped (first 20):")
        for cid, st in skipped[:20]:
            print(f"  {cid:<44} {st}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
