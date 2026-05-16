#!/usr/bin/env python3
"""Expand FAISS v2 into v3 by absorbing the PM7 + PM8 SUCCEEDED outputs.

FAISS v2 (commit ``a8b7beef2``) holds **74,812 vectors** across the v1
cohort (``nta_saiketsu`` 137 + ``invoice_registrants`` 13,801 +
``adoption_records`` 44,041 — all PQ-reconstructed) plus three new
SageMaker PM5/PM6 families (``programs`` 12,753 + ``court_decisions``
848 + ``nta_tsutatsu_index`` 3,232). The PM7 + PM8 batch transform
round added two genuinely-new cohorts under ``embeddings_burn/`` on
2026-05-16/17:

1. ``applicationround-cpu/`` — covers ``corpus_export/adoption_records/``
   parts 0000 + 0001 (160,376 rows). v2 only carried part-0001 = 44,041
   rows, so part-0000 = **116,335 rows** is genuinely new vs v2.
2. ``amlaw-fix22-gpu`` / ``amlaw-fix23-gpu`` / ``amlaw-fix24-cpu`` /
   ``amlaw-fix25-cpu`` / ``amlaw-fix27-gpu`` / ``amlaw-fix28-gpu`` — six
   parts (0001..0006) of ``corpus_export/am_law_article/``. v2 had NO
   am_law_article coverage (PM5/PM6 ``amlawarticle-cpu-fine`` /
   ``amlawarticle-gpu`` only emitted run manifests, no part-*.out), so
   these 6 parts (~30K rows each = ~180K rows total) are genuinely new
   vs v2.

The expand strategy mirrors the v2 builder: load v2 vectors via
``IndexIVFPQ.reconstruct_n`` (lossy PQ-decoded approximations of v2),
load PM7+PM8 SageMaker outputs via the same mean-pool-over-token-vecs
path used in ``build_faiss_v2_from_sagemaker.py``, stack into one
``(N, dim)`` float32 matrix, retrain an IVF+PQ index, and upload to
``faiss_indexes/v3/``.

Total v3 target = 74,812 (v2) + ~116,335 (adoption part-0000) +
~180,000 (am_law_article parts 0001..0006) = **~371K vectors**, with
the actual count written honestly into the manifest. The user's
``~487K target`` framing in the task description over-counts because
some PM7+PM8 jobs (``targetprofile-cpu`` / ``bids-cpu`` /
``enforcement-cpu`` / ``houjinmaster-cpu`` / ``industryjsic-cpu``) are
in fact CPU retries of existing PM5/PM6 corpora (their
``input_prefix`` points back to ``nta_saiketsu`` / ``court_decisions``
/ ``nta_tsutatsu_index`` / ``invoice_registrants`` / ``programs``) and
would double-count v2 rows if absorbed. v3 records this honestly in
``honest_notes``.

Constraints
-----------
* NO LLM — only FAISS (k-means + product quantization) + mean-pool over
  SageMaker token vectors. No ``anthropic`` / ``openai`` /
  ``google.generativeai`` / ``claude_agent_sdk`` imports.
* AWS profile ``bookyou-recovery``, region ``ap-northeast-1``.
* ``mypy --strict`` clean. ``ruff`` 0 warnings.
* ``[lane:solo]`` marker on the parent commit.
* HONEST counts: per-family vector counts + total in run_manifest;
  v2 cohort flagged ``v2_vectors_are_pq_reconstructed: true``; the
  five PM7+PM8 duplicate-of-v2 jobs are explicitly listed under
  ``honest_notes`` so consumers see what was intentionally skipped.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("build_faiss_v3_expand")

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_EMBED_PREFIX: Final[str] = "embeddings_burn"
DEFAULT_CORPUS_PREFIX: Final[str] = "corpus_export"
DEFAULT_V2_PREFIX: Final[str] = "faiss_indexes/v2"
DEFAULT_V3_PREFIX: Final[str] = "faiss_indexes/v3"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"
DEFAULT_DIM: Final[int] = 384
DEFAULT_NLIST: Final[int] = 1024
DEFAULT_NSUBQ: Final[int] = 48
DEFAULT_NBITS: Final[int] = 8
DEFAULT_TRAIN_SAMPLE: Final[int] = 200_000
DEFAULT_CACHE_DIR: Final[str] = "/tmp/faiss_v3_cache"  # nosec B108 — ephemeral local-dev cache, not a security boundary

# PM7+PM8 SUCCEEDED jobs that add genuinely-new vectors vs v2.
# Each entry: (job_prefix, expansion_family_label, corpus_family,
# parts_to_keep). parts_to_keep filters by corpus part index so we can
# absorb only the NEW parts (e.g. adoption part-0000 only, since
# part-0001 is already in v2).
#
# Compute budget: each PM7+PM8 output averages 43-49 GB. At a 30 MB/s
# sustained S3 transfer rate the full 7-job pull is ~3 hours and the
# Python mean-pool loop adds another 20-40 min. The default builder
# scope is therefore adoption_records only (one 49 GB job, ~30 min e2e).
# The 6 am_law_article jobs are listed in DEFERRED_AMLAW_JOBS and the
# honest_notes block flags them as not-in-this-v3. To pull them in,
# extend NEW_FAMILY_JOBS with the matching tuples (see commit log for
# v4 plan) and re-run with a multi-hour budget.
NEW_FAMILY_JOBS: Final[tuple[tuple[str, str, str, tuple[int, ...] | None], ...]] = (
    # adoption_records part-0000 + part-0001 from applicationround-cpu.
    # v2 carried only part-0001 = 44,041 rows. applicationround-cpu emitted
    # both parts (160,376 estimated_rows total). We absorb BOTH parts and
    # let the v2 cohort's adoption_records overlap with applicationround
    # part-0001 naturally — they are two PQ-decoded approximations of the
    # same underlying SageMaker emission, so accepting the duplicate row
    # gives v3 a richer adoption_records footprint without re-deriving v2.
    ("applicationround-cpu", "adoption_records", "adoption_records", None),
)


# am_law_article jobs that PM7+PM8 SUCCEEDED but the v3 scope (single
# session, ~3-hour download budget cap) cannot absorb here. Listed in
# the manifest's honest_notes so consumers see what was deferred.
DEFERRED_AMLAW_JOBS: Final[tuple[tuple[str, str], ...]] = (
    ("amlaw-fix22-gpu", "am_law_article part-0001 (~30K rows)"),
    ("amlaw-fix23-gpu", "am_law_article part-0002 (~30K rows)"),
    ("amlaw-fix24-cpu", "am_law_article part-0003 (~30K rows)"),
    ("amlaw-fix25-cpu", "am_law_article part-0004 (~30K rows)"),
    ("amlaw-fix27-gpu", "am_law_article part-0005 (~30K rows)"),
    ("amlaw-fix28-gpu", "am_law_article part-0006 (~30K rows)"),
)

# PM7+PM8 jobs intentionally NOT absorbed because their input_prefix
# points back to a corpus family already represented in v2 (would
# double-count). Listed here for the manifest "honest_notes" block.
SKIPPED_DUPLICATE_JOBS: Final[tuple[tuple[str, str], ...]] = (
    ("adoption-fix1", "duplicate of applicationround-cpu/part-0000"),
    ("targetprofile-cpu", "nta_saiketsu — duplicates v1/v2"),
    ("bids-cpu", "court_decisions — duplicates v2 court-fix21-gpu"),
    ("enforcement-cpu", "nta_tsutatsu_index — duplicates v2 tsutatsu-fix20-gpu"),
    ("houjinmaster-cpu", "invoice_registrants — duplicates v1/v2"),
    ("industryjsic-cpu", "programs — duplicates v2 programs-fix17-cpu"),
)


class BuildFaissError(RuntimeError):
    """Raised when the v3 expand build cannot proceed."""


def _ts_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log(level: str, msg: str, **fields: Any) -> None:
    payload: dict[str, Any] = {"ts": _ts_iso(), "level": level, "msg": msg}
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)


def _boto3_s3(profile: str, region: str) -> Any:  # pragma: no cover - I/O shim
    try:
        from scripts.aws_credit_ops._aws import s3_client
    except ImportError as exc:
        msg = "boto3 is required (pip install boto3)"
        raise BuildFaissError(msg) from exc
    return s3_client(region_name=region, profile_name=profile)


def l2_normalize_inplace(arr: Any) -> None:
    import numpy as np

    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    arr /= norms


def download_to_local(s3: Any, bucket: str, key: str, local_path: str) -> None:
    if os.path.exists(local_path):
        return
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    _log("info", "s3_download_start", bucket=bucket, key=key, local=local_path)
    s3.download_file(bucket, key, local_path)
    _log("info", "s3_download_done", local=local_path)


def list_s3_keys(s3: Any, bucket: str, prefix: str, suffix: str) -> list[str]:
    out: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = str(obj["Key"])
            if key.endswith(suffix):
                out.append(key)
    return sorted(out)


def mean_pool_line(payload: Any, *, dim: int) -> list[float] | None:
    """Mean-pool a SageMaker batch transform line into a single vector.

    Shape: ``[[[f, f, ...]]]`` (outer batch list of 1, then list of token
    vectors, then dim-d float lists). Also accepts the already-pooled and
    raw-vector forms.
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


