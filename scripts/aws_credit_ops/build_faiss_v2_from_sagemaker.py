#!/usr/bin/env python3
"""Build FAISS v2 from SageMaker PM5+PM6 outputs + v1 reconstruct.

Task #189 expansion path. SageMaker PM5/PM6 jobs SUCCEEDED for these
families (verified 2026-05-16 on commit ``a8b7beef2``)::

    programs-fix17-cpu      12,753 rows  (NEW family vs v1)
    invoice-fix18-cpu       13,801 rows  (duplicates v1 invoice_registrants)
    saiketsu-fix19-cpu         137 rows  (duplicates v1 nta_saiketsu)
    tsutatsu-fix20-gpu       3,232 rows  (NEW family vs v1)
    court-fix21-gpu            848 rows  (NEW family vs v1)

The 3 NEW families (programs, court, tsutatsu) account for 16,833
fresh vectors. The v1 cohort (57,979 vectors over saiketsu / invoice /
adoption_records) is reconstructed from the existing IVF+PQ index via
``reconstruct_n`` — these are PQ-decoded approximations, NOT the raw
SageMaker float32 emissions, so v2 is honest about that in the manifest.

Total v2 = v1 reconstruct + 3 new families = 57,979 + 16,833 = **74,812
vectors**. The "~90K target" called out in the task description is
short by ~15K because the PM5/PM6 outputs that succeeded did not include
``am_law_article`` — its SageMaker container jobs (amlawarticle-cpu-fine
/ amlawarticle-gpu) only emitted run manifests with no ``part-*.out``
artifacts. This script does NOT silently inflate counts to hit 90K;
it lands the honest 74,812 and the manifest writes the honest gap.

Constraints
-----------
* NO LLM — only FAISS (k-means + PQ) + mean-pool over SageMaker token
  vectors. No anthropic/openai/gemini imports.
* AWS profile ``bookyou-recovery``, region ``ap-northeast-1``.
* ``mypy --strict`` clean, ``ruff`` 0 warnings.
* ``[lane:solo]`` marker on the parent commit.
* HONEST counts: per-family vector counts + total in run_manifest;
  v1 cohort flagged ``v1_vectors_are_pq_reconstructed: true``.
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

logger = logging.getLogger("build_faiss_v2_from_sagemaker")

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_EMBED_PREFIX: Final[str] = "embeddings_burn"
DEFAULT_CORPUS_PREFIX: Final[str] = "corpus_export"
DEFAULT_V1_PREFIX: Final[str] = "faiss_indexes/v1"
DEFAULT_V2_PREFIX: Final[str] = "faiss_indexes/v2"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"
DEFAULT_DIM: Final[int] = 384
DEFAULT_NLIST: Final[int] = 256
DEFAULT_NSUBQ: Final[int] = 48
DEFAULT_NBITS: Final[int] = 8
DEFAULT_TRAIN_SAMPLE: Final[int] = 100_000
# /tmp/ here is an operator scratch path for downloaded SageMaker outputs +
# corpus parts; FAISS_V2_CACHE_DIR env-var overrides in production. Not a
# security-sensitive temp file.
DEFAULT_CACHE_DIR: Final[str] = "/tmp/faiss_v2_sm_cache"  # nosec B108

# (sagemaker_job_prefix, canonical_family, corpus_family) tuples.
# corpus_family is used to recover packet IDs from corpus_export/.
NEW_FAMILY_JOBS: Final[tuple[tuple[str, str, str], ...]] = (
    ("programs-fix17-cpu", "programs", "programs"),
    ("court-fix21-gpu", "court_decisions", "court_decisions"),
    ("tsutatsu-fix20-gpu", "nta_tsutatsu_index", "nta_tsutatsu_index"),
)


class BuildFaissError(RuntimeError):
    """Raised when the v2 SageMaker-based build cannot proceed."""


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


def reconstruct_v1_vectors(local_index_path: str) -> tuple[Any, int]:
    """Decode v1 IVF+PQ vectors back to float32 approximations."""
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


def load_v1_meta(local_meta_path: str) -> list[dict[str, Any]]:
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


def load_sagemaker_family(
    s3: Any,
    *,
    bucket: str,
    embed_prefix: str,
    corpus_prefix: str,
    job_prefix: str,
    corpus_family: str,
    cache_dir: str,
    dim: int,
) -> tuple[list[str], Any]:
    """Download SageMaker output + corpus parts, mean-pool to (N, dim)."""
    import numpy as np

    embed_keys = list_s3_keys(s3, bucket, f"{embed_prefix}/{job_prefix}/", ".jsonl.out")
    corpus_keys = list_s3_keys(s3, bucket, f"{corpus_prefix}/{corpus_family}/", ".jsonl")
    _log(
        "info",
        "family_listing",
        job=job_prefix,
        corpus_family=corpus_family,
        n_embed_parts=len(embed_keys),
        n_corpus_parts=len(corpus_keys),
    )

    if not embed_keys:
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
    # L2-normalize so inner-product retrieval is meaningful.
    l2_normalize_inplace(mat)
    _log("info", "family_loaded", job=job_prefix, n_vectors=n)
    return ids, mat


def build_index_v2(
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
    nlist_eff = max(8, min(nlist, max(8, n // 39)))
    nsubq_eff = nsubq if dim % nsubq == 0 else 16
    quantizer = faiss.IndexFlatIP(dim)
    index = faiss.IndexIVFPQ(quantizer, dim, nlist_eff, nsubq_eff, nbits)
    index.metric_type = faiss.METRIC_INNER_PRODUCT

    n_train = min(n, train_sample, max(nlist_eff * 39, 4096))
    if n_train < n:
        rng = np.random.default_rng(seed=20260516)
        idx = rng.choice(n, size=n_train, replace=False)
        train_data = embeddings[idx]
    else:
        train_data = embeddings

    _log(
        "info",
        "faiss_v2_train_start",
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
    _log("info", "faiss_v2_build_done", **telem)
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
    rng = np.random.default_rng(seed=20260516)
    sample_ids = rng.choice(n, size=min(n_queries, n), replace=False)
    queries = embeddings[sample_ids]
    # PERF-40 (2026-05-17): nprobe=8 measured optimal across v2/v3 sweeps —
    # recall@10 plateaus at the PQ codebook floor by nprobe=4-8 and the
    # legacy heuristic nprobe = min(nlist, max(32, nlist // 2)) just paid
    # latency for zero recall gain. See PERF_40_FAISS_NPROBE_PROPOSAL.md.
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
    p.add_argument("--v1-prefix", default=DEFAULT_V1_PREFIX)
    p.add_argument("--v2-prefix", default=DEFAULT_V2_PREFIX)
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

    run_id = f"v2-sm-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    _log(
        "info",
        "boot",
        run_id=run_id,
        bucket=args.bucket,
        new_families=[j[1] for j in NEW_FAMILY_JOBS],
        dim=args.dim,
    )

    s3 = _boto3_s3(args.profile, args.region)

    import numpy as np

    os.makedirs(args.cache_dir, exist_ok=True)

    # 1. Pull v1 artifacts and reconstruct vectors.
    local_v1_index = os.path.join(args.cache_dir, "v1_index.faiss")
    local_v1_meta = os.path.join(args.cache_dir, "v1_meta.json")
    local_v1_manifest = os.path.join(args.cache_dir, "v1_run_manifest.json")
    download_to_local(s3, args.bucket, f"{args.v1_prefix}/index.faiss", local_v1_index)
    download_to_local(s3, args.bucket, f"{args.v1_prefix}/meta.json", local_v1_meta)
    download_to_local(s3, args.bucket, f"{args.v1_prefix}/run_manifest.json", local_v1_manifest)

    v1_vecs, v1_ntotal = reconstruct_v1_vectors(local_v1_index)
    v1_meta_rows = load_v1_meta(local_v1_meta)
    _log("info", "v1_loaded", n_vectors=v1_ntotal, n_meta_rows=len(v1_meta_rows))
    if v1_ntotal != len(v1_meta_rows):
        _log(
            "warn",
            "v1_meta_count_mismatch",
            n_vectors=v1_ntotal,
            n_meta_rows=len(v1_meta_rows),
        )

    # 2. Load each new SageMaker family.
    family_ids: dict[str, list[str]] = {}
    family_vecs: dict[str, Any] = {}
    per_family_seconds: dict[str, float] = {}
    per_family_jobs: dict[str, str] = {}
    for job_prefix, family, corpus_family in NEW_FAMILY_JOBS:
        t_fam = time.time()
        per_family_jobs[family] = job_prefix
        ids, mat = load_sagemaker_family(
            s3,
            bucket=args.bucket,
            embed_prefix=args.embed_prefix,
            corpus_prefix=args.corpus_prefix,
            job_prefix=job_prefix,
            corpus_family=corpus_family,
            cache_dir=args.cache_dir,
            dim=args.dim,
        )
        family_ids[family] = ids
        family_vecs[family] = mat
        per_family_seconds[family] = round(time.time() - t_fam, 2)

    # 3. Combine v1 + new families.
    pieces: list[Any] = [v1_vecs]
    for _, family, _ in NEW_FAMILY_JOBS:
        if family_vecs[family].shape[0] > 0:
            pieces.append(family_vecs[family])
    if not any(p.shape[0] for p in pieces):
        msg = "no vectors to index (v1 empty AND new families empty)"
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

    combined_dump = os.path.join(args.cache_dir, "combined_v2_sm.float32.npy")
    np.save(combined_dump, combined)
    _log("info", "combined_dump", path=combined_dump, bytes=combined.nbytes)

    # 4. Build v2 index.
    index, telem = build_index_v2(
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
    for entry in v1_meta_rows:
        meta_lines.append(
            json.dumps(
                {
                    "row": row_i,
                    "table": entry.get("table", "unknown"),
                    "packet_id": entry.get("packet_id", f"v1_row_{row_i}"),
                    "source": "v1_reconstructed",
                }
            )
        )
        row_i += 1
    for _, family, _ in NEW_FAMILY_JOBS:
        for pid in family_ids[family]:
            meta_lines.append(
                json.dumps(
                    {
                        "row": row_i,
                        "table": family,
                        "packet_id": pid,
                        "source": "sagemaker_pm5_pm6",
                        "sagemaker_job": per_family_jobs[family],
                    }
                )
            )
            row_i += 1
    meta_jsonl = "\n".join(meta_lines)

    by_family_counts: dict[str, int] = {
        family: int(family_vecs[family].shape[0]) for _, family, _ in NEW_FAMILY_JOBS
    }
    v1_table_breakdown: dict[str, int] = {}
    for entry in v1_meta_rows:
        tbl = str(entry.get("table", "unknown"))
        v1_table_breakdown[tbl] = v1_table_breakdown.get(tbl, 0) + 1

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "build_kind": "faiss_ivf_pq_v2_from_sagemaker",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_dim": args.dim,
        "v1_source_prefix": f"s3://{args.bucket}/{args.v1_prefix}/",
        "v1_vectors_are_pq_reconstructed": True,
        "v1_vector_count": v1_ntotal,
        "v1_table_breakdown": v1_table_breakdown,
        "new_families": [j[1] for j in NEW_FAMILY_JOBS],
        "new_family_sagemaker_jobs": per_family_jobs,
        "by_family_new_vectors": by_family_counts,
        "n_vectors_total": int(combined.shape[0]),
        "per_family_seconds": per_family_seconds,
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
            "SageMaker PM5/PM6 outputs consumed directly. PM5+PM6"
            " SUCCEEDED for programs-fix17-cpu / invoice-fix18-cpu /"
            " saiketsu-fix19-cpu / tsutatsu-fix20-gpu / court-fix21-gpu.",
            "Only 3 of 5 successful PM5/PM6 outputs add NEW vectors"
            " vs v1 (programs, court, tsutatsu). invoice-fix18 and"
            " saiketsu-fix19 duplicate v1 tables and were intentionally"
            " skipped to avoid double-counting.",
            "am_law_article SageMaker jobs (amlawarticle-cpu-fine /"
            " amlawarticle-gpu) only emitted run manifests with no"
            " part-*.out, so am_law_article is NOT in v2.",
            "v1 vectors recovered via IndexIVFPQ.reconstruct_n — these"
            " are PQ-decoded approximations, not raw SageMaker float32"
            " emissions.",
            "Honest gap: 74,812 actual vs ~90K task target. The 15K"
            " shortfall is am_law_article which SageMaker did not emit"
            " outputs for.",
        ],
    }

    if args.no_upload:
        _log("info", "upload_skipped", reason="--no-upload")
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 0

    uris = upload_artifacts(
        s3,
        bucket=args.bucket,
        prefix=args.v2_prefix,
        index_bytes=index_bytes,
        meta_jsonl=meta_jsonl,
        manifest=manifest,
    )
    _log("info", "uploaded", **uris)
    recall_threshold = 0.80
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
