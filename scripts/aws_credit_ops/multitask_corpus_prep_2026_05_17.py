#!/usr/bin/env python3
"""Lane M11 Day 1 — Build the multi-task training corpus (local, then upload to S3).

Generates a `train.jsonl` / `val.jsonl` pair where each row is one of:

- ``{"task":"mlm", "text": ...}``                          — masked LM source (largest share).
- ``{"task":"ner", "text": ..., "ner_labels":[int, ...]}`` — token-level NER labels via regex.
- ``{"task":"rel", "text": ..., "rel_label": int}``        — relation class.
- ``{"task":"rank","text": ..., "rank_score": float}``     — tier+adoption derived rank in [0,1].

Sources (in priority order, all in-corpus, NO LLM):

- `data/jpintel.db: programs` (text = title + program_overview) — feeds mlm + ner + rank.
- `data/jpintel.db: case_studies` — feeds mlm + rel (program ↔ outcome).
- `autonomath.db: am_law_article` — feeds mlm + ner (law text).
- The existing `finetune_corpus/train.jsonl` (Lane M5) — for mlm pad if needed.

Falls back to a synthetic stub if no DB is reachable so the script can dry-run
inside CI. ``[lane:solo]`` marker, NO LLM API.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

# Regex-derived NER labels (mirror Lane M1 ontology, BIO scheme).
NER_LABELS: Final[list[str]] = [
    "O",
    "B-CORP",
    "I-CORP",
    "B-PROG",
    "I-PROG",
    "B-LAW",
    "I-LAW",
    "B-AUTH",
    "I-AUTH",
    "B-AMT",
    "I-AMT",
    "B-DATE",
    "I-DATE",
    "B-REGION",
    "I-REGION",
]
NER_LABEL2ID: Final[dict[str, int]] = {lab: i for i, lab in enumerate(NER_LABELS)}

CORP_PAT = re.compile(
    r"(株式会社[\w・ー]{1,30}|有限会社[\w・ー]{1,30}|一般社団法人[\w・ー]{1,30}|"
    r"公益財団法人[\w・ー]{1,30}|学校法人[\w・ー]{1,30}|医療法人[\w・ー]{1,30})"
)
PROG_PAT = re.compile(
    r"([\w・ー]{2,40}(?:補助金|助成金|支援事業|給付金|奨励金|税額控除|減税|交付金))"
)
LAW_PAT = re.compile(
    r"([\w・ー]{2,40}(?:法|令|規則|施行令|施行規則)(?:第\d+条(?:第\d+項)?(?:第\d+号)?)?)"
)
AUTH_PAT = re.compile(
    r"((?:経済産業省|厚生労働省|農林水産省|文部科学省|国土交通省|"
    r"内閣府|総務省|財務省|環境省|外務省|防衛省|国税庁|"
    r"中小企業庁|金融庁|消費者庁|デジタル庁|"
    r"\w{1,8}(?:県|府|都|道)庁?|\w{1,8}(?:市|町|村))"
    r")"
)
AMT_PAT = re.compile(r"(\d[\d,]*(?:\.\d+)?(?:億|万|千|百)?円)")
DATE_PAT = re.compile(r"(\d{4}年\d{1,2}月\d{1,2}日|令和\d+年\d+月\d+日|\d{4}/\d{1,2}/\d{1,2})")
REGION_PAT = re.compile(
    r"((?:北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|"
    r"群馬県|埼玉県|千葉県|東京都|神奈川県|新潟県|富山県|石川県|福井県|"
    r"山梨県|長野県|岐阜県|静岡県|愛知県|三重県|滋賀県|京都府|大阪府|"
    r"兵庫県|奈良県|和歌山県|鳥取県|島根県|岡山県|広島県|山口県|徳島県|"
    r"香川県|愛媛県|高知県|福岡県|佐賀県|長崎県|熊本県|大分県|宮崎県|"
    r"鹿児島県|沖縄県))"
)

# Relation labels (program-centric mini-ontology).
REL_LABELS: Final[list[str]] = [
    "NONE",
    "PROGRAM_OF_AUTHORITY",
    "PROGRAM_HAS_LAW_REF",
    "PROGRAM_HAS_AMOUNT",
    "PROGRAM_HAS_DEADLINE",
    "PROGRAM_FOR_REGION",
    "PROGRAM_FOR_INDUSTRY",
    "CASE_ADOPTED_PROGRAM",
    "CASE_FOR_CORP",
    "ENFORCEMENT_AGAINST_CORP",
    "ENFORCEMENT_REFERS_LAW",
    "INVOICE_FOR_CORP",
    "LAW_AMENDS_LAW",
    "TAX_RULE_FROM_LAW",
    "LOAN_FROM_AUTHORITY",
    "RELATED_PROGRAM",
]
REL_LABEL2ID: Final[dict[str, int]] = {lab: i for i, lab in enumerate(REL_LABELS)}


def char_label_to_bio(text: str, span_label: str, char_labels: list[str]) -> None:
    """In-place BIO marking helper."""
    return None  # Helpers are written inline below for clarity.


def label_text_ner(text: str) -> list[int]:
    """Apply regex set and emit a per-character BIO label sequence, then return
    char-level integer labels (the trainer pads/aligns to tokenizer output later)."""
    n = len(text)
    chars: list[str] = ["O"] * n

    def mark(pat: re.Pattern[str], entity: str) -> None:
        for m in pat.finditer(text):
            s, e = m.span()
            if s >= n or e > n or s == e:
                continue
            if any(c != "O" for c in chars[s:e]):
                continue
            chars[s] = f"B-{entity}"
            for i in range(s + 1, e):
                chars[i] = f"I-{entity}"

    mark(CORP_PAT, "CORP")
    mark(PROG_PAT, "PROG")
    mark(LAW_PAT, "LAW")
    mark(AUTH_PAT, "AUTH")
    mark(AMT_PAT, "AMT")
    mark(DATE_PAT, "DATE")
    mark(REGION_PAT, "REGION")
    return [NER_LABEL2ID.get(lab, 0) for lab in chars]


def _open_db(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _iter_programs(conn: sqlite3.Connection) -> Iterable[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        "SELECT primary_name, COALESCE(authority_name,''), tier, "
        "COALESCE(amount_max_man_yen, 0) FROM programs "
        "WHERE excluded=0 AND tier IN ('S','A','B','C')"
    )
    for name, authority, tier, amt in cur.fetchall():
        text = f"{name or ''} {authority or ''}".strip()
        if len(text) < 8:
            continue
        tier_val = {"S": 1.0, "A": 0.85, "B": 0.6, "C": 0.4}.get(tier or "", 0.3)
        ac_val = min(1.0, math.log1p(max(0, amt or 0)) / math.log1p(10000))
        rank_score = 0.6 * tier_val + 0.4 * ac_val
        yield {"text": text[:512], "rank_score": float(rank_score)}


def _iter_cases(conn: sqlite3.Connection) -> Iterable[str]:
    cur = conn.cursor()
    try:
        cur.execute("SELECT case_title, case_summary FROM case_studies LIMIT 5000")
    except sqlite3.Error:
        return
    for title, summary in cur.fetchall():
        text = f"{title or ''} {summary or ''}".strip()
        if len(text) >= 16:
            yield text[:512]


def _iter_law_articles(conn: sqlite3.Connection, limit: int) -> Iterable[str]:
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT COALESCE(text_full, text_summary, '') FROM am_law_article "
            f"WHERE COALESCE(text_full, text_summary, '') != '' LIMIT {int(limit)}"
        )
    except sqlite3.Error:
        return
    for (body,) in cur.fetchall():
        if body and len(body) >= 16:
            yield body[:512]


def _classify_relation(text: str) -> str:
    has_corp = bool(CORP_PAT.search(text))
    has_prog = bool(PROG_PAT.search(text))
    has_law = bool(LAW_PAT.search(text))
    has_auth = bool(AUTH_PAT.search(text))
    has_amt = bool(AMT_PAT.search(text))
    has_date = bool(DATE_PAT.search(text))
    has_region = bool(REGION_PAT.search(text))
    if has_prog and has_auth:
        return "PROGRAM_OF_AUTHORITY"
    if has_prog and has_law:
        return "PROGRAM_HAS_LAW_REF"
    if has_prog and has_amt:
        return "PROGRAM_HAS_AMOUNT"
    if has_prog and has_date:
        return "PROGRAM_HAS_DEADLINE"
    if has_prog and has_region:
        return "PROGRAM_FOR_REGION"
    if has_corp and has_prog:
        return "CASE_ADOPTED_PROGRAM"
    if has_corp:
        return "CASE_FOR_CORP"
    if has_law:
        return "TAX_RULE_FROM_LAW"
    return "NONE"


import math  # noqa: E402  (used inside _iter_programs)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build multi-task training corpus for Lane M11.")
    p.add_argument("--jpintel-db", default="data/jpintel.db")
    p.add_argument("--autonomath-db", default="autonomath.db")
    p.add_argument("--out-dir", default="data/finetune_corpus_multitask")
    p.add_argument("--law-rows", type=int, default=20000)
    p.add_argument("--mlm-rows-cap", type=int, default=200000)
    p.add_argument("--val-ratio", type=float, default=0.05)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    random.seed(args.seed)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    counts = {"mlm": 0, "ner": 0, "rel": 0, "rank": 0}

    jpi = _open_db(Path(args.jpintel_db))
    am = _open_db(Path(args.autonomath_db))

    # 1. Programs -> rank + ner + mlm + rel
    if jpi is not None:
        for row in _iter_programs(jpi):
            text = row["text"]
            rows.append({"task": "rank", "text": text, "rank_score": row["rank_score"]})
            counts["rank"] += 1
            rows.append({"task": "ner", "text": text, "ner_labels": label_text_ner(text)})
            counts["ner"] += 1
            rel = _classify_relation(text)
            rows.append({"task": "rel", "text": text, "rel_label": REL_LABEL2ID[rel]})
            counts["rel"] += 1
            rows.append({"task": "mlm", "text": text})
            counts["mlm"] += 1

        # 2. case_studies -> rel + mlm
        for text in _iter_cases(jpi):
            rel = _classify_relation(text)
            rows.append({"task": "rel", "text": text, "rel_label": REL_LABEL2ID[rel]})
            counts["rel"] += 1
            rows.append({"task": "mlm", "text": text})
            counts["mlm"] += 1

    # 3. am_law_article -> mlm + ner
    if am is not None:
        for body in _iter_law_articles(am, args.law_rows):
            rows.append({"task": "mlm", "text": body})
            counts["mlm"] += 1
            if random.random() < 0.2:
                rows.append({"task": "ner", "text": body, "ner_labels": label_text_ner(body)})
                counts["ner"] += 1

    if not rows:
        # Fallback stub for CI / no-DB environments.
        for i in range(64):
            text = f"令和{(i % 6) + 1}年度 経済産業省 IT導入補助金 採択 株式会社サンプル{i}。"
            rows.append({"task": "mlm", "text": text})
            rows.append({"task": "ner", "text": text, "ner_labels": label_text_ner(text)})
            rows.append(
                {"task": "rel", "text": text, "rel_label": REL_LABEL2ID["PROGRAM_OF_AUTHORITY"]}
            )
            rows.append({"task": "rank", "text": text, "rank_score": 0.5})
            counts = {k: counts[k] + 1 for k in counts}

    random.shuffle(rows)
    if counts["mlm"] > args.mlm_rows_cap:
        # Trim mlm; keep all ner/rel/rank.
        mlm_kept = 0
        new_rows: list[dict[str, Any]] = []
        for r in rows:
            if r["task"] == "mlm":
                if mlm_kept >= args.mlm_rows_cap:
                    continue
                mlm_kept += 1
            new_rows.append(r)
        rows = new_rows

    split_at = max(1, int(len(rows) * (1 - args.val_ratio)))
    train_rows = rows[:split_at]
    val_rows = rows[split_at:]

    train_path = out_dir / "train.jsonl"
    val_path = out_dir / "val.jsonl"
    with train_path.open("w", encoding="utf-8") as fh:
        for r in train_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with val_path.open("w", encoding="utf-8") as fh:
        for r in val_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": args.seed,
        "counts_per_task_total": counts,
        "train_rows": len(train_rows),
        "val_rows": len(val_rows),
        "ner_label_count": len(NER_LABELS),
        "rel_label_count": len(REL_LABELS),
        "ner_labels": NER_LABELS,
        "rel_labels": REL_LABELS,
    }
    (out_dir / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"ok": True, "manifest": manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
