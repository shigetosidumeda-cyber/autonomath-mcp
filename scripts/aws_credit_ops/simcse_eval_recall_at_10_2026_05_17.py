#!/usr/bin/env python3
"""Lane M5 — recall@10 evaluation: jpcite-bert-v1 vs cl-tohoku base.

Compares the fine-tuned SimCSE model output (downloaded from
``s3://.../models/jpcite-bert-v1/.../model.tar.gz``) against the base
``cl-tohoku/bert-base-japanese-v3`` over a synthetic 100-query
benchmark drawn from the validation split.

Method
------
1. Sample 100 (query, doc) pairs from the held-out val.jsonl
   (deterministic seed). Each query is the first 24 chars of a
   document text; the doc itself is the gold target.
2. Index 5,000 unique val texts (including the 100 golds) using each
   model (mean-pool over last-hidden + L2 normalize).
3. For each query, take top-10 cosine neighbours, mark hit if the
   gold doc index is in the top-10.
4. Report ``recall@10`` for base and tuned + relative delta.

Synthetic benchmark caveat
--------------------------
"100 expert-annotated pairs" is the goal; a 100-row hand-annotated
golden set does not exist in the repo today. This script provides a
**reproducible synthetic proxy** using held-out val data so the
relative delta between models is a fair apples-to-apples signal.
The actual recall@10 numbers should be interpreted as relative.

NO LLM API — only encoder inference.

CLI
---

.. code-block:: text

    python scripts/aws_credit_ops/simcse_eval_recall_at_10_2026_05_17.py \\
        --val-path /Users/shigetoumeda/jpcite/data/_cache/val.jsonl \\
        --tuned-model-path /Users/shigetoumeda/jpcite/data/_cache/jpcite-bert-v1 \\
        --n-queries 100 --index-size 5000
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("simcse_eval")


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


def _encode(texts: list[str], *, model_name_or_path: str, batch_size: int = 32) -> Any:
    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]
    import torch.nn.functional as F  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: N812
    from transformers import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
        AutoModel,
        AutoTokenizer,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tok = AutoTokenizer.from_pretrained(model_name_or_path)
    model = AutoModel.from_pretrained(model_name_or_path)
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


def recall_at_10(
    *,
    queries: list[str],
    docs: list[str],
    gold_indices: list[int],
    model_name_or_path: str,
) -> float:
    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]

    q_emb = _encode(queries, model_name_or_path=model_name_or_path)
    d_emb = _encode(docs, model_name_or_path=model_name_or_path)
    sim = torch.matmul(q_emb, d_emb.t())
    topk = sim.topk(min(10, d_emb.size(0)), dim=-1).indices
    gold = torch.tensor(gold_indices)
    hits = (topk == gold.unsqueeze(-1)).any(dim=-1).sum().item()
    return float(hits) / max(1, len(queries))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--val-path", required=True)
    p.add_argument(
        "--base-model",
        default="cl-tohoku/bert-base-japanese-v3",
    )
    p.add_argument(
        "--tuned-model-path",
        required=True,
        help="local path to extracted jpcite-bert-v1 model dir",
    )
    p.add_argument("--n-queries", type=int, default=100)
    p.add_argument("--index-size", type=int, default=5000)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    random.seed(args.seed)

    texts = _read_jsonl(Path(args.val_path))
    if len(texts) < args.n_queries + args.index_size:
        msg = f"val set too small: have {len(texts)}, need {args.n_queries + args.index_size}"
        raise RuntimeError(msg)
    random.shuffle(texts)
    docs = texts[: args.index_size]
    # Use first n_queries docs as gold, derive queries by truncating.
    gold_indices = list(range(args.n_queries))
    queries: list[str] = []
    for i in gold_indices:
        # 24-char prefix is the synthetic query
        queries.append(docs[i][:24])

    base_r10 = recall_at_10(
        queries=queries,
        docs=docs,
        gold_indices=gold_indices,
        model_name_or_path=args.base_model,
    )
    tuned_r10 = recall_at_10(
        queries=queries,
        docs=docs,
        gold_indices=gold_indices,
        model_name_or_path=args.tuned_model_path,
    )

    rel_delta = tuned_r10 - base_r10
    out = {
        "n_queries": args.n_queries,
        "index_size": args.index_size,
        "base_model": args.base_model,
        "tuned_model_path": args.tuned_model_path,
        "base_recall_at_10": base_r10,
        "tuned_recall_at_10": tuned_r10,
        "relative_delta": rel_delta,
        "relative_pct": (rel_delta / max(1e-9, base_r10)) * 100.0,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
