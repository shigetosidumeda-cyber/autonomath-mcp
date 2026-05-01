#!/usr/bin/env python3
"""Incremental e-Gov full-text loader for am_law catalog stubs.

Lifts the 154 / 10,125 (1.5%) full-text coverage one batch at a time. Each
run picks the top-N catalog-stub laws by SEO importance, fetches their
full XML from e-Gov 法令 API v2, parses every <Article> element, and
upserts into ``am_law_article``. Idempotent — laws already loaded are
skipped, so a weekly cron at 600 laws/run saturates the registered
egov_lawid pool (≈ 9,955 stubs) in roughly 17 weeks (~4 months).

Pace history
------------
* Initial: 100 laws/week → ~96 weeks (1.85 years) saturation. Conservative
  while we validated parser stability against e-Gov's edge cases.
* 2026-04-29 (Wave 30 +1 audit): bumped default to 300 laws/run. e-Gov's
  published rate budget is ~1 req/sec; at 1.0 s polite sleep + ~1.5 s
  fetch we still finish a 300-law batch in ~12-13 min, well under the
  60-min workflow timeout. Saturation accelerates from ~22 months to
  ~7.5 months.
* 2026-05-01 (B4): bumped default to 600 laws/run. The same polite sleep
  gives a typical batch time around 25 min, so the workflow timeout is
  90 min for safer headroom around slow e-Gov responses or Fly I/O waits.

Why this exists
---------------
Marketing now honestly says "154 full-text + 9,484 catalog stubs" (CLAUDE.md
2026-04-29 phantom-moat audit baseline). The real moat strengthens by
raising the 154 number — every additional law contributes to am_law_article
FTS coverage and to GEO citation surface (laws are linked from program
pages, news posts, and the search_by_law tool).

Honesty constraints (non-negotiable)
------------------------------------
* No fabrication. We only insert articles that actually parsed out of the
  e-Gov XML response. If the XML is empty or malformed, we log + skip.
* CC-BY 4.0 attribution preserved: every article carries a
  ``laws.e-gov.go.jp/law/<lawid>#Mp-At_<num>`` source_url. The display
  layer (``site/_templates/program.html`` / law pages) renders the
  e-Gov attribution string ``出典: e-Gov法令検索 (デジタル庁)`` next to
  the citation.
* No Anthropic / SDK calls. Pure stdlib + ``requests`` + ``ElementTree``.
* Solo + zero-touch: no manual review per law. The XML parser is the
  arbiter — if e-Gov says it's the law, we trust it.
* Polite: 1.0s sleep between fetches (well below e-Gov's published budget).

SEO importance heuristic
------------------------
A law's priority score = (am_law_reference rows × 1) + (am_relation
references_law edges × 5) — the relation edges are higher-quality (resolved
to canonical_id) so they get a bigger weight. Ties broken by
``last_amended_at DESC`` (recently amended → more likely to be searched
for and to drive news posts).

Idempotency
-----------
* Laws with ANY existing am_law_article row are skipped (matches the
  on-conflict UPSERT in ingest_law_articles_egov.py — running twice on
  the same priority list inserts 0 new article rows). Re-fetching is
  intentional: schedule a separate refresh job (out of scope here).
* The per-run summary is appended to ``data/law_load_log.jsonl`` so a
  later news cron pass can detect newly-loaded laws and emit posts.
* The script does NOT add a ``has_full_text`` column to am_law because
  the truth is already derivable from a JOIN — adding a denormalized
  flag would create a sync bug surface (every script touching am_law
  would have to maintain it). The query
  ``SELECT canonical_id FROM am_law WHERE canonical_id IN
  (SELECT DISTINCT law_canonical_id FROM am_law_article)`` is the
  single source of truth.

Usage
-----
    python scripts/cron/incremental_law_fulltext.py
    python scripts/cron/incremental_law_fulltext.py --limit 100
    python scripts/cron/incremental_law_fulltext.py --dry-run
    python scripts/cron/incremental_law_fulltext.py --limit 5 --verbose

Exit codes
----------
0  success (possibly with all-skip)
1  fatal (db missing, requests missing)
2  no candidate laws to load (registry saturated)
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Reuse parser + upsert helpers from the existing one-shot ingest script.
# Both modules sit in scripts/, so add the repo's scripts/ingest dir to
# sys.path before importing.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_INGEST = _REPO_ROOT / "scripts" / "ingest"
if str(_INGEST) not in sys.path:
    sys.path.insert(0, str(_INGEST))
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from jpintel_mcp.observability import heartbeat  # noqa: E402

try:
    import requests  # noqa: F401  (used only via the imported module)
except ImportError as exc:
    print(f"missing dep: {exc}. pip install requests", file=sys.stderr)
    sys.exit(1)

# ingest_law_articles_egov defines:
#   fetch_law_xml(law_id) -> bytes
#   parse_articles(xml_bytes) -> list[dict]
#   upsert_article(con, canonical_id, art, source_url, fetched_at, kind)
# We reuse them verbatim — DRY guarantee with the one-shot path.
import ingest_law_articles_egov as _eg  # type: ignore  # noqa: E402

_LOG = logging.getLogger("autonomath.cron.incremental_law_fulltext")
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_LOG_FILE = _REPO_ROOT / "data" / "law_load_log.jsonl"
_DEFAULT_LIMIT = 600  # bumped 2026-05-01 from 300 (see module docstring)
_RATE_SLEEP_SEC = 1.0  # polite to e-Gov (matches their published budget)

# Heuristic weights (see module docstring).
_WEIGHT_LREF = 1
_WEIGHT_REL = 5


# ---------------------------------------------------------------------------
# Priority selection
# ---------------------------------------------------------------------------


def _select_candidates(con: sqlite3.Connection, limit: int) -> list[dict]:
    """Return ``limit`` highest-priority unloaded laws with e_gov_lawid.

    A law is "unloaded" when it has zero rows in am_law_article — note
    that this is the exact-same predicate the news cron / search tools
    use to compute "full-text coverage", so the priority list converges
    on the registry-saturation count we advertise.
    """
    rows = con.execute(
        f"""
        WITH ref_count AS (
            SELECT law_canonical_id AS lid, COUNT(*) AS n
              FROM am_law_reference
             WHERE law_canonical_id IS NOT NULL
               AND law_canonical_id <> 'law:_notlaw'
             GROUP BY law_canonical_id
        ),
        rel_count AS (
            SELECT target_entity_id AS lid, COUNT(*) AS n
              FROM am_relation
             WHERE relation_type = 'references_law'
               AND target_entity_id IS NOT NULL
             GROUP BY target_entity_id
        )
        SELECT
            l.canonical_id,
            l.canonical_name,
            l.e_gov_lawid,
            l.last_amended_at,
            COALESCE(r.n, 0)  AS lref_count,
            COALESCE(rl.n, 0) AS rel_count,
            (COALESCE(r.n, 0) * {_WEIGHT_LREF} +
             COALESCE(rl.n, 0) * {_WEIGHT_REL}) AS priority_score
          FROM am_law l
          LEFT JOIN ref_count r  ON l.canonical_id = r.lid
          LEFT JOIN rel_count rl ON l.canonical_id = rl.lid
         WHERE l.e_gov_lawid IS NOT NULL
           AND l.e_gov_lawid <> ''
           AND l.canonical_id NOT IN (
               SELECT DISTINCT law_canonical_id FROM am_law_article
           )
         ORDER BY priority_score DESC,
                  l.last_amended_at DESC NULLS LAST,
                  l.canonical_id ASC
         LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "canonical_id": r["canonical_id"],
                "canonical_name": r["canonical_name"],
                "e_gov_lawid": r["e_gov_lawid"],
                "last_amended_at": r["last_amended_at"],
                "lref_count": int(r["lref_count"]),
                "rel_count": int(r["rel_count"]),
                "priority_score": int(r["priority_score"]),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Per-law load
