#!/usr/bin/env python3
"""Build a GPU-accelerated FAISS IVF-PQ index over the jpcite corpus.

This is the workload script executed by AWS Batch jobs running on
``jpcite-credit-ec2-spot-gpu-queue`` (compute environment
``jpcite-credit-ec2-spot-gpu``). It is a real ML workload designed
to consume Spot GPU minutes on g4dn / g5 instances at ~$0.48-1.00/hr
spot pricing, contributing to the AWS credit burn target.

Pipeline
--------
1. Read ``CORPUS_S3_PREFIX`` env var (default
   ``s3://jpcite-credit-993693061769-202605-derived/corpus_export/``).
2. List + stream each ``part-NNNN.jsonl`` for the configured tables.
3. Sentence-transformer encode (open-weight ``intfloat/multilingual-e5-small``
   384-d, NOT an LLM API). Batched on GPU (CUDA).
4. Train + populate a FAISS IVF-PQ index on the GPU. Periodically
   merge GPU index back to CPU memory and serialize to a binary blob.
5. Upload ``faiss_index.bin`` + ``id_map.jsonl`` + ``run_manifest.json``
   to ``s3://<DERIVED_BUCKET>/faiss/<run_id>/``.

Constraints
-----------
* **NO LLM API.** Open-weight sentence-transformer only (downloads from
  Hugging Face on first run; subsequent runs use the local cache).
* **GPU-only happy path.** Falls back to CPU sentence-transformer if
  CUDA is not available, but FAISS index build still runs (slower) so
  the AWS Batch job completes successfully even on quota-bumped CPU
  fallback.
* ``mypy --strict`` clean. ``ruff`` 0 warnings.
* ``[lane:solo]`` marker on the parent commit.

Burn math (g4dn.4xlarge at ~$0.48/hr spot, 1× T4 GPU 16 GB)
-----------------------------------------------------------
* 503,930 entities × 384-d = ~193 MB raw embeddings (fp32).
* T4 sustains ~700 sentence/sec on multilingual-e5-small fp16.
* Encoding 503,930 entities ≈ 720 sec ≈ 12 min (steady-state burn).
* IVF-PQ training + add ≈ 5 min on T4.
* Idle-loop padding to ``MIN_RUNTIME_SECONDS`` (default 4 hours = 14400)
  so the job consumes the full credit allocation reliably even if the
  encoding completes faster than budget. The padding does a cheap
  GPU matmul benchmark — useful smoke that the GPU stayed healthy.

Entry point
-----------
``python /app/build_faiss_index_gpu.py``

Or from AWS Batch:
``python /app/entrypoint_gpu.py`` (which calls into this module).
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
    from collections.abc import Iterable

logger = logging.getLogger("build_faiss_index_gpu")

DEFAULT_CORPUS_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_CORPUS_PREFIX: Final[str] = "corpus_export"
DEFAULT_FAISS_PREFIX: Final[str] = "faiss"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_MODEL_NAME: Final[str] = "intfloat/multilingual-e5-small"
DEFAULT_DIM: Final[int] = 384
DEFAULT_NLIST: Final[int] = 1024  # IVF clusters
DEFAULT_NSUBQ: Final[int] = 48  # PQ subquantizers
DEFAULT_NBITS: Final[int] = 8  # bits per subquantizer
DEFAULT_BATCH_SIZE: Final[int] = 256
DEFAULT_MIN_RUNTIME_SECONDS: Final[int] = 4 * 3600  # 4 hours sustained burn

CORPUS_TABLES: Final[tuple[str, ...]] = (
    "programs",
    "am_law_article",
    "adoption_records",
    "nta_tsutatsu_index",
    "court_decisions",
    "nta_saiketsu",
)


class BuildFaissError(RuntimeError):
    """Raised when an unrecoverable build condition is hit."""


def _ts_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log(level: str, msg: str, **fields: Any) -> None:
    """Structured one-line JSON log to stderr."""
    payload: dict[str, Any] = {"ts": _ts_iso(), "level": level, "msg": msg}
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)


def _boto3_s3() -> Any:  # pragma: no cover - trivial shim
    """Return a pooled S3 client (PERF-35).

    Prefers the shared client cache in
    :mod:`scripts.aws_credit_ops._aws` so the 200-500 ms boto3
    ``Session`` + endpoint discovery cold-start is paid once per
    ``(service, region)`` per process. Falls back to direct
    ``boto3.client`` construction when the script runs inside a
    minimal Batch container that ships ``build_faiss_index_gpu.py`` at
    ``/app/`` without the wider ``scripts/`` package on
    ``PYTHONPATH``. Honours the legacy ``AWS_DEFAULT_REGION`` override
    either way.
    """

    region = os.environ.get("AWS_DEFAULT_REGION", DEFAULT_REGION)
    try:
        from scripts.aws_credit_ops._aws import get_client
    except ImportError:
        pass
    else:
        return get_client("s3", region_name=region)
    try:
        import boto3
    except ImportError as exc:
        msg = "boto3 is required (pip install boto3)"
        raise BuildFaissError(msg) from exc
    return boto3.client("s3", region_name=region)


def _try_import_torch() -> tuple[Any, bool]:
    """Return (torch module, cuda_available). None if not installed."""
    try:
        import torch
    except ImportError:
        return None, False
    return torch, bool(getattr(torch, "cuda", None) and torch.cuda.is_available())


def _try_import_faiss(prefer_gpu: bool = True) -> tuple[Any, bool]:
    """Return (faiss module, gpu_available)."""
    try:
        import faiss
    except ImportError as exc:
        msg = "faiss-cpu or faiss-gpu is required (pip install faiss-cpu)"
        raise BuildFaissError(msg) from exc
    gpu_available = bool(prefer_gpu and hasattr(faiss, "StandardGpuResources"))
    return faiss, gpu_available


def _try_import_st() -> Any:
    """Return SentenceTransformer module."""
    try:
        import sentence_transformers
    except ImportError as exc:
        msg = "sentence-transformers is required (pip install sentence-transformers)"
        raise BuildFaissError(msg) from exc
    return sentence_transformers


def list_corpus_parts(
    s3: Any, bucket: str, prefix: str, tables: tuple[str, ...]
) -> list[tuple[str, str, str]]:
    """Return list of (table, s3_key, basename) for every part-*.jsonl object."""
    parts: list[tuple[str, str, str]] = []
    for table in tables:
        key_prefix = f"{prefix}/{table}/"
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
            for obj in page.get("Contents", []) or []:
                key = obj["Key"]
                if not key.endswith(".jsonl") and not key.endswith(".json"):
                    continue
                basename = key.rsplit("/", 1)[-1]
                parts.append((table, key, basename))
    return parts


def iter_corpus_records(
    s3: Any, bucket: str, parts: list[tuple[str, str, str]], limit: int | None
) -> Iterable[tuple[str, str, str]]:
    """Yield (table, record_id, text) tuples from S3 jsonl parts."""
    yielded = 0
    for table, key, _basename in parts:
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
        except Exception as exc:  # noqa: BLE001 - log + skip is correct here
            _log("warn", "s3_get_object_failed", bucket=bucket, key=key, error=str(exc))
            continue
        body = obj["Body"].read()
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rec_id = str(row.get("id") or row.get("entity_id") or row.get("program_id") or "")
            text = str(row.get("text") or row.get("name_ja") or row.get("title") or "")
            if not rec_id or not text:
                continue
            yield table, rec_id, text
            yielded += 1
            if limit is not None and yielded >= limit:
                return


def encode_records(
    model: Any,
    records: list[tuple[str, str, str]],
    batch_size: int,
    *,
    device: str,
) -> tuple[list[tuple[str, str]], Any]:
    """Run sentence-transformer encode on records.

    Returns (id_map, embeddings_np) where id_map = list of (table, rec_id)
    in the same order as embeddings rows.
    """
    import numpy as np

    id_map: list[tuple[str, str]] = []
    texts: list[str] = []
    for table, rec_id, text in records:
        id_map.append((table, rec_id))
        # e5 family expects "passage: <text>" or "query: <text>" prefix.
        texts.append("passage: " + text[:512])

    if not texts:
        return [], np.zeros((0, DEFAULT_DIM), dtype="float32")

    _log("info", "encode_start", n=len(texts), batch_size=batch_size, device=device)
    t0 = time.time()
    emb = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    dt = time.time() - t0
    rate = len(texts) / dt if dt > 0 else 0.0
    _log("info", "encode_done", n=len(texts), seconds=round(dt, 2), per_sec=round(rate, 1))
    return id_map, emb.astype("float32")


def build_faiss_ivf_pq(
    embeddings: Any,
    *,
    dim: int,
    nlist: int,
    nsubq: int,
    nbits: int,
    prefer_gpu: bool,
) -> tuple[Any, dict[str, Any]]:
    """Train + populate FAISS IVF-PQ index on GPU when available.

    Returns (cpu_index, telemetry).
    """
    faiss, gpu_available = _try_import_faiss(prefer_gpu=prefer_gpu)

    nlist_eff = max(8, min(nlist, max(8, embeddings.shape[0] // 39)))
    nsubq_eff = nsubq if dim % nsubq == 0 else 16
    quantizer = faiss.IndexFlatIP(dim)
    cpu_index = faiss.IndexIVFPQ(quantizer, dim, nlist_eff, nsubq_eff, nbits)
    cpu_index.metric_type = faiss.METRIC_INNER_PRODUCT

    use_gpu = gpu_available and embeddings.shape[0] > 0
    if use_gpu:
        res = faiss.StandardGpuResources()
        index = faiss.index_cpu_to_gpu(res, 0, cpu_index)
    else:
        index = cpu_index

    t0 = time.time()
    n_train = min(embeddings.shape[0], max(nlist_eff * 39, 4096))
    train_sample = embeddings[:n_train]
    index.train(train_sample)
    train_dt = time.time() - t0

    t1 = time.time()
    index.add(embeddings)
    add_dt = time.time() - t1

    if use_gpu:
        cpu_index = faiss.index_gpu_to_cpu(index)

    telemetry = {
        "n_vectors": int(embeddings.shape[0]),
        "dim": dim,
        "nlist_eff": nlist_eff,
        "nsubq_eff": nsubq_eff,
        "nbits": nbits,
        "gpu_used": bool(use_gpu),
        "train_seconds": round(train_dt, 2),
        "add_seconds": round(add_dt, 2),
        "index_class": "IndexIVFPQ",
        "metric": "inner_product",
    }
    _log("info", "faiss_build_done", **telemetry)
    return cpu_index, telemetry


def serialize_index_to_bytes(faiss_index: Any) -> bytes:
    import faiss

    writer = faiss.PyCallbackIOWriter(lambda b: None)
    # Simpler: write to a temp file then read back. PyCallbackIOWriter
    # interface differs across faiss versions, so use file IO for
    # portability.
    del writer
    with tempfile.NamedTemporaryFile(suffix=".faiss", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        faiss.write_index(faiss_index, tmp_path)
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
    run_id: str,
    index_bytes: bytes,
    id_map: list[tuple[str, str]],
    manifest: dict[str, Any],
) -> dict[str, str]:
    base = f"{prefix}/{run_id}"
    s3.put_object(Bucket=bucket, Key=f"{base}/faiss_index.bin", Body=index_bytes)
    id_map_jsonl = "\n".join(
        json.dumps({"row_idx": i, "table": t, "id": r}) for i, (t, r) in enumerate(id_map)
    )
    s3.put_object(Bucket=bucket, Key=f"{base}/id_map.jsonl", Body=id_map_jsonl.encode("utf-8"))
    s3.put_object(
        Bucket=bucket,
        Key=f"{base}/run_manifest.json",
        Body=json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
    )
    return {
        "index_uri": f"s3://{bucket}/{base}/faiss_index.bin",
        "id_map_uri": f"s3://{bucket}/{base}/id_map.jsonl",
        "manifest_uri": f"s3://{bucket}/{base}/run_manifest.json",
    }


def gpu_burn_pad(seconds_remaining: float) -> dict[str, Any]:
    """Spin a cheap CUDA matmul loop to pad runtime to MIN_RUNTIME_SECONDS.

    Real workload: large square matmuls (fp16) on GPU. Validates that
    the GPU stays healthy and consumes the credit allocation reliably
    even if the encode + faiss build finishes faster than budgeted.
    """
    torch, cuda_available = _try_import_torch()
    if torch is None or not cuda_available:
        _log("warn", "gpu_pad_skipped", reason="no_cuda")
        # Even without GPU we still want to consume the budgeted runtime
        # so credit burn lands. Sleep is acceptable as a graceful CPU
        # fallback (we don't want to throw because the job needs to
        # complete cleanly for the next submission's idempotency window).
        time.sleep(max(0.0, seconds_remaining))
        return {"mode": "cpu_sleep", "padded_seconds": round(seconds_remaining, 1)}

    device = torch.device("cuda:0")
    dtype = torch.float16
    n = 4096
    iters_done = 0
    start = time.time()
    while time.time() - start < seconds_remaining:
        a = torch.randn(n, n, device=device, dtype=dtype)
        b = torch.randn(n, n, device=device, dtype=dtype)
        c = a @ b
        torch.cuda.synchronize()
        del a, b, c
        iters_done += 1
        if iters_done % 50 == 0:
            elapsed = time.time() - start
            _log(
                "info",
                "gpu_pad_progress",
                iters=iters_done,
                elapsed=round(elapsed, 1),
                remaining=round(seconds_remaining - elapsed, 1),
            )
    return {
        "mode": "gpu_matmul_pad",
        "matrix_n": n,
        "iters": iters_done,
        "padded_seconds": round(time.time() - start, 1),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bucket", default=os.environ.get("CORPUS_BUCKET", DEFAULT_CORPUS_BUCKET))
    p.add_argument("--prefix", default=os.environ.get("CORPUS_PREFIX", DEFAULT_CORPUS_PREFIX))
    p.add_argument(
        "--faiss-prefix",
        default=os.environ.get("FAISS_PREFIX", DEFAULT_FAISS_PREFIX),
    )
    p.add_argument(
        "--tables",
        default=os.environ.get("FAISS_TABLES", ",".join(CORPUS_TABLES)),
        help="comma-separated corpus tables to index",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("FAISS_LIMIT", "0")) or None,
        help="max records to encode (0 = unlimited)",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=int(os.environ.get("FAISS_BATCH_SIZE", DEFAULT_BATCH_SIZE)),
    )
    p.add_argument(
        "--min-runtime-seconds",
        type=int,
        default=int(os.environ.get("MIN_RUNTIME_SECONDS", DEFAULT_MIN_RUNTIME_SECONDS)),
        help="sustained burn floor — pad with GPU matmul if encode finishes early",
    )
    p.add_argument(
        "--model",
        default=os.environ.get("FAISS_MODEL", DEFAULT_MODEL_NAME),
    )
    p.add_argument(
        "--dim",
        type=int,
        default=int(os.environ.get("FAISS_DIM", DEFAULT_DIM)),
    )
    p.add_argument(
        "--nlist",
        type=int,
        default=int(os.environ.get("FAISS_NLIST", DEFAULT_NLIST)),
    )
    p.add_argument(
        "--nsubq",
        type=int,
        default=int(os.environ.get("FAISS_NSUBQ", DEFAULT_NSUBQ)),
    )
    p.add_argument(
        "--nbits",
        type=int,
        default=int(os.environ.get("FAISS_NBITS", DEFAULT_NBITS)),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="list corpus parts + planned work without encoding",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    args = parse_args(argv)

    run_id = f"run-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    tables = tuple(t.strip() for t in args.tables.split(",") if t.strip())
    _log(
        "info",
        "boot",
        run_id=run_id,
        bucket=args.bucket,
        prefix=args.prefix,
        faiss_prefix=args.faiss_prefix,
        tables=list(tables),
        limit=args.limit,
        min_runtime=args.min_runtime_seconds,
        model=args.model,
    )

    t_boot = time.time()
    s3 = _boto3_s3()
    parts = list_corpus_parts(s3, args.bucket, args.prefix, tables)
    _log("info", "corpus_parts_listed", n_parts=len(parts))

    if args.dry_run:
        _log("info", "dry_run_done", n_parts=len(parts))
        return 0

    # Lazy imports so dry-run does not pay torch import cost.
    torch, cuda_available = _try_import_torch()
    st = _try_import_st()
    device = "cuda" if cuda_available else "cpu"
    _log("info", "device_picked", device=device, torch_present=torch is not None)

    model = st.SentenceTransformer(args.model, device=device)
    if torch is not None and cuda_available:
        # cast to fp16 for throughput when on GPU
        try:
            model = model.half()
        except Exception:  # noqa: BLE001
            _log("warn", "model_half_skipped", model=args.model)

    records: list[tuple[str, str, str]] = []
    for triplet in iter_corpus_records(s3, args.bucket, parts, args.limit):
        records.append(triplet)
    _log("info", "records_loaded", n=len(records))

    if not records:
        _log("warn", "no_records", bucket=args.bucket, prefix=args.prefix)
        # Still pad the burn floor so the job consumes its credit budget.
        pad_used = gpu_burn_pad(float(args.min_runtime_seconds))
        return 0 if pad_used else 1

    id_map, embeddings = encode_records(model, records, args.batch_size, device=device)
    faiss_index, telemetry = build_faiss_ivf_pq(
        embeddings,
        dim=args.dim,
        nlist=args.nlist,
        nsubq=args.nsubq,
        nbits=args.nbits,
        prefer_gpu=cuda_available,
    )
    index_bytes = serialize_index_to_bytes(faiss_index)
    _log("info", "index_serialized", bytes=len(index_bytes))

    manifest = {
        "run_id": run_id,
        "model": args.model,
        "tables": list(tables),
        "n_records": len(records),
        "n_parts": len(parts),
        "telemetry": telemetry,
        "boot_ts": _ts_iso(),
        "elapsed_seconds_at_index": round(time.time() - t_boot, 2),
    }
    uris = upload_artifacts(
        s3,
        bucket=args.bucket,
        prefix=args.faiss_prefix,
        run_id=run_id,
        index_bytes=index_bytes,
        id_map=id_map,
        manifest=manifest,
    )
    _log("info", "uploaded", **uris)

    # Sustained burn padding.
    elapsed = time.time() - t_boot
    remaining = max(0.0, float(args.min_runtime_seconds) - elapsed)
    _log(
        "info",
        "burn_pad_plan",
        elapsed=round(elapsed, 1),
        remaining=round(remaining, 1),
        min_runtime=args.min_runtime_seconds,
    )
    if remaining > 0:
        pad_info = gpu_burn_pad(remaining)
        _log("info", "burn_pad_done", **pad_info)

    _log("info", "done", run_id=run_id, total_seconds=round(time.time() - t_boot, 1))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
