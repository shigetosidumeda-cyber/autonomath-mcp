#!/usr/bin/env python3
"""Lane M5 — SimCSE training entrypoint (runs inside SageMaker container).

Implements unsupervised SimCSE (Gao et al. 2021) on top of
``cl-tohoku/bert-base-japanese-v3`` over the jpcite domain corpus
prepared by ``simcse_corpus_prep_2026_05_17.py``.

How SimCSE works (refresher)
----------------------------
- Each text is fed through the BERT encoder TWICE in the same batch.
- Different dropout masks make the two embeddings differ slightly.
- These two embeddings form the positive pair; all OTHER texts in the
  batch are negatives.
- Loss = InfoNCE / NT-Xent over the in-batch similarity matrix with
  temperature τ.

This is purely an encoder fine-tune; no LLM API is used at any point.

SageMaker channel layout
------------------------
- Input channel ``train``  → ``/opt/ml/input/data/train/train.jsonl``
- Input channel ``val``    → ``/opt/ml/input/data/val/val.jsonl``
- Output                   → ``/opt/ml/model/`` (auto-tarred to S3 by SM)
- Hyperparameters are JSON-merged into ``/opt/ml/input/config/hyperparameters.json``
  and exposed as CLI args by the launcher.

Hyperparameters
---------------
- model_name (str, default cl-tohoku/bert-base-japanese-v3)
- epochs (int, default 3)
- batch_size (int, default 64)
- lr (float, default 3e-5)
- max_length (int, default 128) — SimCSE uses short windows; corpus
  texts already truncated to <=512 chars at prep time.
- temperature (float, default 0.05)
- val_every_n_steps (int, default 200)
- log_every_n_steps (int, default 20)
- seed (int, default 42)

Constraints
-----------
- mypy-friendly, ruff-clean.
- NO LLM API.
- ``[lane:solo]`` marker.
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

logger = logging.getLogger("simcse_train")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


def _set_seed(seed: int) -> None:
    random.seed(seed)
    try:
        import numpy as np  # type: ignore[import-not-found,import-untyped,unused-ignore]

        np.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


def _read_jsonl(path: Path) -> list[str]:
    texts: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = obj.get("text") or obj.get("inputs") or ""
            if text:
                texts.append(str(text))
    return texts


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--model_name", default="cl-tohoku/bert-base-japanese-v3")
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--batch_size", type=int, default=64)
    p.add_argument("--lr", type=float, default=3e-5)
    p.add_argument("--max_length", type=int, default=128)
    p.add_argument("--temperature", type=float, default=0.05)
    p.add_argument("--val_every_n_steps", type=int, default=200)
    p.add_argument("--log_every_n_steps", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    # SageMaker injects channel dirs via env.
    p.add_argument(
        "--train_dir",
        default=os.environ.get("SM_CHANNEL_TRAIN", "/opt/ml/input/data/train"),
    )
    p.add_argument(
        "--val_dir",
        default=os.environ.get("SM_CHANNEL_VAL", "/opt/ml/input/data/val"),
    )
    p.add_argument(
        "--output_dir",
        default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"),
    )
    return p.parse_args(argv)


def _build_dataloader(
    texts: list[str],
    tokenizer: Any,
    *,
    batch_size: int,
    max_length: int,
    shuffle: bool,
) -> Any:
    from torch.utils.data import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
        DataLoader,
        Dataset,
    )

    class _Set(Dataset[dict[str, Any]]):
        def __init__(self, items: list[str]) -> None:
            self.items = items

        def __len__(self) -> int:
            return len(self.items)

        def __getitem__(self, idx: int) -> dict[str, Any]:
            return {"text": self.items[idx]}

    def _collate(batch: list[dict[str, Any]]) -> dict[str, Any]:
        encoded = tokenizer(
            [b["text"] for b in batch],
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        return dict(encoded)

    ds = _Set(texts)
    return DataLoader(
        ds,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=2,
        pin_memory=True,
        collate_fn=_collate,
        drop_last=shuffle,
    )


def _simcse_loss(
    embeds_a: Any,
    embeds_b: Any,
    *,
    temperature: float,
) -> Any:
    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]
    import torch.nn.functional as F  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: N812

    a = F.normalize(embeds_a, dim=-1)
    b = F.normalize(embeds_b, dim=-1)
    sim = torch.matmul(a, b.t()) / temperature
    labels = torch.arange(a.size(0), device=a.device)
    return F.cross_entropy(sim, labels)


def _mean_pool(last_hidden: Any, attention_mask: Any) -> Any:

    mask = attention_mask.unsqueeze(-1).type_as(last_hidden)
    summed = (last_hidden * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1.0)
    return summed / counts


def _encode_with_dropout_twice(
    model: Any,
    batch: dict[str, Any],
) -> tuple[Any, Any]:
    """Run encoder twice with independent dropout masks (SimCSE trick)."""

    out_a = model(**batch)
    out_b = model(**batch)
    emb_a = _mean_pool(out_a.last_hidden_state, batch["attention_mask"])
    emb_b = _mean_pool(out_b.last_hidden_state, batch["attention_mask"])
    return emb_a, emb_b


def _eval(
    model: Any,
    loader: Any,
    *,
    device: Any,
    temperature: float,
) -> dict[str, float]:
    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]

    model.eval()
    total = 0.0
    n = 0
    correct1 = 0
    correct5 = 0
    samples = 0
    with torch.no_grad():
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            out_a = model(**batch)
            out_b = model(**batch)
            emb_a = _mean_pool(out_a.last_hidden_state, batch["attention_mask"])
            emb_b = _mean_pool(out_b.last_hidden_state, batch["attention_mask"])
            loss = _simcse_loss(emb_a, emb_b, temperature=temperature)
            bs = emb_a.size(0)
            total += float(loss.item()) * bs
            n += bs
            # Diagonal-recall: each row's max should be its own column.
            import torch.nn.functional as F  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: N812

            a_n = F.normalize(emb_a, dim=-1)
            b_n = F.normalize(emb_b, dim=-1)
            sim = torch.matmul(a_n, b_n.t())
            target = torch.arange(bs, device=device)
            top1 = sim.argmax(dim=-1)
            correct1 += int((top1 == target).sum().item())
            top5 = sim.topk(min(5, bs), dim=-1).indices
            correct5 += int((top5 == target.unsqueeze(-1)).any(dim=-1).sum().item())
            samples += bs
    model.train()
    if n == 0:
        return {"val_loss": float("nan"), "val_acc_top1": 0.0, "val_acc_top5": 0.0}
    return {
        "val_loss": total / n,
        "val_acc_top1": correct1 / max(1, samples),
        "val_acc_top5": correct5 / max(1, samples),
    }


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    args = _parse_args(argv)
    _set_seed(args.seed)
    logger.info("args = %s", vars(args))

    # Lazy import: keeps DRY_RUN parse + local lint cheap.
    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]
    from transformers import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
        AutoModel,
        AutoTokenizer,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("device = %s", device)

    # Resolve data files.
    train_files = sorted(Path(args.train_dir).glob("*.jsonl"))
    val_files = sorted(Path(args.val_dir).glob("*.jsonl"))
    if not train_files:
        msg = f"no train jsonl under {args.train_dir}"
        raise RuntimeError(msg)
    train_texts: list[str] = []
    for p in train_files:
        train_texts.extend(_read_jsonl(p))
    val_texts: list[str] = []
    for p in val_files:
        val_texts.extend(_read_jsonl(p))
    logger.info("train n=%d val n=%d", len(train_texts), len(val_texts))

    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    model = AutoModel.from_pretrained(args.model_name)
    model.to(device)
    model.train()

    train_loader = _build_dataloader(
        train_texts,
        tokenizer,
        batch_size=args.batch_size,
        max_length=args.max_length,
        shuffle=True,
    )
    val_loader = _build_dataloader(
        val_texts,
        tokenizer,
        batch_size=args.batch_size,
        max_length=args.max_length,
        shuffle=False,
    )

    optim = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.0)
    total_steps = args.epochs * max(1, len(train_loader))
    warmup_steps = max(1, int(0.06 * total_steps))

    def lr_at(step: int) -> float:
        if step < warmup_steps:
            return step / float(warmup_steps)
        progress = (step - warmup_steps) / float(max(1, total_steps - warmup_steps))
        return max(0.0, 0.5 * (1.0 + math.cos(math.pi * progress)))

    step = 0
    best_val_loss = float("inf")
    final_loss = float("nan")
    start_t = time.time()
    history: list[dict[str, Any]] = []

    for epoch in range(args.epochs):
        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            # apply LR schedule
            for pg in optim.param_groups:
                pg["lr"] = args.lr * lr_at(step)
            emb_a, emb_b = _encode_with_dropout_twice(model, batch)
            loss = _simcse_loss(emb_a, emb_b, temperature=args.temperature)
            optim.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()
            final_loss = float(loss.item())
            if step % args.log_every_n_steps == 0:
                elapsed = time.time() - start_t
                logger.info(
                    "epoch=%d step=%d loss=%.4f lr=%.2e elapsed=%.1fs",
                    epoch,
                    step,
                    final_loss,
                    optim.param_groups[0]["lr"],
                    elapsed,
                )
                history.append(
                    {
                        "epoch": epoch,
                        "step": step,
                        "train_loss": final_loss,
                        "lr": optim.param_groups[0]["lr"],
                    }
                )
            if step > 0 and step % args.val_every_n_steps == 0 and val_texts:
                val = _eval(model, val_loader, device=device, temperature=args.temperature)
                logger.info(
                    "VAL step=%d loss=%.4f top1=%.3f top5=%.3f",
                    step,
                    val["val_loss"],
                    val["val_acc_top1"],
                    val["val_acc_top5"],
                )
                history.append({"step": step, **val})
                if val["val_loss"] < best_val_loss:
                    best_val_loss = val["val_loss"]
            step += 1

    # final val
    final_val = (
        _eval(model, val_loader, device=device, temperature=args.temperature) if val_texts else {}
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)

    summary = {
        "model_name": args.model_name,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "temperature": args.temperature,
        "max_length": args.max_length,
        "n_train": len(train_texts),
        "n_val": len(val_texts),
        "total_steps": step,
        "final_train_loss": final_loss,
        "best_val_loss": best_val_loss if best_val_loss != float("inf") else None,
        "final_val": final_val,
        "history": history[-200:],
    }
    (out_dir / "training_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    logger.info("done. summary = %s", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
