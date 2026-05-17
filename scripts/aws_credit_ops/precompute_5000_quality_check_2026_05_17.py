#!/usr/bin/env python3
"""GG2 — Quality check for am_precomputed_answer (~5,000 row).

Deterministic, NO LLM. Per-row checks:

- ``len(answer_text) > 200`` chars
- ``citation_count >= 2``
- cohort vocabulary contained somewhere in answer_text or question_text
- non-empty sections (``sections_jsonb``)
- ``q_hash`` not NULL
- ``freshness_state`` in {fresh, stale, unknown}

Output:
    ``data/precompute_5000_quality_2026_05_17.json``
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

logger = logging.getLogger("jpcite.gg2.qcheck")


_COHORT_VOCAB: dict[str, tuple[str, ...]] = {
    "tax": ("税", "法人", "申告", "消費", "源泉", "所得", "決算", "勘定", "仕訳", "課税"),
    "audit": (
        "監査",
        "会計",
        "内部統制",
        "リスク",
        "報告",
        "意見",
        "基準",
        "重要",
        "見積",
        "証拠",
    ),
    "gyousei": (
        "許可",
        "申請",
        "建設",
        "産廃",
        "在留",
        "風営",
        "古物",
        "登録",
        "業務",
        "書類",
        "認可",
        "手続",
        "補助",
        "助成",
        "契約",
        "法人",
    ),
    "shihoshoshi": ("登記", "司法", "成年後見", "供託", "裁判", "代理"),
    "chusho_keieisha": ("補助金", "経営", "事業", "承継", "計画", "中小", "革新", "助成", "支援"),
}


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "autonomath.db"


def _row_passes(row: sqlite3.Row) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    answer_text = row["answer_text"] or ""
    if len(answer_text) <= 200:
        reasons.append(f"answer_text_short:{len(answer_text)}")
    citation_count = int(row["citation_count"] or 0)
    if citation_count < 2:
        reasons.append(f"citation_count_low:{citation_count}")
    cohort = row["cohort"]
    vocab = _COHORT_VOCAB.get(cohort, ())
    haystack = answer_text + " " + (row["question_text"] or "")
    has_vocab = any(v in haystack for v in vocab)
    if vocab and not has_vocab:
        reasons.append("cohort_vocab_missing")
    try:
        sections = json.loads(row["sections_jsonb"] or "[]")
        if not isinstance(sections, list) or len(sections) == 0:
            reasons.append("sections_empty")
        else:
            for s in sections:
                if not isinstance(s, dict) or not s.get("body"):
                    reasons.append("section_body_missing")
                    break
    except json.JSONDecodeError:
        reasons.append("sections_jsonb_parse_fail")
    if not row["q_hash"]:
        reasons.append("q_hash_null")
    fs = row["freshness_state"]
    if fs not in ("fresh", "stale", "unknown"):
        reasons.append(f"freshness_state_invalid:{fs}")
    return (len(reasons) == 0, reasons)


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("jpcite.gg2.qcheck")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GG2 — quality check for precompute 5,000.")
    parser.add_argument("--out", default="data/precompute_5000_quality_2026_05_17.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    db_path = _autonomath_db_path()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT answer_id, cohort, faq_slug, q_hash, question_text, "
            "answer_text, citation_count, sections_jsonb, freshness_state "
            "FROM am_precomputed_answer"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    logger.info("checking %d rows", len(rows))
    total = len(rows)
    passed = 0
    per_cohort: dict[str, dict[str, int]] = {}
    failures: list[dict[str, object]] = []

    for row in rows:
        ok, reasons = _row_passes(row)
        c = row["cohort"]
        per_cohort.setdefault(c, {"total": 0, "passed": 0, "failed": 0})
        per_cohort[c]["total"] += 1
        if ok:
            per_cohort[c]["passed"] += 1
            passed += 1
        else:
            per_cohort[c]["failed"] += 1
            if len(failures) < 100:
                failures.append(
                    {
                        "answer_id": row["answer_id"],
                        "cohort": c,
                        "faq_slug": row["faq_slug"],
                        "reasons": reasons,
                    }
                )

    pass_rate = passed / max(1, total)
    summary = {
        "total_rows": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(pass_rate, 4),
        "pass_rate_target": 0.95,
        "gate_pass": pass_rate >= 0.95,
        "per_cohort": per_cohort,
        "failure_samples_first_100": failures,
        "checked_at": _dt.datetime.now().isoformat(),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "quality check: pass_rate=%.2f%% (%d/%d) gate=%s; wrote %s",
        pass_rate * 100,
        passed,
        total,
        summary["gate_pass"],
        out_path,
    )
    return 0 if summary["gate_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
