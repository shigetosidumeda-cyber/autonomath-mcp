"""Lightweight i18n message catalog for AutonoMath MCP / REST responses.

P6-E (English V4) scaffolding — landed 2026-04-25 ahead of the T+150d
launch slot. This module is deliberately tiny:

  - **No** runtime dependency (no babel, no gettext, no .po files).
  - **No** machine translation; every English string is hand-curated to
    match the i18n style guide (`docs/i18n_style_guide.md`).
  - **ja default** to preserve backward compatibility — every existing
    caller that does not pass `response_language` keeps Japanese output.

Usage::

    from jpintel_mcp.i18n import t

    t("envelope.empty.search_tax_incentives")           # → ja
    t("envelope.empty.search_tax_incentives", "en")     # → en
    t("missing.key.does.not.exist", "en")               # → "missing.key.does.not.exist" (key fallback)

Tool layer (T+150d): every autonomath tool will accept a
`response_language: Literal["ja", "en"] | None = "ja"` parameter and
route user-facing strings (envelope.explanation, envelope.suggestions,
envelope.meta.tips, error.user_message) through `t(key, lang)`.

Catalog scope (P6-E scaffolding):
  - 50+ keys covering envelope status messages for the 16 autonomath
    tools (rich / sparse / empty / error × 10 named tools + fallback)
    + 7 one-shot discovery tool error fallbacks
    + onboarding tips + common error user_messages.
  - Full ~200 key expansion happens D2-D3 of the 10-day plan.

Style anchors (mirror i18n_style_guide.md):
  - English tone: professional but friendly (Stripe / GitHub register).
  - Japanese law names: keep Japanese name, add English transliteration
    in parens at first reference (e.g. "法人税法 (Corporate Tax Act)").
  - Public agencies: Japanese name + official English in parens
    (METI / MHLW / FSA / NTA / JFC / SMRJ).
  - URL hostnames stay verbatim (e.g. e-Gov, j-net21, mirasapo-plus).
"""
from __future__ import annotations

from typing import Final, Literal

LangCode = Literal["ja", "en"]


# ---------------------------------------------------------------------------
# Message catalog
# ---------------------------------------------------------------------------
# Keys are dotted strings: "<surface>.<status>.<tool>" for envelope text,
# "error.<code>" for error.user_message, "tips.<n>" for onboarding tips.
#
# Every entry MUST provide both "ja" and "en". Tests assert this.
# Strings MUST be >= 20 chars in ja (matching envelope_wrapper.py min)
# but English may be shorter (English is denser by char count).
# ---------------------------------------------------------------------------

