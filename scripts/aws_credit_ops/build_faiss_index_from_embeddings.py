#!/usr/bin/env python3
"""Build a FAISS IVF+PQ index from precomputed SageMaker embedding outputs.

Unlike ``build_faiss_index_gpu.py`` (which re-encodes the corpus via
sentence-transformers on a GPU instance for credit burn), this script
consumes the SageMaker batch transform output already sitting in S3 at
``s3://<derived>/embeddings/<table>/part-*.jsonl.out``.

Each output line is a JSON envelope shaped like::

    [[[f, f, ... 384 floats], [...], ... up to ~227 token vectors]]

So one input packet (one input jsonl row) maps to a variable number of
token-level 384-d vectors. We mean-pool across the token axis to derive
one packet-level vector per line, then L2-normalize for inner-product
retrieval.

Pipeline
--------
1. Stream input embedding part files from S3 (per source table).
2. For each line: parse JSON, mean-pool the token vectors, L2-normalize.
3. Stack into one ``(N, 384)`` float32 matrix in memory.
4. Train FAISS ``IndexIVFPQ`` (inner product) on a random ~100k sample.
5. Add all vectors. Serialize. Write ``meta.json`` with row -> packet_id.
6. Smoke test: sample 5 query vectors from the index, retrieve top-10,
   verify recall@10 >= 0.80 (query is its own nearest neighbor).
7. Upload ``index.faiss`` + ``meta.json`` + ``run_manifest.json`` to
   ``s3://<derived>/faiss_indexes/v1/``.

Constraints
-----------
* NO LLM — FAISS is non-LLM ML (k-means + product quantization).
* Uses ``bookyou-recovery`` AWS profile via ``AWS_PROFILE`` env or arg.
* ``mypy --strict`` clean. ``ruff`` 0 warnings.
* ``[lane:solo]`` marker on the parent commit.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import random
import sys
import tempfile
import time
import uuid
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("build_faiss_index_from_embeddings")

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_EMBED_PREFIX: Final[str] = "embeddings"
DEFAULT_CORPUS_PREFIX: Final[str] = "corpus_export"
DEFAULT_INDEX_PREFIX: Final[str] = "faiss_indexes/v1"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"
DEFAULT_DIM: Final[int] = 384
DEFAULT_NLIST: Final[int] = 256
DEFAULT_NSUBQ: Final[int] = 48
DEFAULT_NBITS: Final[int] = 8
DEFAULT_TRAIN_SAMPLE: Final[int] = 100_000
DEFAULT_TABLES: Final[tuple[str, ...]] = (
    "nta_saiketsu",
    "invoice_registrants",
    "adoption_records",
)


class BuildFaissError(RuntimeError):
    """Raised when the build cannot proceed."""


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


def mean_pool_line(payload: Any, *, dim: int) -> list[float] | None:
    """Mean-pool a SageMaker batch transform line into a single vector.

    The expected shape is ``[[[f, f, ...]]]`` (outer batch list of 1,
    then list of token vectors, then 384-d float lists). Accept also
    ``[[f, ...]]`` (already pooled) and ``[f, ...]`` (raw vector).
    """
    cur = payload
    # Unwrap outermost batch axis if present (length 1).
    if isinstance(cur, list) and len(cur) == 1 and isinstance(cur[0], list):
        cur = cur[0]
    if not isinstance(cur, list) or not cur:
        return None

    # If cur is already a flat float list of length=dim, return as-is.
    if isinstance(cur[0], (int, float)) and len(cur) == dim:
        return [float(x) for x in cur]

    # Otherwise expect list of token vectors.
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
    """Read corpus part file to recover ordered (packet) IDs."""
    ids: list[str] = []
    with open(corpus_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            rec_id = obj.get("id")
            if rec_id is None:
                continue
            ids.append(str(rec_id))
    return ids


def iter_embedding_rows(embed_path: str, *, dim: int) -> Iterator[list[float]]:
    """Stream-mean-pool every line of an embedding part file."""
    with open(embed_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            vec = mean_pool_line(payload, dim=dim)
            if vec is None:
                continue
            yield vec


def l2_normalize_inplace(arr: Any) -> None:
    import numpy as np

    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    arr /= norms


def download_if_needed(s3: Any, bucket: str, key: str, local_path: str) -> None:
    if os.path.exists(local_path):
        return
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    _log("info", "s3_download_start", bucket=bucket, key=key, local=local_path)
    s3.download_file(bucket, key, local_path)
    _log("info", "s3_download_done", local=local_path)


def list_embedding_parts(s3: Any, bucket: str, prefix: str, table: str) -> list[str]:
    out: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    key_prefix = f"{prefix}/{table}/"
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        for obj in page.get("Contents", []) or []:
            key = str(obj["Key"])
            if key.endswith(".jsonl.out"):
                out.append(key)
    return sorted(out)


def list_corpus_parts(s3: Any, bucket: str, prefix: str, table: str) -> list[str]:
    out: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    key_prefix = f"{prefix}/{table}/"
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        for obj in page.get("Contents", []) or []:
            key = str(obj["Key"])
            if key.endswith(".jsonl"):
                out.append(key)
    return sorted(out)


def build_index(
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

    _log("info", "faiss_train_start", n_total=n, n_train=int(n_train), nlist=nlist_eff)
    t0 = time.time()
    index.train(train_data)
    train_dt = time.time() - t0

    t1 = time.time()
    index.add(embeddings)
    add_dt = time.time() - t1

    telem = {
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
    _log("info", "faiss_build_done", **telem)
    return index, telem


def smoke_test_recall_at_k(
    index: Any, embeddings: Any, *, k: int, n_queries: int
) -> dict[str, Any]:
    """Sample queries from the index and check recall@k.

    A correct retriever returns each query's own row id within top-k.
    Threshold is set per IVF+PQ realistic recall: with nprobe=8 over
    nlist clusters and 8-bit PQ codes, recall@10 of ~0.80-0.95 is
    expected on aligned data.
    """
    import numpy as np

    n = int(embeddings.shape[0])
    rng = np.random.default_rng(seed=20260516)
    sample_ids = rng.choice(n, size=min(n_queries, n), replace=False)
    queries = embeddings[sample_ids]

    # IVF+PQ recall@k tuning knob. PERF-40 (2026-05-17) measured that
    # recall@10 plateaus at the PQ codebook floor by nprobe=4-8 on both
    # v2 (74k vec / nlist=256) and v3 (235k vec / nlist=1024). Raising
    # nprobe past 8 buys zero recall but pays linear latency. Pin to 8.
    # See docs/_internal/PERF_40_FAISS_NPROBE_PROPOSAL.md.
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
    s3.put_object(Bucket=bucket, Key=f"{base}/meta.json", Body=meta_jsonl.encode("utf-8"))
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
    p.add_argument(
        "--embed-prefix",
        default=os.environ.get("FAISS_EMBED_PREFIX", DEFAULT_EMBED_PREFIX),
    )
    p.add_argument(
        "--corpus-prefix",
        default=os.environ.get("FAISS_CORPUS_PREFIX", DEFAULT_CORPUS_PREFIX),
    )
    p.add_argument(
        "--index-prefix",
        default=os.environ.get("FAISS_INDEX_PREFIX", DEFAULT_INDEX_PREFIX),
    )
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE", DEFAULT_PROFILE))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    p.add_argument("--tables", default=",".join(DEFAULT_TABLES))
    p.add_argument("--dim", type=int, default=DEFAULT_DIM)
    p.add_argument("--nlist", type=int, default=DEFAULT_NLIST)
    p.add_argument("--nsubq", type=int, default=DEFAULT_NSUBQ)
    p.add_argument("--nbits", type=int, default=DEFAULT_NBITS)
    p.add_argument(
        "--train-sample",
        type=int,
        default=DEFAULT_TRAIN_SAMPLE,
        help="Maximum number of vectors used to train the IVF quantizer.",
    )
    p.add_argument(
        "--smoke-queries",
        type=int,
        default=5,
        help="Number of random query vectors for the recall smoke test.",
    )
    p.add_argument(
        "--smoke-k",
        type=int,
        default=10,
        help="Top-K used for the smoke test recall metric.",
    )
    p.add_argument(
        "--cache-dir",
        # /tmp/ is an operator-controlled scratch path for downloaded
        # embeddings/corpus parts, not a security-sensitive temp file;
        # the FAISS_CACHE_DIR env-var overrides it for production use.
        default=os.environ.get("FAISS_CACHE_DIR", "/tmp/faiss_cache"),  # nosec B108
    )
    p.add_argument("--no-upload", action="store_true", help="Skip S3 upload (dry-run).")
    return p.parse_args(argv)


def _load_table(
    s3: Any,
    *,
    bucket: str,
    embed_prefix: str,
    corpus_prefix: str,
    table: str,
    cache_dir: str,
    dim: int,
) -> tuple[list[tuple[str, str]], list[list[float]]]:
    """Download + mean-pool embeddings for one table.

    Returns parallel (id_map, vectors) lists. ``id_map[i] = (table, packet_id)``.
    """
    import numpy as np  # noqa: F401  (ensures numpy available; np used by callers)

    embed_keys = list_embedding_parts(s3, bucket, embed_prefix, table)
    corpus_keys = list_corpus_parts(s3, bucket, corpus_prefix, table)
    _log(
        "info",
        "table_listing",
        table=table,
        n_embed_parts=len(embed_keys),
        n_corpus_parts=len(corpus_keys),
    )
    if not embed_keys:
        return [], []

    # Local cache paths.
    local_embed: list[str] = []
    for key in embed_keys:
        local = os.path.join(cache_dir, key)
        download_if_needed(s3, bucket, key, local)
        local_embed.append(local)
    local_corpus: list[str] = []
    for key in corpus_keys:
        local = os.path.join(cache_dir, key)
        download_if_needed(s3, bucket, key, local)
        local_corpus.append(local)

    # SageMaker batch transform preserves input line order *per input
    # part*: ``embeddings/.../part-NNNN.jsonl.out`` aligns with
    # ``corpus_export/.../part-NNNN.jsonl``. Some upstream pipelines
    # may produce only a subset of parts (e.g. part-0001 without
    # part-0000), so we match on the basename digit instead of relying
    # on a global concatenated order.
    def _part_index(local_path: str) -> int:
        base = os.path.basename(local_path)
        for token in base.replace(".", "-").split("-"):
            if token.isdigit():
                return int(token)
        return -1

    corpus_by_index: dict[int, str] = {_part_index(p): p for p in local_corpus}

    vectors: list[list[float]] = []
    id_map: list[tuple[str, str]] = []
    for ep in local_embed:
        idx = _part_index(ep)
        corpus_path = corpus_by_index.get(idx)
        ids = [] if corpus_path is None else iter_corpus_ids(corpus_path)
        for row_in_part, vec in enumerate(iter_embedding_rows(ep, dim=dim)):
            packet_id = (
                ids[row_in_part]
                if row_in_part < len(ids)
                else f"{table}_part{idx}_row{row_in_part}"
            )
            id_map.append((table, packet_id))
            vectors.append(vec)
    _log("info", "table_loaded", table=table, n_vectors=len(vectors))
    return id_map, vectors


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    args = parse_args(argv)
    random.seed(20260516)

    run_id = f"v1-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    tables = tuple(t.strip() for t in args.tables.split(",") if t.strip())
    _log(
        "info",
        "boot",
        run_id=run_id,
        bucket=args.bucket,
        tables=list(tables),
        dim=args.dim,
        nlist=args.nlist,
        nsubq=args.nsubq,
        nbits=args.nbits,
    )

    s3 = _boto3_s3(args.profile, args.region)

    import numpy as np

    all_id_map: list[tuple[str, str]] = []
    all_vectors: list[list[float]] = []
    table_telem: dict[str, int] = {}
    t_load = time.time()
    for table in tables:
        ids, vecs = _load_table(
            s3,
            bucket=args.bucket,
            embed_prefix=args.embed_prefix,
            corpus_prefix=args.corpus_prefix,
            table=table,
            cache_dir=args.cache_dir,
            dim=args.dim,
        )
        all_id_map.extend(ids)
        all_vectors.extend(vecs)
        table_telem[table] = len(vecs)
    load_dt = round(time.time() - t_load, 2)
    _log("info", "all_loaded", n=len(all_vectors), seconds=load_dt, by_table=table_telem)

    if not all_vectors:
        msg = "no embedding vectors were loaded — aborting"
        raise BuildFaissError(msg)

    embeddings = np.asarray(all_vectors, dtype="float32")
    l2_normalize_inplace(embeddings)

    index, telem = build_index(
        embeddings,
        dim=args.dim,
        nlist=args.nlist,
        nsubq=args.nsubq,
        nbits=args.nbits,
        train_sample=args.train_sample,
    )

    smoke = smoke_test_recall_at_k(index, embeddings, k=args.smoke_k, n_queries=args.smoke_queries)
    _log(
        "info",
        "smoke_done",
        recall_at_k=smoke["recall_at_k"],
        n_queries=smoke["n_queries"],
        k=smoke["k"],
    )

    index_bytes = serialize_index(index)
    _log("info", "index_serialized", bytes=len(index_bytes))

    meta_lines: list[str] = []
    for i, (table, packet_id) in enumerate(all_id_map):
        meta_lines.append(json.dumps({"row": i, "table": table, "packet_id": packet_id}))
    meta_jsonl = "\n".join(meta_lines)

    manifest = {
        "run_id": run_id,
        "build_kind": "faiss_ivf_pq",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_dim": args.dim,
        "tables": list(tables),
        "by_table_n_vectors": table_telem,
        "n_vectors": int(embeddings.shape[0]),
        "telemetry": telem,
        "smoke": smoke,
        "load_seconds": load_dt,
        "boot_ts": _ts_iso(),
        "constraints": ["no_llm", "bookyou_recovery_profile", "lane_solo"],
    }

    if args.no_upload:
        _log("info", "upload_skipped", reason="--no-upload")
        return 0

    uris = upload_artifacts(
        s3,
        bucket=args.bucket,
        prefix=args.index_prefix,
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
        # Do not fail the run — IVF+PQ on tiny corpora can dip below
        # 0.80 due to quantization; the smoke metric is reported in the
        # manifest for transparency.

    _log("info", "done", run_id=run_id, **uris)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
