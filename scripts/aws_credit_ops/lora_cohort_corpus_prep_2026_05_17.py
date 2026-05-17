#!/usr/bin/env python3
"""Lane BB4 — Per-cohort LoRA training corpus prep for jpcite-bert-v1.

Slices the already-staged ``corpus_export/*`` JSONL parts into 5 cohort
shards under ``finetune_corpus_lora_cohort_{cohort}/`` for downstream
PEFT LoRA fine-tunes on top of the M5 jpcite-bert-v1 SimCSE encoder
(fallback ``cl-tohoku/bert-base-japanese-v3``).

Cohort mapping (5 cohort)
-------------------------
- zeirishi (税理士)    : am_law_article (法人税/消費税/相続税 keyword filter)
                          + nta_tsutatsu_index + nta_saiketsu + adoption_records
                          (limited)
- kaikeishi (会計士)   : am_law_article (会計/監査/開示 keyword filter)
                          + adoption_records (M&A/開示 filter) + court_decisions
- gyouseishoshi (行政書士): programs + am_law_article (許認可/業法 keyword filter)
                          + adoption_records (補助金/許認可 filter)
- shihoshoshi (司法書士): am_law_article (商業登記/不動産登記/会社法/民法 filter)
                          + court_decisions + nta_saiketsu (商事関連)
- chusho_keieisha (中小経営者): programs + adoption_records (中小事業者 filter)
                          + invoice_registrants (downsampled)

Filtering uses simple Japanese keyword presence in `text` field. Each
cohort yields 20k-50k unique text snippets (post-dedup, post-truncate).

Output S3 keys
--------------
``s3://{bucket}/finetune_corpus_lora_cohort_{cohort}/train.jsonl``
``s3://{bucket}/finetune_corpus_lora_cohort_{cohort}/val.jsonl``
``s3://{bucket}/finetune_corpus_lora_cohort_{cohort}/_manifest.json``

Constraints
-----------
- DRY_RUN default; pass ``--commit`` to upload.
- NO LLM API calls; pure SQL-ish filter on already-exported JSONL.
- Idempotent S3 keys (re-running overwrites).
- mypy --strict friendly. ``[lane:solo]`` marker.
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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

logger = logging.getLogger("lora_cohort_corpus_prep")

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"

#: Per-cohort filter rules. Each entry:
#:   {"tables": {table_name: [kw, ...] or None}, "max_per_table": int}
#: ``None`` = include all rows; ``[]`` = include all rows (kept for clarity).
#: Keyword filter = "any of these substrings present in normalized text".
COHORT_FILTERS: Final[dict[str, dict[str, Any]]] = {
    "zeirishi": {
        "tables": {
            "am_law_article": [
                "法人税",
                "消費税",
                "相続税",
                "贈与税",
                "所得税",
                "源泉徴収",
                "申告",
                "課税",
                "税額",
                "控除",
                "減価償却",
                "繰越欠損金",
            ],
            "nta_tsutatsu_index": None,
            "nta_saiketsu": None,
            "adoption_records": ["税制", "税務", "申告"],
        },
        "max_per_table": 30000,
    },
    "kaikeishi": {
        "tables": {
            "am_law_article": [
                "会計",
                "監査",
                "開示",
                "金融商品取引",
                "計算書類",
                "貸借対照表",
                "損益計算書",
                "キャッシュ・フロー",
                "連結",
                "減損",
                "公認会計士",
                "内部統制",
            ],
            "adoption_records": [
                "M&A",
                "合併",
                "事業承継",
                "DD",
                "デューデリ",
                "IPO",
                "上場",
                "開示",
            ],
            "court_decisions": ["商事", "会社法", "計算書類"],
        },
        "max_per_table": 30000,
    },
    "gyouseishoshi": {
        "tables": {
            "programs": None,
            "am_law_article": [
                "許可",
                "認可",
                "届出",
                "免許",
                "建設業",
                "宅地建物",
                "古物営業",
                "風俗営業",
                "産業廃棄物",
                "運送業",
                "酒類",
                "食品衛生",
                "外国人",
                "在留",
            ],
            "adoption_records": [
                "補助金",
                "助成金",
                "許認可",
                "業許可",
                "申請",
            ],
        },
        "max_per_table": 30000,
    },
    "shihoshoshi": {
        "tables": {
            "am_law_article": [
                "商業登記",
                "不動産登記",
                "会社法",
                "民法",
                "登記",
                "抵当権",
                "根抵当",
                "供託",
                "成年後見",
                "信託",
                "相続",
                "遺言",
                "債権",
                "債務",
            ],
            "court_decisions": None,
            "nta_saiketsu": ["商事", "登記", "相続"],
        },
        "max_per_table": 30000,
    },
    "chusho_keieisha": {
        "tables": {
            "programs": None,
            "adoption_records": [
                "中小",
                "事業者",
                "小規模",
                "創業",
                "再構築",
                "持続化",
                "省力化",
                "DX",
            ],
            "invoice_registrants": None,
        },
        "max_per_table": 30000,
    },
}


@dataclass
class CohortStats:
    """Per-cohort × per-table stats for the prep ledger."""

    cohort: str
    table_breakdown: dict[str, int] = field(default_factory=dict)
    total_kept: int = 0
    train_rows: int = 0
    val_rows: int = 0


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


def _match(text: str, keywords: list[str] | None) -> bool:
    if keywords is None:
        return True
    return any(kw in text for kw in keywords)


def collect_cohort(
    s3: Any,
    bucket: str,
    source_prefix: str,
    cohort: str,
    *,
    seen_hashes: set[str],
    rng: random.Random,
) -> tuple[list[dict[str, Any]], CohortStats]:
    """Collect a cohort's rows by applying per-table keyword filter."""

    spec = COHORT_FILTERS[cohort]
    tables: dict[str, Any] = spec["tables"]
    max_per_table: int = int(spec["max_per_table"])
    stats = CohortStats(cohort=cohort)
    cohort_rows: list[dict[str, Any]] = []
    for table, keywords in tables.items():
        kw_list: list[str] | None = list(keywords) if keywords else None
        prefix = f"{source_prefix.rstrip('/')}/{table}/"
        parts = _list_parts(s3, bucket, prefix)
        table_rows: list[dict[str, Any]] = []
        for key in parts:
            for obj in _stream_lines(s3, bucket, key):
                text = obj.get("inputs") or obj.get("text") or ""
                text = _normalize_text(str(text))
                if len(text) < 8:
                    continue
                if not _match(text, kw_list):
                    continue
                digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                table_rows.append(
                    {
                        "_id": str(obj.get("id", "")),
                        "text": text,
                        "_table": table,
                        "_cohort": cohort,
                    }
                )
        # Per-table cap (random sample if oversized).
        if len(table_rows) > max_per_table:
            rng.shuffle(table_rows)
            table_rows = table_rows[:max_per_table]
        stats.table_breakdown[table] = len(table_rows)
        logger.info("  %s/%s -> kept=%d", cohort, table, len(table_rows))
        cohort_rows.extend(table_rows)
    stats.total_kept = len(cohort_rows)
    return cohort_rows, stats


