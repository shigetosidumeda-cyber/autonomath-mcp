#!/usr/bin/env python3
"""Lane M7 — Export am_relation triples to S3 for KG embedding training.

Reads ``am_relation`` from the canonical ``autonomath.db`` and exports a
train/val/test JSONL split for PyKEEN 4-model ensemble training
(TransE / RotatE / ComplEx / ConvE) running inside SageMaker.

Output layout (S3)::

    s3://jpcite-credit-993693061769-202605-derived/kg_corpus/train.jsonl
    s3://jpcite-credit-993693061769-202605-derived/kg_corpus/val.jsonl
    s3://jpcite-credit-993693061769-202605-derived/kg_corpus/test.jsonl
    s3://.../kg_corpus/_manifest.json
    s3://.../kg_corpus/entity_id_map.jsonl      (entity_id -> int idx)
    s3://.../kg_corpus/relation_id_map.jsonl    (relation_type -> int idx)

JSONL row format (compact)::

    {"h": "<source_entity_id>", "r": "<relation_type>", "t": "<target_entity_id>"}

Constraints
-----------
- DRY_RUN default; ``--commit`` actually writes to S3.
- NO LLM API.
- ``[lane:solo]`` marker.
- ruff / mypy clean.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import random
import sqlite3
import sys
from pathlib import Path
from typing import Final

DEFAULT_DB: Final[str] = "autonomath.db"
DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_PREFIX: Final[str] = "kg_corpus"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"

# 80/10/10 split is canonical for KG embedding benchmarks (FB15K-237 / WN18RR).
SPLIT_TRAIN: Final[float] = 0.80
SPLIT_VAL: Final[float] = 0.10
# test = remainder = 0.10

# Drop relation types with fewer than this many edges. Embedding models
# cannot learn relation parameters from < 10 examples; including them
# just adds noise. ``related`` (207K) / ``part_of`` (146K) / ``has_authority``
# (7K) easily clear this bar; ``replaces`` (2) / ``applies_to`` (17) get dropped.
MIN_RELATION_COUNT: Final[int] = 10


def _load_triples(db_path: Path) -> list[tuple[str, str, str]]:
    """Read every (h, r, t) where target_entity_id is non-null."""

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT source_entity_id AS h,
                   relation_type    AS r,
                   target_entity_id AS t
              FROM am_relation
             WHERE target_entity_id IS NOT NULL
               AND source_entity_id IS NOT NULL
               AND relation_type    IS NOT NULL
            """
        ).fetchall()
    finally:
        conn.close()
    return [(r["h"], r["r"], r["t"]) for r in rows]


def _filter_by_relation_count(
    triples: list[tuple[str, str, str]], min_count: int
) -> tuple[list[tuple[str, str, str]], dict[str, int]]:
    """Drop relations with < min_count edges; return (kept, per_relation_count)."""

    rel_count: dict[str, int] = {}
    for _h, r, _t in triples:
        rel_count[r] = rel_count.get(r, 0) + 1
    keep_rels = {r for r, c in rel_count.items() if c >= min_count}
    kept = [tr for tr in triples if tr[1] in keep_rels]
    return kept, rel_count


def _split(
    triples: list[tuple[str, str, str]], seed: int
) -> tuple[
    list[tuple[str, str, str]],
    list[tuple[str, str, str]],
    list[tuple[str, str, str]],
]:
    """Random shuffle + 80/10/10 split."""

    rng = random.Random(seed)
    pool = list(triples)
    rng.shuffle(pool)
    n = len(pool)
    n_train = int(n * SPLIT_TRAIN)
    n_val = int(n * SPLIT_VAL)
    return pool[:n_train], pool[n_train : n_train + n_val], pool[n_train + n_val :]


def _to_jsonl(triples: list[tuple[str, str, str]]) -> bytes:
    """Serialize triples to JSONL bytes."""

    buf = io.BytesIO()
    for h, r, t in triples:
        line = json.dumps({"h": h, "r": r, "t": t}, ensure_ascii=False)
        buf.write(line.encode("utf-8"))
        buf.write(b"\n")
    return buf.getvalue()


