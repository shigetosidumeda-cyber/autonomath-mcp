#!/usr/bin/env python3
"""Lane M5 v2 — recall@10 v2 vs v1 comparison harness.

Wraps ``simcse_eval_recall_at_10_2026_05_17.py`` to run **three**
evaluations on the same 50-query synthetic benchmark and emit a
single comparison report:

    A) base cl-tohoku/bert-base-japanese-v3        (untuned baseline)
    B) jpcite-bert-v1                              (M5 v1 tuned)
    C) jpcite-bert-v2                              (M5 v2 tuned)

Output schema (printed JSON + optionally uploaded to S3):

.. code-block:: json

    {
      "n_queries": 50,
      "index_size": 5000,
      "seed": 42,
      "results": {
        "base":   {"recall_at_10": 0.42},
        "v1":     {"recall_at_10": 0.61},
        "v2":     {"recall_at_10": 0.69}
      },
      "v2_lift_over_v1_pct": 13.11,
      "v2_lift_over_base_pct": 64.29,
      "target_lift_pct_range": [5, 15],
      "target_met": true
    }

The +5-15% lift band (vs v1) is the v2 success target per the task
brief. Failure mode = ``target_met=false`` (operator decides whether
to roll v2 to production or rerun with a different recipe).

Constraints
-----------
- NO LLM API; encoder inference only.
- mypy --strict friendly.
- ``[lane:solo]``.

Pre-condition
-------------
- ``finetune_corpus[_v2]/val.jsonl`` available locally (or fetched).
- Tuned model artefacts available locally at ``--v1-model-path`` and
  ``--v2-model-path`` (downloaded + extracted from S3 ``model.tar.gz``).
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger("simcse_eval_v2_vs_v1")

DEFAULT_N_QUERIES: Final[int] = 50
DEFAULT_INDEX_SIZE: Final[int] = 5_000
DEFAULT_K: Final[int] = 10
TARGET_LIFT_LO: Final[float] = 5.0
TARGET_LIFT_HI: Final[float] = 15.0


@dataclass
class EvalResult:
    name: str
    recall_at_k: float


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
            t = obj.get("text")
            if isinstance(t, str) and t:
                out.append(t)
    return out


def _embed(texts: list[str], *, model_id_or_path: str, max_length: int, batch_size: int) -> Any:
    import numpy as np  # type: ignore[import-not-found,import-untyped,unused-ignore]
    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]
    from transformers import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
        AutoModel,
        AutoTokenizer,
    )

    tok = AutoTokenizer.from_pretrained(model_id_or_path)
    mdl = AutoModel.from_pretrained(model_id_or_path)
    mdl.eval()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    mdl.to(device)
    embs: list[Any] = []
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            enc = tok(
                batch,
                max_length=max_length,
                padding=True,
                truncation=True,
                return_tensors="pt",
            ).to(device)
            out = mdl(**enc)
            hidden = out.last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1.0)
            pooled = torch.nn.functional.normalize(pooled, dim=-1)
            embs.append(pooled.cpu().numpy())
    return np.concatenate(embs, axis=0)


def _recall_at_k(
    texts: list[str],
    n_queries: int,
    k: int,
    *,
    model_id_or_path: str,
    max_length: int,
    batch_size: int,
    rng: random.Random,
) -> float:
    import numpy as np  # type: ignore[import-not-found,import-untyped,unused-ignore]

    idxs = list(range(len(texts)))
    rng.shuffle(idxs)
    gold_idxs = idxs[:n_queries]
    queries = [texts[i][:24] for i in gold_idxs]

    embs = _embed(
        texts, model_id_or_path=model_id_or_path, max_length=max_length, batch_size=batch_size
    )
    q_embs = _embed(
        queries, model_id_or_path=model_id_or_path, max_length=max_length, batch_size=batch_size
    )

    # cosine sim — already L2-normalized, so dot product.
    sims = q_embs @ embs.T
    topk = np.argsort(-sims, axis=1)[:, :k]
    hits = 0
    for i, g in enumerate(gold_idxs):
        if g in topk[i].tolist():
            hits += 1
    return hits / max(1, n_queries)


def run_compare(
    *,
    val_path: Path,
    base_model: str,
    v1_path: Path | None,
    v2_path: Path | None,
    n_queries: int,
    index_size: int,
    seed: int,
    max_length: int,
    batch_size: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    texts = _read_jsonl(val_path)
    if len(texts) < n_queries + 1:
        raise RuntimeError(f"val.jsonl too small: {len(texts)} rows < {n_queries + 1}")
    rng.shuffle(texts)
    texts = texts[:index_size]

    results: dict[str, dict[str, Any]] = {}

    # base
    rb = _recall_at_k(
        texts,
        n_queries,
        DEFAULT_K,
        model_id_or_path=base_model,
        max_length=max_length,
        batch_size=batch_size,
        rng=random.Random(seed),
    )
    results["base"] = {"recall_at_10": rb}

    if v1_path is not None and v1_path.exists():
        r1 = _recall_at_k(
            texts,
            n_queries,
            DEFAULT_K,
            model_id_or_path=str(v1_path),
            max_length=max_length,
            batch_size=batch_size,
            rng=random.Random(seed),
        )
        results["v1"] = {"recall_at_10": r1}
    else:
        results["v1"] = {"recall_at_10": float("nan"), "_note": "v1 path missing"}

    if v2_path is not None and v2_path.exists():
        r2 = _recall_at_k(
            texts,
            n_queries,
            DEFAULT_K,
            model_id_or_path=str(v2_path),
            max_length=max_length,
            batch_size=batch_size,
            rng=random.Random(seed),
        )
        results["v2"] = {"recall_at_10": r2}
    else:
        results["v2"] = {"recall_at_10": float("nan"), "_note": "v2 path missing"}

    r_v1 = results["v1"]["recall_at_10"]
    r_v2 = results["v2"]["recall_at_10"]
    r_b = results["base"]["recall_at_10"]

    def _pct(num: float, den: float) -> float:
        if den == 0 or den != den:  # NaN check
            return float("nan")
        return round(100.0 * (num - den) / den, 2)

    lift_v1 = _pct(r_v2, r_v1)
    lift_base = _pct(r_v2, r_b)
    target_met = (
        lift_v1 == lift_v1  # not NaN
        and TARGET_LIFT_LO <= lift_v1 <= TARGET_LIFT_HI
    )

    return {
        "n_queries": n_queries,
        "index_size": index_size,
        "k": DEFAULT_K,
        "seed": seed,
        "results": results,
        "v2_lift_over_v1_pct": lift_v1,
        "v2_lift_over_base_pct": lift_base,
        "target_lift_pct_range": [TARGET_LIFT_LO, TARGET_LIFT_HI],
        "target_met": target_met,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="M5 v2 vs v1 recall@10 comparison harness.",
    )
    p.add_argument("--val-path", type=Path, required=True)
    p.add_argument("--base-model", default="cl-tohoku/bert-base-japanese-v3")
    p.add_argument("--v1-model-path", type=Path, default=None)
    p.add_argument("--v2-model-path", type=Path, default=None)
    p.add_argument("--n-queries", type=int, default=DEFAULT_N_QUERIES)
    p.add_argument("--index-size", type=int, default=DEFAULT_INDEX_SIZE)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--max-length", type=int, default=128)
    p.add_argument("--batch-size", type=int, default=64)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    report = run_compare(
        val_path=args.val_path,
        base_model=args.base_model,
        v1_path=args.v1_model_path,
        v2_path=args.v2_model_path,
        n_queries=args.n_queries,
        index_size=args.index_size,
        seed=args.seed,
        max_length=args.max_length,
        batch_size=args.batch_size,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["target_met"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
