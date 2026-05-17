#!/usr/bin/env python3
"""GG2 — Re-compose failure rows (1-pass retry).

Reads the quality check JSON, locates rows that failed citation_count_low
or cohort_vocab_missing, and re-composes them via the (now top-up enabled)
P2 composer. Idempotent UPSERT.

Constraints
-----------
* No Anthropic / OpenAI / Google SDK import.
* mypy --strict clean / ruff clean.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from precompute_answer_composer_2026_05_17 import (  # noqa: E402
    FaqRow,
    _autonomath_db_path,
    _faq_to_payload,
    _insert_one,
    _open_rw_db,
    _worker_compose,
)

logger = logging.getLogger("jpcite.gg2.recompose")


def _load_failed_rows(db_path: Path) -> list[FaqRow]:
    """Pull current rows with citation_count < 2 and rebuild FaqRow shells."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT cohort, faq_slug, question_text, question_variants, "
            "       opus_baseline_jpy, citation_count "
            "  FROM am_precomputed_answer "
            " WHERE citation_count < 2"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    out: list[FaqRow] = []
    for r in rows:
        try:
            variants = json.loads(r["question_variants"] or "[]")
            if not isinstance(variants, list):
                variants = []
        except json.JSONDecodeError:
            variants = []
        out.append(
            FaqRow(
                cohort=r["cohort"],
                cohort_label_ja="",
                qid=r["faq_slug"],
                category="",
                question_text=r["question_text"],
                variants=variants,
                priority="MED",
                depth_target=3,
                required_data_sources=[],
                opus_baseline_jpy=int(r["opus_baseline_jpy"] or 18),
                jpcite_target_jpy=3,
                legal_disclaimer="§52",
            )
        )
    return out


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("jpcite.gg2.recompose")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GG2 — recompose citation_count_low failures.")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    db_path = _autonomath_db_path()
    failed = _load_failed_rows(db_path)
    logger.info("found %d failed rows to recompose", len(failed))
    if not failed:
        return 0

    payloads: list[dict[str, Any]] = [{**_faq_to_payload(r), "depth_level": 3} for r in failed]
    composed: list[dict[str, Any]] = []
    t0 = time.time()
    if args.workers == 1:
        for p in payloads:
            composed.append(_worker_compose(p))
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = [ex.submit(_worker_compose, p) for p in payloads]
            for f in as_completed(futures):
                composed.append(f.result())
    logger.info("re-composed %d rows in %.1fs", len(composed), time.time() - t0)

    if not args.commit:
        logger.info("[dry-run] would UPSERT %d rows", len(composed))
        return 0

    now_iso = _dt.datetime.now(_dt.UTC).isoformat()
    conn = _open_rw_db()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
    except Exception as exc:
        logger.warning("PRAGMA failed: %s", exc)
    try:
        batch_size = max(1, args.batch_size)
        for i in range(0, len(composed), batch_size):
            chunk = composed[i : i + batch_size]
            attempts = 0
            while True:
                attempts += 1
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    for p in chunk:
                        _insert_one(conn, p, now_iso)
                    conn.execute("COMMIT")
                    break
                except Exception as exc:
                    with contextlib.suppress(Exception):
                        conn.execute("ROLLBACK")
                    if "locked" in str(exc).lower() and attempts < 30:
                        logger.warning("batch %d locked attempt %d", i, attempts)
                        time.sleep(5)
                        continue
                    raise
            logger.info("recomposed batch %d-%d", i, i + len(chunk))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
