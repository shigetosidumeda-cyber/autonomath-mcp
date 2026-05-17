"""Lane M8 v0.2 — SageMaker Batch Transform inference handler.

Runs inside the HuggingFace Inference container. Loads the M6
fine-tuned cross-encoder from ``/opt/ml/model`` and scores incoming
``(query, doc)`` pairs.

The HuggingFace Inference Toolkit looks for the following hook names
in this module:

- ``model_fn(model_dir)`` — load model + tokenizer from
  ``/opt/ml/model``.
- ``input_fn(input_data, content_type)`` — parse the request body.
- ``predict_fn(inputs, model)`` — run inference.
- ``output_fn(prediction, accept)`` — serialise the response.

Input contract
--------------
``application/jsonlines`` body, one JSON object per line:

.. code-block:: json

    {"candidate_id": 1, "court_unified_id": "HAN-...", "article_id": 42,
     "v01_score": 0.61, "query": "court text ...", "doc": "law text ..."}

Output contract
---------------
Same JSON object echoed back with ``cross_score`` and
``cross_label`` fields added.

NO LLM API. The fine-tuned cross-encoder is a HuggingFace
``AutoModelForSequenceClassification`` with ``num_labels=1``, served
locally inside the container.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def model_fn(model_dir: str) -> tuple[Any, Any, Any]:
    """Load the fine-tuned cross-encoder + tokenizer + torch.

    Returns a 3-tuple so ``predict_fn`` can stay framework-agnostic.
    """
    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]
    from transformers import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
        AutoModelForSequenceClassification,
        AutoTokenizer,
    )

    md = Path(model_dir)
    tokenizer = AutoTokenizer.from_pretrained(str(md))
    model = AutoModelForSequenceClassification.from_pretrained(str(md))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()
    return model, tokenizer, device


def input_fn(input_data: bytes | str, content_type: str) -> list[dict[str, Any]]:
    """Parse one or more JSONL lines into Python dicts."""

    text = input_data.decode("utf-8") if isinstance(input_data, bytes) else input_data
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(obj)
    return out


def predict_fn(
    inputs: list[dict[str, Any]],
    model_pack: tuple[Any, Any, Any],
) -> list[dict[str, Any]]:
    """Score each ``(query, doc)`` pair and attach ``cross_score``."""

    import torch  # type: ignore[import-not-found,import-untyped,unused-ignore]

    model, tokenizer, device = model_pack
    out: list[dict[str, Any]] = []
    batch_size = 32
    for i in range(0, len(inputs), batch_size):
        batch = inputs[i : i + batch_size]
        queries = [str(b.get("query") or "") for b in batch]
        docs = [str(b.get("doc") or "") for b in batch]
        # Cross-encoder concat: tokenizer handles [SEP] separation.
        encoded = tokenizer(
            queries,
            docs,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        ).to(device)
        with torch.no_grad():
            logits = model(**encoded).logits.squeeze(-1)
            probs = torch.sigmoid(logits).detach().cpu().tolist()
        for b, p in zip(batch, probs, strict=False):
            row = dict(b)
            row["cross_score"] = float(p)
            row["cross_label"] = 1 if float(p) >= 0.5 else 0
            out.append(row)
    return out


def output_fn(prediction: list[dict[str, Any]], accept: str) -> str:
    """Serialise back to JSONL."""

    lines: list[str] = []
    for r in prediction:
        lines.append(json.dumps(r, ensure_ascii=False))
    return "\n".join(lines) + "\n"
