#!/usr/bin/env python3
"""bulk_egov_law_fulltext.py — Bulk e-Gov 法令本文 saturation loader.

Purpose
-------
Grows the ``am_law_article`` body fulltext coverage in one or more
large batches against the Fly volume's ``autonomath.db``. The existing
weekly cron (``scripts/cron/incremental_law_fulltext.py``) already
walks the priority queue 600 laws/run; this script is the
**intentional, resumable, larger-batch** companion that an operator
can fire from the Fly machine when they want to push the saturation
number toward the 10,106-eligible-law ceiling on demand instead of
waiting for the weekly cadence.

Design (kept boring on purpose)
-------------------------------
* **DRY** — re-uses ``scripts/ingest/ingest_law_articles_egov.py`` as
  ``_eg`` for ``fetch_law_xml`` + ``parse_articles`` + ``upsert_article``.
  Every parser quirk fixed in the one-shot path (附則 Num collisions,
  whitespace collapse, etc.) lands here automatically.
* **Resumable** — per-DB progress file at
  ``data/bulk_egov_law_progress.json`` records ``{processed_canonical_ids,
  last_run_at, batch_history}``. Re-runs skip canonical_ids already
  present in either ``am_law_article`` or the progress file's
  ``processed`` set, so a Ctrl-C mid-batch only loses the in-flight law,
  not the whole queue.
* **Polite to e-Gov** — defaults to a 3.0s inter-fetch sleep (tighter
  than the weekly cron's 1.0s but with longer per-batch caps so we
  amortize the fetch envelope across more laws — caller still controls
  via ``--rate-sleep``). 60-min Fly ssh exec window translates to ~600
  laws @ 6s effective per law (3s sleep + ~3s fetch+parse+upsert),
  which is why ``--batch 100`` is the recommended chunk size and the
  caller is expected to invoke 5-10 sequential batches per session.
* **Read-only against ``am_law``** for the candidate-selection SQL.
  The only write surface is ``am_law_article`` upsert via the shared
  helper. NO write to ``am_law``, ``am_relation``, or any other table.
* **NO LLM**. Pure stdlib + ``requests`` + ``ElementTree``. The
  ``test_no_llm_in_production.py`` CI guard inspects every line under
  ``scripts/etl/`` and would red the build if this file imported
  ``anthropic`` / ``openai`` / etc. We don't.

Why a separate script (vs. just running the cron with --limit 1000)
-------------------------------------------------------------------
* The weekly cron is a *single* run, not resumable across invocations.
  An operator pushing 1,000+ laws in one session needs the progress
  file so a 5xx-storm midway doesn't reset the queue.
* The cron's exit code 2 (registry saturated) is silent on partial
  progress. This script writes a per-batch summary line to
  ``data/bulk_egov_law_progress.json`` so the operator can grep
  ``batch_history[-1]`` for the last run's loaded count without
  spelunking ``data/law_load_log.jsonl``.
* The ``--batch`` + ``--start`` knobs let the caller dial in the exact
  Fly ssh window length, which the cron's fixed 600-laws design
  doesn't accommodate (Fly cuts ssh exec at ~60 min and the cron's
  90-min workflow timeout is GHA, not Fly).

Usage
-----
    # 10-law dry run (verify candidate selection + parser still work):
    .venv/bin/python -m scripts.etl.bulk_egov_law_fulltext \\
        --limit 10 --dry-run

    # Production single-batch on the Fly machine:
    flyctl ssh console -a autonomath-api -C \\
        '/opt/venv/bin/python -m scripts.etl.bulk_egov_law_fulltext \\
            --db /data/autonomath.db --batch 100 --start 0'

    # Resumable saturation push (caller loops on Fly side):
    for i in 0 100 200 300 400; do
      flyctl ssh console -a autonomath-api -C \\
        "/opt/venv/bin/python -m scripts.etl.bulk_egov_law_fulltext \\
          --db /data/autonomath.db --batch 100 --start $i"
    done

Exit codes
----------
0  success (possibly partial — see progress file for per-law detail)
1  fatal (db missing, dependency missing)
2  no candidates (registry saturated against the e_gov_lawid pool)
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
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_INGEST = _REPO_ROOT / "scripts" / "ingest"
if str(_INGEST) not in sys.path:
    sys.path.insert(0, str(_INGEST))
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    import requests  # noqa: F401
except ImportError as exc:  # pragma: no cover
    print(f"missing dep: {exc}. pip install requests", file=sys.stderr)
    sys.exit(1)

# Reuse the one-shot ingestor's parser + upsert helpers (DRY guarantee).
import ingest_law_articles_egov as _eg  # type: ignore  # noqa: E402

# heartbeat is optional — when imported in dev (no cron_state DB) we still
# want to run.
try:
    from jpintel_mcp.observability import heartbeat  # type: ignore
except Exception:  # pragma: no cover
    from contextlib import contextmanager

    @contextmanager  # type: ignore[no-redef]
    def heartbeat(name: str):  # type: ignore[no-redef]
        d: dict[str, Any] = {}
        yield d


_LOG = logging.getLogger("jpcite.etl.bulk_egov_law_fulltext")

_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_DEFAULT_PROGRESS = _REPO_ROOT / "data" / "bulk_egov_law_progress.json"
_DEFAULT_BATCH = 100
_DEFAULT_START = 0
_DEFAULT_RATE_SLEEP = 3.0


# ---------------------------------------------------------------------------
# Progress file (resumable)
# ---------------------------------------------------------------------------


def _load_progress(path: Path) -> dict[str, Any]:
    """Return progress dict, or a fresh empty one when the file is missing.

    Schema is intentionally append-only — old runs' history is preserved
    so an auditor can reconstruct the saturation curve.
    """
    if not path.is_file():
        return {
            "schema_version": 1,
            "processed_canonical_ids": [],
            "last_run_at": None,
            "batch_history": [],
        }
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        _LOG.error("progress_corrupt path=%s err=%s — refusing to overwrite", path, exc)
        raise
    # Normalize to current schema (forward-compatible).
    data.setdefault("schema_version", 1)
    data.setdefault("processed_canonical_ids", [])
    data.setdefault("batch_history", [])
    return data


def _save_progress(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, sort_keys=True, indent=2)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Candidate selection (READ-ONLY)
# ---------------------------------------------------------------------------


def _select_candidates(
    con: sqlite3.Connection,
    *,
    batch: int,
    start: int,
    skip_canonical_ids: set[str],
) -> list[dict[str, Any]]:
    """Return up to ``batch`` unloaded laws, applying ``--start`` offset.

    Same predicate as the weekly cron (no row in am_law_article), with
    the extra in-Python skip set so resumed runs don't re-fetch laws
    the operator already loaded since the last DB snapshot of the
    progress file. Ordering matches the cron's so a parallel weekly
    run won't conflict on the same canonical_id.
    """
    rows = con.execute(
        """
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
            (COALESCE(r.n, 0) * 1 + COALESCE(rl.n, 0) * 5) AS priority_score
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
         LIMIT ? OFFSET ?
        """,
        (batch, start),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        cid = r["canonical_id"]
        if cid in skip_canonical_ids:
            continue
        out.append(
            {
                "canonical_id": cid,
                "canonical_name": r["canonical_name"],
                "e_gov_lawid": r["e_gov_lawid"],
                "last_amended_at": r["last_amended_at"],
                "lref_count": int(r["lref_count"]),
                "rel_count": int(r["rel_count"]),
                "priority_score": int(r["priority_score"]),
            }
        )
    return out


def _select_dry_run_targets(con: sqlite3.Connection, names: list[str]) -> list[dict[str, Any]]:
    """Cherry-pick named laws for the 10-law smoke test.

    Used only when ``--dry-run-targets`` is passed. Each entry is a
    substring match against ``canonical_name`` (e.g. ``法人税法``);
    we take the first ``limit`` matches per term so the smoke set is
    deterministic.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in names:
        rows = con.execute(
            """
            SELECT canonical_id, canonical_name, e_gov_lawid, last_amended_at
              FROM am_law
             WHERE canonical_name LIKE ?
               AND e_gov_lawid IS NOT NULL
               AND e_gov_lawid <> ''
             ORDER BY canonical_id ASC
             LIMIT 3
            """,
            (f"%{name}%",),
        ).fetchall()
        for r in rows:
            if r["canonical_id"] in seen:
                continue
            seen.add(r["canonical_id"])
            out.append(
                {
                    "canonical_id": r["canonical_id"],
                    "canonical_name": r["canonical_name"],
                    "e_gov_lawid": r["e_gov_lawid"],
                    "last_amended_at": r["last_amended_at"],
                    "lref_count": 0,
                    "rel_count": 0,
                    "priority_score": 0,
                }
            )
    return out


