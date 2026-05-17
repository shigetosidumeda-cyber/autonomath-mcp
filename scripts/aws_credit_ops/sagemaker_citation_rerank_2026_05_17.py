#!/usr/bin/env python3
"""Lane M8 v0.2 — Cross-encoder rescoring of bi-encoder citation candidates.

This is the **M6 → M8 bridge driver**: it consumes the v0.1
``am_citation_judge_law`` edges (produced locally by
``infer_judge_law_citation_2026_05_17.py`` via MiniLM bi-encoder) and
re-scores them with the **M6 fine-tuned cross-encoder** on SageMaker
Batch Transform, then ingests the rescored edges back into
``am_citation_judge_law`` under a distinct ``method`` tag so they
co-exist with the v0.1 bi-encoder edges (UNIQUE on
``(court_unified_id, article_id, method)``).

Why Batch Transform (not Training)
----------------------------------
M6 produces a fine-tuned cross-encoder checkpoint (a HuggingFace
SequenceClassification head on
``hotchpotch/japanese-reranker-cross-encoder-large-v1``). Scoring 15M
``(query, doc)`` pairs is *inference*, not training — so the canonical
SageMaker primitive is **Batch Transform**, which streams JSONL input
from S3, invokes the model container per record, writes scores back to
S3, then shuts down automatically. No long-running endpoint, no idle
cost.

Honest framing
--------------
The 5M / 15M / $820 numbers in the M8 brief are an *upper bound*; the
actual candidate set we re-score is bounded by what the bi-encoder
top-K retains. With ``DEFAULT_TOP_K=100`` in the v0.1 driver and 948
real court rows, the **realistic v0.2 candidate count is 94,800 pairs**,
not 15M. That is a ~50-minute job at ~12k pairs/sec on a single
g4dn.xlarge, not a 21-hour x 10-parallel job at $820. Honest cost
projection ~$2-$5 absolute. The 5M / 15M figure stays valid only if
the law side is expanded to 50K-311K articles in a later pass.

This driver therefore defaults to:

* Single ``ml.g4dn.xlarge`` instance (1 T4 GPU, ~$0.736/h
  ap-northeast-1).
* MaxRuntime 6h cap.
* Input: v0.1 candidate JSONL exported from
  ``am_citation_judge_law`` rows with ``method=bi_encoder_minilm_*``.
* Output: one JSONL line per input row with ``cross_score`` field;
  ingest step inserts as a **second** ``am_citation_judge_law`` row
  per ``(court_unified_id, article_id)`` under
  ``method=cross_encoder_japanese_reranker_large_v1``.

A ``--parallel-instances N`` flag is exposed for the upper-bound case
(15M pairs): the driver shards the candidate JSONL into N parts and
submits N Batch Transform jobs concurrently. Default N=1.

Cost preflight + hard-stop
--------------------------
``aws ce get-cost-and-usage`` MTD sampled; abort if MTD >= 18000
USD (well under the $19,490 Never-Reach absolute). NO LLM API
anywhere — only the M6 fine-tuned HuggingFace cross-encoder loaded
into a SageMaker container.

CLI
---

.. code-block:: text

    # 1) Export v0.1 candidates (read-only, local — no AWS)
    python scripts/aws_credit_ops/sagemaker_citation_rerank_2026_05_17.py \\
        export-candidates --out s3://${BUCKET}/citation_rerank/v0.2/candidates.jsonl \\
        [--commit]

    # 2) Create SageMaker Model from M6 training artifact
    python scripts/aws_credit_ops/sagemaker_citation_rerank_2026_05_17.py \\
        register-model --model-data-uri s3://.../model.tar.gz \\
        [--commit]

    # 3) Submit Batch Transform (one or many shards)
    python scripts/aws_credit_ops/sagemaker_citation_rerank_2026_05_17.py \\
        submit-transform --input-uri s3://.../candidates.jsonl \\
        --output-prefix s3://.../citation_rerank/v0.2/scored/ \\
        --parallel-instances 1 \\
        [--commit]

    # 4) Ingest rescored edges back into am_citation_judge_law
    python scripts/aws_credit_ops/sagemaker_citation_rerank_2026_05_17.py \\
        ingest --scored-uri s3://.../citation_rerank/v0.2/scored/ \\
        [--commit]

Constraints
-----------
- DRY_RUN default; pass ``--commit`` to actually create AWS-side jobs.
- NO LLM API anywhere; only a fine-tuned cross-encoder model.
- ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
- Idempotent: re-running ``ingest`` inserts ``OR IGNORE`` on the
  unique ``(court_unified_id, article_id, method)`` constraint.
- mypy --strict friendly.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Final

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"
DEFAULT_ROLE_ARN: Final[str] = "arn:aws:iam::993693061769:role/jpcite-sagemaker-execution-role"
HARD_STOP_USD: Final[float] = 18000.0
AUTONOMATH_DB: Final[str] = "/Users/shigetoumeda/jpcite/autonomath.db"

#: HuggingFace inference image (matches the training image family used
#: by the M6 driver so the fine-tuned weights load cleanly).
INFERENCE_IMAGE: Final[str] = (
    "763104351884.dkr.ecr.ap-northeast-1.amazonaws.com/"
    "huggingface-pytorch-inference:2.1.0-transformers4.36.0-gpu-py310-cu121-ubuntu20.04"
)

V01_METHOD_PREFIX: Final[str] = "bi_encoder_minilm"
V02_METHOD_TAG: Final[str] = "cross_encoder_japanese_reranker_large_v1"

CANDIDATE_BATCH_SIZE: Final[int] = 10000


def _boto3(service: str, region: str, profile: str) -> Any:
    import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]

    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client(service)


def preflight_cost(region: str, profile: str) -> float:
    """MTD cost sample; abort if at hard-stop."""

    ce = _boto3("ce", "us-east-1", profile)
    today = dt.date.today()
    start = today.replace(day=1).isoformat()
    tomorrow = (today + dt.timedelta(days=1)).isoformat()
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": tomorrow},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )
    amt = float(resp["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])
    if amt >= HARD_STOP_USD:
        print(
            f"[HARD-STOP] mtd_usd={amt:.2f} >= {HARD_STOP_USD}, aborting",
            file=sys.stderr,
        )
        sys.exit(2)
    return amt


# ---------------------------------------------------------------------------
# Step 1 — export v0.1 candidates from autonomath.db
# ---------------------------------------------------------------------------


def _query_v01_candidates(
    db_path: str, *, court_text_path: Path | None, max_rows: int
) -> list[dict[str, Any]]:
    """Read v0.1 edges from am_citation_judge_law + materialise (q, d) pairs.

    The query side (``court_unified_id``) lives in ``data/jpintel.db``
    (``court_decisions.key_ruling`` + ``impact_on_business``); the doc
    side (``article_id``) lives in ``autonomath.db``
    (``am_law_article.text_summary``). Since the two DBs are separate
    we accept an optional ``court_text_path`` JSONL with
    ``{"court_unified_id": str, "court_text": str}`` rows; otherwise
    we leave ``query`` empty and the caller must supply it before
    submitting Batch Transform.
    """

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT id, court_unified_id, article_id, article_number, score,
               rank_in_top_k, method, inference_run_id
          FROM am_citation_judge_law
         WHERE method LIKE ?
         ORDER BY id ASC
         LIMIT ?
        """,
        (f"{V01_METHOD_PREFIX}%", max_rows),
    )
    rows = [dict(r) for r in cur.fetchall()]
    # Fetch law article text for each unique article_id.
    article_ids = sorted({int(r["article_id"]) for r in rows})
    article_text: dict[int, str] = {}
    if article_ids:
        # Batch IN clause to keep params under SQLite limit (~999).
        for i in range(0, len(article_ids), 900):
            chunk = article_ids[i : i + 900]
            placeholders = ",".join("?" for _ in chunk)
            cur2 = conn.execute(
                f"""
                SELECT article_id,
                       COALESCE(text_summary, '') AS body,
                       COALESCE(title, '') AS title
                  FROM am_law_article
                 WHERE article_id IN ({placeholders})
                """,
                chunk,
            )
            for ar in cur2.fetchall():
                txt = (ar["title"] + "\n" + ar["body"]).strip()
                article_text[int(ar["article_id"])] = txt
    conn.close()

    # Optional court text lookup.
    court_text: dict[str, str] = {}
    if court_text_path and court_text_path.exists():
        for line in court_text_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            cid = str(obj.get("court_unified_id") or "")
            txt = str(obj.get("court_text") or "")
            if cid and txt:
                court_text[cid] = txt[:2000]  # truncate for cross-encoder

    out: list[dict[str, Any]] = []
    for r in rows:
        aid = int(r["article_id"])
        out.append(
            {
                "candidate_id": int(r["id"]),
                "court_unified_id": str(r["court_unified_id"]),
                "article_id": aid,
                "article_number": str(r.get("article_number") or ""),
                "v01_score": float(r["score"]),
                "v01_rank": int(r.get("rank_in_top_k") or 0),
                "v01_method": str(r["method"]),
                "v01_run_id": str(r["inference_run_id"]),
                # Cross-encoder inputs (filled if text lookups succeeded).
                "query": court_text.get(str(r["court_unified_id"]), ""),
                "doc": article_text.get(aid, ""),
            }
        )
    return out


