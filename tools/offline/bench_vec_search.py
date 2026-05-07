#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""sqlite-vec k-NN latency benchmark.

Measures wall-time latency of `MATCH ?` k-NN queries on each
`am_entities_vec_*` virtual table in `autonomath.db`. Used to
decide whether vec0 brute-force is viable for the 201k-row
`am_entities_vec_A` adoption corpus, or whether partitioned /
IVF / DiskANN migration is needed.

NO LLM IMPORTS. Pure stdlib + sqlite-vec + numpy.

Usage:
    .venv312/bin/python tools/offline/bench_vec_search.py \
        [--db /path/to/autonomath.db] \
        [--iters 100] [--k 10] [--min-rows 100] \
        [--out docs/_internal/W21_VEC_BENCH.md]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import struct
import sys
import time
from pathlib import Path

import sqlite_vec

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUT = REPO_ROOT / "docs" / "_internal" / "W21_VEC_BENCH.md"
TABLE_TIERS = ["S", "L", "C", "T", "K", "J", "A"]
EMBED_DIM = 1024


def random_unit_vec(dim: int, rng) -> bytes:
    # gaussian sample → unit-normalize (BGE / E5 convention)
    v = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    norm = sum(x * x for x in v) ** 0.5 or 1.0
    v = [x / norm for x in v]
    return struct.pack(f"{dim}f", *v)