# ---------------------------------------------------------------------------


def _load_one(
    con: sqlite3.Connection,
    candidate: dict,
    fetched_at: str,
    *,
    dry_run: bool,
) -> dict:
    """Fetch + parse + upsert one law. Returns a per-law summary record."""
    cid = candidate["canonical_id"]
    egov_id = candidate["e_gov_lawid"]
    summary: dict = {
        "canonical_id": cid,
        "e_gov_lawid": egov_id,
        "status": "ok",
        "articles": 0,
        "bytes_fetched": 0,
        "error": None,
    }
    try:
        xml_bytes = _eg.fetch_law_xml(egov_id)
        summary["bytes_fetched"] = len(xml_bytes)
    except FileNotFoundError as exc:
        summary["status"] = "egov_404"
        summary["error"] = str(exc)
        _LOG.warning("egov_404 cid=%s egov_id=%s", cid, egov_id)
        return summary
    except Exception as exc:  # network / 5xx after retries
        summary["status"] = "fetch_error"
        summary["error"] = str(exc)
        _LOG.error("fetch_error cid=%s egov_id=%s err=%s", cid, egov_id, exc)
        return summary

    try:
        articles = _eg.parse_articles(xml_bytes)
    except Exception as exc:
        summary["status"] = "parse_error"
        summary["error"] = str(exc)
        _LOG.error("parse_error cid=%s err=%s", cid, exc)
        return summary

    if not articles:
        summary["status"] = "no_articles"
        _LOG.warning("no_articles cid=%s egov_id=%s", cid, egov_id)
        return summary

    if dry_run:
        summary["status"] = "dry_run"
        summary["articles"] = len(articles)
        return summary

    inserted = 0
    failed = 0
    for art in articles:
        source_url = (
            f"https://laws.e-gov.go.jp/law/{egov_id}"
            f"#Mp-At_{art['article_number']}"
        )
        try:
            _eg.upsert_article(
                con, cid, art, source_url, fetched_at,
                article_kind="main",
            )
            inserted += 1
        except Exception as exc:
            failed += 1
            _LOG.warning(
                "upsert_failed cid=%s art=%s err=%s",
                cid, art.get("article_number"), exc,
            )
    summary["articles"] = inserted
    if failed:
        summary["status"] = "partial"
        summary["error"] = f"{failed} article upserts failed"
    return summary


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


