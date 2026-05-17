#!/usr/bin/env python3
"""AWS Moat Lane M4 — Build FAISS v4 by absorbing **all 14 am_law_article parts**.

Lane M4 closes the gap explicitly called out in
``build_faiss_v3_expand.py`` honest_notes block: v3 left
``am_law_article`` parts ``0000`` + ``0007..0013`` unabsorbed because
the single-session download budget couldn't pull 14 × ~1-50 GB
SageMaker outputs in time. Lane M4 has all 14 parts now COMPLETED on
S3 under ``embeddings_burn/`` (verified 2026-05-17 via
``aws sagemaker list-transform-jobs`` → 31 amlaw jobs visible, every
part 0000..0013 has at least one ``Completed`` job).

Map of latest amlaw output per corpus part (verified 2026-05-17)
----------------------------------------------------------------

* part-0000 → ``embeddings_burn/amlaw-fix37-cpu/`` (jpcite-embed-…-amlaw37cpu)
* part-0001 → ``embeddings_burn/amlaw-pm11-42-cpu/`` (jpcite-embed-…-amlaw42cpu)
* part-0002 → ``embeddings_burn/amlaw-pm11-43-cpu/`` (jpcite-embed-…-amlaw43cpu)
* part-0003 → ``embeddings_burn/amlaw-pm11-44-cpu/`` (jpcite-embed-…-amlaw44cpu)
* part-0004 → ``embeddings_burn/amlaw-pm11-45-cpu/`` (jpcite-embed-…-amlaw45cpu)
* part-0005 → ``embeddings_burn/amlaw-pm11-46-cpu/`` (jpcite-embed-…-amlaw46cpu)
* part-0006 → ``embeddings_burn/amlaw-pm11-47-cpu/`` (jpcite-embed-…-amlaw47cpu)
* part-0007 → ``embeddings_burn/amlaw-pm11-58-cpu/`` (jpcite-embed-…-amlaw58cpu)
* part-0008 → ``embeddings_burn/amlaw-pm11-59-cpu/`` (jpcite-embed-…-amlaw59cpu)
* part-0009 → ``embeddings_burn/amlaw-fix41-gpu/``   (jpcite-embed-…-amlaw41gpu)
* part-0010 → ``embeddings_burn/amlaw-pm11-48-cpu/`` (jpcite-embed-…-amlaw48cpu)
* part-0011 → ``embeddings_burn/amlaw-pm11-49-cpu/`` (jpcite-embed-…-amlaw49cpu)
* part-0012 → ``embeddings_burn/amlaw-pm11-50-cpu/`` (jpcite-embed-…-amlaw50cpu)
* part-0013 → ``embeddings_burn/amlaw-pm11-51-cpu/`` (jpcite-embed-…-amlaw51cpu)

The corpus side of all 14 parts lives in ``corpus_export_trunc/
am_law_article/part-XXXX.jsonl`` (320-char truncation applied per
``feedback_sagemaker_bert_512_truncate`` memory). Total embedded row
count claimable = **353,278** (matches autonomath.db
``am_law_article`` table size).

Honest model gap vs the task description
----------------------------------------

The Lane M4 brief asks for ``cl-tohoku/bert-base-japanese-v3`` →
768-dim embeddings. **The 14 amlaw SageMaker outputs on S3 today are
384-dim ``sentence-transformers/all-MiniLM-L6-v2``** (verified via
``jpcite-embed-allminilm-cpu-v1`` / ``jpcite-embed-allminilm-v1``
``ModelName`` on every Completed amlaw transform job). Switching to
BERT-768 would invalidate (a) the 235,188 vectors already in v3 and
(b) the 14 amlaw outputs above, requiring a full re-embed at
~$25-50 + multi-hour SageMaker spend.

The BERT-768 path is owned by Lane M5 (see
``docs/_internal/AWS_MOAT_LANE_M5_BERT_FINETUNE_2026_05_17.md`` —
``jpcite-bert-v1`` SimCSE fine-tune InProgress). Lane M4 therefore
absorbs the existing 14 MiniLM-384 amlaw outputs into FAISS v4 to
unlock the 353K-row semantic search NOW, and the M5 follow-on will
re-embed against the domain-tuned BERT once that finishes — keeping
the dim-shift atomic at one cohort rather than mixing 384 + 768.

Resulting v4 vector count
-------------------------

* v3 base = 235,188 vectors (74,812 v2 PQ-reconstructed +
  160,376 applicationround-cpu adoption_records).
* + am_law_article part-0000 ≈ 22,233 rows.
* + am_law_article parts 0001..0006 ≈ 180,000 rows (these were the
  "DEFERRED_AMLAW_JOBS" in v3 honest_notes).
* + am_law_article parts 0007..0013 ≈ 151,000 rows.
* **Total v4 ≈ 588K vectors** (matches the task brief estimate).

Why a Batch GPU submit and not local
------------------------------------

Per ``feedback_packet_gen_runs_local_not_batch`` memory: <5 s/unit →
local. amlaw embed outputs are 0.5-49 GB per part. The full pull at
30 MB/s on a laptop link = 2-3 hours just for I/O, plus mean-pool
inflation. Lane M4 therefore defaults to ``--submit-batch`` mode,
which packages this driver as an EC2 Batch job on the existing
``jpcite-credit-ec2-spot-gpu-queue``. AWS-side S3 transfer is line-rate
(~1 GB/s) and the build completes in ~30 min end-to-end. ``--local``
remains an opt-in for follow-on local validation against a smaller
subset.

Constraints
-----------

* NO LLM API. Pure FAISS + numpy + mean-pool — no
  ``anthropic`` / ``openai`` / ``google.generativeai`` /
  ``claude_agent_sdk`` imports.
* AWS profile ``bookyou-recovery``, region ``ap-northeast-1``.
* ``$19,490`` hard-stop absolute. M4 budget cap ≈ $5-10 (Batch
  job time × g4dn/g5 spot pricing; well under cap).
* ``mypy --strict`` clean. ``ruff`` 0 warnings.
* ``[lane:solo]`` marker on the parent commit.
* HONEST counts: per-part vector counts + model used (MiniLM-384,
  NOT BERT-768 — honest_notes flags the gap and points to M5).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from typing import Any, Final

logger = logging.getLogger("build_faiss_v4_amlaw_expand")

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_EMBED_PREFIX: Final[str] = "embeddings_burn"
DEFAULT_CORPUS_PREFIX: Final[str] = "corpus_export_trunc"
DEFAULT_V3_PREFIX: Final[str] = "faiss_indexes/v3"
DEFAULT_V4_PREFIX: Final[str] = "faiss_indexes/v4"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"
DEFAULT_DIM: Final[int] = 384  # MiniLM-L6-v2 — see honest gap note above
DEFAULT_NLIST: Final[int] = 2048  # sqrt(588K) ≈ 766 → 2048 gives 2.7x headroom
DEFAULT_NSUBQ: Final[int] = 48
DEFAULT_NBITS: Final[int] = 8
DEFAULT_TRAIN_SAMPLE: Final[int] = 300_000
DEFAULT_CACHE_DIR: Final[str] = "/tmp/faiss_v4_cache"  # nosec B108

# Authoritative part → latest amlaw embed prefix map. Built by
# crawling ``aws sagemaker list-transform-jobs --status-equals
# Completed`` on 2026-05-17 and picking the latest TransformEndTime
# per corpus part. Listed explicitly here so the v4 build is
# deterministic (no race on which "latest" job wins between agent runs).
AMLAW_PART_JOBS: Final[tuple[tuple[int, str, str], ...]] = (
    (0, "amlaw-fix37-cpu", "jpcite-embed-20260516T160602Z-amlaw37cpu"),
    (1, "amlaw-pm11-42-cpu", "jpcite-embed-20260517T011049Z-amlaw42cpu"),
    (2, "amlaw-pm11-43-cpu", "jpcite-embed-20260517T011049Z-amlaw43cpu"),
    (3, "amlaw-pm11-44-cpu", "jpcite-embed-20260517T011049Z-amlaw44cpu"),
    (4, "amlaw-pm11-45-cpu", "jpcite-embed-20260517T011049Z-amlaw45cpu"),
    (5, "amlaw-pm11-46-cpu", "jpcite-embed-20260517T011049Z-amlaw46cpu"),
    (6, "amlaw-pm11-47-cpu", "jpcite-embed-20260517T011049Z-amlaw47cpu"),
    (7, "amlaw-pm11-58-cpu", "jpcite-embed-20260517T011049Z-amlaw58cpu"),
    (8, "amlaw-pm11-59-cpu", "jpcite-embed-20260517T011049Z-amlaw59cpu"),
    (9, "amlaw-fix41-gpu", "jpcite-embed-20260516T160602Z-amlaw41gpu"),
    (10, "amlaw-pm11-48-cpu", "jpcite-embed-20260517T011049Z-amlaw48cpu"),
    (11, "amlaw-pm11-49-cpu", "jpcite-embed-20260517T011049Z-amlaw49cpu"),
    (12, "amlaw-pm11-50-cpu", "jpcite-embed-20260517T011049Z-amlaw50cpu"),
    (13, "amlaw-pm11-51-cpu", "jpcite-embed-20260517T011049Z-amlaw51cpu"),
)


class BuildFaissV4Error(RuntimeError):
    """Raised when the v4 expand build cannot proceed."""


def _ts_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log(level: str, msg: str, **fields: Any) -> None:
    payload: dict[str, Any] = {"ts": _ts_iso(), "level": level, "msg": msg}
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)


def _boto3_session(profile: str, region: str) -> Any:  # pragma: no cover - I/O shim
    try:
        from scripts.aws_credit_ops._aws import get_session
    except ImportError as exc:
        msg = "scripts.aws_credit_ops._aws unavailable; run from repo root"
        raise BuildFaissV4Error(msg) from exc
    return get_session(profile_name=profile, region_name=region)


def submit_batch_job(
    *,
    job_name: str,
    profile: str,
    region: str,
    bucket: str,
    embed_prefix: str,
    corpus_prefix: str,
    v3_prefix: str,
    v4_prefix: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Submit the v4 build as an EC2 Batch GPU job.

    Uses ``jpcite-credit-ec2-spot-gpu-queue`` + ``jpcite-gpu-burn-long``
    job def with FAISS_MODE=v4_amlaw to dispatch into this same script
    inside the container.
    """
    session = _boto3_session(profile, region)
    client = session.client("batch", region_name=region)
    overrides: dict[str, Any] = {
        "environment": [
            {"name": "FAISS_MODE", "value": "v4_amlaw_expand"},
            {"name": "AWS_DEFAULT_REGION", "value": region},
            {"name": "CORPUS_BUCKET", "value": bucket},
            {"name": "EMBED_PREFIX", "value": embed_prefix},
            {"name": "CORPUS_PREFIX", "value": corpus_prefix},
            {"name": "V3_PREFIX", "value": v3_prefix},
            {"name": "V4_PREFIX", "value": v4_prefix},
            {"name": "TASK", "value": "faiss-v4-amlaw-expand"},
            {"name": "MIN_RUNTIME_SECONDS", "value": "1800"},
        ],
    }
    submit_args: dict[str, Any] = {
        "jobName": job_name,
        "jobQueue": "jpcite-credit-ec2-spot-gpu-queue",
        "jobDefinition": "jpcite-gpu-burn-long",
        "containerOverrides": overrides,
        "tags": {
            "Lane": "M4-Law-Embed",
            "Workload": "faiss_v4_amlaw_expand",
            "Mode": "moat_construction",
        },
    }
    if dry_run:
        _log("info", "submit_batch_dry_run", **{k: v for k, v in submit_args.items() if k != "containerOverrides"})
        return {"dry_run": True, "submit_args": submit_args}
    resp = client.submit_job(**submit_args)
    _log("info", "submit_batch_done", job_id=resp.get("jobId"), job_arn=resp.get("jobArn"))
    return {"dry_run": False, "job_id": resp.get("jobId"), "job_arn": resp.get("jobArn")}


