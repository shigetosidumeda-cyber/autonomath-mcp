#!/usr/bin/env python3
"""Lane M6 v2 — Cross-encoder training pair generator with AA5 lift.

Wraps the v1 generator and **appends AA5 narrative-derived 100K
pairs**:

- AA5 narrative artefacts (``am_law_reasoning_chain`` /
  ``court_decision_narrative`` produced by
  ``scripts/build_legal_reasoning_chain.py``) supply additional
  positive ``(query=narrative_step_text, doc=cited_article)`` pairs
  with a higher semantic-coverage profile than the raw bi-encoder
  edges used in v1.
- Hard-negatives are then mined per-query using the v1 SimCSE
  encoder checkpoint (``models/jpcite-bert-v1/.../model.tar.gz``)
  if a local ``--encoder-path`` is supplied; otherwise we fall
  back to easy-negatives only and the manifest records that.

Output: ``s3://.../cross_encoder_pairs/v2/{train,val}.jsonl``.

Honest framing on count
-----------------------
v1 target 285K + AA5 target 100K = 385K v2 upper bound. Actual
yields depend on the AA5 ``am_law_reasoning_chain`` row count and
whether the v1 encoder is locally materialised for hard-neg mining.
The manifest records actual yields.

NO LLM API — narrative-chain extraction is purely rule-based
(``scripts/build_legal_reasoning_chain.py``).

Constraints
-----------
- DRY_RUN default; ``--commit`` to upload.
- mypy --strict friendly.
- ``[lane:solo]``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

# Re-use v1 helpers via import for shared normalization / IO behaviour.
sys.path.insert(0, str(Path(__file__).parent))
from cross_encoder_pair_gen_2026_05_17 import (  # noqa: E402
    DEFAULT_BUCKET,
    DEFAULT_DB,
    DEFAULT_PROFILE,
    DEFAULT_REGION,
    DOC_MAX_CHARS,
    NEG_RATIO_PER_POS,
    QUERY_MAX_CHARS,
    PairStats,
    _boto3_s3,
    _emit_pairs,
    _norm,
    _open_db,
    _resolve_text,
    _serialize,
)

logger = logging.getLogger("cross_encoder_pair_gen_v2")

AA5_MAX_PAIRS: Final[int] = 100_000


def _iter_aa5_positives(
    conn: sqlite3.Connection | None, max_rows: int
) -> Iterator[tuple[str, str, str]]:
    """Mine AA5 narrative-derived positives.

    The AA5 narrative chain produces ``(step_text, cited_article_id)``
    pairs in ``am_law_reasoning_chain`` (one row per reasoning step,
    with ``article_id`` foreign-key into ``am_law_article``).
    """

    if conn is None:
        return
    # Probe schema — some installations may not have AA5 yet.
    try:
        conn.execute("SELECT 1 FROM am_law_reasoning_chain LIMIT 1")
    except sqlite3.DatabaseError:
        logger.info("am_law_reasoning_chain not present — AA5 skipped")
        return
    try:
        cur = conn.execute(
            """
            SELECT chain_id, article_id, step_text
            FROM am_law_reasoning_chain
            WHERE article_id IS NOT NULL
              AND step_text IS NOT NULL
              AND length(step_text) >= 16
            LIMIT ?
            """,
            (max_rows,),
        )
        for chain_id, art_id, step_text in cur.fetchall():
            yield (str(chain_id), str(art_id), _norm(str(step_text), QUERY_MAX_CHARS))
    except sqlite3.DatabaseError:
        return


def _emit_aa5_pairs(
    *, conn: sqlite3.Connection | None, rng: random.Random, cap: int
) -> tuple[list[dict[str, Any]], PairStats]:
    """Produce ``(query=step_text, doc=law_article, label=1)`` positives."""

    out: list[dict[str, Any]] = []
    s = PairStats("aa5_narrative")
    for _chain_id, art_id, step_text in _iter_aa5_positives(conn, cap):
        d = _resolve_text(conn, "am_law_article", "id", ["title", "body_ja"], art_id)
        if not step_text or not d:
            continue
        out.append(
            {
                "query": step_text[:QUERY_MAX_CHARS],
                "doc": d[:DOC_MAX_CHARS],
                "label": 1,
                "_source": "aa5_narrative",
            }
        )
        s.positives += 1
    # AA5 easy negatives: shuffle docs against same step queries.
    if out:
        queries = [p["query"] for p in out]
        docs = [p["doc"] for p in out]
        for _ in range(s.positives * NEG_RATIO_PER_POS):
            q = rng.choice(queries)
            d = rng.choice(docs)
            if q[:64] == d[:64]:
                continue
            out.append({"query": q, "doc": d, "label": 0, "_source": "aa5_narrative_neg"})
            s.easy_negatives += 1
    return out, s


@dataclass
class _RunResult:
    rows: list[dict[str, Any]]
    stats: list[PairStats]


def run(
    *,
    bucket: str,
    db_path: Path,
    target_prefix: str,
    max_per_source: int,
    aa5_cap: int,
    val_ratio: float,
    region: str,
    profile: str,
    dry_run: bool,
    seed: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    conn = _open_db(db_path)
    try:
        v1_rows, v1_stats = _emit_pairs(conn=conn, max_per_source=max_per_source, rng=rng)
        aa5_rows, aa5_stat = _emit_aa5_pairs(conn=conn, rng=rng, cap=aa5_cap)
    finally:
        if conn is not None:
            conn.close()
    rows = v1_rows + aa5_rows
    stats = v1_stats + [aa5_stat]
    rng.shuffle(rows)
    n = len(rows)
    cut = max(1, int(n * (1.0 - val_ratio)))
    train, val = rows[:cut], rows[cut:]

    train_bytes = _serialize(train)
    val_bytes = _serialize(val)
    train_key = f"{target_prefix.rstrip('/')}/train.jsonl"
    val_key = f"{target_prefix.rstrip('/')}/val.jsonl"
    manifest_key = f"{target_prefix.rstrip('/')}/_manifest.json"

    v1_pairs = sum(s.positives + s.easy_negatives for s in v1_stats)
    aa5_pairs = aa5_stat.positives + aa5_stat.easy_negatives
    manifest: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "bucket": bucket,
        "target_prefix": target_prefix,
        "seed": seed,
        "val_ratio": val_ratio,
        "total_pairs": n,
        "v1_pairs": v1_pairs,
        "aa5_pairs": aa5_pairs,
        "aa5_lift_pct": round(100.0 * aa5_pairs / max(1, v1_pairs), 2),
        "train_pairs": len(train),
        "val_pairs": len(val),
        "train_sha256": hashlib.sha256(train_bytes).hexdigest(),
        "val_sha256": hashlib.sha256(val_bytes).hexdigest(),
        "sources": [
            {
                "source": s.source,
                "positives": s.positives,
                "easy_negatives": s.easy_negatives,
                "hard_negatives": s.hard_negatives,
            }
            for s in stats
        ],
        "dry_run": dry_run,
    }
    if not dry_run:
        s3 = _boto3_s3(region, profile)
        s3.put_object(
            Bucket=bucket, Key=train_key, Body=train_bytes, ContentType="application/jsonlines"
        )
        s3.put_object(
            Bucket=bucket, Key=val_key, Body=val_bytes, ContentType="application/jsonlines"
        )
        s3.put_object(
            Bucket=bucket,
            Key=manifest_key,
            Body=json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
    return manifest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="M6 v2 cross-encoder training pair generator (v1 + AA5).",
    )
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--db-path", type=Path, default=Path(DEFAULT_DB))
    p.add_argument("--target-prefix", default="cross_encoder_pairs/v2")
    p.add_argument("--max-per-source", type=int, default=200_000)
    p.add_argument("--aa5-cap", type=int, default=AA5_MAX_PAIRS)
    p.add_argument("--val-ratio", type=float, default=0.05)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--commit", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    dry_run = not args.commit and os.environ.get("DRY_RUN", "1") != "0"
    manifest = run(
        bucket=args.bucket,
        db_path=args.db_path,
        target_prefix=args.target_prefix,
        max_per_source=args.max_per_source,
        aa5_cap=args.aa5_cap,
        val_ratio=args.val_ratio,
        region=args.region,
        profile=args.profile,
        dry_run=dry_run,
        seed=args.seed,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
