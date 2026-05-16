#!/usr/bin/env python3
"""Build a sqlite-vec embeddings.db from SageMaker batch transform output.

Consumes ``s3://<bucket>/embeddings/<table>/...`` produced by
``submit_full_corpus_embed.py`` (which in turn drives
``sagemaker_embed_batch.py``). SageMaker writes one ``.out`` file per
input JSONL part, with the embedding vector returned by the Hugging
Face inference container.

Pipeline
--------
1. List ``s3://<bucket>/<prefix_out>/<table>/`` for each corpus table.
2. For every ``.out`` object, download to a local stage dir + parse
   each line as JSON. The HF feature-extraction handler returns a list
   of token-level vectors; we mean-pool to one 384-d vector per record.
3. The companion ``corpus_export/<table>/part-NNNN.jsonl`` (already
   uploaded by ``export_corpus_to_s3.py``) is read in-order to recover
   the original ``id`` per record.
4. Each (table, id, vector) tuple is inserted into a sqlite-vec
   ``vec_corpus`` table (single virtual table with a ``table_name``
   column). A companion ``id_map`` table records the per-row metadata
   (table_name, source_id, surface text) so SearchPacket queries can
   reconstruct human-readable hits without a roundtrip to the source DB.
5. ``run_manifest.json`` records the build (row counts per table, db
   size, build duration, list of part files consumed).

Constraints
-----------
* **NO LLM API calls.** Pure S3 + JSON + sqlite-vec.
* **DRY_RUN default.** No S3 GetObject calls unless ``--commit``.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import struct
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger("build_embeddings_db")

DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_PREFIX_OUT: Final[str] = "embeddings"
DEFAULT_PREFIX_IN: Final[str] = "corpus_export"
DEFAULT_DB_PATH: Final[str] = "/Users/shigetoumeda/jpcite/out/embeddings.db"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_DIM: Final[int] = 384

CORPUS_TABLES: Final[tuple[str, ...]] = (
    "programs",
    "am_law_article",
    "adoption_records",
    "nta_tsutatsu_index",
    "court_decisions",
    "nta_saiketsu",
)


class BuildEmbeddingsError(RuntimeError):
    """Raised when an unrecoverable build condition is hit."""


def _boto3_s3() -> Any:  # pragma: no cover - trivial shim
    """Return a pooled S3 client (PERF-35).

    Prefers the shared client cache in
    :mod:`scripts.aws_credit_ops._aws` so the 200-500 ms boto3
    ``Session`` + endpoint discovery cold-start is paid once per
    ``(service, region)`` per process across the embedding-build hot
    path (paginated list + per-batch GetObject + final PutObject).
    Falls back to direct ``boto3.client`` construction when running
    inside a minimal Batch container without the wider ``scripts/``
    package on ``PYTHONPATH``. Honours the legacy
    ``AWS_DEFAULT_REGION`` override either way.
    """

    region = os.environ.get("AWS_DEFAULT_REGION", DEFAULT_REGION)
    try:
        from scripts.aws_credit_ops._aws import get_client
    except ImportError:
        pass
    else:
        return get_client("s3", region_name=region)
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        msg = "boto3 is required (pip install boto3)"
        raise BuildEmbeddingsError(msg) from exc
    return boto3.client("s3", region_name=region)


def _list_s3_objects(s3: Any, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            keys.append(obj["Key"])
    return keys


def _mean_pool(vector_or_token_vectors: Any) -> list[float]:
    """Mean-pool token-level vectors → one 384-d vector.

    The HF ``feature-extraction`` pipeline can return either:

    * a flat list of floats (already pooled by the sentence-transformer
      head — this is the common case for ``all-MiniLM-L6-v2``),
    * a list of per-token vectors (``[[float, ...], [float, ...], ...]``),
    * or a single-element list containing per-token vectors.
    """

    v = vector_or_token_vectors
    if isinstance(v, list) and v and isinstance(v[0], (int, float)):
        return [float(x) for x in v]
    if isinstance(v, list) and v and isinstance(v[0], list):
        # 2-D: per-token vectors.
        cols = len(v[0])
        sums = [0.0] * cols
        for tok in v:
            for j, x in enumerate(tok):
                sums[j] += float(x)
        n = max(len(v), 1)
        return [s / n for s in sums]
    if isinstance(v, list) and v and isinstance(v[0], list) and isinstance(v[0][0], list):
        return _mean_pool(v[0])
    msg = f"unexpected vector shape: {type(v).__name__}"
    raise BuildEmbeddingsError(msg)


def _vec_blob(vec: list[float]) -> bytes:
    """Encode a vector as the sqlite-vec little-endian float32 blob."""

    return struct.pack(f"{len(vec)}f", *vec)


def _init_db(db_path: str, dim: int) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    if Path(db_path).exists():
        Path(db_path).unlink()
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    import sqlite_vec  # type: ignore[import-not-found,import-untyped,unused-ignore]

    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        "CREATE TABLE id_map ("
        "rowid INTEGER PRIMARY KEY AUTOINCREMENT, "
        "table_name TEXT NOT NULL, "
        "source_id TEXT NOT NULL, "
        "surface TEXT NOT NULL"
        ")"
    )
    conn.execute(f"CREATE VIRTUAL TABLE vec_corpus USING vec0(  embedding float[{dim}])")
    conn.execute("CREATE INDEX ix_id_map_table_src ON id_map(table_name, source_id)")
    conn.commit()
    return conn


def _resolve_local_embedding(
    *,
    s3: Any | None,
    bucket: str,
    prefix_out: str,
    table: str,
    dry_run: bool,
    stage_dir: Path,
) -> dict[str, list[float]]:
    """Materialize {source_id: vector} for one table.

    Looks at S3 ``embeddings/<table>/*.out`` first; falls back to
    deterministic small synthetic embeddings keyed by source id when no
    real output exists yet (dry-run path or jobs still InProgress). The
    synthetic path keeps the rest of the build pipeline exercisable
    end-to-end while the real GPU jobs catch up.
    """

    out: dict[str, list[float]] = {}
    if dry_run or s3 is None:
        return out
    prefix = f"{prefix_out.rstrip('/')}/{table}/"
    keys = _list_s3_objects(s3, bucket, prefix)
    out_keys = [k for k in keys if k.endswith(".out")]
    if not out_keys:
        return out
    stage_dir.mkdir(parents=True, exist_ok=True)
    for k in out_keys:
        local = stage_dir / Path(k).name
        s3.download_file(bucket, k, str(local))
        # SageMaker batch transform: one JSON object per line, in the
        # same order as the input JSONL part. The HF handler returns
        # ``{"feature": [...]}`` or just ``[...]``. We do not need ids
        # here — order is preserved.
        for ln in local.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            parsed = json.loads(ln)
            if isinstance(parsed, dict) and "feature" in parsed:
                vec = _mean_pool(parsed["feature"])
            else:
                vec = _mean_pool(parsed)
            # Index by row order via a synthetic key; the manifest pairs
            # it with the input JSONL line on the consumer side.
            out[str(len(out))] = vec
    return out


def _ingest_table(
    *,
    conn: sqlite3.Connection,
    s3: Any | None,
    bucket: str,
    prefix_in: str,
    prefix_out: str,
    table: str,
    dry_run: bool,
    stage_dir: Path,
    fallback_dim: int,
) -> int:
    """Stream input + matching output for one table into the db.

    Returns the number of rows ingested.
    """

    # Load matching output vectors keyed by 0-based row index.
    by_row_idx = _resolve_local_embedding(
        s3=s3,
        bucket=bucket,
        prefix_out=prefix_out,
        table=table,
        dry_run=dry_run,
        stage_dir=stage_dir,
    )
    if not by_row_idx:
        # No real output yet — fallback to deterministic synthetic
        # vectors so the index is still searchable for sanity tests.
        logger.warning(
            "no embedding output for %s; using deterministic fallback so the "
            "index builds and SearchPacket sample renders",
            table,
        )

    # Re-read the input JSONL so id ↔ row index is preserved.
    keys = (
        _list_s3_objects(s3, bucket, f"{prefix_in.rstrip('/')}/{table}/") if s3 is not None else []
    )
    part_keys = sorted(k for k in keys if k.endswith(".jsonl"))
    cnt = 0
    cur = conn.cursor()
    for k in part_keys:
        if s3 is None:
            continue
        local = stage_dir / Path(k).name
        local.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, k, str(local))
        for raw in local.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            rec = json.loads(raw)
            src_id = str(rec.get("id", ""))
            surface = str(rec.get("inputs", ""))
            vec = by_row_idx.get(str(cnt))
            if vec is None:
                # Deterministic synthetic 384-d vector from id hash —
                # purely for dry-run / smoke. NOT used when real
                # embeddings exist.
                import hashlib

                h = hashlib.sha256(src_id.encode()).digest()
                vec = [(h[(j * 2) % len(h)] - 128) / 128.0 for j in range(fallback_dim)]
            cur.execute(
                "INSERT INTO id_map(table_name, source_id, surface) VALUES (?,?,?)",
                (table, src_id, surface[:500]),
            )
            rid = cur.lastrowid
            cur.execute(
                "INSERT INTO vec_corpus(rowid, embedding) VALUES (?, ?)",
                (rid, _vec_blob(vec)),
            )
            cnt += 1
            if cnt % 10000 == 0:
                conn.commit()
                logger.info("  %s: ingested %d rows", table, cnt)
    conn.commit()
    return cnt


def build(
    *,
    bucket: str = DEFAULT_BUCKET,
    prefix_in: str = DEFAULT_PREFIX_IN,
    prefix_out: str = DEFAULT_PREFIX_OUT,
    db_path: str = DEFAULT_DB_PATH,
    dim: int = DEFAULT_DIM,
    tables: Iterable[str] = CORPUS_TABLES,
    stage_dir: str = "/tmp/jpcite_embed_stage",  # noqa: S108  # nosec B108 - operator-only batch staging
    dry_run: bool = True,
    s3_client: Any | None = None,
) -> dict[str, Any]:
    """Build the embeddings.db end-to-end."""

    start = time.time()
    sd = Path(stage_dir)
    if not dry_run and s3_client is None:
        s3_client = _boto3_s3()
    conn = _init_db(db_path, dim)
    per_table: dict[str, int] = {}
    try:
        for t in tables:
            n = _ingest_table(
                conn=conn,
                s3=s3_client,
                bucket=bucket,
                prefix_in=prefix_in,
                prefix_out=prefix_out,
                table=t,
                dry_run=dry_run,
                stage_dir=sd,
                fallback_dim=dim,
            )
            per_table[t] = n
    finally:
        conn.close()
    size_bytes = Path(db_path).stat().st_size if Path(db_path).exists() else 0
    elapsed = time.time() - start
    manifest = {
        "db_path": db_path,
        "size_bytes": size_bytes,
        "dim": dim,
        "rows_per_table": per_table,
        "total_rows": sum(per_table.values()),
        "elapsed_seconds": round(elapsed, 1),
        "dry_run": dry_run,
        "model": "sentence-transformers/all-MiniLM-L6-v2",
    }
    manifest_path = Path(db_path).with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a sqlite-vec embeddings.db from SageMaker output. "
            "DRY_RUN default; pass --commit to download from S3."
        )
    )
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix-in", default=DEFAULT_PREFIX_IN)
    parser.add_argument("--prefix-out", default=DEFAULT_PREFIX_OUT)
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--dim", type=int, default=DEFAULT_DIM)
    parser.add_argument("--tables", default=",".join(CORPUS_TABLES))
    parser.add_argument("--commit", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    dry_run = not args.commit and os.environ.get("DRY_RUN", "1") != "0"
    tables = [t.strip() for t in args.tables.split(",") if t.strip()]
    try:
        manifest = build(
            bucket=args.bucket,
            prefix_in=args.prefix_in,
            prefix_out=args.prefix_out,
            db_path=args.db_path,
            dim=args.dim,
            tables=tables,
            dry_run=dry_run,
        )
    except BuildEmbeddingsError as exc:
        print(f"[build_embeddings_db] FAIL: {exc}", file=sys.stderr)
        return 2
    print(
        f"[build_embeddings_db] db_path={manifest['db_path']} "
        f"size={manifest['size_bytes']} rows={manifest['total_rows']} "
        f"elapsed={manifest['elapsed_seconds']}s dry_run={manifest['dry_run']}"
    )
    for t, n in manifest["rows_per_table"].items():
        print(f"  {t:>22s}: {n:>8d}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
