#!/usr/bin/env python3
"""Lane M5 v2 — SimCSE training corpus prep, AA1+AA2 extended.

Extends ``simcse_corpus_prep_2026_05_17.py`` (v1) with optional
**AA1+AA2 supplemental tables** that are streamed in only if the
matching S3 prefixes exist. The v2 manifest records, per table, the
raw / kept / short / dup counts so the *delta* over v1 is explicit.

v2 supplemental targets (only counted if AA1/AA2 ETL on S3):

    nta_qa                 <= 2,000  (NTA shitsugi-outou)
    nta_saiketsu_extra     <= 3,000  (saiketsu expansion beyond v1 137)
    asbj_kaikei_kijun      <=   120  (ASBJ kaikei kijun PDF body)
    jicpa_audit_committee  <=    90  (JICPA kansa kijun-iinkai PDF body)
    edinet_disclosure      <= 3,800  (EDINET kaiji shoumen excerpts)

If a supplemental prefix returns 0 part files, the table is skipped
silently and the manifest records ``raw_rows=0, source_missing=True``.

v1 corpus stays sha-locked at ``finetune_corpus/`` for reproducibility
of M5 v1 results; v2 writes to ``finetune_corpus_v2/`` so v1 vs v2
recall@10 comparison stays apples-to-apples.

Constraints
-----------
- DRY_RUN default; ``--commit`` to upload.
- NO LLM API.
- mypy --strict friendly.
- ``[lane:solo]`` marker.
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

logger = logging.getLogger("simcse_corpus_prep_v2")

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"

V1_TABLES: Final[list[str]] = [
    "programs",
    "am_law_article",
    "adoption_records",
    "court_decisions",
    "nta_saiketsu",
    "nta_tsutatsu_index",
    "invoice_registrants",
]

V2_SUPPLEMENTAL_TABLES: Final[list[tuple[str, int]]] = [
    ("nta_qa", 2_000),
    ("nta_saiketsu_extra", 3_000),
    ("asbj_kaikei_kijun", 120),
    ("jicpa_audit_committee", 90),
    ("edinet_disclosure", 3_800),
]


@dataclass
class CorpusStats:
    """Per-table corpus stats for the prep ledger."""

    table: str
    raw_rows: int = 0
    kept_rows: int = 0
    skipped_short: int = 0
    skipped_duplicate: int = 0
    source_missing: bool = False


def _boto3_s3(region: str, profile: str) -> Any:
    import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]

    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("s3")


def _list_parts(s3: Any, bucket: str, prefix: str) -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            if key.endswith(".jsonl"):
                keys.append(key)
    return sorted(keys)


def _stream_lines(s3: Any, bucket: str, key: str) -> list[dict[str, Any]]:
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
    text = " ".join(text.split())
    text = text.replace("\x00", "")
    if len(text) > 512:
        text = text[:512]
    return text


def collect_table(
    s3: Any,
    bucket: str,
    table_prefix: str,
    table: str,
    *,
    cap_rows: int,
    seen_hashes: set[str],
    rng: random.Random,
) -> tuple[list[dict[str, Any]], CorpusStats]:
    stats = CorpusStats(table=table)
    parts = _list_parts(s3, bucket, table_prefix)
    if not parts:
        stats.source_missing = True
        logger.info("  %s: SKIP (no parts under %s)", table, table_prefix)
        return [], stats
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
    if cap_rows > 0 and len(rows) > cap_rows:
        rng.shuffle(rows)
        rows = rows[:cap_rows]
    stats.kept_rows = len(rows)
    return rows, stats


def run(
    *,
    bucket: str,
    source_prefix: str,
    supplemental_prefix: str,
    target_prefix: str,
    invoice_sample: int,
    val_ratio: float,
    region: str,
    profile: str,
    dry_run: bool = True,
    seed: int = 42,
) -> dict[str, Any]:
    s3 = _boto3_s3(region, profile)
    rng = random.Random(seed)
    seen: set[str] = set()
    all_rows: list[dict[str, Any]] = []
    table_stats: list[CorpusStats] = []

    for table in V1_TABLES:
        cap = invoice_sample if table == "invoice_registrants" else 0
        table_prefix = f"{source_prefix.rstrip('/')}/{table}/"
        rows, stats = collect_table(
            s3, bucket, table_prefix, table,
            cap_rows=cap, seen_hashes=seen, rng=rng,
        )
        all_rows.extend(rows)
        table_stats.append(stats)
        logger.info(
            "  %s v1 -> kept=%d (raw=%d short=%d dup=%d missing=%s)",
            table, stats.kept_rows, stats.raw_rows,
            stats.skipped_short, stats.skipped_duplicate, stats.source_missing,
        )

    for table, cap in V2_SUPPLEMENTAL_TABLES:
        table_prefix = f"{supplemental_prefix.rstrip('/')}/{table}/"
        rows, stats = collect_table(
            s3, bucket, table_prefix, table,
            cap_rows=cap, seen_hashes=seen, rng=rng,
        )
        all_rows.extend(rows)
        table_stats.append(stats)
        logger.info(
            "  %s v2-aa -> kept=%d (raw=%d short=%d dup=%d missing=%s cap=%d)",
            table, stats.kept_rows, stats.raw_rows,
            stats.skipped_short, stats.skipped_duplicate,
            stats.source_missing, cap,
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

    v2_supplemental_kept = sum(
        s.kept_rows for s in table_stats if s.table in {t for t, _ in V2_SUPPLEMENTAL_TABLES}
    )
    v1_kept = sum(s.kept_rows for s in table_stats if s.table in V1_TABLES)
    manifest: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "bucket": bucket,
        "source_prefix": source_prefix,
        "supplemental_prefix": supplemental_prefix,
        "target_prefix": target_prefix,
        "seed": seed,
        "val_ratio": val_ratio,
        "invoice_sample": invoice_sample,
        "total_rows": n,
        "v1_kept_rows": v1_kept,
        "v2_supplemental_kept_rows": v2_supplemental_kept,
        "v2_lift_pct": round(100.0 * v2_supplemental_kept / max(1, v1_kept), 2),
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
                "source_missing": s.source_missing,
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
        description="SimCSE v2 corpus prep -- aggregate v1 tables + AA1/AA2 supplemental.",
    )
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--source-prefix", default="corpus_export")
    p.add_argument("--supplemental-prefix", default="corpus_export_aa12")
    p.add_argument("--target-prefix", default="finetune_corpus_v2")
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
        supplemental_prefix=args.supplemental_prefix,
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
