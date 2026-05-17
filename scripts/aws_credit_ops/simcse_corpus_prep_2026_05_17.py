#!/usr/bin/env python3
"""Lane M5 — SimCSE training corpus prep for jpcite domain-tuned BERT.

Aggregates already-exported corpus_export/* JSONL parts into
``finetune_corpus/train.jsonl`` + ``finetune_corpus/val.jsonl`` on S3.

Why reuse corpus_export/*
-------------------------
The 6 corpus tables (programs / am_law_article / adoption_records /
court_decisions / invoice_registrants / nta_saiketsu / nta_tsutatsu_index)
were already exported as JSONL parts to s3 by
``scripts/aws_credit_ops/export_corpus_to_s3.py`` (Wave 60-94 substrate).
Re-querying autonomath.db (12 GB) and re-uploading 250K rows would be
duplicate work — we just stream the existing parts, deduplicate by
``id``, downsample ``invoice_registrants`` (very long-tail, dominates if
unsampled), and split 95/5 train/val.

SimCSE input format
-------------------
SimCSE unsupervised training takes a flat list of single texts; the
model creates positive pairs by passing each text twice through the
encoder with independent dropout masks. We emit one line per text:

    {"text": "..."}

(``id`` retained as ``_id`` for trace, but only ``text`` is consumed
by the training script.)

Constraints
-----------
- DRY_RUN default; pass ``--commit`` to upload.
- NO LLM API calls.
- Idempotent S3 keys (re-running overwrites in place).
- mypy --strict friendly.
- ``[lane:solo]`` marker.

CLI
---

.. code-block:: text

    python scripts/aws_credit_ops/simcse_corpus_prep_2026_05_17.py \\
        --bucket jpcite-credit-993693061769-202605-derived \\
        --source-prefix corpus_export \\
        --target-prefix finetune_corpus \\
        --invoice-sample 50000 \\
        --val-ratio 0.05 \\
        [--commit]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import random
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

logger = logging.getLogger("simcse_corpus_prep")

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"

#: Per-table source list. Order is preserved in the output for deterministic
#: training shuffle re-seeding.
CORPUS_TABLES: Final[list[str]] = [
    "programs",
    "am_law_article",
    "adoption_records",
    "court_decisions",
    "nta_saiketsu",
    "nta_tsutatsu_index",
    "invoice_registrants",
]


@dataclass
class CorpusStats:
    """Per-table corpus stats for the prep ledger."""

    table: str
    raw_rows: int = 0
    kept_rows: int = 0
    skipped_short: int = 0
    skipped_duplicate: int = 0


def _boto3_s3(region: str, profile: str) -> Any:
    import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]

    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("s3")


def _list_parts(s3: Any, bucket: str, prefix: str) -> list[str]:
    """List part-*.jsonl keys under prefix/*."""

    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            if key.endswith(".jsonl"):
                keys.append(key)
    return sorted(keys)


def _stream_lines(s3: Any, bucket: str, key: str) -> list[dict[str, Any]]:
    """Stream a JSONL S3 object into a list of dicts."""

    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    out: list[dict[str, Any]] = []
    for line in io.BytesIO(body).read().decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(obj)
    return out


def _normalize_text(text: str) -> str:
    """Collapse whitespace, strip control chars, truncate to 512 chars."""

    text = " ".join(text.split())
    text = text.replace("\x00", "")
    if len(text) > 512:
        text = text[:512]
    return text


def collect_table(
    s3: Any,
    bucket: str,
    source_prefix: str,
    table: str,
    *,
    invoice_sample: int,
    seen_hashes: set[str],
    rng: random.Random,
) -> tuple[list[dict[str, Any]], CorpusStats]:
    """Collect one table's records, dedup-by-content-hash + invoice sample."""

    stats = CorpusStats(table=table)
    table_prefix = f"{source_prefix.rstrip('/')}/{table}/"
    parts = _list_parts(s3, bucket, table_prefix)
    logger.info("  %s: %d part(s)", table, len(parts))
    rows: list[dict[str, Any]] = []
    for key in parts:
        for obj in _stream_lines(s3, bucket, key):
            stats.raw_rows += 1
            text = obj.get("inputs") or obj.get("text") or ""
            text = _normalize_text(str(text))
            if len(text) < 8:
                stats.skipped_short += 1
                continue
            digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
            if digest in seen_hashes:
                stats.skipped_duplicate += 1
                continue
            seen_hashes.add(digest)
            rows.append({"_id": str(obj.get("id", "")), "text": text, "_table": table})

    # invoice_registrants downsample.
    if table == "invoice_registrants" and len(rows) > invoice_sample:
        rng.shuffle(rows)
        rows = rows[:invoice_sample]
    stats.kept_rows = len(rows)
    return rows, stats


def run(
    *,
    bucket: str,
    source_prefix: str,
    target_prefix: str,
    invoice_sample: int,
    val_ratio: float,
    region: str,
    profile: str,
    dry_run: bool = True,
    seed: int = 42,
) -> dict[str, Any]:
    """Aggregate corpus_export/* into finetune_corpus/train.jsonl + val.jsonl."""

    s3 = _boto3_s3(region, profile)
    rng = random.Random(seed)
    seen: set[str] = set()
    all_rows: list[dict[str, Any]] = []
    table_stats: list[CorpusStats] = []
    for table in CORPUS_TABLES:
        rows, stats = collect_table(
            s3,
            bucket,
            source_prefix,
            table,
            invoice_sample=invoice_sample,
            seen_hashes=seen,
            rng=rng,
        )
        all_rows.extend(rows)
        table_stats.append(stats)
        logger.info(
            "  %s -> kept=%d (raw=%d short=%d dup=%d)",
            table,
            stats.kept_rows,
            stats.raw_rows,
            stats.skipped_short,
            stats.skipped_duplicate,
        )
    rng.shuffle(all_rows)
    n = len(all_rows)
    cut = max(1, int(n * (1.0 - val_ratio)))
    train = all_rows[:cut]
    val = all_rows[cut:]

    def _serialize(rows: list[dict[str, Any]]) -> bytes:
        buf = io.BytesIO()
        for r in rows:
            buf.write(json.dumps({"text": r["text"]}, ensure_ascii=False).encode("utf-8") + b"\n")
        return buf.getvalue()

    train_bytes = _serialize(train)
    val_bytes = _serialize(val)
    train_key = f"{target_prefix.rstrip('/')}/train.jsonl"
    val_key = f"{target_prefix.rstrip('/')}/val.jsonl"
    manifest_key = f"{target_prefix.rstrip('/')}/_manifest.json"

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "bucket": bucket,
        "source_prefix": source_prefix,
        "target_prefix": target_prefix,
        "seed": seed,
        "val_ratio": val_ratio,
        "invoice_sample": invoice_sample,
        "total_rows": n,
        "train_rows": len(train),
        "val_rows": len(val),
        "train_sha256": hashlib.sha256(train_bytes).hexdigest(),
        "val_sha256": hashlib.sha256(val_bytes).hexdigest(),
        "tables": [
            {
                "table": s.table,
                "raw_rows": s.raw_rows,
                "kept_rows": s.kept_rows,
                "skipped_short": s.skipped_short,
                "skipped_duplicate": s.skipped_duplicate,
            }
            for s in table_stats
        ],
        "dry_run": dry_run,
    }
    if not dry_run:
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
        description="SimCSE training corpus prep — aggregate corpus_export/* into finetune_corpus/."
    )
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--source-prefix", default="corpus_export")
    p.add_argument("--target-prefix", default="finetune_corpus")
    p.add_argument("--invoice-sample", type=int, default=50000)
    p.add_argument("--val-ratio", type=float, default=0.05)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--commit", action="store_true")
    p.add_argument("--json", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    dry_run = not args.commit and os.environ.get("DRY_RUN", "1") != "0"
    manifest = run(
        bucket=args.bucket,
        source_prefix=args.source_prefix,
        target_prefix=args.target_prefix,
        invoice_sample=args.invoice_sample,
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
