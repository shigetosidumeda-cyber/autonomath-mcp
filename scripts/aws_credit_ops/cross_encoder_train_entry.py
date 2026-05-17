#!/usr/bin/env python3
"""Lane M6 — Cross-encoder training entrypoint (runs inside SageMaker).

Fine-tunes ``hotchpotch/japanese-reranker-cross-encoder-large-v1`` as
a ``AutoModelForSequenceClassification(num_labels=1)`` over
``(query, doc, label)`` triples produced by
``cross_encoder_pair_gen_2026_05_17.py`` (v1) or
``cross_encoder_pair_gen_v2_2026_05_17.py`` (v2).

How M6 differs from M5
----------------------
M5 (SimCSE) is **unsupervised contrastive** — single-text input, two
dropout-perturbed forward passes form the positive pair, every other
sample in the batch is a negative. Loss = InfoNCE.

M6 is **supervised pointwise / pairwise** — explicit
``(query, doc, label∈{0,1})`` triples. Loss = BCEWithLogitsLoss over
the single logit head. Negatives come from in-corpus mismatched pairs
plus (optionally) hard-negatives mined from the v1 SimCSE encoder.

SageMaker channel layout
------------------------
- ``train`` channel  → ``/opt/ml/input/data/train/pairs.jsonl``
- ``val`` channel    → ``/opt/ml/input/data/val/pairs.jsonl``
- Output             → ``/opt/ml/model/`` (auto-tarred to S3 by SM).

Input format (per line)
-----------------------

.. code-block:: json

    {"query": "...", "doc": "...", "label": 1}

Hyperparameters
---------------
- ``model_name``       default ``hotchpotch/japanese-reranker-cross-encoder-large-v1``
- ``epochs``           default 5 (v1) / 10 (v2)
- ``batch_size``       default 32
- ``lr``               default 1e-5
- ``max_length``       default 256
- ``warmup_ratio``     default 0.06
- ``weight_decay``     default 0.01
- ``log_every_n_steps`` default 25
- ``val_every_n_steps`` default 250
- ``seed``             default 42

NO LLM API. Encoder-side reranker only.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("cross_encoder_train")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )


def _read_pairs(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            q = str(obj.get("query") or "")
            d = str(obj.get("doc") or "")
            lab = obj.get("label", 0)
            if not q or not d:
                continue
            try:
                label = float(lab)
            except (TypeError, ValueError):
                continue
            rows.append({"query": q, "doc": d, "label": label})
    return rows


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--model_name",
        default=os.environ.get(
            "SM_HP_MODEL_NAME",
            "hotchpotch/japanese-reranker-cross-encoder-large-v1",
        ),
    )
    p.add_argument("--epochs", type=int, default=int(os.environ.get("SM_HP_EPOCHS", "5")))
    p.add_argument("--batch_size", type=int, default=int(os.environ.get("SM_HP_BATCH_SIZE", "32")))
    p.add_argument("--lr", type=float, default=float(os.environ.get("SM_HP_LR", "1e-5")))
    p.add_argument("--max_length", type=int, default=int(os.environ.get("SM_HP_MAX_LENGTH", "256")))
    p.add_argument(
        "--warmup_ratio",
        type=float,
        default=float(os.environ.get("SM_HP_WARMUP_RATIO", "0.06")),
    )
    p.add_argument(
        "--weight_decay",
        type=float,
        default=float(os.environ.get("SM_HP_WEIGHT_DECAY", "0.01")),
    )
    p.add_argument(
        "--log_every_n_steps",
        type=int,
        default=int(os.environ.get("SM_HP_LOG_EVERY_N_STEPS", "25")),
    )
    p.add_argument(
        "--val_every_n_steps",
        type=int,
        default=int(os.environ.get("SM_HP_VAL_EVERY_N_STEPS", "250")),
    )
    p.add_argument("--seed", type=int, default=int(os.environ.get("SM_HP_SEED", "42")))
    p.add_argument(
        "--train_path",
        default=os.environ.get("SM_CHANNEL_TRAIN", "/opt/ml/input/data/train") + "/pairs.jsonl",
    )
    p.add_argument(
        "--val_path",
        default=os.environ.get("SM_CHANNEL_VAL", "/opt/ml/input/data/val") + "/pairs.jsonl",
    )
    p.add_argument("--model_dir", default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    _setup_logging()
    args = _parse_args(argv)
    logger.info("cross-encoder train args: %s", vars(args))

    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]
    from torch.utils.data import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
        DataLoader,
        Dataset,
    )
    from transformers import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
        AutoModelForSequenceClassification,
        AutoTokenizer,
        get_linear_schedule_with_warmup,
    )

    random.seed(args.seed)
    torch.manual_seed(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("device=%s cuda_count=%d", device, torch.cuda.device_count())

    train_rows = _read_pairs(Path(args.train_path))
    val_rows = _read_pairs(Path(args.val_path))
    logger.info("train_rows=%d val_rows=%d", len(train_rows), len(val_rows))

    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    model = AutoModelForSequenceClassification.from_pretrained(args.model_name, num_labels=1)
    model.to(device)

    class _PairDS(Dataset[dict[str, Any]]):
        def __init__(self, rows: list[dict[str, Any]]) -> None:
            self.rows = rows

        def __len__(self) -> int:
            return len(self.rows)

        def __getitem__(self, i: int) -> dict[str, Any]:
            return self.rows[i]

    def _collate(batch: list[dict[str, Any]]) -> dict[str, Any]:
        enc = tokenizer(
            [b["query"] for b in batch],
            [b["doc"] for b in batch],
            max_length=args.max_length,
            padding=True,
            truncation=True,
            return_tensors="pt",
        )
        enc["labels"] = torch.tensor([b["label"] for b in batch], dtype=torch.float32)
        out: dict[str, Any] = dict(enc)
        return out

    train_loader = DataLoader(
        _PairDS(train_rows),
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=_collate,
        drop_last=True,
    )
    val_loader = DataLoader(
        _PairDS(val_rows),
        batch_size=args.batch_size * 2,
        shuffle=False,
        collate_fn=_collate,
    )

    steps_per_epoch = max(1, len(train_loader))
    total_steps = steps_per_epoch * args.epochs
    warmup_steps = max(1, int(total_steps * args.warmup_ratio))
    optim = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    sched = get_linear_schedule_with_warmup(  # type: ignore[no-untyped-call]
        optim, warmup_steps, total_steps
    )
    bce = torch.nn.BCEWithLogitsLoss()

    def _val() -> tuple[float, float]:
        model.eval()
        total_loss = 0.0
        n = 0
        correct = 0
        with torch.no_grad():
            for b in val_loader:
                b = {k: v.to(device) for k, v in b.items()}
                lab = b.pop("labels")
                out = model(**b)
                logit = out.logits.squeeze(-1)
                loss = bce(logit, lab)
                total_loss += float(loss.item()) * lab.size(0)
                pred = (torch.sigmoid(logit) > 0.5).float()
                correct += int((pred == lab).sum().item())
                n += int(lab.size(0))
        model.train()
        return total_loss / max(1, n), correct / max(1, n)

    model.train()
    step = 0
    t0 = time.time()
    for epoch in range(args.epochs):
        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            lab = batch.pop("labels")
            out = model(**batch)
            logit = out.logits.squeeze(-1)
            loss = bce(logit, lab)
            loss.backward()
            optim.step()
            sched.step()
            optim.zero_grad(set_to_none=True)
            step += 1
            if step % args.log_every_n_steps == 0:
                logger.info(
                    "epoch=%d step=%d loss=%.4f lr=%.2e elapsed=%.1fs",
                    epoch,
                    step,
                    float(loss.item()),
                    sched.get_last_lr()[0],
                    time.time() - t0,
                )
            if step % args.val_every_n_steps == 0:
                vl, va = _val()
                logger.info("VAL step=%d loss=%.4f acc=%.4f", step, vl, va)

    # final eval + save
    vl, va = _val()
    logger.info("FINAL_VAL loss=%.4f acc=%.4f", vl, va)
    out_dir = Path(args.model_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    (out_dir / "training_metrics.json").write_text(
        json.dumps(
            {
                "final_val_loss": vl,
                "final_val_acc": va,
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "lr": args.lr,
                "total_steps": step,
                "train_rows": len(train_rows),
                "val_rows": len(val_rows),
                "model_name": args.model_name,
            }
        ),
        encoding="utf-8",
    )
    logger.info("saved model + tokenizer to %s", out_dir)
    # avoid the unused-import warning for math
    _ = math.pi
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