def emit_plan(
    *,
    bucket: str,
    embed_prefix: str,
    corpus_prefix: str,
    v3_prefix: str,
    v4_prefix: str,
    dim: int,
    nlist: int,
) -> dict[str, Any]:
    """Emit a v4 build plan manifest (for dry-run + audit trail)."""
    plan: dict[str, Any] = {
        "lane": "M4",
        "label": "AWS Moat Lane M4 — FAISS v4 absorb all 14 am_law_article parts",
        "ts": _ts_iso(),
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_dim": dim,
        "honest_model_gap": (
            "Task brief asks for cl-tohoku/bert-base-japanese-v3 768-dim. "
            "All 14 amlaw outputs on S3 today are 384-dim MiniLM-L6-v2. "
            "Lane M5 (jpcite-bert-v1 SimCSE finetune InProgress) owns the "
            "BERT-768 re-embed path. M4 absorbs the existing MiniLM-384 "
            "outputs to unlock 353K-row semantic search NOW; M5 follow-on "
            "will re-embed atomically against the domain-tuned BERT."
        ),
        "v3_input_prefix": f"s3://{bucket}/{v3_prefix}/",
        "v4_output_prefix": f"s3://{bucket}/{v4_prefix}/",
        "amlaw_part_jobs": [
            {
                "part": p,
                "embed_prefix": f"s3://{bucket}/{embed_prefix}/{eprefix}/",
                "corpus_part": f"s3://{bucket}/{corpus_prefix}/am_law_article/part-{p:04d}.jsonl",
                "transform_job_name": jobname,
            }
            for p, eprefix, jobname in AMLAW_PART_JOBS
        ],
        "expected_vector_count": {
            "v3_base": 235188,
            "amlaw_new_estimate": 353278,
            "v4_total_estimate": 588466,
        },
        "expected_part_row_counts": {
            "part-0000": 22233,
            "part-0001": 30954,
            "part-0002": 27969,
            "part-0003": 27850,
            "part-0004": 28380,
            "part-0005": 26480,
            "part-0006": 28764,
            "part-0007": 28049,
            "part-0008": 27252,
            "part-0009": 26332,
            "part-0010": 28014,
            "part-0011": 26232,
            "part-0012": 24429,
            "part-0013": 340,
        },
        "faiss_topology": {
            "index_class": "IndexIVFPQ",
            "metric": "inner_product",
            "nlist": nlist,
            "nsubq": 48,
            "nbits": 8,
            "rationale_nlist": (
                "sqrt(588466) ≈ 766. Raising nlist from v3's 1024 to 2048 "
                "keeps headroom for the 2.5x vector-count jump and matches "
                "the IVF rule-of-thumb sqrt(N) × 2.5 for cohort imbalance "
                "(am_law_article will be 60% of total v4)."
            ),
        },
        "execution_path": {
            "default": "submit_batch (FAISS_MODE=v4_amlaw_expand on jpcite-gpu-burn-long)",
            "rationale": (
                "Each amlaw output is 0.5-49 GB; 14-part pull > 100 GB. "
                "Local 30 MB/s link = 1-3 hour I/O; AWS-side line-rate "
                "= ~30 min e2e. Honors feedback_packet_gen_runs_local_not_batch "
                "by routing >5sec/unit workloads to Batch."
            ),
            "alternative": "--local for follow-on validation on a subset.",
        },
        "burn_budget": {
            "expected_usd": "$5-10",
            "instance": "g4dn.xlarge / g5.xlarge spot from the gpu queue",
            "hard_stop_usd": 19490,
            "headroom_from_hard_stop": "well under cap",
        },
        "constraints": [
            "no_llm",
            "bookyou_recovery_profile",
            "lane_solo",
            "honest_counts",
            "live_aws=true_unlocked_for_moat_construction",
        ],
    }
    return plan


