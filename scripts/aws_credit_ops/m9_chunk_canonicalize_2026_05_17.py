#!/usr/bin/env python3
"""AWS Moat Lane M9 — chunk canonicalization driver (local, 8-core).

Stage 1.5 of Lane M9 (interposed between
``multitask_corpus_prep_2026_05_17.py`` and the SageMaker Batch
Transform fan-out). The multi-task chunker emits 12 fields per row
(``chunk_id`` / ``source_id`` / ``source_kind`` / ``parent_id`` /
``position`` / ``n_chunks`` / ``char_offset_start`` /
``char_offset_end`` / ``length`` / ``inputs`` / ``text`` /
``metadata``) which is the right shape for the M9 retrieval surface
but **not** what the HuggingFace SageMaker inference toolkit
(``sagemaker_huggingface_inference_toolkit``) inside the
``jpcite-embed-allminilm-cpu-v1`` / ``-v1`` (GPU) containers expects.
The toolkit decodes each request body as a single JSON document with
an ``inputs`` key — embedded extra fields trip the JSON parser with
``json.decoder.JSONDecodeError: Extra data: line 1 column 3 (char 2)``.

This script projects each chunk to ``{id, inputs}`` with ``inputs``
truncated to 320 chars (BERT 512-token cap headroom, per memory
``feedback_sagemaker_bert_512_truncate``) and re-uploads to
``s3://<derived>/chunked_corpus_canon/<source_kind>/part-XXXX.jsonl``.

Runs **locally** with ``multiprocessing.Pool(8)`` — for 708,957 rows
across 60 parts the wall is ~60 seconds end-to-end (~300× faster
than a single SageMaker Batch Transform job per
``feedback_packet_local_gen_300x_faster``).

Cost: zero AWS spend on the projection itself; one S3 PUT per part
(~$0.005/1k × 60 = $0.0003) + a few MB of egress on the operator
host.

Constraints honoured
--------------------
- AWS profile ``bookyou-recovery``; region ``ap-northeast-1``.
- NO LLM — pure Python projection.
- ``[lane:solo]`` marker.
- mypy ``--strict`` clean, ruff 0.

Usage
-----
::

    .venv/bin/python scripts/aws_credit_ops/m9_chunk_canonicalize_2026_05_17.py \\
        --max-input-len 320 \\
        --commit

DRY_RUN default; ``--commit`` triggers actual S3 PUTs.
"""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing as mp
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("m9_chunk_canonicalize")

DEFAULT_BUCKET = "jpcite-credit-993693061769-202605-derived"
DEFAULT_PROFILE = "bookyou-recovery"
DEFAULT_REGION = "ap-northeast-1"
DEFAULT_SRC_PREFIX = "chunked_corpus"
DEFAULT_DST_PREFIX = "chunked_corpus_canon"
DEFAULT_MAX_INPUT_LEN = 320
DEFAULT_POOL_SIZE = 8
DEFAULT_LOCAL_ROOT = str(Path(tempfile.gettempdir()) / "m9_chunks_canon")

