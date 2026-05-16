#!/usr/bin/env python3
"""Expand FAISS v1 into v2 by embedding 4 missing source families locally.

FAISS v1 (commit 961b4b4c7) holds 57,979 vectors from 3 families
(``nta_saiketsu`` + ``invoice_registrants`` + ``adoption_records``)
built from SageMaker batch transform outputs. SageMaker PM5 jobs for
``am_law_article`` / ``programs`` / ``court_decisions`` /
``nta_tsutatsu_index`` failed (model container errors, no ``part-*.out``
files), so this script embeds those four families **locally** with the
same model (``sentence-transformers/all-MiniLM-L6-v2``, 384-d) and
rebuilds a fresh IVF+PQ index that includes the v1 cohort plus the new
families.

V1 vectors are reconstructed from the existing ``IndexIVFPQ`` via
``index.reconstruct_n`` — this returns the PQ-decoded approximation
(lossy, by design of v1), and the v2 manifest records this honestly so
downstream consumers know the v1 cohort vectors are approximations
while the four new families carry freshly-encoded float32 values.

Constraints
-----------
* NO LLM — only sentence-transformers (a transformer encoder) +
  FAISS (k-means + PQ). No Anthropic / OpenAI / Gemini call.
* ``bookyou-recovery`` AWS profile, region ``ap-northeast-1``.
* ``mypy --strict`` clean. ``ruff`` 0 warnings.
* ``[lane:solo]`` marker on the parent commit.
* HONEST counts: refuses to silently inflate; v2 manifest writes the
  per-family vector counts plus a ``v1_vectors_are_pq_reconstructed``
  flag.
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from typing import TYPE_CHECKING, Any, Final, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("build_faiss_v2_expand")

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_CORPUS_PREFIX: Final[str] = "corpus_export"
DEFAULT_INDEX_V1_PREFIX: Final[str] = "faiss_indexes/v1"
DEFAULT_INDEX_V2_PREFIX: Final[str] = "faiss_indexes/v2"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"
DEFAULT_DIM: Final[int] = 384
DEFAULT_NLIST: Final[int] = 256
DEFAULT_NSUBQ: Final[int] = 48
DEFAULT_NBITS: Final[int] = 8
DEFAULT_TRAIN_SAMPLE: Final[int] = 100_000
DEFAULT_BATCH_SIZE: Final[int] = 128
DEFAULT_MODEL: Final[str] = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_CACHE_DIR: Final[str] = "/tmp/faiss_v2_cache"  # nosec B108 — ephemeral local-dev cache, not a security boundary
NEW_FAMILIES: Final[tuple[str, ...]] = (
    "am_law_article",
    "programs",
    "court_decisions",
    "nta_tsutatsu_index",
)


class BuildFaissError(RuntimeError):
    """Raised when the v2 expand build cannot proceed."""


def _ts_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log(level: str, msg: str, **fields: Any) -> None:
    payload: dict[str, Any] = {"ts": _ts_iso(), "level": level, "msg": msg}
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)


def _boto3_s3(profile: str, region: str) -> Any:  # pragma: no cover - I/O shim
    try:
        import boto3
    except ImportError as exc:
        msg = "boto3 is required (pip install boto3)"
        raise BuildFaissError(msg) from exc
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("s3")


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


def list_corpus_parts(s3: Any, bucket: str, prefix: str, family: str) -> list[str]:
    out: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    key_prefix = f"{prefix}/{family}/"
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        for obj in page.get("Contents", []) or []:
            key = str(obj["Key"])
            if key.endswith(".jsonl"):
                out.append(key)
    return sorted(out)


def iter_corpus_records(local_path: str) -> Iterator[tuple[str, str]]:
    """Yield (id, text) tuples from a corpus part file.

    Corpus rows follow ``{"id": "...", "inputs": "..."}``. Rows missing
    either field are skipped (honest count: not all rows survive).
    """
    open_fn = gzip.open if local_path.endswith(".gz") else open
    with open_fn(local_path, mode="rt", encoding="utf-8") as fh:
        for line in fh:
            line_s = line.strip()
            if not line_s:
                continue
            try:
                obj = json.loads(line_s)
            except json.JSONDecodeError:
                continue
            rec_id = obj.get("id")
            text = obj.get("inputs") or obj.get("text")
            if rec_id is None or text is None:
                continue
            yield (str(rec_id), str(text))


def encode_family(
    s3: Any,
    *,
    bucket: str,
    corpus_prefix: str,
    family: str,
    cache_dir: str,
    model: Any,
    batch_size: int,
    dim: int,
    max_rows: int | None,
) -> tuple[list[str], Any]:
    """Stream a corpus family from S3 + encode locally.

    Returns (id_list, embedding_matrix). The matrix is a float32 array
    of shape (N, dim) already L2-normalized.
    """
    import numpy as np

    keys = list_corpus_parts(s3, bucket, corpus_prefix, family)
    if not keys:
        _log("warn", "family_no_parts", family=family)
        return [], np.zeros((0, dim), dtype="float32")

    local_parts: list[str] = []
    for key in keys:
        local = os.path.join(cache_dir, key)
        download_to_local(s3, bucket, key, local)
        local_parts.append(local)

    # First pass: count + collect (id, text). We hold IDs in memory but
    # encode in streaming batches to bound peak RSS.
    ids: list[str] = []
    texts: list[str] = []
    for path in local_parts:
        for rec_id, text in iter_corpus_records(path):
            ids.append(rec_id)
            texts.append(text)
            if max_rows is not None and len(ids) >= max_rows:
                break
        if max_rows is not None and len(ids) >= max_rows:
            break

    n = len(ids)
    if n == 0:
        return [], np.zeros((0, dim), dtype="float32")

    _log("info", "family_encode_start", family=family, n_rows=n, batch=batch_size)
    out = np.zeros((n, dim), dtype="float32")
    t0 = time.time()
    for start in range(0, n, batch_size):
        end = min(start + batch_size, n)
        chunk = texts[start:end]
        emb = model.encode(
            chunk,
            batch_size=len(chunk),
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        out[start:end] = emb.astype("float32", copy=False)
        if start % (batch_size * 50) == 0:
            done_pct = round(end / n * 100.0, 2)
            _log(
                "info",
                "family_encode_progress",
                family=family,
                done=end,
                total=n,
                pct=done_pct,
                elapsed_seconds=round(time.time() - t0, 1),
            )
    enc_dt = round(time.time() - t0, 2)
    _log("info", "family_encode_done", family=family, n=n, seconds=enc_dt)
    return ids, out


def reconstruct_v1_vectors(local_index_path: str) -> tuple[Any, int]:
    """Decode v1 IVF+PQ vectors back to float32 approximations.

    The v1 index uses ``IndexIVFPQ`` (lossy). ``reconstruct_n`` decodes
    the PQ codes into approximate vectors — they are *not* the original
    SageMaker-emitted floats, but they round-trip through the same FAISS
    quantizer and so retain the same retrieval behaviour the v1 index
    exposed in production.
    """
    import faiss
    import numpy as np

    index = faiss.read_index(local_index_path)
    ntotal = int(index.ntotal)
    dim = int(index.d)
    if ntotal == 0:
        return np.zeros((0, dim), dtype="float32"), 0
    # reconstruct_n needs a direct map for IVF; build one if missing.
    # IndexIVF subclasses have make_direct_map; non-IVF indexes do not
    # need it.
    with contextlib.suppress(AttributeError, RuntimeError):
        index.make_direct_map()
    out = np.zeros((ntotal, dim), dtype="float32")
    index.reconstruct_n(0, ntotal, out)
    # L2-normalize again because PQ decode can drift slightly.
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    out /= norms
    return out, ntotal


def load_v1_meta(local_meta_path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with open(local_meta_path, encoding="utf-8") as fh:
        for line in fh:
            line_s = line.strip()
            if not line_s:
                continue
            try:
                out.append(json.loads(line_s))
            except json.JSONDecodeError:
                continue
    return out


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

    _log("info", "faiss_v2_train_start", n_total=n, n_train=int(n_train), nlist=nlist_eff)
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
    # PERF-40 (2026-05-17): nprobe baked into the serialized v2 IVF+PQ index.
    # The previous heuristic was nprobe = min(nlist, max(32, nlist // 2))
    # which gave nprobe=128 for nlist=256 — measurably 4.3x over-probed.
    # Sweep on 74,812 vectors / 200 queries / k=10 showed recall@10 plateaus
    # at 0.5205 from nprobe=4 onward (PQ codebook is the recall floor, not
    # the inverted-list walk), while p95 grows linearly with nprobe.
    # nprobe=8 is the sweet spot: same 0.5205 recall, p95 ≈ 0.17ms (vs 0.73ms
    # at nprobe=128). Doc: docs/_internal/PERF_40_FAISS_NPROBE_PROPOSAL.md.
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
    p.add_argument("--corpus-prefix", default=DEFAULT_CORPUS_PREFIX)
    p.add_argument("--v1-prefix", default=DEFAULT_INDEX_V1_PREFIX)
    p.add_argument("--v2-prefix", default=DEFAULT_INDEX_V2_PREFIX)
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE", DEFAULT_PROFILE))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    p.add_argument(
        "--families",
        default=",".join(NEW_FAMILIES),
        help="Comma-separated new families to embed locally.",
    )
    p.add_argument("--dim", type=int, default=DEFAULT_DIM)
    p.add_argument("--nlist", type=int, default=DEFAULT_NLIST)
    p.add_argument("--nsubq", type=int, default=DEFAULT_NSUBQ)
    p.add_argument("--nbits", type=int, default=DEFAULT_NBITS)
    p.add_argument("--train-sample", type=int, default=DEFAULT_TRAIN_SAMPLE)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    p.add_argument(
        "--max-rows-per-family",
        type=int,
        default=None,
        help="Cap rows per family (debug). None = full corpus.",
    )
    p.add_argument("--smoke-queries", type=int, default=5)
    p.add_argument("--smoke-k", type=int, default=10)
    p.add_argument("--no-upload", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - end-to-end orchestration
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    args = parse_args(argv)

    run_id = f"v2-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    families = tuple(t.strip() for t in args.families.split(",") if t.strip())
    _log(
        "info",
        "boot",
        run_id=run_id,
        bucket=args.bucket,
        families=list(families),
        model=args.model,
        dim=args.dim,
    )

    s3 = _boto3_s3(args.profile, args.region)

    import numpy as np
    from sentence_transformers import SentenceTransformer

    # 1. Pull v1 artifacts.
    os.makedirs(args.cache_dir, exist_ok=True)
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

    # 2. Encode new families locally.
    _log("info", "model_load_start", model=args.model)
    t_model = time.time()
    encoder = SentenceTransformer(args.model)
    _log("info", "model_load_done", seconds=round(time.time() - t_model, 2))

    family_vecs: dict[str, Any] = {}
    family_ids: dict[str, list[str]] = {}
    per_family_seconds: dict[str, float] = {}
    for family in families:
        t_fam = time.time()
        # Disk-cache per family so a downstream crash does not waste the
        # 22-minute encode on am_law_article.
        vec_cache = os.path.join(args.cache_dir, f"encoded_{family}.float32.npy")
        id_cache = os.path.join(args.cache_dir, f"encoded_{family}.ids.txt")
        if os.path.exists(vec_cache) and os.path.exists(id_cache):
            mat = np.load(vec_cache)
            with open(id_cache, encoding="utf-8") as fh:
                ids = [line.rstrip("\n") for line in fh if line.strip()]
            _log(
                "info",
                "family_cache_hit",
                family=family,
                n=int(mat.shape[0]),
                vec_cache=vec_cache,
            )
        else:
            ids, mat = encode_family(
                s3,
                bucket=args.bucket,
                corpus_prefix=args.corpus_prefix,
                family=family,
                cache_dir=args.cache_dir,
                model=encoder,
                batch_size=args.batch_size,
                dim=args.dim,
                max_rows=args.max_rows_per_family,
            )
            np.save(vec_cache, mat)
            with open(id_cache, "w", encoding="utf-8") as fh:
                for pid in ids:
                    fh.write(pid + "\n")
            _log(
                "info",
                "family_cache_write",
                family=family,
                n=int(mat.shape[0]),
                vec_cache=vec_cache,
            )
        family_vecs[family] = mat
        family_ids[family] = ids
        per_family_seconds[family] = round(time.time() - t_fam, 2)

    # 3. Stack everything into a single (N, dim) matrix.
    pieces: list[Any] = [v1_vecs]
    pieces.extend(family_vecs[f] for f in families if family_vecs[f].shape[0] > 0)
    if not any(p.shape[0] for p in pieces):
        msg = "no vectors to index (v1 empty AND new families empty)"
        raise BuildFaissError(msg)
    combined = np.ascontiguousarray(np.concatenate(pieces, axis=0).astype("float32", copy=False))
    # Sanitize: replace NaN/Inf with 0 (they can crash FAISS k-means
    # segfault). Re-normalize rows so the inner-product metric stays
    # meaningful.
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

    # Persist the combined matrix to disk before training so a FAISS
    # crash does not throw away the 22-minute encode.
    combined_dump = os.path.join(args.cache_dir, "combined.float32.npy")
    np.save(combined_dump, combined)
    _log("info", "combined_dump", path=combined_dump, bytes=combined.nbytes)

    # 4. Build the v2 index.
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

    # 6. Serialize + write meta jsonl preserving order.
    index_bytes = serialize_index(index)
    _log("info", "index_serialized", bytes=len(index_bytes))

    meta_lines: list[str] = []
    row_i = 0
    # v1 rows first, preserving v1 meta order.
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
    # Then each new family in declared order.
    for family in families:
        for pid in family_ids[family]:
            meta_lines.append(
                json.dumps(
                    {
                        "row": row_i,
                        "table": family,
                        "packet_id": pid,
                        "source": "v2_local_encoded",
                    }
                )
            )
            row_i += 1
    meta_jsonl = "\n".join(meta_lines)

    by_family_counts: dict[str, int] = {
        family: int(family_vecs[family].shape[0]) for family in families
    }
    v1_table_breakdown: dict[str, int] = {}
    for entry in v1_meta_rows:
        tbl = str(entry.get("table", "unknown"))
        v1_table_breakdown[tbl] = v1_table_breakdown.get(tbl, 0) + 1

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "build_kind": "faiss_ivf_pq_v2_expand",
        "embedding_model": args.model,
        "embedding_dim": args.dim,
        "v1_source_prefix": f"s3://{args.bucket}/{args.v1_prefix}/",
        "v1_vectors_are_pq_reconstructed": True,
        "v1_vector_count": v1_ntotal,
        "v1_table_breakdown": v1_table_breakdown,
        "new_families": list(families),
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
            "SageMaker PM5 jobs for the 4 new families FAILED (model"
            " container errors). Embeddings produced locally with"
            " sentence-transformers/all-MiniLM-L6-v2.",
            "v1 vectors recovered via IndexIVFPQ.reconstruct_n — these"
            " are PQ-decoded approximations, not the original SageMaker"
            " float32 emissions.",
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
            recall=cast("float", smoke["recall_at_k"]),
            threshold=recall_threshold,
        )
    _log("info", "done", run_id=run_id, **uris)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
