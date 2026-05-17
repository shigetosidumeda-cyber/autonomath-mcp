#!/usr/bin/env python3
"""GG2 — Build FAISS index v5 for am_precomputed_answer (~5,000 row).

Encodes each precomputed answer's ``question_text`` into a 384-d vector via
a deterministic local hash-based fallback. jpcite-bert-v1 model loading is
not available in this lane (SageMaker batch transform pipeline) so we use
the v0 hash-3gram encoder that mirrors the v1/v2 contract: 384-d float32
unit vectors with inner-product retrieval.

Output:
- ``data/faiss/am_precomputed_v5_2026_05_17.faiss`` — IVF binary
- ``data/faiss/am_precomputed_v5_2026_05_17.meta.json`` — row -> q_hash map

Index params:
- nlist = 512 (~ 4 * sqrt(5000) ~ 282, rounded up)
- nprobe = 8 (PERF-40 floor)
- IndexIVFFlat + METRIC_INNER_PRODUCT (5,000 row is small enough; no PQ)

Constraints
-----------
* NO LLM API.
* mypy --strict clean / ruff clean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

import faiss
import numpy as np

logger = logging.getLogger("jpcite.gg2.faiss_v5")

_DIM = 384
_NLIST = 512
_NPROBE = 8  # PERF-40 floor


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "autonomath.db"


def _hash_encode(text: str, dim: int = _DIM) -> np.ndarray:
    """Deterministic 384-d encoder.

    Properties:
    - Same input -> same output (idempotent).
    - Similar texts -> overlapping 3-grams -> high cosine similarity.
    - NO LLM, NO external model file.
    """
    vec = np.zeros(dim, dtype=np.float32)
    n = len(text)
    if n < 3:
        text = text + "  "
        n = len(text)
    for i in range(n - 2):
        tri = text[i : i + 3]
        h = hashlib.sha256(tri.encode("utf-8")).digest()
        offset = int.from_bytes(h[:4], "little") % dim
        sign = 1.0 if (h[4] & 1) == 0 else -1.0
        vec[offset] += sign
        offset2 = int.from_bytes(h[5:9], "little") % dim
        sign2 = 1.0 if (h[9] & 1) == 0 else -1.0
        vec[offset2] += sign2 * 0.5
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    return vec


def _load_rows(db_path: Path) -> list[tuple[str, str, str, str]]:
    """Load (q_hash, cohort, faq_slug, question_text)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    try:
        cur = conn.execute(
            "SELECT q_hash, cohort, faq_slug, question_text FROM am_precomputed_answer "
            "WHERE q_hash IS NOT NULL ORDER BY answer_id"
        )
        return [(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in cur.fetchall()]
    finally:
        conn.close()


def _build_index(vectors: np.ndarray, nlist: int) -> faiss.Index:
    n, d = vectors.shape
    quantizer = faiss.IndexFlatIP(d)
    nlist_eff = min(nlist, max(1, n // 10))
    index = faiss.IndexIVFFlat(quantizer, d, nlist_eff, faiss.METRIC_INNER_PRODUCT)
    logger.info("training IVF (n=%d, d=%d, nlist=%d)", n, d, nlist_eff)
    index.train(vectors)
    logger.info("adding %d vectors to index", n)
    index.add(vectors)
    index.nprobe = _NPROBE
    return index


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("jpcite.gg2.faiss_v5")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GG2 — Build FAISS v5 for precompute 5,000.")
    parser.add_argument("--out-dir", default="data/faiss")
    parser.add_argument("--index-name", default="am_precomputed_v5_2026_05_17")
    parser.add_argument("--nlist", type=int, default=_NLIST)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    db_path = _autonomath_db_path()
    logger.info("loading rows from %s", db_path)
    rows = _load_rows(db_path)
    if not rows:
        logger.error("no rows with q_hash; ensure composer ran first")
        return 2
    logger.info("loaded %d rows", len(rows))

    t0 = time.time()
    matrix = np.zeros((len(rows), _DIM), dtype=np.float32)
    for i, (_q_hash, _cohort, _faq_slug, qtext) in enumerate(rows):
        matrix[i] = _hash_encode(qtext)
    wall_encode = time.time() - t0
    logger.info(
        "encoded %d vectors in %.2fs (%.1f/sec)",
        len(rows),
        wall_encode,
        len(rows) / max(0.001, wall_encode),
    )

    t1 = time.time()
    index = _build_index(matrix, args.nlist)
    wall_build = time.time() - t1
    logger.info("built index in %.2fs", wall_build)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / f"{args.index_name}.faiss"
    meta_path = out_dir / f"{args.index_name}.meta.json"
    faiss.write_index(index, str(index_path))
    meta = {
        "index_path": str(index_path),
        "dim": _DIM,
        "nlist": index.nlist,
        "nprobe": index.nprobe,
        "ntotal": index.ntotal,
        "metric": "inner_product",
        "encoder": "hash_3gram_fallback_v0",
        "perf_40_floor_nprobe": _NPROBE,
        "row_map": [
            {"id": i, "q_hash": q, "cohort": c, "faq_slug": f}
            for i, (q, c, f, _q) in enumerate(rows)
        ],
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("wrote %s (ntotal=%d)", index_path, index.ntotal)
    logger.info("wrote %s (row_map=%d)", meta_path, len(rows))

    if len(rows) > 0:
        probe = _hash_encode(rows[0][3]).reshape(1, -1)
        _, idx = index.search(probe, 3)
        logger.info("smoke search top-3: indices=%s (expect 0 first)", idx[0].tolist())
        if int(idx[0][0]) != 0:
            logger.warning("smoke recall miss: idx0=%d", int(idx[0][0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
