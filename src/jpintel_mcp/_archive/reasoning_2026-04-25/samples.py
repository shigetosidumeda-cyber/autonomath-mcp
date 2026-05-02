"""Sample driver — 10 intents x 3 queries each -> reasoning/sample_output.md.

Run once to regenerate sample_output.md after any match.py / precompute.py change.
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
OUT_PATH = PKG_ROOT / "sample_output.md"


# 3 queries per intent — drawn from 09_user_queries.md + LLM#02 patterns.
SAMPLE_QUERIES = {
    "i01_filter_programs_by_profile": [
        "東京都 製造業 従業員30人で使える補助金は?",                        # A1
        "熊本県の製造業中小企業、R7 で使える補助金全部",                    # LLM#1
        "うちの業種(食品製造)で使える DX 補助金",                           # A9
    ],
    "i02_program_deadline_documents": [
        "ものづくり補助金 23次の締切は?",                                    # A2
        "IT導入補助金 公募要領 の PDF URL",                                 # LLM#2
        "事業再構築補助金 第13回 公募要領",                                  # derived
    ],
    "i03_program_successor_revision": [
        "令和8年度税制改正 新規変更点 一覧",                                # C1
        "キャリアアップ助成金 正社員化コース 2026 改正前後",                # C3
        "中小企業経営強化税制 C類型 廃止 後の D/E 再編",                    # canon
    ],
    "i04_tax_measure_sunset": [
        "賃上げ促進税制 2026年度 使える?",                                  # A5
        "インボイス 2割特例 いつまで?",                                     # A8
        "中小企業投資促進税制 の適用期限",                                  # 12_tax
    ],
    "i05_certification_howto": [
        "経営革新計画 認定 の取得方法",
        "先端設備等導入計画 の申請手順",
        "健康経営優良法人 申請",
    ],
    "i06_compat_incompat_stacking": [
        "事業再構築補助金と IT導入補助金の併用可否",                         # LLM#8
        "補助金の上乗せで市町村+県+国は併用可?",                              # A7
        "中小企業経営強化税制 A類型 と 賃上げ促進税制 同時適用",             # 12_tax
    ],
    "i07_adoption_cases": [
        "事業再構築補助金 第11回 採択企業 北海道 リストある?",               # A3
        "ものづくり補助金 第17回 採択 東京都",                               # derived
        "IT導入補助金 採択事例 製造業",                                      # derived
    ],
    "i08_similar_municipality_programs": [
        "人口3万 都市で 空家対策補助 やってる類似自治体",                   # D1
        "他自治体の結婚新生活支援 補助内容比較",                            # D4
        "中核市規模 上下水道 PFI 先行事例",                                 # D5
    ],
    "i09_succession_closure": [
        "事業承継税制 M&A 買い手で1億円使いたい",                           # A6
        "廃業したいが補助金あるか",                                         # A10
        "親族内承継で使える税制特例",                                        # derived
    ],
    "i10_wage_dx_gx_themed": [
        "賃上げ促進税制 の税額控除枠",                                      # A5 variant
        "DX 投資促進税制 と IT 導入補助金 DX枠",                            # theme
        "GX 省エネ 補助金 2026 年度",                                       # 15_env
    ],
}


def run() -> None:
    cache = load_cache()
    results: List[tuple] = []
    for intent in query_types.INTENTS:
        queries = SAMPLE_QUERIES[intent.id]
        for q in queries:
            r = match(q, cache=cache)
            results.append((intent, q, r))

    lines: List[str] = []
    lines.append("# AutonoMath Layer 7 — sample answer skeletons")
    lines.append("")
    lines.append(f"Generated: {datetime.now(UTC).isoformat().replace('+00:00', '')}Z  ")
    lines.append(f"Source cache: reasoning/_cache/precomputed.json  ")
    lines.append(f"Input: 10 intents × 3 queries = {len(results)} samples  ")
    lines.append("")
    lines.append(
        "Each block shows (1) the **intent classification** (keyword scorer), "
        "(2) **extracted slots**, (3) the **bound precompute payload** — this is "
        "the part that would otherwise be hallucinated — and (4) the **answer skeleton** "
        "with `<<<missing:X>>>` tokens marking slots the LLM must ask follow-up for "
        "or the data-collection agent must backfill."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Summary of hallucination-risk deltas")
    lines.append("")
    lines.append(_summary_table(results))
    lines.append("")
    lines.append("---")
    lines.append("")

    current_intent_id = None
    for intent, q, r in results:
        if intent.id != current_intent_id:
            current_intent_id = intent.id
            lines.append(f"## {intent.id} — {intent.name_ja}")
            lines.append("")
            lines.append(f"_{intent.description}_")
            lines.append("")

        lines.append(f"### Q: {q}")
        lines.append("")
        lines.append(f"- **intent**: `{r.intent_id}` (confidence {r.confidence})")
        lines.append(f"- **slots**: `{json.dumps(r.slots, ensure_ascii=False)}`")
        bound_json = json.dumps(r.bound.get("precomputed", {}),
                                ensure_ascii=False, indent=2)
        if len(bound_json) > 2000:
            bound_json = bound_json[:2000] + "\n  ... (truncated)"
        lines.append("")
        lines.append("**bound precomputed:**")
        lines.append("")
        lines.append("```json")
        lines.append(bound_json)
        lines.append("```")
        lines.append("")
        lines.append("**answer skeleton:**")
        lines.append("")
        lines.append("```")
        lines.append(r.answer_skeleton.rstrip())
        lines.append("```")
        lines.append("")

    # Known gaps section (honest)
    lines.append("---")
    lines.append("")
    lines.append("## Known precompute gaps (what `<<<missing:X>>>` means)")
    lines.append("")
    lines.append(
        "These are slots the reasoning layer **cannot yet** bind because the upstream "
        "data pipeline has not produced them. The skeleton leaves them visible so "
        "the LLM does not fabricate values:"
    )
    lines.append("")
    for gap in _enumerate_gaps():
        lines.append(f"- **{gap['token']}** — {gap['reason']} (owner: {gap['owner']})")
    lines.append("")
    lines.append(
        "The Layer 7 design guarantees that any value the LLM passes through "
        "to the user either (a) came from a precompute payload with a source URL, "
        "or (b) is flagged `<<<missing>>>`. There is no third path."
    )

    OUT_PATH.write_text("\n".join(lines))
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes, {len(results)} samples)")


def _summary_table(results: List[tuple]) -> str:
    rows = [
        "| intent | samples | slots filled | precompute hits | db_bind ok | skeleton has `<<<missing>>>` |",
        "|---|---|---|---|---|---|",
    ]
    from collections import defaultdict
    agg: dict = defaultdict(lambda: {"n": 0, "slots_filled": 0, "pre_hit": 0, "db_ok": 0, "miss": 0})
    for intent, q, r in results:
        a = agg[intent.id]
        a["n"] += 1
        a["slots_filled"] += sum(1 for v in r.slots.values() if v not in (None, "", []))
        if r.bound.get("precomputed"):
            a["pre_hit"] += 1 if any(r.bound["precomputed"].values()) else 0
        if r.bound.get("db_bind", {}).get("bound_ok"):
            a["db_ok"] += 1
        if "<<<missing:" in r.answer_skeleton:
            a["miss"] += 1
    for intent in query_types.INTENTS:
        a = agg[intent.id]
        rows.append(
            f"| {intent.id} | {a['n']} | {a['slots_filled']} | "
            f"{a['pre_hit']}/{a['n']} | {a['db_ok']}/{a['n']} | {a['miss']}/{a['n']} |"
        )
    return "\n".join(rows)


def _enumerate_gaps() -> List[dict]:
    return [
        {"token": "national_bullets / prefecture_bullets / municipality_bullets",
         "reason": "applicable_programs list not yet joined into Layer 7 cache — "
                   "requires programs table ingest (Layer 2/3 responsibility)",
         "owner": "entity/ingest agent"},
        {"token": "form_urls / doc_bullets",
         "reason": "04_program_documents is not yet in SQL form_documents table",
         "owner": "entity/ingest agent"},
        {"token": "revision_table / diff_from_prev_round",
         "reason": "revision_history[] not yet collected on canonical programs "
                   "(P1 in 09_user_queries.md)",
         "owner": "data-collection agent (P1 work)"},
        {"token": "extension_signal / latest_revision_note",
         "reason": "税制改正大綱 timing scrape not yet done",
         "owner": "data-collection agent"},
        {"token": "pair_matrix_table / violation_detail_bullets",
         "reason": "handled by precompute but render_skeleton currently substitutes "
                   "flat list — pair-table renderer is TODO in Layer 7",
         "owner": "reasoning agent (this layer, next iteration)"},
        {"token": "case_bullets / prefecture_histogram / industry_histogram",
         "reason": "05_adoption_additional (105K rows) not yet indexed by "
                   "prefecture × JSIC × round",
         "owner": "embedding / entity agent"},
        {"token": "peer_roster / comparison_table",
         "reason": "municipality_peer_cluster not built — 10_municipality_master "
                   "needs a clustering pass (population-band × pref_cluster)",
         "owner": "entity agent"},
        {"token": "citation_urls",
         "reason": "source_url bind is done in precompute but the template renderer "
                   "concatenation is handled by the embedding/truth layer, not here",
         "owner": "embedding / truth agent"},
    ]


if __name__ == "__main__":
    run()