def _build_id_maps(
    triples: list[tuple[str, str, str]],
) -> tuple[dict[str, int], dict[str, int]]:
    """Deterministic entity / relation int-id map (sorted by surface key)."""

    ents: set[str] = set()
    rels: set[str] = set()
    for h, r, t in triples:
        ents.add(h)
        ents.add(t)
        rels.add(r)
    entity_map = {e: i for i, e in enumerate(sorted(ents))}
    relation_map = {r: i for i, r in enumerate(sorted(rels))}
    return entity_map, relation_map


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--prefix", default=DEFAULT_PREFIX)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--min-rel-count", type=int, default=MIN_RELATION_COUNT)
    p.add_argument("--commit", action="store_true", help="actually upload (default DRY_RUN)")
    args = p.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[FAIL] db missing: {db_path}", file=sys.stderr)
        return 2

    print(f"[load] reading triples from {db_path}", file=sys.stderr)
    triples = _load_triples(db_path)
    print(f"[load] {len(triples):,} triples raw", file=sys.stderr)

    kept, rel_count = _filter_by_relation_count(triples, args.min_rel_count)
    dropped_rels = {r: c for r, c in rel_count.items() if c < args.min_rel_count}
    print(
        f"[filter] {len(kept):,} triples kept; "
        f"dropped {len(triples) - len(kept):,} edges across "
        f"{len(dropped_rels)} rare relations: {dropped_rels}",
        file=sys.stderr,
    )

    train, val, test = _split(kept, args.seed)
    print(
        f"[split] train={len(train):,} val={len(val):,} test={len(test):,}",
        file=sys.stderr,
    )

    entity_map, relation_map = _build_id_maps(kept)
    print(
        f"[ids] entities={len(entity_map):,} relations={len(relation_map):,}",
        file=sys.stderr,
    )

    train_b = _to_jsonl(train)
    val_b = _to_jsonl(val)
    test_b = _to_jsonl(test)

    ent_map_b = (
        "\n".join(
            json.dumps({"surface": k, "idx": v}, ensure_ascii=False) for k, v in entity_map.items()
        )
        + "\n"
    ).encode("utf-8")
    rel_map_b = (
        "\n".join(
            json.dumps({"surface": k, "idx": v}, ensure_ascii=False)
            for k, v in relation_map.items()
        )
        + "\n"
    ).encode("utf-8")

    manifest = {
        "wave": "M7",
        "lane": "solo",
        "exported_at": dt.datetime.now(dt.UTC).isoformat(),
        "db_path": str(db_path),
        "seed": args.seed,
        "split": {
            "train": SPLIT_TRAIN,
            "val": SPLIT_VAL,
            "test": round(1 - SPLIT_TRAIN - SPLIT_VAL, 6),
        },
        "raw_triple_count": len(triples),
        "kept_triple_count": len(kept),
        "dropped_relation_count": len(dropped_rels),
        "min_relation_count": args.min_rel_count,
        "train_count": len(train),
        "val_count": len(val),
        "test_count": len(test),
        "entity_count": len(entity_map),
        "relation_count": len(relation_map),
        "relation_distribution": dict(sorted(rel_count.items(), key=lambda x: -x[1])),
        "sha256": {
            "train.jsonl": _sha256(train_b),
            "val.jsonl": _sha256(val_b),
            "test.jsonl": _sha256(test_b),
            "entity_id_map.jsonl": _sha256(ent_map_b),
            "relation_id_map.jsonl": _sha256(rel_map_b),
        },
        "size_bytes": {
            "train.jsonl": len(train_b),
            "val.jsonl": len(val_b),
            "test.jsonl": len(test_b),
            "entity_id_map.jsonl": len(ent_map_b),
            "relation_id_map.jsonl": len(rel_map_b),
        },
    }
    manifest_b = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

    objects = {
        f"{args.prefix}/train.jsonl": train_b,
        f"{args.prefix}/val.jsonl": val_b,
        f"{args.prefix}/test.jsonl": test_b,
        f"{args.prefix}/entity_id_map.jsonl": ent_map_b,
        f"{args.prefix}/relation_id_map.jsonl": rel_map_b,
        f"{args.prefix}/_manifest.json": manifest_b,
    }

    print(
        json.dumps(
            {
                "summary": {
                    "train_count": len(train),
                    "val_count": len(val),
                    "test_count": len(test),
                    "entity_count": len(entity_map),
                    "relation_count": len(relation_map),
                    "kept_count": len(kept),
                    "size_bytes": manifest["size_bytes"],
                }
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if not args.commit:
        print(
            f"[DRY_RUN] would upload {len(objects)} objects to s3://{args.bucket}/{args.prefix}/",
            file=sys.stderr,
        )
        for k, v in objects.items():
            print(
                f"[DRY_RUN]   {k}  {len(v):,} bytes",
                file=sys.stderr,
            )
        return 0

    # Live upload — same gate as M5 driver: ``--commit`` opt-in only.
    from scripts.aws_credit_ops._aws import s3_client  # noqa: PLC0415

    s3 = s3_client(region_name=args.region, profile_name=args.profile)
    for key, body in objects.items():
        s3.put_object(
            Bucket=args.bucket,
            Key=key,
            Body=body,
            ContentType=("application/json" if key.endswith(".json") else "application/jsonlines"),
        )
        print(f"[OK] uploaded s3://{args.bucket}/{key} ({len(body):,} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