def _serialize(rows: list[dict[str, Any]]) -> bytes:
    buf = io.BytesIO()
    for r in rows:
        buf.write(json.dumps({"text": r["text"]}, ensure_ascii=False).encode("utf-8") + b"\n")
    return buf.getvalue()


def run(
    *,
    bucket: str,
    source_prefix: str,
    target_prefix_tpl: str,
    val_ratio: float,
    region: str,
    profile: str,
    cohorts: list[str],
    dry_run: bool = True,
    seed: int = 42,
) -> dict[str, Any]:
    """Slice corpus_export/* into per-cohort finetune_corpus_lora_cohort_X/."""

    s3 = _boto3_s3(region, profile)
    rng = random.Random(seed)
    all_manifests: dict[str, Any] = {}
    for cohort in cohorts:
        seen: set[str] = set()  # Per-cohort dedup; cross-cohort overlap is allowed.
        rows, stats = collect_cohort(
            s3,
            bucket,
            source_prefix,
            cohort,
            seen_hashes=seen,
            rng=rng,
        )
        rng.shuffle(rows)
        n = len(rows)
        cut = max(1, int(n * (1.0 - val_ratio)))
        train = rows[:cut]
        val = rows[cut:]
        stats.train_rows = len(train)
        stats.val_rows = len(val)
        train_bytes = _serialize(train)
        val_bytes = _serialize(val)
        target_prefix = target_prefix_tpl.format(cohort=cohort)
        train_key = f"{target_prefix.rstrip('/')}/train.jsonl"
        val_key = f"{target_prefix.rstrip('/')}/val.jsonl"
        manifest_key = f"{target_prefix.rstrip('/')}/_manifest.json"
        manifest = {
            "cohort": cohort,
            "generated_at": datetime.now(UTC).isoformat(),
            "bucket": bucket,
            "source_prefix": source_prefix,
            "target_prefix": target_prefix,
            "seed": seed,
            "val_ratio": val_ratio,
            "total_rows": n,
            "train_rows": len(train),
            "val_rows": len(val),
            "train_sha256": hashlib.sha256(train_bytes).hexdigest(),
            "val_sha256": hashlib.sha256(val_bytes).hexdigest(),
            "table_breakdown": stats.table_breakdown,
            "filter_spec": COHORT_FILTERS[cohort],
            "dry_run": dry_run,
        }
        if not dry_run:
            s3.put_object(
                Bucket=bucket,
                Key=train_key,
                Body=train_bytes,
                ContentType="application/jsonlines",
            )
            s3.put_object(
                Bucket=bucket,
                Key=val_key,
                Body=val_bytes,
                ContentType="application/jsonlines",
            )
            s3.put_object(
                Bucket=bucket,
                Key=manifest_key,
                Body=json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                ContentType="application/json",
            )
        sha_short = str(manifest["train_sha256"])[:12]
        logger.info(
            "  [%s] train=%d val=%d (sha=%s)",
            cohort,
            len(train),
            len(val),
            sha_short,
        )
        all_manifests[cohort] = manifest
    return all_manifests


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "BB4 — per-cohort LoRA training corpus prep "
            "(slice corpus_export/* into 5 cohort shards)."
        )
    )
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--source-prefix", default="corpus_export")
    p.add_argument(
        "--target-prefix-tpl",
        default="finetune_corpus_lora_cohort_{cohort}",
        help="Template; {cohort} is substituted per cohort.",
    )
    p.add_argument("--val-ratio", type=float, default=0.05)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--cohorts",
        nargs="+",
        default=list(COHORT_FILTERS.keys()),
        choices=list(COHORT_FILTERS.keys()),
    )
    p.add_argument("--commit", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    dry_run = not args.commit and os.environ.get("DRY_RUN", "1") != "0"
    manifests = run(
        bucket=args.bucket,
        source_prefix=args.source_prefix,
        target_prefix_tpl=args.target_prefix_tpl,
        val_ratio=args.val_ratio,
        region=args.region,
        profile=args.profile,
        cohorts=list(args.cohorts),
        dry_run=dry_run,
        seed=args.seed,
    )
    print(json.dumps(manifests, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
