#!/usr/bin/env python3
"""GG2 — Pre-computed answer composer EXPANDED (500 -> 5,000).

Batch-driver around ``precompute_answer_composer_2026_05_17.py``. Reads the
5 expanded yaml files in ``data/faq_bank/expanded_5000/`` and INSERTs ~5,000
rows into ``am_precomputed_answer`` (no schema change). Uses ProcessPool with
up to 16 workers for I/O-bound citation pulls.

Constraints
-----------
* No Anthropic / OpenAI / Google SDK import. Rule-based only.
* Idempotent UPSERT on (cohort, faq_slug).
* mypy --strict clean / ruff clean.

Usage
-----
    .venv/bin/python scripts/aws_credit_ops/precompute_answer_composer_expand_2026_05_17.py \\
        --input-dir data/faq_bank/expanded_5000 \\
        --workers 16 \\
        --commit
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import logging
import sqlite3 as _sql3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
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
    parse_faq_yaml,
)

logger = logging.getLogger("jpcite.gg2.composer")


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("jpcite.gg2.composer")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GG2 — composer expansion 500 -> 5,000.")
    parser.add_argument("--input-dir", default="data/faq_bank/expanded_5000")
    parser.add_argument("--depth-level", type=int, default=3)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip rows already present in am_precomputed_answer (cohort, faq_slug).",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    in_dir = Path(args.input_dir)
    yamls = sorted(in_dir.glob("*_top1000.yaml"))
    if not yamls:
        logger.error("no *_top1000.yaml found in %s", in_dir)
        return 2

    t0 = time.time()
    all_rows: list[FaqRow] = []
    for p in yamls:
        rows = parse_faq_yaml(p)
        logger.info("parsed %d FAQ from %s", len(rows), p.name)
        all_rows.extend(rows)

    if not all_rows:
        logger.error("no FAQ parsed; aborting")
        return 3
    logger.info("total FAQ to compose: %d", len(all_rows))

    if args.skip_existing:
        db_path = _autonomath_db_path()
        ro = _sql3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
        try:
            ro.row_factory = _sql3.Row
            cur = ro.execute("SELECT cohort, faq_slug FROM am_precomputed_answer")
            existing = {(r["cohort"], r["faq_slug"]) for r in cur.fetchall()}
        finally:
            ro.close()
        before = len(all_rows)
        all_rows = [r for r in all_rows if (r.cohort, r.qid) not in existing]
        logger.info("skip-existing filter: %d -> %d", before, len(all_rows))
        if not all_rows:
            logger.info("nothing to do — all rows already present")
            return 0

    workers = max(1, args.workers)
    payloads: list[dict[str, Any]] = [
        {**_faq_to_payload(r), "depth_level": args.depth_level} for r in all_rows
    ]
    composed: list[dict[str, Any]] = []

    if workers == 1:
        for p2 in payloads:
            composed.append(_worker_compose(p2))
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_worker_compose, p2) for p2 in payloads]
            for done_n, f in enumerate(as_completed(futures), start=1):
                composed.append(f.result())
                if done_n % 500 == 0:
                    logger.info("composed %d / %d", done_n, len(payloads))

    wall_compose = time.time() - t0
    logger.info(
        "composed %d answers in %.1fs (workers=%d, rate=%.1f/sec)",
        len(composed),
        wall_compose,
        workers,
        len(composed) / max(0.001, wall_compose),
    )

    if not args.commit:
        logger.info("[dry-run] would UPSERT %d rows", len(composed))
        return 0

    now_iso = _dt.datetime.now(_dt.UTC).isoformat()
    t1 = time.time()
    conn = _open_rw_db()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
    except Exception as exc:
        logger.warning("PRAGMA setup failed: %s", exc)
    try:
        batch_size = max(1, args.batch_size)
        for i in range(0, len(composed), batch_size):
            chunk = composed[i : i + batch_size]
            attempts = 0
            while True:
                attempts += 1
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    for payload in chunk:
                        _insert_one(conn, payload, now_iso)
                    conn.execute("COMMIT")
                    break
                except Exception as exc:
                    with contextlib.suppress(Exception):
                        conn.execute("ROLLBACK")
                    if "locked" in str(exc).lower() and attempts < 30:
                        logger.warning("batch %d locked (attempt %d/30); sleep 5s", i, attempts)
                        time.sleep(5)
                        continue
                    raise
            logger.info("upserted batch %d-%d", i, i + len(chunk))
    finally:
        conn.close()

    wall_write = time.time() - t1
    wall_total = time.time() - t0
    logger.info(
        "upserted %d rows in %.1fs (write); total wall=%.1fs",
        len(composed),
        wall_write,
        wall_total,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
