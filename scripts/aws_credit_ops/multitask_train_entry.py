#!/usr/bin/env python3
"""Lane M11 Day 1 — Multi-task fine-tune entrypoint (runs inside SageMaker).

Trains one shared BERT-large encoder with FOUR task heads simultaneously,
each backed by labels derivable in-corpus without any LLM API call:

- **MLM head**     — standard masked-LM (Hugging Face DataCollatorForLanguageModeling).
- **NER head**     — token classification over jpcite regex-derived entities
                     (corporate_entity / program / law / authority / amount / date / region).
- **REL head**     — sentence-pair relation classification (relation type or NONE).
- **RANK head**    — text regression over `programs.tier` / `adoption_count`
                     compressed into [0,1] (M6 proxy).

Each row in the train.jsonl is a self-describing dict with `task` ∈
{mlm, ner, rel, rank} and the fields each head needs. Heads share the
encoder; only the per-task head is trained on each minibatch. The
loss is the per-task loss (no weighting beyond uniform sampling).

NO LLM API anywhere. ``[lane:solo]`` marker.

SageMaker channel layout
------------------------
- /opt/ml/input/data/train/train.jsonl
- /opt/ml/input/data/val/val.jsonl   (may carry only mlm rows)
- /opt/ml/model/                     -> auto-tarred to S3 as model.tar.gz
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

logger = logging.getLogger("multitask_train")


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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Multi-task fine-tune entrypoint.")
    p.add_argument(
        "--model_name", default=os.environ.get("MODEL_NAME", "cl-tohoku/bert-large-japanese-v2")
    )
    p.add_argument("--epochs", type=int, default=int(os.environ.get("EPOCHS", "2")))
    p.add_argument("--batch_size", type=int, default=int(os.environ.get("BATCH_SIZE", "16")))
    p.add_argument("--lr", type=float, default=float(os.environ.get("LR", "2e-5")))
    p.add_argument("--max_length", type=int, default=int(os.environ.get("MAX_LENGTH", "256")))
    p.add_argument("--seed", type=int, default=int(os.environ.get("SEED", "42")))
    p.add_argument(
        "--num_ner_labels", type=int, default=int(os.environ.get("NUM_NER_LABELS", "15"))
    )
    p.add_argument(
        "--num_rel_labels", type=int, default=int(os.environ.get("NUM_REL_LABELS", "16"))
    )
    p.add_argument("--log_every_n_steps", type=int, default=50)
    p.add_argument("--val_every_n_steps", type=int, default=500)
    p.add_argument(
        "--train_data",
        default=os.environ.get("SM_CHANNEL_TRAIN", "/opt/ml/input/data/train") + "/train.jsonl",
    )
    p.add_argument(
        "--val_data",
        default=os.environ.get("SM_CHANNEL_VAL", "/opt/ml/input/data/val") + "/val.jsonl",
    )
    p.add_argument(
        "--output_dir",
        default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    args = _parse_args(argv)
    _set_seed(args.seed)

    logger.info("multitask train start :: args=%s", vars(args))
    t0 = time.time()

    # Lazy imports so the script can be linted on a minimal venv.
    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]
    import torch.nn as nn  # type: ignore[import-not-found,import-untyped,unused-ignore]
    from torch.utils.data import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
        DataLoader,
        Dataset,
    )
    from transformers import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
        AutoModel,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        get_linear_schedule_with_warmup,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(
        "device=%s gpu_count=%s",
        device,
        torch.cuda.device_count() if torch.cuda.is_available() else 0,
    )

    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    encoder = AutoModel.from_pretrained(args.model_name).to(device)
    hidden = encoder.config.hidden_size

    # Four heads.
    mlm_head = nn.Linear(hidden, tokenizer.vocab_size).to(device)
    ner_head = nn.Linear(hidden, args.num_ner_labels).to(device)
    rel_head = nn.Linear(hidden, args.num_rel_labels).to(device)
    rank_head = nn.Sequential(nn.Linear(hidden, 1), nn.Sigmoid()).to(device)

    class MultiTaskDataset(Dataset[dict[str, Any]]):
        def __init__(self, rows: list[dict[str, Any]]) -> None:
            self.rows = rows

        def __len__(self) -> int:
            return len(self.rows)

        def __getitem__(self, idx: int) -> dict[str, Any]:
            return self.rows[idx]

    train_rows = _read_jsonl(Path(args.train_data))
    val_rows = _read_jsonl(Path(args.val_data))
    logger.info("loaded train=%d val=%d", len(train_rows), len(val_rows))

    def collate(batch: list[dict[str, Any]]) -> dict[str, Any]:
        # Group by task; each minibatch is single-task for simplicity.
        # The DataLoader samples uniformly so over an epoch all tasks see updates.
        task = batch[0].get("task", "mlm")
        texts = [b.get("text", "") for b in batch]
        enc = tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=args.max_length,
            return_tensors="pt",
        )
        out: dict[str, Any] = {"task": task, "encoding": {k: v.to(device) for k, v in enc.items()}}
        if task == "ner":
            # NER labels per-token; aligned to the same max_length.
            ner_labels = []
            for b in batch:
                lbl = b.get("ner_labels") or []
                # truncate/pad to encoding length.
                seq_len = out["encoding"]["input_ids"].shape[1]
                lbl = (lbl[:seq_len] + [-100] * max(0, seq_len - len(lbl)))[:seq_len]
                ner_labels.append(lbl)
            out["labels"] = torch.tensor(ner_labels, dtype=torch.long, device=device)
        elif task == "rel":
            out["labels"] = torch.tensor(
                [int(b.get("rel_label", 0)) for b in batch], dtype=torch.long, device=device
            )
        elif task == "rank":
            out["labels"] = torch.tensor(
                [float(b.get("rank_score", 0.0)) for b in batch], dtype=torch.float, device=device
            )
        # mlm: handled by DataCollatorForLanguageModeling below.
        return out

    mlm_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm_probability=0.15)

    train_ds = MultiTaskDataset(train_rows)
    val_ds = MultiTaskDataset(val_rows)

    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=collate,
        num_workers=2,
        pin_memory=False,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=collate,
        num_workers=2,
        pin_memory=False,
    )

    params = (
        list(encoder.parameters())
        + list(mlm_head.parameters())
        + list(ner_head.parameters())
        + list(rel_head.parameters())
        + list(rank_head.parameters())
    )
    optimizer = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.01)
    total_steps = max(1, len(train_loader)) * max(1, args.epochs)
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(0.06 * total_steps),
        num_training_steps=total_steps,
    )

    ce = nn.CrossEntropyLoss(ignore_index=-100)
    mse = nn.MSELoss()

    encoder.train()
    step = 0
    for epoch in range(args.epochs):
        for batch in train_loader:
            task = batch["task"]
            enc = batch["encoding"]
            if task == "mlm":
                texts = tokenizer.batch_decode(enc["input_ids"], skip_special_tokens=True)
                mlm_batch = mlm_collator(
                    [tokenizer(t, max_length=args.max_length, truncation=True) for t in texts]
                )
                mlm_inputs = {k: v.to(device) for k, v in mlm_batch.items()}
                outputs = encoder(
                    input_ids=mlm_inputs["input_ids"],
                    attention_mask=mlm_inputs.get("attention_mask"),
                )
                hidden_states = outputs.last_hidden_state
                logits = mlm_head(hidden_states)
                loss = ce(
                    logits.view(-1, tokenizer.vocab_size),
                    mlm_inputs["labels"].view(-1),
                )
            elif task == "ner":
                outputs = encoder(**enc)
                logits = ner_head(outputs.last_hidden_state)
                loss = ce(logits.view(-1, args.num_ner_labels), batch["labels"].view(-1))
            elif task == "rel":
                outputs = encoder(**enc)
                cls = outputs.last_hidden_state[:, 0, :]
                logits = rel_head(cls)
                loss = ce(logits, batch["labels"])
            elif task == "rank":
                outputs = encoder(**enc)
                cls = outputs.last_hidden_state[:, 0, :]
                score = rank_head(cls).squeeze(-1)
                loss = mse(score, batch["labels"])
            else:
                continue

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, max_norm=1.0)
            optimizer.step()
            scheduler.step()

            if step % args.log_every_n_steps == 0:
                logger.info(
                    "epoch=%d step=%d task=%s loss=%.4f lr=%.2e elapsed=%.1fs",
                    epoch,
                    step,
                    task,
                    float(loss.detach().cpu()),
                    optimizer.param_groups[0]["lr"],
                    time.time() - t0,
                )
            step += 1

    # Validation pass (mlm perplexity proxy).
    encoder.eval()
    val_losses: list[float] = []
    with torch.no_grad():
        for batch in val_loader:
            task = batch["task"]
            enc = batch["encoding"]
            if task != "mlm":
                continue
            texts = tokenizer.batch_decode(enc["input_ids"], skip_special_tokens=True)
            mlm_batch = mlm_collator(
                [tokenizer(t, max_length=args.max_length, truncation=True) for t in texts]
            )
            mlm_inputs = {k: v.to(device) for k, v in mlm_batch.items()}
            outputs = encoder(
                input_ids=mlm_inputs["input_ids"],
                attention_mask=mlm_inputs.get("attention_mask"),
            )
            logits = mlm_head(outputs.last_hidden_state)
            loss = ce(
                logits.view(-1, tokenizer.vocab_size),
                mlm_inputs["labels"].view(-1),
            )
            val_losses.append(float(loss.cpu()))
    val_loss = sum(val_losses) / max(1, len(val_losses))
    val_ppl = math.exp(min(20.0, val_loss)) if val_loss else float("nan")
    logger.info("val_loss=%.4f val_ppl=%.2f", val_loss, val_ppl)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    encoder.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    torch.save(
        {
            "mlm_head": mlm_head.state_dict(),
            "ner_head": ner_head.state_dict(),
            "rel_head": rel_head.state_dict(),
            "rank_head": rank_head.state_dict(),
        },
        out_dir / "task_heads.pt",
    )
    (out_dir / "training_summary.json").write_text(
        json.dumps(
            {
                "model_name": args.model_name,
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "lr": args.lr,
                "max_length": args.max_length,
                "train_rows": len(train_rows),
                "val_rows": len(val_rows),
                "val_loss_mlm": val_loss,
                "val_ppl_mlm": val_ppl,
                "elapsed_sec": time.time() - t0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("done :: elapsed=%.1fs", time.time() - t0)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
