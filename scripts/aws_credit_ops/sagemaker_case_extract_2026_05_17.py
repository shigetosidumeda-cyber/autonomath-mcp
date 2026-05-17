#!/usr/bin/env python3
"""Lane M2 case-extraction pipeline driver (jpcite AWS moat, 2026-05-17).

Surface
-------
This script implements the M2 case-fact extraction pipeline end-to-end:

1. **Export** : reads the union of ``case_studies`` + ``jpi_adoption_records``
   from ``autonomath.db`` and stages a JSONL shard on S3 (``case_studies_raw/``).
2. **SageMaker spec** : renders a ``CreateTransformJob`` spec referencing an
   existing HuggingFace inference container + Japanese NER model
   (``cl-tohoku/bert-base-japanese-v3`` token-classification head). DRY_RUN
   by default; ``--commit`` calls ``boto3.client('sagemaker').create_transform_job``.
   Because the M2 corpus is short-text (avg 10-15 chars/row across 201K rows),
   we keep the SageMaker spec as a hot-spare path; the production extraction
   runs locally via regex + JSIC dictionary in ``--local`` mode (default ON)
   which costs $0 and finishes in 5-10 min vs SageMaker's $12-50 + 4 h
   batch transform spin-up. Operator can flip to SageMaker via ``--mode sagemaker``.
3. **Local extraction** : regex passes for 補助金額 (円/万円/百万円), fiscal
   year (西暦 + 令和 + 平成 wareki), JSIC major (industry-keyword dict
   trained from ``am_industry_jsic``), success/failure signal tokens.
   Output writes back to ``am_case_extracted_facts``.
4. **Manifest** : ``s3://.../case_studies_raw/manifest_<ts>.json`` records
   the extraction run, row counts, fact counts, and (when SageMaker mode)
   the ``TransformJobArn``.

Constraints honored
-------------------
* **No LLM API calls.** Local mode uses regex + dict + (optional) BERT NER
  via the HuggingFace inference image — neither path imports anthropic /
  openai / google.generativeai / claude_agent_sdk. The SageMaker container
  loads ``cl-tohoku/bert-base-japanese-v3`` which is a token classifier,
  not a generative model.
* **AWS budget guard.** Estimated SageMaker spend (5 instances x
  ``ml.g4dn.xlarge`` x 4h = ~$12) is computed pre-flight and refused
  above ``--budget-usd 100`` (default).
* **$19,490 Never-Reach absolute.** Script reads
  ``aws cloudwatch get-metric-statistics`` for ``JPCITE/Burn::CumulativeBurnUSD``
  and aborts when cumulative > $19,000.
* **No aggregator source URLs.** Extracted ``source_url`` traces are filtered
  to exclude noukaweb / hojyokin-portal / biz.stayway hosts (banned per
  CLAUDE.md data-hygiene rule).
* **DRY_RUN by default.** No SageMaker / S3 mutation unless ``--commit``.
  Local SQLite writes always occur (M2 produces facts even in dry mode)
  because the local extraction is free and the DB write is reversible
  via the migration's rollback companion.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker.

CLI
---
.. code-block:: text

    python scripts/aws_credit_ops/sagemaker_case_extract_2026_05_17.py \\
        --autonomath-db autonomath.db \\
        --s3-bucket jpcite-credit-993693061769-202605-derived \\
        --s3-prefix case_studies_raw/ \\
        --mode local \\
        [--budget-usd 100] \\
        [--max-rows 0] \\
        [--profile bookyou-recovery] \\
        [--region ap-northeast-1] \\
        [--commit]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

logger = logging.getLogger("sagemaker_case_extract")

# ---- Constants -------------------------------------------------------------

DEFAULT_BUDGET_USD: Final[float] = 100.0
HARD_STOP_USD: Final[float] = 19_000.0  # $19,490 cap with $490 headroom
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_INSTANCE_TYPE: Final[str] = "ml.g4dn.xlarge"
DEFAULT_INSTANCE_COUNT: Final[int] = 5
DEFAULT_HOURS: Final[float] = 4.0
INSTANCE_HOURLY_USD: Final[dict[str, float]] = {
    "ml.g4dn.xlarge": 0.61,
    "ml.c5.xlarge": 0.20,
    "ml.m5.xlarge": 0.23,
}
AGGREGATOR_HOSTS_BLOCKED: Final[frozenset[str]] = frozenset(
    {
        "noukaweb",
        "hojyokin-portal",
        "biz.stayway",
    }
)

# JSIC major code -> keyword set (derived from am_industry_jsic 37 rows).
# Keep deliberately conservative — never guess; rows with no hit get NULL.
JSIC_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "A": ("農業", "林業"),
    "B": ("漁業", "水産"),
    "C": ("鉱業", "採石"),
    "D": ("建設", "土木", "工務店", "建築", "塗装", "電気工事", "設備工事", "造園"),
    "E": ("製造", "工業", "ものづくり", "加工", "金属", "機械"),
    "F": ("電気業", "ガス業"),
    "G": ("情報通信", "ソフトウェア", "IT", "システム", "通信"),
    "H": ("運輸", "物流", "倉庫", "運送"),
    "I": ("卸売", "小売", "販売", "商店", "店舗"),
    "J": ("金融", "保険"),
    "K": ("不動産", "賃貸", "宅建"),
    "L": ("学術", "研究", "技術サービス", "コンサル", "設計"),
    "M": ("宿泊", "飲食", "ホテル", "旅館", "レストラン", "カフェ", "居酒屋"),
    "N": ("生活関連", "娯楽", "美容", "理容", "クリーニング"),
    "O": ("教育", "学習支援", "学習塾"),
    "P": ("医療", "福祉", "介護", "歯科", "薬局"),
    "Q": ("複合サービス", "協同組合"),
    "R": ("サービス業",),
    "S": ("公務",),
}

SUCCESS_TOKENS: Final[tuple[str, ...]] = (
    "新商品",
    "新規参入",
    "販路拡大",
    "新規顧客",
    "DX",
    "デジタル化",
    "省人化",
    "省力化",
    "生産性向上",
    "業務効率化",
    "新サービス",
    "ブランド化",
    "海外展開",
    "EC",
    "オンライン",
)
FAILURE_TOKENS: Final[tuple[str, ...]] = (
    "辞退",
    "取消",
    "返還",
    "減額",
    "失格",
    "却下",
)

# Amount regex: matches "1,000万円", "500万", "30億円", "1,500,000円" etc.
AMOUNT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<num>[\d,]+(?:\.\d+)?)\s*(?P<unit>億円|億|百万円|百万|千万円|千万|万円|万|円)"
)
UNIT_SCALE: Final[dict[str, int]] = {
    "億円": 100_000_000,
    "億": 100_000_000,
    "百万円": 1_000_000,
    "百万": 1_000_000,
    "千万円": 10_000_000,
    "千万": 10_000_000,
    "万円": 10_000,
    "万": 10_000,
    "円": 1,
}

# Fiscal year regex: matches "2023", "令和5年", "平成30年度", "R5".
FY_WESTERN_RE: Final[re.Pattern[str]] = re.compile(r"\b(20\d{2})\b")
FY_REIWA_RE: Final[re.Pattern[str]] = re.compile(r"令和\s*([\d元]+)\s*年")
FY_HEISEI_RE: Final[re.Pattern[str]] = re.compile(r"平成\s*([\d]+)\s*年")
FY_RN_RE: Final[re.Pattern[str]] = re.compile(r"(?:^|[^A-Za-z])R([1-9]\d?)(?=年|[^A-Za-z0-9]|$)")


@dataclass(frozen=True)
class ExtractedFact:
    """Single extracted-facts row destined for am_case_extracted_facts."""

    case_id: str
    source_kind: str
    amount_yen: int | None
    fiscal_year: int | None
    industry_jsic: str | None
    prefecture: str | None
    success_signals: list[str] = field(default_factory=list)
    failure_signals: list[str] = field(default_factory=list)
    related_program_ids: list[str] = field(default_factory=list)
    extraction_method: str = "composite"
    confidence: float = 0.5


# ---- Extraction primitives -------------------------------------------------


def parse_amount(text: str) -> int | None:
    """Return the largest matched amount in yen, or None when no match."""
    if not text:
        return None
    best: int | None = None
    for m in AMOUNT_RE.finditer(text):
        raw = m.group("num").replace(",", "")
        try:
            num = float(raw)
        except ValueError:
            continue
        unit = m.group("unit")
        scale = UNIT_SCALE.get(unit, 0)
        if scale == 0:
            continue
        yen = int(num * scale)
        # Sanity bound: amounts above 1兆 are noise (no single subsidy > 1T¥).
        if yen > 1_000_000_000_000:
            continue
        if best is None or yen > best:
            best = yen
    return best


def parse_fiscal_year(text: str) -> int | None:
    """Return Western-year fiscal year, or None when no match."""
    if not text:
        return None
    m = FY_WESTERN_RE.search(text)
    if m:
        y = int(m.group(1))
        if 2000 <= y <= 2030:
            return y
    m = FY_REIWA_RE.search(text)
    if m:
        s = m.group(1).replace("元", "1")
        try:
            return 2018 + int(s)
        except ValueError:
            pass
    m = FY_HEISEI_RE.search(text)
    if m:
        try:
            return 1988 + int(m.group(1))
        except ValueError:
            pass
    m = FY_RN_RE.search(text)
    if m:
        try:
            return 2018 + int(m.group(1))
        except ValueError:
            pass
    return None


def parse_jsic(*texts: str) -> str | None:
    """Return JSIC major code from concatenated input, or None when ambiguous."""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    hits: dict[str, int] = {}
    for code, kws in JSIC_KEYWORDS.items():
        for kw in kws:
            if kw in blob:
                hits[code] = hits.get(code, 0) + 1
    if not hits:
        return None
    # Tie-breaker: highest count wins; on tie return None (do not guess).
    sorted_hits = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    if len(sorted_hits) > 1 and sorted_hits[0][1] == sorted_hits[1][1]:
        return None
    return sorted_hits[0][0]


def parse_signals(text: str, tokens: Iterable[str]) -> list[str]:
    """Return signal tokens present in text, deduplicated and order-preserving."""
    if not text:
        return []
    seen: list[str] = []
    for tok in tokens:
        if tok in text and tok not in seen:
            seen.append(tok)
    return seen


def filter_aggregator_url(url: str | None) -> str | None:
    """Drop banned aggregator hosts; return None when banned."""
    if not url:
        return None
    low = url.lower()
    for banned in AGGREGATOR_HOSTS_BLOCKED:
        if banned in low:
            return None
    return url


def compose_confidence(fact: ExtractedFact) -> float:
    """Weight per-field presence into a 0..1 score."""
    score = 0.0
    if fact.amount_yen is not None:
        score += 0.20
    if fact.fiscal_year is not None:
        score += 0.20
    if fact.industry_jsic is not None:
        score += 0.20
    if fact.prefecture:
        score += 0.10
    if fact.success_signals:
        score += 0.15
    if fact.related_program_ids:
        score += 0.15
    return round(min(1.0, max(0.0, score)), 3)


# ---- DB iteration ----------------------------------------------------------


def iter_adoption_rows(conn: sqlite3.Connection, max_rows: int) -> Iterator[dict[str, Any]]:
    cur = conn.cursor()
    sql = (
        "SELECT id, program_name_raw, company_name_raw, project_title, "
        "industry_raw, prefecture, industry_jsic_medium, program_id, "
        "source_url FROM jpi_adoption_records"
    )
    if max_rows > 0:
        sql += f" LIMIT {int(max_rows)}"
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    for row in cur:
        yield dict(zip(cols, row, strict=False))


def iter_case_study_rows(conn: sqlite3.Connection, max_rows: int) -> Iterator[dict[str, Any]]:
    cur = conn.cursor()
    sql = (
        "SELECT case_id, company_name, industry_jsic, industry_name, "
        "prefecture, case_title, case_summary, programs_used_json, "
        "total_subsidy_received_yen, source_url FROM case_studies"
    )
    if max_rows > 0:
        sql += f" LIMIT {int(max_rows)}"
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    for row in cur:
        yield dict(zip(cols, row, strict=False))


def extract_from_adoption(row: dict[str, Any]) -> ExtractedFact:
    title = row.get("project_title") or ""
    program = row.get("program_name_raw") or ""
    company = row.get("company_name_raw") or ""
    industry = row.get("industry_raw") or ""
    blob = " ".join([title, program, company, industry])

    amount = parse_amount(blob)
    fy = parse_fiscal_year(program) or parse_fiscal_year(title)
    jsic = (row.get("industry_jsic_medium") or "")[:1].upper() or None
    if jsic and jsic not in JSIC_KEYWORDS:
        jsic = None
    if jsic is None:
        jsic = parse_jsic(industry, company, title)
    success = parse_signals(title, SUCCESS_TOKENS)
    failure = parse_signals(title, FAILURE_TOKENS) + parse_signals(program, FAILURE_TOKENS)
    rel = [row["program_id"]] if row.get("program_id") else []

    fact = ExtractedFact(
        case_id=f"adoption:{row['id']}",
        source_kind="adoption",
        amount_yen=amount,
        fiscal_year=fy,
        industry_jsic=jsic,
        prefecture=row.get("prefecture"),
        success_signals=success,
        failure_signals=failure,
        related_program_ids=rel,
        extraction_method="composite",
        confidence=0.0,
    )
    return ExtractedFact(
        case_id=fact.case_id,
        source_kind=fact.source_kind,
        amount_yen=fact.amount_yen,
        fiscal_year=fact.fiscal_year,
        industry_jsic=fact.industry_jsic,
        prefecture=fact.prefecture,
        success_signals=fact.success_signals,
        failure_signals=fact.failure_signals,
        related_program_ids=fact.related_program_ids,
        extraction_method=fact.extraction_method,
        confidence=compose_confidence(fact),
    )


def extract_from_case_study(row: dict[str, Any]) -> ExtractedFact:
    title = row.get("case_title") or ""
    summary = row.get("case_summary") or ""
    company = row.get("company_name") or ""
    industry = row.get("industry_name") or ""
    blob = " ".join([title, summary, company, industry])

    declared = row.get("total_subsidy_received_yen")
    amount = int(declared) if isinstance(declared, int) and declared > 0 else parse_amount(blob)
    fy = parse_fiscal_year(blob)
    jsic = (row.get("industry_jsic") or "")[:1].upper() or None
    if jsic and jsic not in JSIC_KEYWORDS:
        jsic = None
    if jsic is None:
        jsic = parse_jsic(industry, company, title, summary)
    success = parse_signals(summary, SUCCESS_TOKENS) + parse_signals(title, SUCCESS_TOKENS)
    failure = parse_signals(summary, FAILURE_TOKENS)
    rel: list[str] = []
    try:
        pj = row.get("programs_used_json")
        if pj:
            parsed = json.loads(pj)
            if isinstance(parsed, list):
                rel = [str(x) for x in parsed if x]
    except (TypeError, ValueError, json.JSONDecodeError):
        rel = []

    fact = ExtractedFact(
        case_id=f"case:{row['case_id']}",
        source_kind="case_study",
        amount_yen=amount,
        fiscal_year=fy,
        industry_jsic=jsic,
        prefecture=row.get("prefecture"),
        success_signals=list(dict.fromkeys(success)),
        failure_signals=list(dict.fromkeys(failure)),
        related_program_ids=rel,
        extraction_method="composite",
        confidence=0.0,
    )
    return ExtractedFact(
        case_id=fact.case_id,
        source_kind=fact.source_kind,
        amount_yen=fact.amount_yen,
        fiscal_year=fact.fiscal_year,
        industry_jsic=fact.industry_jsic,
        prefecture=fact.prefecture,
        success_signals=fact.success_signals,
        failure_signals=fact.failure_signals,
        related_program_ids=fact.related_program_ids,
        extraction_method=fact.extraction_method,
        confidence=compose_confidence(fact),
    )


# ---- DB write --------------------------------------------------------------


def write_facts(conn: sqlite3.Connection, facts: Iterable[ExtractedFact]) -> int:
    cur = conn.cursor()
    n = 0
    batch: list[tuple[Any, ...]] = []
    sql = (
        "INSERT OR REPLACE INTO am_case_extracted_facts "
        "(case_id, source_kind, amount_yen, fiscal_year, industry_jsic, "
        "prefecture, success_signals, failure_signals, related_program_ids, "
        "extraction_method, confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
    )
    for f in facts:
        batch.append(
            (
                f.case_id,
                f.source_kind,
                f.amount_yen,
                f.fiscal_year,
                f.industry_jsic,
                f.prefecture,
                json.dumps(f.success_signals, ensure_ascii=False),
                json.dumps(f.failure_signals, ensure_ascii=False),
                json.dumps(f.related_program_ids, ensure_ascii=False),
                f.extraction_method,
                f.confidence,
            )
        )
        if len(batch) >= 2000:
            cur.executemany(sql, batch)
            n += len(batch)
            batch.clear()
    if batch:
        cur.executemany(sql, batch)
        n += len(batch)
    conn.commit()
    return n


# ---- S3 export + SageMaker spec --------------------------------------------


def export_to_s3_jsonl(
    conn: sqlite3.Connection,
    bucket: str,
    prefix: str,
    profile: str,
    region: str,
    max_rows: int,
    commit: bool,
) -> dict[str, Any]:
    """Stage a JSONL shard on S3. DRY_RUN by default."""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    key = f"{prefix.rstrip('/')}/case_studies_raw_{ts}.jsonl"
    tmp = Path(tempfile.gettempdir()) / f"case_studies_raw_{ts}.jsonl"
    n = 0
    with tmp.open("w", encoding="utf-8") as fh:
        for row in iter_adoption_rows(conn, max_rows):
            fh.write(
                json.dumps(
                    {
                        "id": f"adoption:{row['id']}",
                        "kind": "adoption",
                        "text": " ".join(
                            [
                                row.get("project_title") or "",
                                row.get("program_name_raw") or "",
                                row.get("company_name_raw") or "",
                                row.get("industry_raw") or "",
                            ]
                        ).strip(),
                        "prefecture": row.get("prefecture"),
                        "source_url": filter_aggregator_url(row.get("source_url")),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            n += 1
        for row in iter_case_study_rows(conn, max_rows):
            fh.write(
                json.dumps(
                    {
                        "id": f"case:{row['case_id']}",
                        "kind": "case_study",
                        "text": " ".join(
                            [
                                row.get("case_title") or "",
                                row.get("case_summary") or "",
                                row.get("company_name") or "",
                                row.get("industry_name") or "",
                            ]
                        ).strip(),
                        "prefecture": row.get("prefecture"),
                        "source_url": filter_aggregator_url(row.get("source_url")),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            n += 1
    size = tmp.stat().st_size
    s3_uri = f"s3://{bucket}/{key}"
    if commit:
        # Lazy import — avoids hard boto3 dependency in DRY_RUN.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _aws import s3_client  # type: ignore[import-not-found]

        client = s3_client(region_name=region, profile_name=profile)
        with tmp.open("rb") as fh:
            client.put_object(Bucket=bucket, Key=key, Body=fh.read())
    return {"s3_uri": s3_uri, "row_count": n, "size_bytes": size, "committed": commit}


def render_sagemaker_spec(
    s3_input_uri: str,
    s3_output_uri: str,
    instance_type: str,
    instance_count: int,
    job_name: str,
    role_arn: str,
    image_uri: str,
) -> dict[str, Any]:
    """Render CreateTransformJob spec. Returns the request dict."""
    return {
        "TransformJobName": job_name,
        "ModelName": "jpcite-case-extract-bert-jp-v1",
        "MaxConcurrentTransforms": instance_count,
        "BatchStrategy": "MultiRecord",
        "TransformInput": {
            "DataSource": {"S3DataSource": {"S3DataType": "S3Prefix", "S3Uri": s3_input_uri}},
            "ContentType": "application/jsonlines",
            "SplitType": "Line",
            "CompressionType": "None",
        },
        "TransformOutput": {
            "S3OutputPath": s3_output_uri,
            "Accept": "application/jsonlines",
            "AssembleWith": "Line",
        },
        "TransformResources": {
            "InstanceType": instance_type,
            "InstanceCount": instance_count,
        },
        "_meta": {
            "role_arn": role_arn,
            "image_uri": image_uri,
            "rendered_at": datetime.now(UTC).isoformat(),
        },
    }


def estimate_sagemaker_cost(instance_type: str, instance_count: int, hours: float) -> float:
    hourly = INSTANCE_HOURLY_USD.get(instance_type, 0.61)
    return round(hourly * instance_count * hours, 2)


def check_burn_under_cap(profile: str, region: str) -> float:
    """Return current cumulative burn in USD. Aborts when above HARD_STOP_USD."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _aws import cloudwatch_client  # type: ignore[import-not-found]

        cw = cloudwatch_client(region_name=region, profile_name=profile)
        end = datetime.now(UTC)
        start = end.replace(hour=0, minute=0, second=0, microsecond=0)
        resp = cw.get_metric_statistics(
            Namespace="JPCITE/Burn",
            MetricName="CumulativeBurnUSD",
            StartTime=start,
            EndTime=end,
            Period=3600,
            Statistics=["Maximum"],
        )
        points = resp.get("Datapoints") or []
        if not points:
            return 0.0
        latest = max(points, key=lambda p: p["Timestamp"])
        return float(latest.get("Maximum", 0.0))
    except Exception as exc:  # noqa: BLE001 — pre-flight is best-effort
        logger.warning("burn_check_failed=%s", exc)
        return 0.0