def percentile(sorted_vals, pct: float) -> float:
    if not sorted_vals:
        return float("nan")
    k = max(0, min(len(sorted_vals) - 1, int(round((pct / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def bench_table(conn: sqlite3.Connection, table: str, iters: int, k: int, dim: int, rng) -> dict:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    n_rows = cur.fetchone()[0]
    sql = f"SELECT entity_id, distance FROM {table} WHERE embedding MATCH ? ORDER BY distance LIMIT {k}"

    # warmup (page cache) — 3 untimed iters
    for _ in range(min(3, iters)):
        try:
            list(cur.execute(sql, (random_unit_vec(dim, rng),)))
        except sqlite3.OperationalError as e:
            return {"table": table, "rows": n_rows, "error": str(e)}

    samples_ms: list[float] = []
    for _ in range(iters):
        q = random_unit_vec(dim, rng)
        t0 = time.perf_counter_ns()
        list(cur.execute(sql, (q,)))
        elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
        samples_ms.append(elapsed_ms)
    samples_ms.sort()
    return {
        "table": table,
        "rows": n_rows,
        "iters": iters,
        "k": k,
        "p50_ms": round(percentile(samples_ms, 50), 3),
        "p95_ms": round(percentile(samples_ms, 95), 3),
        "p99_ms": round(percentile(samples_ms, 99), 3),
        "min_ms": round(samples_ms[0], 3),
        "max_ms": round(samples_ms[-1], 3),
        "mean_ms": round(sum(samples_ms) / len(samples_ms), 3),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--iters", type=int, default=100)
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--min-rows", type=int, default=100)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--dim", type=int, default=EMBED_DIM)
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument(
        "--json", action="store_true", help="emit JSON to stdout instead of writing markdown"
    )
    args = p.parse_args()

    if not os.path.exists(args.db):
        print(f"ERROR: db not found: {args.db}", file=sys.stderr)
        return 2

    import random

    rng = random.Random(args.seed)

    conn = sqlite3.connect(args.db)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    cur = conn.cursor()
    cur.execute("SELECT vec_version()")
    vec_version = cur.fetchone()[0]
    cur.execute("SELECT sqlite_version()")
    sqlite_version = cur.fetchone()[0]

    results = []
    skipped = []
    for tier in TABLE_TIERS:
        table = f"am_entities_vec_{tier}"
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            n = cur.fetchone()[0]
        except sqlite3.OperationalError as e:
            skipped.append({"table": table, "reason": f"missing: {e}"})
            continue
        if n < args.min_rows:
            skipped.append({"table": table, "rows": n, "reason": f"rows<{args.min_rows}"})
            continue
        print(f"[bench] {table} rows={n} iters={args.iters} k={args.k} ...", file=sys.stderr)
        r = bench_table(conn, table, args.iters, args.k, args.dim, rng)
        results.append(r)

    payload = {
        "db": args.db,
        "sqlite_version": sqlite_version,
        "sqlite_vec_version": vec_version,
        "embedding_dim": args.dim,
        "iters": args.iters,
        "k": args.k,
        "results": results,
        "skipped": skipped,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("# W21 sqlite-vec k-NN benchmark")
    lines.append("")
    lines.append(f"- db: `{args.db}`")
    lines.append(f"- sqlite: {sqlite_version}")
    lines.append(f"- sqlite-vec: {vec_version}")
    lines.append(f"- embedding dim: {args.dim}")
    lines.append(f"- iterations per table: {args.iters} (3 untimed warmup)")
    lines.append(f"- top-k: {args.k}")
    lines.append("")
    lines.append("## Latency by tier (ms)")
    lines.append("")
    lines.append("| table | rows | p50 | p95 | p99 | min | max | mean |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        if "error" in r:
            lines.append(
                f"| {r['table']} | {r['rows']} | ERR | ERR | ERR | ERR | ERR | ERR |  ({r['error']})"
            )
            continue
        lines.append(
            f"| {r['table']} | {r['rows']} | {r['p50_ms']} | {r['p95_ms']} | {r['p99_ms']} | "
            f"{r['min_ms']} | {r['max_ms']} | {r['mean_ms']} |"
        )
    if skipped:
        lines.append("")
        lines.append("## Skipped tables")
        lines.append("")
        for s in skipped:
            lines.append(
                f"- `{s['table']}` — {s['reason']}"
                + (f" (rows={s.get('rows')})" if "rows" in s else "")
            )
    lines.append("")
    lines.append("## HNSW availability")
    lines.append("")
    lines.append(
        "sqlite-vec **0.1.9 has no HNSW index**. Probed via:\n"
        "`CREATE VIRTUAL TABLE ... USING vec0(embedding float[N], hnsw=1)` →\n"
        "`vec0 constructor error: Unknown table option: hnsw`. Upstream\n"
        "(github.com/asg017/sqlite-vec) carries IVF / IVF-kmeans / DiskANN\n"
        "source files but no released build exposes them as a `vec0` option."
    )
    lines.append("")
    lines.append("## Partition key option (available, recommended for vec_A)")
    lines.append("")
    lines.append(
        "vec0 **does** support `PARTITION KEY` columns. Probed in-memory:\n"
        "`CREATE VIRTUAL TABLE __t USING vec0(prefecture_code TEXT PARTITION KEY, embedding float[1024])` → OK.\n"
        "For `am_entities_vec_A` (201k row target), partitioning by\n"
        "`prefecture_code` (47 buckets, ~4.3k rows / bucket) reduces\n"
        "per-query candidate set by ~47×. Filtered queries take the form:\n"
        "`WHERE prefecture_code = ? AND embedding MATCH ? ORDER BY distance LIMIT k`."
    )
    lines.append("")
    lines.append("## HNSW migration decision")
    lines.append("")
    if results:
        # find vec_A or biggest table
        biggest = max(results, key=lambda r: r.get("rows", 0))
        lines.append(
            f"Largest measured tier: `{biggest['table']}` ({biggest['rows']} rows) → "
            f"p95 = {biggest.get('p95_ms')} ms.\n"
            f"Linear extrapolation to 201,845 rows (`am_entities_vec_A` saturated) "
            f"≈ {round(biggest.get('p95_ms', 0) * 201_845 / max(biggest['rows'], 1), 1)} ms p95.\n"
        )
        lines.append(
            "**Decision**: HNSW is unavailable in the current sqlite-vec\n"
            "build, so a migration 152 cannot adopt it today. The viable\n"
            "near-term levers when `am_entities_vec_A` saturates:\n"
            "1. Add `prefecture_code` (and/or `record_kind`) `PARTITION KEY`\n"
            "   to the vec_A DDL. Most adoption queries are already\n"
            "   prefecture-scoped — the 47× pruning likely keeps p95\n"
            "   under 50 ms.\n"
            "2. Pin sqlite-vec ≥ 0.1.10 once IVF/DiskANN ship as\n"
            "   `vec0` options and re-evaluate.\n"
            "3. Pre-filter via `entity_id IN (SELECT ... FROM am_entities WHERE ...)`\n"
            "   then rank — vec0 honors candidate-restriction pushdown.\n"
        )
    else:
        lines.append("No tiers met `--min-rows`; skipping extrapolation.")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[bench] wrote {out_path}", file=sys.stderr)
    print(
        json.dumps(
            {"out": str(out_path), "results": results, "skipped": skipped},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