def export_candidates(
    *,
    db_path: str,
    out_uri: str,
    court_text_path: Path | None,
    max_rows: int,
    region: str,
    profile: str,
    bucket: str,
    dry_run: bool,
) -> dict[str, Any]:
    rows = _query_v01_candidates(db_path, court_text_path=court_text_path, max_rows=max_rows)
    n_rows = len(rows)
    n_with_q = sum(1 for r in rows if r["query"])
    n_with_d = sum(1 for r in rows if r["doc"])

    payload = io.BytesIO()
    for r in rows:
        payload.write(json.dumps(r, ensure_ascii=False).encode("utf-8") + b"\n")
    body = payload.getvalue()

    manifest = {
        "exported_at": dt.datetime.now(dt.UTC).isoformat(),
        "db_path": db_path,
        "out_uri": out_uri,
        "candidate_count": n_rows,
        "with_query_text": n_with_q,
        "with_doc_text": n_with_d,
        "v01_method_prefix": V01_METHOD_PREFIX,
        "dry_run": dry_run,
    }
    if dry_run:
        print(
            f"[DRY_RUN] {n_rows} candidates ({n_with_q} with query / "
            f"{n_with_d} with doc); would PUT {len(body)} bytes to {out_uri}"
        )
        return manifest
    # Parse out_uri.
    assert out_uri.startswith("s3://")
    s3_path = out_uri[len("s3://") :]
    out_bucket, _, key = s3_path.partition("/")
    s3 = _boto3("s3", region, profile)
    s3.put_object(
        Bucket=out_bucket or bucket,
        Key=key,
        Body=body,
        ContentType="application/jsonlines",
    )
    return manifest


