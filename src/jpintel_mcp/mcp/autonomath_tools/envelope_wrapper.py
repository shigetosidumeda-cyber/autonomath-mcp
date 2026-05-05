"""Response envelope v2 wrapper for AutonoMath MCP tools (Wave 11 Agent #6).

Goal
----
Customer LLMs that call AutonoMath via MCP currently have to parse
free-text `hint` strings and guess whether 0 results means "query was
bad" or "we don't have that data". This wrapper normalizes every tool's
return value into a single envelope with an explicit 4-way `status`
bucket (rich / sparse / empty / error), a Japanese `explanation`, and a
structured `suggested_actions[]` list.

See docs/response_envelope_v2.yaml for the full schema.

Layering
--------
The wrapper is a decorator, not a rewrite — legacy tools.py is left
untouched. `tools_envelope.py` imports each tool from tools.py and
re-exports a wrapped version. MCP registration is decoupled: callers
import from tools_envelope when they want the v2 envelope.

Empty-bucket explanation
------------------------
When a tool returns 0 results we call query_router's `route()` to derive
an `explain_empty` string keyed on the inferred intent. If the routing
subsystem is unavailable (import fails in sandbox runs), we fall back
to a canned sentence keyed on `tool_name`.

Error-bucket wiring
-------------------
If a wrapped function raises, we catch, classify via the same mapping
as error_envelope.make_error (sqlite OperationalError → db_locked /
db_unavailable, ValueError/TypeError → internal). If the function
returns a dict already shaped as an error_envelope.make_error payload
(i.e. `is_error()` is True), we preserve the `error` object and
wrap it with status="error".

No API key usage: this wrapper never calls Anthropic or any LLM.
"""
from __future__ import annotations

import contextlib
import functools
import logging
import sqlite3
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from .._error_helpers import safe_internal_error_payload
from .cs_features import build_meta, enhance_error_with_retry
from .error_envelope import ERROR_CODES, is_error, make_error  # noqa: F401

# O8 — Bayesian per-fact uncertainty. Soft-imported so a sandbox without
# the autonomath.db view (or scipy) still produces an envelope; the
# `_uncertainty` field stays absent on import failure, which downstream
# consumers already tolerate.
try:
    from jpintel_mcp.api.uncertainty import (
        get_uncertainty_for_fact as _o8_get_uncertainty_for_fact,
    )
    from jpintel_mcp.api.uncertainty import (
        score_fact as _o8_score_fact,
    )
except Exception:  # pragma: no cover - soft dependency
    _o8_get_uncertainty_for_fact = None  # type: ignore[assignment]
    _o8_score_fact = None  # type: ignore[assignment]

logger = logging.getLogger("autonomath.mcp.envelope")

# Bump to 1.1 for the additive `meta` block + error retry/user_message
# fields. Backward-compatible: every new field is optional, and
# fields="minimal" omits them entirely.
ENVELOPE_API_VERSION = "1.1"

# ---------------------------------------------------------------------------
# Bucket classification (matches learning/common.py trigger rules)
# ---------------------------------------------------------------------------

RICH_THRESHOLD = 3  # >= 3 results => rich
SPARSE_MIN = 1      # 1..RICH_THRESHOLD-1 => sparse


def classify_bucket(result_count: int) -> str:
    """Return one of 'rich' | 'sparse' | 'empty'. Error is set separately."""
    if result_count == 0:
        return "empty"
    if result_count < RICH_THRESHOLD:
        return "sparse"
    return "rich"


# ---------------------------------------------------------------------------
# Default Japanese explanations (per tool, per bucket).
# Each string is >= 20 chars to pass the test_envelope minimum-length assert.
# ---------------------------------------------------------------------------

# Keyed by (tool_name, status). Fallback uses tool_name alone.
DEFAULT_EXPLANATIONS: dict[str, dict[str, str]] = {
    "search_tax_incentives": {
        "rich": "税制特例が十分件数見つかりました。適用期限と対象を確認して引用してください。",
        "sparse": "税制特例は少数のみ該当しました。条件を広げると追加候補が見つかる可能性があります。",
        "empty": "指定条件の税制特例は当 DB に収録されていません。条件を広げるか国税庁原典をご確認ください。",
        "error": "税制検索が一時的に失敗しました。時間をおいて再度お試しください。",
    },
    "search_certifications": {
        "rich": "該当する認定制度が複数見つかりました。取得手続きの一次資料リンクを確認してください。",
        "sparse": "該当認定は少数のみでした。認定名の正式名称で再検索すると精度が上がります。",
        "empty": "該当する認定制度は当 DB に未登録です。経営革新計画など主要 14 認定から再指定してください。",
        "error": "認定検索が一時的に失敗しました。時間をおいて再度お試しください。",
    },
    "list_open_programs": {
        "rich": "現在公募中の制度が複数あります。締切順に並べて提示してください。",
        "sparse": "現在公募中の該当制度は少数です。対象期間や地域条件を広げることを検討してください。",
        "empty": "指定条件で現在公募中の制度は DB にありません。次回公募時期は各制度の個別照会を推奨します。",
        "error": "公募情報の取得が一時的に失敗しました。時間をおいて再度お試しください。",
    },
    "search_by_law": {
        "rich": "指定法令に紐づく制度が複数見つかりました。法改正履歴の有無も合わせて確認してください。",
        "sparse": "指定法令に紐づく制度は少数です。法令の正式名称 (例: 中小企業等経営強化法) で再検索してください。",
        "empty": "指定法令に紐づく制度は当 DB に未収録です。e-Gov で法令原文を確認する案内が適切です。",
        "error": "法令検索が一時的に失敗しました。時間をおいて再度お試しください。",
    },
    "active_programs_at": {
        "rich": "指定日に施行中の制度が十分件数見つかりました。適用期限を確認の上ご案内ください。",
        "sparse": "指定日に施行中の制度は少数です。前後の日付を試すと追加候補が見つかる可能性があります。",
        "empty": "指定日に施行中だった制度は DB にありません。日付指定の書式や範囲をご確認ください。",
        "error": "施行期間検索が一時的に失敗しました。時間をおいて再度お試しください。",
    },
    "related_programs": {
        "rich": "指定制度に関連する制度が複数見つかりました。関係種別 (前提/競合/後継) を明示してください。",
        "sparse": "関連制度は少数のみ見つかりました。種別フィルタを外すと追加関連が得られる場合があります。",
        "empty": "指定 seed の関連制度はグラフ上に未登録です。seed_id の表記揺れをご確認ください。",
        "error": "関連制度検索が一時的に失敗しました。時間をおいて再度お試しください。",
    },
    "search_acceptance_stats": {
        "rich": "採択統計が複数回次で見つかりました。採択率の推移で提示してください。",
        "sparse": "採択統計は少数回次のみ DB に存在します。制度名の表記揺れをご確認ください。",
        "empty": "該当制度の採択統計は DB に未登録です。採択者発表 PDF の一次資料をご案内ください。",
        "error": "採択統計の取得が一時的に失敗しました。時間をおいて再度お試しください。",
    },
    "enum_values": {
        "rich": "指定 enum の候補値を取得しました。この enum から値を選んで再検索してください。",
        "sparse": "該当 enum の候補値は少数です。enum 名の綴りをご確認ください。",
        "empty": "指定 enum は未登録または空です。enum 名の綴りをご確認ください。",
        "error": "enum 値の取得が一時的に失敗しました。時間をおいて再度お試しください。",
    },
    "intent_of": {
        "rich": "質問の意図を複数候補で推定しました。confidence 最上位を採用するのが安全です。",
        "sparse": "意図推定の候補が少数でした。質問文をより具体的に再入力すると精度が上がります。",
        "empty": "質問から意図を推定できませんでした。業種・制度名・時期を含めて再入力してください。",
        "error": "意図推定が一時的に失敗しました。時間をおいて再度お試しください。",
    },
    "reason_answer": {
        "rich": "推論根拠を複数件取得しました。引用元 URL を必ず提示してから結論を述べてください。",
        "sparse": "推論根拠は少数のみ得られました。追加情報の確認を人間に促すのが安全です。",
        "empty": "推論に必要な根拠が DB にありません。推測での回答は避け、原典参照をご案内ください。",
        "error": "推論エンジンが一時的に失敗しました。時間をおいて再度お試しください。",
    },
}