def run(
    db_path: Path,
    limit: int,
    dry_run: bool,
    log_file: Path,
) -> dict:
    """Top-level orchestration. Returns a summary dict for the caller."""
    counters = {
        "candidates": 0,
        "loaded_ok": 0,
        "skipped_404": 0,
        "errors": 0,
        "articles_total": 0,
        "elapsed_sec": 0.0,
    }

    if not db_path.is_file():
        _LOG.error("db_missing path=%s", db_path)
        return counters

    con = sqlite3.connect(db_path, timeout=300)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 300000")
    try:
        candidates = _select_candidates(con, limit)
        counters["candidates"] = len(candidates)
        if not candidates:
            _LOG.info("no_candidates registry_saturated=true")
            return counters

        # Initial coverage stats — useful for the news cron to attach.
        loaded_count_before = con.execute(
            "SELECT COUNT(DISTINCT law_canonical_id) FROM am_law_article"
        ).fetchone()[0]
        total_with_egov = con.execute(
            "SELECT COUNT(*) FROM am_law "
            "WHERE e_gov_lawid IS NOT NULL AND e_gov_lawid <> ''"
        ).fetchone()[0]
        _LOG.info(
            "candidates n=%d coverage_before=%d/%d (%.1f%%) limit=%d dry_run=%s",
            len(candidates),
            loaded_count_before,
            total_with_egov,
            100.0 * loaded_count_before / total_with_egov if total_with_egov else 0.0,
            limit,
            dry_run,
        )

        fetched_at = datetime.now(UTC).isoformat()
        per_law: list[dict] = []
        t0 = time.time()
        for i, c in enumerate(candidates):
            _LOG.info(
                "fetch idx=%d/%d cid=%s egov_id=%s score=%d",
                i + 1, len(candidates), c["canonical_id"],
                c["e_gov_lawid"], c["priority_score"],
            )
            summary = _load_one(con, c, fetched_at, dry_run=dry_run)
            per_law.append(summary)
            if summary["status"] in ("ok", "dry_run"):
                counters["loaded_ok"] += 1
                counters["articles_total"] += int(summary["articles"])
            elif summary["status"] == "egov_404":
                counters["skipped_404"] += 1
            else:
                counters["errors"] += 1

            # Rate limit: don't hammer e-Gov. Skip on the last iteration.
            if i + 1 < len(candidates):
                time.sleep(_RATE_SLEEP_SEC)
        counters["elapsed_sec"] = round(time.time() - t0, 1)

        loaded_count_after = con.execute(
            "SELECT COUNT(DISTINCT law_canonical_id) FROM am_law_article"
        ).fetchone()[0]
        counters["coverage_before"] = loaded_count_before
        counters["coverage_after"] = loaded_count_after
        counters["coverage_total_eligible"] = total_with_egov

        # Append to the load log so the news cron can pick up newly-loaded
        # laws and emit per-law "full-text now searchable" posts. We write
        # one JSON line per run, not per law, to keep the file small.
        if not dry_run:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "run_at": fetched_at,
                "candidates": counters["candidates"],
                "loaded_ok": counters["loaded_ok"],
                "skipped_404": counters["skipped_404"],
                "errors": counters["errors"],
                "articles_total": counters["articles_total"],
                "coverage_before": loaded_count_before,
                "coverage_after": loaded_count_after,
                "coverage_total_eligible": total_with_egov,
                "loaded_canonical_ids": sorted(
                    s["canonical_id"]
                    for s in per_law
                    if s["status"] == "ok" and s["articles"] > 0
                ),
            }
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            _LOG.info("appended_load_log path=%s", log_file)

        _LOG.info(
            "run_done candidates=%d loaded=%d 404=%d errors=%d articles=%d "
            "elapsed=%.1fs coverage=%d→%d/%d",
            counters["candidates"], counters["loaded_ok"],
            counters["skipped_404"], counters["errors"],
            counters["articles_total"], counters["elapsed_sec"],
            loaded_count_before, loaded_count_after, total_with_egov,
        )
        return counters
    finally:
        con.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool) -> None:
    root = logging.getLogger("autonomath.cron.incremental_law_fulltext")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Incremental e-Gov full-text loader for am_law stubs."
    )
    p.add_argument(
        "--db",
        type=Path,
        default=_DEFAULT_DB,
        help=f"SQLite path (default: {_DEFAULT_DB})",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=f"Number of laws to load this run (default: {_DEFAULT_LIMIT})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + parse only; print priority list without writing.",
    )
    p.add_argument(
        "--print-priority",
        action="store_true",
        help="Print the top-N priority list without fetching anything.",
    )
    p.add_argument(
        "--log-file",
        type=Path,
        default=_LOG_FILE,
        help=f"Append-only run log (default: {_LOG_FILE.relative_to(_REPO_ROOT)})",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    if args.print_priority:
        if not args.db.is_file():
            _LOG.error("db_missing path=%s", args.db)
            return 1
        con = sqlite3.connect(args.db, timeout=60)
        con.row_factory = sqlite3.Row
        try:
            cands = _select_candidates(con, args.limit)
        finally:
            con.close()
        if not cands:
            _LOG.info("no_candidates registry_saturated=true")
            return 2
        for i, c in enumerate(cands, 1):
            print(
                f"{i:>3}  score={c['priority_score']:>4}  "
                f"lref={c['lref_count']:>3}  rel={c['rel_count']:>3}  "
                f"egov={c['e_gov_lawid']:<16}  "
                f"amended={c['last_amended_at'] or '—':<12}  "
                f"{c['canonical_id']:<40}  "
                f"{(c['canonical_name'] or '')[:40]}"
            )
        return 0

    with heartbeat("incremental_law_fulltext") as hb:
        counters = run(
            db_path=args.db,
            limit=args.limit,
            dry_run=args.dry_run,
            log_file=args.log_file,
        )
        hb["rows_processed"] = int(counters.get("loaded_ok", 0) or 0)
        hb["rows_skipped"] = int(counters.get("skipped", 0) or 0)
        hb["metadata"] = {
            "candidates": counters.get("candidates"),
            "errors": counters.get("errors"),
            "limit": args.limit,
            "dry_run": bool(args.dry_run),
        }
        if counters["candidates"] == 0:
            return 2
        if counters["errors"] > 0 and counters["loaded_ok"] == 0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
