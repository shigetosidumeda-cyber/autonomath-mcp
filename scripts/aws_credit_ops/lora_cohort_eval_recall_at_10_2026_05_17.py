#!/usr/bin/env python3
"""Lane BB4 — Per-cohort recall@10 evaluation: cohort-LoRA vs base.

Compares each cohort's LoRA adapter (stacked on jpcite-bert-v1 OR
``cl-tohoku/bert-base-japanese-v3`` fallback) against the un-adapted
base over a cohort-specific synthetic 10-query benchmark drawn from
the cohort's held-out val.jsonl.

Method (per cohort)
-------------------
1. Read the cohort's ``s3://.../finetune_corpus_lora_cohort_{cohort}/val.jsonl``.
2. Sample 10 (query, doc) pairs (deterministic seed). Each query is
   the first 24 chars of a document text; the doc itself is the gold
   target.
3. Index 1,000 unique val texts (including the 10 golds) with each
   model (mean-pool over last-hidden + L2 normalize).
4. For each query, take top-10 cosine neighbours, mark hit if the
   gold doc index is in the top-10.
5. Report ``recall@10`` for base and cohort-LoRA + relative delta.

Output
------
JSON manifest under ``docs/_internal/bb4_lora_eval_recall_at_10_2026_05_17.json``
with the 5 cohort × {base, lora, delta} matrix.

Synthetic benchmark caveat
--------------------------
"10 expert-annotated queries per cohort" is the goal. A hand-annotated
golden set per cohort does not exist in the repo today. This script
provides a **reproducible synthetic proxy** drawn from cohort-filtered
held-out val data so the relative delta between models is a fair
apples-to-apples signal.

Constraints
-----------
- NO LLM API anywhere; encoder inference only.
- Locally runnable (CPU-only, ~5-10 min per cohort with 1000-row index).
- mypy-friendly, ruff-clean. ``[lane:solo]`` marker.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("lora_cohort_eval")

VALID_COHORTS: tuple[str, ...] = (
    "zeirishi",
    "kaikeishi",
    "gyouseishoshi",
    "shihoshoshi",
    "chusho_keieisha",
)


def _read_jsonl(path: Path) -> list[str]:
    out: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = obj.get("text") or obj.get("inputs") or ""
            if t:
                out.append(str(t))
    return out


def _encode(
    texts: list[str],
    *,
    base_model: str,
    adapter_path: str | None = None,
    batch_size: int = 32,
) -> Any:
    """Encode texts using base or base+LoRA adapter.

    Parameters
    ----------
    texts:
        List of text strings to encode.
    base_model:
        HuggingFace model name or local checkpoint path.
    adapter_path:
        If set, treats as a PEFT LoRA adapter directory and stacks on
        top of ``base_model``.
    batch_size:
        Encoder batch size.
    """

    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]
    import torch.nn.functional as F  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: N812
    from transformers import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
        AutoModel,
        AutoTokenizer,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tok = AutoTokenizer.from_pretrained(base_model)
    model = AutoModel.from_pretrained(base_model)
    if adapter_path:
        from peft import PeftModel  # type: ignore[import-not-found,import-untyped,unused-ignore]

        model = PeftModel.from_pretrained(model, adapter_path)
    model.to(device)
    model.eval()
    embs: list[Any] = []
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            enc = tok(
                chunk,
                padding=True,
                truncation=True,
                max_length=128,
                return_tensors="pt",
            ).to(device)
            out = model(**enc)
            mask = enc["attention_mask"].unsqueeze(-1).type_as(out.last_hidden_state)
            summed = (out.last_hidden_state * mask).sum(dim=1)
            counts = mask.sum(dim=1).clamp(min=1.0)
            pooled = summed / counts
            embs.append(F.normalize(pooled, dim=-1).cpu())
    return torch.cat(embs, dim=0)


def _recall_at_k(
    query_embs: Any,
    doc_embs: Any,
    *,
    gold_indices: list[int],
    k: int = 10,
) -> float:
    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]

    sim = torch.matmul(query_embs, doc_embs.t())
    topk = sim.topk(k, dim=-1).indices.tolist()
    hits = 0
    for qi, gold_idx in enumerate(gold_indices):
        if gold_idx in topk[qi]:
            hits += 1
    return hits / max(1, len(gold_indices))


def eval_cohort(
    *,
    cohort: str,
    val_path: Path,
    base_model: str,
    adapter_path: str | None,
    n_queries: int,
    index_size: int,
    seed: int,
) -> dict[str, Any]:
    """Run a single-cohort eval and return its recall@10 matrix."""

    rng = random.Random(seed)
    val = _read_jsonl(val_path)
    if len(val) < index_size:
        logger.warning(
            "  cohort=%s val_size=%d < index_size=%d; using full val",
            cohort,
            len(val),
            index_size,
        )
        index_size = len(val)
    # Sample n_queries + (index_size - n_queries) other texts.
    rng.shuffle(val)
    queries = val[:n_queries]
    golds = queries  # The full doc is the gold target.
    other = val[n_queries:index_size]
    docs = list(golds) + list(other)
    gold_indices = list(range(n_queries))
    queries_str = [q[:24] for q in queries]

    logger.info("  cohort=%s n_q=%d n_docs=%d", cohort, len(queries_str), len(docs))

    # Base encode.
    base_doc_embs = _encode(docs, base_model=base_model, adapter_path=None)
    base_q_embs = _encode(queries_str, base_model=base_model, adapter_path=None)
    base_recall = _recall_at_k(base_q_embs, base_doc_embs, gold_indices=gold_indices, k=10)
    logger.info("  cohort=%s base recall@10=%.3f", cohort, base_recall)

    # LoRA encode.
    lora_recall: float | None = None
    if adapter_path and Path(adapter_path).exists():
        lora_doc_embs = _encode(docs, base_model=base_model, adapter_path=adapter_path)
        lora_q_embs = _encode(queries_str, base_model=base_model, adapter_path=adapter_path)
        lora_recall = _recall_at_k(lora_q_embs, lora_doc_embs, gold_indices=gold_indices, k=10)
        logger.info("  cohort=%s LoRA recall@10=%.3f", cohort, lora_recall)
    else:
        logger.info("  cohort=%s LoRA adapter not present; skip", cohort)

    delta: float | None = (lora_recall - base_recall) if (lora_recall is not None) else None
    return {
        "cohort": cohort,
        "n_queries": n_queries,
        "n_docs": len(docs),
        "base_model": base_model,
        "adapter_path": adapter_path,
        "base_recall_at_10": base_recall,
        "lora_recall_at_10": lora_recall,
        "delta": delta,
        "lift_pct": (delta * 100.0) if delta is not None else None,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="BB4 — per-cohort recall@10 eval (base vs cohort-LoRA)."
    )
    p.add_argument(
        "--cohorts",
        nargs="+",
        default=list(VALID_COHORTS),
        choices=list(VALID_COHORTS),
    )
    p.add_argument(
        "--val-root",
        default="data/_cache/lora_cohort_val",
        help="Local dir containing {cohort}/val.jsonl downloaded from S3.",
    )
    p.add_argument(
        "--adapter-root",
        default="data/_cache/lora_cohort_adapters",
        help="Local dir containing {cohort}/lora_adapter/ from the SM model tarball.",
    )
    p.add_argument(
        "--base-model",
        default="cl-tohoku/bert-base-japanese-v3",
        help="HuggingFace model name OR local M5 jpcite-bert-v1 checkpoint path.",
    )
    p.add_argument("--n-queries", type=int, default=10)
    p.add_argument("--index-size", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--output",
        default="docs/_internal/bb4_lora_eval_recall_at_10_2026_05_17.json",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    val_root = Path(args.val_root)
    adapter_root = Path(args.adapter_root)
    results: list[dict[str, Any]] = []
    for cohort in args.cohorts:
        val_path = val_root / cohort / "val.jsonl"
        adapter_path = adapter_root / cohort / "lora_adapter"
        if not val_path.exists():
            logger.info("  cohort=%s val.jsonl missing at %s; skip", cohort, val_path)
            results.append(
                {
                    "cohort": cohort,
                    "status": "missing_val",
                    "val_path": str(val_path),
                }
            )
            continue
        try:
            r = eval_cohort(
                cohort=cohort,
                val_path=val_path,
                base_model=args.base_model,
                adapter_path=str(adapter_path) if adapter_path.exists() else None,
                n_queries=args.n_queries,
                index_size=args.index_size,
                seed=args.seed,
            )
            results.append(r)
        except (RuntimeError, ImportError, OSError) as exc:
            logger.exception("  cohort=%s eval failed", cohort)
            results.append(
                {
                    "cohort": cohort,
                    "status": "error",
                    "error": str(exc),
                }
            )
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