_FALLBACK_EXPLAIN = {
    "rich": "関連する情報が十分件数見つかりました。引用元を明示した上で提示してください。",
    "sparse": "関連する情報は少数のみでした。検索条件を広げると追加候補が見つかる可能性があります。",
    "empty": "該当する情報は当 DB に収録されていません。条件を広げるか一次資料をご確認ください。",
    "error": "取得が一時的に失敗しました。時間をおいて再度お試しください。",
}


# ---------------------------------------------------------------------------
# `_disclaimer` envelope field (S7 finding, 2026-04-25)
#
# Sensitive tools must surface a tool-specific business-law / regulatory
# disclaimer so that customer LLMs do not relay our output as legal /
# compliance / credit advice. This avoids 行政書士法 §1 (申請書面作成),
# 税理士法 §52 (税務代理), 弁護士法 §72 (法律事務) boundary risk and
# 詐欺 risk on credit / DD use-cases.
#
# Three levels:
#   "strict"  : long form (every disclaimer concatenated).
#   "standard": one-paragraph default — mirrors task spec verbatim.
#   "minimal" : single line, no specifics — used for token-sensitive paths.
# ---------------------------------------------------------------------------

# Tools that are SENSITIVE — every envelope must carry `_disclaimer`.
# Includes deprecated `combined_compliance_check` for back-compat. The
# unimplemented tools (`predict_subsidy_outcome` / `score_dd_risk`) are
# pre-registered so that when their bodies land they pick up the
# disclaimer automatically without a second envelope pass.
SENSITIVE_TOOLS: frozenset[str] = frozenset({
    "dd_profile_am",
    "regulatory_prep_pack",
    "combined_compliance_check",
    "rule_engine_check",
    "predict_subsidy_outcome",
    "score_dd_risk",
    "intent_of",
    "reason_answer",
    # Tax surfaces — 税理士法 §52 fence. jpcite.com brand sits in
    # 税務会計 territory, so every tax-data tool must declare the output
    # information retrieval, NOT 税務助言.
    "search_tax_incentives",
    "get_am_tax_rule",
    "list_tax_sunset_alerts",
    # Wave 21 composition tools — eligibility / portfolio / mock walkthrough
    # all sit in 税理士法 §52 + 行政書士法 §1 + 弁護士法 §72 territory.
    "apply_eligibility_chain_am",
    "find_complementary_programs_am",
    "simulate_application_am",
    # Wave 22 composition tools — DD checklist / kessan briefing /
    # jurisdiction onboarding / application kit. Four of five sit in
    # 税理士法 §52 / 行政書士法 §1 / 弁護士法 §72 territory.
    # forecast_program_renewal is intentionally NOT in this set — it is
    # a statistical forecast about program lifecycle, not regulated.
    "match_due_diligence_questions",
    "prepare_kessan_briefing",
    "cross_check_jurisdiction",
    "bundle_application_kit",
    # 会計士 work-paper bundle tools — 公認会計士法 §47条の2 監査調書保存 +
    # 税理士法 §52 fence. Citation chain auto-resolution sits in the
    # same sensitive territory because the response cites tax
    # authorities verbatim.
    "compose_audit_workpaper",
    "audit_batch_evaluate",
    "resolve_citation_chain",
    # Wave 23 industry pack wrappers (2026-04-29) — bundle programs +
    # saiketsu citations + 通達 references for 建設 / 製造 / 不動産 cohorts.
    # 税理士法 §52 + 公認会計士法 §47条の2 fence — the response cites
    # tax authority decisions and references applicable to business
    # planning, all of which live in regulated advice territory.
    "pack_construction",
    "pack_manufacturing",
    "pack_real_estate",
    # Corporate layer — 法人番号 / 適格請求書 surfaces can be used in
    # regulated tax, credit, and DD workflows. EDINET pointer-only tool is
    # intentionally excluded.
    "get_houjin_360_am",
    "search_invoice_by_houjin_partial",
    # Vector kNN recommendation tools (recommend_similar.py, 2026-05-05).
    # 行政書士法 §1 + 弁護士法 §72 + 税理士法 §52 fence — vector
    # similarity is a retrieval signal, not an 採択/法解釈/税務判断.
    "recommend_similar_program",
    "recommend_similar_case",
    "recommend_similar_court_decision",
})