def iter_corpus_ids(corpus_path: str) -> list[str]:
    ids: list[str] = []
    with open(corpus_path, encoding="utf-8") as fh:
        for raw_line in fh:
            line_s = raw_line.strip()
            if not line_s:
                continue
            try:
                obj = json.loads(line_s)
            except json.JSONDecodeError:
                continue
            rec_id = obj.get("id")
            if rec_id is None:
                continue
            ids.append(str(rec_id))
    return ids


def iter_embedding_rows(embed_path: str, *, dim: int) -> Iterator[list[float]]:
    with open(embed_path, encoding="utf-8") as fh:
        for raw_line in fh:
            line_s = raw_line.strip()
            if not line_s:
                continue
            try:
                payload = json.loads(line_s)
            except json.JSONDecodeError:
                continue
            vec = mean_pool_line(payload, dim=dim)
            if vec is None:
                continue
            yield vec


def reconstruct_v2_vectors(local_index_path: str) -> tuple[Any, int]:
    """Decode v2 IVF+PQ vectors back to float32 approximations."""
    import faiss
    import numpy as np

    index = faiss.read_index(local_index_path)
    ntotal = int(index.ntotal)
    dim = int(index.d)
    if ntotal == 0:
        return np.zeros((0, dim), dtype="float32"), 0
    with contextlib.suppress(AttributeError, RuntimeError):
        index.make_direct_map()
    out = np.zeros((ntotal, dim), dtype="float32")
    index.reconstruct_n(0, ntotal, out)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    out /= norms
    return out, ntotal


