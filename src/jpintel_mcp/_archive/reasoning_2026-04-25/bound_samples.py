"""Focused sample driver for the 6 db-bound intents (i01/i02/i03/i05/i07/i08).

Writes reasoning/bound_samples.md showing, per intent:
  1. the bind source (canonical tables + graph relations + precompute closures)
  2. the input slots
  3. the ``db_bind`` payload summary (bound_ok + notes + source_url count)
  4. the rendered answer skeleton

This is the artifact the parent task asks for.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import List

from . import query_types
from .match import match
from .precompute import load_cache

PKG_ROOT = Path(__file__).resolve().parent
OUT = PKG_ROOT / "bound_samples.md"

BOUND_INTENTS = [
    "i01_filter_programs_by_profile",
    "i02_program_deadline_documents",
    "i03_program_successor_revision",
    "i05_certification_howto",
    "i07_adoption_cases",
    "i08_similar_municipality_programs",
]

SAMPLE_QUERIES = {
    "i01_filter_programs_by_profile": [
        "東京都 製造業 従業員30人で使える補助金は?",
        "大阪府 小売業 従業員10人で使える補助金",
        "北海道 建設業 中小企業 補助金 一覧",
    ],
    "i02_program_deadline_documents": [
        "ものづくり補助金 23次の締切は?",
        "IT導入補助金 公募要領 の PDF URL",
        "事業再構築補助金 第13回 公募要領",
    ],
    "i03_program_successor_revision": [
        "令和8年度税制改正 新規変更点 一覧",
        "キャリアアップ助成金 正社員化コース 2026 改正前後",
        "技能実習制度 育成就労 後継",
    ],
    "i05_certification_howto": [
        "経営革新計画 認定 の取得方法",
        "先端設備等導入計画 の申請手順",
        "事業継続力強化計画 申請",
    ],
    "i07_adoption_cases": [
        "事業再構築補助金 第11回 採択企業 北海道 リストある?",
        "ものづくり補助金 第1次 採択",
        "IT導入補助金 採択事例 製造業",
    ],
    "i08_similar_municipality_programs": [
        "人口3万 都市で 空家対策補助 やってる類似自治体",
        "中核市規模 上下水道 PFI 先行事例",
        "近畿 省エネ 類似自治体",
    ],
}


def _compact_bound(bound: dict) -> dict:
    db = bound.get("db_bind") or {}
    out = {
        "bound_ok": db.get("bound_ok"),
        "notes": db.get("notes"),
        "source_urls_count": len(db.get("source_urls") or []),
        "source_urls_sample": (db.get("source_urls") or [])[:3],
        "ctx_keys_filled": sorted((db.get("ctx") or {}).keys()),
    }
    pre = bound.get("precomputed") or {}
    if pre:
        out["precomputed_keys"] = sorted(pre.keys())
    return out


def run() -> None:
    cache = load_cache()
    lines: List[str] = []
    lines.append("# AutonoMath Layer 7 — bound_samples (i01 / i02 / i03 / i05 / i07 / i08)")
    lines.append("")
    lines.append(f"Generated: {datetime.now(UTC).isoformat().replace('+00:00', '')}Z  ")
    lines.append("")
    lines.append("This file focuses on the 6 intents whose DB-bind was completed in "
                 "Wave-2. Every sample shows:  ")
    lines.append(" 1. the intent + slots extracted from the raw query,  ")
    lines.append(" 2. the `db_bind` outcome (bound_ok / notes / URL count / ctx keys),  ")
    lines.append(" 3. the rendered skeleton with verifiable values filled in.  ")
    lines.append("")
    lines.append("Sources bound per intent:  ")
    lines.append("- i01 → graph.am_relation(available_in / applies_to_industry / applies_to_size) "
                 "+ canonical am_entities + am_entity_facts (authority / amount / URL)  ")
    lines.append("- i02 → canonical am_entities source_topic=04_program_documents "
                 "+ am_entity_facts(raw.application_deadline / required_documents)  ")
    lines.append("- i03 → graph.am_relation(replaces) + canonical am_entity_facts(relation.N.*) "
                 "+ 07_new_program_candidates (R8 tax reform) + precompute.tax_measure_validity  ")
    lines.append("- i05 → canonical am_entities record_kind=certification (raw_json "
                 "requirements/benefits/linked_subsidies) + precompute.certification_unlocks  ")
    lines.append("- i07 → canonical am_entity_facts(raw.program_id_hint) → 05_adoption_additional "
                 "(105K rows) + 22_mirasapo_cases + 01/02 acceptance_stats aggregate  ")
    lines.append("- i08 → canonical 47_local_ordinance_benefits + 20_designated_city_programs "
                 "+ 06/33_prefecture_programs filtered by category + pref_cluster  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # per-intent summary table
    rows = [
        "| intent | queries | bound_ok | ctx keys per query | source URLs per query |",
        "|---|---|---|---|---|",
    ]
    per_intent_stats = []
    for iid in BOUND_INTENTS:
        samples = SAMPLE_QUERIES.get(iid, [])
        ok = 0
        total_keys = 0
        total_urls = 0
        per_q = []
        for q in samples:
            r = match(q, cache=cache)
            db = r.bound.get("db_bind", {}) or {}
            if db.get("bound_ok"):
                ok += 1
            keys = len((db.get("ctx") or {}).keys())
            urls = len(db.get("source_urls") or [])
            total_keys += keys
            total_urls += urls
            per_q.append((q, r))
        per_intent_stats.append((iid, samples, per_q))
        rows.append(
            f"| {iid} | {len(samples)} | {ok}/{len(samples)} | "
            f"{total_keys // max(1, len(samples))} avg | "
            f"{total_urls // max(1, len(samples))} avg |"
        )
    lines.append("## Summary")
    lines.append("")
    lines.append("\n".join(rows))
    lines.append("")
    lines.append("---")
    lines.append("")

    # detailed samples
    for iid, samples, per_q in per_intent_stats:
        intent = query_types.INTENT_BY_ID[iid]
        lines.append(f"## {iid} — {intent.name_ja}")
        lines.append("")
        for q, r in per_q:
            lines.append(f"### Q: {q}")
            lines.append("")
            lines.append(f"- **intent**: `{r.intent_id}` (confidence {r.confidence})")
            lines.append(f"- **slots**: `{json.dumps(r.slots, ensure_ascii=False)}`")
            compact = _compact_bound(r.bound)
            lines.append("- **db_bind summary**:")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(compact, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
            lines.append("**bound answer skeleton:**")
            lines.append("")
            lines.append("```")
            lines.append(r.answer_skeleton.rstrip())
            lines.append("```")
            lines.append("")
        lines.append("---")
        lines.append("")

    # Gap section
    lines.append("## Remaining gaps (honest)")
    lines.append("")
    lines.append(
        "These are the places where the skeleton still leaves `-` or a (未 ingest) "
        "note because the upstream data isn't in canonical yet. They are **visible** "
        "in the skeleton, not hallucinated — LLMs won't invent values."
    )
    lines.append("")
    lines.append("- i02 **root_law / 採択発表予定 / 交付決定 / prev_round diff** — "
                 "04_program_documents has form URLs but no timeline fields; revision_history[] is P1 TODO.")
    lines.append("- i02 **window_end per-round** — `raw.application_deadline` exists on some "
                 "entities but is not indexed by round_number; we surface the raw text.")
    lines.append("- i03 **transition_period / coexistence_window** — graph.replaces yields "
                 "successor pairs only; transition rules are in raw 経過措置 text not ingested.")
    lines.append("- i05 **application_fee_yen** — present for the 25 canonical certs; zero "
                 "in all current rows. validity_period / renewal_rule partial.")
    lines.append("- i07 **amount_granted_yen** — null for 100% of 05_adoption_additional "
                 "rows (P2 backfill); only 01/02 stats have aggregate totals.")
    lines.append("- i08 **muni peer cluster (population band)** — 10_municipality_master "
                 "has no population column; coverage ~11% of 1788 municipalities.")
    lines.append("")
    lines.append(
        "When the downstream data agent fills these gaps, the skeleton picks up "
        "the new values automatically — no change to reasoning/ required."
    )

    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    run()