_DISCLAIMER_STANDARD: dict[str, str] = {
    "dd_profile_am": (
        "本 response は公開 enforcement / adoption / certification データの "
        "検索 aggregation のみで、信用調査・与信・反社チェック・労務 due diligence "
        "(社労士法・弁護士法 §72) の代替ではありません。検索結果は heuristic 由来の "
        "rule や partial provenance を含むため、業務判断には必ず一次資料を直接確認してください。"
    ),
    "regulatory_prep_pack": (
        "本 response は制度概要の検索結果のみで、申請書面の作成・提出は "
        "行政書士法 §1 に基づく独占業務です。当社は draft scaffold を提供せず "
        "一次資料 URL のみ surface します。検索結果のみ提供、業務判断は primary source 確認必須。"
    ),
    "combined_compliance_check": (
        "本 response は公開ルールに対する機械的な検索照合で、法律事務 "
        "(弁護士法 §72) ・税務代理 (税理士法 §52) ・申請代理 (行政書士法 §1) "
        "・労務判断 (社労士法) のいずれにも該当しません。検索結果のみ提供、"
        "業務判断は primary source 確認必須、確定判断は士業へ。"
    ),
    "rule_engine_check": (
        "Rule judgment は公開コーパス (一次資料) に対する機械的検索照合で、"
        "法律事務 (弁護士法 §72) ・税務代理 (税理士法 §52) ・申請代理 "
        "(行政書士法 §1) ・労務判断 (社労士法) は提供しません。"
        "rule の一部は heuristic 由来。検索結果のみ提供、業務判断は primary source 確認必須。"
    ),
    "predict_subsidy_outcome": (
        "予測値は過去採択データに基づく統計的 score で、採択を担保するものではありません。"
        "予測 model の一部は heuristic feature を含み、申請可否判断 (行政書士法 §1) "
        "の代替ではありません。検索結果のみ提供、業務判断は primary source 確認必須。"
    ),
    "score_dd_risk": (
        "過去 enforcement / 行政処分の検索ベース score で、与信判断・反社チェック・"
        "信用調査 (弁護士法 §72) ・労務 due diligence (社労士法) の代替ではありません。"
        "score は heuristic 由来の rule を含む。検索結果のみ提供、業務判断は primary source 確認必須。"
    ),
    "intent_of": (
        "本 response は自然言語クエリの 10 intent cluster への決定論的分類で、"
        "法解釈・申請判断・税務判断・労務判断には該当しません。"
        "業法 (弁護士法 §72 / 税理士法 §52 / 行政書士法 §1 / 社労士法) の業務範囲は "
        "当社対象外、confidence < 0.5 は branching か reason_answer に回してください。"
    ),
    "reason_answer": (
        "本 response は intent 分類 → slot 抽出 → DB bind → answer skeleton の "
        "決定論 pipeline で、申請書面作成は行政書士法 §1、税務判断は税理士法 §52、"
        "労務判断は社労士法、法律相談は弁護士法 §72 の業務範囲。"
        "skeleton は検索結果のみ提供、業務判断は primary source 確認必須、確定判断は士業へ。"
    ),
    "search_tax_incentives": (
        "本 response は am_tax_rule (国税庁・財務省・e-Gov 由来 ~285 行) の "
        "情報検索のみで、税務助言ではありません。AutonoMath は税理士法 §52 に基づき "
        "個別具体的な税務判断・申告書作成代行を行いません。検索結果に含まれる "
        "rate / sunset / authority は公表時点の値であり、申告期限までに改正される "
        "可能性があります。個別案件は資格を有する税理士に必ずご相談ください。"
    ),
    "get_am_tax_rule": (
        "本 response は単一の税制措置 (am_tax_rule) lookup で、税務助言では "
        "ありません。root_law / rate / applicability window は公表時点の "
        "国税庁・財務省・e-Gov 一次資料から抽出した値であり、税理士法 §52 に基づき "
        "個別具体的な税務判断・申告書作成代行は行いません。申告期限・適用条件の "
        "個別判断は資格を有する税理士に必ずご相談ください。"
    ),
    "list_tax_sunset_alerts": (
        "本 response は am_tax_rule の sunset_at 集計 (公表時点の措置法廃止予定日) で、"
        "税務助言ではありません。sunset_at は予定日であり延長・前倒しの可能性が "
        "あります。税理士法 §52 に基づき個別具体的な税務判断は提供しません。"
        "個別案件は資格を有する税理士に必ずご相談ください。"
    ),
    # --- Wave 22 composition tools ---------------------------------------
    "match_due_diligence_questions": (
        "本 response は dd_question_templates (60 行) と houjin / adoption / "
        "enforcement / invoice corpora の機械的 join による DD 質問 checklist で、"
        "信用調査・反社チェック (弁護士法 §72) ・労務 due diligence (社労士法) ・"
        "税務助言 (税理士法 §52) の代替ではありません。質問は情報照会 checklist で、"
        "確定判断は資格を有する士業に必ずご相談ください。"
    ),
    "prepare_kessan_briefing": (
        "本 response は am_amendment_diff + jpi_tax_rulesets の機械的 aggregation "
        "による 決算期前後の制度変動 briefing で、税務代理 (税理士法 §52) ・申告書 "
        "作成代行は提供しません。差分検知は heuristic を含み、決算書面・申告書面の "
        "作成は資格を有する税理士・公認会計士に必ずご相談ください。"
    ),
    "cross_check_jurisdiction": (
        "本 response は houjin_master + invoice_registrants + adoption_records の "
        "住所・所在地データの突合せで、税務代理 (税理士法 §52) ・登記申請 "
        "(司法書士法 §3) ・行政書士業務 (行政書士法 §1) の代替ではありません。"
        "不一致検出は heuristic で、確定判断は資格を有する士業に必ずご相談ください。"
    ),
    "bundle_application_kit": (
        "本 response は公開公募要領 + 採択事例 + 必要書類リストの assembly で、"
        "申請書面の作成・提出代行は行政書士法 §1 の独占業務です。当社は scaffold + "
        "primary source URL のみ surface し、書面作成自体は提供しません。"
        "最終申請判断は資格を有する行政書士・中小企業診断士・税理士へ。"
    ),
    # --- Wave 23 industry pack wrappers ----------------------------------
    "pack_construction": (
        "本 response は jpintel programs (建設業 fence) + nta_saiketsu + "
        "nta_tsutatsu_index の機械的 aggregation で、税務助言 (税理士法 §52) ・"
        "監査調書 (公認会計士法 §47条の2) ・申請代理 (行政書士法 §1) の代替では "
        "ありません。業種マッピングは JSIC D + 名称キーワード fence による "
        "heuristic で、各 program の適合可否は申請要領を一次資料で必ずご確認ください。"
    ),
    "pack_manufacturing": (
        "本 response は jpintel programs (製造業 fence) + nta_saiketsu + "
        "nta_tsutatsu_index の機械的 aggregation で、税務助言 (税理士法 §52) ・"
        "監査調書 (公認会計士法 §47条の2) ・申請代理 (行政書士法 §1) の代替では "
        "ありません。業種マッピングは JSIC E + 名称キーワード fence による "
        "heuristic で、各 program の適合可否は申請要領を一次資料で必ずご確認ください。"
    ),
    "pack_real_estate": (
        "本 response は jpintel programs (不動産業 fence) + nta_saiketsu + "
        "nta_tsutatsu_index の機械的 aggregation で、税務助言 (税理士法 §52) ・"
        "監査調書 (公認会計士法 §47条の2) ・申請代理 (行政書士法 §1) の代替では "
        "ありません。業種マッピングは JSIC K + 名称キーワード fence による "
        "heuristic で、各 program の適合可否は申請要領を一次資料で必ずご確認ください。"
    ),
    "get_houjin_360_am": (
        "本 response は公開法人情報・適格請求書登録・行政処分・採択履歴の機械的 "
        "join による法人 360 view で、信用調査・反社チェック・税務助言 "
        "(税理士法 §52) ・法律判断 (弁護士法 §72) の代替ではありません。"
        "業務判断では法務局・国税庁・各一次資料を必ず確認してください。"
    ),
    "search_invoice_by_houjin_partial": (
        "本 response は国税庁 適格請求書発行事業者公表データの機械的検索で、"
        "仕入税額控除の確定判断・税務助言 (税理士法 §52) は提供しません。"
        "最新の登録状況は国税庁公表サイトで必ず確認してください。"
    ),
    # --- Wave 21 composition tools (canonical disclaimer copies; the tool ----
    # bodies emit their own inline disclaimer string today, but registering
    # them here lets `disclaimer_for(name)` answer correctly for any future
    # caller that walks the SENSITIVE_TOOLS surface.) ------------------------
    "apply_eligibility_chain_am": (
        "本 response は am_subsidy_rule + am_compat_matrix + jpi_program 由来の "
        "適用判定チェーン検索で、申請書類作成・税務代理は提供しません (行政書士法 §1 / "
        "税理士法 §52)。chain_depth は heuristic 拡張、final 判定は申請要領 + 申告 "
        "ガイドラインを一次資料で確認し、資格を有する士業へご相談ください。"
    ),
    "find_complementary_programs_am": (
        "本 response は am_compat_matrix の機械的 peer 検索で、ポートフォリオ運用 "
        "助言・税務助言は提供しません (税理士法 §52 / 行政書士法 §1)。"
        "compat_status='unknown' rows は heuristic 由来。確定判断は資格を有する "
        "士業に必ずご相談ください。"
    ),
    "simulate_application_am": (
        "本 response は採択スコア mock で、申請可否担保・申請書面作成代行は提供 "
        "しません (行政書士法 §1)。score は am_application_round + heuristic "
        "feature の重み付き平均で、採択を担保しません。確定判断は資格を有する "
        "行政書士・中小企業診断士へ。"
    ),
    # --- 会計士 work-paper bundle tools (compose_audit_workpaper / ----------
    # audit_batch_evaluate / resolve_citation_chain). Server-side bodies in
    # mcp/server.py emit inline disclaimers via _KAIKEI_DISCLAIMER; mirroring
    # them here keeps disclaimer_for(name) symmetric.) -----------------------
    "compose_audit_workpaper": (
        "本 response は公開税制・補助金・法令情報の検索結果と機械的予測のみで、"
        "監査意見・税務判断・申告書作成代行は提供しません (公認会計士法 §47条の2 / "
        "税理士法 §52)。監査人は本書の内容を自らの責任において検証し、§47条の2 に "
        "従って監査調書を保存してください。"
    ),
    "audit_batch_evaluate": (
        "本 response は target_ruleset_ids × business_profile の機械的 evaluate "
        "ループ結果で、監査意見・税務判断・申告書作成代行は提供しません "
        "(公認会計士法 §47条の2 / 税理士法 §52)。anomaly_flag は heuristic 由来、"
        "確定判断は資格を有する公認会計士・税理士へ。"
    ),
    "resolve_citation_chain": (
        "本 response は am_law_article + tax_ruleset citations の引用 chain "
        "解決で、監査意見・税務判断・申告書作成代行は提供しません "
        "(公認会計士法 §47条の2 / 税理士法 §52)。各引用 row の source_url で "
        "原典を確認し、確定判断は資格を有する公認会計士・税理士へ。"
    ),
    # --- Vector kNN recommendation tools (recommend_similar.py) -----------
    "recommend_similar_program": (
        "本 response は sqlite-vec (am_entities_vec_S) 上の k-NN 検索結果で、"
        "採択を担保するものではありません。類似度は意味類似性の近似で、"
        "申請可否判断 (行政書士法 §1) ・税務助言 (税理士法 §52) の代替では "
        "ありません。verification_count + density_score (W22-9) で再ランクして "
        "いますが、これは検索品質シグナルであって採択スコアではありません。"
        "確定判断は資格を有する士業に必ずご相談ください。"
    ),
    "recommend_similar_case": (
        "本 response は sqlite-vec (am_entities_vec_C) 上の k-NN 検索結果で、"
        "採択事例間の意味類似性を返すだけです。類似 case があるからといって "
        "申請可否や採択を担保しません (行政書士法 §1)。各 case の source_url で "
        "原典を確認し、確定判断は資格を有する士業に必ずご相談ください。"
    ),
    "recommend_similar_court_decision": (
        "本 response は sqlite-vec (am_entities_vec_J) 上の k-NN 検索結果で、"
        "判例間の意味類似性を返すだけです。法解釈・法律判断 (弁護士法 §72) ・"
        "申請判断 (行政書士法 §1) の代替ではありません。各判例の source_url で "
        "原典を確認し、法解釈は資格を有する弁護士に必ずご相談ください。"
    ),
}