MESSAGES: Final[dict[str, dict[LangCode, str]]] = {
    # -- Generic fallback (used when tool-specific key not found) -----
    "envelope.rich.fallback": {
        "ja": "関連する情報が十分件数見つかりました。引用元を明示した上で提示してください。",
        "en": "Sufficient matches found. Please cite the source URL before presenting.",
    },
    "envelope.sparse.fallback": {
        "ja": "関連する情報は少数のみでした。検索条件を広げると追加候補が見つかる可能性があります。",
        "en": "Only a few matches. Widening the query may surface additional candidates.",
    },
    "envelope.empty.fallback": {
        "ja": "該当する情報は当 DB に収録されていません。条件を広げるか一次資料をご確認ください。",
        "en": "No matches in this DB. Widen the query or check the primary source directly.",
    },
    "envelope.error.fallback": {
        "ja": "取得が一時的に失敗しました。時間をおいて再度お試しください。",
        "en": "Lookup temporarily failed. Please retry after a short interval.",
    },

    # -- search_tax_incentives ----------------------------------------
    "envelope.rich.search_tax_incentives": {
        "ja": "税制特例が十分件数見つかりました。適用期限と対象を確認して引用してください。",
        "en": "Sufficient tax incentives found. Verify the sunset date (適用期限) and eligible scope before citing.",
    },
    "envelope.sparse.search_tax_incentives": {
        "ja": "税制特例は少数のみ該当しました。条件を広げると追加候補が見つかる可能性があります。",
        "en": "Few tax incentives matched. Widening filters may surface more candidates.",
    },
    "envelope.empty.search_tax_incentives": {
        "ja": "指定条件の税制特例は当 DB に収録されていません。条件を広げるか国税庁原典をご確認ください。",
        "en": "No tax incentive matches for these filters. Widen the query or consult the NTA (国税庁) primary source.",
    },
    "envelope.error.search_tax_incentives": {
        "ja": "税制検索が一時的に失敗しました。時間をおいて再度お試しください。",
        "en": "Tax incentive search temporarily failed. Please retry after a short interval.",
    },

    # -- search_certifications ----------------------------------------
    "envelope.rich.search_certifications": {
        "ja": "該当する認定制度が複数見つかりました。取得手続きの一次資料リンクを確認してください。",
        "en": "Multiple certifications matched. Verify the application procedure on the primary-source link before citing.",
    },
    "envelope.sparse.search_certifications": {
        "ja": "該当認定は少数のみでした。認定名の正式名称で再検索すると精度が上がります。",
        "en": "Few certifications matched. Re-querying with the official Japanese name will improve precision.",
    },
    "envelope.empty.search_certifications": {
        "ja": "該当する認定制度は当 DB に未登録です。経営革新計画など主要 14 認定から再指定してください。",
        "en": "No certification matches in this DB. Try one of the 14 major certifications (e.g. 経営革新計画 / Management Innovation Plan).",
    },
    "envelope.error.search_certifications": {
        "ja": "認定検索が一時的に失敗しました。時間をおいて再度お試しください。",
        "en": "Certification search temporarily failed. Please retry after a short interval.",
    },

    # -- list_open_programs -------------------------------------------
    "envelope.rich.list_open_programs": {
        "ja": "現在公募中の制度が複数あります。締切順に並べて提示してください。",
        "en": "Multiple programs currently open. Sort by deadline (締切) when presenting to the user.",
    },
    "envelope.sparse.list_open_programs": {
        "ja": "現在公募中の該当制度は少数です。対象期間や地域条件を広げることを検討してください。",
        "en": "Few programs are open right now. Consider widening the time window or region filter.",
    },
    "envelope.empty.list_open_programs": {
        "ja": "指定条件で現在公募中の制度は DB にありません。次回公募時期は各制度の個別照会を推奨します。",
        "en": "No open programs match these filters. For next-round timing, query each program individually.",
    },
    "envelope.error.list_open_programs": {
        "ja": "公募情報の取得が一時的に失敗しました。時間をおいて再度お試しください。",
        "en": "Open-call lookup temporarily failed. Please retry after a short interval.",
    },

    # -- search_by_law -------------------------------------------------
    "envelope.rich.search_by_law": {
        "ja": "指定法令に紐づく制度が複数見つかりました。法改正履歴の有無も合わせて確認してください。",
        "en": "Multiple programs link to this statute. Also verify whether amendment history applies.",
    },
    "envelope.sparse.search_by_law": {
        "ja": "指定法令に紐づく制度は少数です。法令の正式名称 (例: 中小企業等経営強化法) で再検索してください。",
        "en": "Few programs link to this statute. Re-query with the official law name (e.g. 中小企業等経営強化法 / SME Management Enhancement Act).",
    },
    "envelope.empty.search_by_law": {
        "ja": "指定法令に紐づく制度は当 DB に未収録です。e-Gov で法令原文を確認する案内が適切です。",
        "en": "No programs link to this statute in this DB. Consult the e-Gov law portal for the primary text.",
    },
    "envelope.error.search_by_law": {
        "ja": "法令検索が一時的に失敗しました。時間をおいて再度お試しください。",
        "en": "Law-linkage search temporarily failed. Please retry after a short interval.",
    },

    # -- active_programs_at -------------------------------------------
    "envelope.rich.active_programs_at": {
        "ja": "指定日に施行中の制度が十分件数見つかりました。適用期限を確認の上ご案内ください。",
        "en": "Sufficient programs were active on the given date. Verify each sunset date before responding.",
    },
    "envelope.sparse.active_programs_at": {
        "ja": "指定日に施行中の制度は少数です。前後の日付を試すと追加候補が見つかる可能性があります。",
        "en": "Few programs were active on that date. Trying nearby dates may surface more candidates.",
    },
    "envelope.empty.active_programs_at": {
        "ja": "指定日に施行中だった制度は DB にありません。日付指定の書式や範囲をご確認ください。",
        "en": "No programs were active on that date in this DB. Double-check the date format and range.",
    },
    "envelope.error.active_programs_at": {
        "ja": "施行期間検索が一時的に失敗しました。時間をおいて再度お試しください。",
        "en": "Effective-date search temporarily failed. Please retry after a short interval.",
    },

    # -- related_programs ---------------------------------------------
    "envelope.rich.related_programs": {
        "ja": "指定制度に関連する制度が複数見つかりました。関係種別 (前提/競合/後継) を明示してください。",
        "en": "Multiple related programs found. State the relation kind (prerequisite / conflict / successor) when presenting.",
    },
    "envelope.sparse.related_programs": {
        "ja": "関連制度は少数のみ見つかりました。種別フィルタを外すと追加関連が得られる場合があります。",
        "en": "Few related programs found. Removing the relation-kind filter may surface more.",
    },
    "envelope.empty.related_programs": {
        "ja": "指定 seed の関連制度はグラフ上に未登録です。seed_id の表記揺れをご確認ください。",
        "en": "No related programs in the graph for this seed. Check the seed_id for spelling variants.",
    },
    "envelope.error.related_programs": {
        "ja": "関連制度検索が一時的に失敗しました。時間をおいて再度お試しください。",
        "en": "Relation-graph search temporarily failed. Please retry after a short interval.",
    },

    # -- search_acceptance_stats --------------------------------------
    "envelope.rich.search_acceptance_stats": {
        "ja": "採択統計が複数回次で見つかりました。採択率の推移で提示してください。",
        "en": "Acceptance stats found across multiple rounds. Present the acceptance-rate trend over time.",
    },
    "envelope.sparse.search_acceptance_stats": {
        "ja": "採択統計は少数回次のみ DB に存在します。制度名の表記揺れをご確認ください。",
        "en": "Only a few rounds have acceptance stats. Check the program name for spelling variants.",
    },
    "envelope.empty.search_acceptance_stats": {
        "ja": "該当制度の採択統計は DB に未登録です。採択者発表 PDF の一次資料をご案内ください。",
        "en": "No acceptance stats for this program in the DB. Direct the user to the official acceptance-list PDF.",
    },
    "envelope.error.search_acceptance_stats": {
        "ja": "採択統計の取得が一時的に失敗しました。時間をおいて再度お試しください。",
        "en": "Acceptance-stat lookup temporarily failed. Please retry after a short interval.",
    },

    # -- enum_values --------------------------------------------------
    "envelope.rich.enum_values": {
        "ja": "指定 enum の候補値を取得しました。この enum から値を選んで再検索してください。",
        "en": "Enum candidate values returned. Pick a value from this list and re-query.",
    },
    "envelope.empty.enum_values": {
        "ja": "指定 enum は未登録または空です。enum 名の綴りをご確認ください。",
        "en": "Unknown or empty enum. Check the enum name spelling.",
    },
    "envelope.error.enum_values": {
        "ja": "enum 値の取得が一時的に失敗しました。時間をおいて再度お試しください。",
        "en": "Enum-value lookup temporarily failed. Please retry after a short interval.",
    },

    # -- intent_of ----------------------------------------------------
    "envelope.rich.intent_of": {
        "ja": "質問の意図を複数候補で推定しました。confidence 最上位を採用するのが安全です。",
        "en": "Multiple intent candidates inferred. Adopting the top-confidence pick is the safe default.",
    },
    "envelope.sparse.intent_of": {
        "ja": "意図推定の候補が少数でした。質問文をより具体的に再入力すると精度が上がります。",
        "en": "Few intent candidates. Re-entering a more specific question improves accuracy.",
    },
    "envelope.empty.intent_of": {
        "ja": "質問から意図を推定できませんでした。業種・制度名・時期を含めて再入力してください。",
        "en": "Could not infer intent. Re-enter the question including industry, program name, and timing.",
    },
    "envelope.error.intent_of": {
        "ja": "意図推定が一時的に失敗しました。時間をおいて再度お試しください。",
        "en": "Intent inference temporarily failed. Please retry after a short interval.",
    },

    # -- reason_answer ------------------------------------------------
    "envelope.rich.reason_answer": {
        "ja": "推論根拠を複数件取得しました。引用元 URL を必ず提示してから結論を述べてください。",
        "en": "Multiple reasoning citations retrieved. Always present source URLs before stating the conclusion.",
    },
    "envelope.sparse.reason_answer": {
        "ja": "推論根拠は少数のみ得られました。追加情報の確認を人間に促すのが安全です。",
        "en": "Only a few reasoning citations available. Asking the human to verify is the safer path.",
    },
    "envelope.empty.reason_answer": {
        "ja": "推論に必要な根拠が DB にありません。推測での回答は避け、原典参照をご案内ください。",
        "en": "No supporting evidence in the DB. Avoid guessing — direct the user to the primary source.",
    },
    "envelope.error.reason_answer": {
        "ja": "推論エンジンが一時的に失敗しました。時間をおいて再度お試しください。",
        "en": "Reasoning engine temporarily failed. Please retry after a short interval.",
    },

    # -- common error.user_message ------------------------------------
    "error.rate_limit": {
        "ja": "リクエスト上限を超えました。匿名は月 50 件、API キーは契約上限までご利用いただけます。",
        "en": "Request limit exceeded. Anonymous tier allows 50/month; API-key tier allows up to your subscription limit.",
    },
    "error.invalid_param": {
        "ja": "パラメータが不正です。docs/api-reference.md の該当ツール項目をご確認ください。",
        "en": "Invalid parameter. See the corresponding tool entry in docs/api-reference.md.",
    },
    "error.not_found": {
        "ja": "指定 ID の該当データが DB に存在しません。表記揺れや廃止済み ID の可能性があります。",
        "en": "No data exists for the given ID. The ID may be misspelled or refer to a discontinued program.",
    },
    "error.internal": {
        "ja": "サーバ内部エラーが発生しました。時間をおいて再試行してください。",
        "en": "Internal server error. Please retry after a short interval.",
    },
    "error.upstream_unavailable": {
        "ja": "DB が一時的に利用できません。Fly.io Tokyo region の status をご確認ください。",
        "en": "Database is temporarily unavailable. Please check the Fly.io Tokyo-region status.",
    },

    # -- onboarding tips (subset) -------------------------------------
    "tips.first_call": {
        "ja": "初回呼び出しありがとうございます。/v1/programs/search から始めると主要 11,211 件を横断検索できます。",
        "en": "Thanks for your first call. Start with /v1/programs/search to query the 11,211-program corpus.",
    },
    "tips.cite_primary_source": {
        "ja": "回答時は必ず source_url を引用してください。アグリゲータ転載は誤情報リスクがあります。",
        "en": "Always cite source_url in answers. Aggregator re-posts carry a misinformation risk.",
    },
    "tips.use_phrase_query": {
        "ja": "FTS5 trigram のため、2 文字以上の漢字熟語は \"税額控除\" のように引用符で句検索してください。",
        "en": "Because FTS5 uses trigram tokenization, wrap multi-kanji terms in quotes (e.g. \"税額控除\") for phrase queries.",
    },
    "tips.tier_hint": {
        "ja": "tier='X' は隔離行です。検索パスでは必ず tier IN ('S','A','B','C') で絞り込んでください。",
        "en": "tier='X' is the quarantine row. Always filter tier IN ('S','A','B','C') in search paths.",
    },
    "tips.jst_reset": {
        "ja": "匿名 50 req/月 は JST 月初 00:00 にリセットされます。API キーの日次クォータは UTC 0:00 (毎日) にリセットされます。",
        "en": "Anonymous 50 req/month resets at JST month-start (00:00). API-key daily quotas reset at UTC midnight (every day).",
    },
    "tips.pricing": {
        "ja": "従量課金は ¥3/req (税込 ¥3.30) のみ、tier 無し・年間最低保証無し・席数課金無しです。",
        "en": "Metered pricing is ¥3 per request only (tax-inc. ¥3.30). No tiers, no annual minimums, no seat fees.",
    },
}


