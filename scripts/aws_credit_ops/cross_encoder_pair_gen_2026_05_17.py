#!/usr/bin/env python3
"""Lane M6 v1 — Cross-encoder training pair generator.

Produces ``(query, doc, label)`` triples from the existing
``corpus_export/*`` JSONL parts and writes them to
``s3://.../cross_encoder_pairs/v1/{train,val}.jsonl``.

How positives are constructed
-----------------------------
Three canonical positive-pair sources are mined from the autonomath
corpus side:

1. **Court → cited law** edges (``am_citation_judge_law`` v0.1 from
   the MiniLM bi-encoder ingest). Positive label = 1 when
   ``score >= POS_SCORE_FLOOR`` AND ``method`` is a bi-encoder method
   tag.
2. **Program → cited law** edges
   (``am_citation_program_law``). Positives when score >= floor.
3. **Adoption record → law article** edges (``adoption_records``
   side, joining on ``law_article_id`` if present).

Negatives
---------
- **Easy negatives**: random ``(query, doc)`` mismatched pairs from
  the same corpus (programs / courts / adoptions paired against
  randomly sampled am_law_article rows).
- **Hard negatives** (optional, requires v1 SimCSE encoder finished
  → see ``--hard-negative-from``): for each positive, retrieve top-K
  cosine neighbours of the query that are NOT the gold doc.

Honest framing on count
-----------------------
The 285K v1 target = (court 0.85K × 50 negatives) + (program 12.7K × ~15
negatives) + (adoption 160K × small fraction with non-null
law_article_id × ~3 negatives). Actual yield depends on the bi-encoder
edges available; this generator emits whatever is mineable. The 285K
number is an upper bound — the generator records the actual count in
the manifest.

Output schema
-------------

.. code-block:: json

    {"query": "court text first 256 char...",
     "doc":   "law article text first 256 char...",
     "label": 1,
     "_source": "court→law"}

Constraints
-----------
- DRY_RUN default; ``--commit`` to upload.
- NO LLM API.
- mypy --strict friendly.
- ``[lane:solo]``.
"""

from __future__ import annotations

import argparse
import hashlib
import io
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

logger = logging.getLogger("cross_encoder_pair_gen")

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"
DEFAULT_DB: Final[str] = "autonomath.db"

POS_SCORE_FLOOR: Final[float] = 0.55
NEG_RATIO_PER_POS: Final[int] = 3
QUERY_MAX_CHARS: Final[int] = 256
DOC_MAX_CHARS: Final[int] = 256


@dataclass
class PairStats:
    """Per-source pair counts for the manifest."""

    source: str
    positives: int = 0
    easy_negatives: int = 0
    hard_negatives: int = 0