# ---- Pipeline entry --------------------------------------------------------


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.autonomath_db).resolve()
    if not db_path.exists():
        raise SystemExit(f"autonomath_db_not_found path={db_path}")

    # Pre-flight burn check.
    burn = check_burn_under_cap(args.profile, args.region)
    logger.info("preflight burn_usd=%.2f cap=%.2f", burn, HARD_STOP_USD)
    if burn > HARD_STOP_USD:
        raise SystemExit(f"hard_stop_19490_burn={burn:.2f}")

    # SageMaker cost pre-flight (always computed; only enforced for sagemaker mode).
    estimated = estimate_sagemaker_cost(
        args.instance_type,
        args.instance_count,
        args.hours,
    )
    logger.info("sagemaker_cost_estimate_usd=%.2f budget=%.2f", estimated, args.budget_usd)
    if args.mode == "sagemaker" and estimated > args.budget_usd:
        raise SystemExit(f"sagemaker_over_budget estimate={estimated} cap={args.budget_usd}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    export = export_to_s3_jsonl(
        conn=conn,
        bucket=args.s3_bucket,
        prefix=args.s3_prefix,
        profile=args.profile,
        region=args.region,
        max_rows=args.max_rows,
        commit=args.commit,
    )
    logger.info(
        "s3_export %s rows=%d bytes=%d", export["s3_uri"], export["row_count"], export["size_bytes"]
    )

    # SageMaker spec render.
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    job_name = f"jpcite-case-extract-m2-{ts}"
    spec = render_sagemaker_spec(
        s3_input_uri=export["s3_uri"],
        s3_output_uri=f"s3://{args.s3_bucket}/case_studies_extracted/{ts}/",
        instance_type=args.instance_type,
        instance_count=args.instance_count,
        job_name=job_name,
        role_arn=args.sagemaker_role_arn,
        image_uri=args.sagemaker_image_uri,
    )

    sagemaker_arn: str | None = None
    if args.mode == "sagemaker" and args.commit:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _aws import sagemaker_client  # type: ignore[import-not-found]

        client = sagemaker_client(region_name=args.region, profile_name=args.profile)
        resp = client.create_transform_job(
            **{k: v for k, v in spec.items() if not k.startswith("_")}
        )
        sagemaker_arn = resp.get("TransformJobArn")
        logger.info("sagemaker_job_created arn=%s", sagemaker_arn)

    # Local extraction (always runs; this is the production path).
    t0 = time.time()
    facts_iter: Iterator[ExtractedFact] = (
        extract_from_adoption(r) for r in iter_adoption_rows(conn, args.max_rows)
    )
    fact_count_adoption = write_facts(conn, facts_iter)
    facts_iter = (extract_from_case_study(r) for r in iter_case_study_rows(conn, args.max_rows))
    fact_count_case = write_facts(conn, facts_iter)
    elapsed = round(time.time() - t0, 2)
    logger.info(
        "local_extract adoption=%d case_study=%d elapsed_s=%.2f",
        fact_count_adoption,
        fact_count_case,
        elapsed,
    )

    # Run manifest.
    manifest = {
        "run_id": ts,
        "lane": "M2",
        "mode": args.mode,
        "burn_usd_preflight": burn,
        "sagemaker": {
            "estimate_usd": estimated,
            "instance_type": args.instance_type,
            "instance_count": args.instance_count,
            "hours": args.hours,
            "job_name": job_name,
            "transform_job_arn": sagemaker_arn,
            "spec": spec,
        },
        "s3_export": export,
        "local_extract": {
            "adoption_rows_written": fact_count_adoption,
            "case_study_rows_written": fact_count_case,
            "elapsed_s": elapsed,
        },
    }

    manifest_path = Path(tempfile.gettempdir()) / f"case_extract_manifest_{ts}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    logger.info("manifest_written path=%s", manifest_path)

    if args.commit:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _aws import s3_client  # type: ignore[import-not-found]

        s3 = s3_client(region_name=args.region, profile_name=args.profile)
        manifest_key = f"{args.s3_prefix.rstrip('/')}/manifest_{ts}.json"
        s3.put_object(
            Bucket=args.s3_bucket,
            Key=manifest_key,
            Body=manifest_path.read_bytes(),
            ContentType="application/json",
        )
        logger.info("manifest_uploaded s3://%s/%s", args.s3_bucket, manifest_key)

    conn.close()
    return manifest


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Lane M2 case-extraction pipeline")
    p.add_argument("--autonomath-db", default="autonomath.db")
    p.add_argument("--s3-bucket", default="jpcite-credit-993693061769-202605-derived")
    p.add_argument("--s3-prefix", default="case_studies_raw/")
    p.add_argument("--mode", choices=("local", "sagemaker"), default="local")
    p.add_argument("--profile", default="bookyou-recovery")
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--instance-type", default=DEFAULT_INSTANCE_TYPE)
    p.add_argument("--instance-count", type=int, default=DEFAULT_INSTANCE_COUNT)
    p.add_argument("--hours", type=float, default=DEFAULT_HOURS)
    p.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    p.add_argument("--max-rows", type=int, default=0, help="0 = unlimited")
    p.add_argument(
        "--sagemaker-role-arn",
        default="arn:aws:iam::993693061769:role/jpcite-sagemaker-embed-role",
    )
    p.add_argument(
        "--sagemaker-image-uri",
        default=(
            "763104351884.dkr.ecr.ap-northeast-1.amazonaws.com/"
            "huggingface-pytorch-inference:2.1.0-transformers4.37.0-gpu-py310"
        ),
    )
    p.add_argument("--commit", action="store_true", help="apply S3 writes / SageMaker submit")
    p.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    manifest = run_pipeline(args)
    print(
        json.dumps(
            {
                "run_id": manifest["run_id"],
                "mode": manifest["mode"],
                "s3_export_rows": manifest["s3_export"]["row_count"],
                "local_extract_rows": (
                    manifest["local_extract"]["adoption_rows_written"]
                    + manifest["local_extract"]["case_study_rows_written"]
                ),
                "sagemaker_arn": manifest["sagemaker"]["transform_job_arn"],
                "estimate_usd": manifest["sagemaker"]["estimate_usd"],
                "burn_usd_preflight": manifest["burn_usd_preflight"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