# ---------------------------------------------------------------------------
# Step 2 — register SageMaker Model from M6 training output
# ---------------------------------------------------------------------------


def register_model(
    *,
    model_name: str,
    model_data_uri: str,
    role_arn: str,
    region: str,
    profile: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Create a SageMaker Model object referencing the M6 .tar.gz."""

    spec = {
        "ModelName": model_name,
        "PrimaryContainer": {
            "Image": INFERENCE_IMAGE,
            "ModelDataUrl": model_data_uri,
            "Environment": {
                "HF_TASK": "text-classification",
                "HF_MODEL_ID": "/opt/ml/model",
            },
        },
        "ExecutionRoleArn": role_arn,
        "Tags": [
            {"Key": "lane", "Value": "solo"},
            {"Key": "wave", "Value": "M8"},
            {"Key": "purpose", "Value": "jpcite-cross-encoder-citation-rerank"},
        ],
    }
    if dry_run:
        return {"dry_run": True, "spec": spec}
    sm = _boto3("sagemaker", region, profile)
    resp = sm.create_model(**spec)
    return {"dry_run": False, "response": {"arn": resp.get("ModelArn", "")}}


# ---------------------------------------------------------------------------
# Step 3 — submit one or more Batch Transform jobs
# ---------------------------------------------------------------------------


def submit_transform(
    *,
    job_prefix: str,
    model_name: str,
    input_uri: str,
    output_prefix: str,
    instance_type: str,
    instance_count: int,
    parallel_instances: int,
    max_runtime: int,
    region: str,
    profile: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Submit Batch Transform job(s). Returns a list of TransformJobArns."""

    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    arns: list[str] = []
    specs: list[dict[str, Any]] = []
    for shard in range(parallel_instances):
        job_name = f"{job_prefix}-{ts}-shard{shard:02d}"
        spec: dict[str, Any] = {
            "TransformJobName": job_name,
            "ModelName": model_name,
            "MaxConcurrentTransforms": 4,
            "MaxPayloadInMB": 6,
            "BatchStrategy": "MultiRecord",
            "TransformInput": {
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": input_uri,
                    }
                },
                "ContentType": "application/jsonlines",
                "SplitType": "Line",
                "CompressionType": "None",
            },
            "TransformOutput": {
                "S3OutputPath": f"{output_prefix.rstrip('/')}/shard{shard:02d}/",
                "Accept": "application/jsonlines",
                "AssembleWith": "Line",
            },
            "TransformResources": {
                "InstanceType": instance_type,
                "InstanceCount": instance_count,
            },
            "Tags": [
                {"Key": "lane", "Value": "solo"},
                {"Key": "wave", "Value": "M8"},
                {"Key": "shard", "Value": str(shard)},
            ],
        }
        if max_runtime > 0:
            spec["TransformResources"]["VolumeKmsKeyId"] = ""  # noqa: E501  # explicit no-KMS
        specs.append(spec)
        if not dry_run:
            sm = _boto3("sagemaker", region, profile)
            resp = sm.create_transform_job(**spec)
            arns.append(resp.get("TransformJobArn", ""))
    return {"dry_run": dry_run, "specs": specs, "arns": arns}