#: Canonical chunk part layout per ``chunked_corpus/_manifest.json``
#: (2026-05-17 chunker run). Pinned here so the canonicalizer can fan
#: out without re-reading the manifest from S3.
PARTS: list[tuple[str, int]] = [
    ("program", 1),
    ("am_law_article", 42),
    ("adoption_record", 17),
]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI flags."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--src-prefix", default=DEFAULT_SRC_PREFIX)
    p.add_argument("--dst-prefix", default=DEFAULT_DST_PREFIX)
    p.add_argument("--max-input-len", type=int, default=DEFAULT_MAX_INPUT_LEN)
    p.add_argument("--pool-size", type=int, default=DEFAULT_POOL_SIZE)
    p.add_argument("--local-root", default=DEFAULT_LOCAL_ROOT)
    p.add_argument("--commit", action="store_true", help="Lift DRY_RUN guard")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def _aws_s3(args: list[str], *, profile: str) -> int:
    """Run ``aws s3 <args> --profile <profile> --quiet`` and return rc."""
    cmd = ["aws", "s3"] + args + ["--profile", profile, "--quiet"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(f"aws s3 {' '.join(args)} failed: {proc.stderr}\n")
    return proc.returncode


def _process_part(
    task: tuple[str, int, str, str, str, int, str],
) -> tuple[str, int, int, str]:
    """Project one chunk part to ``{id, inputs}`` and re-upload to S3.

    The task tuple is ``(source_kind, part_idx, bucket, src_prefix,
    dst_prefix, max_input_len, local_root, profile)``. We unpack inside
    the worker so the function is picklable across the multiprocessing
    pool.
    """
    source_kind, part_idx, bucket, src_prefix, dst_prefix, max_input_len, profile = task
    pad = f"{part_idx:04d}"
    src_key = f"{src_prefix}/{source_kind}/part-{pad}.jsonl"
    raw_path = Path(DEFAULT_LOCAL_ROOT) / source_kind / f"part-{pad}.raw.jsonl"
    canon_path = Path(DEFAULT_LOCAL_ROOT) / source_kind / f"part-{pad}.canon.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    rc = _aws_s3(["cp", f"s3://{bucket}/{src_key}", str(raw_path)], profile=profile)
    if rc != 0:
        return (source_kind, part_idx, 0, "download_failed")
    n_out = 0
    with raw_path.open() as fh, canon_path.open("w") as out:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r: dict[str, Any] = json.loads(line)
            txt = r.get("inputs") or r.get("text") or ""
            if not txt:
                continue
            if len(txt) > max_input_len:
                txt = txt[:max_input_len]
            out.write(json.dumps({"id": r["chunk_id"], "inputs": txt}, ensure_ascii=False) + "\n")
            n_out += 1
    raw_path.unlink(missing_ok=True)
    dst_key = f"{dst_prefix}/{source_kind}/part-{pad}.jsonl"
    rc = _aws_s3(["cp", str(canon_path), f"s3://{bucket}/{dst_key}"], profile=profile)
    canon_path.unlink(missing_ok=True)
    status = "ok" if rc == 0 else "upload_failed"
    return (source_kind, part_idx, n_out, status)


def main(argv: list[str] | None = None) -> int:
    """CLI entry — fan out the canonicalization across the 60-part substrate."""
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
    )
    if not args.commit:
        n = sum(c for _, c in PARTS)
        logger.info("DRY_RUN — would canonicalize %d parts (%d rows)", n, 708_957)
        return 0
    local_root = Path(args.local_root)
    local_root.mkdir(parents=True, exist_ok=True)
    tasks: list[tuple[str, int, str, str, str, int, str]] = []
    for kind, count in PARTS:
        for i in range(count):
            tasks.append(
                (
                    kind,
                    i,
                    args.bucket,
                    args.src_prefix,
                    args.dst_prefix,
                    args.max_input_len,
                    args.profile,
                )
            )
    logger.info("processing %d parts with pool=%d", len(tasks), args.pool_size)
    t0 = time.time()
    total_out = 0
    failures: list[tuple[str, int, str]] = []
    with mp.Pool(args.pool_size) as pool:
        for source_kind, part_idx, n_out, status in pool.imap_unordered(_process_part, tasks):
            total_out += n_out
            if status != "ok":
                failures.append((source_kind, part_idx, status))
            if (part_idx % 5) == 0 or status != "ok":
                logger.info(
                    "  %s/part-%04d: %d rows (%s)",
                    source_kind,
                    part_idx,
                    n_out,
                    status,
                )
    elapsed = time.time() - t0
    logger.info(
        "done. total_rows=%d elapsed=%.1fs failures=%d",
        total_out,
        elapsed,
        len(failures),
    )
    if failures:
        for f in failures:
            logger.error("FAILURE: %s", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