_DISCLAIMER_MINIMAL: dict[str, str] = {
    "dd_profile_am": (
        "公開データ検索 aggregation のみ。与信・反社・労務 DD (社労士法・弁護士法 §72) "
        "の代替不可。一次資料確認必須。"
    ),
    "regulatory_prep_pack": (
        "制度概要の検索のみ。申請代理は行政書士法 §1 の独占業務。一次資料確認必須。"
    ),
    "combined_compliance_check": (
        "公開ルール検索照合のみ。弁護士法 §72 / 税理士法 §52 / 行政書士法 §1 / 社労士法 "
        "の業務範囲外。確定判断は士業へ。"
    ),
    "rule_engine_check": (
        "公開コーパス検索照合のみ。heuristic rule を含む。"
        "業法 4 法 (弁護士・税理士・行政書士・社労士) の判断は対象外。"
    ),
    "predict_subsidy_outcome": (
        "統計的 score のみ。採択を担保せず、heuristic 含む。"
        "申請可否判断 (行政書士法 §1) の代替不可。"
    ),
    "score_dd_risk": (
        "公開処分ベース検索 score。与信・反社 (弁護士法 §72) ・労務 DD (社労士法) "
        "の代替不可。一次資料確認必須。"
    ),
    "intent_of": (
        "intent 分類のみ。業法 4 法 (弁護士・税理士・行政書士・社労士) の判断は対象外。"
    ),
    "reason_answer": (
        "決定論 pipeline 検索出力のみ。業法 4 法の判断は対象外、確定判断は士業へ。"
    ),
    "search_tax_incentives": (
        "国税庁・財務省 由来の税制措置検索のみ。税務助言ではない (税理士法 §52)。"
        "rate/sunset 改正可能。個別判断は税理士へ。"
    ),
    "get_am_tax_rule": (
        "単一税制措置 lookup のみ。税務助言ではない (税理士法 §52)。"
        "個別判断は税理士へ。"
    ),
    "list_tax_sunset_alerts": (
        "措置法廃止予定日の集計のみ。税務助言ではない (税理士法 §52)。"
        "延長・前倒し可能。個別判断は税理士へ。"
    ),
    # --- Wave 22 composition tools ---------------------------------------
    "match_due_diligence_questions": (
        "DD 質問 checklist のみ。信用調査・反社・労務 DD (弁護士法 §72 / 社労士法) ・"
        "税務助言 (税理士法 §52) の代替不可。確定判断は士業へ。"
    ),
    "prepare_kessan_briefing": (
        "決算期前後の制度変動 briefing のみ。税務代理 (税理士法 §52) ・"
        "申告書作成代行不可。確定判断は税理士・公認会計士へ。"
    ),
    "cross_check_jurisdiction": (
        "登記 / 公表 / 採択 jurisdiction 突合せのみ。税務代理 (税理士法 §52) ・"
        "登記申請 (司法書士法 §3) ・行政書士業務 (§1) の代替不可。"
    ),
    "bundle_application_kit": (
        "申請 kit scaffold + 一次 URL のみ。書面作成は行政書士法 §1 の独占業務、"
        "当社は提供しない。最終判断は行政書士へ。"
    ),
    # --- Wave 23 industry pack wrappers ----------------------------------
    "pack_construction": (
        "建設業 (JSIC D) cohort 検索 aggregation のみ。税務助言 (税理士法 §52) ・"
        "監査調書 (公認会計士法 §47条の2) の代替不可。一次資料確認必須。"
    ),
    "pack_manufacturing": (
        "製造業 (JSIC E) cohort 検索 aggregation のみ。税務助言 (税理士法 §52) ・"
        "監査調書 (公認会計士法 §47条の2) の代替不可。一次資料確認必須。"
    ),
    "pack_real_estate": (
        "不動産業 (JSIC K) cohort 検索 aggregation のみ。税務助言 (税理士法 §52) ・"
        "監査調書 (公認会計士法 §47条の2) の代替不可。一次資料確認必須。"
    ),
    "get_houjin_360_am": (
        "公開法人情報の機械的 join のみ。与信・反社・税務/法律判断の代替不可。"
        "一次資料確認必須。"
    ),
    "search_invoice_by_houjin_partial": (
        "国税庁公表データの検索のみ。仕入税額控除の確定判断・税務助言ではない。"
        "国税庁原典確認必須。"
    ),
    # --- Wave 21 composition tools ---------------------------------------
    "apply_eligibility_chain_am": (
        "適用判定 chain 検索のみ。申請代理 (行政書士法 §1) ・税務代理 "
        "(税理士法 §52) の代替不可。一次資料確認必須。"
    ),
    "find_complementary_programs_am": (
        "compat_matrix peer 検索のみ。税務助言 (税理士法 §52) ・申請代理 "
        "(行政書士法 §1) の代替不可。確定判断は士業へ。"
    ),
    "simulate_application_am": (
        "採択スコア mock のみ。採択を担保せず、heuristic 含む。"
        "申請可否判断 (行政書士法 §1) の代替不可。"
    ),
    # --- 会計士 work-paper bundle tools ----------------------------------
    "compose_audit_workpaper": (
        "公開税制 + 補助金検索結果のみ。監査意見・税務判断 "
        "(公認会計士法 §47条の2 / 税理士法 §52) の代替不可。"
    ),
    "audit_batch_evaluate": (
        "ruleset × profile 機械評価のみ。監査意見・税務判断 "
        "(公認会計士法 §47条の2 / 税理士法 §52) の代替不可。"
    ),
    "resolve_citation_chain": (
        "引用 chain 解決のみ。監査意見・税務判断 "
        "(公認会計士法 §47条の2 / 税理士法 §52) の代替不可。"
    ),
    # --- Vector kNN recommendation tools ----------------------------------
    "recommend_similar_program": (
        "vec k-NN 検索結果のみ。採択を担保せず、申請可否判断 (行政書士法 §1) ・"
        "税務助言 (税理士法 §52) の代替不可。"
    ),
    "recommend_similar_case": (
        "vec k-NN 検索結果のみ。採択事例の意味類似のみ、申請可否担保なし "
        "(行政書士法 §1)。"
    ),
    "recommend_similar_court_decision": (
        "vec k-NN 検索結果のみ。判例の意味類似のみ、法解釈 (弁護士法 §72) ・"
        "申請判断 (行政書士法 §1) の代替不可。"
    ),
}