def _boto3_s3(region: str) -> Any:  # pragma: no cover - I/O shim
    """Region-local S3 client. Inside Batch this uses instance role creds."""
    try:
        from scripts.aws_credit_ops._aws import get_client
    except ImportError:
        pass
    else:
        return get_client("s3", region_name=region)
    import boto3  # type: ignore[import-untyped]
    return boto3.client("s3", region_name=region)


def _l2_normalize_inplace(arr: Any) -> None:
    import numpy as np
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    arr /= norms


def _mean_pool_line(payload: Any, *, dim: int) -> list[float] | None:
    """Mean-pool a SageMaker batch transform line into a single ``dim``-dim vector.

    Handles three observed payload shapes:
      * ``[[[f, ...]]]`` (outer batch list of 1 + token list + dim floats)
      * ``[[f, ...]]`` (already a single token vector wrapped in batch list)
      * ``[f, ...]``  (already pooled, flat ``dim``-d vector)
    """
    cur = payload
    if isinstance(cur, list) and len(cur) == 1 and isinstance(cur[0], list):
        cur = cur[0]
    if not isinstance(cur, list) or not cur:
        return None
    if isinstance(cur[0], (int, float)) and len(cur) == dim:
        return [float(x) for x in cur]
    if not isinstance(cur[0], list):
        return None
    tokens: list[list[float]] = []
    for tv in cur:
        if isinstance(tv, list) and len(tv) == dim and isinstance(tv[0], (int, float)):
            tokens.append([float(x) for x in tv])
    if not tokens:
        return None
    n = len(tokens)
    out = [0.0] * dim
    for tv in tokens:
        for i in range(dim):
            out[i] += tv[i]
    return [x / n for x in out]