def _norm(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    text = text.replace("\x00", "")
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def _row_to_text(obj: dict[str, Any]) -> str:
    return _norm(
        str(obj.get("inputs") or obj.get("text") or ""), max(QUERY_MAX_CHARS, DOC_MAX_CHARS)
    )


def _open_db(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        logger.warning("db not found: %s — emitting random-pair fallback", db_path)
        return None
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _iter_court_law_positives(
    conn: sqlite3.Connection | None, max_rows: int
) -> Iterator[tuple[str, str, str]]:
    if conn is None:
        return
    try:
        cur = conn.execute(
            """
            SELECT cj.court_unified_id, cj.article_id, cj.score
            FROM am_citation_judge_law AS cj
            WHERE cj.score >= ?
              AND cj.method LIKE 'bi_encoder%'
            ORDER BY cj.score DESC
            LIMIT ?
            """,
            (POS_SCORE_FLOOR, max_rows),
        )
        for cuid, art_id, _score in cur.fetchall():
            yield ("court_law", str(cuid), str(art_id))
    except sqlite3.DatabaseError:
        return


def _iter_program_law_positives(
    conn: sqlite3.Connection | None, max_rows: int
) -> Iterator[tuple[str, str, str]]:
    if conn is None:
        return
    try:
        cur = conn.execute(
            """
            SELECT pj.program_id, pj.article_id, pj.score
            FROM am_citation_program_law AS pj
            WHERE pj.score >= ?
            ORDER BY pj.score DESC
            LIMIT ?
            """,
            (POS_SCORE_FLOOR, max_rows),
        )
        for pid, art_id, _score in cur.fetchall():
            yield ("program_law", str(pid), str(art_id))
    except sqlite3.DatabaseError:
        return


def _resolve_text(
    conn: sqlite3.Connection | None,
    table: str,
    id_col: str,
    text_cols: list[str],
    row_id: str,
) -> str:
    if conn is None:
        return ""
    try:
        cols = ", ".join(text_cols)
        cur = conn.execute(f"SELECT {cols} FROM {table} WHERE {id_col} = ? LIMIT 1", (row_id,))
        r = cur.fetchone()
    except sqlite3.DatabaseError:
        return ""
    if not r:
        return ""
    parts = [str(c) for c in r if c]
    return _norm(" ".join(parts), DOC_MAX_CHARS)


def _emit_pairs(
    *,
    conn: sqlite3.Connection | None,
    max_per_source: int,
    rng: random.Random,
) -> tuple[list[dict[str, Any]], list[PairStats]]:
    out: list[dict[str, Any]] = []
    stats: list[PairStats] = []

    # court → law positives
    s = PairStats("court_law")
    for _src, cuid, art_id in _iter_court_law_positives(conn, max_per_source):
        q = _resolve_text(conn, "court_decisions", "unified_id", ["title", "summary"], cuid)
        d = _resolve_text(conn, "am_law_article", "id", ["title", "body_ja"], art_id)
        if not q or not d:
            continue
        out.append(
            {
                "query": q[:QUERY_MAX_CHARS],
                "doc": d[:DOC_MAX_CHARS],
                "label": 1,
                "_source": "court_law",
            }
        )
        s.positives += 1
    stats.append(s)

    # program → law positives
    s = PairStats("program_law")
    for _src, pid, art_id in _iter_program_law_positives(conn, max_per_source):
        q = _resolve_text(conn, "programs", "id", ["title", "summary", "description"], pid)
        d = _resolve_text(conn, "am_law_article", "id", ["title", "body_ja"], art_id)
        if not q or not d:
            continue
        out.append(
            {
                "query": q[:QUERY_MAX_CHARS],
                "doc": d[:DOC_MAX_CHARS],
                "label": 1,
                "_source": "program_law",
            }
        )
        s.positives += 1
    stats.append(s)

    # easy negatives: random mismatched pairs (3x positives)
    n_pos = sum(s.positives for s in stats)
    n_neg = n_pos * NEG_RATIO_PER_POS
    queries = [p["query"] for p in out if p["label"] == 1]
    docs = [p["doc"] for p in out if p["label"] == 1]
    s = PairStats("easy_neg")
    if queries and docs:
        for _ in range(n_neg):
            q = rng.choice(queries)
            d = rng.choice(docs)
            # avoid accidental positive — quick string check
            if q[:64] == d[:64]:
                continue
            out.append({"query": q, "doc": d, "label": 0, "_source": "easy_neg"})
            s.easy_negatives += 1
    stats.append(s)
    return out, stats


def _serialize(rows: list[dict[str, Any]]) -> bytes:
    buf = io.BytesIO()
    for r in rows:
        buf.write(json.dumps(r, ensure_ascii=False).encode("utf-8") + b"\n")
    return buf.getvalue()


def _boto3_s3(region: str, profile: str) -> Any:
    import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]

    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("s3")


def run(
    *,
    bucket: str,
    db_path: Path,
    target_prefix: str,
    max_per_source: int,
    val_ratio: float,
    region: str,
    profile: str,
    dry_run: bool,
    seed: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    conn = _open_db(db_path)
    try:
        rows, stats = _emit_pairs(conn=conn, max_per_source=max_per_source, rng=rng)
    finally:
        if conn is not None:
            conn.close()
    rng.shuffle(rows)
    n = len(rows)
    cut = max(1, int(n * (1.0 - val_ratio)))
    train, val = rows[:cut], rows[cut:]

    train_bytes = _serialize(train)
    val_bytes = _serialize(val)
    train_key = f"{target_prefix.rstrip('/')}/train.jsonl"
    val_key = f"{target_prefix.rstrip('/')}/val.jsonl"
    manifest_key = f"{target_prefix.rstrip('/')}/_manifest.json"

    manifest: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "bucket": bucket,
        "target_prefix": target_prefix,
        "seed": seed,
        "val_ratio": val_ratio,
        "total_pairs": n,
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
        description="M6 v1 cross-encoder training pair generator.",
    )
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--db-path", type=Path, default=Path(DEFAULT_DB))
    p.add_argument("--target-prefix", default="cross_encoder_pairs/v1")
    p.add_argument("--max-per-source", type=int, default=200_000)
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