_DISCLAIMER_STRICT_SUFFIX = (
    " 出力は AI 生成であり、内容の正確性・完全性は担保されません。"
    "業法 (弁護士法 §72 / 税理士法 §52 / 行政書士法 §1 / 社労士法) の "
    "業務範囲に該当する判断は当社サービス対象外です。"
    "本 API は検索インデックスです。検索結果には heuristic 由来の rule や "
    "partial provenance を含みます。業務判断には必ず primary source を直接確認してください。"
)


def disclaimer_for(tool_name: str, level: str = "standard") -> str | None:
    """Return the `_disclaimer` string for a sensitive tool, or None.

    Non-sensitive tools always return None. Unknown levels degrade to
    "standard" silently.
    """
    if tool_name not in SENSITIVE_TOOLS:
        return None
    lvl = level if level in ("strict", "standard", "minimal") else "standard"
    if lvl == "minimal":
        return _DISCLAIMER_MINIMAL.get(tool_name)
    base = _DISCLAIMER_STANDARD.get(tool_name)
    if base is None:
        return None
    if lvl == "strict":
        return base + _DISCLAIMER_STRICT_SUFFIX
    return base


def _explanation_for(
    tool_name: str,
    status: str,
    *,
    result_count: int = 0,
    router_explain: str | None = None,
) -> str:
    """Pick an explanation string >= 20 chars.

    Precedence:
      1. router_explain (from reasoning.query_route.route) if given
      2. DEFAULT_EXPLANATIONS[tool_name][status]
      3. _FALLBACK_EXPLAIN[status]
    For rich/sparse we try to include the count as a prefix when possible.
    """
    if router_explain and len(router_explain) >= 20 and status == "empty":
        return router_explain
    by_tool = DEFAULT_EXPLANATIONS.get(tool_name, {})
    text = by_tool.get(status) or _FALLBACK_EXPLAIN.get(status) or _FALLBACK_EXPLAIN["empty"]
    if status in ("rich", "sparse") and result_count > 0:
        # Prepend a count marker for LLM-friendliness; preserves >=20 char rule.
        return f"{result_count} 件の候補が見つかりました。" + text
    return text