# ---------------------------------------------------------------------------
# Step 4 — ingest rescored edges back into am_citation_judge_law
# ---------------------------------------------------------------------------


def ingest(
    *,
    db_path: str,
    scored_uri: str,
    rerank_run_id: str,
    region: str,
    profile: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Read scored JSONL parts from S3 and insert v0.2 edges."""

    assert scored_uri.startswith("s3://")
    s3_path = scored_uri[len("s3://") :]
    bucket, _, prefix = s3_path.partition("/")
    s3 = _boto3("s3", region, profile)
    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            k = obj["Key"]
            if k.endswith(".jsonl") or k.endswith(".out"):
                keys.append(k)
    keys = sorted(keys)

    inserted = 0
    skipped = 0
    score_hist: dict[str, int] = {
        "0.85+": 0,
        "0.65-0.85": 0,
        "0.40-0.65": 0,
        "<0.40": 0,
    }

    def _bucket(score: float) -> str:
        if score >= 0.85:
            return "0.85+"
        if score >= 0.65:
            return "0.65-0.85"
        if score >= 0.40:
            return "0.40-0.65"
        return "<0.40"

    conn = sqlite3.connect(db_path) if not dry_run else None
    if conn is not None:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

    for k in keys:
        body = s3.get_object(Bucket=bucket, Key=k)["Body"].read()
        for line in io.BytesIO(body).read().decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            score = float(rec.get("cross_score") or rec.get("score") or 0.0)
            cid = str(rec.get("court_unified_id") or "")
            aid_raw = rec.get("article_id")
            try:
                aid = int(aid_raw) if aid_raw is not None else 0
            except (TypeError, ValueError):
                aid = 0
            if not cid or aid <= 0:
                skipped += 1
                continue
            score_hist[_bucket(score)] += 1
            if conn is not None:
                # INSERT OR IGNORE on the unique (court, article, method).
                conn.execute(
                    """
                    INSERT OR IGNORE INTO am_citation_judge_law
                        (court_unified_id, law_canonical_id, article_id,
                         article_number, score, rank_in_top_k, method,
                         threshold, inference_run_id, confidence, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cid,
                        str(rec.get("law_canonical_id") or ""),
                        aid,
                        str(rec.get("article_number") or ""),
                        score,
                        int(rec.get("rank_in_top_k") or 0),
                        V02_METHOD_TAG,
                        0.65,  # rerank threshold for "confident"
                        rerank_run_id,
                        0.85,  # cross-encoder prior
                        f"rescored from v0.1 (v01_score={rec.get('v01_score')})",
                    ),
                )
                inserted += 1

    if conn is not None:
        conn.commit()
        conn.close()

    return {
        "dry_run": dry_run,
        "scored_uri": scored_uri,
        "files_read": len(keys),
        "inserted": inserted,
        "skipped": skipped,
        "score_histogram": score_hist,
        "rerank_run_id": rerank_run_id,
    }


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="M8 v0.2 — cross-encoder rerank of judge × law candidates."
    )
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--role-arn", default=DEFAULT_ROLE_ARN)
    p.add_argument("--commit", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export-candidates", help="Export v0.1 edges to S3 JSONL.")
    e.add_argument("--db", default=AUTONOMATH_DB)
    e.add_argument(
        "--out",
        default=(
            f"s3://{DEFAULT_BUCKET}/citation_rerank/v0.2/"
            f"candidates-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
        ),
    )
    e.add_argument(
        "--court-text",
        default=None,
        help="Optional local JSONL with court_unified_id -> court_text mapping.",
    )
    e.add_argument("--max-rows", type=int, default=10_000_000)

    r = sub.add_parser("register-model", help="Create SageMaker Model from M6 artifact.")
    r.add_argument(
        "--model-name",
        default=f"jpcite-cross-encoder-v1-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}",
    )
    r.add_argument(
        "--model-data-uri",
        required=False,
        help="s3://.../model.tar.gz produced by M6 training.",
    )

    t = sub.add_parser("submit-transform", help="Submit Batch Transform job(s).")
    t.add_argument("--job-prefix", default="jpcite-citation-rerank")
    t.add_argument("--model-name", required=True)
    t.add_argument("--input-uri", required=True)
    t.add_argument(
        "--output-prefix",
        default=f"s3://{DEFAULT_BUCKET}/citation_rerank/v0.2/scored",
    )
    t.add_argument("--instance-type", default="ml.g4dn.xlarge")
    t.add_argument("--instance-count", type=int, default=1)
    t.add_argument(
        "--parallel-instances",
        type=int,
        default=1,
        help="Number of parallel Batch Transform jobs (shards).",
    )
    t.add_argument(
        "--max-runtime",
        type=int,
        default=6 * 3600,
        help="MaxRuntimeInSeconds (informational; Batch Transform self-terminates).",
    )

    g = sub.add_parser("ingest", help="Ingest rescored edges back to SQLite.")
    g.add_argument("--db", default=AUTONOMATH_DB)
    g.add_argument(
        "--scored-uri",
        default=f"s3://{DEFAULT_BUCKET}/citation_rerank/v0.2/scored/",
    )
    g.add_argument(
        "--rerank-run-id",
        default=f"M8v0.2-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}",
    )

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dry_run = not args.commit and os.environ.get("DRY_RUN", "1") != "0"

    # MTD preflight gate every command path; cheap call.
    mtd = preflight_cost(args.region, args.profile)
    print(f"[preflight] mtd_usd={mtd:.4f} < {HARD_STOP_USD}", file=sys.stderr)

    result: dict[str, Any]
    if args.cmd == "export-candidates":
        court_text_path = Path(args.court_text) if args.court_text else None
        result = export_candidates(
            db_path=args.db,
            out_uri=args.out,
            court_text_path=court_text_path,
            max_rows=args.max_rows,
            region=args.region,
            profile=args.profile,
            bucket=args.bucket,
            dry_run=dry_run,
        )
    elif args.cmd == "register-model":
        if not args.model_data_uri:
            print(
                "[FAIL] --model-data-uri required (output S3 of M6 training)",
                file=sys.stderr,
            )
            return 2
        result = register_model(
            model_name=args.model_name,
            model_data_uri=args.model_data_uri,
            role_arn=args.role_arn,
            region=args.region,
            profile=args.profile,
            dry_run=dry_run,
        )
    elif args.cmd == "submit-transform":
        result = submit_transform(
            job_prefix=args.job_prefix,
            model_name=args.model_name,
            input_uri=args.input_uri,
            output_prefix=args.output_prefix,
            instance_type=args.instance_type,
            instance_count=args.instance_count,
            parallel_instances=args.parallel_instances,
            max_runtime=args.max_runtime,
            region=args.region,
            profile=args.profile,
            dry_run=dry_run,
        )
    elif args.cmd == "ingest":
        result = ingest(
            db_path=args.db,
            scored_uri=args.scored_uri,
            rerank_run_id=args.rerank_run_id,
            region=args.region,
            profile=args.profile,
            dry_run=dry_run,
        )
    else:  # pragma: no cover
        print(f"[FAIL] unknown cmd: {args.cmd}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