# ---------------------------------------------------------------------------
# Per-law load (thin wrapper around _eg.upsert_article)
# ---------------------------------------------------------------------------


def _load_one(
    con: sqlite3.Connection,
    candidate: dict[str, Any],
    fetched_at: str,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    cid = candidate["canonical_id"]
    egov_id = candidate["e_gov_lawid"]
    summary: dict[str, Any] = {
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
        source_url = f"https://laws.e-gov.go.jp/law/{egov_id}#Mp-At_{art['article_number']}"
        try:
            _eg.upsert_article(
                con,
                cid,
                art,
                source_url,
                fetched_at,
                article_kind="main",
            )
            inserted += 1
        except Exception as exc:
            failed += 1
            _LOG.warning(
                "upsert_failed cid=%s art=%s err=%s",
                cid,
                art.get("article_number"),
                exc,
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
    *,
    db_path: Path,
    progress_path: Path,
    batch: int,
    start: int,
    rate_sleep: float,
    dry_run: bool,
    dry_run_targets: list[str] | None,
) -> dict[str, Any]:
    counters: dict[str, Any] = {
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

    progress = _load_progress(progress_path)
    skip_set = set(progress.get("processed_canonical_ids", []))

    con = sqlite3.connect(db_path, timeout=300)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 300000")
    try:
        if dry_run_targets:
            candidates = _select_dry_run_targets(con, dry_run_targets)
        else:
            candidates = _select_candidates(
                con,
                batch=batch,
                start=start,
                skip_canonical_ids=skip_set,
            )
        counters["candidates"] = len(candidates)
        if not candidates:
            _LOG.info("no_candidates registry_saturated_or_offset_too_high=true")
            return counters

        coverage_before = con.execute(
            "SELECT COUNT(DISTINCT law_canonical_id) FROM am_law_article"
        ).fetchone()[0]
        total_with_egov = con.execute(
            "SELECT COUNT(*) FROM am_law WHERE e_gov_lawid IS NOT NULL AND e_gov_lawid <> ''"
        ).fetchone()[0]
        _LOG.info(
            "candidates n=%d coverage_before=%d/%d (%.1f%%) batch=%d start=%d dry_run=%s",
            len(candidates),
            coverage_before,
            total_with_egov,
            100.0 * coverage_before / total_with_egov if total_with_egov else 0.0,
            batch,
            start,
            dry_run,
        )

        fetched_at = datetime.now(UTC).isoformat()
        per_law: list[dict[str, Any]] = []
        t0 = time.time()
        for i, c in enumerate(candidates):
            _LOG.info(
                "fetch idx=%d/%d cid=%s egov_id=%s score=%d",
                i + 1,
                len(candidates),
                c["canonical_id"],
                c["e_gov_lawid"],
                c["priority_score"],
            )
            summary = _load_one(con, c, fetched_at, dry_run=dry_run)
            per_law.append(summary)
            if summary["status"] in ("ok", "dry_run"):
                counters["loaded_ok"] += 1
                counters["articles_total"] += int(summary["articles"])
                if not dry_run and summary["articles"] > 0:
                    skip_set.add(c["canonical_id"])
            elif summary["status"] == "egov_404":
                counters["skipped_404"] += 1
                # Mark 404'd laws as processed too — re-fetching them
                # next batch won't help. e-Gov 404 means the law_id has
                # been retired or the catalog stub is mislinked.
                if not dry_run:
                    skip_set.add(c["canonical_id"])
            else:
                counters["errors"] += 1

            if i + 1 < len(candidates):
                time.sleep(rate_sleep)

        counters["elapsed_sec"] = round(time.time() - t0, 1)

        coverage_after = con.execute(
            "SELECT COUNT(DISTINCT law_canonical_id) FROM am_law_article"
        ).fetchone()[0]
        counters["coverage_before"] = coverage_before
        counters["coverage_after"] = coverage_after
        counters["coverage_total_eligible"] = total_with_egov

        if not dry_run:
            progress["processed_canonical_ids"] = sorted(skip_set)
            progress["last_run_at"] = fetched_at
            progress["batch_history"].append(
                {
                    "run_at": fetched_at,
                    "batch": batch,
                    "start": start,
                    "candidates": counters["candidates"],
                    "loaded_ok": counters["loaded_ok"],
                    "skipped_404": counters["skipped_404"],
                    "errors": counters["errors"],
                    "articles_total": counters["articles_total"],
                    "coverage_before": coverage_before,
                    "coverage_after": coverage_after,
                    "elapsed_sec": counters["elapsed_sec"],
                }
            )
            _save_progress(progress_path, progress)
            _LOG.info("progress_saved path=%s processed=%d", progress_path, len(skip_set))

        _LOG.info(
            "run_done candidates=%d loaded=%d 404=%d errors=%d articles=%d "
            "elapsed=%.1fs coverage=%d->%d/%d",
            counters["candidates"],
            counters["loaded_ok"],
            counters["skipped_404"],
            counters["errors"],
            counters["articles_total"],
            counters["elapsed_sec"],
            coverage_before,
            coverage_after,
            total_with_egov,
        )
        return counters
    finally:
        con.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool) -> None:
    root = logging.getLogger("jpcite.etl.bulk_egov_law_fulltext")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bulk e-Gov 法令本文 saturation loader (resumable, larger batch)."
    )
    p.add_argument(
        "--db",
        type=Path,
        default=_DEFAULT_DB,
        help=f"SQLite path (default: {_DEFAULT_DB})",
    )
    p.add_argument(
        "--progress",
        type=Path,
        default=_DEFAULT_PROGRESS,
        help=f"Progress JSON (default: {_DEFAULT_PROGRESS.relative_to(_REPO_ROOT)})",
    )
    p.add_argument(
        "--batch",
        type=int,
        default=_DEFAULT_BATCH,
        help=f"Laws per batch (default: {_DEFAULT_BATCH})",
    )
    p.add_argument(
        "--start",
        type=int,
        default=_DEFAULT_START,
        help=f"Offset into priority queue (default: {_DEFAULT_START})",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Convenience alias for --batch (lower wins).",
    )
    p.add_argument(
        "--rate-sleep",
        type=float,
        default=_DEFAULT_RATE_SLEEP,
        help=f"Inter-fetch sleep seconds (default: {_DEFAULT_RATE_SLEEP})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + parse only; no DB write.",
    )
    p.add_argument(
        "--dry-run-targets",
        nargs="+",
        default=None,
        help="Cherry-pick laws by canonical_name substring (e.g. 法人税法 消費税法).",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    batch = args.batch
    if args.limit is not None and args.limit < batch:
        batch = args.limit

    with heartbeat("bulk_egov_law_fulltext") as hb:
        counters = run(
            db_path=args.db,
            progress_path=args.progress,
            batch=batch,
            start=args.start,
            rate_sleep=args.rate_sleep,
            dry_run=args.dry_run,
            dry_run_targets=args.dry_run_targets,
        )
        hb["rows_processed"] = int(counters.get("loaded_ok", 0) or 0)
        hb["rows_skipped"] = int(counters.get("skipped_404", 0) or 0)
        hb["metadata"] = {
            "candidates": counters.get("candidates"),
            "errors": counters.get("errors"),
            "batch": batch,
            "start": args.start,
            "dry_run": bool(args.dry_run),
        }
        if counters["candidates"] == 0:
            return 2
        if counters["errors"] > 0 and counters["loaded_ok"] == 0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