# ---------------------------------------------------------------------------
# Suggested-action synthesis
# ---------------------------------------------------------------------------


def _default_suggested_actions(
    tool_name: str,
    status: str,
    *,
    legacy_retry_with: list[str] | None = None,
) -> list[dict[str, str]]:
    """Derive a list of {action, details} dicts from bucket + tool identity.

    Customer-LLM playbook:
      rich   -> no suggestion (the answer is enough)
      sparse -> broaden_query, plus optional alternative tool
      empty  -> consult_primary_source + alternative tool + clarification
      error  -> retry_with_backoff (+ alternative tool if soft severity)
    """
    actions: list[dict[str, str]] = []
    if status == "rich":
        return actions

    if status == "sparse":
        actions.append({
            "action": "broaden_query",
            "details": "都道府県・業種などフィルタを 1 つ外して再検索すると候補が増えます。",
        })
        if legacy_retry_with:
            actions.append({
                "action": "try_alternative_tool",
                "details": f"代替ツール候補: {', '.join(legacy_retry_with[:3])}",
            })
        return actions

    if status == "empty":
        actions.append({
            "action": "broaden_query",
            "details": "地域・期間・金額条件のいずれかを外すと該当件数が増える可能性があります。",
        })
        if legacy_retry_with:
            actions.append({
                "action": "try_alternative_tool",
                "details": f"代替ツール候補: {', '.join(legacy_retry_with[:3])}",
            })
        else:
            # Provide sensible defaults per tool family
            actions.append({
                "action": "try_alternative_tool",
                "details": "search_programs_fts で自由語検索を試してください。",
            })
        actions.append({
            "action": "consult_primary_source",
            "details": "DB 未収録の可能性があります。該当官庁の一次資料 URL をご確認ください。",
        })
        actions.append({
            "action": "ask_user_for_clarification",
            "details": "業種・地域・時期の指定を具体化すると精度が上がります。",
        })
        return actions

    # status == "error"
    actions.append({
        "action": "retry_with_backoff",
        "details": "数秒待って再試行してください。継続する場合は管理者へ連絡を。",
    })
    return actions


# ---------------------------------------------------------------------------
# Router / empty-explanation integration (soft import)
# ---------------------------------------------------------------------------


def _router_explain(query: str | None) -> str | None:
    """Call reasoning.query_route.route(query) and return explain_empty.

    Soft import — if the reasoning module is not importable (missing dep,
    sandboxed test, etc.) we return None and let the caller fall back
    to DEFAULT_EXPLANATIONS.
    """
    if not query or not isinstance(query, str) or not query.strip():
        return None
    try:
        from reasoning.query_route import route  # type: ignore
    except Exception:  # pragma: no cover - soft dependency
        return None
    try:
        decision = route(query)
        return getattr(decision, "explain_empty", None)
    except Exception:  # pragma: no cover - defensive
        return None


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


def _classify_exception(exc: BaseException) -> tuple[str, str]:
    """Map an exception to (error_code, severity). Mirrors tools._db_error."""
    if isinstance(exc, sqlite3.OperationalError):
        msg = str(exc).lower()
        if "locked" in msg or "busy" in msg:
            return "db_locked", "hard"
        return "db_unavailable", "hard"
    if isinstance(exc, sqlite3.Error):
        return "db_unavailable", "hard"
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "internal", "hard"
    return "internal", "hard"


# ---------------------------------------------------------------------------
# Public API: @with_envelope decorator
# ---------------------------------------------------------------------------


def _coerce_results(payload: Any) -> tuple[list, dict[str, Any]]:
    """Accept either a bare list of results or the legacy envelope dict.

    Returns (results_list, extra_kv) where extra_kv holds {total, limit,
    offset, hint, retry_with} if the legacy envelope shape was used.
    """
    if isinstance(payload, list):
        return list(payload), {}
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            extras: dict[str, Any] = {}
            for k in ("total", "limit", "offset", "hint", "retry_with"):
                if k in payload:
                    extras[k] = payload[k]
            # Pull through any additional tool-specific fields so they are
            # preserved on the final envelope (e.g. seed_name).
            for k, v in payload.items():
                if k not in {"results", "total", "limit", "offset",
                             "hint", "retry_with", "error"}:
                    extras.setdefault(k, v)
            return list(results), extras
        # No `results` key -> treat the whole dict as a single record.
        return [payload], {}
    if payload is None:
        return [], {}
    return [payload], {}


def _count_evidence_sources(results: list) -> int:
    """Count how many records cite a primary-source URL.

    A record is "primary-source cited" if it has a non-empty
    source_url / primary_source / evidence_span / source field
    pointing at an authoritative host. We deliberately over-count
    slightly rather than under-count; the goal is for the customer
    LLM to refuse citation when evidence is truly zero.
    """
    count = 0
    primary_hosts = (
        "maff.go.jp", "meti.go.jp", "mof.go.jp", "jfc.go.jp",
        "nta.go.jp", "chusho.meti.go.jp", "env.go.jp", "mlit.go.jp",
        "mhlw.go.jp", "e-gov.go.jp", "j-net21.smrj.go.jp",
        ".lg.jp", ".pref.", ".city.",
    )
    for r in results:
        if not isinstance(r, dict):
            continue
        # Try several common field names.
        urls: list[str] = []
        for k in ("source_url", "primary_source", "evidence_url",
                  "url", "authority_url"):
            v = r.get(k)
            if isinstance(v, str) and v:
                urls.append(v)
        # evidence_span may be a list of dicts with their own url
        span = r.get("evidence_span") or r.get("evidence") or []
        if isinstance(span, list):
            for s in span:
                if isinstance(s, dict):
                    v = s.get("url") or s.get("source_url")
                    if isinstance(v, str) and v:
                        urls.append(v)
        if any(any(host in u for host in primary_hosts) for u in urls):
            count += 1
    return count


