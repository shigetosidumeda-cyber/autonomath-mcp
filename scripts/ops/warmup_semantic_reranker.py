#!/usr/bin/env python3
"""R3 P1-5 boot-time warmup helper for the semantic-search v2 cross-encoder.

This script eagerly loads the MS-MARCO MiniLM-L-6-v2 cross-encoder (the same
model used by ``POST /v1/search/semantic``) and primes it with a single dummy
prediction so the HF / sentence-transformers file cache and the torch / ONNX
kernel weights are resident before the first real request lands.

Why
---

`_get_reranker_model` in ``src/jpintel_mcp/api/semantic_search_v2.py`` measures
cold-load time and opens the reranker circuit if construction exceeds
``RERANKER_COLD_LOAD_TIMEOUT_MS`` (default 2000 ms). A cold Python interpreter
or evicted page cache can push the first call past that budget — turning the
first real ``/v1/search/semantic`` request after a deploy / machine restart
into a RRF-only response (vector + FTS5 only, no reranker reorder).

Running this script inside the API process/preload path also primes the
``semantic_search_v2`` module cache so the first user request hits a populated
model and stays inside the budget. When run as a standalone process it still
warms the Hugging Face / OS file cache, but process-local Python globals do
not cross the process boundary.

Usage
-----

  .venv/bin/python scripts/ops/warmup_semantic_reranker.py

  # From entrypoint.sh §6 (optional, non-blocking — see comment in
  # entrypoint.sh; we never want warmup to fail the boot since the
  # reranker circuit will already gracefully degrade to RRF order).

Exit codes:
  0  warmup succeeded (model loaded + dummy predict ran)
  0  warmup intentionally skipped (sentence_transformers missing, no
     HF cache, etc.) — emits a log line but does NOT fail boot
  1  unexpected fatal error

The script is intentionally tolerant of missing deps because
``entrypoint.sh`` calls it best-effort.
"""

from __future__ import annotations

import logging
import os
import pathlib
import sys
import time

# Make ``jpintel_mcp`` importable when this script is run directly from the
# repo root (the install also exposes it on PYTHONPATH, but the script must
# work in both layouts).
_REPO_SRC = pathlib.Path(__file__).resolve().parent.parent.parent / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

logging.basicConfig(
    level=os.environ.get("WARMUP_SEMANTIC_RERANKER_LOG_LEVEL", "INFO"),
    format="[warmup_semantic_reranker] %(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("warmup_semantic_reranker")


def _cache_dir() -> str | None:
    return os.environ.get("HF_HOME") or os.environ.get("SENTENCE_TRANSFORMERS_HOME")


def warmup() -> int:
    """Load + dummy-predict the cross-encoder. Returns process exit code."""
    try:
        from jpintel_mcp.api import semantic_search_v2 as ssv2
    except ImportError as exc:
        logger.info("jpintel_mcp.api.semantic_search_v2 unavailable (%s) — skipping warmup", exc)
        return 0

    try:
        from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]
    except ImportError as exc:
        logger.info("sentence_transformers unavailable (%s) — skipping warmup", exc)
        return 0

    cache_dir = _cache_dir()
    logger.info(
        "loading cross-encoder=%s cache_dir=%s budget=%sms",
        ssv2.RERANKER_MODEL,
        cache_dir or "<none>",
        ssv2.RERANKER_COLD_LOAD_TIMEOUT_MS,
    )

    load_start = time.perf_counter()
    kwargs: dict[str, object] = {}
    if cache_dir:
        kwargs["cache_folder"] = cache_dir
    try:
        model = CrossEncoder(ssv2.RERANKER_MODEL, **kwargs)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        logger.warning("cross-encoder load failed (%s) — skipping warmup", exc)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "cross-encoder load raised unexpected %s (%s) — skipping warmup",
            type(exc).__name__,
            exc,
        )
        return 0
    load_ms = int((time.perf_counter() - load_start) * 1000)
    logger.info("cross-encoder load completed in %sms", load_ms)

    if load_ms > ssv2.RERANKER_COLD_LOAD_TIMEOUT_MS:
        # Don't fail boot — the runtime will open the circuit on the first
        # real request and gracefully degrade to RRF order. But surface a
        # warning so ops can chase down the slow cold load.
        logger.warning(
            "cross-encoder cold load exceeded budget (%sms > %sms) — first real "
            "request will trip the circuit; investigate HF cache or disk pressure",
            load_ms,
            ssv2.RERANKER_COLD_LOAD_TIMEOUT_MS,
        )

    # Prime the kernel with a dummy prediction so the torch / ONNX weight
    # tensors land in RAM before the first real user request.
    predict_start = time.perf_counter()
    try:
        scores = model.predict([("warmup", "warmup")])
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        logger.warning("cross-encoder dummy predict failed (%s) — partial warmup", exc)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "cross-encoder dummy predict raised unexpected %s (%s) — partial warmup",
            type(exc).__name__,
            exc,
        )
        return 0
    predict_ms = int((time.perf_counter() - predict_start) * 1000)
    logger.info(
        "cross-encoder dummy predict completed in %sms (score sample=%s)",
        predict_ms,
        list(scores)[:1] if hasattr(scores, "__iter__") else scores,
    )
    ssv2._prime_reranker_model_cache(model)

    logger.info(
        "warmup complete — total=%sms (load=%sms predict=%sms api_cache=primed)",
        load_ms + predict_ms,
        load_ms,
        predict_ms,
    )
    return 0


def main() -> int:
    try:
        return warmup()
    except Exception as exc:  # noqa: BLE001
        logger.error("unexpected fatal warmup error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
