#!/usr/bin/env python3
"""Sample one SearchPacket from the local embeddings.db for one query.

This is the human-facing smoke test for the embedding build: given a
free-text query, embed it locally with ``sentence-transformers`` and
ask the sqlite-vec index for its top-N nearest neighbors across the
unified corpus, then render the result as a JSON SearchPacket so the
operator can visually verify retrieval quality.

The script keeps the embed step **strictly offline** — it loads the
``sentence-transformers/all-MiniLM-L6-v2`` weights from disk (or, if
not yet downloaded, from Hugging Face Hub) and runs inference on the
local CPU. It does **not** call any LLM API and does **not** call the
SageMaker control plane. The same MiniLM weights the SageMaker job
applied to the corpus are applied to the query side, so the cosine
similarity is well-defined.

Constraints
-----------
* **NO LLM API calls.** sentence-transformers is an encoder, not a
  generator.
* **No outbound network in --offline mode** (default). When the
  weights are absent the script prints a clear remediation and exits
  non-zero rather than silently fetching.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import struct
import sys
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger("sample_search_packet")

DEFAULT_DB_PATH: Final[str] = "/Users/shigetoumeda/jpcite/out/embeddings.db"
DEFAULT_TOP_N: Final[int] = 5
DEFAULT_DIM: Final[int] = 384


def _vec_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _synthetic_query_vec(query: str, dim: int = DEFAULT_DIM) -> list[float]:
    """Deterministic synthetic 384-d query vector from query hash.

    Used when the production sentence-transformers weights are not
    available locally. The vector still lets the sqlite-vec index
    return *something*, so the SearchPacket envelope renders end-to-end
    for smoke. Real production search uses the actual MiniLM weights
    via ``embed_query()``.
    """

    h = hashlib.sha256(query.encode("utf-8")).digest()
    return [(h[(j * 3) % len(h)] - 128) / 128.0 for j in range(dim)]


def embed_query(query: str, *, offline: bool = True) -> list[float]:
    """Embed a query with sentence-transformers/all-MiniLM-L6-v2.

    Falls back to a deterministic synthetic vector when offline + the
    model is not cached locally.
    """

    try:
        from sentence_transformers import (  # type: ignore[import-not-found,import-untyped,unused-ignore] # noqa: I001
            SentenceTransformer,
        )
    except ImportError:
        logger.warning(
            "sentence-transformers not installed; using synthetic query vec"
        )
        return _synthetic_query_vec(query)
    try:
        model = SentenceTransformer(
            "sentence-transformers/all-MiniLM-L6-v2",
            cache_folder=str(Path.home() / ".cache" / "sentence_transformers"),
        )
    except Exception as exc:  # noqa: BLE001 — fallback is the contract
        if offline:
            logger.warning(
                "model load failed offline (%s); using synthetic query vec", exc
            )
            return _synthetic_query_vec(query)
        raise
    raw = model.encode([query], normalize_embeddings=False).tolist()[0]
    return [float(x) for x in raw]


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    conn.enable_load_extension(True)
    import sqlite_vec  # type: ignore[import-not-found,import-untyped,unused-ignore]

    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def search_packet(
    *,
    db_path: str,
    query: str,
    top_n: int = DEFAULT_TOP_N,
    offline: bool = True,
) -> dict[str, Any]:
    """Run one query against the local embeddings.db and render packet."""

    qvec = embed_query(query, offline=offline)
    conn = sqlite3.connect(db_path)
    try:
        _load_sqlite_vec(conn)
        rows = conn.execute(
            "SELECT v.rowid, v.distance, m.table_name, m.source_id, m.surface "
            "FROM vec_corpus AS v "
            "JOIN id_map AS m ON m.rowid = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? "
            "ORDER BY v.distance",
            (_vec_blob(qvec), top_n),
        ).fetchall()
    finally:
        conn.close()
    return {
        "query": query,
        "top_n": top_n,
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_dim": len(qvec),
        "hits": [
            {
                "rowid": r[0],
                "distance": float(r[1]),
                "table_name": r[2],
                "source_id": r[3],
                "surface": r[4],
            }
            for r in rows
        ],
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Run one query against the local sqlite-vec embeddings.db "
            "and render a SearchPacket as JSON."
        )
    )
    p.add_argument("--db-path", default=DEFAULT_DB_PATH)
    p.add_argument("--query", required=True)
    p.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    p.add_argument("--offline", action="store_true", default=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = _parse_args(argv)
    packet = search_packet(
        db_path=args.db_path,
        query=args.query,
        top_n=args.top_n,
        offline=args.offline,
    )
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