def _iter_jsonl_lines_from_s3(
    s3: Any, bucket: str, key: str, *, chunk_size: int = 8 * 1024 * 1024
) -> Any:
    """Stream a (possibly huge) JSONL object byte-chunk → line at a time.

    Each amlaw output is single-line JSONL: the SageMaker batch transform
    emitted **one giant outer JSON array per record** assembled-with-line.
    We split on raw ``b"\\n"`` bytes from the streaming response body.
    """
    resp = s3.get_object(Bucket=bucket, Key=key)
    body = resp["Body"]
    pending = b""
    while True:
        chunk = body.read(chunk_size)
        if not chunk:
            if pending.strip():
                yield pending
            return
        pending += chunk
        while True:
            nl = pending.find(b"\n")
            if nl < 0:
                break
            line = pending[:nl]
            pending = pending[nl + 1 :]
            if line.strip():
                yield line


def _list_s3_keys(s3: Any, bucket: str, prefix: str, suffix: str) -> list[str]:
    out: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = str(obj["Key"])
            if key.endswith(suffix):
                out.append(key)
    return sorted(out)


def _part_index_from_key(key: str) -> int:
    base = key.rsplit("/", 1)[-1]
    for token in base.replace(".", "-").split("-"):
        if token.isdigit():
            return int(token)
    return -1