def t(key: str, lang: LangCode | str = "ja") -> str:
    """Resolve a message key for the requested language.

    Resolution order:
      1. Exact (key, lang) hit.
      2. (key, "ja") fallback if `lang` was non-Japanese and missing.
      3. The literal `key` string (so callers always get *something*
         renderable — never raises KeyError, never returns None).

    Unknown languages other than {"ja","en"} fall back to "ja" silently
    rather than raising — this keeps tool wiring forgiving when callers
    pass through user input that has not been validated yet.
    """
    if lang not in ("ja", "en"):
        lang = "ja"
    bucket = MESSAGES.get(key)
    if bucket is None:
        return key
    if lang in bucket:
        return bucket[lang]
    # English missing — degrade to Japanese rather than the raw key,
    # since "ja" is always present per catalog invariant.
    return bucket.get("ja", key)


def has_key(key: str) -> bool:
    """True iff the catalog contains both ja and en for this key."""
    bucket = MESSAGES.get(key)
    if bucket is None:
        return False
    return "ja" in bucket and "en" in bucket


def supported_languages() -> tuple[LangCode, ...]:
    """The closed set of supported language codes."""
    return ("ja", "en")


def all_keys() -> tuple[str, ...]:
    """Every catalog key, sorted. Used by tests."""
    return tuple(sorted(MESSAGES.keys()))


__all__ = [
    "LangCode",
    "MESSAGES",
    "all_keys",
    "has_key",
    "supported_languages",
    "t",
]
