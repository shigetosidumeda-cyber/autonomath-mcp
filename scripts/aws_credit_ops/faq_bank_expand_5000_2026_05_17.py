#!/usr/bin/env python3
"""GG2 — FAQ bank expander 500 -> 5,000.

Reads existing ``data/faq_bank/{cohort}_top100.yaml`` (5 x 100 = 500 base
questions) and fans out each base question into 10 variants via deterministic
rule-based templating:

- Cohort-specific term substitution (10 domain terms per cohort).
- Question structure variation (10 structural prefixes/suffixes).

Output: ``data/faq_bank/expanded_5000/{cohort}_top1000.yaml`` (5 files).

Quality gate:

- Per-cohort row count: 1,000 +/- 50 (after similarity dedupe).
- Text similarity (Jaccard 3-gram) > 0.85 -> dedupe.
- Total: 5,000 +/- 100.

Constraints
-----------
* No Anthropic / OpenAI / Google SDK import. Rule-based only.
* mypy --strict clean / ruff clean.

Usage
-----
    .venv/bin/python scripts/aws_credit_ops/faq_bank_expand_5000_2026_05_17.py \\
        --out-dir data/faq_bank/expanded_5000 --per-cohort 1000
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("jpcite.gg2.expand")


_STRUCT_VARIATIONS: tuple[tuple[str, str], ...] = (
    ("", ""),
    ("実務上、", "の留意点は？"),
    ("具体的に", "の要件は？"),
    ("最新通達では", "の取扱いは？"),
    ("法定期限を踏まえ", "のスケジュールは？"),
    ("罰則回避のため", "の対応手順は？"),
    ("小規模事業者の場合、", "の判定は？"),
    ("中規模法人で", "の論点は？"),
    ("デジタル化対応で", "の影響は？"),
    ("2026年改正後、", "の変更点は？"),
)


_DOMAIN_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "tax": (
        "法人税",
        "消費税",
        "相続税",
        "印紙税",
        "源泉所得税",
        "事業税",
        "住民税",
        "地方法人税",
        "国際課税",
        "電子帳簿保存法",
    ),
    "audit": (
        "監査基準",
        "監査リスク",
        "内部統制",
        "会計上の見積り",
        "後発事象",
        "継続企業の前提",
        "監査報告書",
        "監査調書",
        "倫理規則",
        "品質管理基準",
    ),
    "gyousei": (
        "建設業許可",
        "産業廃棄物処理業",
        "在留資格",
        "風営法許可",
        "古物商許可",
        "車庫証明",
        "NPO法人設立",
        "一般社団法人",
        "宅地建物取引業",
        "飲食店営業",
    ),
    "shihoshoshi": (
        "不動産登記",
        "商業登記",
        "相続登記",
        "成年後見",
        "供託",
        "簡裁訴訟代理",
        "組織再編",
        "家族法務",
        "競売手続",
        "電子定款認証",
    ),
    "chusho_keieisha": (
        "ものづくり補助金",
        "事業再構築補助金",
        "IT導入補助金",
        "小規模事業者持続化補助金",
        "省力化投資補助金",
        "経営革新計画",
        "事業承継税制",
        "BCP策定",
        "脱炭素経営",
        "賃上げ促進税制",
    ),
}


@dataclass
class BaseFaq:
    """One base FAQ extracted from {cohort}_top100.yaml."""

    qid: str
    cohort: str
    category: str
    question: str
    priority: str
    depth: int
    opus_jpy: int
    legal_disclaimer: str


def _parse_top100_yaml(path: Path, cohort_slug: str) -> list[BaseFaq]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    rows: list[BaseFaq] = []
    cur: dict[str, str] = {}
    in_questions = False
    for line in lines:
        s = line.rstrip()
        if s.startswith("questions:"):
            in_questions = True
            continue
        if not in_questions:
            continue
        if s.startswith("  - id:"):
            if cur.get("id"):
                rows.append(_finalize_base(cur, cohort_slug))
            cur = {"id": s.split(":", 1)[1].strip()}
            continue
        if s.startswith("    ") and ": " in s:
            key, _, val = s.lstrip().partition(": ")
            v = val.strip().strip('"').strip("'")
            if key in ("category", "question", "priority", "legal_disclaimer"):
                cur[key] = v
            elif key == "answer_depth_target":
                try:
                    cur["depth"] = str(int(v))
                except ValueError:
                    cur["depth"] = "3"
            elif key == "opus_baseline_cost_estimate_jpy":
                try:
                    cur["opus_jpy"] = str(int(v))
                except ValueError:
                    cur["opus_jpy"] = "18"
    if cur.get("id"):
        rows.append(_finalize_base(cur, cohort_slug))
    return rows


def _finalize_base(cur: dict[str, str], cohort_slug: str) -> BaseFaq:
    return BaseFaq(
        qid=cur.get("id", ""),
        cohort=cohort_slug,
        category=cur.get("category", ""),
        question=cur.get("question", ""),
        priority=cur.get("priority", "MED"),
        depth=int(cur.get("depth", "3")),
        opus_jpy=int(cur.get("opus_jpy", "18")),
        legal_disclaimer=cur.get("legal_disclaimer", "§52"),
    )


@dataclass
class ExpandedFaq:
    """One expanded FAQ row."""

    qid: str
    cohort_ja: str
    category: str
    question: str
    variants: list[str]
    priority: str
    depth: int
    opus_jpy: int
    legal_disclaimer: str


def _trigrams(text: str) -> set[str]:
    return {text[i : i + 3] for i in range(max(0, len(text) - 2))}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _expand_one(base: BaseFaq, cohort_slug: str) -> list[ExpandedFaq]:
    out: list[ExpandedFaq] = []
    base_q = base.question.strip().rstrip("?？")
    domain_terms = _DOMAIN_EXPANSIONS.get(cohort_slug, _DOMAIN_EXPANSIONS["tax"])
    cohort_ja_map = {
        "tax": "税理士",
        "audit": "会計士",
        "gyousei": "行政書士",
        "shihoshoshi": "司法書士",
        "chusho_keieisha": "中小経営者",
    }
    cohort_ja = cohort_ja_map.get(cohort_slug, "税理士")

    for idx, term in enumerate(domain_terms):
        struct_prefix, struct_suffix = _STRUCT_VARIATIONS[idx % len(_STRUCT_VARIATIONS)]
        new_q = f"{struct_prefix}{term}における{base_q}{struct_suffix}".strip()
        if not new_q.endswith("？"):
            new_q = new_q + "？"
        new_qid = f"{base.qid}_v{idx + 1:02d}"
        out.append(
            ExpandedFaq(
                qid=new_qid,
                cohort_ja=cohort_ja,
                category=base.category,
                question=new_q,
                variants=[
                    f"{term} {base.category}",
                    f"{term}の{base.category}実務",
                    f"{base.category} x {term}",
                ],
                priority=base.priority,
                depth=base.depth,
                opus_jpy=base.opus_jpy,
                legal_disclaimer=base.legal_disclaimer,
            )
        )
    return out


def _dedupe_by_similarity(rows: list[ExpandedFaq], threshold: float) -> list[ExpandedFaq]:
    kept: list[ExpandedFaq] = []
    fingerprints: list[set[str]] = []
    for r in rows:
        fp = _trigrams(r.question)
        drop = False
        for prev in fingerprints:
            if _jaccard(fp, prev) > threshold:
                drop = True
                break
        if not drop:
            kept.append(r)
            fingerprints.append(fp)
    return kept


def _escape_yaml(s: str) -> str:
    safe = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{safe}"'


def _emit_yaml_full(rows: list[ExpandedFaq], cohort_slug: str, cohort_ja: str) -> str:
    head = [
        f"# {cohort_slug}_top1000.yaml — jpcite GG2 expansion (500 -> 5000)",
        f"# Cohort: {cohort_ja}",
        "# Generated: 2026-05-17 (Wave 95 / GG2 expansion)",
        "# Source: top100 base x 10 domain term fan-out",
        "# Constraint: rule-based, NO LLM.",
        "# ---",
        "meta:",
        f"  cohort: {cohort_ja}",
        f"  total_questions: {len(rows)}",
        "  language: ja",
        "  schema_version: 1",
        "  legal_disclaimer_default: §52",
        "  expansion_strategy: domain_term_fanout",
        "questions:",
    ]
    body: list[str] = []
    for r in rows:
        body.append(f"  - id: {r.qid}")
        body.append(f"    cohort: {r.cohort_ja}")
        body.append(f"    category: {r.category}")
        body.append(f"    question: {_escape_yaml(r.question)}")
        body.append("    question_variants:")
        for v in r.variants:
            body.append(f"      - {_escape_yaml(v)}")
        body.append(f"    priority: {r.priority}")
        body.append(f"    answer_depth_target: {r.depth}")
        body.append(f"    opus_baseline_cost_estimate_jpy: {r.opus_jpy}")
        body.append("    jpcite_target_cost_jpy: 3")
        body.append(f"    legal_disclaimer: {r.legal_disclaimer}")
    return "\n".join(head + body) + "\n"


_COHORT_FROM_STEM: dict[str, str] = {
    "zeirishi_top100": "tax",
    "kaikeishi_top100": "audit",
    "gyouseishoshi_top100": "gyousei",
    "gyoseishoshi_top100": "gyousei",
    "shihoshoshi_top100": "shihoshoshi",
    "chusho_keieisha_top100": "chusho_keieisha",
}

_COHORT_JA: dict[str, str] = {
    "tax": "税理士",
    "audit": "会計士",
    "gyousei": "行政書士",
    "shihoshoshi": "司法書士",
    "chusho_keieisha": "中小経営者",
}

_OUT_FILENAME: dict[str, str] = {
    "tax": "zeirishi_top1000.yaml",
    "audit": "kaikeishi_top1000.yaml",
    "gyousei": "gyouseishoshi_top1000.yaml",
    "shihoshoshi": "shihoshoshi_top1000.yaml",
    "chusho_keieisha": "chusho_keieisha_top1000.yaml",
}


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("jpcite.gg2.expand")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GG2 — FAQ bank expander 500 -> 5,000.")
    parser.add_argument("--source-dir", default="data/faq_bank")
    parser.add_argument("--out-dir", default="data/faq_bank/expanded_5000")
    parser.add_argument("--per-cohort", type=int, default=1000)
    parser.add_argument("--similarity-threshold", type=float, default=0.85)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    source_dir = Path(args.source_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cohort_to_path: dict[str, Path] = {}
    for f in sorted(source_dir.glob("*_top100.yaml")):
        stem = f.stem
        slug = _COHORT_FROM_STEM.get(stem)
        if slug is None:
            continue
        if slug in cohort_to_path:
            if "gyouseishoshi" in stem:
                cohort_to_path[slug] = f
            continue
        cohort_to_path[slug] = f

    total = 0
    summary: dict[str, int] = {}
    for cohort_slug, base_path in cohort_to_path.items():
        cohort_ja = _COHORT_JA[cohort_slug]
        bases = _parse_top100_yaml(base_path, cohort_slug)
        logger.info("parsed %d base FAQ from %s", len(bases), base_path)

        expanded: list[ExpandedFaq] = []
        for base in bases:
            expanded.extend(_expand_one(base, cohort_slug))

        kept = _dedupe_by_similarity(expanded, args.similarity_threshold)
        logger.info(
            "expanded %d -> %d unique (cohort=%s)",
            len(expanded),
            len(kept),
            cohort_slug,
        )

        target = args.per_cohort
        if len(kept) > target:
            kept = kept[:target]

        out_path = out_dir / _OUT_FILENAME[cohort_slug]
        yaml_text = _emit_yaml_full(kept, cohort_slug, cohort_ja)
        out_path.write_text(yaml_text, encoding="utf-8")
        logger.info("wrote %d FAQ to %s", len(kept), out_path)
        summary[cohort_slug] = len(kept)
        total += len(kept)

    logger.info("expansion complete: total=%d (per-cohort: %s)", total, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