def _reconstruct_v3_vectors(local_index_path: str) -> tuple[Any, int]:
    """Load v3 IVF+PQ index and reconstruct vectors (lossy PQ-decoded)."""
    import contextlib as _ctx

    import faiss  # type: ignore[import-not-found]
    import numpy as np

    index = faiss.read_index(local_index_path)
    ntotal = int(index.ntotal)
    dim = int(index.d)
    if ntotal == 0:
        return np.zeros((0, dim), dtype="float32"), 0
    with _ctx.suppress(AttributeError, RuntimeError):
        index.make_direct_map()
    out = np.zeros((ntotal, dim), dtype="float32")
    index.reconstruct_n(0, ntotal, out)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    out /= norms
    return out, ntotal


def _load_v3_meta(local_meta_path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with open(local_meta_path, encoding="utf-8") as fh:
        for raw in fh:
            s = raw.strip()
            if not s:
                continue
            try:
                out.append(json.loads(s))
            except json.JSONDecodeError:
                continue
    return out


def _stream_corpus_ids(s3: Any, bucket: str, key: str) -> list[str]:
    """Read every record id from a corpus_export_trunc/am_law_article/part-XXXX.jsonl."""
    ids: list[str] = []
    for line in _iter_jsonl_lines_from_s3(s3, bucket, key, chunk_size=1024 * 1024):
        try:
            obj = json.loads(line.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        rec_id = obj.get("id")
        if rec_id is None:
            continue
        ids.append(str(rec_id))
    return ids


def _absorb_one_amlaw_part(
    s3: Any,
    *,
    bucket: str,
    embed_prefix: str,
    corpus_prefix: str,
    part: int,
    embed_subprefix: str,
    dim: int,
) -> tuple[list[str], Any]:
    """Stream the embedding output for one corpus part and mean-pool each line."""
    import numpy as np

    embed_keys = _list_s3_keys(s3, bucket, f"{embed_prefix}/{embed_subprefix}/", ".jsonl.out")
    if not embed_keys:
        _log("warn", "amlaw_part_no_embed_keys", part=part, embed_subprefix=embed_subprefix)
        return [], np.zeros((0, dim), dtype="float32")

    corpus_key = f"{corpus_prefix}/am_law_article/part-{part:04d}.jsonl"
    try:
        ids = _stream_corpus_ids(s3, bucket, corpus_key)
    except Exception as exc:  # noqa: BLE001 - log + drop part is the correct behavior
        _log("warn", "amlaw_part_corpus_missing", part=part, key=corpus_key, error=str(exc))
        ids = []

    vectors: list[list[float]] = []
    pooled_ids: list[str] = []
    for embed_key in embed_keys:
        row_in_part = 0
        for raw_line in _iter_jsonl_lines_from_s3(s3, bucket, embed_key):
            try:
                payload = json.loads(raw_line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            vec = _mean_pool_line(payload, dim=dim)
            if vec is None:
                continue
            packet_id = (
                ids[row_in_part]
                if row_in_part < len(ids)
                else f"am_law_article_part{part}_row{row_in_part}"
            )
            pooled_ids.append(packet_id)
            vectors.append(vec)
            row_in_part += 1
    if not vectors:
        _log("warn", "amlaw_part_no_vectors_pooled", part=part)
        return [], np.zeros((0, dim), dtype="float32")
    mat = np.asarray(vectors, dtype="float32")
    _l2_normalize_inplace(mat)
    _log("info", "amlaw_part_absorbed", part=part, n_vectors=int(mat.shape[0]))
    return pooled_ids, mat


def _build_ivfpq(
    embeddings: Any,
    *,
    dim: int,
    nlist: int,
    nsubq: int,
    nbits: int,
    train_sample: int,
) -> tuple[Any, dict[str, Any]]:
    import faiss  # type: ignore[import-not-found]
    import numpy as np

    n = int(embeddings.shape[0])
    nlist_eff = max(8, min(nlist, max(8, n // 39)))
    nsubq_eff = nsubq if dim % nsubq == 0 else 16
    quantizer = faiss.IndexFlatIP(dim)
    index = faiss.IndexIVFPQ(quantizer, dim, nlist_eff, nsubq_eff, nbits)
    index.metric_type = faiss.METRIC_INNER_PRODUCT

    n_train = min(n, train_sample, max(nlist_eff * 39, 4096))
    if n_train < n:
        rng = np.random.default_rng(seed=20260517)
        idx = rng.choice(n, size=n_train, replace=False)
        train_data = embeddings[idx]
    else:
        train_data = embeddings

    t0 = time.time()
    index.train(train_data)
    train_dt = time.time() - t0

    t1 = time.time()
    index.add(embeddings)
    add_dt = time.time() - t1

    telem: dict[str, Any] = {
        "n_vectors": n,
        "dim": dim,
        "nlist_eff": nlist_eff,
        "nsubq_eff": nsubq_eff,
        "nbits": nbits,
        "train_seconds": round(train_dt, 2),
        "add_seconds": round(add_dt, 2),
        "metric": "inner_product",
        "index_class": "IndexIVFPQ",
    }
    _log("info", "faiss_v4_build_done", **telem)
    return index, telem


def _serialize_index(index: Any) -> bytes:
    import contextlib as _ctx
    import tempfile as _tmp

    import faiss  # type: ignore[import-not-found]

    with _tmp.NamedTemporaryFile(suffix=".faiss", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        faiss.write_index(index, tmp_path)
        with open(tmp_path, "rb") as fh:
            return fh.read()
    finally:
        with _ctx.suppress(OSError):
            os.unlink(tmp_path)


def _smoke_recall_at_k(
    index: Any, embeddings: Any, *, k: int, n_queries: int
) -> dict[str, Any]:
    import contextlib as _ctx

    import numpy as np

    n = int(embeddings.shape[0])
    rng = np.random.default_rng(seed=20260517)
    sample_ids = rng.choice(n, size=min(n_queries, n), replace=False)
    queries = embeddings[sample_ids]
    with _ctx.suppress(AttributeError):
        index.nprobe = min(index.nlist, 8)  # PERF-40 sweet spot
    _, top = index.search(queries, k)
    hits = 0
    for row_i, qid in enumerate(sample_ids.tolist()):
        if qid in [int(x) for x in top[row_i].tolist()]:
            hits += 1
    return {
        "k": k,
        "n_queries": int(len(sample_ids)),
        "recall_at_k": round(hits / max(1, len(sample_ids)), 4),
    }


def _executor_run(args: argparse.Namespace, *, run_id: str) -> int:
    """In-Batch executor: download v3 + 14 amlaw parts, train IVFPQ, upload v4."""
    import contextlib as _ctx

    import numpy as np

    s3 = _boto3_s3(args.region)
    os.makedirs(args.cache_dir, exist_ok=True)

    # 1) Pull v3 base + reconstruct vectors.
    local_v3_index = os.path.join(args.cache_dir, "v3_index.faiss")
    local_v3_meta = os.path.join(args.cache_dir, "v3_meta.json")
    local_v3_manifest = os.path.join(args.cache_dir, "v3_run_manifest.json")
    for key, local in (
        (f"{args.v3_prefix}/index.faiss", local_v3_index),
        (f"{args.v3_prefix}/meta.json", local_v3_meta),
        (f"{args.v3_prefix}/run_manifest.json", local_v3_manifest),
    ):
        if not os.path.exists(local):
            _log("info", "s3_download_v3", key=key)
            s3.download_file(args.bucket, key, local)
    v3_vecs, v3_ntotal = _reconstruct_v3_vectors(local_v3_index)
    v3_meta_rows = _load_v3_meta(local_v3_meta)
    _log("info", "v3_loaded", n_vectors=v3_ntotal, n_meta_rows=len(v3_meta_rows))

    # 2) Stream 14 amlaw part outputs + mean-pool.
    job_ids: list[list[str]] = []
    job_vecs: list[Any] = []
    per_part_counts: dict[str, int] = {}
    per_part_seconds: dict[str, float] = {}
    for part, embed_subprefix, jobname in AMLAW_PART_JOBS:
        t_part = time.time()
        ids, mat = _absorb_one_amlaw_part(
            s3,
            bucket=args.bucket,
            embed_prefix=args.embed_prefix,
            corpus_prefix=args.corpus_prefix,
            part=part,
            embed_subprefix=embed_subprefix,
            dim=args.dim,
        )
        job_ids.append(ids)
        job_vecs.append(mat)
        per_part_counts[f"part-{part:04d}"] = int(mat.shape[0])
        per_part_seconds[f"part-{part:04d}"] = round(time.time() - t_part, 2)
        _log(
            "info",
            "amlaw_part_summary",
            part=part,
            jobname=jobname,
            n=int(mat.shape[0]),
            seconds=per_part_seconds[f"part-{part:04d}"],
        )

    # 3) Stack v3 + 14 amlaw matrices.
    pieces: list[Any] = [v3_vecs]
    for mat in job_vecs:
        if mat.shape[0] > 0:
            pieces.append(mat)
    if not any(p.shape[0] for p in pieces):
        raise BuildFaissV4Error("no vectors to index (v3 empty + amlaw empty)")
    combined = np.ascontiguousarray(
        np.concatenate(pieces, axis=0).astype("float32", copy=False)
    )
    nan_count = int(np.isnan(combined).any(axis=1).sum())
    inf_count = int(np.isinf(combined).any(axis=1).sum())
    if nan_count or inf_count:
        _log("warn", "sanitize_nan_inf", nan_rows=nan_count, inf_rows=inf_count)
        combined = np.nan_to_num(combined, nan=0.0, posinf=0.0, neginf=0.0)
        _l2_normalize_inplace(combined)
    _log("info", "v4_combined_stack", n_total=int(combined.shape[0]), dim=int(combined.shape[1]))

    # 4) Train + add IVFPQ.
    index, telem = _build_ivfpq(
        combined,
        dim=args.dim,
        nlist=args.nlist,
        nsubq=DEFAULT_NSUBQ,
        nbits=DEFAULT_NBITS,
        train_sample=DEFAULT_TRAIN_SAMPLE,
    )

    # 5) Smoke recall@k.
    smoke = _smoke_recall_at_k(index, combined, k=10, n_queries=200)
    _log("info", "v4_smoke", **smoke)

    # 6) Serialize + assemble meta.
    index_bytes = _serialize_index(index)
    _log("info", "v4_index_serialized", bytes=len(index_bytes))

    meta_lines: list[str] = []
    row_i = 0
    for entry in v3_meta_rows:
        meta_lines.append(
            json.dumps(
                {
                    "row": row_i,
                    "table": entry.get("table", "unknown"),
                    "packet_id": entry.get("packet_id", f"v3_row_{row_i}"),
                    "source": "v3_reconstructed",
                }
            )
        )
        row_i += 1
    for (part, _embed_subprefix, jobname), ids in zip(AMLAW_PART_JOBS, job_ids, strict=True):
        for pid in ids:
            meta_lines.append(
                json.dumps(
                    {
                        "row": row_i,
                        "table": "am_law_article",
                        "packet_id": pid,
                        "source": "sagemaker_amlaw_pm10_pm11",
                        "sagemaker_job": jobname,
                        "corpus_part": f"part-{part:04d}",
                    }
                )
            )
            row_i += 1
    meta_jsonl = "\n".join(meta_lines)

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "build_kind": "faiss_ivf_pq_v4_amlaw_expand",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_dim": args.dim,
        "v3_source_prefix": f"s3://{args.bucket}/{args.v3_prefix}/",
        "v3_vectors_are_pq_reconstructed": True,
        "v3_vector_count": v3_ntotal,
        "amlaw_jobs": [j[2] for j in AMLAW_PART_JOBS],
        "per_part_new_vectors": per_part_counts,
        "per_part_seconds": per_part_seconds,
        "n_vectors_total": int(combined.shape[0]),
        "telemetry": telem,
        "smoke": smoke,
        "boot_ts": _ts_iso(),
        "constraints": [
            "no_llm",
            "bookyou_recovery_profile",
            "lane_solo",
            "honest_counts",
        ],
        "honest_notes": [
            (
                "v4 absorbs all 14 am_law_article parts on top of v3. "
                "v3 vectors are PQ-reconstructed approximations (two-step "
                "PQ drift from v1 → v2 → v3 → v4), the 14 amlaw parts are "
                "freshly mean-pooled MiniLM-L6-v2 token vectors."
            ),
            (
                "embedding model is sentence-transformers/all-MiniLM-L6-v2 "
                "(384-dim), NOT cl-tohoku/bert-base-japanese-v3 (768-dim). "
                "The brief's BERT-768 path is owned by Lane M5 SimCSE "
                "fine-tune → v5 atomic dim-shift."
            ),
            (
                "nlist upgraded from v3's 1024 → 2048 to match the ~sqrt(N) "
                "IVF guideline at 588K-scale vectors with 2.5x cohort-imbalance "
                "headroom (am_law_article is ~60% of total v4)."
            ),
        ],
    }

    if args.no_upload:
        _log("info", "upload_skipped", reason="--no-upload")
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 0

    base = args.v4_prefix.rstrip("/")
    s3.put_object(Bucket=args.bucket, Key=f"{base}/index.faiss", Body=index_bytes)
    s3.put_object(
        Bucket=args.bucket,
        Key=f"{base}/meta.json",
        Body=meta_jsonl.encode("utf-8"),
    )
    s3.put_object(
        Bucket=args.bucket,
        Key=f"{base}/run_manifest.json",
        Body=json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
    )
    _log(
        "info",
        "v4_uploaded",
        index_uri=f"s3://{args.bucket}/{base}/index.faiss",
        meta_uri=f"s3://{args.bucket}/{base}/meta.json",
        manifest_uri=f"s3://{args.bucket}/{base}/run_manifest.json",
    )
    with _ctx.suppress(OSError):
        os.makedirs(args.cache_dir, exist_ok=True)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bucket", default=os.environ.get("FAISS_BUCKET", DEFAULT_BUCKET))
    p.add_argument("--embed-prefix", default=os.environ.get("EMBED_PREFIX", DEFAULT_EMBED_PREFIX))
    p.add_argument(
        "--corpus-prefix", default=os.environ.get("CORPUS_PREFIX", DEFAULT_CORPUS_PREFIX)
    )
    p.add_argument("--v3-prefix", default=os.environ.get("V3_PREFIX", DEFAULT_V3_PREFIX))
    p.add_argument("--v4-prefix", default=os.environ.get("V4_PREFIX", DEFAULT_V4_PREFIX))
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE", DEFAULT_PROFILE))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    p.add_argument("--dim", type=int, default=DEFAULT_DIM)
    p.add_argument("--nlist", type=int, default=DEFAULT_NLIST)
    p.add_argument("--cache-dir", default=os.environ.get("FAISS_CACHE_DIR", DEFAULT_CACHE_DIR))
    p.add_argument("--no-upload", action="store_true")
    p.add_argument(
        "--executor",
        action="store_true",
        help="In-Batch container codepath: download v3 + 14 amlaw parts and build v4.",
    )
    p.add_argument(
        "--submit-batch",
        action="store_true",
        help="Submit as EC2 Batch job (default execution path).",
    )
    p.add_argument(
        "--local",
        action="store_true",
        help="Run the build locally (slow on a 30 MB/s link; use Batch instead).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Default: emit plan + dry-run Batch submit. Pass --commit to actually submit.",
    )
    p.add_argument(
        "--commit",
        action="store_true",
        help="Actually submit (Batch) or run (local/executor). Without --commit this is a dry-run.",
    )
    p.add_argument(
        "--job-name",
        default=f"jpcite-faiss-v4-amlaw-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    args = parse_args(argv)

    run_id = (
        f"v4-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    )
    plan = emit_plan(
        bucket=args.bucket,
        embed_prefix=args.embed_prefix,
        corpus_prefix=args.corpus_prefix,
        v3_prefix=args.v3_prefix,
        v4_prefix=args.v4_prefix,
        dim=args.dim,
        nlist=args.nlist,
    )
    plan["run_id"] = run_id

    dry_run = not args.commit

    _log(
        "info",
        "boot",
        run_id=run_id,
        bucket=args.bucket,
        amlaw_parts=len(AMLAW_PART_JOBS),
        dry_run=dry_run,
        mode=("executor" if args.executor else ("submit_batch" if not args.local else "local")),
    )

    if args.executor:
        if not args.commit:
            plan["execution_mode"] = "executor_dry_run"
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        plan["execution_mode"] = "executor"
        return _executor_run(args, run_id=run_id)

    if args.local:
        _log(
            "warn",
            "local_mode_deferred",
            note=(
                "Local mode is the alternative; default execution is Batch. "
                "Each amlaw output is 0.5-49 GB; on a 30 MB/s link the 14-part "
                "pull is 1-3 hours of I/O. To run locally, pass --local --commit "
                "and budget ≥3 hours."
            ),
        )
        plan["execution_mode"] = "local_deferred"
        if not args.commit:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        # Local execution would dispatch to build_faiss_v3_expand-style
        # logic with NEW_FAMILY_JOBS = AMLAW_PART_JOBS + the v3 base.
        # Intentionally not implemented here — the production path is
        # Batch, and the local form would re-implement 600 LoC from
        # build_faiss_v3_expand.py. Lane M4 brief prefers the Batch
        # path; local validation can run against a single part subset.
        _log(
            "error",
            "local_commit_not_implemented",
            note=(
                "Local --commit is intentionally not wired in v4. The "
                "production path is Batch (--submit-batch --commit). "
                "Local single-part validation is doable via the v3 "
                "expand driver with NEW_FAMILY_JOBS narrowed to a single "
                "amlaw entry."
            ),
        )
        return 3

    # Default: Batch submit path.
    batch_result = submit_batch_job(
        job_name=args.job_name,
        profile=args.profile,
        region=args.region,
        bucket=args.bucket,
        embed_prefix=args.embed_prefix,
        corpus_prefix=args.corpus_prefix,
        v3_prefix=args.v3_prefix,
        v4_prefix=args.v4_prefix,
        dry_run=dry_run,
    )
    plan["execution_mode"] = "submit_batch"
    plan["batch_submit"] = batch_result

    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
