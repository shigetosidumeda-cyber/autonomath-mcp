#!/usr/bin/env python3
"""Lane BB4 — Per-cohort LoRA training entrypoint (runs inside SageMaker).

Adds a PEFT LoRA adapter on top of the M5 jpcite-bert-v1 SimCSE checkpoint
(or ``cl-tohoku/bert-base-japanese-v3`` fallback) using cohort-specific
JSONL corpus from ``finetune_corpus_lora_cohort_{cohort}/`` channels.

Training objective remains SimCSE (unsupervised in-batch contrastive)
but only the LoRA matrices are updated; the base BERT weights stay
frozen. The exported adapter is small (~5-15 MB) and is saved separately
under ``/opt/ml/model/lora_adapter/`` for downstream merge or stack.

Hyperparameters
---------------
- model_name_or_path (str, default cl-tohoku/bert-base-japanese-v3)
  - If the SageMaker channel ``base_model`` is provided, the local path
    is used instead (M5 jpcite-bert-v1 checkpoint).
- cohort (str, required) -- one of {zeirishi, kaikeishi, gyouseishoshi,
  shihoshoshi, chusho_keieisha}
- epochs (int, default 2)
- batch_size (int, default 32)
- lr (float, default 5e-4)  -- LoRA-style higher LR vs full-finetune
- lora_rank (int, default 16)
- lora_alpha (int, default 32)
- lora_dropout (float, default 0.05)
- max_length (int, default 128)
- temperature (float, default 0.05)
- seed (int, default 42)

SageMaker channels
------------------
- ``train`` -> /opt/ml/input/data/train/train.jsonl
- ``val``   -> /opt/ml/input/data/val/val.jsonl
- ``base_model`` (optional) -> /opt/ml/input/data/base_model/ (M5 checkpoint)
- Output  -> /opt/ml/model/ (auto-tarred by SM; adapter under lora_adapter/)

Constraints
-----------
- mypy-friendly, ruff-clean.
- NO LLM API; encoder fine-tune only.
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

logger = logging.getLogger("lora_cohort_train")

VALID_COHORTS: tuple[str, ...] = (
    "zeirishi",
    "kaikeishi",
    "gyouseishoshi",
    "shihoshoshi",
    "chusho_keieisha",
)


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
    p.add_argument("--cohort", required=True, choices=list(VALID_COHORTS))
    p.add_argument("--epochs", type=int, default=2)
    p.add_argument("--batch_size", type=int, default=32)
    p.add_argument("--lr", type=float, default=5e-4)
    p.add_argument("--lora_rank", type=int, default=16)
    p.add_argument("--lora_alpha", type=int, default=32)
    p.add_argument("--lora_dropout", type=float, default=0.05)
    p.add_argument("--max_length", type=int, default=128)
    p.add_argument("--temperature", type=float, default=0.05)
    p.add_argument("--log_every_n_steps", type=int, default=20)
    p.add_argument("--val_every_n_steps", type=int, default=200)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--train_dir",
        default=os.environ.get("SM_CHANNEL_TRAIN", "/opt/ml/input/data/train"),
    )
    p.add_argument(
        "--val_dir",
        default=os.environ.get("SM_CHANNEL_VAL", "/opt/ml/input/data/val"),
    )
    p.add_argument(
        "--base_model_dir",
        default=os.environ.get("SM_CHANNEL_BASE_MODEL", ""),
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


def _simcse_loss(emb_a: Any, emb_b: Any, *, temperature: float) -> Any:
    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]
    import torch.nn.functional as F  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: N812

    a = F.normalize(emb_a, dim=-1)
    b = F.normalize(emb_b, dim=-1)
    sim = torch.matmul(a, b.t()) / temperature
    labels = torch.arange(a.size(0), device=a.device)
    return F.cross_entropy(sim, labels)


def _mean_pool(last_hidden: Any, attention_mask: Any) -> Any:
    mask = attention_mask.unsqueeze(-1).type_as(last_hidden)
    summed = (last_hidden * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1.0)
    return summed / counts


def _resolve_base_model(args: argparse.Namespace) -> str:
    base = args.base_model_dir or ""
    if base and Path(base).exists():
        # Check it actually has a config.json (full HF checkpoint).
        if (Path(base) / "config.json").exists():
            logger.info("using base model from channel: %s", base)
            return base
        logger.info(
            "base_model channel exists but no config.json — fallback to %s", args.model_name
        )
    return str(args.model_name)


def _eval(
    model: Any,
    loader: Any,
    *,
    device: Any,
    temperature: float,
) -> dict[str, float]:
    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]
    import torch.nn.functional as F  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: N812

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


def _apply_lora(model: Any, *, rank: int, alpha: int, dropout: float) -> Any:
    """Wrap the model with a PEFT LoRA adapter on Q/K/V/output_dense."""

    from peft import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
        LoraConfig,
        get_peft_model,
    )

    target_modules = ["query", "key", "value", "output.dense"]
    config = LoraConfig(
        r=rank,
        lora_alpha=alpha,
        lora_dropout=dropout,
        bias="none",
        target_modules=target_modules,
        task_type="FEATURE_EXTRACTION",
    )
    peft_model = get_peft_model(model, config)
    return peft_model


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    args = _parse_args(argv)
    _set_seed(args.seed)
    logger.info("args = %s", vars(args))

    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]
    from transformers import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
        AutoModel,
        AutoTokenizer,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("device = %s", device)

    base_model_resolved = _resolve_base_model(args)
    logger.info("base model = %s", base_model_resolved)

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
    logger.info("cohort=%s train n=%d val n=%d", args.cohort, len(train_texts), len(val_texts))

    tokenizer = AutoTokenizer.from_pretrained(base_model_resolved)
    base_model = AutoModel.from_pretrained(base_model_resolved)
    model = _apply_lora(
        base_model,
        rank=args.lora_rank,
        alpha=args.lora_alpha,
        dropout=args.lora_dropout,
    )
    model.to(device)
    model.train()

    # Log trainable parameter count.
    n_trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    n_total = sum(p.numel() for p in model.parameters())
    logger.info(
        "LoRA trainable=%d / total=%d (%.4f%%)",
        n_trainable,
        n_total,
        100.0 * n_trainable / max(1, n_total),
    )

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

    # Only LoRA params are trainable; use AdamW.
    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optim = torch.optim.AdamW(trainable_params, lr=args.lr, weight_decay=0.0)
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
            for pg in optim.param_groups:
                pg["lr"] = args.lr * lr_at(step)
            out_a = model(**batch)
            out_b = model(**batch)
            emb_a = _mean_pool(out_a.last_hidden_state, batch["attention_mask"])
            emb_b = _mean_pool(out_b.last_hidden_state, batch["attention_mask"])
            loss = _simcse_loss(emb_a, emb_b, temperature=args.temperature)
            optim.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable_params, 1.0)
            optim.step()
            final_loss = float(loss.item())
            if step % args.log_every_n_steps == 0:
                elapsed = time.time() - start_t
                logger.info(
                    "cohort=%s epoch=%d step=%d loss=%.4f lr=%.2e elapsed=%.1fs",
                    args.cohort,
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
                    "VAL cohort=%s step=%d loss=%.4f top1=%.3f top5=%.3f",
                    args.cohort,
                    step,
                    val["val_loss"],
                    val["val_acc_top1"],
                    val["val_acc_top5"],
                )
                history.append({"step": step, **val})
                if val["val_loss"] < best_val_loss:
                    best_val_loss = val["val_loss"]
            step += 1

    final_val = (
        _eval(model, val_loader, device=device, temperature=args.temperature) if val_texts else {}
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Save LoRA adapter ONLY (small ~5-15 MB).
    adapter_dir = out_dir / "lora_adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))

    summary = {
        "cohort": args.cohort,
        "base_model": base_model_resolved,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "lora_rank": args.lora_rank,
        "lora_alpha": args.lora_alpha,
        "lora_dropout": args.lora_dropout,
        "temperature": args.temperature,
        "max_length": args.max_length,
        "n_train": len(train_texts),
        "n_val": len(val_texts),
        "total_steps": step,
        "n_trainable_params": n_trainable,
        "n_total_params": n_total,
        "trainable_ratio": n_trainable / max(1, n_total),
        "final_train_loss": final_loss,
        "best_val_loss": best_val_loss if best_val_loss != float("inf") else None,
        "final_val": final_val,
        "history": history[-200:],
    }
    (out_dir / "training_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    logger.info(
        "done cohort=%s. summary = %s", args.cohort, json.dumps(summary, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