def _maybe_attach_uncertainty(results: list) -> dict[str, Any] | None:
    """Mutate `results` to add per-fact `_uncertainty` and return a summary.

    O8 default-injection rule (mirrors `pii_redact_response_enabled`):

      * Each result that looks like a fact (carries `fact_id` AND any of
        `field_kind` / `field_name` / `license`) gets a fresh
        ``_uncertainty`` dict computed from the fact-row itself when the
        relevant columns are already on the dict, otherwise from the
        `am_uncertainty_view` SQL view if a connection is reachable.
      * Result rows without `fact_id` are left untouched — those are
        program / case / loan summaries, not raw facts.

    Returns a top-level summary dict (mean score + label histogram) when
    at least one fact got a score; None otherwise (so the envelope skips
    the `_uncertainty` summary key entirely on non-fact responses).

    Resilience: a failure inside scoring never breaks the envelope —
    we swallow exceptions and leave `_uncertainty` absent on the
    offending row. Honest under-promise vs. silent over-claim.
    """
    # Feature flag honours the same one-flag rollback pattern as
    # `pii_redact_response_enabled`. We import lazily because config may
    # not be initialised in pure unit tests.
    try:
        from jpintel_mcp.config import settings  # local import on purpose
        if not getattr(settings, "uncertainty_enabled", True):
            return None
    except Exception:
        # Sandbox without settings — fail open and keep injecting; the
        # math is pure-Python and never calls the network.
        pass

    if _o8_score_fact is None:
        return None

    label_hist: dict[str, int] = {
        "high": 0, "medium": 0, "low": 0, "unknown": 0,
    }
    score_sum = 0.0
    score_count = 0

    # Lazy DB connection — only opened when we encounter a fact row that
    # needs the SQL view (i.e. license / field_kind missing on the dict).
    _conn_holder: dict[str, Any] = {"conn": None, "tried": False}

    def _conn() -> Any:
        if _conn_holder["tried"]:
            return _conn_holder["conn"]
        _conn_holder["tried"] = True
        try:
            import sqlite3 as _sqlite3

            from jpintel_mcp.config import settings as _s
            conn = _sqlite3.connect(str(_s.autonomath_db_path))
            conn.row_factory = _sqlite3.Row
            _conn_holder["conn"] = conn
            return conn
        except Exception:
            return None

    for row in results:
        if not isinstance(row, dict):
            continue
        if "fact_id" not in row:
            continue
        # Skip rows that already carry _uncertainty (idempotent).
        if "_uncertainty" in row and row["_uncertainty"]:
            unc = row["_uncertainty"]
            label = unc.get("label", "unknown")
            label_hist[label] = label_hist.get(label, 0) + 1
            score_sum += float(unc.get("score") or 0.0)
            score_count += 1
            continue
        try:
            unc: dict[str, Any] | None = None  # type: ignore[no-redef]
            # Prefer in-row fields when present (no DB call).
            if "field_kind" in row or "license" in row:
                unc = _o8_score_fact(
                    field_kind=row.get("field_kind"),
                    license_value=row.get("license"),
                    days_since_fetch=row.get("days_since_fetch"),
                    n_sources=int(row.get("n_sources") or 0),
                    agreement=int(row.get("agreement") or 0),
                )
            else:
                # Fall back to the SQL view.
                conn = _conn()
                if conn is not None and _o8_get_uncertainty_for_fact:
                    unc = _o8_get_uncertainty_for_fact(
                        int(row["fact_id"]), conn,
                    )
            if unc:
                row["_uncertainty"] = unc
                label = unc.get("label", "unknown")
                label_hist[label] = label_hist.get(label, 0) + 1
                score_sum += float(unc.get("score") or 0.0)
                score_count += 1
        except Exception:
            # Never break the envelope on a per-row scoring fault.
            continue

    # Close the lazy connection if we opened one.
    conn = _conn_holder["conn"]
    if conn is not None:
        with contextlib.suppress(Exception):
            conn.close()

    if score_count == 0:
        return None
    return {
        "mean_score": round(score_sum / score_count, 4),
        "label_histogram": label_hist,
        "n_facts_scored": score_count,
        "model": "beta_posterior_v1",
    }


