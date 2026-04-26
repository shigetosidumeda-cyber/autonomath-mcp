"""Query intent taxonomy for Layer 7.

Maps the 50 typical queries from 09_user_queries.md into 10 intent clusters.
Each intent is canonical — match.py normalizes raw queries to one of these.

Design invariants:
- 10 intents, no more. A wider taxonomy dilutes the decision tree hit rate.
- Every intent ships with:
    * sample_queries   — subset of the 50 from 09_user_queries.md
    * required_entities / edges / filters
    * answer_template  (bullet|table|decision_flow)
    * precompute_keys  (what precompute.py must have cached)
- Intents are ordered by LLM access frequency, not by user type. A single user
  asks queries across multiple intents; we route per query, not per persona.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Intent:
    id: str
    name_ja: str
    description: str
    sample_queries: List[str]
    required_entity_types: List[str]
    required_edge_types: List[str]
    required_filters: List[str]
    answer_template: str  # one of: bullet, table, decision_flow
    precompute_keys: List[str]
    proactive_hints: List[str]  # list of rule ids driving 先回り提案


# ---------------------------------------------------------------------------
# Intent registry — keep list order stable (matches trees/<id>.yaml filenames)
# ---------------------------------------------------------------------------

INTENTS: List[Intent] = [
    Intent(
        id="i01_filter_programs_by_profile",
        name_ja="業種×地域×規模で使える補助金一覧",
        description=(
            "Enumerate programs applicable to a business profile "
            "(industry/region/size/fiscal-year). Layered national/prefecture/municipality."
        ),
        sample_queries=[
            "東京都 製造業 従業員30人で使える補助金は?",  # A1
            "熊本県の製造業中小企業、R7で使える補助金全部",  # A9-ish
            "うちの業種(食品製造)で使える DX 補助金",  # A9
        ],
        required_entity_types=["program"],
        required_edge_types=["applicable_to"],
        required_filters=[
            "prefecture",
            "municipality",
            "jsic_industry",
            "business_size",
            "active_on",
            "fiscal_year",
        ],
        answer_template="bullet",
        precompute_keys=[
            "program.eligibility_matrix",
            "program.application_window_index",
        ],
        proactive_hints=[
            "suggest_certification_prerequisites",
            "suggest_stacking_partners",
        ],
    ),
    Intent(
        id="i02_program_deadline_documents",
        name_ja="ある制度の申請締切・必要書類",
        description=(
            "Single-program canonical lookup — deadline, required documents, "
            "official forms. Must return URL + 最終確認日."
        ),
        sample_queries=[
            "ものづくり補助金 23次の締切は? 23次 vs 24次 違い",  # A2
            "IT導入補助金の公募要領 PDF の URL",  # E/catalog
            "建設業許可 29業種 申請書類リスト",  # C5
        ],
        required_entity_types=["program", "program_document"],
        required_edge_types=["has_document"],
        required_filters=["program_id", "round", "doc_type"],
        answer_template="bullet",
        precompute_keys=[
            "program.application_window_index",
            "program.document_bundle",
        ],
        proactive_hints=["suggest_next_round", "suggest_related_forms"],
    ),
    Intent(
        id="i03_program_successor_revision",
        name_ja="ある制度の後継制度・改正内容",
        description=(
            "Revision history / successor / predecessor chain. 『2025 と 2026 で何が変わったか』."
        ),
        sample_queries=[
            "令和8年度税制改正 新規変更点 一覧",  # C1
            "キャリアアップ助成金 正社員化コース 2026 改正前後",  # C3
            "中小企業経営強化税制 C類型 廃止 後の D/E 再編",  # 12_tax sub_type
        ],
        required_entity_types=["program", "law_revision"],
        required_edge_types=["successor_of", "amended_by"],
        required_filters=["program_id", "fiscal_year", "change_type"],
        answer_template="table",
        precompute_keys=["program.revision_chain", "law.latest_amendment"],
        proactive_hints=[
            "suggest_transition_period",
            "suggest_affected_clients_checklist",
        ],
    ),
    Intent(
        id="i04_tax_measure_sunset",
        name_ja="税制特例の適用期限",
        description=(
            "Tax measure validity window — application_period_from / to, sunset_date, "
            "abolition_note. Must flag 残り日数 and 自動失効リスク."
        ),
        sample_queries=[
            "賃上げ促進税制 2026年度 使える?",  # A5
            "インボイス 2割特例 いつまで?",  # A8
            "中小企業投資促進税制 延長の有無",  # 12_tax
        ],
        required_entity_types=["tax_measure"],
        required_edge_types=[],
        required_filters=["measure_id", "as_of_date"],
        answer_template="bullet",
        precompute_keys=["tax_measure.validity_index"],
        proactive_hints=[
            "suggest_successor_measure",
            "suggest_deadline_alarm",
        ],
    ),
    Intent(
        id="i05_certification_howto",
        name_ja="ある認定の取得方法・要件",
        description=(
            "Certification acquisition path — authority, requirements, fee, "
            "processing days, post-benefits."
        ),
        sample_queries=[
            "経営革新計画 認定 の取得方法",  # 09_cert
            "先端設備等導入計画 の申請手順",
            "健康経営優良法人 申請",
        ],
        required_entity_types=["certification"],
        required_edge_types=["certifying_authority", "unlocks_program"],
        required_filters=["certification_id"],
        answer_template="decision_flow",
        precompute_keys=[
            "certification.unlocks_programs",
            "authority.parent_ministry",
        ],
        proactive_hints=[
            "suggest_unlocked_programs",
            "suggest_parallel_certifications",
        ],
    ),
    Intent(
        id="i06_compat_incompat_stacking",
        name_ja="ある制度と併用可/不可の他制度",
        description=(
            "Compatibility matrix — compatible_with, incompatible_with, prerequisite. "
            "Transitive closure over exclusion rules."
        ),
        sample_queries=[
            "補助金の上乗せで市町村+県+国は併用可?",  # A7
            "事業再構築補助金と IT導入補助金の併用可否",  # LLM#8
            "中小企業経営強化税制 A類型 と 賃上げ促進税制 同時適用",  # 12_tax
        ],
        required_entity_types=["program", "tax_measure"],
        required_edge_types=["compatible", "incompatible", "prerequisite"],
        required_filters=["program_ids"],
        answer_template="table",
        precompute_keys=[
            "program.compat_closure",
            "program.incompat_closure",
            "program.prereq_closure",
        ],
        proactive_hints=[
            "suggest_overlapping_costs_warning",
            "suggest_stack_pattern_example",
        ],
    ),
    Intent(
        id="i07_adoption_cases",
        name_ja="採択事例・過去実績",
        description=(
            "Adoption / award records — filter by prefecture/industry/round/company-profile."
        ),
        sample_queries=[
            "事業再構築補助金 第11回 採択企業 北海道 リストある?",  # A3
            "うち(従業員30人/東京/小売)と同じprofileの採択事例",  # LLM#7
            "地方創生交付金 R8 採択自治体一覧 北陸",  # D2
        ],
        required_entity_types=["program", "case_study"],
        required_edge_types=["adopted_under"],
        required_filters=[
            "program_id",
            "round",
            "prefecture",
            "industry_jsic",
            "employee_range",
        ],
        answer_template="bullet",
        precompute_keys=["case_study.profile_index"],
        proactive_hints=[
            "suggest_similar_cases",
            "suggest_acceptance_rate_trend",
        ],
    ),
    Intent(
        id="i08_similar_municipality_programs",
        name_ja="類似自治体の制度",
        description=(
            "Peer-municipality program comparison — same population-band / same category / "
            "same prefecture cluster."
        ),
        sample_queries=[
            "人口3万 都市で 空家対策補助 やってる類似自治体",  # D1
            "他自治体の結婚新生活支援 補助内容比較",  # D4
            "上下水道 PFI 先行事例 中核市規模",  # D5
        ],
        required_entity_types=["municipality", "program"],
        required_edge_types=["offered_by"],
        required_filters=[
            "muni_population_band",
            "program_category",
            "pref_cluster",
        ],
        answer_template="table",
        precompute_keys=[
            "muni.peer_cluster",
            "program.category_index",
        ],
        proactive_hints=["suggest_peer_roster", "suggest_template_ordinance"],
    ),
    Intent(
        id="i09_succession_closure",
        name_ja="事業承継・廃業時に使える制度",
        description=(
            "Programs usable during business succession, M&A buy-side, voluntary closure. "
            "Includes tax measures and subsidies."
        ),
        sample_queries=[
            "事業承継税制 M&A 買い手で1億円使いたい",  # A6
            "廃業したいが補助金あるか",  # A10
            "事業承継・引継ぎ補助金 廃業・再チャレンジ枠",  # canon
        ],
        required_entity_types=["program", "tax_measure"],
        required_edge_types=["applicable_to_lifecycle"],
        required_filters=["lifecycle_stage", "target_role"],
        answer_template="bullet",
        precompute_keys=[
            "program.lifecycle_index",
            "program.compat_closure",
        ],
        proactive_hints=[
            "suggest_tax_benefits_chain",
            "suggest_advisory_window_warning",
        ],
    ),
    Intent(
        id="i10_wage_dx_gx_themed",
        name_ja="賃上げ/DX/GX 特化で使える制度",
        description=(
            "Theme-driven search — wage raise, DX, GX, etc. Cross-cutting over subsidies + "
            "tax measures + loans."
        ),
        sample_queries=[
            "賃上げ促進税制 の税額控除枠",  # A5 variant
            "DX 投資促進税制 と IT 導入補助金 DX枠",  # theme
            "GX/省エネ 補助金 2026 年度",  # 15_env
        ],
        required_entity_types=["program", "tax_measure", "loan_program"],
        required_edge_types=["themed_as"],
        required_filters=["theme", "fiscal_year"],
        answer_template="bullet",
        precompute_keys=[
            "program.theme_index",
            "program.compat_closure",
        ],
        proactive_hints=[
            "suggest_certification_prerequisites",
            "suggest_stacking_partners",
        ],
    ),
]


INTENT_BY_ID = {i.id: i for i in INTENTS}


def list_intents() -> List[Intent]:
    return list(INTENTS)


def get_intent(intent_id: str) -> Intent:
    if intent_id not in INTENT_BY_ID:
        raise KeyError(f"unknown intent_id: {intent_id}")
    return INTENT_BY_ID[intent_id]


# ---------------------------------------------------------------------------
# Rough keyword triggers for match.py fallback (does not replace a real classifier)
# ---------------------------------------------------------------------------

# ordering matters — more specific first
INTENT_KEYWORDS: List[tuple] = [
    ("i04_tax_measure_sunset",
     ["いつまで", "期限", "サンセット", "適用期限", "延長", "使える?", "2割特例"]),
    ("i03_program_successor_revision",
     ["改正", "改正前後", "差分", "diff", "廃止", "後継", "令和8年度", "税制改正"]),
    ("i06_compat_incompat_stacking",
     ["併用", "併給", "重複", "stack", "同時適用", "同時", "国+県", "上乗せ", "併用可否"]),
    ("i05_certification_howto",
     ["認定", "計画認定", "取得方法", "先端設備", "経営革新", "経営力向上",
      "事業継続力強化", "健康経営", "申請手順", "認定機関", "取得手順",
      "認証 取得", "認証取得", "認定取得", "認定要件", "になるには",
      "GAP認証", "GAP 認証", "エコアクション21", "くるみん", "えるぼし",
      "ユースエール", "もにす", "SECURITY ACTION", "ハラール認証",
      "健康経営優良法人", "スポーツエールカンパニー", "創業支援等事業",
      "地域経済牽引", "事業適応計画", "特例承継計画"]),
    ("i07_adoption_cases",
     ["採択", "採択企業", "採択自治体", "同じprofile", "類似 採択"]),
    ("i08_similar_municipality_programs",
     ["類似自治体", "他自治体", "人口3万", "人口 3 万", "中核市規模",
      "同規模", "同 規模", "類似 自治体", "制度比較", "自治体 比較",
      "先行事例", "先行 事例", "peer", "類似団体",
      "横浜市と同", "川崎市と同", "同じ規模"]),
    ("i09_succession_closure",
     ["事業承継", "廃業", "M&A", "引継ぎ", "事業縮小", "親族内承継", "親族承継", "承継"]),
    ("i10_wage_dx_gx_themed",
     ["賃上げ", "DX", "GX", "省エネ", "脱炭素", "デジタル化"]),
    ("i02_program_deadline_documents",
     ["締切", "申請書類", "公募要領", "申請様式", "必要書類", "記入例"]),
    ("i01_filter_programs_by_profile",
     ["業種", "都道府県", "従業員", "中小企業", "一覧", "全部", "小売", "製造業"]),
]