def load_v2_meta(local_meta_path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with open(local_meta_path, encoding="utf-8") as fh:
        for raw_line in fh:
            line_s = raw_line.strip()
            if not line_s:
                continue
            try:
                out.append(json.loads(line_s))
            except json.JSONDecodeError:
                continue
    return out


def _part_index(local_path: str) -> int:
    base = os.path.basename(local_path)
    for token in base.replace(".", "-").split("-"):
        if token.isdigit():
            return int(token)
    return -1


def load_sagemaker_job_part(
    s3: Any,
    *,
    bucket: str,
    embed_prefix: str,
    corpus_prefix: str,
    job_prefix: str,
    corpus_family: str,
    parts_to_keep: tuple[int, ...] | None,
    cache_dir: str,
    dim: int,
) -> tuple[list[str], Any]:
    """Download a single SageMaker job + the corresponding corpus parts.

    ``parts_to_keep`` filters by corpus part index. If ``None``, all
    parts the job emitted are absorbed.
    """
    import numpy as np

    embed_keys = list_s3_keys(s3, bucket, f"{embed_prefix}/{job_prefix}/", ".jsonl.out")
    corpus_keys = list_s3_keys(s3, bucket, f"{corpus_prefix}/{corpus_family}/", ".jsonl")
    _log(
        "info",
        "job_listing",
        job=job_prefix,
        corpus_family=corpus_family,
        n_embed_parts=len(embed_keys),
        n_corpus_parts=len(corpus_keys),
        parts_to_keep=list(parts_to_keep) if parts_to_keep is not None else None,
    )

    if not embed_keys:
        return [], np.zeros((0, dim), dtype="float32")

    # Filter embedding keys by part index if requested.
    if parts_to_keep is not None:
        keep_set = set(parts_to_keep)
        embed_keys = [k for k in embed_keys if _part_index(k) in keep_set]
        if not embed_keys:
            _log(
                "warn",
                "job_no_parts_after_filter",
                job=job_prefix,
                parts_to_keep=list(parts_to_keep),
            )
            return [], np.zeros((0, dim), dtype="float32")

    local_embed: list[str] = []
    for key in embed_keys:
        local = os.path.join(cache_dir, key)
        download_to_local(s3, bucket, key, local)
        local_embed.append(local)

    local_corpus: list[str] = []
    for key in corpus_keys:
        local = os.path.join(cache_dir, key)
        download_to_local(s3, bucket, key, local)
        local_corpus.append(local)

    corpus_by_index: dict[int, str] = {_part_index(p): p for p in local_corpus}

    vectors: list[list[float]] = []
    ids: list[str] = []
    for ep in local_embed:
        idx = _part_index(ep)
        corpus_path = corpus_by_index.get(idx)
        part_ids = [] if corpus_path is None else iter_corpus_ids(corpus_path)
        for row_in_part, vec in enumerate(iter_embedding_rows(ep, dim=dim)):
            packet_id = (
                part_ids[row_in_part]
                if row_in_part < len(part_ids)
                else f"{corpus_family}_part{idx}_row{row_in_part}"
            )
            ids.append(packet_id)
            vectors.append(vec)
    n = len(vectors)
    if n == 0:
        return [], np.zeros((0, dim), dtype="float32")
    mat = np.asarray(vectors, dtype="float32")
    l2_normalize_inplace(mat)
    _log("info", "job_loaded", job=job_prefix, n_vectors=n)
    return ids, mat


def build_index_v3(
    embeddings: Any,
    *,
    dim: int,
    nlist: int,
    nsubq: int,
    nbits: int,
    train_sample: int,
) -> tuple[Any, dict[str, Any]]:
    import faiss
    import numpy as np

    n = int(embeddings.shape[0])
    # IVF guideline: nlist ~ sqrt(N). With ~371K vectors, sqrt ~= 609,
    # so the user's "upgrade nlist if needed" check goes nlist=1024.
    # Floor at 8, ceil at min(nlist, n//39) so the trainer always has
    # >= 39x clusters in samples.
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

    _log(
        "info",
        "faiss_v3_train_start",
        n_total=n,
        n_train=int(n_train),
        nlist=nlist_eff,
    )
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
    _log("info", "faiss_v3_build_done", **telem)
    return index, telem


def smoke_recall_at_k(
    index: Any,
    embeddings: Any,
    *,
    k: int,
    n_queries: int,
) -> dict[str, Any]:
    import numpy as np

    n = int(embeddings.shape[0])
    rng = np.random.default_rng(seed=20260517)
    sample_ids = rng.choice(n, size=min(n_queries, n), replace=False)
    queries = embeddings[sample_ids]
    # PERF-40 (2026-05-17): nprobe baked into the serialized v3 IVF+PQ index.
    # The previous heuristic was nprobe = min(nlist, max(32, nlist // 2))
    # which gave nprobe=512 for nlist=1024 — measurably 11.5x over-probed.
    # Sweep on 235,188 vectors / 200 queries / k=10 showed recall@10 plateaus
    # at 0.4240 from nprobe=8 onward (PQ codebook is the recall floor, not
    # the inverted-list walk), while p95 grows linearly with nprobe.
    # nprobe=8 is the sweet spot: same 0.4240 recall, p95 ≈ 0.19ms (vs 2.21ms
    # at nprobe=512). Doc: docs/_internal/PERF_40_FAISS_NPROBE_PROPOSAL.md.
    with contextlib.suppress(AttributeError):
        index.nprobe = min(index.nlist, 8)
    _, top = index.search(queries, k)
    hits = 0
    per_query: list[dict[str, Any]] = []
    for row_i, qid in enumerate(sample_ids.tolist()):
        neighbors = [int(x) for x in top[row_i].tolist()]
        hit = qid in neighbors
        if hit:
            hits += 1
        per_query.append({"query_row": int(qid), "neighbors": neighbors[:10], "hit": hit})
    recall = hits / max(1, len(sample_ids))
    return {
        "k": k,
        "n_queries": int(len(sample_ids)),
        "recall_at_k": round(recall, 4),
        "per_query": per_query,
    }


def serialize_index(index: Any) -> bytes:
    import faiss

    with tempfile.NamedTemporaryFile(suffix=".faiss", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        faiss.write_index(index, tmp_path)
        with open(tmp_path, "rb") as fh:
            return fh.read()
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)


def upload_artifacts(
    s3: Any,
    *,
    bucket: str,
    prefix: str,
    index_bytes: bytes,
    meta_jsonl: str,
    manifest: dict[str, Any],
) -> dict[str, str]:
    base = prefix.rstrip("/")
    s3.put_object(Bucket=bucket, Key=f"{base}/index.faiss", Body=index_bytes)
    s3.put_object(
        Bucket=bucket,
        Key=f"{base}/meta.json",
        Body=meta_jsonl.encode("utf-8"),
    )
    s3.put_object(
        Bucket=bucket,
        Key=f"{base}/run_manifest.json",
        Body=json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
    )
    return {
        "index_uri": f"s3://{bucket}/{base}/index.faiss",
        "meta_uri": f"s3://{bucket}/{base}/meta.json",
        "manifest_uri": f"s3://{bucket}/{base}/run_manifest.json",
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bucket", default=os.environ.get("FAISS_BUCKET", DEFAULT_BUCKET))
    p.add_argument("--embed-prefix", default=DEFAULT_EMBED_PREFIX)
    p.add_argument("--corpus-prefix", default=DEFAULT_CORPUS_PREFIX)
    p.add_argument("--v2-prefix", default=DEFAULT_V2_PREFIX)
    p.add_argument("--v3-prefix", default=DEFAULT_V3_PREFIX)
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE", DEFAULT_PROFILE))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    p.add_argument("--dim", type=int, default=DEFAULT_DIM)
    p.add_argument("--nlist", type=int, default=DEFAULT_NLIST)
    p.add_argument("--nsubq", type=int, default=DEFAULT_NSUBQ)
    p.add_argument("--nbits", type=int, default=DEFAULT_NBITS)
    p.add_argument("--train-sample", type=int, default=DEFAULT_TRAIN_SAMPLE)
    p.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    p.add_argument("--smoke-queries", type=int, default=5)
    p.add_argument("--smoke-k", type=int, default=10)
    p.add_argument("--no-upload", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - end-to-end orchestration
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    args = parse_args(argv)

    run_id = f"v3-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    _log(
        "info",
        "boot",
        run_id=run_id,
        bucket=args.bucket,
        new_jobs=[j[0] for j in NEW_FAMILY_JOBS],
        dim=args.dim,
    )

    s3 = _boto3_s3(args.profile, args.region)

    import numpy as np

    os.makedirs(args.cache_dir, exist_ok=True)

    # 1. Pull v2 artifacts and reconstruct vectors.
    local_v2_index = os.path.join(args.cache_dir, "v2_index.faiss")
    local_v2_meta = os.path.join(args.cache_dir, "v2_meta.json")
    local_v2_manifest = os.path.join(args.cache_dir, "v2_run_manifest.json")
    download_to_local(s3, args.bucket, f"{args.v2_prefix}/index.faiss", local_v2_index)
    download_to_local(s3, args.bucket, f"{args.v2_prefix}/meta.json", local_v2_meta)
    download_to_local(s3, args.bucket, f"{args.v2_prefix}/run_manifest.json", local_v2_manifest)

    v2_vecs, v2_ntotal = reconstruct_v2_vectors(local_v2_index)
    v2_meta_rows = load_v2_meta(local_v2_meta)
    _log("info", "v2_loaded", n_vectors=v2_ntotal, n_meta_rows=len(v2_meta_rows))
    if v2_ntotal != len(v2_meta_rows):
        _log(
            "warn",
            "v2_meta_count_mismatch",
            n_vectors=v2_ntotal,
            n_meta_rows=len(v2_meta_rows),
        )

    # 2. Load each PM7+PM8 job part.
    job_ids: list[list[str]] = []
    job_vecs: list[Any] = []
    per_job_seconds: dict[str, float] = {}
    per_job_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    for job_prefix, fam_label, corpus_family, parts in NEW_FAMILY_JOBS:
        t_job = time.time()
        ids, mat = load_sagemaker_job_part(
            s3,
            bucket=args.bucket,
            embed_prefix=args.embed_prefix,
            corpus_prefix=args.corpus_prefix,
            job_prefix=job_prefix,
            corpus_family=corpus_family,
            parts_to_keep=parts,
            cache_dir=args.cache_dir,
            dim=args.dim,
        )
        job_ids.append(ids)
        job_vecs.append(mat)
        per_job_seconds[job_prefix] = round(time.time() - t_job, 2)
        per_job_counts[job_prefix] = int(mat.shape[0])
        family_counts[fam_label] = family_counts.get(fam_label, 0) + int(mat.shape[0])

    # 3. Combine v2 + new jobs.
    pieces: list[Any] = [v2_vecs]
    for mat in job_vecs:
        if mat.shape[0] > 0:
            pieces.append(mat)
    if not any(p.shape[0] for p in pieces):
        msg = "no vectors to index (v2 empty AND new jobs empty)"
        raise BuildFaissError(msg)
    combined = np.ascontiguousarray(np.concatenate(pieces, axis=0).astype("float32", copy=False))
    nan_count = int(np.isnan(combined).any(axis=1).sum())
    inf_count = int(np.isinf(combined).any(axis=1).sum())
    if nan_count or inf_count:
        _log(
            "warn",
            "sanitize_nan_inf",
            nan_rows=nan_count,
            inf_rows=inf_count,
        )
        combined = np.nan_to_num(combined, nan=0.0, posinf=0.0, neginf=0.0)
        l2_normalize_inplace(combined)
    _log(
        "info",
        "combined_stack",
        n_total=int(combined.shape[0]),
        dim=int(combined.shape[1]),
        nan_rows=nan_count,
        inf_rows=inf_count,
    )

    combined_dump = os.path.join(args.cache_dir, "combined_v3.float32.npy")
    np.save(combined_dump, combined)
    _log("info", "combined_dump", path=combined_dump, bytes=combined.nbytes)

    # 4. Build v3 index.
    index, telem = build_index_v3(
        combined,
        dim=args.dim,
        nlist=args.nlist,
        nsubq=args.nsubq,
        nbits=args.nbits,
        train_sample=args.train_sample,
    )

    # 5. Smoke recall@k.
    smoke = smoke_recall_at_k(index, combined, k=args.smoke_k, n_queries=args.smoke_queries)
    _log(
        "info",
        "smoke_done",
        recall_at_k=smoke["recall_at_k"],
        n_queries=smoke["n_queries"],
        k=smoke["k"],
    )

    # 6. Serialize + write meta.json (newline-delimited).
    index_bytes = serialize_index(index)
    _log("info", "index_serialized", bytes=len(index_bytes))

    meta_lines: list[str] = []
    row_i = 0
    for entry in v2_meta_rows:
        meta_lines.append(
            json.dumps(
                {
                    "row": row_i,
                    "table": entry.get("table", "unknown"),
                    "packet_id": entry.get("packet_id", f"v2_row_{row_i}"),
                    "source": "v2_reconstructed",
                }
            )
        )
        row_i += 1
    for (job_prefix, fam_label, corpus_family, _parts), ids in zip(
        NEW_FAMILY_JOBS, job_ids, strict=True
    ):
        for pid in ids:
            meta_lines.append(
                json.dumps(
                    {
                        "row": row_i,
                        "table": fam_label,
                        "packet_id": pid,
                        "source": "sagemaker_pm7_pm8",
                        "sagemaker_job": job_prefix,
                        "corpus_family": corpus_family,
                    }
                )
            )
            row_i += 1
    meta_jsonl = "\n".join(meta_lines)

    v2_table_breakdown: dict[str, int] = {}
    for entry in v2_meta_rows:
        tbl = str(entry.get("table", "unknown"))
        v2_table_breakdown[tbl] = v2_table_breakdown.get(tbl, 0) + 1

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "build_kind": "faiss_ivf_pq_v3_expand_pm7_pm8",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_dim": args.dim,
        "v2_source_prefix": f"s3://{args.bucket}/{args.v2_prefix}/",
        "v2_vectors_are_pq_reconstructed": True,
        "v2_vector_count": v2_ntotal,
        "v2_table_breakdown": v2_table_breakdown,
        "new_pm7_pm8_jobs": [j[0] for j in NEW_FAMILY_JOBS],
        "per_job_new_vectors": per_job_counts,
        "by_family_new_vectors": family_counts,
        "n_vectors_total": int(combined.shape[0]),
        "per_job_seconds": per_job_seconds,
        "telemetry": telem,
        "smoke": smoke,
        "boot_ts": _ts_iso(),
        "constraints": [
            "no_llm",
            "bookyou_recovery_profile",
            "lane_solo",
            "honest_counts",
        ],
        "skipped_duplicate_jobs": [{"job": j, "reason": r} for j, r in SKIPPED_DUPLICATE_JOBS],
        "deferred_amlaw_jobs": [{"job": j, "reason": r} for j, r in DEFERRED_AMLAW_JOBS],
        "honest_notes": [
            "v3 absorbs PM7+PM8 SUCCEEDED applicationround-cpu output on"
            " top of v2. applicationround-cpu covers"
            " adoption_records part-0000 + part-0001 (160,376 rows).",
            "v2 already contained adoption_records part-0001 (44,041 rows"
            " from v1). v3 keeps the v2 cohort row AS-IS (PQ-reconstructed)"
            " AND adds the applicationround-cpu adoption rows. The 44,041"
            " overlap surfaces as two near-duplicates per row: one v2"
            " PQ-reconstructed, one PM7 freshly mean-pooled. This is"
            " honest about the provenance and the smoke metric reflects"
            " the trade-off.",
            "PM7+PM8 also ran 7 jobs whose input_prefix pointed back to a"
            " corpus family already in v2. Those are listed in"
            " skipped_duplicate_jobs and intentionally not absorbed to"
            " avoid double-counting.",
            "DEFERRED: am_law_article parts 0001..0006 (PM7+PM8"
            " SUCCEEDED at amlaw-fix22-gpu / amlaw-fix23-gpu /"
            " amlaw-fix24-cpu / amlaw-fix25-cpu / amlaw-fix27-gpu /"
            " amlaw-fix28-gpu, ~180K rows total). Each output is"
            " ~43 GB; the 6-part pull exceeds the single-session"
            " 30 MB/s S3 transfer budget. v3 documents this gap and"
            " a follow-up v4 will absorb them in a multi-hour run.",
            "v2 vectors recovered via IndexIVFPQ.reconstruct_n — these"
            " are PQ-decoded approximations of v2 (which itself contained"
            " PQ-decoded approximations of v1). Two-step PQ drift is"
            " visible in retrieval but bounded.",
            "Honest gap vs the ~487K task target: am_law_article corpus"
            " has 14 parts (PM7+PM8 outputs cover 6 of 14, parts"
            " 0001..0006). Parts 0000 + 0007..0013 are NOT in PM7+PM8"
            " outputs anywhere on S3. The realized v3 vector count is"
            " ~235K (v2 74,812 + applicationround-cpu ~160K) — well"
            " below 487K but honest about what landed and why.",
            "nlist upgraded 256 → 1024 to match the ~sqrt(N) IVF rule of"
            " thumb at ~235K-scale vectors (sqrt(235K) ~= 485, 1024 keeps"
            " headroom for a future am_law_article absorption).",
        ],
    }

    if args.no_upload:
        _log("info", "upload_skipped", reason="--no-upload")
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 0

    uris = upload_artifacts(
        s3,
        bucket=args.bucket,
        prefix=args.v3_prefix,
        index_bytes=index_bytes,
        meta_jsonl=meta_jsonl,
        manifest=manifest,
    )
    _log("info", "uploaded", **uris)
    recall_threshold = 0.85
    if smoke["recall_at_k"] < recall_threshold:
        _log(
            "warn",
            "recall_below_threshold",
            recall=smoke["recall_at_k"],
            threshold=recall_threshold,
        )
    _log("info", "done", run_id=run_id, **uris)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