def build_envelope(
    *,
    tool_name: str,
    results: list,
    query_echo: str = "",
    latency_ms: float = 0.0,
    legacy_extras: dict | None = None,
    error: dict | None = None,
    router_query: str | None = None,
    tool_kwargs: dict[str, Any] | None = None,
    api_key_created_at: str | None = None,
    fields: str = "standard",
    http_status: int | None = None,
    disclaimer_level: str = "standard",
) -> dict[str, Any]:
    """Assemble the canonical ResponseEnvelope v2 dict.

    Public for unit tests that want to verify shape without going through
    a real tool call.

    Tier 1 CS additions (P3-M++, dd_v8_08, additive only):
      - ``meta`` block built by :func:`cs_features.build_meta`
        (suggestions / alternative_intents / input_warnings /
        token_estimate / wall_time_ms / tips). Suppressed when
        ``fields="minimal"``.
      - ``error.user_message`` + ``error.retry_after`` +
        ``error.alternate_endpoint`` enrichment via
        :func:`cs_features.enhance_error_with_retry`.
    """
    legacy_extras = legacy_extras or {}
    if error is not None:
        status = "error"
        result_count = 0
        results = []
    else:
        result_count = len(results)
        status = classify_bucket(result_count)

    router_explain = _router_explain(router_query) if status == "empty" else None
    explanation = _explanation_for(
        tool_name, status,
        result_count=result_count,
        router_explain=router_explain,
    )

    legacy_retry = legacy_extras.get("retry_with")
    suggested = _default_suggested_actions(
        tool_name, status,
        legacy_retry_with=legacy_retry if isinstance(legacy_retry, list) else None,
    )

    envelope: dict[str, Any] = {
        "status": status,
        "results": results,
        "result_count": result_count,
        "explanation": explanation,
        "suggested_actions": suggested,
        "api_version": ENVELOPE_API_VERSION,
        "tool_name": tool_name,
        "query_echo": query_echo or "",
        "latency_ms": round(float(latency_ms), 3),
        "evidence_source_count": _count_evidence_sources(results),
        # --- legacy back-compat fields ---
        "total": int(legacy_extras.get("total", result_count)),
        "limit": int(legacy_extras.get("limit", max(1, result_count))),
        "offset": int(legacy_extras.get("offset", 0)),
        "hint": legacy_extras.get("hint"),
    }
    # retry_with is kept as a structured dict; legacy list form is surfaced
    # via suggested_actions only.
    if status in ("sparse", "empty") and not legacy_retry:
        envelope["retry_with"] = None
    elif isinstance(legacy_retry, dict):
        envelope["retry_with"] = dict(legacy_retry)
    if error is not None:
        # Enrich with retry_after / alternate_endpoint / user_message
        # (Feature E + J). Pure additive — never overwrites existing keys.
        envelope["error"] = enhance_error_with_retry(
            error, http_status=http_status,
        )
    # Feature A/B/F: meta block (opt-out via fields="minimal").
    meta = build_meta(
        tool_name=tool_name,
        status=status,
        query_echo=query_echo or "",
        latency_ms=latency_ms,
        results=results,
        legacy_extras=legacy_extras,
        kwargs=tool_kwargs,
        api_key_created_at=api_key_created_at,
        fields=fields,
    )
    if meta is not None:
        envelope["meta"] = meta

    # S7 finding (2026-04-25): uniform `_disclaimer` envelope on every
    # sensitive tool. Non-sensitive tools (search_*, get_meta, ...) get
    # None back from disclaimer_for() so the field stays absent.
    disclaimer_text = disclaimer_for(tool_name, disclaimer_level)
    if disclaimer_text:
        envelope["_disclaimer"] = disclaimer_text

    # O8 finding (2026-04-25): default-inject `_uncertainty` on rows
    # that look like raw facts (carry `fact_id`). Mirrors the
    # `pii_redact_response_enabled` rollback pattern via
    # `AUTONOMATH_UNCERTAINTY_ENABLED`. Honest fence: avoid surfacing a
    # summary on tools that never return facts (search_programs etc.).
    if error is None and results:
        unc_summary = _maybe_attach_uncertainty(results)
        if unc_summary is not None:
            envelope["_uncertainty"] = unc_summary
    return envelope


def with_envelope(
    tool_name: str,
    *,
    query_arg: str = "query",
) -> Callable[[Callable[..., Any]], Callable[..., dict[str, Any]]]:
    """Decorator: wrap an MCP tool so its return value is a v2 envelope.

    Parameters
    ----------
    tool_name : str
        Canonical tool name recorded on the envelope.
    query_arg : str
        Name of the kwarg to read as `query_echo` and feed to the router
        for empty-explanation. Default "query". If the tool takes a
        different kwarg (e.g. law_name, program_id), pass that name.

    Usage
    -----
    >>> @with_envelope("search_tax_incentives")
    ... def search_tax_incentives(*, query: str, limit: int = 20): ...

    The inner function may return either:
      - a plain list[dict] of results, or
      - a dict with `results: list[dict]` plus optional legacy fields
        (total, limit, offset, hint, retry_with), or
      - an error envelope from error_envelope.make_error().

    On exception, we emit an envelope with status="error".
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., dict[str, Any]]:
        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
            t0 = time.perf_counter()
            query_echo = str(kwargs.get(query_arg) or "")
            # Tier 1 CS args are pulled OUT of kwargs before the wrapped
            # function sees them — they are control-plane only and the
            # underlying tool does not declare them.
            fields = str(kwargs.pop("__envelope_fields__", "standard"))
            api_key_created_at = kwargs.pop("__api_key_created_at__", None)
            # Snapshot the (post-extraction) kwargs for the meta block's
            # input_warnings analysis. We deliberately copy *after* the
            # control-plane args were popped so they don't show up.
            tool_kwargs_snapshot = dict(kwargs)
            try:
                raw = fn(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - exercised via tests
                code, severity = _classify_exception(exc)
                err = safe_internal_error_payload(
                    exc,
                    logger=logger,
                    tool_name=tool_name,
                    extra={"tool_kwargs": tool_kwargs_snapshot},
                    code=code,
                    severity=severity,
                )
                err["hint"] = ERROR_CODES.get(code, ERROR_CODES["internal"])["summary"]
                latency = (time.perf_counter() - t0) * 1000.0
                return build_envelope(
                    tool_name=tool_name,
                    results=[],
                    query_echo=query_echo,
                    latency_ms=latency,
                    error=err,
                    router_query=query_echo,
                    tool_kwargs=tool_kwargs_snapshot,
                    api_key_created_at=api_key_created_at,
                    fields=fields,
                )

            # Preserve errors from make_error()
            if is_error(raw):
                err_obj = raw.get("error") if isinstance(raw, dict) else None
                latency = (time.perf_counter() - t0) * 1000.0
                return build_envelope(
                    tool_name=tool_name,
                    results=[],
                    query_echo=query_echo,
                    latency_ms=latency,
                    error=err_obj,
                    router_query=query_echo,
                    tool_kwargs=tool_kwargs_snapshot,
                    api_key_created_at=api_key_created_at,
                    fields=fields,
                )

            results, extras = _coerce_results(raw)
            latency = (time.perf_counter() - t0) * 1000.0
            return build_envelope(
                tool_name=tool_name,
                results=results,
                query_echo=query_echo,
                latency_ms=latency,
                legacy_extras=extras,
                router_query=query_echo,
                tool_kwargs=tool_kwargs_snapshot,
                api_key_created_at=api_key_created_at,
                fields=fields,
            )

        # Expose the bare function for tests that want to bypass wrapping.
        wrapped.__wrapped__ = fn  # type: ignore[attr-defined]
        wrapped.tool_name = tool_name  # type: ignore[attr-defined]
        return wrapped

    return decorator


__all__ = [
    "with_envelope",
    "build_envelope",
    "classify_bucket",
    "ENVELOPE_API_VERSION",
    "DEFAULT_EXPLANATIONS",
    # S7 disclaimer surface
    "SENSITIVE_TOOLS",
    "disclaimer_for",
    # Re-exports from cs_features for convenient single-import access
    "build_meta",
    "enhance_error_with_retry",
]
