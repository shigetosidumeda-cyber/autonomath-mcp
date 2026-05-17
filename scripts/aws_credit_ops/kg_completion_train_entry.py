#!/usr/bin/env python3
"""Lane M7 — PyKEEN KG embedding training entrypoint (runs inside SageMaker).

Trains one of 4 KG embedding models (TransE / RotatE / ComplEx / ConvE)
on the jpcite knowledge graph extracted from ``am_relation`` and exported
to S3 by ``kg_completion_export_2026_05_17.py``.

Why these 4 models
------------------
- **TransE**  (Bordes et al. 2013): translational, lightweight, strong
  baseline. Models r as a translation h + r ≈ t in embedding space.
- **RotatE**  (Sun et al. 2019): rotation in complex space; handles
  symmetry / antisymmetry / inversion / composition patterns. Strong
  on bidirectional relations (``related``, ``compatible``).
- **ComplEx** (Trouillon et al. 2016): complex embeddings; excels at
  antisymmetric relations (``successor_of``, ``replaces``, ``prerequisite``).
- **ConvE**   (Dettmers et al. 2018): convolutional, parameter-efficient,
  high hits@10 on multi-hop reasoning; complementary to the 3 translational
  / bilinear baselines.

Ensemble averaging the 4 scoring functions yields strictly better hits@10
than any single model on FB15K-237 / WN18RR; the same dynamic should hold
on the jpcite KG.

SageMaker channel layout
------------------------
- Input channel ``train``    → ``/opt/ml/input/data/train/train.jsonl``
- Input channel ``val``      → ``/opt/ml/input/data/val/val.jsonl``
- Input channel ``test``     → ``/opt/ml/input/data/test/test.jsonl``
- Output                     → ``/opt/ml/model/`` (auto-tarred to S3)
- Hyperparameters injected via ``/opt/ml/input/config/hyperparameters.json``

Hyperparameters
---------------
- model (str)              — one of {TransE, RotatE, ComplEx, ConvE}
- embedding_dim (int=500)  — embedding dimension
- epochs (int=200)
- batch_size (int=512)
- negative_samples (int=256)
- learning_rate (float=1e-3)
- seed (int=42)

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
import os
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("kg_completion_train")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SUPPORTED_MODELS = ("TransE", "RotatE", "ComplEx", "ConvE")


def _load_hyperparameters() -> dict[str, Any]:
    """Load hyperparameters injected by SageMaker (JSON file)."""

    hp_path = Path("/opt/ml/input/config/hyperparameters.json")
    if hp_path.exists():
        try:
            return json.loads(hp_path.read_text())
        except (OSError, json.JSONDecodeError):
            logger.warning("could not parse hyperparameters.json; using defaults")
    return {}


def _read_jsonl(path: Path) -> list[tuple[str, str, str]]:
    triples: list[tuple[str, str, str]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            triples.append((obj["h"], obj["r"], obj["t"]))
    return triples


def _train_pykeen(
    *,
    model_name: str,
    train_triples: list[tuple[str, str, str]],
    val_triples: list[tuple[str, str, str]],
    test_triples: list[tuple[str, str, str]],
    embedding_dim: int,
    epochs: int,
    batch_size: int,
    negative_samples: int,
    learning_rate: float,
    seed: int,
    output_dir: Path,
) -> dict[str, Any]:
    """Train one PyKEEN model + evaluate hits@1/3/10 + MRR."""

    # Imports gated to runtime so this module is mypy-importable on the
    # macOS dev host (PyKEEN + torch are heavy GPU deps that only exist
    # inside the SageMaker container).
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415
    from pykeen.pipeline import pipeline  # noqa: PLC0415
    from pykeen.triples import TriplesFactory  # noqa: PLC0415

    np.random.seed(seed)
    torch.manual_seed(seed)

    # PyKEEN expects np.ndarray of shape (n, 3).
    train_arr = np.array(train_triples, dtype=str)
    val_arr = np.array(val_triples, dtype=str)
    test_arr = np.array(test_triples, dtype=str)

    training_factory = TriplesFactory.from_labeled_triples(train_arr)
    val_factory = TriplesFactory.from_labeled_triples(
        val_arr,
        entity_to_id=training_factory.entity_to_id,
        relation_to_id=training_factory.relation_to_id,
    )
    test_factory = TriplesFactory.from_labeled_triples(
        test_arr,
        entity_to_id=training_factory.entity_to_id,
        relation_to_id=training_factory.relation_to_id,
    )

    result = pipeline(
        training=training_factory,
        validation=val_factory,
        testing=test_factory,
        model=model_name,
        model_kwargs={"embedding_dim": embedding_dim},
        optimizer="Adam",
        optimizer_kwargs={"lr": learning_rate},
        training_loop="sLCWA",
        negative_sampler="basic",
        negative_sampler_kwargs={"num_negs_per_pos": negative_samples},
        training_kwargs={
            "num_epochs": epochs,
            "batch_size": batch_size,
            "use_tqdm_batch": False,
        },
        evaluation_kwargs={"use_tqdm": False},
        random_seed=seed,
        device="gpu" if torch.cuda.is_available() else "cpu",
    )

    # Save model + training summary
    result.save_to_directory(str(output_dir))
    metrics = result.metric_results.to_dict()

    # Pull the canonical 4-tuple (hits@1 / hits@3 / hits@10 / MRR).
    def _avg_side(metric: str, k: int | None = None) -> float:
        try:
            both = metrics["both"]
            real = both["realistic"]
            if k is None:
                return float(real[metric])
            return float(real[f"{metric}_at_{k}"])
        except (KeyError, TypeError):
            return float("nan")

    summary = {
        "model": model_name,
        "embedding_dim": embedding_dim,
        "epochs": epochs,
        "batch_size": batch_size,
        "negative_samples": negative_samples,
        "learning_rate": learning_rate,
        "seed": seed,
        "num_entities": training_factory.num_entities,
        "num_relations": training_factory.num_relations,
        "num_train_triples": len(train_triples),
        "num_val_triples": len(val_triples),
        "num_test_triples": len(test_triples),
        "metrics": {
            "hits_at_1": _avg_side("hits", 1),
            "hits_at_3": _avg_side("hits", 3),
            "hits_at_10": _avg_side("hits", 10),
            "mean_reciprocal_rank": _avg_side("inverse_harmonic_mean_rank"),
        },
    }
    (output_dir / "training_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    return summary


def _predict_missing_edges(
    *,
    model_name: str,
    output_dir: Path,
    threshold: float,
    sample_cap: int,
) -> dict[str, Any]:
    """Score head-relation-? completions; emit predictions above threshold.

    For each (h, r) appearing in train, score all candidate t entities
    using the trained model and emit (h, r, t) with score >= ``threshold``
    that are NOT already in train. Capped at ``sample_cap`` per (h, r)
    to keep output bounded.
    """

    import torch  # noqa: PLC0415

    model_path = output_dir / "trained_model.pkl"
    if not model_path.exists():
        logger.warning("trained model file missing; skipping inference: %s", model_path)
        return {"predicted_count": 0, "threshold": threshold}

    model = torch.load(model_path, map_location="cpu", weights_only=False)
    model.eval()
    # Inference is wave-19 follow-up — for the live training pass we emit
    # only the summary; an offline aggregator joins all 4 model outputs
    # post-fact (see ``kg_completion_aggregate.py`` follow-up).
    return {
        "predicted_count": 0,
        "threshold": threshold,
        "sample_cap": sample_cap,
        "deferred_to_aggregator": True,
    }


def main(argv: list[str] | None = None) -> int:
    hp_file = _load_hyperparameters()

    p = argparse.ArgumentParser()
    p.add_argument("--model", default=hp_file.get("model", "TransE"), choices=SUPPORTED_MODELS)
    p.add_argument("--embedding-dim", type=int, default=int(hp_file.get("embedding_dim", 500)))
    p.add_argument("--epochs", type=int, default=int(hp_file.get("epochs", 200)))
    p.add_argument("--batch-size", type=int, default=int(hp_file.get("batch_size", 512)))
    p.add_argument(
        "--negative-samples",
        type=int,
        default=int(hp_file.get("negative_samples", 256)),
    )
    p.add_argument(
        "--learning-rate",
        type=float,
        default=float(hp_file.get("learning_rate", 1e-3)),
    )
    p.add_argument("--seed", type=int, default=int(hp_file.get("seed", 42)))
    p.add_argument(
        "--threshold",
        type=float,
        default=float(hp_file.get("threshold", 0.85)),
        help="confidence threshold for missing edge prediction (post-train)",
    )
    p.add_argument(
        "--sample-cap",
        type=int,
        default=int(hp_file.get("sample_cap", 10)),
        help="max candidate tails to keep per (h,r) during inference",
    )
    p.add_argument("--train-path", default="/opt/ml/input/data/train/train.jsonl")
    p.add_argument("--val-path", default="/opt/ml/input/data/val/val.jsonl")
    p.add_argument("--test-path", default="/opt/ml/input/data/test/test.jsonl")
    p.add_argument("--output-dir", default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
    args = p.parse_args(argv)

    start = time.time()

    train_triples = _read_jsonl(Path(args.train_path))
    val_triples = _read_jsonl(Path(args.val_path))
    test_triples = _read_jsonl(Path(args.test_path))
    logger.info(
        "loaded triples train=%d val=%d test=%d",
        len(train_triples),
        len(val_triples),
        len(test_triples),
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = _train_pykeen(
        model_name=args.model,
        train_triples=train_triples,
        val_triples=val_triples,
        test_triples=test_triples,
        embedding_dim=args.embedding_dim,
        epochs=args.epochs,
        batch_size=args.batch_size,
        negative_samples=args.negative_samples,
        learning_rate=args.learning_rate,
        seed=args.seed,
        output_dir=out_dir,
    )

    prediction = _predict_missing_edges(
        model_name=args.model,
        output_dir=out_dir,
        threshold=args.threshold,
        sample_cap=args.sample_cap,
    )

    summary["elapsed_seconds"] = round(time.time() - start, 2)
    summary["prediction"] = prediction
    (out_dir / "training_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )

    logger.info("training summary: %s", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
