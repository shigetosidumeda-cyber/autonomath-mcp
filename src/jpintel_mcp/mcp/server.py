"""AutonoMath MCP server.

Exposes the same operations as the REST API, but as MCP tools for clients
like Claude Desktop, Cursor, ChatGPT (2025-10+), Gemini, etc.

Run:
    autonomath-mcp       # stdio transport (default for Claude Desktop)
    python -m jpintel_mcp.mcp.server
"""
from __future__ import annotations

import functools
import inspect
import json
import logging
import sqlite3
import time
import unicodedata
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from jpintel_mcp.api.response_sanitizer import sanitize_response_text
from jpintel_mcp.api.vocab import (
    _is_known_prefecture,
    _normalize_authority_level,
    _normalize_industry_jsic,
    _normalize_prefecture,
)
from jpintel_mcp.config import settings
from jpintel_mcp.db.session import connect, init_db
from jpintel_mcp.mcp.auth import (  # noqa: F401  # === DEVICE FLOW AUTH (RFC 8628) PATCH ===
    ensure_authenticated,
    get_stored_token,
    handle_quota_exceeded,
)
from jpintel_mcp.mcp._constants import PrefectureParam
from jpintel_mcp.mcp._http_fallback import (  # === S3 HTTP FALLBACK (uvx empty-DB fix) ===
    detect_fallback_mode,
    http_call,
    remote_only_error,
)
from jpintel_mcp.models import MINIMAL_FIELD_WHITELIST

# === DEVICE FLOW AUTH (RFC 8628) PATCH =================================
# jpintel_mcp.mcp.auth (imported above) exposes the keyring-backed
# credential store + the device-flow polling client. Tool wrappers that
# make HTTP calls should use get_stored_token() for the X-API-Key header
# and call handle_quota_exceeded() when the REST side returns 429.
# ensure_authenticated() is invoked in run() below — current tools read
# SQLite directly, so the interception is a no-op today but ready for
# the HTTP-client migration. See src/jpintel_mcp/mcp/auth.py.
# === END DEVICE FLOW AUTH PATCH ========================================

logger = logging.getLogger("jpintel.mcp")

try:
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("autonomath-mcp")
except Exception:  # pragma: no cover
    __version__ = "0.1.0"

mcp = FastMCP(
    name="autonomath",
    instructions=(
        "Japanese public-program data (日本の補助金 / 助成金 / 融資 / 税制優遇 / 認定制度). "
        "Primary-source URL + fetched_at on every row; no aggregators.\n\n"
        "Coverage:\n"
        "- 11,211 programs (国 + 47 都道府県 + 市区町村)\n"
        "- 2,286 採択事例 (real recipient profiles paired with programs received)\n"
        "- 108 融資 programs on 3-axis risk (担保 / 個人保証人 / 第三者保証人)\n"
        "- 1,185 会計検査院 enforcement_cases (不当請求 / 目的外使用 etc.)\n"
        "- 181 exclusion / prerequisite rules (125 exclude + 17 prerequisite + 15 absolute + 24 other) pre-extracted from 要綱 PDF footnotes\n\n"
        "Tier: S/A = primary-source verified; B = partially enriched; C = sparse; X = excluded.\n"
        "Use search_programs for program discovery, search_case_studies for adoption evidence, "
        "search_loan_programs for 無担保・無保証 filtering, search_enforcement_cases for compliance / "
        "due-diligence, check_exclusions for 併給可否 (can I combine A+B?).\n\n"
        "Before filtering on target_type / funding_purpose / program_kind / authority_level / "
        "prefecture / event_type / ministry / loan_type / provider / programs_used, "
        "call enum_values(field=…) to see the live "
        "canonical vocabulary — the DB mixes English slugs and Japanese labels, so guessing "
        "returns 0 rows."
    ),
)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
# FastMCP does not forward ``version`` to the underlying low-level Server, so
# the initialize response otherwise reports the MCP SDK's own package version
# (e.g. "1.27.0") as serverInfo.version. Set it explicitly on the inner server
# so clients see the autonomath-mcp release.
mcp._mcp_server.version = __version__


def _json_col(row: sqlite3.Row, col: str, default: Any) -> Any:
    raw = row[col]
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


_VALID_FIELDS = ("minimal", "default", "full")


_PREFECTURE_SUFFIX = ("都", "道", "府", "県")


def _looks_non_canonical_prefecture(value: str | None) -> bool:
    """True when a prefecture filter is almost certainly wrong-form.

    DB stores '東京都' / '北海道' / '全国'. 'Tokyo', '東京', 'TOKYO' are common
    caller mistakes. Don't false-positive on '全国' (national sentinel).
    """
    if value is None:
        return False
    if value == "全国":
        return False
    return not value.endswith(_PREFECTURE_SUFFIX)


def _empty_case_studies_hint(
    prefecture: str | None,
    industry_jsic: str | None,
    houjin_bangou: str | None,
    program_used: str | None,
) -> str:
    """Empty-hit hint for search_case_studies. Same priority as _empty_search_hint:
    non-canonical filter > missing-coverage > pivot."""
    if _looks_non_canonical_prefecture(prefecture):
        return (
            f"prefecture='{prefecture}' は canonical 形式ではありません. "
            "`enum_values(field='prefecture')` で 47 都道府県 + '全国' を確認してください."
        )
    if program_used:
        return (
            f"program_used='{program_used}' で 0 件. "
            "案件名は 35 種しか登録されておらず, 表記ブレで外れている可能性があります. "
            "`enum_values(field='programs_used')` で canonical 一覧を確認して再検索してください."
        )
    if houjin_bangou and not (houjin_bangou.isdigit() and len(houjin_bangou) == 13):
        return (
            f"houjin_bangou='{houjin_bangou}' は 13 桁数字ではありません. "
            "国税庁 法人番号公表サイトの 13 桁 (チェックディジット含む) を渡してください."
        )
    if industry_jsic and len(industry_jsic) > 2:
        return (
            f"industry_jsic='{industry_jsic}' は粒度が細かすぎる可能性があります. "
            "大分類 1 文字 ('A'=農林水産, 'E'=製造業, 'I'=卸売小売) に緩めて再検索してください."
        )
    return (
        "採択事例に該当なし. 事例は 2,286 件で業種/規模の粒度が粗い. "
        "別アプローチ: (a) search_programs で制度自体を調べる, (b) prefecture を外して全国で再検索, "
        "(c) industry_jsic を 2 桁 (大分類) に緩める."
    )


def _empty_enforcement_hint(
    prefecture: str | None,
    ministry: str | None,
    event_type: str | None,
    recipient_houjin_bangou: str | None,
) -> str:
    """Empty-hit hint for search_enforcement_cases."""
    if _looks_non_canonical_prefecture(prefecture):
        return (
            f"prefecture='{prefecture}' は canonical 形式ではありません. "
            "`enum_values(field='prefecture')` で確認してください."
        )
    if ministry:
        return (
            f"ministry='{ministry}' で 0 件. 表記ブレ ('厚労省' vs '厚生労働省') の可能性があります. "
            "`enum_values(field='ministry')` で canonical 省庁名 (8 種) を確認してください."
        )
    if event_type:
        return (
            f"event_type='{event_type}' で 0 件. "
            "`enum_values(field='event_type')` で canonical 値 ('clawback' / 'penalty' 等) を確認してください."
        )
    if recipient_houjin_bangou:
        # recipient_houjin_bangou column is 100 % NULL: 会計検査院 does not
        # publish 法人番号. Redirect the caller to q=<digits> instead, which
        # substring-matches reason_excerpt / source_title / program_name_hint.
        return (
            f"recipient_houjin_bangou='{recipient_houjin_bangou}' の専用カラムは 会計検査院 公表分 では 100% NULL のため必ず 0 件になります. "
            f"`q='{recipient_houjin_bangou}'` (13 桁 substring) もしくは `q='<法人名>'` で再試行してください — "
            "reason_excerpt / source_title / program_name_hint を横断 LIKE 検索します. "
            "それでも 0 件なら 『会計検査院 公表分では該当なし』 が正確な結論 (健全の断定ではなく公表分限定)."
        )
    return (
        "会計検査院 公表事例に該当なし. 他の切り口: (a) search_programs で当該補助金の現行制度を確認, "
        "(b) event_type を広げる (不当請求 / 目的外使用 / 重複受給 / 資格不備)."
    )


def _empty_loan_hint(
    provider: str | None,
    loan_type: str | None,
) -> str:
    """Empty-hit hint for search_loan_programs."""
    if provider:
        return (
            f"provider='{provider}' で 0 件. 'JFC' / '公庫' の略称はヒットしません "
            "(DB は '日本政策金融公庫 国民生活事業' のような正式名称で保存). "
            "`enum_values(field='provider')` で canonical 一覧を確認してください."
        )
    if loan_type:
        return (
            f"loan_type='{loan_type}' で 0 件. 日本語値 ('運転資金' 等) はヒットしません "
            "(DB は英語 slug: 'general', 'agri', 'safety_net' 等で保存). "
            "`enum_values(field='loan_type')` で 11 種の canonical slug を確認してください."
        )
    return (
        "融資プログラムに該当なし. 108 件と母集団が小さい. "
        "別アプローチ: (a) 担保/保証人 axis を 'negotiable' や None に緩める, "
        "(b) provider を外して全国 lender で再検索, (c) max_interest_rate や "
        "min_loan_period_years を一旦解除, (d) search_programs で補助金側も当たる."
    )


def _expansion_coverage_state(table: str, conn: sqlite3.Connection) -> dict[str, Any]:
    """Return a `data_state` snippet for expansion tables (laws / tax_rulesets /
    court_decisions / bids / invoice_registrants). Tells the caller whether the
    underlying table is loaded, partially loaded, or empty — so `total=0` can
    be disambiguated from 'our DB is empty for this dataset'.

    Called only on the empty-result path to keep normal search responses lean.
    """
    try:
        (row_count,) = conn.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()
    except sqlite3.Error:
        row_count = 0
    if row_count == 0:
        return {
            "data_state": "table_pending_load",
            "rows_loaded": 0,
            "note": (
                f"{table} はスキーマ構築済み・本格ロード post-launch です. "
                "現状では常に total=0 を返します."
            ),
        }
    return {"data_state": "partial", "rows_loaded": int(row_count)}


def _empty_laws_hint(
    q: str | None,
    ministry: str | None,
    law_type: str | None,
) -> str:
    """Empty-hit hint for search_laws."""
    if q and len(q.strip()) < 3:
        return (
            f"q='{q}' が短すぎて FTS にヒットしません. "
            "3 文字以上 (例: '消費税法', '建築基準法') で再検索してください."
        )
    if ministry:
        return (
            f"ministry='{ministry}' で 0 件. 表記ブレの可能性があります "
            "('財務省' vs '国税庁'). e-Gov の所管省庁名と完全一致させてください."
        )
    if law_type:
        return (
            f"law_type='{law_type}' で 0 件. canonical 値は '法律' / '政令' / '省令' / '規則' / '告示'."
        )
    return (
        "法令に該当なし. 略称 '下請法' は 下請代金支払遅延等防止法 のように正式名で保存されています. "
        "別アプローチ: (a) 正式名で再検索, (b) `search_tax_rules` で税制 ruleset を直接引く, "
        "(c) `get_am_tax_rule(measure_name_or_id=…)` で autonomath 側 (承継/相続/贈与 3 ルールあり) を試す."
    )


def _empty_tax_rules_hint(
    q: str | None,
    tax_category: str | None,
) -> str:
    """Empty-hit hint for search_tax_rules (coverage is インボイス/電帳法/中小企業 法人税/消費税 biased, 35 rows)."""
    if q and any(kw in q for kw in ("事業承継", "承継税制", "相続", "贈与", "組織再編", "合併", "分割")):
        return (
            f"q='{q}' は search_tax_rules の 35 行対象外 (インボイス/電帳法/中小企業 法人税・消費税 only). "
            "`get_am_tax_rule(measure_name_or_id='事業承継税制')` または `search_tax_incentives(query='…')` に切り替えてください — "
            "autonomath 側に 承継/相続/贈与/組織再編 のルールがあります."
        )
    if tax_category == "inheritance" or tax_category == "gift":
        return (
            f"tax_category='{tax_category}' は search_tax_rules 未収録. "
            "`get_am_tax_rule(measure_name_or_id=…)` で相続・贈与関連を確認してください."
        )
    if q and len(q.strip()) < 3:
        return (
            f"q='{q}' が短すぎます. 3 文字以上の語で再検索してください."
        )
    return (
        "税務 ruleset に該当なし. 現状 35 行 (インボイス/電帳法/中小企業 法人税・消費税). "
        "別アプローチ: (a) `search_tax_incentives` で autonomath tax_measure (>100 種) を横断検索, "
        "(b) `get_am_tax_rule(measure_name_or_id=…)` で具体的ルール名 (事業承継税制, 研究開発税制 等) を取得."
    )


def _empty_court_decisions_hint(q: str | None) -> str:
    """Empty-hit hint for search_court_decisions (table currently empty per CLAUDE.md).

    Note: this hint points the caller at `find_precedents_by_statute` as an
    alternate call path. Do NOT reuse this helper inside
    `find_precedents_by_statute` itself — that tool should point elsewhere
    (search_enforcement_cases / find_cases_by_law) to avoid recommending
    itself. See `_empty_precedents_hint` below.
    """
    return (
        "判例データは本格ロード post-launch です (schema ready, 0 rows). "
        "別アプローチ: (a) `search_laws` で根拠法令を特定, (b) `find_precedents_by_statute` "
        "で法令側から判例を統計的に逆引き (こちらも現状 0 件返しますが, "
        "ロード後は同じ call path で埋まります)."
    )


def _empty_precedents_hint(article_citation: str | None) -> str:
    """Empty-hit hint for find_precedents_by_statute.

    Distinct from `_empty_court_decisions_hint` because that helper recommends
    calling find_precedents_by_statute itself (useless as a retry when
    find_precedents_by_statute is the empty tool). Here we point the caller
    at alternative 法令→事象 paths that do have data.
    """
    prefix = (
        f"article_citation='{article_citation}' に該当する 判例 は現 DB 0 件です. "
        if article_citation else ""
    )
    return (
        f"{prefix}"
        "判例 テーブル本体が post-launch ロード中 (schema ready, 0 rows). "
        "別アプローチ: (a) `find_cases_by_law(law_unified_id, include_enforcement=True)` "
        "で 会計検査院 不当事例 を同じ法令から引く (enforcement_cases には 1,185 行あり), "
        "(b) `search_enforcement_cases(q=…)` で自由語での行政処分事例, "
        "(c) 裁判所 RSS / 判例検索システム (courts.go.jp) で直接検索."
    )


def _empty_bids_hint(q: str | None) -> str:
    """Empty-hit hint for search_bids (table currently empty per CLAUDE.md)."""
    return (
        "入札データは本格ロード post-launch です (schema ready, 0 rows — GEPS/自治体 bulk 準備中). "
        "別アプローチ: (a) `search_programs` で補助金側の交付先を調べる, "
        "(b) `search_case_studies` で採択事例から発注者関係を逆引き."
    )


def _empty_invoice_registrants_hint(
    q: str | None,
    houjin_bangou: str | None,
) -> str:
    """Empty-hit hint for search_invoice_registrants (13,801 rows delta-only, pre-2025 absent)."""
    if houjin_bangou and not (houjin_bangou.isdigit() and len(houjin_bangou) == 13):
        return (
            f"houjin_bangou='{houjin_bangou}' は 13 桁数字ではありません. "
            "国税庁 公表 T 番号から先頭 'T' を除いた 13 桁を渡してください."
        )
    return (
        "適格請求書発行事業者に該当なし. **重要**: 現 DB は 2025-10 以降 delta のみ 13,801 行 "
        "(full 400 万行 monthly bulk は post-launch)。pre-2025 登録者は本 DB 外にあり, "
        "'登録していない' ではなく '本 DB mirror 対象外' の可能性が高い. "
        "国税庁 適格事業者公表サイトで直接確認してください."
    )


def _empty_search_hint(
    q: str | None,
    prefecture: str | None,
    tier: list[str] | None,
    authority_level: str | None,
    target_type: list[str] | None = None,
    funding_purpose: list[str] | None = None,
) -> str:
    """Explain *why* search returned 0 rows so the agent retries smartly.

    Models retry 4x more often when a hint is present vs a bare empty
    array. Picks the most plausible cause and proposes one concrete
    alternative — we don't list every tool, that's what `retry_with`
    is for.

    Priority: non-canonical filter values > missing-coverage > pivot.
    A wrong filter is always worth fixing before pivoting, because
    pivoting hides the cause.
    """
    if q and len(q.strip()) < 3:
        return (
            f"クエリ '{q}' が短すぎて FTS にヒットしません. "
            "3 文字以上の語 (例: '補助金' '省エネ') を含めて再検索してください."
        )
    if prefecture and prefecture != "全国" and not prefecture.endswith(_PREFECTURE_SUFFIX):
        return (
            f"prefecture='{prefecture}' は canonical 形式ではありません "
            "(DB は '東京都' のようにフル都道府県名で保存). "
            "`enum_values(field='prefecture')` で 47 都道府県 + '全国' を確認して再検索してください."
        )
    if target_type:
        return (
            f"target_type={target_type} で 0 件. 表記ブレの可能性があります "
            "('中小企業'/'sme', '個人事業主'/'sole_proprietor' が混在). "
            "`enum_values(field='target_type')` で canonical 一覧を取得し, "
            "見つかった値をそのまま渡してください."
        )
    if funding_purpose:
        return (
            f"funding_purpose={funding_purpose} で 0 件. 表記ブレ ('DX'/'デジタル化', "
            "'省エネ'/'energy') の可能性があります. "
            "`enum_values(field='funding_purpose')` で canonical 一覧を確認してください."
        )
    if tier and all(t in {"S", "A"} for t in tier):
        return (
            "tier=['S','A'] のみで絞ったため該当なし. "
            "tier=['S','A','B','C'] に拡張すると件数が戻ります (C は要1次確認)."
        )
    if prefecture:
        return (
            f"prefecture='{prefecture}' 限定で 0 件. "
            "国 (national) 制度は prefecture=null で保存されているため, "
            "prefecture を外して authority_level='national' で再検索してください."
        )
    if authority_level == "national":
        return (
            "authority_level='national' で 0 件. 地方自治体制度を含めるなら "
            "authority_level を外すか, prefecture を指定してください."
        )
    return (
        "該当なし. 別の切り口として: (a) search_case_studies で実際の受給事例から逆引き, "
        "(b) search_loan_programs で融資, (c) search_enforcement_cases で不当請求 due-diligence. "
        "クエリを英日両方 ('DX'/'デジタル化') で試すのも有効."
    )


def _row_to_dict(row: sqlite3.Row, include_enriched: bool = False) -> dict[str, Any]:
    # Lineage columns were added by migration 001; they may be absent on
    # very old DB files where the migration has not yet been applied.
    row_keys = row.keys()
    source_url = row["source_url"] if "source_url" in row_keys else None
    source_fetched_at = (
        row["source_fetched_at"] if "source_fetched_at" in row_keys else None
    )
    source_checksum = (
        row["source_checksum"] if "source_checksum" in row_keys else None
    )

    application_window = _json_col(row, "application_window_json", None)
    official_url = row["official_url"]

    # Parity with REST: actionable-row fields exposed on every row. The past-
    # date filter for next_deadline and enriched parse for required_documents
    # live in api.programs; import here to keep the single canonical impl.
    from jpintel_mcp.api.programs import (
        _extract_next_deadline,
        _extract_required_documents,
        _post_cache_next_deadline,
    )

    base = {
        "unified_id": row["unified_id"],
        "primary_name": row["primary_name"],
        "aliases": _json_col(row, "aliases_json", []),
        "authority_level": row["authority_level"],
        "authority_name": row["authority_name"],
        "prefecture": row["prefecture"],
        "municipality": row["municipality"],
        "program_kind": row["program_kind"],
        "official_url": official_url,
        "amount_max_man_yen": row["amount_max_man_yen"],
        "amount_min_man_yen": row["amount_min_man_yen"],
        "subsidy_rate": row["subsidy_rate"],
        "trust_level": row["trust_level"],
        "tier": row["tier"],
        "coverage_score": row["coverage_score"],
        "gap_to_tier_s": _json_col(row, "gap_to_tier_s_json", []),
        "a_to_j_coverage": _json_col(row, "a_to_j_coverage_json", {}),
        "excluded": bool(row["excluded"]),
        "exclusion_reason": row["exclusion_reason"],
        "crop_categories": _json_col(row, "crop_categories_json", []),
        "equipment_category": row["equipment_category"],
        "target_types": _json_col(row, "target_types_json", []),
        "funding_purpose": _json_col(row, "funding_purpose_json", []),
        "amount_band": row["amount_band"],
        "application_window": application_window,
        "next_deadline": _post_cache_next_deadline(
            _extract_next_deadline(application_window)
        ),
        "application_url": official_url,
        "source_url": source_url,
        "source_fetched_at": source_fetched_at,
        "source_checksum": source_checksum,
    }
    if include_enriched:
        enriched = _json_col(row, "enriched_json", None)
        base["enriched"] = enriched
        base["source_mentions"] = _json_col(row, "source_mentions_json", [])
        base["required_documents"] = _extract_required_documents(enriched)
    return base


def _resolve_fields(fields: str | None) -> Literal["minimal", "default", "full"]:
    """Validate a tool-supplied `fields` value.

    MCP tool schemas come from the function signature; a plain `str` is the
    safe wire type (not every MCP client speaks Python `Literal`). Validate
    here so an invalid value fails loud instead of silently passing through.
    """
    if fields is None:
        return "default"
    if fields not in _VALID_FIELDS:
        raise ValueError(
            f"fields must be one of {_VALID_FIELDS}, got {fields!r}"
        )
    return fields  # type: ignore[return-value]  # validated against _VALID_FIELDS above


def _trim_to_fields(record: dict[str, Any], fields: str) -> dict[str, Any]:
    """Shape a program dict to the requested fields level. Mirrors the REST
    helper in api/programs.py; see that file for the rationale.
    """
    if fields == "minimal":
        return {k: record.get(k) for k in MINIMAL_FIELD_WHITELIST}
    if fields == "full":
        record.setdefault("enriched", None)
        record.setdefault("source_mentions", None)
        record.setdefault("source_url", None)
        record.setdefault("source_fetched_at", None)
        record.setdefault("source_checksum", None)
        return record
    return record  # default


# Token-shaping helpers for case_studies + enforcement_cases (dd_v3_09 / v7 P3-K).
# Each tool's row→dict already returns a "full" shape; these trim down to
# minimal/standard for list rendering. Default = minimal so unannotated callers
# get the smallest payload (~80 B/row vs ~600 B/row full). See task brief.

_CASE_STUDY_MINIMAL_KEYS: tuple[str, ...] = (
    "case_id", "company_name", "case_title", "source_url",
)
_CASE_STUDY_STANDARD_EXTRA: tuple[str, ...] = (
    "prefecture", "industry_jsic", "industry_name", "publication_date",
    "total_subsidy_received_yen", "fetched_at",
)


def _trim_case_study_fields(record: dict[str, Any], fields: str) -> dict[str, Any]:
    if fields == "minimal":
        return {k: record.get(k) for k in _CASE_STUDY_MINIMAL_KEYS}
    if fields == "standard":
        keys = _CASE_STUDY_MINIMAL_KEYS + _CASE_STUDY_STANDARD_EXTRA
        return {k: record.get(k) for k in keys}
    return record  # full = existing complete shape


_ENFORCEMENT_MINIMAL_KEYS: tuple[str, ...] = (
    "case_id", "program_name_hint", "event_type", "source_url",
)
_ENFORCEMENT_STANDARD_EXTRA: tuple[str, ...] = (
    "ministry", "prefecture", "disclosed_date",
    "amount_improper_grant_yen", "recipient_name", "fetched_at",
)


def _trim_enforcement_fields(record: dict[str, Any], fields: str) -> dict[str, Any]:
    if fields == "minimal":
        return {k: record.get(k) for k in _ENFORCEMENT_MINIMAL_KEYS}
    if fields == "standard":
        keys = _ENFORCEMENT_MINIMAL_KEYS + _ENFORCEMENT_STANDARD_EXTRA
        return {k: record.get(k) for k in keys}
    return record  # full = existing complete shape


_SHAPED_FIELDS = ("minimal", "standard", "full")


def _resolve_shaped_fields(fields: str | None) -> Literal["minimal", "standard", "full"]:
    """Validate the (minimal/standard/full) variant used by case_studies +
    enforcement_cases + autonomath search tools. Distinct from
    `_resolve_fields` which uses the legacy (minimal/default/full) triple
    for `search_programs` / `get_program` / `batch_get_programs`.
    """
    if fields is None:
        return "minimal"
    if fields not in _SHAPED_FIELDS:
        raise ValueError(
            f"fields must be one of {_SHAPED_FIELDS}, got {fields!r}"
        )
    return fields  # type: ignore[return-value]


def _enforce_limit_cap(
    limit: int, cap: int = 20
) -> tuple[int, list[dict[str, Any]]]:
    """Cap `limit` at `cap` and emit an input_warnings entry if the caller
    asked for more. dd_v3_09 / v7 P3-K: list tools cap at 20 rows so a
    single call cannot blow the response budget.
    """
    warnings: list[dict[str, Any]] = []
    if limit > cap:
        warnings.append({
            "field": "limit",
            "code": "limit_capped",
            "value": limit,
            "normalized_to": cap,
            "message": (
                f"limit={limit} は token-shaping cap ({cap}) を超過。"
                f"{cap} に丸めました。さらに必要なら offset を進めて再呼び出ししてください。"
            ),
        })
        limit = cap
    return limit, warnings


# ── MCP query telemetry ────────────────────────────────────────────────────
# Mirrors the REST middleware but as a per-tool wrapper. Centralised here so
# the logging logic is not repeated 31 times.

_mcp_query_log = logging.getLogger("autonomath.query")


def _mcp_detect_lang(text: str) -> str:
    """Return 'ja', 'en', or 'mixed' based on CJK character ratio."""
    if not text:
        return "en"
    cjk = sum(
        1
        for ch in text
        if unicodedata.category(ch) in ("Lo",) and "⺀" <= ch <= "鿿"
    )
    ratio = cjk / len(text)
    if ratio > 0.5:
        return "ja"
    if ratio > 0.1:
        return "mixed"
    return "en"


def _mcp_params_shape(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return {key: True} for every non-None kwarg (no values logged)."""
    shape: dict[str, Any] = {k: True for k, v in kwargs.items() if v is not None}
    q = kwargs.get("q")
    if isinstance(q, str) and q:
        shape["q_len"] = len(q)
        shape["q_lang"] = _mcp_detect_lang(q)
    return shape


def _emit_mcp_log(
    *,
    tool_name: str,
    params_shape: dict[str, Any],
    result_count: int,
    latency_ms: int,
    status: int | str,
    error_class: str | None,
) -> None:
    try:
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "channel": "mcp",
            "endpoint": tool_name,
            "params_shape": params_shape,
            "result_count": result_count,
            "latency_ms": latency_ms,
            "status": status,
            "error_class": error_class,
        }
        _mcp_query_log.info(json.dumps(record, ensure_ascii=False))
    except Exception:
        pass


def _count_results(result: Any) -> int:
    """Best-effort result count: checks 'results' list or top-level list."""
    if isinstance(result, dict):
        inner = result.get("results")
        if isinstance(inner, list):
            return len(inner)
        return 1
    if isinstance(result, list):
        return len(result)
    return 0 if result is None else 1


# --------------------------------------------------------------------------- #
# === S3 HTTP FALLBACK (uvx empty-DB fix) ====================================
# When ``uvx autonomath-mcp`` ships the wheel without ``data/`` (excluded in
# pyproject.toml), the local ``data/jpintel.db`` is empty and every tool
# returns 0 rows. ``_fallback_call()`` checks the cached fallback flag and,
# if active, routes the request to ``api.autonomath.ai`` via the helper in
# ``jpintel_mcp.mcp._http_fallback``. Returns ``None`` when the local DB is
# fine, so the call site continues with the existing SQL path. Tools that
# don't have a REST equivalent (dd_profile_am / rule_engine_check) get a
# structured ``remote_only_via_REST_API`` envelope via remote_only_error().
# Memory contract: ¥3/req metering applies on the REST side, anonymous
# 50/月 is enforced by IP, no Anthropic API call here.
# --------------------------------------------------------------------------- #


def _fallback_call(
    tool_name: str,
    *,
    rest_path: str | None,
    params: dict[str, Any] | None = None,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return remote response when in fallback mode, else None.

    ``rest_path`` of ``None`` indicates a tool with no REST equivalent —
    surface ``remote_only_via_REST_API`` so the caller learns what to do.
    Param-value cleaning: drop ``None`` keys (httpx encodes None as the
    string "None" otherwise).
    """
    if not detect_fallback_mode():
        return None
    if rest_path is None:
        return remote_only_error(tool_name)
    clean_params: dict[str, Any] | None = None
    if params:
        clean_params = {k: v for k, v in params.items() if v is not None}
    return http_call(
        rest_path,
        method=method,
        params=clean_params,
        json_body=json_body,
    )


# === END S3 HTTP FALLBACK ===================================================


def _walk_and_sanitize_mcp(node: Any) -> tuple[Any, list[str]]:
    """Recursive str-leaf sanitizer for MCP envelope dicts.

    Mirrors :func:`jpintel_mcp.api.response_sanitizer._walk_and_sanitize`
    but kept inline so the MCP server has no hidden dep on api/* loading
    order. Returns ``(clean_node, hits)`` where ``hits`` is the flat list
    of pattern ids triggered anywhere in the tree.
    """
    hits: list[str] = []
    if isinstance(node, str):
        clean, h = sanitize_response_text(node)
        hits.extend(h)
        return clean, hits
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            c, h = _walk_and_sanitize_mcp(v)
            out[k] = c
            hits.extend(h)
        return out, hits
    if isinstance(node, list):
        out_l: list[Any] = []
        for v in node:
            c, h = _walk_and_sanitize_mcp(v)
            out_l.append(c)
            hits.extend(h)
        return out_l, hits
    return node, hits


def _envelope_merge(
    *,
    tool_name: str,
    result: Any,
    kwargs: dict[str, Any],
    latency_ms: float,
) -> Any:
    """Additively merge response-envelope v2 hint fields onto a tool result.

    Problem this fixes
    ------------------
    The 4-way envelope (status / explanation / suggested_actions /
    meta.suggestions / meta.alternative_intents / meta.tips) was wired
    into ``envelope_wrapper.with_envelope`` but no caller ever imported
    it (J9 / K3 dead-code finding). Customer LLMs receiving 0 results
    therefore had no structured hint about why — they could only parse
    the free-text ``hint`` string. This helper fixes that gap by running
    the canonical ``build_envelope`` call inside the telemetry wrapper.

    Posture
    -------
    * **Additive** — never overwrites an existing key on ``result``.
      Tools that already publish ``meta.data_as_of`` / ``retrieval_note``
      keep those verbatim; envelope-only keys land alongside.
    * **Opt-out** — callers passing ``fields="minimal"`` (anywhere in
      kwargs) get no ``meta`` block, matching the B-A8 spec.
    * **Error-aware** — if the tool already returned an error envelope
      ({error: {code, message, ...}}) we still merge ``status="error"``
      and ``suggested_actions=[retry_with_backoff]`` so the LLM has a
      consistent recovery path.
    * **No upstream change** — ``envelope_wrapper`` itself is untouched
      (B-A8 frozen). We import its public ``build_envelope`` and slot it
      in here.

    Returns the merged dict (or, for non-dict tool results, the bare
    envelope so the client always gets a structured shape).
    """
    # Soft import — keep server.py importable even if the autonomath
    # package is hard-disabled (settings.autonomath_enabled=False breaks
    # the package import chain in some test fixtures).
    try:
        from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import (
            _coerce_results,
            build_envelope,
        )
    except Exception:
        return result

    # Detect envelope opt-out. The B-A8 spec uses an internal
    # `__envelope_fields__` kwarg as the control-plane signal — tool-
    # level `fields="minimal"` means "minimal row shape" (whitelist
    # trim) and is unrelated to the envelope's meta block. Mixing them
    # would silently strip meta.suggestions for every default
    # search_programs call, defeating the whole β1 wiring.
    envelope_fields = kwargs.get("__envelope_fields__")
    fields = "minimal" if envelope_fields == "minimal" else "standard"

    # S7 disclaimer level — read once from settings. Soft import so the
    # envelope path stays usable in tests that monkey-patch settings or
    # in environments where pydantic_settings cannot resolve env vars.
    try:
        from jpintel_mcp.config import settings as _s
        disclaimer_level = str(getattr(_s, "autonomath_disclaimer_level", "standard"))
    except Exception:
        disclaimer_level = "standard"

    # Pick the most query-like kwarg for query_echo + router input.
    query_echo = ""
    for q_key in ("q", "query", "law_name", "program_name", "enum_name",
                  "natural_query", "name_query", "target_name"):
        v = kwargs.get(q_key)
        if isinstance(v, str) and v:
            query_echo = v
            break

    # Detect error envelope shape from tools that pre-built one.
    err_obj: dict[str, Any] | None = None
    if isinstance(result, dict):
        err = result.get("error")
        if isinstance(err, dict) and ("code" in err or "message" in err):
            err_obj = err

    try:
        if err_obj is not None:
            envelope = build_envelope(
                tool_name=tool_name,
                results=[],
                query_echo=query_echo,
                latency_ms=latency_ms,
                error=err_obj,
                router_query=query_echo,
                tool_kwargs=dict(kwargs),
                fields=fields,
                disclaimer_level=disclaimer_level,
            )
        else:
            results_list, extras = _coerce_results(result)
            envelope = build_envelope(
                tool_name=tool_name,
                results=results_list,
                query_echo=query_echo,
                latency_ms=latency_ms,
                legacy_extras=extras,
                router_query=query_echo,
                tool_kwargs=dict(kwargs),
                fields=fields,
                disclaimer_level=disclaimer_level,
            )
    except Exception:
        # Never let envelope synthesis break a working tool.
        return result

    # Pure-list / pure-record result: return the envelope as-is so the
    # client gets a structured shape. (Bare list response is uncommon
    # for our @mcp.tool functions but is handled defensively.)
    if not isinstance(result, dict):
        return envelope

    # Dict result: additive merge — original keys win on every key
    # collision. The new envelope-only keys we want to surface for
    # AI-agent consumers are appended; the tool's existing fields
    # (e.g. retrieval_note, meta.data_as_of, hint, retry_with) are
    # preserved verbatim.
    merged: dict[str, Any] = dict(result)
    additive_keys = (
        "status",
        "result_count",
        "explanation",
        "suggested_actions",
        "api_version",
        "tool_name",
        "query_echo",
        "latency_ms",
        "evidence_source_count",
        # S7 disclaimer surface — additive so a tool that already authored
        # its own `_disclaimer` (e.g. rule_engine_check) keeps its longer
        # custom string verbatim.
        "_disclaimer",
    )
    for k in additive_keys:
        if k in envelope and k not in merged:
            merged[k] = envelope[k]
    # Merge meta: existing tool-level meta (data_as_of / etc.) wins,
    # envelope-only keys (suggestions / alternative_intents / tips /
    # token_estimate / wall_time_ms / input_warnings) are added.
    env_meta = envelope.get("meta")
    if isinstance(env_meta, dict):
        existing_meta = merged.get("meta")
        if isinstance(existing_meta, dict):
            new_meta = dict(existing_meta)
            for k, v in env_meta.items():
                if k not in new_meta:
                    new_meta[k] = v
            merged["meta"] = new_meta
        else:
            merged["meta"] = dict(env_meta)

    # INV-22 (景表法) sanitization for MCP stdio path. REST has its own
    # ResponseSanitizerMiddleware (api/main.py); MCP bypasses HTTP entirely
    # so we must apply the same regex here. The ``_sanitized`` sentinel
    # prevents a double-pass if an upstream caller (e.g. REST wrapping an
    # MCP tool) already sanitized.
    if not merged.get("_sanitized"):
        sanitized_node, hits = _walk_and_sanitize_mcp(merged)
        if hits:
            sanitized_node["_sanitized"] = 1
            sanitized_node["_sanitize_hits"] = sorted(set(hits))
            logger.warning(
                "mcp_response_sanitized tool=%s hits=%s",
                tool_name,
                ",".join(sorted(set(hits))),
            )
            return sanitized_node
    return merged


def _with_mcp_telemetry(fn: Any) -> Any:
    """Decorator: wrap an MCP tool function with query telemetry logging.

    Apply with ``@_with_mcp_telemetry`` BELOW ``@mcp.tool`` so FastMCP sees
    the original signature for schema generation, and the wrapper is called
    at invocation time.

    Usage::

        @mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
        @_with_mcp_telemetry
        def search_programs(q: ..., ...) -> ...:
            ...

    Side-effects beyond logging:
      * Response-envelope v2 hint fields are additively merged onto the
        tool result via :func:`_envelope_merge`. This wires the
        ``envelope_wrapper.build_envelope`` machinery (status /
        suggested_actions / meta.suggestions / meta.alternative_intents
        / meta.tips) onto every ``@mcp.tool`` call without modifying the
        per-tool function bodies. See _envelope_merge docstring for the
        merge posture (additive only — never overrides existing keys).

    Zero-result returns still log at INFO — no WARNING noise.
    """
    tool_name = fn.__name__

    @functools.wraps(fn)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        t0 = time.monotonic()
        error_class: str | None = None
        status: int | str = 200
        result: Any = None
        all_kwargs: dict[str, Any] | None = None
        # Control-plane kwargs that the envelope layer reads but the
        # underlying tool MUST NOT see. Popped here so the inner call
        # stays signature-compatible with all 38+33 wrapped tools.
        envelope_fields = kwargs.pop("__envelope_fields__", None)
        api_key_created_at = kwargs.pop("__api_key_created_at__", None)
        try:
            result = fn(*args, **kwargs)
            # Build bound kwargs once — used by both telemetry shape
            # extraction and envelope input_warnings derivation. The
            # control-plane args are added back in for envelope use.
            try:
                sig = inspect.signature(fn)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                all_kwargs = dict(bound.arguments)
            except Exception:
                all_kwargs = dict(kwargs)
            envelope_kwargs = dict(all_kwargs)
            if envelope_fields is not None:
                envelope_kwargs["__envelope_fields__"] = envelope_fields
            if api_key_created_at is not None:
                envelope_kwargs["__api_key_created_at__"] = api_key_created_at
            latency_ms_float = (time.monotonic() - t0) * 1000.0
            result = _envelope_merge(
                tool_name=tool_name,
                result=result,
                kwargs=envelope_kwargs,
                latency_ms=latency_ms_float,
            )
            return result
        except Exception as exc:
            error_class = type(exc).__name__
            status = "error"
            raise
        finally:
            latency_ms = int((time.monotonic() - t0) * 1000)
            if all_kwargs is None:
                try:
                    sig = inspect.signature(fn)
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    all_kwargs = dict(bound.arguments)
                except Exception:
                    all_kwargs = dict(kwargs)
            _emit_mcp_log(
                tool_name=tool_name,
                params_shape=_mcp_params_shape(all_kwargs),
                result_count=_count_results(result),
                latency_ms=latency_ms,
                status=status,
                error_class=error_class,
            )

    return _wrapper


# ── End MCP telemetry ──────────────────────────────────────────────────────


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def search_programs(
    q: Annotated[
        str | None,
        Field(
            description=(
                "Free-text query (Japanese or English). FTS5 trigram for 3+ "
                "chars (recommended); 1-2 chars fall back to LIKE substring. "
                "Example: '設備投資' / 'IT導入' / 'greenhouse'."
            ),
        ),
    ] = None,
    tier: Annotated[
        list[Literal["S", "A", "B", "C", "X"]] | None,
        Field(
            description=(
                "Quality-tier filter (multi-select, OR). S/A = primary-source "
                "verified (8+/10 dims). B = partial (4-7/10). C = name+URL "
                "only (1-3/10). X = excluded/deprecated (omit unless "
                "include_excluded=true). Typical agent default: ['S','A','B']."
            ),
        ),
    ] = None,
    prefecture: Annotated[
        PrefectureParam,
        Field(
            description=(
                "都道府県 closed-set ('東京都' / '北海道' / '全国' 等 48 値). "
                "短縮形 ('東京') / romaji ('Tokyo') は自動正規化。"
                "未知値は invalid_enum で拒否 — typo silently filter は防止。"
                "国制度 (prefecture=null on row) を含めるには未指定 or '全国'。"
            ),
        ),
    ] = None,
    authority_level: Annotated[
        Literal["national", "prefecture", "municipality", "financial"] | None,
        Field(
            description=(
                "Administrative level. 'national' = 国 (省庁); 'prefecture' = "
                "都道府県; 'municipality' = 市区町村; 'financial' = 政策金融公庫等."
            ),
        ),
    ] = None,
    funding_purpose: Annotated[
        list[str] | None,
        Field(
            description=(
                "Funding purpose tags (AND — all must match). Common values: "
                "'設備投資', '運転資金', '研究開発', '雇用', '省エネ', 'DX'."
            ),
        ),
    ] = None,
    target_type: Annotated[
        list[str] | None,
        Field(
            description=(
                "Target applicant type (AND). Common values: '中小企業', "
                "'小規模事業者', '個人事業主', '認定新規就農者', 'NPO法人'."
            ),
        ),
    ] = None,
    amount_min_man_yen: Annotated[
        float | None,
        Field(ge=0, description="Lower bound on amount_max_man_yen (万円). Must be >= 0."),
    ] = None,
    amount_max_man_yen: Annotated[
        float | None,
        Field(ge=0, description="Upper bound on amount_max_man_yen (万円). Must be >= 0."),
    ] = None,
    include_excluded: Annotated[
        bool,
        Field(
            description=(
                "Include tier=X excluded/deprecated programs. Default false."
            ),
        ),
    ] = False,
    limit: Annotated[
        int,
        Field(
            description=(
                "Max rows returned. Token-shaping cap = 20 (dd_v3_09 / v7 "
                "P3-K); values above 20 are silently capped with "
                "input_warnings. Default 20."
            ),
            ge=1,
            le=100,
        ),
    ] = 20,
    offset: Annotated[
        int,
        Field(description="Pagination offset (0-based). Default 0.", ge=0),
    ] = 0,
    fields: Annotated[
        Literal["minimal", "default", "full"],
        Field(
            description=(
                "Response shape per row. 'minimal' (default, ~300 B/row, "
                "list rendering — 7-key whitelist). 'default' = full "
                "Program shape. 'full' = +enriched A-J + source_mentions + "
                "lineage. Default switched to 'minimal' under dd_v3_09 / "
                "v7 P3-K token shaping; pass fields='default' or 'full' "
                "when callers need the wider shape."
            ),
        ),
    ] = "minimal",
    as_of: Annotated[
        str,
        Field(
            description=(
                "Effective-date filter (ISO YYYY-MM-DD or 'today'). "
                "Default 'today' (JST). Drops rows whose "
                "application_window.end_date has already passed; rows "
                "without a structured end_date are kept (通年 / 随時 / "
                "absence of date). Pass an ISO date for historical "
                "queries (`as_of='2024-01-01'`). Echoed in "
                "meta.data_as_of."
            ),
            pattern=r"^(today|\d{4}-\d{2}-\d{2})$",
        ),
    ] = "today",
) -> dict[str, Any]:
    """DISCOVER: Search 11,547 Japanese public programs (subsidies/loans/tax incentives/certifications) with Tier-graded data quality.

    補助金・助成金・融資・税制優遇・認定制度を横断検索する (国 + 47 都道府県 + 市区町村). Returns program **definitions** (policy text, not recipients) with tier-graded quality labels and primary-source URL + fetched_at on every row — no aggregator sources. Jグランツ 公開 API does not support this cross-ministry / cross-prefecture discovery with quality ranking; this is the canonical entrypoint for "what 補助金 can X use?" questions.

    Use this for program **definitions** (eligibility, amount, window, authority).
    To find **real recipients** of a program ("businesses like mine actually
    received this"), use `search_case_studies` instead — that returns applicant
    profiles, not policy text.

    Typical queries:
      - "この事業に使える補助金は?" / "What subsidies does X business qualify for?"
      - "東京都の小規模事業者向け、上限 300 万円以下の補助金は?"
      - "設備投資に使える税制優遇・税額控除は?"
      - "農林水産省管轄で 認定新規就農者向けの助成金を一覧"

    Filters combine freely (AND across dimensions, OR within each list). Japanese
    free-text search works for 3+ char queries via FTS5 trigram; shorter queries
    fall back to LIKE substring.

    Tier ranking (best→worst): S, A, B, C, X. S/A are verified by primary-source
    URL + evidence on 8+/10 A-J dimensions; B is partial (4-7 dims); C is sparse
    (1-3 dims, name+URL only); X is excluded/deprecated. When presenting to an
    end user, default to tier ∈ {S, A, B} and mark C as "要 1 次確認".

    `fields` controls response size per row (see param description).

    WHEN NOT:
      - `search_enforcement_cases` instead if the user asks about 不正受給 / 返還命令 / 会計検査院.
      - `search_case_studies` instead if they ask which *recipients* got the program ("農事法人 E で使えた補助金", "北海道の食品製造で採択例").
      - `search_loan_programs` instead for 融資 filtered by 担保・保証人 axes; search_programs does surface 融資 rows but cannot filter on the 3-axis risk.
      - `enum_values(field=…)` *first* if unsure whether a target_type / funding_purpose / authority_level / prefecture value is canonical — the DB mixes "sole_proprietor" / "個人事業主", "省エネ" / "energy" etc. Prefecture uses the full suffix ("東京都", not "東京" or "Tokyo").

    LIMITATIONS:
      - Tier X is a **quarantine tier** (deprecated / untrustworthy rows) and is excluded by default (`include_excluded=False`). Do not flip `include_excluded=True` to surface more results — the X-tier rows intentionally lack a verified primary source.
      - `source_fetched_at` is a **uniform sentinel** across bulk-rewritten rows (<100 distinct values for thousands of programs). Render as "出典取得日" (when we last fetched), never as "最終更新日" or "現行確認日" — the column does not imply we verified currency.
      - FTS5 trigram tokenizer causes false positives on single-kanji overlap. Searching `税額控除` also matches `ふるさと納税` because both contain `税`. For 2+ character kanji compounds, wrap the query in quotes (`"税額控除"`) to force phrase matching.
      - `application_window` coverage is partial; many rows store 通年 / 随時 / empty — absence of a date does not mean closed. Fall back to the source URL for 募集期間 when the field is null.
      - `amount_max_man_yen` is a 万円 unit (not 円). Filtering `amount_max_man_yen <= 300` matches programs with cap ≤ 300万円, not ≤ 300円.
      - `as_of` (default 'today' JST) drops rows whose `application_window.end_date` is strictly past relative to the pivot. Rows lacking a structured end_date (通年 / 随時 / null) are always kept — absence of a deadline is not closure. Pass `as_of='YYYY-MM-DD'` for historical "what was active at X" queries; `meta.data_as_of` echoes the resolved date.

    CHAIN:
      → `get_program(unified_id=…)` for single-record detail.
      → `batch_get_programs(unified_ids=[…])` when the user wants full shape for 2-50 rows at once.
      → `check_exclusions(program_ids=[…])` to verify A+B 併給可否.
      → `search_case_studies(program_used=primary_name)` to attach recipient evidence (the field does a substring match; today's data stores names, not unified_ids).
    """
    # === S3 HTTP FALLBACK ===
    _fb = _fallback_call(
        "search_programs",
        rest_path="/v1/programs/search",
        params={
            "q": q,
            "tier": tier,
            "prefecture": prefecture,
            "authority_level": authority_level,
            "funding_purpose": funding_purpose,
            "target_type": target_type,
            "amount_min_man_yen": amount_min_man_yen,
            "amount_max_man_yen": amount_max_man_yen,
            "include_excluded": include_excluded,
            "limit": limit,
            "offset": offset,
            "fields": fields,
            "as_of": as_of,
        },
    )
    if _fb is not None:
        return _fb
    # === END S3 HTTP FALLBACK ===
    fields = _resolve_fields(fields)
    limit = max(1, min(100, limit))
    limit, limit_warnings = _enforce_limit_cap(limit, cap=20)
    offset = max(0, offset)

    # Resolve as_of → ISO date. 'today' or empty → JST today; otherwise
    # validate YYYY-MM-DD shape (also enforced by Field pattern).
    as_of_iso = _jst_today_iso() if (not as_of or as_of == "today") else as_of

    # D1: reject negative amount bounds — silent 0-results on amount_max=-1 is
    # a paying-user trap ("no programs match" → user gives up, burns 1 req).
    if amount_min_man_yen is not None and amount_min_man_yen < 0:
        return {
            "total": 0, "limit": limit, "offset": offset, "results": [],
            "error": {
                "code": "invalid_range",
                "message": f"amount_min_man_yen must be >= 0 (got {amount_min_man_yen}).",
                "hint": "Field is 万円; pass 0 for 'no lower bound', or omit the param.",
                "retry_with": ["search_programs (omit amount_min_man_yen)"],
            },
        }
    if amount_max_man_yen is not None and amount_max_man_yen < 0:
        return {
            "total": 0, "limit": limit, "offset": offset, "results": [],
            "error": {
                "code": "invalid_range",
                "message": f"amount_max_man_yen must be >= 0 (got {amount_max_man_yen}).",
                "hint": "Field is 万円; omit for 'no upper bound'.",
                "retry_with": ["search_programs (omit amount_max_man_yen)"],
            },
        }

    where: list[str] = []
    params: list[Any] = []
    join_fts = False

    if q:
        q_clean = q.strip()
        if len(q_clean) >= 3:
            from jpintel_mcp.api.programs import _build_fts_match
            join_fts = True
            params.append(_build_fts_match(q_clean))
        else:
            # Short query (1-2 chars: 'DX', 'EC', 'IT'). FTS5 trigram can't
            # tokenize, so we LIKE. Expand via KANA_EXPANSIONS so 'DX' also
            # matches 'デジタルトランスフォーメーション' / 'デジタル化', and 'EC'
            # also matches 'Eコマース' / '電子商取引'. Without this the user
            # pays ¥3/req for 0 hits on a normal abbreviation.
            from jpintel_mcp.api.programs import KANA_EXPANSIONS
            short_terms: list[str] = [q_clean]
            for k in (q_clean, q_clean.lower(), q_clean.upper()):
                if k in KANA_EXPANSIONS:
                    short_terms.extend(KANA_EXPANSIONS[k])
                    break
            # Dedup while preserving order.
            seen: set[str] = set()
            short_terms = [t for t in short_terms if not (t in seen or seen.add(t))]
            like_or: list[str] = []
            for t in short_terms:
                like_or.append("(primary_name LIKE ? OR aliases_json LIKE ?)")
                like = f"%{t}%"
                params.extend([like, like])
            where.append("(" + " OR ".join(like_or) + ")")

    if tier:
        where.append(f"tier IN ({','.join('?' * len(tier))})")
        params.extend(tier)
    pref_raw = prefecture
    prefecture = _normalize_prefecture(prefecture)
    # BUG-2 fix: warn on unknown prefecture, drop filter so we don't silently
    # match 0 rows on a typo like 'Tokio' / '東京府' (¥3/req refund trap).
    input_warnings: list[dict[str, Any]] = []
    if pref_raw and not _is_known_prefecture(pref_raw):
        input_warnings.append({
            "field": "prefecture",
            "code": "unknown_prefecture",
            "value": pref_raw,
            "normalized_to": prefecture,
            "message": (
                f"prefecture={pref_raw!r} は正規の都道府県に一致せず。"
                "フィルタを無効化し全国ベースで返しました。正しい例: '東京' / '東京都' / 'Tokyo'。"
            ),
            "retry_with": ["enum_values(field='prefecture')"],
        })
        prefecture = None
    if prefecture:
        where.append("prefecture = ?")
        params.append(prefecture)
    authority_level_norm = _normalize_authority_level(authority_level)
    if authority_level_norm:
        where.append("authority_level = ?")
        params.append(authority_level_norm)
    if funding_purpose:
        for fp in funding_purpose:
            where.append("funding_purpose_json LIKE ?")
            params.append(f"%{json.dumps(fp, ensure_ascii=False)}%")
    if target_type:
        for t in target_type:
            where.append("target_types_json LIKE ?")
            params.append(f"%{json.dumps(t, ensure_ascii=False)}%")
    if amount_min_man_yen is not None:
        where.append("amount_max_man_yen >= ?")
        params.append(amount_min_man_yen)
    if amount_max_man_yen is not None:
        where.append("amount_max_man_yen <= ?")
        params.append(amount_max_man_yen)
    if not include_excluded:
        where.append("excluded = 0")
        # Keep the MCP surface in parity with the REST gate: tier='X' is
        # the quality quarantine. api/programs.py applies the same rule
        # (COALESCE(tier,'X') != 'X'); MCP must not be looser.
        where.append("COALESCE(tier,'X') != 'X'")

    # as_of filter: drop rows whose application_window.end_date is strictly
    # past relative to as_of_iso. NULL-tolerant: rows with no end_date (通年
    # / 随時 / not yet structured) are KEPT — absence of a deadline is not
    # closure. dd_v4_08 / v8 P3-L: backward-compat-breaking (default shifts
    # from "all" to "active today") accepted as 詐欺 risk mitigation.
    where.append(
        "(json_extract(application_window_json, '$.end_date') IS NULL "
        " OR json_extract(application_window_json, '$.end_date') >= ?)"
    )
    params.append(as_of_iso)

    if join_fts:
        base_from = "programs_fts JOIN programs USING(unified_id)"
        where_clause = "programs_fts MATCH ?"
        if where:
            where_clause = where_clause + " AND " + " AND ".join(where)
        order_sql = "ORDER BY rank, primary_name"
    else:
        base_from = "programs"
        where_clause = " AND ".join(where) if where else "1=1"
        order_sql = (
            "ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 "
            "WHEN 'C' THEN 3 ELSE 4 END, primary_name"
        )

    conn = connect()
    try:
        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM {base_from} WHERE {where_clause}", params
        ).fetchone()
        rows = conn.execute(
            f"SELECT programs.* FROM {base_from} WHERE {where_clause} {order_sql} "
            f"LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        # Build rows at the "default" shape, then enrich / trim based on
        # `fields`. `_row_to_dict(include_enriched=True)` does the enriched
        # JSON decode; we only pay for it when fields=full.
        results: list[dict[str, Any]] = []
        for r in rows:
            rec = _row_to_dict(r, include_enriched=(fields == "full"))
            results.append(_trim_to_fields(rec, fields))
        payload: dict[str, Any] = {
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": results,
            "meta": {"data_as_of": as_of_iso},
            "retrieval_note": (
                f"Filtered for active items as of {as_of_iso} JST "
                "(rows with no application_window.end_date are kept "
                "as 通年 / 随時)."
            ),
        }
        if input_warnings or limit_warnings:
            payload["input_warnings"] = input_warnings + limit_warnings
        if total == 0:
            # Empty-result hint steers the agent toward the right alternative
            # instead of telling the user "no data". The text here is picked
            # up verbatim by the model in many clients.
            payload["hint"] = _empty_search_hint(
                q, prefecture, list(tier) if tier else None,
                authority_level_norm, target_type, funding_purpose
            )
            payload["retry_with"] = [
                "search_case_studies",
                "search_loan_programs",
                "search_enforcement_cases",
            ]
        return payload
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def get_program(
    unified_id: Annotated[
        str,
        Field(
            description=(
                "Program unified_id from search_programs results. Canonical "
                "internal IDs (e.g. 'keiei-kaishi-shikin', 'it-dounyu-2026') "
                "or synthetic 'UNI-ext-<10hex>' external-ingest IDs."
            ),
        ),
    ],
    fields: Annotated[
        Literal["minimal", "default", "full"],
        Field(
            description=(
                "Response shape. 'minimal' = 7-key whitelist. 'default' = "
                "full Program + enriched A-J + source_mentions + lineage "
                "(legacy shape). 'full' = default with enriched/source_mentions "
                "keys guaranteed present (may be null)."
            ),
        ),
    ] = "default",
) -> dict[str, Any]:
    """DETAIL: 1 制度の完全詳細を unified_id で取得する (fetch one 補助金 / 助成金 / 融資 / 税制 / 認定 program's full detail). Returns application window, required documents, exclusion notes, statistics (J_*), plus source_url + fetched_at lineage. Jグランツ does not expose per-program detail via API; this is the structured equivalent.

    Use when the user names a specific program ("事業再構築補助金の要件を教えて") or
    after search_programs returns a candidate. For 2-50 programs at once, use
    batch_get_programs instead (one round-trip).

    Enriched fields cover application_window, documents_required, exclusions,
    statistics (J_statistics often null for B/C tier), authority, contact,
    subsidy_rate, target_types (detailed).

    WHEN NOT:
      - `batch_get_programs` instead if you have 2-50 unified_ids — avoid N round-trips.
      - `search_programs` instead when the user only named the program by keyword, not unified_id.
      - `search_case_studies(program_used=primary_name)` instead when they want recipients, not policy text.

    CHAIN:
      → `check_exclusions(program_ids=[unified_id, …])` to test 併給可否 with other candidates.
      → `search_case_studies(program_used=primary_name)` for recipient evidence — the field substring-matches programs_used_json, which stores program names (not unified_ids).
      → `search_enforcement_cases(q=primary_name)` for 不正 / 返還 history against this program.
    """
    # === S3 HTTP FALLBACK ===
    _fb = _fallback_call(
        "get_program",
        rest_path=f"/v1/programs/{unified_id}",
        params={"fields": fields},
    )
    if _fb is not None:
        return _fb
    # === END S3 HTTP FALLBACK ===
    fields = _resolve_fields(fields)
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM programs WHERE unified_id = ?", (unified_id,)
        ).fetchone()
        if row is None:
            return {
                "error": f"program not found: {unified_id}",
                "code": "no_matching_records",
                "hint": "unified_id は search_programs の results[].unified_id をそのまま渡してください.",
            }
        rec = _row_to_dict(row, include_enriched=True)
        return _trim_to_fields(rec, fields)
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def batch_get_programs(
    unified_ids: Annotated[
        list[str],
        Field(
            description=(
                "1-50 unified_id values from search_programs. Deduped "
                "(first-occurrence order preserved). Missing ids return in "
                "not_found[], not as an error — partial success is expected."
            ),
            min_length=1,
            max_length=50,
        ),
    ],
) -> dict[str, Any]:
    """DETAIL: 複数の制度を 1 コールで一括取得する (batch fetch up to 50 補助金 / 助成金 / 融資 / 税制 / 認定 programs). Use after search_programs returns a candidate list and the user wants full detail for comparison ("この3つの補助金を詳しく比較して") — 50 round-trips collapse to one.

    Mirrors REST `POST /v1/programs/batch`. Each element of `results[]` has the
    same shape as `get_program(fields="full")`: Program + enriched (A-J) +
    source_mentions + lineage.

    Missing ids return in `not_found[]` — never raises on partial misses. Check
    both `results[]` and `not_found[]` before telling the user "not found".

    WHEN NOT:
      - `get_program` instead for a single unified_id — simpler contract, smaller payload.
      - `search_programs` instead when the user has not produced unified_ids yet.

    CHAIN:
      → `check_exclusions(program_ids=[…])` on the same id set to verify 併給可否.
      → `search_case_studies(program_used=primary_name)` per row when user needs recipient evidence (substring match; data stores names).
    """
    # Dedupe, preserving first-occurrence order (matches REST handler).
    seen: set[str] = set()
    deduped: list[str] = []
    for uid in unified_ids:
        if uid in seen:
            continue
        seen.add(uid)
        deduped.append(uid)

    if not deduped:
        return {
            "results": [], "not_found": [],
            "error": {
                "code": "empty_input",
                "message": "unified_ids required (list must contain 1-50 ids)",
                "hint": "Run search_programs first to obtain unified_id values.",
                "retry_with": ["search_programs"],
            },
        }
    if len(deduped) > 50:
        return {
            "results": [], "not_found": [],
            "error": {
                "code": "limit_exceeded",
                "message": f"unified_ids cap is 50, got {len(deduped)}",
                "hint": "Chunk into batches of 50 and call batch_get_programs multiple times.",
                "retry_with": ["batch_get_programs (unified_ids=list[:50])"],
            },
        }

    conn = connect()
    try:
        placeholders = ",".join("?" * len(deduped))
        rows = conn.execute(
            f"SELECT * FROM programs WHERE unified_id IN ({placeholders})",
            deduped,
        ).fetchall()
        by_id: dict[str, sqlite3.Row] = {r["unified_id"]: r for r in rows}

        results: list[dict[str, Any]] = []
        not_found: list[str] = []
        for uid in deduped:
            row = by_id.get(uid)
            if row is None:
                not_found.append(uid)
                continue
            # Batch uses the "full" contract — enriched/source_mentions/lineage
            # keys always present even if null. Parity with REST /v1/programs/batch.
            rec = _row_to_dict(row, include_enriched=True)
            results.append(_trim_to_fields(rec, "full"))
        out: dict[str, Any] = {"results": results, "not_found": not_found}
        if not results and not_found:
            out["hint"] = (
                f"指定した {len(not_found)} 件の unified_id はどれも見つかりません。"
                "ID が古い / ミスタイプの可能性。search_programs で先に最新 ID を取得してください。"
            )
            out["retry_with"] = ["search_programs", "list_open_programs"]
            out["data_state"] = "all_ids_not_found"
        return out
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def list_exclusion_rules(
    kind: Annotated[
        list[Literal[
            "exclude", "prerequisite", "absolute", "combine_ok",
            "conditional_reduction", "same_asset_exclusive",
            "cross_tier_same_asset", "area_allocation",
            "cross_tier_loan_interest", "entity_scope_restriction",
            "mutex_certification",
        ]] | None,
        Field(
            description=(
                "Filter by rule kind (multi-select, OR). Omit for all 181. "
                "Common narrow: ['exclude', 'absolute'] for 併給禁止 only."
            ),
        ),
    ] = None,
    program_id: Annotated[
        str | None,
        Field(
            description=(
                "Filter rules that reference this program in program_a, "
                "program_b, or program_b_group. Accepts unified_id "
                "(UNI-…) or agri-canonical names (keiei-kaishi-shikin, "
                "etc). Omit for all rules."
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool,
        Field(
            description=(
                "When True, return raw full rows (description + source_notes "
                "+ source_urls + extra unmodified). Default False truncates "
                "description/source_notes to 200 chars, keeps only first "
                "source_url, and drops `extra`. Saves ~45% tokens per call."
            ),
        ),
    ] = False,
) -> dict[str, Any]:
    """COMPLIANCE: 補助金の併給禁止 / 前提要件ルールを列挙する (list 181 subsidy exclusion + prerequisite rules across agri + non-agri). Pre-extracted from 公募要領 PDF footnotes — not available as structured data on Jグランツ 公開 API or any ministry site. Parsing these from JP prose is exactly the kind of brittle LLM work this tool eliminates.

    Typical queries:
      - "補助金の排他ルール一覧が欲しい"
      - "農業系の併給制限を教えて"
      - "IT 導入補助金の他省庁事業との重複排除ルールは?"

    Rule kinds (181 total):
      - 125 exclude (相互排他)
      - 17 prerequisite (A を取る前に B が必要)
      - 15 absolute (例外なしの併給不可)
      - 9 combine_ok (明示的に併用可と告知済み)
      - 6 conditional_reduction (併用時に上限減額)
      - 9 その他 (same_asset_exclusive 3 / cross_tier_same_asset 2 / area_allocation 1 / cross_tier_loan_interest 1 / entity_scope_restriction 1 / mutex_certification 1)
    Provenance: 35 hand-seeded named rules (22 agri + 13 non-agri) + 146 primary-source auto-extracted (`rule_id = excl-ext-*`, 要綱 / 公募要領 PDF parser output). Domain coverage spans 事業再構築・ものづくり・IT導入・省エネ系 に加え、経営開始資金 / 経営発展支援 / 雇用就農 / 青年等就農 / スーパーL / 認定新規就農者 / 認定農業者 の農業系.

    TOKEN BUDGET: default is lean (~68 KB for all 181 rows). For raw citation
    text pass `verbose=True` (~124 KB). To narrow scope use `kind=[...]`.

    WHEN NOT:
      - `check_exclusions(program_ids=[…])` instead when the user has a specific candidate set — that returns only the triggered rules, not all 181. Do not call both back-to-back for the same question.
      - `search_programs` / `get_program` instead for program *definitions* — this tool only returns *rules*, not program text.

    CHAIN:
      → `check_exclusions(program_ids=[…])` once the user narrows to candidates.
      → `search_programs(q=rule.program_a)` to surface the program referenced in a rule they ask about.
    """
    conn = connect()
    try:
        where: list[str] = []
        params: list[Any] = []
        if kind:
            where.append(f"kind IN ({','.join('?' * len(kind))})")
            params.extend(kind)
        if program_id:
            # program_id may sit in program_a, program_b, or
            # program_b_group_json (a JSON array). LIKE on the JSON
            # text covers the array case without sqlite-json1 dependency.
            where.append(
                "(program_a = ? OR program_b = ? "
                "OR COALESCE(program_b_group_json,'') LIKE ?)"
            )
            params.extend([program_id, program_id, f'%"{program_id}"%'])
        sql = "SELECT * FROM exclusion_rules"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY rule_id"
        rows = conn.execute(sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            desc = r["description"] or ""
            notes = r["source_notes"] or ""
            src_urls = _json_col(r, "source_urls_json", [])
            extra = _json_col(r, "extra_json", {})
            if not verbose:
                if len(desc) > 200:
                    desc = desc[:197] + "…"
                if len(notes) > 200:
                    notes = notes[:197] + "…"
                src_urls = src_urls[:1]
                extra = {}
            out.append({
                "rule_id": r["rule_id"],
                "kind": r["kind"],
                "severity": r["severity"],
                "program_a": r["program_a"],
                "program_b": r["program_b"],
                "program_b_group": _json_col(r, "program_b_group_json", []),
                "description": desc,
                "source_notes": notes,
                "source_urls": src_urls,
                "extra": extra,
            })
        # Always return the same envelope shape (rules / total / filters)
        # regardless of populated vs empty result. The pre-fix path returned
        # a bare list on hit and a dict envelope on miss — that union typing
        # forced every consumer to branch on `isinstance(resp, list)`. The
        # unified envelope makes responses self-describing and lets clients
        # always read `.rules` / `.total`.
        filters_applied = {
            k: v for k, v in [
                ("kind", list(kind) if kind else None),
                ("program_id", program_id),
                ("verbose", verbose),
            ] if v is not None and v != []
        }
        if not out:
            # Empty-hit envelope: echo filters + suggest broader queries
            # so the agent doesn't burn another ¥3/req on a near-miss retry.
            suggestions: list[str] = []
            if program_id and kind:
                suggestions.append(
                    "Drop 'kind' to see every rule that references this "
                    "program (across exclude / prerequisite / absolute …)."
                )
            if program_id:
                suggestions.append(
                    "check_exclusions(program_ids=[program_id, candidate_id]) "
                    "の direct lookup も検討 — that path triggers prerequisite "
                    "rules even on a single program_id."
                )
                suggestions.append(
                    "search_programs(q=program_id) で unified_id の表記揺れ "
                    "(UNI-… vs agri-canonical 名) を確認."
                )
            elif kind:
                suggestions.append(
                    "Drop 'kind' to see all 181 rules; each kind has at "
                    "least 1 row, so kind alone never returns 0."
                )
            suggestions.append(
                "enum_values(field='exclusion_rule_kind') で kind enum 一覧 "
                "(exclude / prerequisite / absolute / combine_ok / …)."
            )
            return {
                "rules": [],
                "total": 0,
                "filters": filters_applied,
                "hint": {
                    "message": (
                        "No exclusion rules matched. 該当プログラムは併用制限が "
                        "登録されていない、またはフィルタが厳しすぎる可能性。"
                    ),
                    "filters_applied": filters_applied,
                    "suggestions": suggestions,
                },
                "retry_with": ["check_exclusions", "search_programs"],
            }
        return {
            "rules": out,
            "total": len(out),
            "filters": filters_applied,
        }
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def check_exclusions(
    program_ids: Annotated[
        list[str],
        Field(
            description=(
                "2+ program identifiers to check against the full 181 "
                "exclusion / prerequisite rule set. Accepts unified_id or "
                "agri-canonical names ('keiei-kaishi-shikin', "
                "'koyo-shuno-shikin', 'super-l-shikin', 'it-dounyu-2026', "
                "etc.). For a prerequisite check, 1 program id is allowed. "
                "Capped at 50 (parity with batch_get_programs); larger sets "
                "should be chunked by the caller."
            ),
            min_length=1,
            max_length=50,
        ),
    ],
) -> dict[str, Any]:
    """COMPLIANCE: 併給可否を機械的に判定する — 候補制度セットに対して 181 本の併給禁止 / 前提要件ルールを走らせ、違反するものだけ返す (given a candidate set of program IDs, run all 181 補助金 exclusion / prerequisite rules and return only the violations). This answers the core "can I combine A and B?" / "do I need certification X before applying for Y?" question in one call — LLM による PDF 脚注パースの hallucination を構造的に排除する。

    Typical queries:
      - "IT導入補助金と事業再構築補助金は併用できる?"
      - "これら3つの補助金に同時申請できる?"
      - "スーパーL資金を使う前に必要な認定は?"

    Empty `hits[]` means no rule fired — safe-by-default interpretation: 併給可
    (within the 181 codified rules; edge cases outside this set may still exist).

    WHEN NOT:
      - `list_exclusion_rules` instead if the user wants to browse rules generally without a specific candidate set.
      - `search_programs` first if you don't yet have program_ids — this tool requires them as input.

    CHAIN:
      ← `search_programs` / `batch_get_programs` to produce the program_ids.
      → `get_program(unified_id=hit.program_a)` to explain a triggered rule in context.
      → `search_case_studies(program_used=primary_name)` to check how recipients handled the restriction in practice (resolve primary_name via `get_program(unified_id=hit.program_a)` first).
      DO NOT → `list_exclusion_rules` right after this call — each hit already embeds the rule row (rule_id / description / severity / source_url).
    """
    if not program_ids:
        return {
            "program_ids": [], "hits": [], "checked_rules": 0,
            "summary": "program_ids required (>=1 for prerequisite, >=2 for exclusion check).",
            "error": {
                "code": "empty_input",
                "message": "program_ids required",
                "hint": "Pass unified_id (UNI-xxxx) or agri-canonical names (keiei-kaishi-shikin, etc).",
                "retry_with": ["search_programs", "list_exclusion_rules"],
            },
        }
    if len(program_ids) > 50:
        return {
            "program_ids": program_ids[:50], "hits": [], "checked_rules": 0,
            "summary": f"program_ids cap is 50 (got {len(program_ids)}).",
            "error": {
                "code": "limit_exceeded",
                "message": f"program_ids supports at most 50 items per call (got {len(program_ids)})",
                "hint": "Chunk the list and call check_exclusions multiple times.",
                "retry_with": ["check_exclusions (program_ids=list[:50])"],
            },
        }

    # Dual-key expansion (P0-3 / J10 fix, migration 051).
    # exclusion_rules.program_{a,b} carry a mix of unified_id ('UNI-...'),
    # English slug ('keiei-kaishi-shikin'), and Japanese name keys.
    # Migration 051 added program_{a,b}_uid columns where the legacy key
    # resolves to a programs.unified_id. Without this expansion a caller
    # passing a unified_id silently misses slug/name-keyed rules — this
    # was the K4/J10 silent fraud risk.
    #
    # Strategy: build a (caller_input → unified_id) map by looking up each
    # input as either programs.unified_id OR programs.primary_name. A rule
    # matches when the rule's legacy string is in the input set (legacy
    # behavior, preserved verbatim) OR when the rule's resolved _uid
    # equals one of the input-derived unified_ids.
    selected = set(program_ids)
    conn = connect()
    try:
        # Reverse-resolve every caller input. The placeholders are bounded
        # by the 50-id cap above.
        placeholders = ",".join(["?"] * len(program_ids))
        prog_rows = conn.execute(
            f"SELECT unified_id, primary_name FROM programs "
            f"WHERE unified_id IN ({placeholders}) "
            f"   OR primary_name IN ({placeholders})",
            (*program_ids, *program_ids),
        ).fetchall()
        # input_to_uid: caller key (uid OR primary_name) → programs.unified_id
        input_to_uid: dict[str, str] = {}
        # uid_to_input: unified_id → preferred caller-facing label (input or uid)
        uid_to_input: dict[str, str] = {}
        for pr in prog_rows:
            uid = pr["unified_id"]
            name = pr["primary_name"]
            if uid in selected:
                input_to_uid[uid] = uid
                uid_to_input.setdefault(uid, uid)
            if name and name in selected:
                input_to_uid[name] = uid
                uid_to_input.setdefault(uid, name)

        rows = conn.execute("SELECT * FROM exclusion_rules").fetchall()
        # PRAGMA table_info returns (cid, name, type, notnull, dflt, pk).
        col_names = {d[1] for d in conn.execute("PRAGMA table_info(exclusion_rules)")}
        has_uid = "program_a_uid" in col_names and "program_b_uid" in col_names

        def _match(rule_key: str | None, rule_uid: str | None) -> str | None:
            # Legacy direct match (caller passed the exact rule key).
            if rule_key and rule_key in selected:
                return rule_key
            # Caller passed a unified_id that the rule resolves to.
            if rule_uid:
                if rule_uid in selected:
                    return uid_to_input.get(rule_uid, rule_uid)
                # Caller passed a primary_name that resolves to rule's uid.
                for caller_key, uid in input_to_uid.items():
                    if uid == rule_uid:
                        return caller_key
            return None

        hits: list[dict[str, Any]] = []
        for r in rows:
            b_group = _json_col(r, "program_b_group_json", [])
            candidates: set[str] = set()
            a_uid = r["program_a_uid"] if has_uid else None
            b_uid = r["program_b_uid"] if has_uid else None
            ma = _match(r["program_a"], a_uid)
            if ma:
                candidates.add(ma)
            mb = _match(r["program_b"], b_uid)
            if mb:
                candidates.add(mb)
            for gid in b_group:
                # group entries are legacy strings only; no _uid column.
                mg = _match(gid, None)
                if mg:
                    candidates.add(mg)

            if len(candidates) >= 2 or (r["kind"] == "prerequisite" and candidates):
                hits.append(
                    {
                        "rule_id": r["rule_id"],
                        "kind": r["kind"],
                        "severity": r["severity"],
                        "programs_involved": sorted(candidates),
                        "description": r["description"],
                        "source_urls": _json_col(r, "source_urls_json", []),
                    }
                )
        if hits:
            severities = [h["severity"] for h in hits if h.get("severity")]
            top_severity = next(
                (s for s in ("critical", "high", "medium", "low") if s in severities),
                severities[0] if severities else "unknown",
            )
            summary = (
                f"{len(hits)} rule(s) fired. 最高 severity: {top_severity}. "
                "rule_id / programs_involved / source_urls を確認して併給不可として扱ってください."
            )
        else:
            summary = (
                f"0 件のルールに抵触 ({len(rows)} 本を全件検証) — "
                "codified ルール内では併給可の見込み. 最終確認は各 公募要領 の footnote も参照."
            )
        return {
            "program_ids": program_ids,
            "hits": hits,
            "checked_rules": len(rows),
            "summary": summary,
        }
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def get_meta() -> dict[str, Any]:
    """UTILITY: データの鮮度・網羅件数を確認する (verify dataset freshness and scope). Returns visible program count (excluded=0 AND tier != X), canonical vs external-source split, 採択事例 / 融資 / 行政処分 / rule counts, tier distribution (S/A/B/C/X), prefecture distribution, and last_ingested_at.

    **When to call:** before first `search_programs` if the user asks about
    coverage / freshness ("データはいつ更新された?" / "何件入ってる?" /
    "都道府県別の分布は?"). Otherwise skip to search — the per-row
    `source_fetched_at` is authoritative for per-record freshness.

    **Key fields to surface to the user:**
    - `visible_programs`: rows a default search will return (excluded=0, tier != X)
    - `tier_counts`: quality distribution; quote S/A first when the user
      asks about "信頼できるデータ".
    - `last_ingested_at`: UTC ISO-8601 of the most recent pipeline run.

    WHEN NOT:
      - `enum_values(field=…)` instead if the user wants the canonical list of filter values (target_type, funding_purpose, etc.) — get_meta only returns counts, not value lists.
      - Per-row `source_fetched_at` via `get_program` is more authoritative than `last_ingested_at` for a single program's freshness.

    CHAIN:
      → `enum_values(field=…)` to translate "何種類の target_type がある?" after seeing tier_counts.
      → `search_programs` once the user has confirmed coverage suits their query.
      DO NOT → call `search_*` tools right after unless the user has a concrete query in hand; get_meta is a coverage/freshness probe, not a discovery hop.
    """
    conn = connect()
    try:
        tier_counts: dict[str, int] = {}
        for row in conn.execute(
            "SELECT COALESCE(tier, 'unknown') AS tier, COUNT(*) AS c "
            "FROM programs WHERE excluded=0 GROUP BY tier"
        ):
            tier_counts[row["tier"]] = row["c"]

        pref_counts: dict[str, int] = {}
        for row in conn.execute(
            "SELECT COALESCE(prefecture, '_none') AS p, COUNT(*) AS c "
            "FROM programs WHERE excluded=0 GROUP BY prefecture"
        ):
            pref_counts[row["p"]] = row["c"]

        def _scalar(sql: str) -> int:
            cur = conn.execute(sql)
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0

        programs_total = _scalar("SELECT COUNT(*) FROM programs")
        programs_visible = _scalar(
            "SELECT COUNT(*) FROM programs WHERE excluded=0 AND COALESCE(tier,'X') != 'X'"
        )
        programs_canonical = _scalar(
            "SELECT COUNT(*) FROM programs WHERE unified_id NOT LIKE 'UNI-ext-%'"
        )
        programs_external = _scalar(
            "SELECT COUNT(*) FROM programs WHERE unified_id LIKE 'UNI-ext-%'"
        )
        rules_n = _scalar("SELECT COUNT(*) FROM exclusion_rules")

        # These tables were added by migrations 011 / 012 / 013; older DBs
        # may not have them. Tolerate missing tables so get_meta never fails.
        def _optional_scalar(sql: str) -> int | None:
            try:
                return _scalar(sql)
            except sqlite3.OperationalError:
                return None

        case_studies_n = _optional_scalar("SELECT COUNT(*) FROM case_studies")
        loan_programs_n = _optional_scalar("SELECT COUNT(*) FROM loan_programs")
        enforcement_cases_n = _optional_scalar(
            "SELECT COUNT(*) FROM enforcement_cases"
        )

        # Dynamic tool count: read directly from FastMCP's tool manager
        # rather than hardcoding. Hardcoding drifted (was "47 if autonomath
        # else 31" but V4 absorption added 4 universal tools = 59 with
        # autonomath, 38 without). The tool_manager's registry is the single
        # source of truth and updates whenever a `@mcp.tool` decorator runs.
        try:
            tool_count = len(mcp._tool_manager.list_tools())
        except Exception:  # noqa: BLE001 — never let meta probe fail
            tool_count = 0

        meta: dict[str, Any] = {
            "total_programs": programs_total,
            "visible_programs": programs_visible,
            "canonical_programs": programs_canonical,
            "external_programs": programs_external,
            "case_studies_count": case_studies_n,
            "loan_programs_count": loan_programs_n,
            "enforcement_cases_count": enforcement_cases_n,
            "exclusion_rules_count": rules_n,
            "tier_counts": tier_counts,
            "prefecture_counts": pref_counts,
            "tool_count": tool_count,
            "mcp_protocol_version": "2025-06-18",
            "package_version": __version__,
        }
        for row in conn.execute("SELECT key, value FROM meta"):
            if row["key"] in {"last_ingested_at", "data_as_of"}:
                meta[row["key"]] = row["value"]
        return meta
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def get_usage_status(
    api_key: Annotated[
        str | None,
        Field(
            description=(
                "Caller's API key. None / omitted → returns the configured "
                "anonymous quota (50 req/月 per IP+fingerprint). When provided, "
                "returns the authenticated key's month-to-date usage."
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """META: 現在のクォータ残量を確認する (probe current API quota state without consuming a slot).

    Returns the caller's quota state under the active tier:
      - ``tier``: "anonymous" | "paid" | "free"
      - ``limit``: integer cap for the period (None for paid — metered, no cap)
      - ``remaining``: requests left this period (None for paid)
      - ``used``: month-to-date or day-to-date count for this caller
      - ``reset_at``: ISO 8601 timestamp of next quota reset
      - ``reset_timezone``: "JST" (anonymous) or "UTC" (authenticated). The
        anonymous bucket resets at JST 月初 00:00; authenticated counters
        reset at UTC midnight (daily) or UTC 月初 (paid month-to-date).
        These are NOT the same — a 50-req/月 anonymous bucket can roll
        over up to 9 hours BEFORE a UTC-tracked dashboard says it should.
      - ``upgrade_url``: when relevant, the public upgrade landing.
      - ``note``: human-readable summary.

    **Why this matters for MCP callers:** the anonymous tier hands out
    50 req/月 per IP+fingerprint. An LLM batch that does 60 small queries
    in one session will hit the ceiling at request 51 with a hard 429.
    Calling ``get_usage_status`` *before* a batch lets the agent tell the
    user "あと N 件で月次クォータに達します。継続するなら API key を発行してください。"
    instead of failing mid-flight.

    **Caveat (MCP stdio):** the MCP transport has no client IP, so
    anonymous calls from MCP cannot resolve the per-IP bucket — the tool
    returns the configured ceiling and a note explaining that the actual
    remaining is observable only from the HTTP layer (``GET /v1/usage``)
    where the IP+fingerprint is known. With ``api_key`` supplied, the
    response is exact (month-to-date count from usage_events).

    WHEN:
      - Before launching a batch operation that may exceed 50 calls.
      - When a previous tool returned a 429-ish hint.
      - To reassure the user about cost before recommending a sweep.
    WHEN NOT: Do NOT call on every turn — once you know the remaining,
    reuse the value across the session. Calling repeatedly is harmless
    but noisy (each invocation still costs telemetry latency).

    EXAMPLE (anonymous, MCP):
      get_usage_status() →
        {"tier":"anonymous","limit":50,"remaining":null,
         "reset_at":"2026-05-01T00:00:00+09:00","reset_timezone":"JST",
         "note":"MCP stdio cannot resolve per-IP bucket; call GET /v1/usage for exact remaining."}

    EXAMPLE (paid):
      get_usage_status(api_key="am_…") →
        {"tier":"paid","limit":null,"remaining":null,"used":1247,
         "reset_at":"2026-05-01T00:00:00+00:00","reset_timezone":"UTC"}
    """
    from datetime import timedelta, timezone as _tz

    _JST = _tz(timedelta(hours=9))

    def _jst_next_month_iso() -> str:
        now = datetime.now(_JST)
        if now.month == 12:
            nxt = now.replace(
                year=now.year + 1, month=1, day=1,
                hour=0, minute=0, second=0, microsecond=0,
            )
        else:
            nxt = now.replace(
                month=now.month + 1, day=1,
                hour=0, minute=0, second=0, microsecond=0,
            )
        return nxt.isoformat()

    def _utc_next_month_iso() -> str:
        now = datetime.now(UTC)
        if now.month == 12:
            nxt = now.replace(
                year=now.year + 1, month=1, day=1,
                hour=0, minute=0, second=0, microsecond=0,
            )
        else:
            nxt = now.replace(
                month=now.month + 1, day=1,
                hour=0, minute=0, second=0, microsecond=0,
            )
        return nxt.isoformat()

    # No api_key supplied → anonymous response. MCP stdio has no IP so we
    # can only return the configured ceiling — be honest about that in the
    # note rather than reporting a misleading "remaining=50" that may
    # already be 12 by the time the next call lands on the REST side.
    if not api_key:
        return {
            "tier": "anonymous",
            "limit": settings.anon_rate_limit_per_month,
            "remaining": None,  # unknown over MCP stdio
            "used": 0,  # unknown
            "reset_at": _jst_next_month_iso(),
            "reset_timezone": "JST",
            "upgrade_url": "https://autonomath.ai/go",
            "note": (
                "Anonymous tier は IP+fingerprint 単位で "
                f"{settings.anon_rate_limit_per_month} req/月 (JST 月初 00:00 リセット)。"
                "MCP stdio は client IP を解決できないため exact remaining は不明。"
                "正確な残量は REST endpoint `GET /v1/usage` を呼ぶか、"
                "X-API-Key を発行 (paid tier ¥3/req 税別) してください。"
            ),
        }

    # Authenticated path — resolve the key locally.
    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(api_key)
    conn = connect()
    try:
        row = conn.execute(
            "SELECT tier, revoked_at FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
        if row is None:
            return {
                "tier": "unknown",
                "limit": None,
                "remaining": None,
                "used": 0,
                "reset_at": _utc_next_month_iso(),
                "reset_timezone": "UTC",
                "upgrade_url": "https://autonomath.ai/go",
                "note": (
                    "Provided api_key did not match any issued key. "
                    "Was it rotated? POST /v1/me/rotate-key issues a fresh key once."
                ),
                "error": {
                    "code": "key_not_found",
                    "message": "api_key not recognized",
                    "hint": "Verify the key string. Anonymous tier is implied if you omit api_key.",
                },
            }
        if row["revoked_at"]:
            return {
                "tier": "revoked",
                "limit": 0,
                "remaining": 0,
                "used": 0,
                "reset_at": _utc_next_month_iso(),
                "reset_timezone": "UTC",
                "upgrade_url": "https://autonomath.ai/go",
                "note": (
                    "API key has been revoked. Issue a new one via the dashboard "
                    "(POST /v1/me/rotate-key) or sign in again."
                ),
                "error": {
                    "code": "key_revoked",
                    "message": "api_key has been revoked",
                    "hint": "Generate a fresh key from the customer portal.",
                },
            }

        tier = row["tier"]
        if tier == "paid":
            month_start = datetime.now(UTC).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            ).isoformat()
            (used,) = conn.execute(
                "SELECT COUNT(*) FROM usage_events "
                "WHERE key_hash = ? AND ts >= ? "
                "AND metered = 1 AND status < 400",
                (key_hash, month_start),
            ).fetchone()
            return {
                "tier": "paid",
                "limit": None,
                "remaining": None,
                "used": int(used),
                "reset_at": _utc_next_month_iso(),
                "reset_timezone": "UTC",
                "upgrade_url": None,
                "note": (
                    "Paid tier は metered ¥3/req 税別 (税込 ¥3.30)。"
                    "月次集計は UTC 月初 00:00 で 0 リセット。"
                    "詳細 breakdown: GET /v1/me/dashboard。"
                ),
            }

        # "free" / dunning-demote tier — daily cap, UTC midnight reset.
        daily_limit = settings.rate_limit_free_per_day
        bucket = datetime.now(UTC).strftime("%Y-%m-%d")
        (used,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND ts >= ?",
            (key_hash, bucket),
        ).fetchone()
        used_int = int(used)
        tomorrow = (datetime.now(UTC) + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return {
            "tier": "free",
            "limit": daily_limit,
            "remaining": max(0, daily_limit - used_int),
            "used": used_int,
            "reset_at": tomorrow.isoformat(),
            "reset_timezone": "UTC",
            "upgrade_url": "https://autonomath.ai/go",
            "note": (
                f"Free (dunning-demote) tier — daily cap {daily_limit} req。"
                "UTC 翌日 00:00 リセット。請求情報を更新すると paid tier に復帰。"
            ),
        }
    finally:
        conn.close()


_EnumFieldT = Literal[
    "target_type",
    "funding_purpose",
    "program_kind",
    "authority_level",
    "prefecture",
    "event_type",
    "ministry",
    "loan_type",
    "provider",
    "programs_used",
]


# Each entry: (frequency_sql, distinct_count_sql, note).
# frequency_sql: returns (value, count) rows ordered by count DESC, expects LIMIT param.
# distinct_count_sql: returns total distinct non-null values (no params).
_ENUM_SOURCES: dict[str, tuple[str, str, str]] = {
    "target_type": (
        "SELECT value AS v, COUNT(*) AS n "
        "FROM programs, json_each(COALESCE(target_types_json, '[]')) "
        "WHERE excluded=0 AND value IS NOT NULL "
        "GROUP BY value ORDER BY n DESC LIMIT ?",
        "SELECT COUNT(DISTINCT value) "
        "FROM programs, json_each(COALESCE(target_types_json, '[]')) "
        "WHERE excluded=0 AND value IS NOT NULL",
        "target_types[] tag on programs. Japanese + English mixed "
        "(e.g. 'sole_proprietor' vs '個人事業主'); matcher normalizes at query time, "
        "so either form is acceptable as a search filter.",
    ),
    "funding_purpose": (
        "SELECT value AS v, COUNT(*) AS n "
        "FROM programs, json_each(COALESCE(funding_purpose_json, '[]')) "
        "WHERE excluded=0 AND value IS NOT NULL "
        "GROUP BY value ORDER BY n DESC LIMIT ?",
        "SELECT COUNT(DISTINCT value) "
        "FROM programs, json_each(COALESCE(funding_purpose_json, '[]')) "
        "WHERE excluded=0 AND value IS NOT NULL",
        "funding_purpose[] tag on programs. Same bilingual mix as target_type.",
    ),
    "program_kind": (
        "SELECT program_kind AS v, COUNT(*) AS n FROM programs "
        "WHERE excluded=0 AND program_kind IS NOT NULL "
        "GROUP BY program_kind ORDER BY n DESC LIMIT ?",
        "SELECT COUNT(DISTINCT program_kind) FROM programs "
        "WHERE excluded=0 AND program_kind IS NOT NULL",
        "Kind of program. Canonical coarse values: '補助金', '助成金', '融資', "
        "'税制', '認定', 'subsidy', 'grant', 'loan'. Long tail exists; use the "
        "top-10 for user-facing filters.",
    ),
    "authority_level": (
        "SELECT authority_level AS v, COUNT(*) AS n FROM programs "
        "WHERE excluded=0 AND authority_level IS NOT NULL "
        "GROUP BY authority_level ORDER BY n DESC LIMIT ?",
        "SELECT COUNT(DISTINCT authority_level) FROM programs "
        "WHERE excluded=0 AND authority_level IS NOT NULL",
        "Administrative tier. Canonical: 'national', 'prefecture', "
        "'municipality', 'financial' (公庫 etc.). '国' legacy value may also "
        "appear — normalize to 'national' before filtering.",
    ),
    "prefecture": (
        "SELECT prefecture AS v, COUNT(*) AS n FROM programs "
        "WHERE excluded=0 AND prefecture IS NOT NULL "
        "GROUP BY prefecture ORDER BY n DESC LIMIT ?",
        "SELECT COUNT(DISTINCT prefecture) FROM programs "
        "WHERE excluded=0 AND prefecture IS NOT NULL",
        "47都道府県 + '全国' sentinel for nation-wide programs (48 values). "
        "Canonical form is the full suffix ('東京都', not '東京' or 'Tokyo'). "
        "Same form is used across programs / case_studies / enforcement_cases / "
        "loan_programs — resolve once, reuse everywhere.",
    ),
    "event_type": (
        "SELECT event_type AS v, COUNT(*) AS n FROM enforcement_cases "
        "WHERE event_type IS NOT NULL "
        "GROUP BY event_type ORDER BY n DESC LIMIT ?",
        "SELECT COUNT(DISTINCT event_type) FROM enforcement_cases "
        "WHERE event_type IS NOT NULL",
        "Enforcement outcome. Current values: 'clawback' (返還命令), "
        "'penalty' (処分). Use as a filter on search_enforcement_cases.",
    ),
    "ministry": (
        "SELECT ministry AS v, COUNT(*) AS n FROM enforcement_cases "
        "WHERE ministry IS NOT NULL "
        "GROUP BY ministry ORDER BY n DESC LIMIT ?",
        "SELECT COUNT(DISTINCT ministry) FROM enforcement_cases "
        "WHERE ministry IS NOT NULL",
        "Supervising ministry on enforcement cases. 8 values "
        "(厚労省 / 経産省 / 農水省 / 国交省 / 文科省 / 環境省 / 総務省 / 内閣府).",
    ),
    "loan_type": (
        "SELECT loan_type AS v, COUNT(*) AS n FROM loan_programs "
        "WHERE loan_type IS NOT NULL "
        "GROUP BY loan_type ORDER BY n DESC LIMIT ?",
        "SELECT COUNT(DISTINCT loan_type) FROM loan_programs "
        "WHERE loan_type IS NOT NULL",
        "Loan category. English slugs: 'general', 'agri', 'succession', "
        "'green', 'productivity', 'overseas', 'safety_net', 'special_rate', "
        "'social', 'tourism', 'wage_increase'.",
    ),
    "provider": (
        "SELECT provider AS v, COUNT(*) AS n FROM loan_programs "
        "WHERE provider IS NOT NULL "
        "GROUP BY provider ORDER BY n DESC LIMIT ?",
        "SELECT COUNT(DISTINCT provider) FROM loan_programs "
        "WHERE provider IS NOT NULL",
        "Lender. Top: '日本政策金融公庫 国民生活事業 / 中小企業事業 / 農林水産事業', "
        "'商工組合中央金庫', '信金中央金庫'.",
    ),
    "programs_used": (
        "SELECT value AS v, COUNT(*) AS n "
        "FROM case_studies, json_each(COALESCE(programs_used_json, '[]')) "
        "WHERE value IS NOT NULL "
        "GROUP BY value ORDER BY n DESC LIMIT ?",
        "SELECT COUNT(DISTINCT value) "
        "FROM case_studies, json_each(COALESCE(programs_used_json, '[]')) "
        "WHERE value IS NOT NULL",
        "Program names referenced from case_studies.programs_used_json. "
        "Feed the returned value verbatim to search_case_studies(program_used=…) — "
        "the column stores raw names (e.g. 'IT導入補助金'), not unified_ids. "
        "Umbrella labels like 'JETRO' or '日本政策金融公庫' appear and refer to an "
        "organization, not a single program.",
    ),
}


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def enum_values(
    field: Annotated[
        _EnumFieldT,
        Field(
            description=(
                "Which enum to fetch. One of: target_type, funding_purpose, "
                "program_kind, authority_level, prefecture (programs); "
                "event_type, ministry (enforcement_cases); "
                "loan_type, provider (loan_programs); "
                "programs_used (case_studies.programs_used_json raw names)."
            ),
        ),
    ],
    limit: Annotated[
        int,
        Field(
            description="Max values (top-N by frequency). Clamped to [1, 200]. Default 50.",
            ge=1,
            le=200,
        ),
    ] = 50,
) -> dict[str, Any]:
    """UTILITY: 他ツールのフィルタ値を先に検証する (probe which filter values actually exist for target_type / funding_purpose / program_kind / authority_level / event_type / ministry / loan_type / provider — call this *before* a search when unsure whether a value is canonical). Returns the live top-N distribution sorted by row-count so the agent sees realistic options.

    WHAT: Reads the DB directly (no caching) and returns {field, values:[{value,count}], total_distinct, note}. Frequency-ranked. Source tables: programs (visible rows only: excluded=0), enforcement_cases, loan_programs.

    WHEN:
      - Before `search_programs(target_type=["…"])` if unsure of canonical spelling.
      - When an earlier search returned 0 rows and `hint` suggested "値が canonical でない可能性".
      - When the user uses a vague term ("製造業" / "零細") and you need to translate to the enum vocabulary.

    WHEN NOT: Do not call if you already know the canonical value (e.g. prefecture '東京都' is free-form, not enum — use as-is). Do not call for free-text `q` queries.

    CHAIN:
      → `search_programs` / `search_enforcement_cases` / `search_loan_programs` (pass a value from the returned list).
      DO NOT → chain enum_values on every turn — once resolved, reuse the value across the session.

    EXAMPLE:
      Input:  field="target_type", limit=10
      Output: {field: "target_type", values: [{value: "sole_proprietor", count: 2744}, ...], total_distinct: 58, note: "..."}
    """
    if field not in _ENUM_SOURCES:
        return {
            "error": f"unknown field: {field!r}",
            "code": "invalid_field",
            "valid_fields": sorted(_ENUM_SOURCES.keys()),
            "hint": "field は valid_fields のいずれかを渡してください.",
        }
    freq_sql, distinct_sql, note = _ENUM_SOURCES[field]
    limit = max(1, min(200, limit))

    conn = connect()
    try:
        rows = conn.execute(freq_sql, (limit,)).fetchall()
        (total_distinct,) = conn.execute(distinct_sql).fetchone()
        return {
            "field": field,
            "values": [
                {"value": r["v"], "count": int(r["n"])}
                for r in rows
                if r["v"] is not None
            ],
            "total_distinct": int(total_distinct or 0),
            "limit": limit,
            "note": note,
        }
    finally:
        conn.close()


def _row_to_enforcement_case(row: sqlite3.Row) -> dict[str, Any]:
    """Mirror of api/enforcement.py::_row_to_case. Kept local so MCP stdio
    path has no import-time coupling on the REST layer.
    """
    fy_raw = row["occurred_fiscal_years_json"]
    fy: list[int] = []
    if fy_raw:
        try:
            parsed = json.loads(fy_raw)
            if isinstance(parsed, list):
                fy = [
                    int(x)
                    for x in parsed
                    if isinstance(x, (int, str)) and str(x).lstrip("-").isdigit()
                ]
        except (json.JSONDecodeError, ValueError):
            fy = []

    sole_raw = row["is_sole_proprietor"]
    is_sole: bool | None = None if sole_raw is None else bool(sole_raw)

    return {
        "case_id": row["case_id"],
        "event_type": row["event_type"],
        "program_name_hint": row["program_name_hint"],
        "recipient_name": row["recipient_name"],
        "recipient_kind": row["recipient_kind"],
        "recipient_houjin_bangou": row["recipient_houjin_bangou"],
        "is_sole_proprietor": is_sole,
        "bureau": row["bureau"],
        "intermediate_recipient": row["intermediate_recipient"],
        "prefecture": row["prefecture"],
        "ministry": row["ministry"],
        "occurred_fiscal_years": fy,
        "amount_yen": row["amount_yen"],
        "amount_project_cost_yen": row["amount_project_cost_yen"],
        "amount_grant_paid_yen": row["amount_grant_paid_yen"],
        "amount_improper_grant_yen": row["amount_improper_grant_yen"],
        "amount_improper_project_cost_yen": row["amount_improper_project_cost_yen"],
        "reason_excerpt": row["reason_excerpt"],
        "legal_basis": row["legal_basis"],
        "source_url": row["source_url"],
        "source_section": row["source_section"],
        "source_title": row["source_title"],
        "disclosed_date": row["disclosed_date"],
        "disclosed_until": row["disclosed_until"],
        "fetched_at": row["fetched_at"],
        "confidence": row["confidence"],
    }


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def search_enforcement_cases(
    q: Annotated[
        str | None,
        Field(
            description=(
                "Free-text LIKE match across program_name_hint + "
                "reason_excerpt + source_title. Example: '不当請求', "
                "'目的外使用', '重複受給'."
            ),
        ),
    ] = None,
    event_type: Annotated[
        str | None,
        Field(
            description=(
                "Exact match. Common values: '不当事項' / '処置要求事項' / "
                "'意見表示' / '不正' / '補助金過大交付'."
            ),
        ),
    ] = None,
    ministry: Annotated[
        str | None,
        Field(
            description=(
                "Exact match on managing 省庁. Common: '農林水産省', "
                "'経済産業省', '国土交通省', '厚生労働省'."
            ),
        ),
    ] = None,
    prefecture: Annotated[
        PrefectureParam,
        Field(
            description=(
                "都道府県 closed-set ('東京都'/'大阪府'/'全国' 等 48 値). "
                "短縮形・romaji 自動正規化、未知値は invalid_enum で拒否。"
            ),
        ),
    ] = None,
    legal_basis: Annotated[
        str | None,
        Field(description="Partial (LIKE) match on cited 法令. e.g. '補助金適正化法'."),
    ] = None,
    program_name_hint: Annotated[
        str | None,
        Field(description="Partial (LIKE) match on the program name hint column."),
    ] = None,
    recipient_houjin_bangou: Annotated[
        str | None,
        Field(
            description=(
                "13-digit 法人番号 exact match. **Currently returns 0 rows** — "
                "the column is 100 % NULL across the 1,185 公表分 records because "
                "会計検査院 does not publish 法人番号. Use `q=<company_name>` or "
                "`q=<houjin_bangou_digits>` (substring on reason_excerpt / "
                "source_title / program_name_hint) instead. Param retained for "
                "forward-compat once 法人番号 enrichment ships."
            ),
        ),
    ] = None,
    min_improper_grant_yen: Annotated[
        int | None,
        Field(description="Lower bound on amount_improper_grant_yen (JPY)."),
    ] = None,
    max_improper_grant_yen: Annotated[
        int | None,
        Field(description="Upper bound on amount_improper_grant_yen (JPY)."),
    ] = None,
    disclosed_from: Annotated[
        str | None,
        Field(description="Lower bound ISO date (YYYY-MM-DD) on disclosed_date."),
    ] = None,
    disclosed_until: Annotated[
        str | None,
        Field(description="Upper bound ISO date (YYYY-MM-DD) on disclosed_date."),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description=(
                "Max rows. Token-shaping cap = 20 (dd_v3_09 / v7 P3-K); "
                "values above 20 are silently capped with input_warnings. "
                "Default 20."
            ),
            ge=1,
            le=100,
        ),
    ] = 20,
    offset: Annotated[
        int,
        Field(
            description=(
                "Pagination offset (0-based row count to skip). Default 0. "
                "Combine with `limit` for paging through `total`. "
                "Examples: offset=0 (first page), offset=20 (page 2 with limit=20)."
            ),
            ge=0,
        ),
    ] = 0,
    fields: Annotated[
        Literal["minimal", "standard", "full"],
        Field(
            description=(
                "Response shape per row. 'minimal' (default, ~80 B/row): "
                "{case_id, program_name_hint, event_type, source_url}. "
                "'standard': + ministry, prefecture, disclosed_date, "
                "amount_improper_grant_yen, recipient_name, fetched_at. "
                "'full': existing complete row (all amount_* + recipient + "
                "bureau + reason_excerpt + legal_basis + occurred_fiscal_years)."
            ),
        ),
    ] = "minimal",
    as_of: Annotated[
        str,
        Field(
            description=(
                "Disclosure-window pivot (ISO YYYY-MM-DD or 'today'). "
                "Default 'today' (JST). Drops cases whose "
                "disclosed_until has already passed (record removed from "
                "公表 list) and cases not yet disclosed (disclosed_date "
                "in the future). NULL-tolerant on both ends. Pass an "
                "ISO date for historical 公表分 lookups "
                "(`as_of='2024-01-01'`). Echoed in meta.data_as_of."
            ),
            pattern=r"^(today|\d{4}-\d{2}-\d{2})$",
        ),
    ] = "today",
) -> dict[str, Any]:
    """RISK: 会計検査院 (Board of Audit) の不正・不当請求事例を検索する — 1,185 historical findings of improper 補助金 handling (over-payment / 目的外使用 / eligibility failure / documentation defects). Spread across METI / MAFF / 国交省 / 厚労省; not available as a queryable list in any single public site. Essential for 不正 detection, due-diligence, and 詐欺 prevention before advising a client on a program or counterparty with prior clawback history.

    Typical queries:
      - "法人 XXX に過去の不正受給・返還命令はある?" (use `q=<company_name>` or `q=<13-digit houjin_bangou>` — the dedicated `recipient_houjin_bangou` column is NULL across all 1,185 rows because 会計検査院 does not publish 法人番号)
      - "事業再構築補助金で過去に不正還付された事例は?"
      - "農水省管轄で最も大きい不当請求額は?"

    Ordered by disclosed_date DESC (most recent first), then case_id for stability.

    Empty results on `q=<company_name_or_houjin_digits>` should be cited as
    "会計検査院 公表分では見当たらず" — not as "clean record". Private-sector
    audits, in-progress investigations, and 不起訴 cases are not in scope.

    WHEN NOT:
      - `search_programs` instead if the user asks about the *program definition*, not 不正事例 ("雇用調整助成金 is a program; 雇用調整助成金 不正受給 事例 is an enforcement case").
      - `search_case_studies` instead for 採択 (successful adoption), which is the *opposite* signal.
      - `list_exclusion_rules` instead for 併給禁止 ルール — different dataset, different question.

    LIMITATIONS:
      - `recipient_houjin_bangou` is **100 % NULL** in the current dataset — 会計検査院 公表分 does not publish 法人番号. Filtering by this field returns 0 rows. Use `q=<company_name>` or `q=<houjin_bangou_digits>` instead (both hit source_title / reason_excerpt / program_name_hint substring).
      - Dataset covers only **会計検査院 公表分** (annual 検査報告 + 随時報告). Private-sector audits, in-progress investigations, and 不起訴 cases are not included. "No hits" must be cited as "会計検査院 公表分では見当たらず", not "clean record".
      - `ministry` uses the current ministry name; ministry restructures (e.g. 旧 通産省 → 経産省) are collapsed to the post-reform label. Historical queries should search `q=<bureau>` instead.
      - `disclosed_date` granularity is **year+quarter** for many rows (e.g. 2023-03-31 is a placeholder for "FY2022 検査報告"); do not treat as a precise incident date.
      - `as_of` (default 'today' JST) drops cases whose `disclosed_until` is past (公表 から外れた古い事例) and cases whose `disclosed_date` is future. NULL columns pass the filter. For historical 公表分 lookups pass an ISO date. `meta.data_as_of` echoes the resolved date.

    CHAIN:
      → `get_enforcement_case(case_id=…)` for the full record + legal_basis + bureau.
      → `search_programs(q=program_name_hint)` to find the current active program referenced in the case.

    `fields` controls response size per row (see param description). Default
    is 'minimal' (token-shaping per dd_v3_09 / v7 P3-K) — pass `fields='full'`
    when the audit detail (amount_*, reason_excerpt, legal_basis) is needed.
    """
    # === S3 HTTP FALLBACK ===
    _fb = _fallback_call(
        "search_enforcement_cases",
        rest_path="/v1/enforcement-cases/search",
        params={
            "q": q,
            "event_type": event_type,
            "ministry": ministry,
            "prefecture": prefecture,
            "legal_basis": legal_basis,
            "program_name_hint": program_name_hint,
            "recipient_houjin_bangou": recipient_houjin_bangou,
            "min_improper_grant_yen": min_improper_grant_yen,
            "max_improper_grant_yen": max_improper_grant_yen,
            "disclosed_from": disclosed_from,
            "disclosed_until": disclosed_until,
            "limit": limit,
            "offset": offset,
            "fields": fields,
            "as_of": as_of,
        },
    )
    if _fb is not None:
        return _fb
    # === END S3 HTTP FALLBACK ===
    fields = _resolve_shaped_fields(fields)
    limit = max(1, min(100, limit))
    limit, limit_warnings = _enforce_limit_cap(limit, cap=20)
    offset = max(0, offset)

    # Resolve as_of → ISO date.
    as_of_iso = _jst_today_iso() if (not as_of or as_of == "today") else as_of

    where: list[str] = []
    params: list[Any] = []

    if q:
        like = f"%{q}%"
        where.append(
            "(program_name_hint LIKE ? OR reason_excerpt LIKE ? OR source_title LIKE ?)"
        )
        params.extend([like, like, like])
    if event_type:
        where.append("event_type = ?")
        params.append(event_type)
    if ministry:
        where.append("ministry = ?")
        params.append(ministry)
    pref_raw = prefecture
    prefecture = _normalize_prefecture(prefecture)
    # BUG-2 fix: warn on unknown prefecture, drop filter so we don't silently
    # match 0 rows on a typo like 'Tokio' / '東京府' (¥3/req refund trap).
    input_warnings: list[dict[str, Any]] = []
    if pref_raw and not _is_known_prefecture(pref_raw):
        input_warnings.append({
            "field": "prefecture",
            "code": "unknown_prefecture",
            "value": pref_raw,
            "normalized_to": prefecture,
            "message": (
                f"prefecture={pref_raw!r} は正規の都道府県に一致せず。"
                "フィルタを無効化し全国ベースで返しました。正しい例: '東京' / '東京都' / 'Tokyo'。"
            ),
            "retry_with": ["enum_values(field='prefecture')"],
        })
        prefecture = None
    if prefecture:
        where.append("prefecture = ?")
        params.append(prefecture)
    if legal_basis:
        where.append("legal_basis LIKE ?")
        params.append(f"%{legal_basis}%")
    if program_name_hint:
        where.append("program_name_hint LIKE ?")
        params.append(f"%{program_name_hint}%")
    if recipient_houjin_bangou:
        where.append("recipient_houjin_bangou = ?")
        params.append(recipient_houjin_bangou)
    if min_improper_grant_yen is not None:
        where.append("amount_improper_grant_yen >= ?")
        params.append(min_improper_grant_yen)
    if max_improper_grant_yen is not None:
        where.append("amount_improper_grant_yen <= ?")
        params.append(max_improper_grant_yen)
    if disclosed_from:
        where.append("disclosed_date >= ?")
        params.append(disclosed_from)
    if disclosed_until:
        where.append("disclosed_date <= ?")
        params.append(disclosed_until)

    # as_of filter: keep cases that are within their public disclosure window
    # at as_of_iso. NULL-tolerant on both ends — many rows lack one or both
    # date fields. dd_v4_08 / v8 P3-L: backward-compat-breaking (default
    # shifts from "all 公表分" to "現在 公表中") accepted as 詐欺 risk
    # mitigation (returning withdrawn 公表 with no caveat is a 景表法 risk).
    where.append(
        "(disclosed_date IS NULL OR disclosed_date <= ?) "
        "AND (disclosed_until IS NULL OR disclosed_until >= ?)"
    )
    params.extend([as_of_iso, as_of_iso])

    where_sql = " AND ".join(where) if where else "1=1"

    conn = connect()
    try:
        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM enforcement_cases WHERE {where_sql}", params
        ).fetchone()
        rows = conn.execute(
            f"""SELECT * FROM enforcement_cases
                WHERE {where_sql}
                ORDER BY
                    COALESCE(disclosed_date, '') DESC,
                    case_id
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
        results = [
            _trim_enforcement_fields(_row_to_enforcement_case(r), fields)
            for r in rows
        ]
        payload: dict[str, Any] = {
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": results,
            "meta": {"data_as_of": as_of_iso},
            "retrieval_note": (
                f"Filtered for active items as of {as_of_iso} JST "
                "(rows with NULL disclosed_date / disclosed_until are kept)."
            ),
        }
        if input_warnings or limit_warnings:
            payload["input_warnings"] = input_warnings + limit_warnings
        if total == 0:
            payload["hint"] = _empty_enforcement_hint(
                prefecture, ministry, event_type, recipient_houjin_bangou
            )
            payload["retry_with"] = ["search_programs", "search_case_studies"]
        return payload
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def get_enforcement_case(
    case_id: Annotated[
        str,
        Field(description="case_id from search_enforcement_cases results."),
    ],
) -> dict[str, Any]:
    """DETAIL: 会計検査院 不正・不当請求事例 1 件の詳細を取得する (fetch one enforcement case). Returns full record: event_type, ministry, recipient (name + 法人番号 + kind), bureau, prefecture, occurred_fiscal_years, all amount_* fields (improper_grant / project_cost / grant_paid), reason_excerpt, legal_basis, source_url, disclosed_date.

    Example:
        get_enforcement_case(case_id="ENF-2024-METI-0123")
        → {"case_id": "ENF-2024-METI-0123", "event_type": "improper_grant",
           "ministry": "経産省", "recipient_name": "...", "amount_improper_grant_yen": 12000000,
           "reason_excerpt": "...", "source_url": "..."}

    When NOT to call:
        - Without a case_id → use search_enforcement_cases / check_enforcement_am first.
        - For 補助金 program definition → use get_program (this returns audit findings).
        - For 判例 / court rulings → use get_court_decision (different table).
        - To screen a 法人 across all enforcement → use check_enforcement_am(houjin_bangou).

    CHAIN:
      ← `search_enforcement_cases` produces the case_id.
      → `search_programs(q=program_name_hint)` to cross-reference the current form of the program named in the case.
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM enforcement_cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        if row is None:
            return {
                "error": f"enforcement case not found: {case_id}",
                "code": "no_matching_records",
                "hint": "case_id は search_enforcement_cases の results[].case_id をそのまま渡してください.",
            }
        return _row_to_enforcement_case(row)
    finally:
        conn.close()


def _row_to_case_study(row: sqlite3.Row) -> dict[str, Any]:
    """Mirror of api/case_studies.py::_row_to_case_study — decodes the three
    JSON columns and bool-casts is_sole_proprietor. Kept local to keep this
    module import-safe without the FastAPI layer.
    """
    sole_raw = row["is_sole_proprietor"]
    is_sole: bool | None = None if sole_raw is None else bool(sole_raw)

    def _list_col(col: str) -> list[str]:
        raw = row[col]
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(parsed, list):
            return []
        return [str(x) for x in parsed if x is not None]

    def _any_col(col: str) -> Any:
        raw = row[col]
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    return {
        "case_id": row["case_id"],
        "company_name": row["company_name"],
        "houjin_bangou": row["houjin_bangou"],
        "is_sole_proprietor": is_sole,
        "prefecture": row["prefecture"],
        "municipality": row["municipality"],
        "industry_jsic": row["industry_jsic"],
        "industry_name": row["industry_name"],
        "employees": row["employees"],
        "founded_year": row["founded_year"],
        "capital_yen": row["capital_yen"],
        "case_title": row["case_title"],
        "case_summary": row["case_summary"],
        "programs_used": _list_col("programs_used_json"),
        "total_subsidy_received_yen": row["total_subsidy_received_yen"],
        "outcomes": _any_col("outcomes_json"),
        "patterns": _any_col("patterns_json"),
        "publication_date": row["publication_date"],
        "source_url": row["source_url"],
        "source_excerpt": row["source_excerpt"],
        "fetched_at": row["fetched_at"],
        "confidence": row["confidence"],
    }


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def search_case_studies(
    q: Annotated[
        str | None,
        Field(
            description=(
                "Free-text LIKE across company_name + case_title + "
                "case_summary + source_excerpt."
            ),
        ),
    ] = None,
    prefecture: Annotated[
        PrefectureParam,
        Field(
            description=(
                "都道府県 closed-set ('東京都'/'北海道'/'全国' 等 48 値). "
                "短縮形・romaji 自動正規化、未知値は invalid_enum で拒否。"
            ),
        ),
    ] = None,
    industry_jsic: Annotated[
        str | None,
        Field(
            description=(
                "JSIC 日本標準産業分類 prefix match. 'A' = 農林水産業, "
                "'05' = 食料品製造業, 'I' = 卸売・小売業, etc."
            ),
        ),
    ] = None,
    houjin_bangou: Annotated[
        str | None,
        Field(
            description=(
                "13-digit 法人番号 exact match. "
                "NOTE: only ~19 % of case studies carry 法人番号 (427 / 2,286) — "
                "most 採択 announcements publish 社名 only. Fall back to `q=<company_name>` when this returns 0."
            ),
        ),
    ] = None,
    program_used: Annotated[
        str | None,
        Field(
            description=(
                "Substring over programs_used_json. Pass the program **name** "
                "(e.g. 'IT導入補助金', 'BCP策定のためのコンサルタント派遣制度') — "
                "the column stores names, not unified_ids. "
                "Resolve name via `get_program(unified_id=…).primary_name` when you only have an ID."
            ),
        ),
    ] = None,
    min_subsidy_yen: Annotated[
        int | None,
        Field(
            description=(
                "Lower bound on total_subsidy_received_yen (JPY). "
                "WARNING: this column is populated in <1% of rows (ministries rarely publish 交付額 with 採択) — "
                "applying this filter silently drops ~99% of matches. Prefer leaving None and reading the amount per row."
            ),
        ),
    ] = None,
    max_subsidy_yen: Annotated[
        int | None,
        Field(
            description=(
                "Upper bound on total_subsidy_received_yen (JPY). "
                "WARNING: same <1% sparsity as min_subsidy_yen — avoid unless the user explicitly asked for an amount ceiling."
            ),
        ),
    ] = None,
    min_employees: Annotated[
        int | None,
        Field(
            ge=0,
            description=(
                "Inclusive lower bound on employees (人数). NULL = 下限なし. "
                "WARNING: employees is populated in <30% of rows — applying "
                "this filter silently drops rows where the count is unknown. "
                "例: min_employees=10 で 10 名以上のみ."
            ),
        ),
    ] = None,
    max_employees: Annotated[
        int | None,
        Field(
            ge=0,
            description=(
                "Inclusive upper bound on employees (人数). NULL = 上限なし. "
                "Same <30% sparsity caveat as min_employees. "
                "例: max_employees=300 で中堅以下に絞る (中小企業基本法基準と整合)."
            ),
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description=(
                "Max rows. Token-shaping cap = 20 (dd_v3_09 / v7 P3-K); "
                "values above 20 are silently capped with input_warnings. "
                "Default 20."
            ),
            ge=1,
            le=100,
        ),
    ] = 20,
    offset: Annotated[
        int,
        Field(description="Pagination offset (0-based row count to skip). Default 0. Combine with `limit` to page through `total`. 例: offset=20 で limit=20 なら 2 ページ目.", ge=0),
    ] = 0,
    fields: Annotated[
        Literal["minimal", "standard", "full"],
        Field(
            description=(
                "Response shape per row. 'minimal' (default, ~80 B/row): "
                "{case_id, company_name, case_title, source_url}. "
                "'standard': + prefecture, industry_jsic, industry_name, "
                "publication_date, total_subsidy_received_yen, fetched_at. "
                "'full': existing complete row (recipient profile + outcomes "
                "+ patterns + programs_used)."
            ),
        ),
    ] = "minimal",
) -> dict[str, Any]:
    """EVIDENCE: 採択事例 (recipient profiles paired with programs actually received) を検索する — 2,286 records covering Jグランツ 採択結果 + mirasapo 事業事例 + 都道府県 事例集. The Jグランツ 公開 API does not expose adoption history; cross-ministry aggregation here normally requires hand-crawling ministry PDFs. Each record has company_name + 法人番号 + prefecture + JSIC 業種 + employees + programs received + 受給額.

    **Use this** when the user wants "proof that a business like mine actually
    got this" — recipient profile matching, benchmarking, social proof.
    **Use `search_programs` instead** for policy definitions (eligibility,
    amount, window). Do not conflate the two: search_programs returns policy
    text, search_case_studies returns real recipients.

    Typical queries:
      - "うちと同じ規模・業種で採択された会社はある?"
      - "事業再構築補助金で採択された北海道の中小企業は?"
      - "この法人 (法人番号 XXX) はどの補助金を受給してる?"

    Ordered by publication_date DESC (most recent first), case_id for stability.

    WHEN NOT:
      - `search_programs` instead for policy text (eligibility / amount / window).
      - `search_enforcement_cases` instead for 不正 / 返還 (opposite signal — this tool returns successful adoption, that one returns clawbacks).
      - `search_loan_programs` instead for 融資 products — this table is grant-only.
      - `enum_values(field="programs_used")` *first* when unsure which program_used string will match — only 35 distinct values exist (all raw names, no unified_ids).

    LIMITATIONS:
      - `houjin_bangou` is populated on ~19 % of rows (mostly 事業再構築 + ものづくり disclosures). Filtering by it will miss ~81 % of records; fall back to `q=<company_name>` when houjin lookup returns 0.
      - `total_subsidy_received_yen` is sparsely populated (<1 % of rows) — ministries publish 採択 without amounts. Do not rely on 金額 filters; surface the number only when present and omit the filter otherwise.
      - `programs_used` stores **raw program names** (not `unified_id`). Names drift year-over-year (e.g. "ものづくり・商業・サービス生産性向上促進補助金" ≠ "ものづくり補助金"). Use `enum_values(field="programs_used")` to see exact stored strings.
      - `is_sole_proprietor` is nullable. `NULL` ≠ "not a sole proprietor" — it means unknown. Treat the filter tri-value: true / false / unknown.
      - Source ratio is ~70 % Jグランツ 採択結果 (機械的) + ~30 % 都道府県 / mirasapo 事業事例 (文章). Text-search hits (`q=`) on the latter give softer match quality than houjin / industry filters.

    CHAIN:
      → `get_case_study(case_id=…)` for full recipient detail (outcomes, patterns, summary).
      → `search_programs(q=programs_used[i])` to pull the current form of the program the recipient used.
      → `search_enforcement_cases(q=<company_name>)` to run a 詐欺 / 不正 check on the same 法人 — `recipient_houjin_bangou` on the enforcement table is 100 % NULL, so search by name/digits in `q` instead.

    `fields` controls response size per row (see param description). Default
    is 'minimal' (token-shaping per dd_v3_09 / v7 P3-K) — call sites that need
    the full recipient profile must pass `fields='full'`.
    """
    # === S3 HTTP FALLBACK ===
    _fb = _fallback_call(
        "search_case_studies",
        rest_path="/v1/case-studies/search",
        params={
            "q": q,
            "prefecture": prefecture,
            "industry_jsic": industry_jsic,
            "houjin_bangou": houjin_bangou,
            "program_used": program_used,
            "min_subsidy_yen": min_subsidy_yen,
            "max_subsidy_yen": max_subsidy_yen,
            "min_employees": min_employees,
            "max_employees": max_employees,
            "limit": limit,
            "offset": offset,
            "fields": fields,
        },
    )
    if _fb is not None:
        return _fb
    # === END S3 HTTP FALLBACK ===
    fields = _resolve_shaped_fields(fields)
    limit = max(1, min(100, limit))
    limit, limit_warnings = _enforce_limit_cap(limit, cap=20)
    offset = max(0, offset)

    where: list[str] = []
    params: list[Any] = []

    if q:
        like = f"%{q}%"
        where.append(
            "(COALESCE(company_name,'') LIKE ? "
            "OR COALESCE(case_title,'') LIKE ? "
            "OR COALESCE(case_summary,'') LIKE ? "
            "OR COALESCE(source_excerpt,'') LIKE ?)"
        )
        params.extend([like, like, like, like])
    pref_raw = prefecture
    prefecture = _normalize_prefecture(prefecture)
    # BUG-2 fix: warn on unknown prefecture, drop filter so we don't silently
    # match 0 rows on a typo like 'Tokio' / '東京府' (¥3/req refund trap).
    input_warnings: list[dict[str, Any]] = []
    if pref_raw and not _is_known_prefecture(pref_raw):
        input_warnings.append({
            "field": "prefecture",
            "code": "unknown_prefecture",
            "value": pref_raw,
            "normalized_to": prefecture,
            "message": (
                f"prefecture={pref_raw!r} は正規の都道府県に一致せず。"
                "フィルタを無効化し全国ベースで返しました。正しい例: '東京' / '東京都' / 'Tokyo'。"
            ),
            "retry_with": ["enum_values(field='prefecture')"],
        })
        prefecture = None
    if prefecture:
        where.append("prefecture = ?")
        params.append(prefecture)
    industry_jsic = _normalize_industry_jsic(industry_jsic)
    if industry_jsic:
        where.append("industry_jsic LIKE ?")
        params.append(f"{industry_jsic}%")
    if houjin_bangou:
        where.append("houjin_bangou = ?")
        params.append(houjin_bangou)
    if program_used:
        where.append("programs_used_json LIKE ?")
        params.append(f"%{program_used}%")
    if min_subsidy_yen is not None:
        where.append("total_subsidy_received_yen >= ?")
        params.append(min_subsidy_yen)
    if max_subsidy_yen is not None:
        where.append("total_subsidy_received_yen <= ?")
        params.append(max_subsidy_yen)
    if min_employees is not None:
        where.append("employees >= ?")
        params.append(min_employees)
    if max_employees is not None:
        where.append("employees <= ?")
        params.append(max_employees)

    where_sql = " AND ".join(where) if where else "1=1"

    conn = connect()
    try:
        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM case_studies WHERE {where_sql}", params
        ).fetchone()
        rows = conn.execute(
            f"""SELECT * FROM case_studies
                WHERE {where_sql}
                ORDER BY
                    COALESCE(publication_date, '') DESC,
                    case_id
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
        results = [
            _trim_case_study_fields(_row_to_case_study(r), fields) for r in rows
        ]
        payload: dict[str, Any] = {
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": results,
        }
        if input_warnings or limit_warnings:
            payload["input_warnings"] = input_warnings + limit_warnings
        if total == 0:
            payload["hint"] = _empty_case_studies_hint(
                prefecture, industry_jsic, houjin_bangou, program_used
            )
            payload["retry_with"] = ["search_programs", "search_loan_programs"]
        return payload
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def get_case_study(
    case_id: Annotated[
        str,
        Field(description="case_id from search_case_studies (e.g. 'mirasapo_case_118')."),
    ],
) -> dict[str, Any]:
    """DETAIL: 採択事例 1 件の完全詳細を取得する (fetch one case study). Returns full record: recipient profile (company_name, 法人番号, prefecture, industry_jsic, employees, founded_year, capital_yen), case_title / case_summary, programs_used (list of 受給した補助金), subsidy amount, outcomes / patterns (JSON), source_url + publication_date.

    WHEN NOT:
      - `search_case_studies` instead if you don't have a case_id yet.
      - `get_program` instead for program policy detail — this returns recipient profile, not policy text.

    CHAIN:
      ← `search_case_studies` produces the case_id.
      → `search_programs(q=programs_used[i])` to resolve each program the recipient used to its current definition.
      → `search_enforcement_cases(q=<company_name>)` for an integrity check on the same 法人 — `recipient_houjin_bangou` on the enforcement table is 100 % NULL, so search by name/13-digit substring in `q` instead.
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM case_studies WHERE case_id = ?", (case_id,)
        ).fetchone()
        if row is None:
            return {
                "error": f"case study not found: {case_id}",
                "code": "no_matching_records",
                "hint": "case_id は search_case_studies の results[].case_id をそのまま渡してください.",
            }
        return _row_to_case_study(row)
    finally:
        conn.close()


_LOAN_RISK_VALUES = ("required", "not_required", "negotiable", "unknown")


def _row_to_loan_program(row: sqlite3.Row) -> dict[str, Any]:
    """Mirror of api/loan_programs.py::_row_to_loan."""
    return {
        "id": row["id"],
        "program_name": row["program_name"],
        "provider": row["provider"],
        "loan_type": row["loan_type"],
        "amount_max_yen": row["amount_max_yen"],
        "loan_period_years_max": row["loan_period_years_max"],
        "grace_period_years_max": row["grace_period_years_max"],
        "interest_rate_base_annual": row["interest_rate_base_annual"],
        "interest_rate_special_annual": row["interest_rate_special_annual"],
        "rate_names": row["rate_names"],
        "security_required": row["security_required"],
        "target_conditions": row["target_conditions"],
        "official_url": row["official_url"],
        "source_excerpt": row["source_excerpt"],
        "fetched_at": row["fetched_at"],
        "confidence": row["confidence"],
        "collateral_required": row["collateral_required"],
        "personal_guarantor_required": row["personal_guarantor_required"],
        "third_party_guarantor_required": row["third_party_guarantor_required"],
        "security_notes": row["security_notes"],
    }


_LoanRiskT = Literal["required", "not_required", "negotiable", "unknown"]


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def search_loan_programs(
    q: Annotated[
        str | None,
        Field(description="Free-text LIKE across program_name + provider + target_conditions."),
    ] = None,
    provider: Annotated[
        str | None,
        Field(
            description=(
                "Exact match on lender. Common: '日本政策金融公庫', '東京都', "
                "'大阪府', '商工組合中央金庫', '信用保証協会'."
            ),
        ),
    ] = None,
    loan_type: Annotated[
        str | None,
        Field(
            description=(
                "Exact match. Common: '運転資金', '設備資金', '創業融資', "
                "'経営改善資金', '災害復旧'."
            ),
        ),
    ] = None,
    collateral_required: Annotated[
        _LoanRiskT | None,
        Field(
            description=(
                "担保 requirement. 'required' (担保必須), 'not_required' "
                "(無担保可), 'negotiable' (相談), 'unknown' (要綱に記載なし)."
            ),
        ),
    ] = None,
    personal_guarantor_required: Annotated[
        _LoanRiskT | None,
        Field(
            description=(
                "個人保証人 (代表者保証) requirement. Same 4 values as "
                "collateral_required."
            ),
        ),
    ] = None,
    third_party_guarantor_required: Annotated[
        _LoanRiskT | None,
        Field(
            description=(
                "第三者保証人 (代表者以外の保証人) requirement. Same 4 values."
            ),
        ),
    ] = None,
    min_amount_yen: Annotated[
        int | None,
        Field(description="Lower bound on amount_max_yen (JPY)."),
    ] = None,
    max_amount_yen: Annotated[
        int | None,
        Field(description="Upper bound on amount_max_yen (JPY)."),
    ] = None,
    max_interest_rate: Annotated[
        float | None,
        Field(description="Upper bound on interest_rate_base_annual (e.g. 0.015 = 1.5%)."),
    ] = None,
    min_loan_period_years: Annotated[
        int | None,
        Field(description="Minimum loan_period_years_max."),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Max rows. Clamped to [1, 100]. Default 20.", ge=1, le=100),
    ] = 20,
    offset: Annotated[
        int,
        Field(description="Pagination offset (0-based row count to skip). Default 0. Combine with `limit` to page through `total`. 例: offset=20 で limit=20 なら 2 ページ目.", ge=0),
    ] = 0,
) -> dict[str, Any]:
    """DISCOVER: 無担保・無保証 の融資を 1 クエリで抽出する — 108 日本の融資プログラム (日本政策金融公庫 / 自治体融資 / 信用金庫 etc.) with three-axis risk filters. Headline feature: 担保 (collateral) / 個人保証人 (personal guarantor) / 第三者保証人 (third-party guarantor) are each a **separate enum axis** — "無担保・無個人保証" filtering is one query, not multi-turn natural-language parsing of each provider's prose. No single public site offers this 融資 decomposition.

    Typical queries:
      - "無担保・無個人保証で通せる公庫融資は?"
      - "運転資金で金利 1.5% 以下・5000万以上の融資は?"
      - "10 年返済可能な設備資金融資は?"

    Example filter combination for 無担保・無保証人:

        collateral_required="not_required" AND
        third_party_guarantor_required="not_required"

    Each axis value is one of: required | not_required | negotiable | unknown.
    Invalid values return an envelope with code='invalid_enum' + hint (not silent-fail).

    Ordered by amount_max_yen DESC, id. limit clamped to [1, 100]; default 20.

    WHEN NOT:
      - `search_programs` instead for 補助金 / 助成金 / 税制 (this table is 融資 only — 108 rows).
      - `search_enforcement_cases` instead for 不正 / 返還 against a lender or borrower.
      - `enum_values(field="loan_type"|"provider")` *first* if unsure which loan_type / provider strings are canonical.

    LIMITATIONS:
      - Coverage is 108 rows: 日本政策金融公庫 (国民 + 中小) + 信用保証協会 + 自治体制度融資 + 主要信金. **Commercial-bank proprietary loans** (メガバンク プロパー融資, 地銀 事業融資) are not indexed — providers keep conditions in branch-level discretion, not published schedules.
      - **No prefecture filter.** 自治体 rows mention the 自治体 in `provider` / `program_name` / `target_conditions` — use `q=<都道府県名>` or `provider=<自治体名>` for regional filtering.
      - `personal_guarantor_required="not_required"` typically means 2024-04 以降 公庫 原則不要 ルール applied; confirm against the lender's current 要項 because 保証料 / 信用保証 料率 is priced separately and not surfaced here.
      - `interest_rate_base` is the **base rate**; `interest_rate_special` covers 特別利率 tiers. The lender's actual offer depends on 信用 / 担保 / 期間, which the table records only as target_conditions text.
      - Every 3-axis value can be `unknown` when the 要綱 is silent. Treat `unknown` as "調査必要", not as a permissive default — 不記載 in 要綱 often means 原則 required.

    CHAIN:
      → `get_loan_program(loan_id=…)` for the full record (target_conditions, official_url, lineage).
      → `search_programs(q=…)` to compare against 補助金 options for the same purpose (借入 vs 補助金 decision).
    """
    # === S3 HTTP FALLBACK ===
    _fb = _fallback_call(
        "search_loan_programs",
        rest_path="/v1/loan-programs/search",
        params={
            "q": q,
            "provider": provider,
            "loan_type": loan_type,
            "collateral_required": collateral_required,
            "personal_guarantor_required": personal_guarantor_required,
            "third_party_guarantor_required": third_party_guarantor_required,
            "min_amount_yen": min_amount_yen,
            "max_amount_yen": max_amount_yen,
            "max_interest_rate": max_interest_rate,
            "min_loan_period_years": min_loan_period_years,
            "limit": limit,
            "offset": offset,
        },
    )
    if _fb is not None:
        return _fb
    # === END S3 HTTP FALLBACK ===
    # Defense-in-depth validation (Literal already enforces this at the
    # pydantic layer, but older MCP clients that bypass schema coercion
    # would otherwise fail with an opaque SQL error).
    for name, val in (
        ("collateral_required", collateral_required),
        ("personal_guarantor_required", personal_guarantor_required),
        ("third_party_guarantor_required", third_party_guarantor_required),
    ):
        if val is not None and val not in _LOAN_RISK_VALUES:
            return {
                "total": 0, "limit": limit, "offset": offset, "results": [],
                "error": {
                    "code": "invalid_enum",
                    "message": f"{name} must be one of {list(_LOAN_RISK_VALUES)}, got {val!r}",
                    "hint": (
                        "Each 3-axis value is: required | not_required | "
                        "negotiable | unknown. Pass 'unknown' to skip the axis."
                    ),
                    "retry_with": [f"search_loan_programs ({name}='unknown')"],
                },
            }

    limit = max(1, min(100, limit))
    offset = max(0, offset)

    where: list[str] = []
    params: list[Any] = []

    if q:
        like = f"%{q}%"
        where.append(
            "(COALESCE(program_name,'') LIKE ? "
            "OR COALESCE(provider,'') LIKE ? "
            "OR COALESCE(target_conditions,'') LIKE ?)"
        )
        params.extend([like, like, like])
    if provider:
        where.append("provider = ?")
        params.append(provider)
    if loan_type:
        where.append("loan_type = ?")
        params.append(loan_type)
    for col, val in (
        ("collateral_required", collateral_required),
        ("personal_guarantor_required", personal_guarantor_required),
        ("third_party_guarantor_required", third_party_guarantor_required),
    ):
        if val is None:
            continue
        where.append(f"{col} = ?")
        params.append(val)
    if min_amount_yen is not None:
        where.append("amount_max_yen >= ?")
        params.append(min_amount_yen)
    if max_amount_yen is not None:
        where.append("amount_max_yen <= ?")
        params.append(max_amount_yen)
    if max_interest_rate is not None:
        where.append("interest_rate_base_annual <= ?")
        params.append(max_interest_rate)
    if min_loan_period_years is not None:
        where.append("loan_period_years_max >= ?")
        params.append(min_loan_period_years)

    where_sql = " AND ".join(where) if where else "1=1"

    conn = connect()
    try:
        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM loan_programs WHERE {where_sql}", params
        ).fetchone()
        rows = conn.execute(
            f"""SELECT * FROM loan_programs
                WHERE {where_sql}
                ORDER BY
                    COALESCE(amount_max_yen, 0) DESC,
                    id
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
        payload: dict[str, Any] = {
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": [_row_to_loan_program(r) for r in rows],
        }
        if total == 0:
            payload["hint"] = _empty_loan_hint(provider, loan_type)
            payload["retry_with"] = ["search_programs", "search_enforcement_cases"]
        return payload
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def get_loan_program(
    loan_id: Annotated[
        int,
        Field(description="Numeric id from search_loan_programs results."),
    ],
) -> dict[str, Any]:
    """DETAIL: 融資プログラム 1 件の詳細を取得する (fetch one 融資 program by numeric id). Returns full record including three-axis risk (担保 / 個人保証人 / 第三者保証人), interest rates (base + special), loan period, grace period, target_conditions, official_url + fetched_at lineage, and the legacy security_required free-text kept for audit.

    Example:
        get_loan_program(loan_id=42)
        → {"id": 42, "loan_program_name": "...", "collateral_required": "条件付",
           "personal_guarantor_required": "不要", "interest_rate_base": "1.50%", ...}

    When NOT to call:
        - Without a numeric loan_id → use search_loan_programs / search_loans_am first.
        - For 補助金 / 助成金 detail → use get_program (this table is 融資 only).
        - For 信用保証協会 enforcement / 取消 → use get_enforcement_case instead.
        - To screen co-applicable subsidies → use subsidy_combo_finder, not this.

    CHAIN:
      ← `search_loan_programs` produces the loan_id.
      → `search_programs(q=loan_program_name)` to find co-applicable 補助金 that pair with this loan.
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM loan_programs WHERE id = ?", (loan_id,)
        ).fetchone()
        if row is None:
            return {
                "error": f"loan program not found: {loan_id}",
                "code": "no_matching_records",
                "hint": "loan_id は search_loan_programs の results[].id をそのまま渡してください.",
            }
        return _row_to_loan_program(row)
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def prescreen_programs(
    prefecture: Annotated[
        PrefectureParam,
        Field(
            description=(
                "Caller's prefecture (closed-set 48 値). Accepts canonical ('東京都'), short ('東京'), "
                "or romaji ('Tokyo') — auto-normalized. Unknown values raise invalid_enum. "
                "Use None or '全国' to skip — you'll still get national programs."
            )
        ),
    ] = None,
    industry_jsic: Annotated[
        str | None,
        Field(
            description=(
                "JSIC 大分類 letter (A..T). Accepts JP ('製造業'/'農業'). "
                "Used for hints only in v1."
            )
        ),
    ] = None,
    is_sole_proprietor: Annotated[
        bool | None,
        Field(
            description=(
                "True = 個人事業主. False = 法人 (株式会社/合同会社/組合 etc.). "
                "None = unspecified."
            )
        ),
    ] = None,
    employee_count: Annotated[
        int | None,
        Field(
            ge=0,
            le=100000,
            description=(
                "Total employee headcount (常時雇用 + パート 込み, 役員除く). "
                "Used to gate 中小企業 / 小規模事業者 fitness for amount-tier "
                "and applicant-type matching. Range 0-100000. None = skip."
            ),
        ),
    ] = None,
    revenue_yen: Annotated[
        int | None,
        Field(
            ge=0,
            description=(
                "Annual revenue in **JPY (NOT 万円)**. e.g. 50,000,000 円 = "
                "5千万円, NOT 5,000. Used for 中小企業基本法 size classification + "
                "amount-tier suitability. None = skip filter."
            ),
        ),
    ] = None,
    founded_year: Annotated[
        int | None,
        Field(
            ge=1800,
            le=2100,
            description=(
                "Year company / sole-proprietor was founded (西暦, 4-digit). "
                "Used for 創業 / 新規 / 第二創業 程度判定 (e.g. 創業5年以内). "
                "Range 1800-2100. None = skip."
            ),
        ),
    ] = None,
    planned_investment_man_yen: Annotated[
        float | None,
        Field(
            ge=0,
            description=(
                "Planned project cost in 万円 (NOT 円). Programs whose "
                "amount_max_man_yen is below this are flagged 'undersized'."
            ),
        ),
    ] = None,
    houjin_bangou: Annotated[
        str | None,
        Field(
            description=(
                "13-digit 国税庁 法人番号. Identity only — not used for matching in v1."
            ),
            max_length=13,
        ),
    ] = None,
    declared_certifications: Annotated[
        list[str] | None,
        Field(
            description=(
                "Certifications the caller holds (e.g., '認定新規就農者', "
                "'認定農業者', '経営革新計画承認'). Suppresses 'prerequisite-missing' caveats."
            )
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=50,
            description=(
                "返却する候補制度の最大件数. Range [1, 50]. Default 10. "
                "fit_score 降順で上位 N 件を返す. 50 超は le で拒否."
            ),
        ),
    ] = 10,
) -> dict[str, Any]:
    """DISCOVER-JUDGE: profile → ranked eligible programs (fit-based discovery, NOT keyword search).

    Complements search_programs: search = "find programs mentioning X", prescreen = "find programs I
    plausibly fit, ranked by fit, with reasons + caveats". Use this first when the caller describes
    a business ("茨城 5ha 稲作 個人事業主、8000万円の設備投資予定"); use search_programs when the
    caller names a known program or theme ("IT導入補助金").

    Each row returns:
      - fit_score: positive-match count in v1 (0..~5). Compare within one response only.
      - match_reasons[]: why the row scored (prefecture match, target_type match, amount sufficiency).
      - caveats[]: missing prerequisites, undersized amount, or tagging gaps.

    LIMITATIONS:
      - v1 does not enforce exclusion_rules `exclude`/`combine_ok` — those need an
        'applying_for' list we don't accept yet. Use `check_exclusions` on pairs you plan to apply.
      - target_types has EN/JP drift in the DB. Unrecognized tokens don't penalize rows.

    WHEN NOT:
      - `search_programs(q=…)` for keyword-based discovery.
      - `search_case_studies` for "who like me received X?" social-proof discovery.

    CHAIN:
      → `get_program(unified_id)` for full row of a short-listed match.
      → `check_exclusions(program_a, program_b)` to validate combined-application feasibility.
      → `search_case_studies(prefecture=…, industry_jsic=…)` for adoption evidence of top matches.
    """
    from jpintel_mcp.api.prescreen import PrescreenRequest, run_prescreen

    pref_norm = _normalize_prefecture(prefecture)
    # BUG-2 fix: warn on unknown prefecture, drop filter so prescreen falls
    # back to national candidates instead of silently scoring against a typo.
    input_warnings: list[dict[str, Any]] = []
    if prefecture and not _is_known_prefecture(prefecture):
        input_warnings.append({
            "field": "prefecture",
            "code": "unknown_prefecture",
            "value": prefecture,
            "normalized_to": pref_norm,
            "message": (
                f"prefecture={prefecture!r} は正規の都道府県に一致せず。"
                "フィルタを無効化し全国ベースで返しました。正しい例: '東京' / '東京都' / 'Tokyo'。"
            ),
            "retry_with": ["enum_values(field='prefecture')"],
        })
        pref_norm = None

    profile = PrescreenRequest(
        prefecture=pref_norm,
        industry_jsic=_normalize_industry_jsic(industry_jsic),
        is_sole_proprietor=is_sole_proprietor,
        employee_count=employee_count,
        revenue_yen=revenue_yen,
        founded_year=founded_year,
        planned_investment_man_yen=planned_investment_man_yen,
        houjin_bangou=houjin_bangou,
        declared_certifications=declared_certifications,
        limit=limit,
    )
    conn = connect()
    try:
        result = run_prescreen(conn, profile)
        payload = result.model_dump()
        if input_warnings:
            payload["input_warnings"] = input_warnings
        return payload
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def smb_starter_pack(
    prefecture: Annotated[
        PrefectureParam,
        Field(
            description=(
                "都道府県 closed-set 48 値。`'東京都'` / `'東京'` / `'Tokyo'` 何れもOK (自動正規化)。"
                "未知値は invalid_enum で拒否。`None` / `'全国'` で国の制度のみ。"
            )
        ),
    ] = None,
    industry_jsic: Annotated[
        str | None,
        Field(
            description=(
                "JSIC 大分類 (A..T) もしくは 和名 ('製造業','農業','建設業' 等)。"
                "`jsic` という別名 でも受けます。"
            )
        ),
    ] = None,
    jsic: Annotated[
        str | None,
        Field(description="Alias for `industry_jsic` (LLM が短い名前を選びがち)."),
    ] = None,
    employees: Annotated[
        int | None,
        Field(
            ge=0,
            le=100000,
            description=(
                "従業員数 (パート含む全頭数). 中小企業基本法基準 "
                "(製造業 300 / 卸売 100 / 小売 50 / サービス 100) で "
                "size 推定に使う. `employee_count` 別名も受付. 例: 12, 80, 250."
            ),
        ),
    ] = None,
    employee_count: Annotated[
        int | None,
        Field(
            ge=0,
            le=100000,
            description=(
                "`employees` の別名. LLM が短い名前を選びがちなので両方受付. "
                "両方指定された場合は employees が優先."
            ),
        ),
    ] = None,
    revenue_yen: Annotated[
        int | None,
        Field(ge=0, description="年商 (円)。1.2 億 = 120000000 (NOT 120 NOT 1.2e8-string)."),
    ] = None,
    planned_investment_man_yen: Annotated[
        float | None,
        Field(
            ge=0,
            description=(
                "計画投資額 (万円). 設備 / システム / 研修 / 拠点 等の予算合計. "
                "1 万 = 100,000 円. 例: 500 = 500 万円, 5000 = 5,000 万円. "
                "amount_max_man_yen filter に流用される."
            ),
        ),
    ] = None,
    is_sole_proprietor: Annotated[
        bool | None,
        Field(
            description=(
                "`True` = 個人事業主, `False` = 法人。`None` = 未指定 (候補は法人込で返る)."
            )
        ),
    ] = None,
    limit_per_section: Annotated[
        int,
        Field(
            ge=1,
            le=10,
            description="各セクション (subsidies / loans / tax) の max 件数。default 5。",
        ),
    ] = 5,
) -> dict[str, Any]:
    """ONE-SHOT DISCOVERY: 1 call で SMB 経営者が「今日何できる?」を返す。

    ChatGPT / Claude と同じ感覚の 1-question-1-answer 体験のための primitive。
    `search_programs` → `prescreen_programs` → `search_loan_programs` →
    `search_tax_rules` → `upcoming_deadlines` → `search_enforcement_cases`
    の 6 ツール分を 1 call で返す (≤ 4 KB payload)。

    入力は一般的な企業プロファイル (都道府県 / 業種 / 従業員 / 売上 / 投資予定):
      - prefecture: '愛知' / '愛知県' / 'Aichi' 自動正規化
      - industry_jsic / jsic: 英 letter と 和名 両対応
      - employees / employee_count: alias 両方受ける
      - planned_investment_man_yen: あれば 金額不足 (undersized) 警告

    返り値 (compact):
      {
        "profile": {正規化後の入力},
        "top_subsidies": [{unified_id, name, amount_max_man_yen, end_date, fit_score, why_fit}, ...N],
        "top_loans": [{loan_id, program_name, provider, collateral_required, rate, amount_max_yen}, ...N],
        "applicable_tax_hints": [{keyword, measure}] — 税制は profile だけでは確定判定不能なので hints のみ
        "urgent_deadlines_30d": [{unified_id, name, end_date, days_left}, ...up to 5],
        "same_industry_enforcement_count": int — 同業種で過去3年の行政処分件数 (DD 参考)
        "next_actions": ["GビズID取得", "経営計画書草案", ...] — 人が1日で動けるステップ
        "source": {"generated_at": ISO8601, "coverage": "..."},
      }

    空 hit は `hint` / `retry_with` 付きで返す (0 件でも迷わせない)。

    CHAIN (深掘り時):
      → `get_program(unified_id)` で top_subsidies の詳細
      → `check_exclusions(a, b)` で併用可否
      → `search_case_studies(prefecture, industry_jsic)` で採択事例
      → `get_loan_program(loan_id)` で融資 要項
    """
    from datetime import date, datetime

    from jpintel_mcp.api.prescreen import PrescreenRequest, run_prescreen

    emp = employees if employees is not None else employee_count
    jsic_raw = industry_jsic if industry_jsic is not None else jsic
    pref_norm = _normalize_prefecture(prefecture)
    jsic_norm = _normalize_industry_jsic(jsic_raw)

    # BUG-2 fix: Tokio/Tokyou/東京府 etc. silently pass through _normalize_prefecture,
    # then SQL match never fires → all-national fallback. Collect typos as warnings
    # so the LLM knows the filter was a no-op, and drop the filter to national fallback.
    input_warnings: list[dict[str, Any]] = []
    if prefecture and not _is_known_prefecture(prefecture):
        input_warnings.append({
            "field": "prefecture",
            "code": "unknown_prefecture",
            "value": prefecture,
            "normalized_to": pref_norm,
            "message": (
                f"prefecture={prefecture!r} は正規の都道府県に一致せず。"
                "フィルタを無効化し全国ベースで返しました。正しい例: '東京' / '東京都' / 'Tokyo'。"
            ),
            "retry_with": ["enum_values(field='prefecture')"],
        })
        pref_norm = None

    profile = PrescreenRequest(
        prefecture=pref_norm,
        industry_jsic=jsic_norm,
        is_sole_proprietor=is_sole_proprietor,
        employee_count=emp,
        revenue_yen=revenue_yen,
        founded_year=None,
        planned_investment_man_yen=planned_investment_man_yen,
        houjin_bangou=None,
        declared_certifications=None,
        limit=limit_per_section,
    )

    conn = connect()
    try:
        prescreen = run_prescreen(conn, profile).model_dump()
        programs_raw = prescreen.get("results", []) or []

        # BUG-3 fix: prescreen returns rows of all program_kind. top_subsidies is
        # 補助金/助成金/税制 only — loan rows have their own top_loans section.
        # Strip loans so セーフティネット貸付 doesn't masquerade as a subsidy.
        raw_ids = [r.get("unified_id") for r in programs_raw if r.get("unified_id")]
        loan_ids: set[str] = set()
        if raw_ids:
            placeholders = ",".join(["?"] * len(raw_ids))
            loan_rows = conn.execute(
                f"SELECT unified_id FROM programs "
                f"WHERE unified_id IN ({placeholders}) AND program_kind='loan'",
                raw_ids,
            ).fetchall()
            loan_ids = {row[0] for row in loan_rows}
        programs_subsidy = [r for r in programs_raw if r.get("unified_id") not in loan_ids]

        top_subsidies = []
        for r in programs_subsidy[:limit_per_section]:
            top_subsidies.append({
                "unified_id": r.get("unified_id"),
                "name": r.get("primary_name") or r.get("name"),
                "amount_max_man_yen": r.get("amount_max_man_yen"),
                "tier": r.get("tier"),
                "official_url": r.get("official_url"),
                "fit_score": r.get("fit_score"),
                "why_fit": (r.get("match_reasons") or [])[:2],
            })

        # BUG-6 fix: stress-test found 4/5 default loans are 事業再生/DIP/危機対応
        # (distressed-company products) served to every user regardless of
        # prefecture/industry. Filter them out of the healthy-baseline pack,
        # and boost rows that mention the caller's prefecture in target_conditions.
        _distressed_kws = (
            "DIP", "事業再生", "企業再建", "危機対応", "再挑戦",
            "セーフティネット", "東日本大震災",
            "豪雨", "災害", "特別貸付", "被災", "地震",
        )
        loan_rows_all = conn.execute(
            """
            SELECT id, program_name, provider, loan_type,
                   collateral_required, personal_guarantor_required,
                   interest_rate_base_annual, amount_max_yen,
                   loan_period_years_max, target_conditions
              FROM loan_programs
             WHERE (collateral_required = 'not_required'
                    OR collateral_required = 'negotiable'
                    OR personal_guarantor_required = 'not_required')
             ORDER BY amount_max_yen DESC
             LIMIT 40
            """,
        ).fetchall()
        loan_candidates = [
            r for r in loan_rows_all
            if not any(k in (r[1] or "") for k in _distressed_kws)
        ]

        def _loan_starter_score(r: Any) -> tuple[int, int]:
            name = r[1] or ""
            tc = r[9] or ""
            bonus = 0
            if pref_norm and pref_norm in tc:
                bonus += 3
            if pref_norm and pref_norm in name:
                bonus += 2
            # Soft industry bonus — JSIC letter alone doesn't match, but 和名 may appear.
            if jsic_norm and ("新事業" in name or "創業" in name):
                bonus += 1
            return (bonus, int(r[7] or 0))

        loan_candidates.sort(key=_loan_starter_score, reverse=True)
        top_loans = [{
            "loan_id": r[0],
            "program_name": r[1],
            "provider": r[2],
            "loan_type": r[3],
            "collateral_required": r[4],
            "personal_guarantor_required": r[5],
            "interest_rate_base_annual": r[6],
            "amount_max_yen": r[7],
            "loan_period_years_max": r[8],
        } for r in loan_candidates[:limit_per_section]]

        tax_hints: list[dict[str, Any]] = []
        if revenue_yen is not None or emp is not None:
            tax_rows = conn.execute(
                """
                SELECT unified_id, ruleset_name, tax_category, ruleset_kind,
                       effective_from, effective_until
                  FROM tax_rulesets
                 WHERE effective_from <= date('now')
                   AND (effective_until IS NULL OR effective_until >= date('now'))
                 ORDER BY effective_from DESC
                 LIMIT ?
                """,
                (limit_per_section,),
            ).fetchall()
            tax_hints = [{
                "unified_id": r[0],
                "ruleset_name": r[1],
                "tax_category": r[2],
                "ruleset_kind": r[3],
                "effective_until": r[5],
                "call_to_confirm": "evaluate_tax_applicability",
            } for r in tax_rows]

        deadlines_rows = conn.execute(
            """
            SELECT unified_id, primary_name,
                   json_extract(application_window_json, '$.end_date') AS end_date
              FROM programs
             WHERE excluded = 0
               AND tier IN ('S','A','B','C')
               AND json_extract(application_window_json, '$.end_date') IS NOT NULL
               AND json_extract(application_window_json, '$.end_date') >= date('now')
               AND json_extract(application_window_json, '$.end_date') <= date('now', '+30 days')
               AND (? IS NULL OR prefecture IS NULL OR prefecture = ?)
             ORDER BY end_date ASC
             LIMIT 5
            """,
            (pref_norm, pref_norm),
        ).fetchall()
        urgent_deadlines = []
        for r in deadlines_rows:
            end_iso = r[2]
            try:
                dl = datetime.strptime(end_iso[:10], "%Y-%m-%d").date()
                days_left = (dl - date.fromisoformat(_jst_today_iso())).days
            except Exception:
                days_left = None
            urgent_deadlines.append({
                "unified_id": r[0],
                "name": r[1],
                "end_date": end_iso[:10] if end_iso else None,
                "days_left": days_left,
            })

        enf_count = conn.execute(
            """
            SELECT COUNT(*)
              FROM enforcement_cases
             WHERE disclosed_date >= date('now', '-3 years')
               AND (? IS NULL OR prefecture IS NULL OR prefecture = ?)
            """,
            (pref_norm, pref_norm),
        ).fetchone()[0]

    finally:
        conn.close()

    next_actions: list[str] = []
    if not top_subsidies:
        next_actions.append(
            "prescreen が 0 件 → industry_jsic / 地域 を広げて再実行"
        )
    else:
        next_actions.append("GビズID プライム取得 (ほぼ全補助金で必要)")
        if any(r.get("amount_max_man_yen", 0) and r["amount_max_man_yen"] >= 500 for r in top_subsidies):
            next_actions.append("経営計画書 草案 (1 週間で粗書き → 士業に添削)")
        if top_loans:
            next_actions.append("公庫 事業資金相談の予約 (担保・保証の 3 軸ヒアリング)")
        if urgent_deadlines:
            next_actions.append(
                f"直近 30 日 に {len(urgent_deadlines)} 件締切 — スケジュール優先度高"
            )

    payload: dict[str, Any] = {
        "profile": {
            "prefecture": pref_norm,
            "industry_jsic": jsic_norm,
            "employees": emp,
            "revenue_yen": revenue_yen,
            "planned_investment_man_yen": planned_investment_man_yen,
            "is_sole_proprietor": is_sole_proprietor,
        },
        "input_warnings": input_warnings if input_warnings else None,
        "top_subsidies": top_subsidies,
        "top_loans": top_loans,
        "applicable_tax_hints": tax_hints,
        "urgent_deadlines_30d": urgent_deadlines,
        "recent_enforcement_count_3y": enf_count,
        "next_actions": next_actions,
        "source": {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "coverage": (
                "補助金 11,211 + 融資 108 + 税制 35 + 行政処分 1,185 から "
                "プロファイルに沿った top N を 1 call で。"
                "併用可否は check_exclusions、詳細は get_program で深掘り。"
            ),
        },
    }

    if not top_subsidies:
        payload["hint"] = (
            "補助金候補 0 件。industry_jsic ('製造業' 等) か prefecture ('東京' 等) を"
            "緩める or 正規化ミス確認 (JSIC=E が正規、'製造業' は自動変換、'E1' はNG)。"
            "融資/税制/直近締切 は別軸なので 0 件でも有用な場合あり。"
        )
        payload["retry_with"] = [
            "prescreen_programs (同じ引数でより緩い fit-score ranking)",
            "search_programs (q='業種キーワード')",
            "enum_values(field='industry_jsic') で正規コード確認",
        ]
        payload["data_state"] = "empty_subsidies"

    return payload


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def upcoming_deadlines(
    within_days: Annotated[
        int | None,
        Field(
            ge=1,
            le=180,
            description="Only list programs whose end_date is within today..today+within_days. Default 30. Alias: `days_ahead` (same semantics).",
        ),
    ] = None,
    days_ahead: Annotated[
        int | None,
        Field(
            ge=1,
            le=180,
            description="Alias for within_days. If both are set, within_days wins. Default 30.",
        ),
    ] = None,
    prefecture: Annotated[
        PrefectureParam,
        Field(
            description=(
                "Prefecture filter (closed-set 48 値). Canonical kanji ('東京都'), short ('東京'), "
                "romaji ('Tokyo') — auto-normalized. Unknown values raise invalid_enum. "
                "National programs are always included."
            )
        ),
    ] = None,
    authority_level: Annotated[
        str | None,
        Field(
            description=(
                "national / prefecture / municipality / financial (also 国 / 都道府県 / 市区町村)."
            )
        ),
    ] = None,
    tier: Annotated[
        list[str] | None,
        Field(description="Tier OR filter: ['S'], ['S','A'], etc. None = all tiers except X."),
    ] = None,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description=(
                "返却する deadline 行の最大件数. Range [1, 100]. Default 50. "
                "end_date ASC 順なので index 0 が最も urgent. "
                "カレンダー表示は 50, summary 用は 10-20 が現実的."
            ),
        ),
    ] = 50,
) -> dict[str, Any]:
    """DISCOVER-CALENDAR: list 補助金 / 助成金 / 融資 / 税制 programs whose application deadline (application_window.end_date) falls within the next N days.

    Use when the caller frames the question time-first: "来月締切の支援制度を一覧で" / "茨城で今月締切を迎えるもの".
    One call replaces the keyword-guess + per-program get_program dance. Rows are ordered by
    `end_date ASC`, so index 0 is always the most urgent.

    Each row returns: unified_id, primary_name, tier, prefecture, end_date, days_remaining,
    amount_max_man_yen, application_url.

    LIMITATIONS:
      - Only reads `application_window.end_date`. Programs without a structured end_date
        (roughly 60% of the corpus — most rolling / 随時 programs) are silently skipped.
      - Multi-round 公募 where each round has its own window are represented by a single
        end_date today; richer multi-round support is pending an enriched-schema stabilisation.

    WHEN NOT:
      - `search_programs(q=…)` for keyword discovery (no deadline filter).
      - `get_program(unified_id)` for a single program's full window + multi-round detail.

    CHAIN:
      → `get_program(unified_id)` for required documents / full policy on the most urgent row.
      → `check_exclusions([…])` before recommending the caller apply for multiple urgent ones.
    """
    from jpintel_mcp.api.calendar import run_upcoming_deadlines
    from jpintel_mcp.api.vocab import (
        _normalize_authority_level,
        _normalize_prefecture,
    )

    effective_days = (
        within_days
        if within_days is not None
        else (days_ahead if days_ahead is not None else 30)
    )
    conn = connect()
    try:
        normalized_pref = _normalize_prefecture(prefecture)
        # BUG-2 fix: warn on unknown prefecture, drop filter so the calendar
        # falls back to national rather than silently filtering on garbage.
        input_warnings: list[dict[str, Any]] = []
        if prefecture and not _is_known_prefecture(prefecture):
            input_warnings.append({
                "field": "prefecture",
                "code": "unknown_prefecture",
                "value": prefecture,
                "normalized_to": normalized_pref,
                "message": (
                    f"prefecture={prefecture!r} は正規の都道府県に一致せず。"
                    "フィルタを無効化し全国ベースの締切一覧を返しました。"
                    "正しい例: '東京' / '東京都' / 'Tokyo'。"
                ),
                "retry_with": ["enum_values(field='prefecture')"],
            })
            normalized_pref = None
        result = run_upcoming_deadlines(
            conn,
            within_days=effective_days,
            prefecture=normalized_pref,
            authority_level=_normalize_authority_level(authority_level),
            tier=tier,
            limit=limit,
        )
        payload = result.model_dump()
        # S5 fix: when the user passed prefecture=<X>, the result legitimately
        # includes 国 (national) rows. That's useful, but they get silently
        # mixed into `total` — a 大阪府 agent asking "Osaka deadlines" sees
        # 21 rows and doesn't know 0 are 大阪-specific, 21 are national.
        results_list = payload.get("results", []) or []
        nat_count = sum(
            1 for r in results_list
            if not r.get("prefecture")
            or r.get("authority_level") == "national"
        )
        pref_count = len(results_list) - nat_count
        payload["prefecture_specific_count"] = pref_count
        payload["national_count"] = nat_count
        if normalized_pref and pref_count == 0 and nat_count > 0:
            payload["hint"] = (
                f"prefecture='{normalized_pref}' で該当 0 件。返している "
                f"{nat_count} 件は全国区 (国 / 政策金融公庫 等) の制度です。"
                "都道府県固有の補助金が見たい場合は prefecture を外すか、"
                "`search_programs(prefecture='{normalized_pref}', authority_level='prefecture')` "
                "で直接探してください。"
            )
        if input_warnings:
            payload["input_warnings"] = input_warnings
        return payload
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def deadline_calendar(
    months_ahead: Annotated[
        int,
        Field(
            ge=1,
            le=6,
            description="何ヶ月先まで見るか (1..6)。default 3。6 超は `upcoming_deadlines` で。",
        ),
    ] = 3,
    prefecture: Annotated[
        PrefectureParam,
        Field(
            description=(
                "都道府県 closed-set 48 値 (省略=全国+都道府県ミックス)。"
                "'東京' / '東京都' / 'Tokyo' 自動正規化、未知値は invalid_enum で拒否。"
            )
        ),
    ] = None,
    tier: Annotated[
        list[str] | None,
        Field(description="tier フィルタ (default = S/A/B/C)."),
    ] = None,
) -> dict[str, Any]:
    """ONE-SHOT CALENDAR: 今後 N ヶ月 (1..6) の締切を月別グルーピングで 1 call。

    税理士・行政書士 が顧問先に配る月次ブリーフィング用。per-program `get_program`
    チェーンを潰す: 1 call で `{"2026-05": [...5件], "2026-06": [...3件], ...}` を返す。

    返り値 (compact):
      {
        "months_ahead": 3,
        "total": N,
        "by_month": {
          "2026-05": [{unified_id, name, end_date, days_left, amount_max_man_yen, tier}, ...],
          "2026-06": [...],
          "2026-07": [...]
        },
        "urgent_next_7_days": N,  # quick flag
        "empty_months": ["2026-08"] | [],  # "今月締切なし" hint
        "source": {...}
      }

    WHEN NOT:
      - `upcoming_deadlines(within_days=N)` for flat (ungrouped) time-ordered list.
      - `list_open_programs` for pure "今開いてる" (募集中) framing, no deadline sort.

    LIMITATIONS:
      - Same as upcoming_deadlines: 60% 程度の 随時 / rolling 制度 は structured
        end_date を持たないため対象外。
    """
    from datetime import date, datetime

    from jpintel_mcp.api.calendar import run_upcoming_deadlines

    pref_norm = _normalize_prefecture(prefecture)
    within_days = months_ahead * 31

    # BUG-2 fix: warn on unknown prefecture, drop filter to national fallback.
    input_warnings: list[dict[str, Any]] = []
    if prefecture and not _is_known_prefecture(prefecture):
        input_warnings.append({
            "field": "prefecture",
            "code": "unknown_prefecture",
            "value": prefecture,
            "normalized_to": pref_norm,
            "message": (
                f"prefecture={prefecture!r} は正規の都道府県名ではありません。"
                "フィルタを無効化し全国ベースの締切一覧を返しました。"
            ),
            "retry_with": ["enum_values(field='prefecture')"],
        })
        pref_norm = None

    conn = connect()
    try:
        result = run_upcoming_deadlines(
            conn,
            within_days=within_days,
            prefecture=pref_norm,
            authority_level=None,
            tier=tier,
            limit=100,
        )
        payload = result.model_dump()
        rows = payload.get("results", []) or []
    finally:
        conn.close()

    by_month: dict[str, list[dict[str, Any]]] = {}
    urgent = 0
    pref_specific = 0
    national = 0
    today = date.fromisoformat(_jst_today_iso())
    for r in rows:
        end_iso = r.get("end_date")
        if not end_iso:
            continue
        try:
            dl = datetime.strptime(end_iso[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        key = end_iso[:7]
        row_pref = r.get("prefecture")
        row_auth = r.get("authority_level")
        is_national_row = (not row_pref) or row_auth == "national"
        by_month.setdefault(key, []).append({
            "unified_id": r.get("unified_id"),
            "name": r.get("primary_name") or r.get("name"),
            "end_date": end_iso[:10],
            "days_left": (dl - today).days,
            "amount_max_man_yen": r.get("amount_max_man_yen"),
            "tier": r.get("tier"),
            "prefecture": row_pref,
            "authority_level": row_auth,
        })
        if (dl - today).days <= 7:
            urgent += 1
        if is_national_row:
            national += 1
        else:
            pref_specific += 1

    for k in by_month:
        by_month[k].sort(key=lambda x: x["end_date"])
        by_month[k] = by_month[k][:10]

    expected_months: list[str] = []
    for i in range(months_ahead + 1):
        y = today.year + ((today.month - 1 + i) // 12)
        m = ((today.month - 1 + i) % 12) + 1
        expected_months.append(f"{y:04d}-{m:02d}")
    empty_months = [m for m in expected_months if m not in by_month]

    out: dict[str, Any] = {
        "months_ahead": months_ahead,
        "prefecture": pref_norm,
        "input_warnings": input_warnings if input_warnings else None,
        "total": sum(len(v) for v in by_month.values()),
        "prefecture_specific_count": pref_specific,
        "national_count": national,
        "by_month": dict(sorted(by_month.items())),
        "urgent_next_7_days": urgent,
        "empty_months": empty_months,
        "source": {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "coverage": (
                "application_window.end_date を持つ programs のみ。"
                "60% 程度の 随時/rolling 制度は対象外 (上記 LIMITATIONS 参照)."
            ),
        },
    }

    # BUG-1 fix: when pref_norm is set and all rows are national-or-mismatched-prefecture,
    # be explicit so the LLM doesn't frame 霧島市 rows as Tokyo programs.
    if pref_norm and pref_specific == 0 and national > 0:
        out.setdefault("hint", (
            f"prefecture='{pref_norm}' 固有の締切 0 件。返している {national} 件は"
            " 全国区 / 市区町村 プレフィックスの no-prefecture 行です。"
            f" search_programs(prefecture='{pref_norm}', authority_level='prefecture') で"
            "都道府県固有の直接検索も検討してください。"
        ))

    if out["total"] == 0:
        out["hint"] = (
            f"今後 {months_ahead} ヶ月で構造化期限を持つ制度が 0 件。"
            f"prefecture='{pref_norm}' を外す or months_ahead を 6 に広げて再実行推奨。"
            "random / 随時 募集の制度は `list_open_programs` 側で見られる。"
        )
        out["retry_with"] = [
            "upcoming_deadlines (within_days=180)",
            "list_open_programs",
        ]
        out["data_state"] = "empty_calendar"

    return out


# ===========================================================================
# ONE-SHOT: subsidy_combo_finder
# 補助金+融資+税制 の 非衝突組合せ TOP N を 1 call で返す。
# 税理士/行政書士 が顧問先に「ものづくり+マル経+生産性向上税制」みたいな
# パッケージ提案をする時の「どれとどれが同時に使えるか」を自動判定。
# ===========================================================================


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def subsidy_combo_finder(
    keyword: Annotated[
        str | None,
        Field(
            description=(
                "seed 補助金名 / キーワード (例: 'ものづくり' 'IT導入' '事業再構築')."
                " unified_id のほうが確実。"
            )
        ),
    ] = None,
    unified_id: Annotated[
        str | None,
        Field(
            description=(
                "seed 補助金の unified_id (UNI-xxxx)。keyword より優先、exact match。"
            )
        ),
    ] = None,
    prefecture: Annotated[
        PrefectureParam,
        Field(
            description=(
                "融資候補 絞り込み用都道府県 closed-set 48 値 (例: '東京' / '東京都' / 'Tokyo' 自動正規化)。"
                "未知値は invalid_enum で拒否。"
            ),
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=5, description="返す組合せ数 (default=3, max=5)。各 combo は 補助金+融資+税制 の 1 セット — 上位 N 件を combined_max_benefit_man_yen 順で返却。"),
    ] = 3,
) -> dict[str, Any]:
    """ONE-SHOT COMBO: 補助金+融資+税制 の 非衝突組合せ TOP N を 1 call で。

    Japanese SMB の典型シナリオ:
      「ものづくり補助金」申請予定 → 残りの投資資金をどう賄うか？
      → このツールは exclusion_rules を参照し、seed 補助金と同時利用可能な
         融資 + 税制 を自動で見つけて 組合せとして返す。

    LLM が手動で (search_programs → get_program → list_exclusion_rules →
    search_loans → get_tax_rule) を 5 回チェーンする必要がなくなる。

    入力:
      - `unified_id`: seed 補助金 (例: 'UNI-xxxxxxxxxx')、最も確実
      - `keyword`:    seed 補助金キーワード (例: 'ものづくり')、fuzzy
      - `prefecture`: 融資の地域絞り込み (optional)
      - `limit`:      返す組合せ数 (default=3, max=5)

    返り値 (compact, ≤ 3 KB):
      {
        "seed": {"unified_id", "name", "amount_max_man_yen"},
        "combos": [
          {
            "rank": 1,
            "subsidy": {"unified_id", "name", "amount_max_man_yen"},
            "loan":    {"loan_id", "program_name", "provider", "amount_max_man_yen", "rate"},
            "tax":     {"unified_id", "ruleset_name", "tax_category"},
            "combined_max_benefit_man_yen": <int>,
            "blocked_by": [],               # 非衝突なら空
            "why_combo": "補助金で初期投資、融資で運転資金、税制で減価償却加速"
          },
          ...
        ],
        "blocked_names": ["他の助成金", "中小企業生産性革命推進事業", ...],
        "source": {...}
      }

    WHEN NOT:
      - `check_compat(a, b)` — 既に 2 つ特定制度があって「これ併給できる？」だけ聞きたい時
      - `prescreen_programs` — プロファイル→候補リスト、組合せはまだ要らない時
      - `smb_starter_pack`   — 補助金/融資/税制/期限 の 汎用ダッシュボード
    """
    # Normalize full-width → half-width so `ＩＴ導入` matches stored `IT導入`.
    # Without this, 日本語サイトからコピペした keyword が silent miss になる。
    import unicodedata as _ud
    if keyword is not None:
        keyword = _ud.normalize("NFKC", keyword).strip()
    if unified_id is not None:
        unified_id = _ud.normalize("NFKC", unified_id).strip()

    # BUG-2 fix: warn on unknown prefecture (ranking bonus path, not hard filter).
    input_warnings: list[dict[str, Any]] = []
    if prefecture and not _is_known_prefecture(prefecture):
        input_warnings.append({
            "field": "prefecture",
            "code": "unknown_prefecture",
            "value": prefecture,
            "message": (
                f"prefecture={prefecture!r} は正規の都道府県名ではありません。"
                "ランキング bonus は効かず全国候補から選定します。"
            ),
            "retry_with": ["enum_values(field='prefecture')"],
        })

    # seed resolve
    seed: dict[str, Any] | None = None
    conn = connect()
    try:
        cur = conn.cursor()
        if unified_id:
            cur.execute(
                "SELECT unified_id, primary_name, amount_max_man_yen, official_url, tier "
                "FROM programs WHERE unified_id = ? AND excluded=0",
                (unified_id,),
            )
            row = cur.fetchone()
            if row:
                seed = dict(row)
        if not seed and keyword:
            cur.execute(
                """
                SELECT unified_id, primary_name, amount_max_man_yen, official_url, tier
                FROM programs
                WHERE excluded=0
                  AND tier IN ('S','A','B','C')
                  AND primary_name LIKE ?
                ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1
                                   WHEN 'B' THEN 2 ELSE 3 END,
                         amount_max_man_yen DESC NULLS LAST
                LIMIT 1
                """,
                (f"%{keyword}%",),
            )
            row = cur.fetchone()
            if row:
                seed = dict(row)
        if not seed:
            return {
                "seed": None,
                "combos": [],
                "blocked_names": [],
                "error": {
                    "code": "seed_not_found",
                    "message": (
                        f"seed 補助金が見つからず: unified_id={unified_id!r}, keyword={keyword!r}"
                    ),
                    "hint": (
                        "keyword を短く (例: 'ものづくり' not 'ものづくり補助金 第23次') "
                        "or search_programs で unified_id を先に特定してから呼ぶ。"
                    ),
                    "retry_with": ["search_programs", "list_open_programs"],
                },
            }

        seed_name = seed.get("primary_name") or ""

        # 1. Get exclusion_rules — match by seed primary_name AND by user keyword
        # (primary_name may be 'ものづくり・商業・...' but exclusion_rules uses
        #  'ものづくり補助金 (第23次公募)' so both angles are needed).
        kw_hint = keyword or ""
        seed_core = seed_name.split("(")[0].split("（")[0].strip()
        like_patterns = {f"%{seed_core}%"}
        if kw_hint:
            like_patterns.add(f"%{kw_hint}%")
        clause = " OR ".join(["program_a LIKE ?"] * len(like_patterns))
        cur.execute(
            f"""
            SELECT program_a, program_b, kind, severity, description
              FROM exclusion_rules
             WHERE ({clause})
               AND kind IN ('exclude', 'absolute', 'same_asset_exclusive',
                            'mutex_certification', 'cross_tier_same_asset')
            """,
            tuple(like_patterns),
        )
        blocked_rows = cur.fetchall()
        blocked_names = list({r["program_b"] for r in blocked_rows if r["program_b"]})

        def _is_blocked(candidate_name: str) -> str | None:
            if not candidate_name:
                return None
            for bn in blocked_names:
                if not bn:
                    continue
                if bn in candidate_name or candidate_name in bn:
                    return bn
            return None

        # 2. Candidate loans — growth-oriented only. Drop distressed-company loans
        # (DIP/企業再建/危機対応/再挑戦/セーフティネット) unless the seed itself
        # is 再生/再建/倒産系; those 20億 products are wrong for 補助金 申請者
        # (who must be in 健全経営).
        distressed_kws = (
            "DIP", "事業再生", "企業再建", "危機対応", "再挑戦",
            "セーフティネット", "東日本大震災",
            # BUG-5 (stress-test 2026-04-25): 豪雨 / 災害 / 特別貸付 が
            # ものづくり seed に混入して disaster-relief loans が recommend
            # される事故。天災 loan は 再建 と同じ bucket で block する。
            "豪雨", "災害", "特別貸付", "被災", "地震",
        )
        seed_is_distressed = any(k in seed_name for k in distressed_kws) or any(
            k in (kw_hint or "") for k in distressed_kws
        )
        # Pull a broad candidate set — don't hard-filter on prefecture. BUG-5
        # stress-test showed prefecture+distressed-block can starve valid
        # combos (e.g. 鹿児島+ものづくり where only disaster loans mentioned
        # "鹿児島" in target_conditions; blocking those dropped us to 0).
        cur.execute(
            "SELECT id, program_name, provider, amount_max_yen, "
            "interest_rate_base_annual, interest_rate_special_annual, "
            "rate_names, official_url, target_conditions "
            "FROM loan_programs WHERE program_name IS NOT NULL "
            "ORDER BY amount_max_yen DESC NULLS LAST LIMIT 80"
        )
        loans_all = [dict(r) for r in cur.fetchall()]

        def _loan_score(ln: dict[str, Any]) -> tuple[int, int]:
            name = ln.get("program_name") or ""
            tc = ln.get("target_conditions") or ""
            provider = ln.get("provider") or ""
            theme_bonus = 0
            # keyword overlap: if seed keyword appears in loan name, huge boost
            for token in (kw_hint or seed_core or "").split():
                if token and token in name:
                    theme_bonus += 2
            # Common theme heuristics
            for seed_word, loan_hint in (
                ("ものづくり", "新事業活動"),
                ("省力化", "省力化"),
                ("IT導入", "IT活用"),
                ("デジタル", "IT活用"),
                ("事業承継", "事業承継"),
                ("再構築", "新事業活動"),
                ("省エネ", "環境・エネルギー"),
                ("創業", "新事業育成"),
                ("賃上げ", "働き方改革"),
            ):
                if seed_word in (seed_core + " " + (kw_hint or "")) and loan_hint in name:
                    theme_bonus += 3
            # Prefecture = ranking bonus, not hard filter (was hard filter → starved combos).
            if prefecture and (prefecture in tc or prefecture in provider or prefecture in name):
                theme_bonus += 2
            return (theme_bonus, int(ln.get("amount_max_yen") or 0))

        loans_filtered = [
            ln for ln in loans_all
            if _is_blocked(ln.get("program_name") or "") is None
            and (
                seed_is_distressed
                or not any(k in (ln.get("program_name") or "") for k in distressed_kws)
            )
        ]
        loans_filtered.sort(key=_loan_score, reverse=True)
        loans_ok = loans_filtered[:10]

        # 3. Candidate tax rulesets — prefer business-relevant (corporate credit /
        # special_depreciation / 少額減価償却) over 住宅ローン控除 / 電子帳簿 等.
        cur.execute(
            """
            SELECT unified_id, ruleset_name, tax_category, ruleset_kind,
                   rate_or_amount, authority, effective_until
              FROM tax_rulesets
             WHERE (effective_until IS NULL OR effective_until >= date('now'))
               AND (
                    (tax_category = 'corporate'
                     AND ruleset_kind IN ('credit', 'special_depreciation'))
                 OR ruleset_name LIKE '%投資促進%'
                 OR ruleset_name LIKE '%賃上げ%'
                 OR ruleset_name LIKE '%少額減価償却%'
                 OR ruleset_name LIKE '%経営強化%'
                )
             ORDER BY
               CASE
                 WHEN ruleset_name LIKE '%投資促進%' THEN 0
                 WHEN ruleset_name LIKE '%経営強化%' THEN 1
                 WHEN ruleset_name LIKE '%賃上げ%' THEN 2
                 WHEN ruleset_name LIKE '%少額減価償却%' THEN 3
                 ELSE 4
               END
            """
        )
        tax_all = [dict(r) for r in cur.fetchall()]
        tax_ok = [
            t for t in tax_all
            if _is_blocked(t.get("ruleset_name") or "") is None
        ]
    finally:
        conn.close()

    # 4. Build combos — rotate tax picks to cover top 3 categories (投資促進 →
    # 経営強化/賃上げ → 少額減価償却). loan ordered amount DESC already.
    combos: list[dict[str, Any]] = []
    seed_amount_man = int(seed.get("amount_max_man_yen") or 0)

    for i, ln in enumerate(loans_ok[:limit]):
        tax_pick: dict[str, Any] | None = tax_ok[i] if i < len(tax_ok) else (
            tax_ok[0] if tax_ok else None
        )
        loan_max_man = (ln.get("amount_max_yen") or 0) // 10000
        loan_rate = ln.get("interest_rate_special_annual") or ln.get("interest_rate_base_annual")
        combo = {
            "rank": len(combos) + 1,
            "subsidy": {
                "unified_id": seed.get("unified_id"),
                "name": seed_name,
                "grant_max_man_yen": seed_amount_man or None,
            },
            "loan": {
                "loan_id": ln.get("id"),
                "program_name": ln.get("program_name"),
                "provider": ln.get("provider"),
                "loan_max_man_yen": loan_max_man or None,
                "rate_annual": loan_rate,
            },
            "tax": {
                "unified_id": tax_pick.get("unified_id") if tax_pick else None,
                "ruleset_name": tax_pick.get("ruleset_name") if tax_pick else None,
                "tax_category": tax_pick.get("tax_category") if tax_pick else None,
                "ruleset_kind": tax_pick.get("ruleset_kind") if tax_pick else None,
            } if tax_pick else None,
            "financial_structure": {
                "grant_man_yen": seed_amount_man or None,
                "debt_capacity_man_yen": loan_max_man or None,
                "note": "grant と debt は 別 bucket。投資総額の上限目安は grant+debt ではなく 投資計画 次第。",
            },
            "blocked_by": [],
            "why_combo": (
                f"{seed_name} で 補助金 受領、{ln.get('program_name')} で 投資資金 調達"
                + (f"、{tax_pick.get('ruleset_name')} で 税負担 軽減" if tax_pick else "")
            ),
        }
        combos.append(combo)

    out: dict[str, Any] = {
        "seed": {
            "unified_id": seed.get("unified_id"),
            "name": seed_name,
            "grant_max_man_yen": seed_amount_man or None,
            "tier": seed.get("tier"),
            "official_url": seed.get("official_url"),
        },
        "input_warnings": input_warnings if input_warnings else None,
        "combos": combos,
        "blocked_names": blocked_names[:15],
        "source": {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "tool": "subsidy_combo_finder",
            "db": "jpintel.db",
            "note": (
                "blocked_names は 公募要領 記載の併給禁止 category/program 一覧. "
                "'他の助成金' のような category 型 は fuzzy 除外済み (false negative 可)."
            ),
        },
    }

    if not combos:
        out["hint"] = (
            f"seed='{seed_name}' に対し 融資 候補 0 件。"
            f"prefecture='{prefecture}' を外す or loan DB が 108 件のみ (全国融資が中心) "
            "のため地方公庫 の制度は含まれていない。"
        )
        out["retry_with"] = ["search_loans", "list_exclusion_rules"]
        out["data_state"] = "no_compatible_loans"

    return out


# ===========================================================================
# ONE-SHOT: dd_profile_am
# M&A 仲介 / VC / 銀行 DD / 士業 顧問先調査 の 「法人番号 1 本で会社の
# 公表コンプライアンス + 補助金実績 + インボイス登録 を 1 call」。
# 採択実績 + 行政処分 + インボイス の 3 軸を houjin_bangou で stitch。
# ===========================================================================


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def dd_profile_am(
    houjin_bangou: Annotated[
        str,
        Field(
            description=(
                "対象法人の 13 桁 法人番号。'T'付インボイス番号/全角/ハイフンは自動正規化。"
                "例: '3040001101014', 'T3040001101014', '3040-0011-01014', '３０４０…'."
            ),
            min_length=1,
            max_length=64,
        ),
    ],
    include_adoptions: Annotated[
        bool,
        Field(
            description=(
                "補助金採択履歴 (adoption_records) を含めるか. Default True. "
                "False で payload を最大 60% 圧縮 (token 節約). "
                "False のとき adoption_limit は無視される."
            ),
        ),
    ] = True,
    adoption_limit: Annotated[
        int,
        Field(
            ge=1,
            le=50,
            description="adoptions リストの最大行数 (default 20)。件数だけなら limit=1 + total を見る。",
        ),
    ] = 20,
) -> dict[str, Any]:
    """ONE-SHOT DD: 法人番号 → 公表コンプライアンス + 採択実績 + インボイス登録 を 1 call.

    M&A 仲介 / 銀行 DD / VC の投資前調査 / 士業の顧問先調査 の定番チェーン
    (search_enforcement → check_enforcement → search_acceptance_stats_am →
     list_adoptions → invoice_registrants) を houjin_bangou 一発で返す。

    入力:
      - houjin_bangou: 13 桁 (T 付き インボイス番号、ハイフン、全角 全て OK。NFKC + 非数字除去で 13 桁化)

    返り値 (≤ 3 KB 目安):
      {
        "houjin_bangou": "...",          # 正規化後
        "entity": {                       # 法人マスタ (autonomath corporate_entity があれば)
          "name", "category", "prefecture", "municipality", "certified_at"
        },
        "adoptions_summary": {
          "total": int,
          "programs_list": [...]          # 採択された補助金 名 unique
        },
        "adoptions": [                    # include_adoptions=True の時のみ
          {"canonical_id", "program_name", "adopted_at", ...}
        ],
        "enforcement": {                  # check_enforcement の戻り
          "found", "currently_excluded", "active_exclusions", "recent_history", "all_count"
        },
        "invoice_registration": {
          "status": "registered" | "revoked" | "unknown_in_mirror",
          "invoice_registration_number": "T...", "registered_date", "trade_name"
        },
        "dd_flags": [                     # agents が要注意点を一覧で取れる bullet
          "currently_excluded", "no_adoption_history", "clean_enforcement_record",
          "invoice_mirror_miss", "unknown_company"
        ],
        "coverage_scope": "...",          # 与信/反社/信用情報には一切該当せず、公的補助金/税制 due diligence 専用
        "source": {...}
      }

    DATA HONESTY GATES (誤解防止):
      - adoptions.amount_granted_yen is 100% NULL in current snapshot —
        total_amount_man_yen は返しません (虚偽の数字を作らない)。
      - invoice_registrants は delta mirror (13,801 / 4M 公表済み) —
        "unknown_in_mirror" = "国税庁に未登録" ではない。absence ≠ not registered。
      - enforcement.found=false は 公表 1,185 行政処分 corpus 外であって、反社
        チェック / 信用情報 / 帝国データバンク は別途必要 (範囲外)。

    WHEN NOT:
      - `check_enforcement_am` — 法人番号ピンポイント で 行政処分 だけ欲しい時
      - `search_acceptance_stats_am` — 特定 program に対する採択率だけ欲しい時
      - `search_enforcement_cases(keyword=…)` — 名称部分一致 or 法人番号無し の時

    CHAIN:
      → `check_enforcement_am(houjin_bangou)` で active_exclusions の詳細
      → `search_enforcement_cases(houjin_bangou)` で行政処分 source_url へ
      → `get_invoice_registrant(registration_number)` で登録履歴の詳細
    """
    # === S3 HTTP FALLBACK ===
    # dd_profile_am is a composite tool (autonomath corporate_entity +
    # enforcement + invoice mirror). No single REST endpoint mirrors this
    # shape today, so fallback returns the structured remote_only error
    # plus a recommended REST chain. Operators will land a /v1/am/dd_profile
    # endpoint in a follow-up; until then this surfaces an honest hint.
    if detect_fallback_mode():
        from jpintel_mcp.mcp._http_fallback import _api_base
        base = _api_base()
        return {
            "error": "remote_only_via_REST_API",
            "tool": "dd_profile_am",
            "message": (
                "dd_profile_am は composite tool (法人番号 → corporate_entity + "
                "enforcement + invoice). MCP HTTP-fallback では未対応です — "
                "ローカル DB 不在 (uvx インストール) 時は REST chain を直接呼んでください。"
            ),
            "rest_chain_hint": [
                f"{base}/v1/enforcement-cases/search?q={houjin_bangou}",
                f"{base}/v1/am/enforcement?houjin_bangou={houjin_bangou}",
                f"{base}/v1/invoice-registrants/{houjin_bangou}",
            ],
            "rest_api_base": base,
            "remediation": (
                "1) Use the REST chain above, or 2) clone the repo for a full local DB."
            ),
        }
    # === END S3 HTTP FALLBACK ===
    from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath
    from jpintel_mcp.mcp.autonomath_tools.enforcement_tool import (
        _normalize_houjin,
        check_enforcement,
    )

    hj = _normalize_houjin(houjin_bangou)
    if not hj:
        return {
            "houjin_bangou": None,
            "entity": None,
            "adoptions_summary": {"total": 0, "programs_list": []},
            "adoptions": [],
            "enforcement": None,
            "invoice_registration": None,
            "dd_flags": [],
            "error": {
                "code": "invalid_enum",
                "message": (
                    f"houjin_bangou={houjin_bangou!r} を 13 桁に正規化できません。"
                ),
                "hint": (
                    "T+13桁のインボイス番号、ハイフン入り (1234-5678-9012-3)、"
                    "全角数字、いずれも自動正規化します。13 桁の法人番号が必要。"
                ),
                "retry_with": ["search_enforcement_cases (name 検索)", "check_enforcement_am"],
            },
        }

    dd_flags: list[str] = []
    entity_info: dict[str, Any] | None = None
    adoptions_rows: list[dict[str, Any]] = []
    adoptions_total = 0
    program_names_set: set[str] = set()
    invoice_info: dict[str, Any] = {"status": "unknown_in_mirror"}

    # --- autonomath.db: adoption + corporate_entity ---
    # connect_autonomath() returns a thread-local cached connection (see
    # autonomath_tools/db.py); DO NOT close it — closing poisons the cache.
    try:
        am_conn = connect_autonomath()
        am_conn.row_factory = sqlite3.Row
        ce = am_conn.execute(
            """
            SELECT canonical_id, primary_name, raw_json
              FROM am_entities
             WHERE record_kind = 'corporate_entity'
               AND json_extract(raw_json, '$.houjin_bangou') = ?
             LIMIT 1
            """,
            (hj,),
        ).fetchone()
        if ce:
            try:
                raw = json.loads(ce["raw_json"]) if ce["raw_json"] else {}
            except Exception:
                raw = {}
            entity_info = {
                "canonical_id": ce["canonical_id"],
                "name": ce["primary_name"] or raw.get("name"),
                "category": raw.get("category"),
                "prefecture": raw.get("prefecture_name") or raw.get("prefecture"),
                "municipality": raw.get("municipality"),
                "certified_at": raw.get("certified_at"),
            }

        if include_adoptions:
            adoptions_total = am_conn.execute(
                """
                SELECT COUNT(*)
                  FROM am_entities
                 WHERE record_kind = 'adoption'
                   AND json_extract(raw_json, '$.houjin_bangou') = ?
                """,
                (hj,),
            ).fetchone()[0]

            if adoptions_total > 0:
                rows = am_conn.execute(
                    """
                    SELECT canonical_id, primary_name, source_topic, raw_json
                      FROM am_entities
                     WHERE record_kind = 'adoption'
                       AND json_extract(raw_json, '$.houjin_bangou') = ?
                     LIMIT ?
                    """,
                    (hj, adoption_limit),
                ).fetchall()
                for row in rows:
                    try:
                        raw = json.loads(row["raw_json"]) if row["raw_json"] else {}
                    except Exception:
                        raw = {}
                    prog = raw.get("program_name") or row["source_topic"]
                    if prog:
                        program_names_set.add(prog)
                    adoptions_rows.append({
                        "canonical_id": row["canonical_id"],
                        "program_name": prog,
                        "adopted_at": raw.get("adopted_at") or raw.get("adoption_date"),
                        "adopted_name": row["primary_name"],
                        "prefecture": raw.get("prefecture"),
                        "source_topic": row["source_topic"],
                    })
    except sqlite3.OperationalError:
        # autonomath.db 不在でも他データ で返せる — entity/adoption は空で進む。
        pass

    # --- jpintel.db: invoice_registrants + enforcement ---
    enforcement_payload = check_enforcement(houjin_bangou=hj)

    try:
        conn = connect()
        try:
            inv = conn.execute(
                """
                SELECT invoice_registration_number, registered_date, revoked_date,
                       expired_date, registrant_kind, trade_name, normalized_name,
                       prefecture
                  FROM invoice_registrants
                 WHERE houjin_bangou = ?
                 LIMIT 1
                """,
                (hj,),
            ).fetchone()
            if inv:
                invoice_info = {
                    "status": "revoked" if inv["revoked_date"] else (
                        "expired" if inv["expired_date"] else "registered"
                    ),
                    "invoice_registration_number": inv["invoice_registration_number"],
                    "registered_date": inv["registered_date"],
                    "revoked_date": inv["revoked_date"],
                    "expired_date": inv["expired_date"],
                    "registrant_kind": inv["registrant_kind"],
                    "trade_name": inv["trade_name"],
                    "name": inv["normalized_name"],
                    "prefecture": inv["prefecture"],
                }
            else:
                dd_flags.append("invoice_mirror_miss")
        finally:
            conn.close()
    except sqlite3.OperationalError:
        invoice_info = {"status": "unknown_in_mirror", "reason": "mirror_unavailable"}

    # --- dd_flags 集約 ---
    if enforcement_payload.get("currently_excluded"):
        dd_flags.append("currently_excluded")
    if enforcement_payload.get("found") and enforcement_payload.get("all_count", 0) > 0 \
            and not enforcement_payload.get("currently_excluded"):
        dd_flags.append("recent_enforcement_history")
    if enforcement_payload.get("found") is False:
        dd_flags.append("clean_enforcement_record_in_corpus")
    if adoptions_total == 0:
        dd_flags.append("no_adoption_history")
    if not entity_info and not invoice_info.get("name") and adoptions_total == 0:
        dd_flags.append("unknown_company")

    return {
        "houjin_bangou": hj,
        "entity": entity_info,
        "adoptions_summary": {
            "total": adoptions_total,
            "programs_list": sorted(program_names_set),
            # HONESTY GATE: adoption records don't store granted amounts. Returning
            # total_amount_man_yen would fabricate numbers M&A buyers might price on.
            "total_amount_man_yen": None,
            "amount_coverage_note": (
                "採択件数のみ集計可能。各採択の交付金額は corpus に未記録のため "
                "total_amount は None。個別 program の予算上限は search_programs で。"
            ),
        },
        "adoptions": adoptions_rows if include_adoptions else None,
        "enforcement": {
            "found": enforcement_payload.get("found", False),
            "currently_excluded": enforcement_payload.get("currently_excluded", False),
            "active_exclusions": enforcement_payload.get("active_exclusions", []),
            "recent_history": enforcement_payload.get("recent_history", []),
            "all_count": enforcement_payload.get("all_count", 0),
        },
        "invoice_registration": invoice_info,
        "dd_flags": dd_flags,
        "coverage_scope": (
            "採択実績は 215,233 行政公表 adoption rows (IT 導入/ものづくり/事業再構築 等). "
            "行政処分は 1,185 公表済 rows。インボイスは delta mirror 13,801/4M (未ヒット="
            "未登録 NOT equal)。反社 / 信用情報 / 帝国データバンク / 官報 は範囲外。"
        ),
        "source": {
            "tool": "dd_profile_am",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "dbs": ["autonomath.db (am_entities adoption + corporate_entity)",
                    "jpintel.db (invoice_registrants + enforcement_cases via check_enforcement)"],
        },
    }


# ===========================================================================
# CASE-STUDY-LED DISCOVERY: similar_cases
# 2026-04-25 task #129. ユーザが or LLM が "この採択事例と似た会社" の角度で
# 制度を逆引きするための tool。search_case_studies が「条件→事例リスト」なのに
# 対し、similar_cases は「seed 事例 (or 自由文) → 似た事例 + その制度」を返す。
# Scoring は Jaccard ベース: industry x 2 + prefecture x 1 + programs_used 重複 x 3.
# 似事例の programs_used を最後に programs テーブルへ best-effort 解決して
# supporting_programs (unified_id, source_name, tier, ...) として同梱する。
# ===========================================================================


def _resolve_supporting_programs(
    conn: sqlite3.Connection, names: list[str]
) -> list[dict[str, Any]]:
    """Best-effort name -> programs row resolution. Returns one record per
    `programs_used` name; missing matches surface as
    ``{"source_name": name, "matched": False}`` so the caller never silently
    loses an entry. Uses LIKE on programs.primary_name (programs.source_name
    column does not exist in the live schema — primary_name is the canonical
    label that 採択 sources reference).
    """
    out: list[dict[str, Any]] = []
    for name in names:
        if not name:
            continue
        like = f"%{name}%"
        try:
            row = conn.execute(
                """
                SELECT unified_id, primary_name, tier, prefecture,
                       authority_level, official_url
                  FROM programs
                 WHERE excluded = 0
                   AND (primary_name LIKE ? OR aliases_json LIKE ?)
                 ORDER BY
                     CASE tier
                         WHEN 'S' THEN 0
                         WHEN 'A' THEN 1
                         WHEN 'B' THEN 2
                         WHEN 'C' THEN 3
                         ELSE 4
                     END,
                     primary_name
                 LIMIT 1
                """,
                (like, like),
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row is None:
            out.append({"source_name": name, "matched": False})
            continue
        out.append({
            "unified_id": row["unified_id"],
            "source_name": name,
            "primary_name": row["primary_name"],
            "tier": row["tier"],
            "prefecture": row["prefecture"],
            "authority_level": row["authority_level"],
            "official_url": row["official_url"],
            "matched": True,
        })
    return out


def _score_case_similarity(
    seed_industry: str | None,
    seed_prefecture: str | None,
    seed_programs: list[str],
    cand_industry: str | None,
    cand_prefecture: str | None,
    cand_programs: list[str],
) -> tuple[float, list[str]]:
    """Weighted similarity (industry x 2 + prefecture x 1 + programs overlap x 3)
    normalized into [0, 1] by the maximum achievable weight (2+1+3 = 6 if seed
    has at least 1 program; 2+1 = 3 otherwise). Returns the score and a list
    of human-readable match_reasons that the LLM can echo back to the user.
    """
    reasons: list[str] = []
    score = 0.0
    max_score = 2.0 + 1.0  # industry + prefecture always contribute to denom

    if seed_industry and cand_industry:
        # JSIC prefix match (D06 ⊃ D, E32 vs E ⇒ partial). Use 1-char-prefix
        # for partial credit, full equality for full credit.
        if seed_industry == cand_industry:
            score += 2.0
            reasons.append("same industry (JSIC full match)")
        elif seed_industry[:1] == cand_industry[:1]:
            score += 1.0
            reasons.append(f"related industry ({seed_industry[:1]}*)")
    if seed_prefecture and cand_prefecture and seed_prefecture == cand_prefecture:
        score += 1.0
        reasons.append("same prefecture")
    if seed_programs:
        max_score += 3.0
        seed_set = {p for p in seed_programs if p}
        cand_set = {p for p in cand_programs if p}
        if seed_set and cand_set:
            overlap = seed_set & cand_set
            if overlap:
                # Jaccard on programs_used, scaled to weight 3.
                jaccard = len(overlap) / len(seed_set | cand_set)
                score += 3.0 * jaccard
                if len(overlap) == 1:
                    reasons.append(f"shared 1 program ({next(iter(overlap))})")
                else:
                    reasons.append(f"shared {len(overlap)} programs")
    if max_score == 0:
        return 0.0, reasons
    return score / max_score, reasons


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def similar_cases(
    case_id: Annotated[
        str | None,
        Field(
            description=(
                "Seed case_id (e.g. 'mirasapo_case_120'). 取れていれば最優先で seed として使う。"
                "未指定の場合は description で FTS / LIKE 検索した top 1 を seed に採用。"
            ),
        ),
    ] = None,
    description: Annotated[
        str | None,
        Field(
            description=(
                "case_id が無い時のフォールバック。company_name + case_title + "
                "case_summary + source_excerpt を LIKE 検索し最初のヒットを seed にする。"
                "例: '農業 法人化', 'BCP 災害対応 製造業'."
            ),
        ),
    ] = None,
    industry_jsic: Annotated[
        str | None,
        Field(
            description=(
                "JSIC override (seed の industry を上書き)。seed が industry 不明の "
                "事例の時に明示するなど。'A'='農林水産業', 'E'='製造業' 等。"
            ),
        ),
    ] = None,
    prefecture: Annotated[
        PrefectureParam,
        Field(
            description=(
                "Prefecture override closed-set 48 値 (seed の prefecture を上書き)。"
                "'東京' / '東京都' / 'Tokyo' 自動正規化、未知値は invalid_enum で拒否。"
            ),
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=20,
            description="返す similar_cases 件数 (default 10, max 20)。",
        ),
    ] = 10,
) -> dict[str, Any]:
    """CASE-STUDY-LED DISCOVERY: 採択事例 を seed に「似た事例 + その制度」を返す。

    `search_case_studies` の逆方向 entry point。条件→事例 ではなく、事例 (or 自由文) →
    類似事例 のグルーピング を返し、各 similar case の programs_used を programs テーブルへ
    best-effort で解決する。「この事例 良いな」→ 似た事例 + その制度 が 1 call で揃う。

    Resolution rules:
      - case_id 指定: その case を fetch、industry/prefecture/programs_used を seed vector に。
      - description 指定 (case_id 無し): case_studies を LIKE 検索して top 1 を seed に採用。
      - 両方無し: empty_input error envelope (hint: "case_id か description を渡してください").

    Scoring (Jaccard 型):
      - industry JSIC full match = +2 / 1文字prefix match = +1
      - prefecture exact = +1
      - programs_used overlap = +3 * Jaccard
      - max_score で正規化 → similarity_score ∈ [0, 1]
      - 降順 sort、seed 自身は除外。

    返り値:
      {
        "seed": {"case_id", "title", "industry_jsic", "prefecture", "programs_used"},
        "similar_cases": [
          {
            "case_id", "title", "company_name", "outcome", "prefecture",
            "industry_jsic", "similarity_score",
            "match_reasons": ["same industry", "shared 2 programs"],
            "supporting_programs": [{"unified_id", "source_name", "tier", ...}, ...]
          }, ...
        ],
        "total_found": int,                # similar_cases の長さ
        "source": {...}
      }

    WHEN NOT:
      - `search_case_studies` instead — 条件 (prefecture/industry) で事例リストが
        欲しい時 (こちらは事例 seed が必要)。
      - `smb_starter_pack` instead — プロファイル (都道府県+業種+従業員) から制度を
        探したい時。
      - `dd_profile_am` instead — 法人番号で 1 社の DD だけ欲しい時。

    LIMITATIONS:
      - programs_used の name → unified_id 解決は LIKE substring (best-effort)。
        年度更新で名称変わっていると null = ``"matched": false`` になる。
      - case_studies の programs_used は < 35 種しか登録なし (採択 corpus 全体で
        sparse). 多くの seed では programs overlap = 0 になり、industry+prefecture
        だけで rank される。
      - description LIKE は FTS5 ではなく単純 substring。3 文字未満は filter 外し。

    CHAIN:
      → `get_case_study(case_id=…)` で各 similar case の outcomes/patterns 詳細
      → `get_program(unified_id=…)` で supporting_programs の制度詳細
      → `check_exclusions(a, b)` で複数制度の併給可否
    """
    # --- 1. validate input ---------------------------------------------
    if not case_id and not description:
        return {
            "error": "case_id か description のいずれかを渡してください.",
            "code": "empty_input",
            "hint": (
                "seed として (a) 既知の case_id を渡すか、(b) 'BCP 災害対応' のような "
                "description で LIKE 検索 → top 1 を seed に採用するか、いずれかが必要。"
            ),
            "retry_with": ["search_case_studies"],
        }

    limit = max(1, min(20, limit))

    # Normalize override fields up-front so industry_jsic typos surface early.
    pref_override_raw = prefecture
    pref_override = _normalize_prefecture(prefecture)
    input_warnings: list[dict[str, Any]] = []
    if pref_override_raw and not _is_known_prefecture(pref_override_raw):
        input_warnings.append({
            "field": "prefecture",
            "code": "unknown_prefecture",
            "value": pref_override_raw,
            "normalized_to": pref_override,
            "message": (
                f"prefecture={pref_override_raw!r} は正規の都道府県に一致せず。"
                "override を無効化し seed 側の prefecture を採用しました。"
            ),
            "retry_with": ["enum_values(field='prefecture')"],
        })
        pref_override = None
    industry_override = _normalize_industry_jsic(industry_jsic)

    conn = connect()
    try:
        # --- 2. resolve seed ------------------------------------------
        seed_row: sqlite3.Row | None = None
        seed_via = "case_id"
        if case_id:
            seed_row = conn.execute(
                "SELECT * FROM case_studies WHERE case_id = ?", (case_id,)
            ).fetchone()
            if seed_row is None:
                return {
                    "error": f"case study not found: {case_id}",
                    "code": "seed_not_found",
                    "hint": (
                        "case_id は search_case_studies の results[].case_id "
                        "をそのまま渡してください。"
                    ),
                    "retry_with": ["search_case_studies"],
                }
        else:
            # description フォールバック: LIKE substring across the same 4
            # columns search_case_studies(q=…) covers. Pick top 1 by
            # publication_date DESC for stability.
            assert description is not None  # mypy comfort
            like = f"%{description}%"
            seed_row = conn.execute(
                """
                SELECT * FROM case_studies
                 WHERE (COALESCE(company_name, '') LIKE ?
                        OR COALESCE(case_title, '') LIKE ?
                        OR COALESCE(case_summary, '') LIKE ?
                        OR COALESCE(source_excerpt, '') LIKE ?)
                 ORDER BY COALESCE(publication_date, '') DESC, case_id
                 LIMIT 1
                """,
                (like, like, like, like),
            ).fetchone()
            seed_via = "description"
            if seed_row is None:
                # No seed found via LIKE — return an empty-result envelope
                # (similar_cases=[]) instead of erroring, so callers can keep
                # rendering the standard shape. The empty case is honest and
                # the hint points at FTS-aware retry.
                return {
                    "seed": None,
                    "similar_cases": [],
                    "total_found": 0,
                    "candidate_pool_size": 0,
                    "code": "no_matching_records",
                    "hint": (
                        f"description={description!r} で LIKE substring 一致 0 件。"
                        "より広い 1 単語で再検索するか `search_case_studies(q=…)` で "
                        "case_id を取得してから渡し直してください。"
                    ),
                    "retry_with": ["search_case_studies"],
                }

        seed = _row_to_case_study(seed_row)
        seed_industry = industry_override or seed["industry_jsic"]
        seed_prefecture = pref_override or seed["prefecture"]
        seed_programs: list[str] = list(seed.get("programs_used") or [])

        # --- 3. fetch candidate pool. Pre-filter to same JSIC 大分類 OR
        # same prefecture OR overlapping programs_used to keep the scan
        # bounded; if neither industry nor prefecture is known, fall back
        # to the full corpus (still cheap at 2,286 rows).
        where_clauses: list[str] = ["case_id != ?"]
        params: list[Any] = [seed["case_id"]]
        if seed_industry:
            where_clauses.append("(industry_jsic LIKE ? OR prefecture = ?)")
            params.append(f"{seed_industry[:1]}%")
            params.append(seed_prefecture or "")
        elif seed_prefecture:
            where_clauses.append("prefecture = ?")
            params.append(seed_prefecture)
        sql = f"""
            SELECT case_id, company_name, case_title, case_summary,
                   industry_jsic, prefecture, programs_used_json,
                   outcomes_json, patterns_json, source_url,
                   publication_date
              FROM case_studies
             WHERE {' AND '.join(where_clauses)}
        """
        cand_rows = conn.execute(sql, params).fetchall()

        # --- 4. score every candidate; keep only positive scores -----
        scored: list[dict[str, Any]] = []
        for r in cand_rows:
            cand_programs_raw = r["programs_used_json"] or ""
            try:
                cand_programs = (
                    json.loads(cand_programs_raw) if cand_programs_raw else []
                )
            except json.JSONDecodeError:
                cand_programs = []
            if not isinstance(cand_programs, list):
                cand_programs = []
            cand_programs = [str(p) for p in cand_programs if p]
            score, reasons = _score_case_similarity(
                seed_industry,
                seed_prefecture,
                seed_programs,
                r["industry_jsic"],
                r["prefecture"],
                cand_programs,
            )
            if score <= 0:
                continue
            outcomes_raw = r["outcomes_json"]
            outcome: Any = None
            if outcomes_raw:
                try:
                    outcome = json.loads(outcomes_raw)
                except json.JSONDecodeError:
                    outcome = None
            scored.append({
                "case_id": r["case_id"],
                "title": r["case_title"],
                "company_name": r["company_name"],
                "outcome": outcome,
                "prefecture": r["prefecture"],
                "industry_jsic": r["industry_jsic"],
                "programs_used": cand_programs,
                "similarity_score": round(score, 3),
                "match_reasons": reasons,
                "source_url": r["source_url"],
                "publication_date": r["publication_date"],
            })

        scored.sort(
            key=lambda x: (
                -x["similarity_score"],
                x["publication_date"] or "",
                x["case_id"],
            )
        )
        top = scored[:limit]

        # --- 5. resolve supporting_programs for each kept hit --------
        for rec in top:
            rec["supporting_programs"] = _resolve_supporting_programs(
                conn, rec.get("programs_used") or []
            )

        payload: dict[str, Any] = {
            "seed": {
                "case_id": seed["case_id"],
                "title": seed["case_title"],
                "company_name": seed["company_name"],
                "industry_jsic": seed_industry,
                "prefecture": seed_prefecture,
                "programs_used": seed_programs,
                "resolved_via": seed_via,
            },
            "similar_cases": top,
            "total_found": len(top),
            "candidate_pool_size": len(cand_rows),
            "source": {
                "tool": "similar_cases",
                "generated_at": datetime.now(UTC).isoformat().replace(
                    "+00:00", "Z"
                ),
                "scoring": (
                    "weighted Jaccard: industry×2 + prefecture×1 + "
                    "programs_used overlap×3, normalized to [0, 1]"
                ),
            },
        }
        if input_warnings:
            payload["input_warnings"] = input_warnings
        if not top:
            payload["hint"] = (
                "seed と類似する案件が候補プールから見つかりませんでした。"
                "industry_jsic / prefecture override を緩めるか、"
                "search_case_studies(q=…) で別 seed を取り直してください。"
            )
            payload["retry_with"] = ["search_case_studies", "search_programs"]
        return payload
    finally:
        conn.close()


# ===========================================================================
# ONE-SHOT: subsidy_roadmap_3yr — 2026-04-25. industry/prefecture/size/purpose
# から N ヶ月先 (default 36) の applicable application window を JST 会計年度
# quarter (Apr-Jun=Q1) にバケット。"いつ何を申請?" round-trip を 1 call に潰す。
# ===========================================================================
_FP_MAP: dict[str, list[str]] = {
    "equipment": ["設備投資", "equipment", "施設建設"],
    "rd": ["研究開発", "rd", "技術開発"],
    "export": ["販路開拓", "海外展開", "export"],
    "staffing": ["人件費", "研修費", "training"],
    "digital": ["IT/DX", "digital"],
    "green": ["環境対応", "green", "GX"],
    "general": ["運転資金", "operating", "general"],
}
_SIZE_MAP: dict[str, list[str]] = {
    "sole": ["sole_proprietor", "個人農業者", "個人事業主"],
    "small": ["corporation", "中小企業", "小規模事業者", "農業法人"],
    "medium": ["corporation", "中堅企業", "農業法人"],
    "large": ["corporation", "大企業"],
}


def _jst_today_iso() -> str:
    from datetime import timedelta as _td
    return (datetime.now(UTC) + _td(hours=9)).date().isoformat()


def _jst_fy_quarter(d_iso: str) -> str:
    """Japanese FY (Apr-Mar): 4-6=Q1, 7-9=Q2, 10-12=Q3, 1-3=Q4 of prior FY."""
    from datetime import date as _date
    try:
        d = _date.fromisoformat(d_iso[:10])
    except Exception:
        return "FY?? Q?"
    m = d.month
    if 4 <= m <= 6:
        return f"FY{d.year} Q1"
    if 7 <= m <= 9:
        return f"FY{d.year} Q2"
    if 10 <= m <= 12:
        return f"FY{d.year} Q3"
    return f"FY{d.year - 1} Q4"


def _project_next_opens(start: str | None, cycle: str | None, anchor_iso: str) -> str | None:
    """Past start_date + cycle=annual → roll +N years until >= anchor (Feb 29
    on a non-leap year drops to Feb 28). Non-annual past returns None."""
    from datetime import date as _date
    if not start:
        return None
    try:
        d = _date.fromisoformat(start[:10])
        anchor = _date.fromisoformat(anchor_iso)
    except Exception:
        return None
    if d >= anchor:
        return d.isoformat()
    if cycle != "annual":
        return None
    while d < anchor:
        try:
            d = d.replace(year=d.year + 1)
        except ValueError:
            d = d.replace(year=d.year + 1, day=28)
        if d.year > anchor.year + 5:  # safety bound
            return None
    return d.isoformat()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def subsidy_roadmap_3yr(
    industry: Annotated[str, Field(description="JSIC 大分類 (A..T) または和名 ('製造業','農業','建設業' 等). `enum_values(field='industry_jsic')` 参照.")],
    prefecture: Annotated[PrefectureParam, Field(description="都道府県 closed-set 48 値 ('東京'/'東京都'/'Tokyo' 自動正規化, 未知値は invalid_enum). 省略=全国+都道府県ミックス.")] = None,
    company_size: Annotated[Literal["sole", "small", "medium", "large"] | None, Field(description="個人=sole / 小=small / 中=medium / 大=large. target_types へ写像.")] = None,
    funding_purpose: Annotated[Literal["equipment", "rd", "export", "staffing", "digital", "green", "general"] | None, Field(description="使途. equipment/rd/export/staffing/digital/green/general.")] = None,
    from_date: Annotated[str | None, Field(description="起点 ISO8601 date (YYYY-MM-DD). default=today JST. 過去日は today JST に clamp + hint 出力.")] = None,
    horizon_months: Annotated[int, Field(ge=1, le=60, description="先何ヶ月までを timeline 射程にするか. Range [1, 60] = 最大 5 年. Default 36 (3 年). 短くするほど直近 quarter に焦点, 長くするほど先期の予算審議リスクを含む.")] = 36,
    limit: Annotated[int, Field(ge=1, le=100, description="timeline 全体の最大件数 (default 20).")] = 20,
) -> dict[str, Any]:
    """ONE-SHOT 3-YEAR ROADMAP: industry × prefecture × size × purpose で
    今後 N ヶ月の application window を JST 会計年度 quarter にバケット。
    Sort = opens_at ASC, deadline ASC tiebreak. tier S/A/B/C, excluded=0 のみ.
    deadline past + start future なら start を採用. cycle=annual の past start
    は +1 year に project. Errors: ``{"error": {"code","message","hint"}}``.

    Example:
        subsidy_roadmap_3yr(industry="製造業", prefecture="東京都",
                            company_size="small", funding_purpose="equipment",
                            horizon_months=36, limit=20)
        → {"timeline": [{"quarter": "2026Q2", "items": [...]}, ...], "total": N}

    When NOT to call:
        - For a SINGLE program detail → use get_program (much cheaper).
        - For free-text keyword search → use search_programs.
        - For currently-open windows only (not 3-year horizon) → use list_open_programs.
        - For 融資 / 補助金 dual-use combo → use subsidy_combo_finder.
        - For tax incentive timing → use search_tax_incentives + cliff dates.

    LIMITATIONS: 60% は 随時/rolling で start/end null → 漏れる
    (`list_open_programs` 参照). industry filter は heuristic.
    """
    from datetime import date as _date
    from datetime import timedelta as _td

    today = _jst_today_iso()
    pref_raw = prefecture
    pref_norm = _normalize_prefecture(prefecture)
    jsic_norm = _normalize_industry_jsic(industry)
    if not jsic_norm:
        return {"error": {"code": "invalid_industry",
                          "message": f"industry={industry!r} を JSIC に正規化できません.",
                          "hint": "enum_values(field='industry_jsic') で正規 letter (A..T) または和名を確認."}}

    input_warnings: list[dict[str, Any]] = []
    if pref_raw and not _is_known_prefecture(pref_raw):
        input_warnings.append({
            "field": "prefecture",
            "code": "unknown_prefecture",
            "value": pref_raw,
            "normalized_to": pref_norm,
            "message": (
                f"prefecture={pref_raw!r} は正規の都道府県に一致せず。"
                "フィルタを無効化し全国ベースで返しました。正しい例: '東京' / '東京都' / 'Tokyo'。"
            ),
            "retry_with": ["enum_values(field='prefecture')"],
        })
        pref_norm = None

    hints: list[str] = []
    eff_from = from_date or today
    if from_date and from_date < today:
        hints.append(f"from_date={from_date!r} は past のため today JST ({today}) に clamp しました.")
        eff_from = today
    try:
        from_d = _date.fromisoformat(eff_from)
    except Exception:
        return {"error": {"code": "invalid_from_date",
                          "message": f"from_date={from_date!r} は ISO8601 date でない.",
                          "hint": "YYYY-MM-DD で渡してください. 例 '2026-05-01'."}}
    horizon_iso = (from_d + _td(days=horizon_months * 31)).isoformat()

    where = ["excluded = 0", "tier IN ('S','A','B','C')",
             "application_window_json IS NOT NULL", "application_window_json != ''"]
    params: list[Any] = []
    if pref_norm:
        where.append("(prefecture = ? OR prefecture IS NULL OR prefecture = '')")
        params.append(pref_norm)
    if company_size and company_size in _SIZE_MAP:
        sz = []
        for tt in _SIZE_MAP[company_size]:
            sz.append("target_types_json LIKE ?")
            params.append(f"%{tt}%")
        where.append("(target_types_json IS NULL OR target_types_json = '' OR " + " OR ".join(sz) + ")")
    if funding_purpose and funding_purpose in _FP_MAP:
        fp = []
        for v in _FP_MAP[funding_purpose]:
            fp.append("funding_purpose_json LIKE ?")
            params.append(f"%{v}%")
        where.append("(" + " OR ".join(fp) + ")")

    sql = (f"SELECT unified_id, primary_name, program_kind, prefecture, "
           f"amount_max_man_yen, official_url, source_url, application_window_json "
           f"FROM programs WHERE {' AND '.join(where)} LIMIT 800")
    conn = connect()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    timeline: list[dict[str, Any]] = []
    for r in rows:
        try:
            w = json.loads(r["application_window_json"] or "{}")
        except json.JSONDecodeError:
            continue
        start, end, cycle = w.get("start_date"), w.get("end_date"), w.get("cycle")
        opens_at = start if (start and start >= eff_from) else _project_next_opens(start, cycle, eff_from)
        deadline = end if (end and end >= eff_from) else None
        anchor = opens_at or deadline
        if not anchor or anchor > horizon_iso:
            continue
        amount_yen = int(r["amount_max_man_yen"] * 10_000) if r["amount_max_man_yen"] else None
        why = [f"industry={jsic_norm}"]
        if company_size:
            why.append(f"size={company_size}")
        if funding_purpose:
            why.append(f"purpose={funding_purpose}")
        if pref_norm and r["prefecture"] == pref_norm:
            why.append(f"pref-match={pref_norm}")
        timeline.append({
            "quarter": _jst_fy_quarter(anchor),
            "program_id": r["unified_id"], "program_name": r["primary_name"],
            "program_kind": r["program_kind"],
            "opens_at": opens_at, "application_deadline": deadline,
            "max_amount_yen": amount_yen,
            "source_url": r["source_url"] or r["official_url"],
            "why": " / ".join(why),
        })

    timeline.sort(key=lambda x: (x["opens_at"] or "9999", x["application_deadline"] or "9999"))
    timeline = timeline[:limit]
    by_q: dict[str, int] = {}
    total = 0
    for e in timeline:
        by_q[e["quarter"]] = by_q.get(e["quarter"], 0) + 1
        if e["max_amount_yen"]:
            total += e["max_amount_yen"]

    if not timeline:
        envelope: dict[str, Any] = {"error": {"code": "empty_roadmap",
                          "message": f"industry={jsic_norm} prefecture={pref_norm} で 今後 {horizon_months} ヶ月 の application window が 0 件.",
                          "hint": "(a) prefecture を外す, (b) funding_purpose を緩める, (c) horizon_months=60 で広げる, (d) `list_open_programs` で 随時/rolling 募集を参照."}}
        if input_warnings:
            envelope["input_warnings"] = input_warnings
        return envelope
    if len(timeline) < 5:
        hints.append(f"timeline={len(timeline)} 件のみ. funding_purpose を外すか horizon_months を広げると拾える可能性あり.")
    payload: dict[str, Any] = {
        "industry": jsic_norm, "prefecture": pref_norm, "from_date": eff_from,
        "horizon_end": horizon_iso, "timeline": timeline,
        "total_ceiling_yen": total, "by_quarter_count": dict(sorted(by_q.items())),
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if hints:
        payload["hint"] = " / ".join(hints)
    if input_warnings:
        payload["input_warnings"] = input_warnings
    return payload


# ===========================================================================
# 2026-04-24 expansion: laws / court_decisions / bids / tax_rulesets /
# invoice_registrants + cross-dataset glue.
#
# Error pattern for these tools: return {"error": "...", "code": "no_matching_records"
# | "invalid_enum" | "internal"} instead of raising, matching the typed
# contract the caller asked for. (Pre-existing tools raise ValueError; we
# don't touch those — the request was explicit about preserving the 15.)
# ===========================================================================


_LAW_ID_RE = r"^LAW-[0-9a-f]{10}$"
_HAN_ID_RE = r"^HAN-[0-9a-f]{10}$"
_BID_ID_RE = r"^BID-[0-9a-f]{10}$"
_TAX_ID_RE = r"^TAX-[0-9a-f]{10}$"
_INVOICE_REG_RE = r"^T\d{13}$"


def _err(
    code: str,
    message: str,
    hint: str | None = None,
    retry_with: list[str] | None = None,
) -> dict[str, Any]:
    """Standard structured error for the expansion tools.

    Keeps legacy top-level keys (`error`, `code`) for backward compat. Adds
    optional `hint` (human-readable next step) and `retry_with` (list of
    alternative tools) — agent 7/10 finding: these let the LLM self-correct
    on 1 retry instead of giving up.
    """
    out: dict[str, Any] = {"error": message, "code": code}
    if hint:
        out["hint"] = hint
    if retry_with:
        out["retry_with"] = retry_with
    return out


def _json_list(row: sqlite3.Row, col: str) -> list[str]:
    raw = row[col]
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(x) for x in parsed if x is not None]


def _row_to_law_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "unified_id": row["unified_id"],
        "law_number": row["law_number"],
        "law_title": row["law_title"],
        "law_short_title": row["law_short_title"],
        "law_type": row["law_type"],
        "ministry": row["ministry"],
        "promulgated_date": row["promulgated_date"],
        "enforced_date": row["enforced_date"],
        "last_amended_date": row["last_amended_date"],
        "revision_status": row["revision_status"],
        "superseded_by_law_id": row["superseded_by_law_id"],
        "article_count": row["article_count"],
        "full_text_url": row["full_text_url"],
        "summary": row["summary"],
        "subject_areas": _json_list(row, "subject_areas_json"),
        "source_url": row["source_url"],
        "source_checksum": row["source_checksum"],
        "confidence": row["confidence"],
        "fetched_at": row["fetched_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_court_decision_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "unified_id": row["unified_id"],
        "case_name": row["case_name"],
        "case_number": row["case_number"],
        "court": row["court"],
        "court_level": row["court_level"],
        "decision_date": row["decision_date"],
        "decision_type": row["decision_type"],
        "subject_area": row["subject_area"],
        "related_law_ids": _json_list(row, "related_law_ids_json"),
        "key_ruling": row["key_ruling"],
        "parties_involved": row["parties_involved"],
        "impact_on_business": row["impact_on_business"],
        "precedent_weight": row["precedent_weight"],
        "full_text_url": row["full_text_url"],
        "pdf_url": row["pdf_url"],
        "source_url": row["source_url"],
        "source_excerpt": row["source_excerpt"],
        "source_checksum": row["source_checksum"],
        "confidence": row["confidence"],
        "fetched_at": row["fetched_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_bid_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "unified_id": row["unified_id"],
        "bid_title": row["bid_title"],
        "bid_kind": row["bid_kind"],
        "procuring_entity": row["procuring_entity"],
        "procuring_houjin_bangou": row["procuring_houjin_bangou"],
        "ministry": row["ministry"],
        "prefecture": row["prefecture"],
        "program_id_hint": row["program_id_hint"],
        "announcement_date": row["announcement_date"],
        "question_deadline": row["question_deadline"],
        "bid_deadline": row["bid_deadline"],
        "decision_date": row["decision_date"],
        "budget_ceiling_yen": row["budget_ceiling_yen"],
        "awarded_amount_yen": row["awarded_amount_yen"],
        "winner_name": row["winner_name"],
        "winner_houjin_bangou": row["winner_houjin_bangou"],
        "participant_count": row["participant_count"],
        "bid_description": row["bid_description"],
        "eligibility_conditions": row["eligibility_conditions"],
        "classification_code": row["classification_code"],
        "source_url": row["source_url"],
        "source_excerpt": row["source_excerpt"],
        "source_checksum": row["source_checksum"],
        "confidence": row["confidence"],
        "fetched_at": row["fetched_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_tax_ruleset_dict(row: sqlite3.Row) -> dict[str, Any]:
    predicates_raw = row["eligibility_conditions_json"]
    predicates: Any = None
    if predicates_raw:
        try:
            predicates = json.loads(predicates_raw)
        except json.JSONDecodeError:
            predicates = None
    return {
        "unified_id": row["unified_id"],
        "ruleset_name": row["ruleset_name"],
        "tax_category": row["tax_category"],
        "ruleset_kind": row["ruleset_kind"],
        "effective_from": row["effective_from"],
        "effective_until": row["effective_until"],
        "related_law_ids": _json_list(row, "related_law_ids_json"),
        "eligibility_conditions": row["eligibility_conditions"],
        "eligibility_conditions_json": predicates,
        "rate_or_amount": row["rate_or_amount"],
        "calculation_formula": row["calculation_formula"],
        "filing_requirements": row["filing_requirements"],
        "authority": row["authority"],
        "authority_url": row["authority_url"],
        "source_url": row["source_url"],
        "source_excerpt": row["source_excerpt"],
        "source_checksum": row["source_checksum"],
        "confidence": row["confidence"],
        "fetched_at": row["fetched_at"],
        "updated_at": row["updated_at"],
    }


def _trim_tax_ruleset(rec: dict[str, Any], fields: str) -> dict[str, Any]:
    """Shape a tax_ruleset row for `fields ∈ {minimal, default, full}`.

    minimal (~200 B): core identifier + window + authority URL only.
    default (~900 B): + 400-char narrative, predicate JSON, related laws,
        rate/formula/filing. Drops source_excerpt/source_checksum.
    full    (~1.6 KB): raw (everything).
    """
    if fields == "full":
        return rec
    if fields == "minimal":
        return {
            "unified_id": rec["unified_id"],
            "ruleset_name": rec["ruleset_name"],
            "tax_category": rec["tax_category"],
            "ruleset_kind": rec["ruleset_kind"],
            "effective_from": rec["effective_from"],
            "effective_until": rec["effective_until"],
            "authority_url": rec["authority_url"],
            "source_url": rec["source_url"],
        }
    # default: drop source_excerpt + source_checksum, truncate narrative.
    narrative = rec.get("eligibility_conditions") or ""
    if isinstance(narrative, str) and len(narrative) > 400:
        narrative = narrative[:397] + "…"
    out = {k: v for k, v in rec.items()
           if k not in ("source_excerpt", "source_checksum")}
    out["eligibility_conditions"] = narrative
    return out


def _row_to_invoice_registrant_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "invoice_registration_number": row["invoice_registration_number"],
        "houjin_bangou": row["houjin_bangou"],
        "normalized_name": row["normalized_name"],
        "address_normalized": row["address_normalized"],
        "prefecture": row["prefecture"],
        "registered_date": row["registered_date"],
        "revoked_date": row["revoked_date"],
        "expired_date": row["expired_date"],
        "registrant_kind": row["registrant_kind"],
        "trade_name": row["trade_name"],
        "last_updated_nta": row["last_updated_nta"],
        "source_url": row["source_url"],
        "source_checksum": row["source_checksum"],
        "confidence": row["confidence"],
        "fetched_at": row["fetched_at"],
        "updated_at": row["updated_at"],
    }


_INVOICE_ATTRIBUTION: dict[str, Any] = {
    "source": "国税庁適格請求書発行事業者公表サイト（国税庁）",
    "source_url": "https://www.invoice-kohyo.nta.go.jp/",
    "license": "公共データ利用規約 第1.0版 (PDL v1.0)",
    "edited": True,
    "notice": (
        "本データは国税庁公表データを編集加工したものであり、原データと完全には一致しません。"
        "公表データは本API経由ではなく、発行元サイトで最新のものを確認してください。"
    ),
}


# ---------------------------------------------------------------------------
# Laws (3)
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def search_laws(
    q: Annotated[
        str | None,
        Field(
            description=(
                "Free-text over law_title + law_short_title + law_number + "
                "summary. FTS5 trigram with quoted-phrase workaround for 2+ "
                "character kanji compounds; terms < 3 chars fall back to LIKE."
            ),
        ),
    ] = None,
    law_type: Annotated[
        Literal[
            "constitution",
            "act",
            "cabinet_order",
            "imperial_order",
            "ministerial_ordinance",
            "rule",
            "notice",
            "guideline",
        ]
        | None,
        Field(description="Filter by law_type. e-Gov 法令分類."),
    ] = None,
    ministry: Annotated[
        str | None,
        Field(description="所管府省 exact match (e.g. '農林水産省')."),
    ] = None,
    currently_effective_only: Annotated[
        bool,
        Field(
            description=(
                "When true (default), only revision_status='current' rows "
                "are returned. Flip to false to include 'superseded' rows."
            ),
        ),
    ] = True,
    include_repealed: Annotated[
        bool,
        Field(
            description=(
                "When false (default), revision_status='repealed' rows are "
                "excluded. Flip to true for historical research."
            ),
        ),
    ] = False,
    limit: Annotated[int, Field(ge=1, le=100, description="返却する最大行数. Range [1, 100]. Default 20. 増やすほど token 消費が比例 — 確認用は 5-10, 一覧表示は 20-50 が現実的.")] = 20,
    offset: Annotated[int, Field(ge=0, description="Pagination offset (0-based row count to skip). Default 0. Combine with `limit` for paging through `total`.")] = 0,
) -> dict[str, Any]:
    """DISCOVER-LAW: search e-Gov 法令 catalog (~3,400 憲法 / 法律 / 政令 / 勅令 / 府省令 / 規則 / 告示 / ガイドライン harvested under CC-BY 4.0). Primary surface for "what is the 根拠法 of 補助金 X" and "which statute does this article cite" questions. Returns law_title + number + enforced_date + ministry + summary + lineage.

    CHAIN:
      → `get_law(unified_id)` for full detail on a single row.
      → `list_law_revisions(unified_id)` to walk superseded_by_law_id chain.
      → `find_cases_by_law(law_unified_id)` for 判例 citing this statute.
      → `trace_program_to_law(program_unified_id)` for the reverse edge.

    WHEN NOT:
      - `search_programs` instead for 補助金 discovery — laws is statute-only.
      - `search_tax_rules` instead for 税制 Q&A / decision rulesets.

    LIMITATIONS:
      - Same FTS5 trigram single-kanji false-positive gotcha as search_programs.
      - `currently_effective_only=True` hides superseded rows; disable for diachronic analysis.
    """
    conn = connect()
    try:
        where: list[str] = []
        params: list[Any] = []
        join_fts = False

        from jpintel_mcp.api.programs import KANA_EXPANSIONS, _build_fts_match

        if q:
            q_clean = q.strip()
            if q_clean:
                terms: list[str] = [q_clean]
                if q_clean in KANA_EXPANSIONS:
                    terms.extend(KANA_EXPANSIONS[q_clean])
                shortest = min(len(t) for t in terms)
                if shortest >= 3:
                    join_fts = True
                    params.append(_build_fts_match(q_clean))
                else:
                    like_clauses: list[str] = []
                    for t in terms:
                        like_clauses.append(
                            "(law_title LIKE ? "
                            "OR COALESCE(law_short_title,'') LIKE ? "
                            "OR law_number LIKE ? "
                            "OR COALESCE(summary,'') LIKE ?)"
                        )
                        like = f"%{t}%"
                        params.extend([like, like, like, like])
                    where.append("(" + " OR ".join(like_clauses) + ")")

        if law_type:
            where.append("law_type = ?")
            params.append(law_type)
        if ministry:
            where.append("ministry = ?")
            params.append(ministry)
        if currently_effective_only:
            where.append("revision_status = 'current'")
        if not include_repealed:
            where.append("revision_status != 'repealed'")

        if join_fts:
            base_from = "laws_fts JOIN laws USING(unified_id)"
            where_clause = "laws_fts MATCH ?"
            if where:
                where_clause = where_clause + " AND " + " AND ".join(where)
        else:
            base_from = "laws"
            where_clause = " AND ".join(where) if where else "1=1"

        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM {base_from} WHERE {where_clause}", params
        ).fetchone()

        rev_order = (
            "CASE revision_status "
            "WHEN 'current' THEN 0 WHEN 'superseded' THEN 1 "
            "WHEN 'repealed' THEN 2 ELSE 3 END"
        )
        order_parts: list[str] = [rev_order]
        if join_fts:
            order_parts.append("laws_fts.rank")
        order_parts.extend(
            ["COALESCE(enforced_date, promulgated_date, '') DESC", "unified_id"]
        )
        order_sql = "ORDER BY " + ", ".join(order_parts)

        rows = conn.execute(
            f"SELECT laws.* FROM {base_from} WHERE {where_clause} {order_sql} "
            f"LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        payload: dict[str, Any] = {
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": [_row_to_law_dict(r) for r in rows],
        }
        if total == 0:
            payload["hint"] = _empty_laws_hint(q, ministry, law_type)
            payload["retry_with"] = [
                "search_tax_rules",
                "get_am_tax_rule",
                "search_programs",
            ]
            payload.update(_expansion_coverage_state("laws", conn))
        return payload
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def get_law(
    unified_id: Annotated[
        str,
        Field(
            description="LAW-<10 hex> unified_id from search_laws results.",
            pattern=_LAW_ID_RE,
        ),
    ],
) -> dict[str, Any]:
    """DETAIL-LAW: fetch a single 法令 row by LAW-<10 hex> unified_id. Returns full record with summary, article_count, ministry, enforced_date, superseded_by_law_id lineage, plus source_url + fetched_at. Provenance: e-Gov 法令 API V2 (CC-BY 4.0).

    Example:
        get_law(unified_id="LAW-1a2b3c4d5e")
        → {"unified_id": "LAW-1a2b3c4d5e", "law_name": "...", "ministry": "...",
           "article_count": 213, "revision_status": "current", "source_url": "..."}

    When NOT to call:
        - Without a LAW-<10 hex> unified_id → use search_laws first.
        - For full article text → use get_law_article_am (this returns law metadata).
        - For 判例 / case detail → use get_court_decision instead.
        - For tax rulesets derived from a law → use get_tax_rule.

    CHAIN:
      ← `search_laws` produces the unified_id.
      → `list_law_revisions(unified_id)` when revision_status != 'current'.
      → `find_cases_by_law(law_unified_id)` for 判例 citing this law.
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM laws WHERE unified_id = ?", (unified_id,)
        ).fetchone()
        if row is None:
            return _err("no_matching_records", f"law not found: {unified_id}")
        return _row_to_law_dict(row)
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def list_law_revisions(
    unified_id: Annotated[
        str,
        Field(
            description=(
                "LAW-<10 hex> unified_id. The tool walks the superseded_by_law_id "
                "chain forward (this row → its successor → … → current) and "
                "backward (predecessors pointing at this row)."
            ),
            pattern=_LAW_ID_RE,
        ),
    ],
    max_hops: Annotated[
        int,
        Field(
            ge=1,
            le=20,
            description="Safety cap on chain depth per direction. Default 10.",
        ),
    ] = 10,
) -> dict[str, Any]:
    """LINEAGE-LAW: trace the revision chain for a 法令 — walks `superseded_by_law_id` forward and backward to reconstruct (predecessors → this → successors → current). Essential for diachronic legal analysis ("which law was in force on 2023-06-01?").

    Returns:
      - predecessors[]: rows where superseded_by_law_id == given unified_id, recursively
      - self: the starting row
      - successors[]: forward chain through superseded_by_law_id pointers
      - current_id: terminal row in the successor chain (revision_status='current' or chain tail)

    CHAIN:
      ← `search_laws` / `get_law` produces the unified_id.
      → `find_cases_by_law(law_unified_id=current_id)` to run 判例 against the current form.

    LIMITATIONS:
      - Chain integrity depends on ingest; orphan pointers return an empty successors list without error.
      - Cycles are prevented by max_hops + a visited-set.
    """
    conn = connect()
    try:
        start = conn.execute(
            "SELECT * FROM laws WHERE unified_id = ?", (unified_id,)
        ).fetchone()
        if start is None:
            return _err("seed_not_found", f"law not found: {unified_id}")

        # Successor walk
        successors: list[dict[str, Any]] = []
        visited: set[str] = {unified_id}
        current = start
        for _ in range(max_hops):
            nxt_id = current["superseded_by_law_id"]
            if not nxt_id or nxt_id in visited:
                break
            visited.add(nxt_id)
            nxt_row = conn.execute(
                "SELECT * FROM laws WHERE unified_id = ?", (nxt_id,)
            ).fetchone()
            if nxt_row is None:
                break
            successors.append(_row_to_law_dict(nxt_row))
            current = nxt_row
        current_id = current["unified_id"]

        # Predecessor walk (rows that point AT this one)
        predecessors: list[dict[str, Any]] = []
        frontier: list[str] = [unified_id]
        seen_pred: set[str] = {unified_id}
        for _ in range(max_hops):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            next_frontier: list[str] = []
            pred_rows = conn.execute(
                f"SELECT * FROM laws WHERE superseded_by_law_id IN ({placeholders})",
                frontier,
            ).fetchall()
            for pr in pred_rows:
                if pr["unified_id"] in seen_pred:
                    continue
                seen_pred.add(pr["unified_id"])
                predecessors.append(_row_to_law_dict(pr))
                next_frontier.append(pr["unified_id"])
            frontier = next_frontier

        # Diagnostic: when both chains are empty, the caller's most common
        # assumption ("I just hit an orphan") is usually wrong — most rows in
        # the current ingest are singletons because supersede pointers have
        # not been back-filled yet. Say so out loud so the LLM does not
        # invent a story to fill the silence.
        chain_status: str
        diagnostic: str | None = None
        if not predecessors and not successors:
            chain_status = "singleton"
            rev_status = start.get("revision_status") if hasattr(start, "get") else (start["revision_status"] if "revision_status" in start.keys() else None)  # noqa: SIM118
            diagnostic = (
                "revision_chain_not_populated: this row has no predecessors and "
                "no successors. supersede pointers across the laws table are "
                "still being back-filled (2026-04-25 state). Treat the `self` "
                "row as the operative text as of today, but verify against "
                "e-Gov 法令検索 for silent revisions. "
                f"revision_status={rev_status!r}."
            )
        elif predecessors and successors:
            chain_status = "complete"
        elif successors:
            chain_status = "forward_only"
        else:
            chain_status = "backward_only"

        payload: dict[str, Any] = {
            "self": _row_to_law_dict(start),
            "predecessors": predecessors,
            "successors": successors,
            "current_id": current_id,
            "max_hops": max_hops,
            "chain_status": chain_status,
        }
        if diagnostic:
            payload["diagnostic"] = diagnostic
        return payload
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Court decisions (3)
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def search_court_decisions(
    q: Annotated[
        str | None,
        Field(
            description=(
                "Free-text over case_name + subject_area + key_ruling + "
                "impact_on_business. FTS5 trigram with quoted-phrase "
                "workaround; terms < 3 chars fall back to LIKE."
            ),
        ),
    ] = None,
    court_level: Annotated[
        Literal["supreme", "high", "district", "summary", "family"] | None,
        Field(description="裁判所階層. supreme > high > district > summary > family."),
    ] = None,
    decision_type: Annotated[
        Literal["判決", "決定", "命令"] | None,
        Field(
            description=(
                "判断の形式 (closed-set). '判決' = 本案判決 (民事/刑事/行政), "
                "'決定' = 訴訟手続上の決定 (保全 / 執行 等), '命令' = 裁判官 "
                "単独命令 (支払督促 等). None = no filter."
            )
        ),
    ] = None,
    subject_area: Annotated[
        str | None,
        Field(description="分野 LIKE match (e.g. '租税', '補助金適正化法')."),
    ] = None,
    references_law_id: Annotated[
        str | None,
        Field(
            description=(
                "Filter rows whose related_law_ids_json array contains this "
                "LAW-<10 hex> unified_id."
            ),
            pattern=_LAW_ID_RE,
        ),
    ] = None,
    decided_from: Annotated[
        str | None,
        Field(description="ISO date lower bound on decision_date (YYYY-MM-DD)."),
    ] = None,
    decided_to: Annotated[
        str | None,
        Field(description="ISO date upper bound on decision_date (YYYY-MM-DD)."),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="返却する最大行数. Range [1, 100]. Default 20. 増やすほど token 消費が比例 — 確認用は 5-10, 一覧表示は 20-50 が現実的.")] = 20,
    offset: Annotated[
        int,
        Field(
            ge=0,
            description=(
                "Pagination offset (0-based). Default 0. Combine with `limit` "
                "to walk past page 1 — total result count returned in `total`."
            ),
        ),
    ] = 0,
) -> dict[str, Any]:
    """DISCOVER-CASE: search 判例 (courts.go.jp hanrei_jp primary source). Ordered by precedent_weight (binding > persuasive > informational), then court_level (supreme > high > district …), then most-recent decision_date. Commercial aggregators (D1 Law / Westlaw / LEX/DB) are banned at ingest.

    CHAIN:
      → `get_court_decision(unified_id)` for full record.
      → `find_precedents_by_statute(law_unified_id)` for statute→rulings.
      → `find_cases_by_law(law_unified_id, include_enforcement=True)` to combine with 会計検査院.

    WHEN NOT:
      - `search_enforcement_cases` instead for 会計検査院 reports (not court rulings).
      - `search_laws` instead for statute text.

    LIMITATIONS:
      - DATA AVAILABILITY: 0 rows loaded as of 2026-04-24. Schema and ingest infrastructure are pre-built; initial data load is coming post-launch. Queries will return empty results until then.
      - Same FTS trigram single-kanji false-positive gotcha.
      - `references_law_id` is a JSON-array substring LIKE — accurate because unified_ids are fixed-width.
    """
    conn = connect()
    try:
        where: list[str] = []
        params: list[Any] = []
        join_fts = False

        from jpintel_mcp.api.programs import KANA_EXPANSIONS, _build_fts_match

        if q:
            q_clean = q.strip()
            if q_clean:
                terms: list[str] = [q_clean]
                if q_clean in KANA_EXPANSIONS:
                    terms.extend(KANA_EXPANSIONS[q_clean])
                shortest = min(len(t) for t in terms)
                if shortest >= 3:
                    join_fts = True
                    params.append(_build_fts_match(q_clean))
                else:
                    like_clauses: list[str] = []
                    for t in terms:
                        like_clauses.append(
                            "(case_name LIKE ? "
                            "OR COALESCE(subject_area,'') LIKE ? "
                            "OR COALESCE(key_ruling,'') LIKE ? "
                            "OR COALESCE(impact_on_business,'') LIKE ?)"
                        )
                        like = f"%{t}%"
                        params.extend([like, like, like, like])
                    where.append("(" + " OR ".join(like_clauses) + ")")

        if court_level:
            where.append("court_level = ?")
            params.append(court_level)
        if decision_type:
            where.append("decision_type = ?")
            params.append(decision_type)
        if subject_area:
            where.append("COALESCE(subject_area,'') LIKE ?")
            params.append(f"%{subject_area}%")
        if references_law_id:
            where.append("COALESCE(related_law_ids_json,'') LIKE ?")
            params.append(f'%"{references_law_id}"%')
        if decided_from:
            where.append("decision_date >= ?")
            params.append(decided_from)
        if decided_to:
            where.append("decision_date <= ?")
            params.append(decided_to)

        if join_fts:
            base_from = "court_decisions_fts JOIN court_decisions USING(unified_id)"
            where_clause = "court_decisions_fts MATCH ?"
            if where:
                where_clause = where_clause + " AND " + " AND ".join(where)
        else:
            base_from = "court_decisions"
            where_clause = " AND ".join(where) if where else "1=1"

        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM {base_from} WHERE {where_clause}", params
        ).fetchone()

        weight_order = (
            "CASE precedent_weight "
            "WHEN 'binding' THEN 0 WHEN 'persuasive' THEN 1 "
            "WHEN 'informational' THEN 2 ELSE 3 END"
        )
        level_order = (
            "CASE court_level "
            "WHEN 'supreme' THEN 0 WHEN 'high' THEN 1 WHEN 'district' THEN 2 "
            "WHEN 'summary' THEN 3 WHEN 'family' THEN 4 ELSE 5 END"
        )
        order_parts: list[str] = [weight_order, level_order]
        if join_fts:
            order_parts.append("court_decisions_fts.rank")
        order_parts.extend(["COALESCE(decision_date, '') DESC", "unified_id"])
        order_sql = "ORDER BY " + ", ".join(order_parts)

        rows = conn.execute(
            f"SELECT court_decisions.* FROM {base_from} WHERE {where_clause} "
            f"{order_sql} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        payload: dict[str, Any] = {
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": [_row_to_court_decision_dict(r) for r in rows],
        }
        if total == 0:
            payload["hint"] = _empty_court_decisions_hint(q)
            payload["retry_with"] = [
                "search_laws",
                "find_precedents_by_statute",
                "search_enforcement_cases",
            ]
            payload.update(_expansion_coverage_state("court_decisions", conn))
        return payload
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def get_court_decision(
    unified_id: Annotated[
        str,
        Field(
            description="HAN-<10 hex> unified_id from search_court_decisions.",
            pattern=_HAN_ID_RE,
        ),
    ],
) -> dict[str, Any]:
    """DETAIL-CASE: fetch a single 判例 with full source lineage (courts.go.jp primary). Returns case_name, court, decision_date, key_ruling, impact_on_business, related_law_ids, precedent_weight, source_url + source_excerpt + fetched_at.

    Example:
        get_court_decision(unified_id="HAN-0123abcdef")
        → {"unified_id": "HAN-0123abcdef", "case_name": "...", "court": "...",
           "key_ruling": "...", "related_law_ids": ["LAW-..."], "source_url": "..."}

    When NOT to call:
        - Without a HAN-<10 hex> unified_id → use search_court_decisions first.
        - For 行政処分 / 会計検査院 audit findings → use get_enforcement_case instead.
        - For statutory text itself → use get_law (this returns the ruling, not the law).
        - To trace ALL precedents citing one statute → use find_precedents_by_statute.

    CHAIN:
      ← `search_court_decisions` or `find_precedents_by_statute` produces the unified_id.
      → `get_law(law_unified_id)` for each related_law_ids entry.
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM court_decisions WHERE unified_id = ?", (unified_id,)
        ).fetchone()
        if row is None:
            return _err("no_matching_records", f"court decision not found: {unified_id}")
        return _row_to_court_decision_dict(row)
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def find_precedents_by_statute(
    law_unified_id: Annotated[
        str,
        Field(
            description="LAW-<10 hex> unified_id to trace rulings against.",
            pattern=_LAW_ID_RE,
        ),
    ],
    article_citation: Annotated[
        str | None,
        Field(
            description=(
                "Optional narrowing. When supplied, additionally require the "
                "article string (e.g. '第22条') to appear in key_ruling or "
                "source_excerpt. Honest contains-check — not a structured join."
            ),
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="返却する最大行数. Range [1, 100]. Default 20. 増やすほど token 消費が比例 — 確認用は 5-10, 一覧表示は 20-50 が現実的.")] = 20,
    offset: Annotated[int, Field(ge=0, description="Pagination offset (0-based row count to skip). Default 0. Combine with `limit` for paging through `total`.")] = 0,
) -> dict[str, Any]:
    """TRACE-STATUTE: given a LAW-<10 hex> unified_id, return 判例 citing that statute via related_law_ids_json. Ordered by precedent_weight → court_level → decision_date. When `article_citation` is set, we additionally require the article string to appear in key_ruling or source_excerpt (best-effort narrowing).

    Example:
        find_precedents_by_statute(law_unified_id="LAW-1a2b3c4d5e",
                                   article_citation="第22条", limit=20)
        → {"results": [{"unified_id": "HAN-...", "case_name": "...",
                        "precedent_weight": 0.82, ...}], "total": N}

    When NOT to call:
        - For full free-text 判例 search → use search_court_decisions.
        - To fetch ONE 判例's full record → use get_court_decision (this returns a list).
        - To pull 会計検査院 audit hits too → use find_cases_by_law(include_enforcement=True).
        - Without a LAW-<10 hex> id → use search_laws to resolve a name to id first.

    CHAIN:
      ← `search_laws` / `get_law` produces the law_unified_id.
      → `get_court_decision(unified_id)` for each hit's full record.
      → `find_cases_by_law(law_unified_id, include_enforcement=True)` to also pull 会計検査院.

    LIMITATIONS:
      - Article narrowing is best-effort (string contains), not a structured (law_id, article) FK join.
    """
    conn = connect()
    try:
        law_row = conn.execute(
            "SELECT unified_id FROM laws WHERE unified_id = ?", (law_unified_id,)
        ).fetchone()
        if law_row is None:
            return _err("seed_not_found", f"law not found: {law_unified_id}")

        where: list[str] = ["COALESCE(related_law_ids_json,'') LIKE ?"]
        params: list[Any] = [f'%"{law_unified_id}"%']

        if article_citation:
            article = article_citation.strip()
            where.append(
                "(COALESCE(key_ruling,'') LIKE ? "
                "OR COALESCE(source_excerpt,'') LIKE ?)"
            )
            like_article = f"%{article}%"
            params.extend([like_article, like_article])

        where_sql = " AND ".join(where)

        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM court_decisions WHERE {where_sql}", params
        ).fetchone()

        weight_order = (
            "CASE precedent_weight "
            "WHEN 'binding' THEN 0 WHEN 'persuasive' THEN 1 "
            "WHEN 'informational' THEN 2 ELSE 3 END"
        )
        level_order = (
            "CASE court_level "
            "WHEN 'supreme' THEN 0 WHEN 'high' THEN 1 WHEN 'district' THEN 2 "
            "WHEN 'summary' THEN 3 WHEN 'family' THEN 4 ELSE 5 END"
        )
        rows = conn.execute(
            f"""SELECT * FROM court_decisions
                WHERE {where_sql}
                ORDER BY {weight_order}, {level_order},
                         COALESCE(decision_date, '') DESC,
                         unified_id
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()

        payload: dict[str, Any] = {
            "law_unified_id": law_unified_id,
            "article_citation": article_citation,
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": [_row_to_court_decision_dict(r) for r in rows],
        }
        if total == 0:
            payload["hint"] = _empty_precedents_hint(article_citation)
            payload["retry_with"] = [
                "find_cases_by_law",
                "search_enforcement_cases",
            ]
            payload.update(_expansion_coverage_state("court_decisions", conn))
        return payload
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bids (3)
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def search_bids(
    q: Annotated[
        str | None,
        Field(
            description=(
                "Free-text over bid_title + bid_description + procuring_entity "
                "+ winner_name. FTS5 trigram; < 3 chars fall back to LIKE."
            ),
        ),
    ] = None,
    bid_kind: Annotated[
        Literal["open", "selective", "negotiated", "kobo_subsidy"] | None,
        Field(
            description=(
                "open=一般競争, selective=指名競争, negotiated=随意契約, "
                "kobo_subsidy=公募型補助."
            ),
        ),
    ] = None,
    procuring_houjin_bangou: Annotated[
        str | None,
        Field(
            description="Exact 13-digit 法人番号 of procuring entity.",
            pattern=r"^\d{13}$",
        ),
    ] = None,
    winner_houjin_bangou: Annotated[
        str | None,
        Field(
            description=(
                "13 桁 法人番号 of 落札者 (NTA 法人番号公表サイト準拠). "
                "exact match. ハイフン / 'T' prefix / 全角は事前に caller 側で除去. "
                "例: '3010001084451' で当該落札者の入札一覧."
            ),
            pattern=r"^\d{13}$",
        ),
    ] = None,
    program_id_hint: Annotated[
        str | None,
        Field(
            description=(
                "Exact programs.unified_id (UNI-* / TAX-* / LAW-*) — bids "
                "linked to a program via ingest matchers."
            ),
        ),
    ] = None,
    min_amount_yen: Annotated[
        int | None,
        Field(
            ge=0,
            description=(
                "Inclusive lower bound on awarded_amount_yen. Rows with NULL "
                "awarded_amount_yen are excluded when this is set."
            ),
        ),
    ] = None,
    max_amount_yen: Annotated[
        int | None,
        Field(
            ge=0,
            description="Inclusive upper bound on awarded_amount_yen.",
        ),
    ] = None,
    deadline_after: Annotated[
        str | None,
        Field(
            description=(
                "ISO date (YYYY-MM-DD) — inclusive lower bound on bid_deadline. "
                "Useful for 'still-open' queries."
            ),
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="返却する最大行数. Range [1, 100]. Default 20. 増やすほど token 消費が比例 — 確認用は 5-10, 一覧表示は 20-50 が現実的.")] = 20,
    offset: Annotated[int, Field(ge=0, description="Pagination offset (0-based row count to skip). Default 0. Combine with `limit` for paging through `total`.")] = 0,
) -> dict[str, Any]:
    """DISCOVER-BID: search 入札 (GEPS 政府電子調達 CC-BY 4.0 + self-gov top-7 JV flows + ministry *.go.jp). Primary-source only — NJSS-style aggregators are banned at ingest. Headline query: "vendors that won 5000万円+ 公募型補助 in 2025".

    CHAIN:
      → `get_bid(unified_id)` for full record.
      → `bid_eligible_for_profile(unified_id, business_profile)` to screen an applicant.
      → `search_programs(unified_id=program_id_hint)` to tie a bid to the funded 補助事業.

    WHEN NOT:
      - `search_programs` instead for 補助金 募集 — bids is procurement (after-the-fact), not funded-program discovery.

    LIMITATIONS:
      - DATA AVAILABILITY: 0 rows loaded as of 2026-04-24. Schema and ingest infrastructure are pre-built; initial data load is coming post-launch. Queries will return empty results until then.
      - Same FTS trigram gotcha; quote 2+ char kanji compounds.
      - `program_id_hint` is a soft ref (no FK) — may be NULL on 公募型補助 / stale.
    """
    conn = connect()
    try:
        where: list[str] = []
        params: list[Any] = []
        join_fts = False

        from jpintel_mcp.api.programs import _build_fts_match

        if q:
            q_clean = q.strip()
            if q_clean:
                if len(q_clean) >= 3:
                    join_fts = True
                    params.append(_build_fts_match(q_clean))
                else:
                    like = f"%{q_clean}%"
                    where.append(
                        "(bid_title LIKE ? "
                        "OR COALESCE(bid_description,'') LIKE ? "
                        "OR procuring_entity LIKE ? "
                        "OR COALESCE(winner_name,'') LIKE ?)"
                    )
                    params.extend([like, like, like, like])

        if bid_kind:
            where.append("bid_kind = ?")
            params.append(bid_kind)
        if procuring_houjin_bangou:
            where.append("procuring_houjin_bangou = ?")
            params.append(procuring_houjin_bangou)
        if winner_houjin_bangou:
            where.append("winner_houjin_bangou = ?")
            params.append(winner_houjin_bangou)
        if program_id_hint:
            where.append("program_id_hint = ?")
            params.append(program_id_hint)
        if min_amount_yen is not None:
            where.append("awarded_amount_yen IS NOT NULL AND awarded_amount_yen >= ?")
            params.append(min_amount_yen)
        if max_amount_yen is not None:
            where.append("awarded_amount_yen IS NOT NULL AND awarded_amount_yen <= ?")
            params.append(max_amount_yen)
        if deadline_after:
            where.append("bid_deadline IS NOT NULL AND bid_deadline >= ?")
            params.append(deadline_after)

        if join_fts:
            base_from = "bids_fts JOIN bids USING(unified_id)"
            where_clause = "bids_fts MATCH ?"
            if where:
                where_clause = where_clause + " AND " + " AND ".join(where)
        else:
            base_from = "bids"
            where_clause = " AND ".join(where) if where else "1=1"

        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM {base_from} WHERE {where_clause}", params
        ).fetchone()

        if join_fts:
            order_sql = (
                "ORDER BY bids_fts.rank, "
                "COALESCE(bids.announcement_date, bids.bid_deadline, bids.updated_at) DESC, "
                "bids.unified_id"
            )
        else:
            order_sql = (
                "ORDER BY "
                "COALESCE(bids.announcement_date, bids.bid_deadline, bids.updated_at) DESC, "
                "bids.unified_id"
            )

        rows = conn.execute(
            f"SELECT bids.* FROM {base_from} WHERE {where_clause} "
            f"{order_sql} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        payload: dict[str, Any] = {
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": [_row_to_bid_dict(r) for r in rows],
        }
        if total == 0:
            payload["hint"] = _empty_bids_hint(q)
            payload["retry_with"] = [
                "search_programs",
                "search_case_studies",
            ]
            payload.update(_expansion_coverage_state("bids", conn))
        return payload
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def get_bid(
    unified_id: Annotated[
        str,
        Field(
            description="BID-<10 hex> unified_id from search_bids.",
            pattern=_BID_ID_RE,
        ),
    ],
) -> dict[str, Any]:
    """DETAIL-BID: fetch a single 入札案件 (procurement notice / 落札結果). Returns bid_title, bid_kind, procuring_entity + houjin_bangou, ministry, prefecture, program_id_hint, all deadline + amount + winner fields, eligibility_conditions, classification_code (役務/物品/工事), and full lineage.

    Example:
        get_bid(unified_id="BID-9f8e7d6c5b")
        → {"unified_id": "BID-9f8e7d6c5b", "bid_title": "...", "bid_kind": "役務",
           "procuring_entity": "...", "deadline": "...", "winner_name": "..."}

    When NOT to call:
        - Without a BID-<10 hex> id → use search_bids first.
        - For 補助金 / 助成金 program detail → use get_program (bids are procurement, not subsidies).
        - To screen applicability → use bid_eligible_for_profile (this is just the raw record).
        - For tax / law / 判例 detail → use get_tax_rule / get_law / get_court_decision.

    CHAIN:
      ← `search_bids` produces the unified_id.
      → `bid_eligible_for_profile(unified_id, business_profile)` to screen applicability.
      → `search_programs(unified_id=program_id_hint)` when the bid links to a funded 補助事業.
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM bids WHERE unified_id = ?", (unified_id,)
        ).fetchone()
        if row is None:
            return _err("no_matching_records", f"bid not found: {unified_id}")
        return _row_to_bid_dict(row)
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def bid_eligible_for_profile(
    bid_unified_id: Annotated[
        str,
        Field(
            description="BID-<10 hex> unified_id to screen.",
            pattern=_BID_ID_RE,
        ),
    ],
    business_profile: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Caller-supplied profile used for substring signals against "
                "eligibility_conditions. Recognized keys (all optional): "
                "prefecture, houjin_bangou, industry_jsic, rating_grade "
                "(A/B/C/D), target_types[]. A missing key yields a neutral "
                "signal, not a disqualification."
            ),
        ),
    ],
) -> dict[str, Any]:
    """SCREEN-BID: compare a business profile against bid.eligibility_conditions. Honest substring scan — not a structured eligibility engine. Returns `possibly_eligible` (bool, True unless a hard mismatch is found) + matched_signals + unmatched_signals + caveats.

    Signals:
      - prefecture: "当県内" / prefecture string LIKE match
      - rating_grade: '等級' / 'A等級' etc. present + matches profile.rating_grade
      - industry_jsic: JSIC label substring
      - houjin_bangou: exact 13-digit match against procuring_houjin_bangou (conflict-of-interest marker)

    WHEN NOT:
      - Treat an empty eligibility_conditions as "unknown" — absent text does not mean unrestricted.
      - This tool does not verify 経営審査 / 指名停止 / 建設業許可 status. Always confirm with the primary source_url before bidding.

    CHAIN:
      ← `search_bids` / `get_bid` produces the bid_unified_id.
      → `search_court_decisions(q='指名停止')` for 指名停止 jurisprudence if profile hits a conflict.
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM bids WHERE unified_id = ?", (bid_unified_id,)
        ).fetchone()
        if row is None:
            return _err("seed_not_found", f"bid not found: {bid_unified_id}")

        eligibility = row["eligibility_conditions"] or ""
        matched: list[str] = []
        unmatched: list[str] = []
        caveats: list[str] = []
        possibly_eligible = True

        prefecture = business_profile.get("prefecture")
        if isinstance(prefecture, str) and prefecture:
            if prefecture in eligibility:
                matched.append(f"prefecture='{prefecture}' mentioned in eligibility_conditions")
            elif "都道府県" in eligibility or "県内" in eligibility:
                caveats.append(
                    f"eligibility_conditions mentions 都道府県/県内 but not '{prefecture}' — "
                    "confirm jurisdiction with source_url"
                )

        industry_jsic = business_profile.get("industry_jsic")
        if (
            isinstance(industry_jsic, str)
            and industry_jsic
            and industry_jsic in eligibility
        ):
            matched.append(f"industry_jsic='{industry_jsic}' mentioned")

        rating_grade = business_profile.get("rating_grade")
        if isinstance(rating_grade, str) and rating_grade:
            if f"{rating_grade}等級" in eligibility or f"等級{rating_grade}" in eligibility:
                matched.append(f"rating_grade='{rating_grade}' matched")
            elif "等級" in eligibility:
                unmatched.append(
                    f"rating_grade='{rating_grade}' — eligibility_conditions "
                    "references 等級 but no grade match found"
                )
                caveats.append(
                    "等級要件あり; confirm 競争参加資格 grade before bidding"
                )

        target_types = business_profile.get("target_types")
        if isinstance(target_types, list):
            for t in target_types:
                if isinstance(t, str) and t and t in eligibility:
                    matched.append(f"target_type='{t}' mentioned")

        # Conflict-of-interest check: bidder == procurer is a hard disqualifier.
        houjin_bangou = business_profile.get("houjin_bangou")
        if isinstance(houjin_bangou, str) and houjin_bangou == row["procuring_houjin_bangou"]:
            possibly_eligible = False
            unmatched.append(
                "houjin_bangou equals procuring_houjin_bangou — self-procurement is disqualifying"
            )

        if not eligibility:
            caveats.append(
                "eligibility_conditions is empty in this row; absence does NOT imply no restrictions. "
                "Read source_url directly before applying."
            )

        return {
            "bid_unified_id": bid_unified_id,
            "possibly_eligible": possibly_eligible,
            "matched_signals": matched,
            "unmatched_signals": unmatched,
            "caveats": caveats,
            "eligibility_conditions_excerpt": eligibility[:500] if eligibility else None,
            "source_url": row["source_url"],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tax rulesets (3)
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def search_tax_rules(
    q: Annotated[
        str | None,
        Field(
            description=(
                "Free-text over ruleset_name + eligibility_conditions + "
                "calculation_formula. FTS5 trigram; < 3 chars fall back to LIKE."
            ),
        ),
    ] = None,
    tax_category: Annotated[
        Literal[
            "consumption", "corporate", "income", "property", "local", "inheritance"
        ]
        | None,
        Field(
            description=(
                "Tax category (closed-set). 'consumption' = 消費税 / "
                "インボイス, 'corporate' = 法人税, 'income' = 所得税, "
                "'property' = 固定資産税 / 不動産取得税, 'local' = "
                "事業税 / 住民税 等 地方税, 'inheritance' = 相続税 / 贈与税."
            )
        ),
    ] = None,
    ruleset_kind: Annotated[
        Literal[
            "registration",
            "credit",
            "deduction",
            "special_depreciation",
            "exemption",
            "preservation",
            "other",
        ]
        | None,
        Field(
            description=(
                "Ruleset kind (税制特例の形式). 'registration' = "
                "適格請求書発行事業者登録, 'credit' = 税額控除 "
                "(賃上げ促進 / 中小機械装置等), 'deduction' = 所得控除 / "
                "損金算入, 'special_depreciation' = 特別償却, 'exemption' = "
                "免税 (2割特例 等), 'preservation' = 帳簿保存 (電帳法), "
                "'other' = 上記以外."
            )
        ),
    ] = None,
    effective_on: Annotated[
        str | None,
        Field(
            description=(
                "ISO 8601 date (YYYY-MM-DD). Returns only rulesets whose "
                "effective_from <= date AND (effective_until IS NULL OR "
                "effective_until >= date). Critical around cliff dates "
                "2026-09-30 / 2027-09-30 / 2029-09-30 (インボイス 経過措置)."
            ),
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="返却する最大行数. Range [1, 100]. Default 20. 増やすほど token 消費が比例 — 確認用は 5-10, 一覧表示は 20-50 が現実的.")] = 20,
    offset: Annotated[
        int,
        Field(
            ge=0,
            description=(
                "Pagination offset (0-based). Default 0. Combine with `limit` "
                "to walk past page 1."
            ),
        ),
    ] = 0,
    fields: Annotated[
        Literal["minimal", "default", "full"],
        Field(
            description=(
                "Response shape. 'minimal' (~200 B/row) drops narrative "
                "eligibility_conditions + predicate JSON + lineage. 'default' "
                "(~900 B/row) truncates narrative to 400 chars, drops "
                "source_excerpt/source_checksum, keeps predicate JSON. 'full' "
                "(~1.6 KB/row) returns raw columns including source_excerpt."
            ),
        ),
    ] = "default",
) -> dict[str, Any]:
    """DISCOVER-TAX: search 税務判定ルールセット (国税庁 タックスアンサー + 電帳法一問一答 + インボイス Q&A). Each row pairs narrative `eligibility_conditions` with a machine-readable predicate tree for `evaluate_tax_applicability`.

    CHAIN:
      → `get_tax_rule(unified_id)` for a single row.
      → `evaluate_tax_applicability(business_profile, target_ruleset_ids)` to run the predicate engine.

    WHEN NOT:
      - `search_laws` instead for the underlying statute (related_law_ids links to LAW-*).
      - `search_programs` instead for 補助金 / 助成金.

    LIMITATIONS:
      - This is NOT tax advice. `evaluate_tax_applicability` only matches declared JSON predicates — it does not interpret tax law.
      - Cliff dates: 2026-09-30 (2割特例 終了), 2027-09-30 (80% 経過措置), 2029-09-30 (50% 経過措置 / 少額特例 終了). Use `effective_on` to snapshot.
      - COVERAGE (35 rows live): インボイス制度 / 電子帳簿保存法 / 中小企業 法人税・消費税 特例. 相続税 / 贈与税 / 事業承継税制 / 組織再編税制 は未収載 — `get_am_tax_rule` (autonomath.db: 相続 / 贈与 / 事業承継 を含む 900+ rule 全文) に fallback してください.
    """
    conn = connect()
    try:
        where: list[str] = []
        params: list[Any] = []
        join_fts = False

        from jpintel_mcp.api.programs import KANA_EXPANSIONS, _build_fts_match

        if q:
            q_clean = q.strip()
            if q_clean:
                terms: list[str] = [q_clean]
                if q_clean in KANA_EXPANSIONS:
                    terms.extend(KANA_EXPANSIONS[q_clean])
                shortest = min(len(t) for t in terms)
                if shortest >= 3:
                    join_fts = True
                    params.append(_build_fts_match(q_clean))
                else:
                    like_clauses: list[str] = []
                    for t in terms:
                        like_clauses.append(
                            "(ruleset_name LIKE ? "
                            "OR COALESCE(eligibility_conditions,'') LIKE ? "
                            "OR COALESCE(calculation_formula,'') LIKE ?)"
                        )
                        like = f"%{t}%"
                        params.extend([like, like, like])
                    where.append("(" + " OR ".join(like_clauses) + ")")

        if tax_category:
            where.append("tax_category = ?")
            params.append(tax_category)
        if ruleset_kind:
            where.append("ruleset_kind = ?")
            params.append(ruleset_kind)
        if effective_on:
            where.append("effective_from <= ?")
            params.append(effective_on)
            where.append("(effective_until IS NULL OR effective_until >= ?)")
            params.append(effective_on)

        if join_fts:
            base_from = "tax_rulesets_fts JOIN tax_rulesets USING(unified_id)"
            where_clause = "tax_rulesets_fts MATCH ?"
            if where:
                where_clause = where_clause + " AND " + " AND ".join(where)
        else:
            base_from = "tax_rulesets"
            where_clause = " AND ".join(where) if where else "1=1"

        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM {base_from} WHERE {where_clause}", params
        ).fetchone()

        order_parts: list[str] = [
            "CASE WHEN effective_until IS NULL THEN 0 ELSE 1 END"
        ]
        if join_fts:
            order_parts.append("bm25(tax_rulesets_fts)")
        order_parts.extend(["effective_from DESC", "unified_id"])
        order_sql = "ORDER BY " + ", ".join(order_parts)

        rows = conn.execute(
            f"SELECT tax_rulesets.* FROM {base_from} WHERE {where_clause} "
            f"{order_sql} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        results_raw = [_row_to_tax_ruleset_dict(r) for r in rows]
        results = [_trim_tax_ruleset(rec, fields) for rec in results_raw]
        payload: dict[str, Any] = {
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": results,
        }
        if total == 0:
            payload["hint"] = _empty_tax_rules_hint(q, tax_category)
            payload["retry_with"] = [
                "get_am_tax_rule",
                "search_tax_incentives",
                "search_laws",
            ]
            payload.update(_expansion_coverage_state("tax_rulesets", conn))
        return payload
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def get_tax_rule(
    unified_id: Annotated[
        str,
        Field(
            description="TAX-<10 hex> unified_id from search_tax_rules.",
            pattern=_TAX_ID_RE,
        ),
    ],
) -> dict[str, Any]:
    """DETAIL-TAX: fetch a single 税務判定ルールセット by TAX-<10 hex>. Returns ruleset_name, tax_category, ruleset_kind, effective_from / effective_until (watch cliff dates), related_law_ids, narrative eligibility_conditions, predicate JSON, rate_or_amount, calculation_formula, filing_requirements, authority + URL, full lineage.

    Example:
        get_tax_rule(unified_id="TAX-0a1b2c3d4e")
        → {"unified_id": "TAX-0a1b2c3d4e", "ruleset_name": "...", "tax_category": "法人税",
           "effective_from": "2025-04-01", "rate_or_amount": "...", "predicate_json": {...}}

    When NOT to call:
        - Without a TAX-<10 hex> id → use search_tax_rules / search_tax_incentives first.
        - To EVALUATE applicability against a profile → use evaluate_tax_applicability.
        - For statutory text → use get_law (this returns the predicate, not the law).
        - For 補助金 / grant programs → use get_program (different table; tax rulesets are tax-only).
        - For sunset alerts only → use list_tax_sunset_alerts.

    CHAIN:
      ← `search_tax_rules` produces the unified_id.
      → `evaluate_tax_applicability(business_profile, target_ruleset_ids=[unified_id])` to run the predicate.
      → `get_law(law_unified_id)` for each related_law_ids entry.
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM tax_rulesets WHERE unified_id = ?", (unified_id,)
        ).fetchone()
        if row is None:
            return _err("no_matching_records", f"tax_ruleset not found: {unified_id}")
        return _row_to_tax_ruleset_dict(row)
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def evaluate_tax_applicability(
    business_profile: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Caller-supplied key/value bag. Keys referenced by predicate "
                "`field` values are looked up here. Arbitrary schema; a "
                "missing field yields a false condition with 'field missing' "
                "reason. Common keys: annual_revenue_yen, business_type, "
                "invoice_registration_number, employees, industry_jsic."
            ),
        ),
    ],
    target_ruleset_ids: Annotated[
        list[str] | None,
        Field(
            description=(
                "Optional list of TAX-<10 hex> ids to evaluate. When omitted, "
                "all CURRENT rulesets (effective_until IS NULL OR >= today) "
                "are evaluated. Cap: 100 ids per call."
            ),
            max_length=100,
        ),
    ] = None,
) -> dict[str, Any]:
    """JUDGE-TAX: evaluate eligibility predicates for tax rulesets against a caller business_profile. Walks `eligibility_conditions_json` per row and returns per-ruleset `applicable` + reasons + matched / unmatched predicate lists. Does NOT interpret tax law — pure JSON predicate matching.

    Supported ops: eq / gte / lte / in / has_invoice_registration / all / any / not.
    Missing profile field => False with reason "field missing from profile: X".
    Malformed JSON or unsupported op => applicable=False with error code.

    Example:
        evaluate_tax_applicability(
            business_profile={"annual_revenue_yen": 80000000, "employees": 12,
                              "invoice_registration_number": "T1234..."},
            target_ruleset_ids=["TAX-0a1b2c3d4e", "TAX-9f8e7d6c5b"])
        → {"results": [{"unified_id": "TAX-0a1b2c3d4e", "applicable": true,
                        "matched": [...], "unmatched": []}, ...]}

    When NOT to call:
        - To find candidate rulesets first → use search_tax_rules / search_tax_incentives.
        - For raw ruleset detail → use get_tax_rule (this evaluates; that returns the rule).
        - As a final tax filing decision — always confirm with source_url + a tax professional.
        - For 補助金 / loan / bid eligibility → use the matching domain-specific eligibility tool.

    CHAIN:
      ← `search_tax_rules` / `get_tax_rule` surfaces candidate TAX-<10 hex> ids.
      → `get_law(law_unified_id)` for statute behind an applicable ruleset.
    """
    if target_ruleset_ids is not None:
        for uid in target_ruleset_ids:
            import re as _re
            if not _re.match(_TAX_ID_RE, uid):
                return _err(
                    "invalid_enum",
                    f"target_ruleset_ids contains malformed id: {uid!r} "
                    "(expected TAX-<10 hex>)",
                )

    try:
        from jpintel_mcp.api.tax_rulesets import _evaluate_ruleset
    except ImportError as exc:  # pragma: no cover
        return _err("internal", f"tax_rulesets evaluator unavailable: {exc}")

    conn = connect()
    try:
        if target_ruleset_ids is not None:
            ids = list(dict.fromkeys(target_ruleset_ids))
            if not ids:
                return {"results": []}
            placeholders = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT * FROM tax_rulesets WHERE unified_id IN ({placeholders})",
                ids,
            ).fetchall()
            by_id: dict[str, sqlite3.Row] = {r["unified_id"]: r for r in rows}
            ordered_rows = [by_id[uid] for uid in ids if uid in by_id]
        else:
            ordered_rows = conn.execute(
                "SELECT * FROM tax_rulesets "
                "WHERE effective_until IS NULL OR effective_until >= date('now') "
                "ORDER BY unified_id"
            ).fetchall()

        results = [
            _evaluate_ruleset(r, business_profile).model_dump() for r in ordered_rows
        ]
        return {"results": results}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Invoice registrants (1)
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def search_invoice_registrants(
    q: Annotated[
        str | None,
        Field(
            description=(
                "Prefix LIKE on normalized_name (事業者名). Index-eligible, "
                "not FTS. Minimum 2 characters; shorter is rejected."
            ),
        ),
    ] = None,
    houjin_bangou: Annotated[
        str | None,
        Field(
            description=(
                "Exact 13-digit 法人番号 filter. Sole-proprietor rows are "
                "excluded when set (their houjin_bangou is NULL)."
            ),
            pattern=r"^\d{13}$",
        ),
    ] = None,
    kind: Annotated[
        Literal["corporate", "individual"] | None,
        Field(
            description=(
                "corporate = 法人 (registrant_kind='corporation'); "
                "individual = 個人事業主 (registrant_kind='sole_proprietor')."
            ),
        ),
    ] = None,
    prefecture: Annotated[
        PrefectureParam,
        Field(
            description=(
                "Prefecture closed-set 48 値. Canonical '東京都' / short '東京' / "
                "romaji 'Tokyo' all accepted (auto-normalized). Unknown values "
                "raise invalid_enum."
            ),
        ),
    ] = None,
    registered_after: Annotated[
        str | None,
        Field(description="ISO date lower bound on registered_date."),
    ] = None,
    registered_before: Annotated[
        str | None,
        Field(description="ISO date upper bound on registered_date."),
    ] = None,
    active_only: Annotated[
        bool,
        Field(
            description=(
                "When true (default), excludes revoked + expired rows. "
                "Flip to false for historical/audit research."
            ),
        ),
    ] = True,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description=(
                "Page size. Default 50, hard cap 100. No wildcard bulk "
                "export — point consumers at NTA's download URL for "
                "full snapshots."
            ),
        ),
    ] = 50,
    offset: Annotated[int, Field(ge=0, description="Pagination offset (0-based row count to skip). Default 0. Combine with `limit` for paging through `total`.")] = 0,
) -> dict[str, Any]:
    """LOOKUP-INVOICE: search 適格請求書発行事業者 (国税庁 bulk, PDL v1.0). Returns {total, limit, offset, results, attribution} — every response carries the mandatory 出典明記 + 編集・加工注記 block per PDL v1.0.

    CHAIN:
      → (verify invoice_registration_number) for T<13 digits> validation in downstream flows.
      → `search_court_decisions(q='適格請求書')` for 判例 on 適格請求書 / 仕入控除.

    WHEN NOT:
      - Do NOT call with empty q + empty filters to enumerate the 4M-row master — the hard 100-row cap plus the PDL attribution on every page prevent scraping. Use NTA's own bulk download.
      - Do NOT append name-matching logic on top — sole-proprietor rows are only present because ingest pre-filtered to NTA's consent model.

    LIMITATIONS:
      - DATA AVAILABILITY: 13,801 rows loaded as of 2026-04-25 — **delta only** (増分 mirror since 2025-10). Pre-2025 registrations and the full 4M-row NTA bulk are pending post-launch; a `total=0` response does NOT mean "not registered", it may mean "out of the current mirror window". Always point the user at 国税庁 適格事業者公表サイト (https://www.invoice-kohyo.nta.go.jp/) for the 確定 lookup.
      - 法人 rows carry houjin_bangou; sole-proprietors do NOT (soft-FK to houjin_master).
      - `active_only=True` hides revoked/expired; required for "is this invoice number currently valid?".
      - `q` is prefix LIKE on normalized_name, NOT FTS — kana variants are not synthesized at the MCP layer.
    """
    if q is not None:
        q_clean = q.strip()
        if q_clean and len(q_clean) < 2:
            return _err("out_of_range", "q must be at least 2 characters")
    else:
        q_clean = ""

    kind_map = {"corporate": "corporation", "individual": "sole_proprietor"}

    conn = connect()
    try:
        where: list[str] = []
        params: list[Any] = []
        if q_clean:
            where.append("normalized_name LIKE ?")
            params.append(f"{q_clean}%")
        if houjin_bangou:
            where.append("houjin_bangou = ?")
            params.append(houjin_bangou)
        if kind:
            where.append("registrant_kind = ?")
            params.append(kind_map[kind])
        prefecture_norm = _normalize_prefecture(prefecture)
        if prefecture_norm:
            where.append("prefecture = ?")
            params.append(prefecture_norm)
        if registered_after:
            where.append("registered_date >= ?")
            params.append(registered_after)
        if registered_before:
            where.append("registered_date <= ?")
            params.append(registered_before)
        if active_only:
            where.append("revoked_date IS NULL")
            where.append("expired_date IS NULL")

        where_clause = " AND ".join(where) if where else "1=1"

        try:
            (total,) = conn.execute(
                f"SELECT COUNT(*) FROM invoice_registrants WHERE {where_clause}",
                params,
            ).fetchone()
        except sqlite3.OperationalError as exc:
            return _err("internal", f"invoice_registrants table unavailable: {exc}")

        rows = conn.execute(
            f"SELECT * FROM invoice_registrants WHERE {where_clause} "
            f"ORDER BY registered_date DESC, invoice_registration_number ASC "
            f"LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

        payload: dict[str, Any] = {
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": [_row_to_invoice_registrant_dict(r) for r in rows],
            "attribution": _INVOICE_ATTRIBUTION,
        }
        if total == 0:
            payload["hint"] = _empty_invoice_registrants_hint(q, houjin_bangou)
            payload["retry_with"] = ["search_enforcement_cases"]
            # Surface coverage: 13,801 delta rows today, full 400 万 bulk pending.
            try:
                (loaded,) = conn.execute(
                    "SELECT COUNT(*) FROM invoice_registrants"
                ).fetchone()
            except sqlite3.Error:
                loaded = 0
            payload["coverage_note"] = {
                "rows_loaded": int(loaded),
                "mode": "delta_since_2025_10",
                "full_bulk_status": "pending_post_launch",
                "disambiguation": (
                    "total=0 は '登録なし' ではなく '本 DB mirror 対象外' の可能性が高いです. "
                    "国税庁 適格事業者公表サイトで最終確認してください."
                ),
            }
        return payload
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Cross-dataset glue (3)
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def trace_program_to_law(
    program_unified_id: Annotated[
        str,
        Field(
            description=(
                "programs.unified_id (UNI-*, canonical name, or UNI-ext-<10hex>). "
                "The tool walks program_law_refs → laws and optionally follows "
                "the superseded_by_law_id chain to report the current form."
            ),
        ),
    ],
    follow_revision_chain: Annotated[
        bool,
        Field(
            description=(
                "When true (default), each linked law is followed via "
                "superseded_by_law_id until revision_status='current'. "
                "When false, the raw law referenced by the program is returned."
            ),
        ),
    ] = True,
) -> dict[str, Any]:
    """TRACE-PROGRAM-LAW: given a program unified_id, return its 根拠法 / 関連法 chain — joins `program_law_refs` → `laws`. Each entry reports ref_kind (authority / eligibility / exclusion / reference / penalty), article_citation, law title, and (when follow_revision_chain=True) the current form of the law after walking superseded_by_law_id.

    Returns:
      - program_id
      - legal_basis_chain[]: list of {law_id, ref_kind, article_citation, title, law_number, revision_status, current_law_id?, current_title?}

    CHAIN:
      ← `search_programs` / `get_program` produces the program_unified_id.
      → `get_law(law_unified_id)` for full law detail.
      → `find_cases_by_law(current_law_id)` to run 判例 against the live version.

    LIMITATIONS:
      - Only surfaces links the ingest layer recorded. Programs without populated `program_law_refs` return an empty `legal_basis_chain`.
    """
    conn = connect()
    try:
        # Guard against silent empty-chain: if the program id itself doesn't
        # exist in programs, we must not return total_refs=0 with no error —
        # that looks like "no legal basis" and can drive funding DD mistakes.
        exists = conn.execute(
            "SELECT 1 FROM programs WHERE unified_id = ? LIMIT 1",
            (program_unified_id,),
        ).fetchone()
        if exists is None:
            return {
                "program_id": program_unified_id,
                "legal_basis_chain": [],
                "total_refs": 0,
                "error": {
                    "code": "program_not_found",
                    "message": (
                        f"program_unified_id={program_unified_id!r} is not in "
                        "the programs table. An empty legal_basis_chain here "
                        "does NOT mean the program has no legal basis — it "
                        "means the id is wrong."
                    ),
                    "hint": (
                        "Use `search_programs(...)` and take results[].unified_id "
                        "(shape UNI-* or UNI-ext-<10hex>). Autonomath canonical "
                        "ids like 'program:xxx' are NOT accepted here — they live "
                        "in autonomath.db, not jpintel.db/programs."
                    ),
                    "retry_with": ["search_programs", "get_program"],
                },
            }

        rows = conn.execute(
            """SELECT plr.program_unified_id AS program_unified_id,
                      plr.law_unified_id    AS law_unified_id,
                      plr.ref_kind          AS ref_kind,
                      plr.article_citation  AS article_citation,
                      l.law_title           AS law_title,
                      l.law_number          AS law_number,
                      l.revision_status     AS revision_status,
                      l.superseded_by_law_id AS superseded_by_law_id
               FROM program_law_refs plr
               LEFT JOIN laws l ON l.unified_id = plr.law_unified_id
               WHERE plr.program_unified_id = ?
               ORDER BY
                   CASE plr.ref_kind
                       WHEN 'authority' THEN 0
                       WHEN 'eligibility' THEN 1
                       WHEN 'exclusion' THEN 2
                       WHEN 'penalty' THEN 3
                       WHEN 'reference' THEN 4
                       ELSE 5 END,
                   plr.law_unified_id""",
            (program_unified_id,),
        ).fetchall()

        chain: list[dict[str, Any]] = []
        for r in rows:
            entry: dict[str, Any] = {
                "law_id": r["law_unified_id"],
                "ref_kind": r["ref_kind"],
                "article_citation": r["article_citation"],
                "title": r["law_title"],
                "law_number": r["law_number"],
                "revision_status": r["revision_status"],
            }
            if follow_revision_chain and r["law_unified_id"]:
                visited: set[str] = {r["law_unified_id"]}
                cur_id = r["law_unified_id"]
                cur_row = r
                for _ in range(20):
                    nxt = cur_row["superseded_by_law_id"]
                    if not nxt or nxt in visited:
                        break
                    visited.add(nxt)
                    nxt_row = conn.execute(
                        "SELECT unified_id, law_title, superseded_by_law_id, "
                        "revision_status FROM laws WHERE unified_id = ?",
                        (nxt,),
                    ).fetchone()
                    if nxt_row is None:
                        break
                    cur_id = nxt_row["unified_id"]
                    cur_row = nxt_row
                entry["current_law_id"] = cur_id
                entry["current_title"] = cur_row["law_title"] if cur_row else None
            chain.append(entry)

        return {
            "program_id": program_unified_id,
            "legal_basis_chain": chain,
            "total_refs": len(chain),
        }
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def find_cases_by_law(
    law_unified_id: Annotated[
        str,
        Field(
            description="LAW-<10 hex> unified_id to search against.",
            pattern=_LAW_ID_RE,
        ),
    ],
    include_enforcement: Annotated[
        bool,
        Field(
            description=(
                "When true (default), also return 会計検査院 enforcement_cases "
                "linked to court_decisions that cite this law, via "
                "enforcement_decision_refs. When false, only court_decisions "
                "are returned."
            ),
        ),
    ] = True,
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Max rows per section. Default 20."),
    ] = 20,
) -> dict[str, Any]:
    """TRACE-LAW-CASES: given a LAW-<10 hex>, return (court_decisions citing it) + optionally (enforcement_cases linked to those decisions via enforcement_decision_refs). Essential for "which rulings + 会計検査院 findings interpret 補助金適正化法 第22条" in one call.

    Returns:
      - law_id
      - court_decisions[]: direct citers via related_law_ids_json
      - enforcement_cases[]: linked via enforcement_decision_refs (when include_enforcement=True)
      - totals: {court_decisions, enforcement_cases}

    CHAIN:
      ← `trace_program_to_law` or `get_law` produces the law_unified_id.
      → `get_court_decision(unified_id)` for detail.
      → `get_enforcement_case(case_id)` for each enforcement hit.

    LIMITATIONS:
      - enforcement_decision_refs coverage depends on manual curation — absence is not proof of no litigation.
    """
    conn = connect()
    try:
        law_row = conn.execute(
            "SELECT unified_id FROM laws WHERE unified_id = ?", (law_unified_id,)
        ).fetchone()
        if law_row is None:
            return _err("seed_not_found", f"law not found: {law_unified_id}")

        weight_order = (
            "CASE precedent_weight "
            "WHEN 'binding' THEN 0 WHEN 'persuasive' THEN 1 "
            "WHEN 'informational' THEN 2 ELSE 3 END"
        )
        level_order = (
            "CASE court_level "
            "WHEN 'supreme' THEN 0 WHEN 'high' THEN 1 WHEN 'district' THEN 2 "
            "WHEN 'summary' THEN 3 WHEN 'family' THEN 4 ELSE 5 END"
        )
        court_rows = conn.execute(
            f"""SELECT * FROM court_decisions
                WHERE COALESCE(related_law_ids_json,'') LIKE ?
                ORDER BY {weight_order}, {level_order},
                         COALESCE(decision_date,'') DESC,
                         unified_id
                LIMIT ?""",
            [f'%"{law_unified_id}"%', limit],
        ).fetchall()
        court_ids = [r["unified_id"] for r in court_rows]

        enforcement_rows: list[sqlite3.Row] = []
        if include_enforcement and court_ids:
            placeholders = ",".join("?" * len(court_ids))
            try:
                enforcement_rows = conn.execute(
                    f"""SELECT DISTINCT ec.*
                        FROM enforcement_cases ec
                        JOIN enforcement_decision_refs edr
                          ON edr.enforcement_case_id = ec.case_id
                        WHERE edr.decision_unified_id IN ({placeholders})
                        ORDER BY COALESCE(ec.disclosed_date,'') DESC, ec.case_id
                        LIMIT ?""",
                    [*court_ids, limit],
                ).fetchall()
            except sqlite3.OperationalError:
                # enforcement_decision_refs may not exist on older DBs — tolerate.
                enforcement_rows = []

        payload: dict[str, Any] = {
            "law_id": law_unified_id,
            "court_decisions": [_row_to_court_decision_dict(r) for r in court_rows],
            "enforcement_cases": [
                _row_to_enforcement_case(r) for r in enforcement_rows
            ],
            "totals": {
                "court_decisions": len(court_rows),
                "enforcement_cases": len(enforcement_rows),
            },
        }
        if not court_rows and not enforcement_rows:
            payload["hint"] = (
                f"law_id={law_unified_id} に紐づく 判例 / 行政処分 が 0 件. "
                "court_decisions テーブルは table_pending_load 状態 (judgment ingest 後に追補予定). "
                "search_enforcement_cases で直接 会計検査院 findings を叩くか, "
                "find_precedents_by_statute を裁判所 RSS 側で別途追跡してください."
            )
            payload["retry_with"] = ["search_enforcement_cases", "find_precedents_by_statute"]
            payload.update(_expansion_coverage_state("court_decisions", conn))
        return payload
    finally:
        conn.close()


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def combined_compliance_check(
    business_profile: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Caller profile used for tax evaluation and bid relevance. "
                "Common keys: prefecture, industry_jsic, annual_revenue_yen, "
                "business_type, invoice_registration_number, employees."
            ),
        ),
    ],
    program_unified_id: Annotated[
        str | None,
        Field(
            description=(
                "Optional programs.unified_id. When supplied, `exclusion_check` "
                "runs the 181-rule engine on [program_unified_id] and "
                "`relevant_bids` are filtered by program_id_hint="
                "program_unified_id first."
            ),
        ),
    ] = None,
    include_tax_eval: Annotated[
        bool,
        Field(
            description=(
                "When true (default), evaluate all currently-effective "
                "tax_rulesets against business_profile."
            ),
        ),
    ] = True,
    tax_verbose: Annotated[
        bool,
        Field(
            description=(
                "When False (default), tax_evaluation.results includes only rulesets "
                "where applicable=True (90%+ token savings — typical 35-row scan "
                "returns 2-4 applicable rows). Set True to include non-matching "
                "rulesets with their disqualification reasons (audit / debugging)."
            ),
        ),
    ] = False,
    top_bids: Annotated[
        int,
        Field(
            ge=0,
            le=20,
            description="How many relevant bids to surface. Default 5.",
        ),
    ] = 5,
    candidate_program_ids: Annotated[
        list[str] | None,
        Field(
            description=(
                "Optional list of 2..N program ids the caller is considering "
                "combining (P0.3 dark-inventory unlock). Each id is matched "
                "by its native key shape ('certification:…' / 'loan:jfc:…' / "
                "'program:…' / 'tax_measure:…') against am_compat_matrix and "
                "am_combo_calculator — no silent rekeying. When supplied with "
                "len ≥ 2, the response gains `compat_matrix` and "
                "`combo_calculator` sections. Length 0/1 → both sections absent "
                "(byte-equivalent to pre-extension behaviour)."
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """OMNIBUS-COMPLIANCE: one-shot compliance report combining (a) exclusion_rules check for the named program, (b) tax_rulesets evaluation against business_profile, (c) top-N relevant bids (filtered by program_id_hint when program_unified_id is set, otherwise by business_profile.prefecture), and (d) when `candidate_program_ids` ≥ 2: pairwise am_compat_matrix lookup + am_combo_calculator member-containment match. Use when the caller says "check everything for this business/program at once".

    DEPRECATED (2026-04-25): superseded by `rule_engine_check` (R9 unified rule
    engine, 49,247 rows across 6 corpora incl. the 48,815-row dark inventory
    am_compat_matrix). Retained for backward compatibility and for the bid
    filtering / tax_ruleset evaluation legs which `rule_engine_check` does not
    yet cover. New integrations SHOULD prefer `rule_engine_check`.

    Returns:
      - program_id (echo)
      - exclusion_check: {hits[], checked_rules} (empty when program_unified_id is None)
      - tax_evaluation: {results[], applicable_count, applicable_ruleset_ids} — results is applicable-only by default; set tax_verbose=True to include non-matching rulesets.
      - relevant_bids: [BidOut …] (up to top_bids)
      - compat_matrix: {pairs[], incompatible_count, case_by_case_count, unknown_count, missing_count} (only when candidate_program_ids has ≥2 entries; reads am_compat_matrix in native key shape).
      - combo_calculator: {matched_combos[], unmatched_count} (only when candidate_program_ids has ≥2 entries; member-containment match against am_combo_calculator).
      - data_quality: {exclusion_join_coverage_pct, compat_unknown_bucket_pct} — honest data-coverage surface so the LLM does not silently treat dark-inventory gaps as "all clear".
      - summary: terse natural-language roll-up.

    CHAIN:
      ← `search_programs` / `search_tax_rules` / `search_bids` / `subsidy_combo_finder` supply the inputs.
      → `rule_engine_check` for unified rule evaluation across all 6 corpora (preferred).
      → `evaluate_tax_applicability` for more targeted tax evaluation with explicit ids.
      → `check_exclusions([program_a, program_b, …])` for pairwise 併給 checks.

    LIMITATIONS:
      - Not legal/tax advice — see each sub-tool's LIMITATIONS.
      - `relevant_bids` ordering is best-effort; empty program_id_hint + empty prefecture reverts to recency ordering.
      - When `program_unified_id` is supplied but does not exist in the `programs` table, `exclusion_check` silently returns empty — callers should pre-verify via `get_program(unified_id)` for hard-validation.
    """
    try:
        from jpintel_mcp.api.tax_rulesets import _evaluate_ruleset
    except ImportError as exc:  # pragma: no cover
        return _err("internal", f"tax_rulesets evaluator unavailable: {exc}")

    conn = connect()
    try:
        # --- Validate program_unified_id exists before running checks ---
        # Silent mismatch is a 景表法 risk: a typo'd id would return "no exclusions"
        # which the LLM may relay to the user as "compliance passed". Hard-fail instead.
        if program_unified_id:
            exists = conn.execute(
                "SELECT 1 FROM programs WHERE unified_id = ? LIMIT 1",
                (program_unified_id,),
            ).fetchone()
            if not exists:
                return {
                    "program_id": program_unified_id,
                    "error": {
                        "code": "program_not_found",
                        "message": f"unified_id={program_unified_id!r} does not exist in programs table",
                        "hint": (
                            "Pre-validate via search_programs(q=…) → get_program(unified_id) "
                            "before passing program_unified_id to compliance tools. "
                            "A silent empty exclusion_check on an unknown id could surface "
                            "as a false 'compliance passed' — this guard prevents that."
                        ),
                        "retry_with": ["search_programs", "get_program"],
                    },
                    "exclusion_check": {"hits": [], "checked_rules": 0},
                    "tax_evaluation": {"results": [], "applicable_count": 0, "applicable_ruleset_ids": []},
                    "relevant_bids": [],
                    "summary": "program_not_found; no checks run",
                }

        # --- Exclusion check (only when a program is named) ---
        exclusion_hits: list[dict[str, Any]] = []
        checked_rules = 0
        if program_unified_id:
            rule_rows = conn.execute("SELECT * FROM exclusion_rules").fetchall()
            checked_rules = len(rule_rows)
            selected = {program_unified_id}
            for r in rule_rows:
                b_group = _json_col(r, "program_b_group_json", [])
                candidates: set[str] = set()
                if r["program_a"] and r["program_a"] in selected:
                    candidates.add(r["program_a"])
                if r["program_b"] and r["program_b"] in selected:
                    candidates.add(r["program_b"])
                for gid in b_group:
                    if gid in selected:
                        candidates.add(gid)
                # Single-program context: only prerequisite rules fire on one-id sets.
                if r["kind"] == "prerequisite" and candidates:
                    exclusion_hits.append(
                        {
                            "rule_id": r["rule_id"],
                            "kind": r["kind"],
                            "severity": r["severity"],
                            "programs_involved": sorted(candidates),
                            "description": r["description"],
                            "source_urls": _json_col(r, "source_urls_json", []),
                        }
                    )

        # --- Tax evaluation ---
        tax_results: list[dict[str, Any]] = []
        if include_tax_eval:
            try:
                tax_rows = conn.execute(
                    "SELECT * FROM tax_rulesets "
                    "WHERE effective_until IS NULL OR effective_until >= date('now') "
                    "ORDER BY unified_id"
                ).fetchall()
                tax_results = [
                    _evaluate_ruleset(r, business_profile).model_dump() for r in tax_rows
                ]
            except sqlite3.OperationalError:
                tax_results = []

        # --- Relevant bids ---
        bids: list[dict[str, Any]] = []
        if top_bids > 0:
            try:
                if program_unified_id:
                    bid_rows = conn.execute(
                        """SELECT * FROM bids
                           WHERE program_id_hint = ?
                           ORDER BY
                               COALESCE(announcement_date, bid_deadline, updated_at) DESC,
                               unified_id
                           LIMIT ?""",
                        (program_unified_id, top_bids),
                    ).fetchall()
                else:
                    prefecture = _normalize_prefecture(
                        business_profile.get("prefecture")
                        if isinstance(business_profile.get("prefecture"), str)
                        else None
                    )
                    if prefecture:
                        bid_rows = conn.execute(
                            """SELECT * FROM bids
                               WHERE prefecture = ?
                               ORDER BY
                                   COALESCE(announcement_date, bid_deadline, updated_at) DESC,
                                   unified_id
                               LIMIT ?""",
                            (prefecture, top_bids),
                        ).fetchall()
                    else:
                        bid_rows = conn.execute(
                            """SELECT * FROM bids
                               ORDER BY
                                   COALESCE(announcement_date, bid_deadline, updated_at) DESC,
                                   unified_id
                               LIMIT ?""",
                            (top_bids,),
                        ).fetchall()
                bids = [_row_to_bid_dict(r) for r in bid_rows]
            except sqlite3.OperationalError:
                bids = []

        # --- P0.3 dark-inventory unlock: am_compat_matrix + am_combo_calculator ---
        # When candidate_program_ids has ≥2 entries we open a parallel RO connection
        # to autonomath.db (different file, different key shapes — INNER JOIN with
        # jpi_exclusion_rules is 0 rows, verified 2026-04-25). Both reads are
        # best-effort: if autonomath.db is missing or the tables are absent we
        # surface empty sections rather than hard-fail. Silent miss is a 詐欺
        # risk so data_quality.compat_unknown_bucket_pct stays surfaced regardless.
        compat_section: dict[str, Any] | None = None
        combo_section: dict[str, Any] | None = None
        compat_unknown_pct: float | None = None
        if (
            isinstance(candidate_program_ids, list)
            and len(candidate_program_ids) >= 2
            and all(isinstance(x, str) and x for x in candidate_program_ids)
        ):
            try:
                from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath
                am_conn = connect_autonomath()
                # Pairwise compat_matrix lookup — read both (a,b) and (b,a) since
                # the matrix is not guaranteed symmetric in row population.
                ids_sorted = sorted(set(candidate_program_ids))
                pairs_out: list[dict[str, Any]] = []
                missing_count = 0
                inc_n = cbc_n = unk_n = 0
                for i in range(len(ids_sorted)):
                    for j in range(i + 1, len(ids_sorted)):
                        a, b = ids_sorted[i], ids_sorted[j]
                        row = am_conn.execute(
                            "SELECT * FROM am_compat_matrix "
                            "WHERE program_a_id=? AND program_b_id=? LIMIT 1",
                            (a, b),
                        ).fetchone()
                        if row is None:
                            row = am_conn.execute(
                                "SELECT * FROM am_compat_matrix "
                                "WHERE program_a_id=? AND program_b_id=? LIMIT 1",
                                (b, a),
                            ).fetchone()
                        if row is None:
                            missing_count += 1
                            continue
                        status = row["compat_status"]
                        if status == "incompatible":
                            inc_n += 1
                        elif status == "case_by_case":
                            cbc_n += 1
                        elif status == "unknown":
                            unk_n += 1
                        pairs_out.append({
                            "program_a_id": row["program_a_id"],
                            "program_b_id": row["program_b_id"],
                            "compat_status": status,
                            "combined_max_yen": row["combined_max_yen"],
                            "conditions_text": row["conditions_text"],
                            "rationale_short": row["rationale_short"],
                            "evidence_relation": row["evidence_relation"],
                            "source_url": row["source_url"],
                            "confidence": row["confidence"],
                        })
                compat_section = {
                    "pairs": pairs_out,
                    "incompatible_count": inc_n,
                    "case_by_case_count": cbc_n,
                    "unknown_count": unk_n,
                    "missing_count": missing_count,
                }

                # Combo calculator member-containment scan — 56-row table, O(56).
                cand_set = set(candidate_program_ids)
                combo_rows = am_conn.execute(
                    "SELECT * FROM am_combo_calculator"
                ).fetchall()
                matched: list[dict[str, Any]] = []
                for cr in combo_rows:
                    try:
                        members = json.loads(cr["members_json"] or "[]")
                    except (TypeError, ValueError):
                        members = []
                    if not isinstance(members, list):
                        continue
                    member_set = {m for m in members if isinstance(m, str)}
                    if not cand_set.issubset(member_set):
                        continue
                    matched.append({
                        "combo_id": cr["combo_id"],
                        "combo_name": cr["combo_name"],
                        "members": members,
                        "scenario_business_type": cr["scenario_business_type"],
                        "invest_amount_yen": cr["invest_amount_yen"],
                        "subsidy_max_yen": cr["subsidy_max_yen"],
                        "tax_savings_yen": cr["tax_savings_yen"],
                        "loan_advantage_yen": cr["loan_advantage_yen"],
                        "total_max_benefit": cr["total_max_benefit"],
                        "duration_months": cr["duration_months"],
                        "rationale_md": cr["rationale_md"],
                    })
                combo_section = {
                    "matched_combos": matched,
                    "unmatched_count": len(combo_rows) - len(matched),
                }

                # data_quality.compat_unknown_bucket_pct — global ratio of unknown
                # rows in am_compat_matrix. This is a STATIC honesty surface (not
                # filtered by candidate_program_ids) so the LLM never mistakes
                # "no incompatibility found" for "verified compatible" while
                # 4,849 / 48,815 ≈ 9.93% of the matrix is the unknown bucket.
                tot_row = am_conn.execute(
                    "SELECT "
                    "  SUM(CASE WHEN compat_status='unknown' THEN 1 ELSE 0 END) AS u, "
                    "  COUNT(*) AS t "
                    "FROM am_compat_matrix"
                ).fetchone()
                if tot_row and tot_row["t"]:
                    compat_unknown_pct = round(
                        100.0 * (tot_row["u"] or 0) / float(tot_row["t"]), 2
                    )
            except (sqlite3.OperationalError, FileNotFoundError, ImportError):
                # autonomath.db absent / table missing — surface empty sections
                # so the LLM can see the dark inventory was attempted but the
                # subsystem was unavailable. Never hard-fail.
                compat_section = {
                    "pairs": [],
                    "incompatible_count": 0,
                    "case_by_case_count": 0,
                    "unknown_count": 0,
                    "missing_count": 0,
                    "subsystem_unavailable": True,
                }
                combo_section = {
                    "matched_combos": [],
                    "unmatched_count": 0,
                    "subsystem_unavailable": True,
                }

        applicable_tax = sum(1 for t in tax_results if t.get("applicable"))
        applicable_ruleset_ids = [
            t.get("ruleset_unified_id") or t.get("unified_id")
            for t in tax_results
            if t.get("applicable") and (t.get("ruleset_unified_id") or t.get("unified_id"))
        ]
        evaluated_count = len(tax_results)
        # Token saver (default): drop non-applicable rulesets.
        # 35-row scan with full disqualification reasons is ~32 KB; applicable-only
        # is typically ~2-4 KB. Callers that need the audit trail pass tax_verbose=True.
        if include_tax_eval and not tax_verbose:
            tax_results_out = [t for t in tax_results if t.get("applicable")]
        else:
            tax_results_out = tax_results
        summary_parts = [
            f"exclusion_hits={len(exclusion_hits)} (checked {checked_rules} rules)",
            f"tax_applicable={applicable_tax}/{evaluated_count}",
            f"relevant_bids={len(bids)}",
        ]
        if compat_section is not None:
            summary_parts.append(
                f"compat_pairs={len(compat_section['pairs'])} "
                f"(incompat={compat_section['incompatible_count']}, "
                f"case_by_case={compat_section['case_by_case_count']}, "
                f"unknown={compat_section['unknown_count']})"
            )
        if combo_section is not None:
            summary_parts.append(
                f"combo_matches={len(combo_section['matched_combos'])}"
            )
        summary = ", ".join(summary_parts)

        payload: dict[str, Any] = {
            "program_id": program_unified_id,
            "exclusion_check": {
                "hits": exclusion_hits,
                "checked_rules": checked_rules,
            },
            "tax_evaluation": {
                "results": tax_results_out,
                "applicable_count": applicable_tax,
                "evaluated_count": evaluated_count,
                "applicable_ruleset_ids": applicable_ruleset_ids,
                "verbose": tax_verbose,
            },
            "relevant_bids": bids,
            "summary": summary,
        }
        if compat_section is not None:
            payload["compat_matrix"] = compat_section
        if combo_section is not None:
            payload["combo_calculator"] = combo_section
        # data_quality block: only surfaced when the dark-inventory pass ran,
        # so the existing call shape (no candidate_program_ids) stays
        # byte-equivalent to the pre-extension version (P0.3 §6 acceptance gate).
        if compat_section is not None:
            payload["data_quality"] = {
                "exclusion_join_coverage_pct": 0.0,  # see P0.3 design §2: the two
                # corpora share zero key space today; honest 0.0 is the correct
                # disclosure. P0.4 / P0.5 may close this with a mapping table.
                "compat_unknown_bucket_pct": compat_unknown_pct,
            }
        # Surface coverage gaps so the LLM doesn't mistake "0 bids" for "no bids exist".
        coverage: dict[str, Any] = {}
        if top_bids > 0 and not bids:
            coverage["bids"] = _expansion_coverage_state("bids", conn)
            payload["bids_hint"] = (
                "relevant_bids=0 — bids テーブルは table_pending_load 状態 "
                "(GEPS + 自治体入札 ingest 構築中). GEPS 本体 (https://www.geps.go.jp/) "
                "or 自治体 procurement page が 現状の primary lookup です."
            )
        if coverage:
            payload["coverage"] = coverage
        return payload
    finally:
        conn.close()


# ===========================================================================
# REGULATORY-PREP-PACK: regulatory_prep_pack
# 2026-04-25 follow-up to similar_cases. Industry + prefecture (+ size) →
# applicable laws + certifications + tax rulesets + recent enforcement, in
# one call. Eliminates 4-5 round-trips a user would make to assemble the
# compliance context for a new business / new prefecture / new vertical.
# ===========================================================================

# Single-letter JSIC code → broad JP keyword used for LIKE-substring matching
# against laws.law_title/summary, tax_rulesets.ruleset_name/eligibility_conditions,
# and enforcement_cases.reason_excerpt/program_name_hint. The DB has no
# canonical industry FK on these tables (subject_areas_json + industry_scope
# are not yet populated), so we lean on substring fuzz instead of failing
# to filter at all.
_JSIC_LIKE_KEYWORD: dict[str, str] = {
    "A": "農", "B": "漁", "C": "鉱", "D": "建設", "E": "製造",
    "F": "電気", "G": "情報", "H": "運輸", "I": "卸売",
    "J": "金融", "K": "不動産", "L": "学術", "M": "宿泊",
    "N": "生活", "O": "教育", "P": "医療", "Q": "サービス",
    "R": "サービス", "S": "公務", "T": "産業",
}


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def regulatory_prep_pack(
    industry: Annotated[
        str,
        Field(
            description=(
                "業種。JSIC 大分類 letter ('E') もしくは 和名 ('製造業','農業','建設業') / "
                "EN slug ('manufacturing'). 自動正規化。"
            ),
        ),
    ],
    prefecture: Annotated[
        PrefectureParam,
        Field(
            description=(
                "都道府県 closed-set 48 値。'東京' / '東京都' / 'Tokyo' 自動正規化、"
                "未知値は invalid_enum で拒否。None で国の制度のみ。"
            ),
        ),
    ] = None,
    company_size: Annotated[
        Literal["sole", "small", "medium", "large"] | None,
        Field(
            description=(
                "規模 hint。今 release では返り値の `company_size` に echo されるのみ "
                "(将来 tax cliff / 中小企業向け制度 filter に利用予定)."
            ),
        ),
    ] = None,
    include_expired: Annotated[
        bool,
        Field(
            description=(
                "True で tax_rulesets の effective_until 経過済 行も含める "
                "(historical research 用)。default False = 現行 ruleset のみ。"
            ),
        ),
    ] = False,
    limit_per_section: Annotated[
        int,
        Field(
            ge=1,
            le=20,
            description="laws / certifications / tax_rulesets / recent_enforcement 各セクションの max 件数。default 5。",
        ),
    ] = 5,
) -> dict[str, Any]:
    """ONE-SHOT DISCOVERY: 業種 + 都道府県 (+ 規模) で「コンプラ pack」を 1 call で。

    新規事業立ち上げ / 新規進出時に必要な regulatory コンテキストを 4 セクション
    一括で返す。これがないと search_laws → programs(certification) → search_tax_rules →
    search_enforcement_cases の 4-5 往復が必要。

    返り値:
      {
        "industry": JSIC letter,
        "prefecture": normalized name | None,
        "laws":              [{law_id, canonical_name, scope_summary, source_url}, ...],
        "certifications":    [{program_id, name, issuer, validity_years, url}, ...],
        "tax_rulesets":      [{ruleset_id, name, effective_from, effective_until, url}, ...],
        "recent_enforcement":[{case_id, authority, action, published_at, url}, ...],
        "generated_at": ISO 8601 UTC,
        "hint": str   # only when at least one section is empty
      }

    LIMITATIONS:
      - laws.subject_areas_json / tax_rulesets.industry_scope は未populated のため、
        業種 filter は 法令名・要件本文への kanji LIKE substring で best-effort 解決。
        FP (false positive) を許容する代わりに 0 件を避ける設計。
      - certifications テーブルは未存在 → programs(program_kind LIKE 'certification%') で代替。
      - enforcement_cases に industry FK は無い。reason_excerpt / program_name_hint
        への LIKE で粗く絞り、ヒット 0 件なら都道府県だけ で fallback。
      - company_size は今 release では echo のみ (将来 tax cliff date filter に使う予定).

    CHAIN:
      → `get_law(unified_id)` で laws[i] の詳細
      → `get_program(unified_id)` で certifications[i] の詳細
      → `get_tax_rule(unified_id)` で tax_rulesets[i] の詳細
      → `get_enforcement_case(case_id)` で recent_enforcement[i] の詳細
    """
    industry_norm = _normalize_industry_jsic(industry)
    if not industry_norm:
        return {"error": {
            "code": "missing_required_arg",
            "message": "industry が未指定です。",
            "hint": "JSIC letter ('E') / 和名 ('製造業') / EN slug ('manufacturing') のいずれか。",
        }}

    pref_raw = prefecture
    pref_norm = _normalize_prefecture(prefecture)
    input_warnings: list[dict[str, Any]] = []
    if pref_raw and not _is_known_prefecture(pref_raw):
        input_warnings.append({
            "field": "prefecture",
            "code": "unknown_prefecture",
            "value": pref_raw,
            "normalized_to": pref_norm,
            "message": (
                f"prefecture={pref_raw!r} は正規の都道府県に一致せず。"
                "フィルタを無効化し全国ベースで返しました。正しい例: '東京' / '東京都' / 'Tokyo'。"
            ),
            "retry_with": ["enum_values(field='prefecture')"],
        })
        pref_norm = None

    # Industry → LIKE keyword (single-kanji broad term). Fall back to the raw
    # input string when the user passed a more specific 中分類 / 小分類 code.
    keyword = _JSIC_LIKE_KEYWORD.get(industry_norm[:1], industry_norm)
    like = f"%{keyword}%"
    limit = max(1, min(20, limit_per_section))

    conn = connect()
    try:
        # --- laws ---------------------------------------------------------
        laws_rows = conn.execute(
            """
            SELECT unified_id, law_title, law_short_title, summary, source_url
              FROM laws
             WHERE revision_status = 'current'
               AND (law_title LIKE ? OR COALESCE(summary,'') LIKE ?)
             ORDER BY COALESCE(enforced_date, promulgated_date, '') DESC, unified_id
             LIMIT ?
            """,
            (like, like, limit),
        ).fetchall()
        laws_out = [{
            "law_id": r["unified_id"],
            "canonical_name": r["law_short_title"] or r["law_title"],
            "scope_summary": r["summary"],
            "source_url": r["source_url"],
        } for r in laws_rows]

        # --- certifications (programs.program_kind LIKE 'certification%') -
        cert_sql = (
            "SELECT unified_id, primary_name, authority_name, official_url "
            "FROM programs WHERE excluded = 0 "
            "AND program_kind LIKE 'certification%' "
        )
        params: list[Any] = []
        if pref_norm:
            cert_sql += "AND (prefecture IS NULL OR prefecture = ?) "
            params.append(pref_norm)
        cert_sql += "ORDER BY tier, primary_name LIMIT ?"
        params.append(limit)
        cert_rows = conn.execute(cert_sql, params).fetchall()
        certs_out = [{
            "program_id": r["unified_id"],
            "name": r["primary_name"],
            "issuer": r["authority_name"],
            "validity_years": None,  # not stored on programs schema
            "url": r["official_url"],
        } for r in cert_rows]

        # --- tax_rulesets ------------------------------------------------
        tax_sql = (
            "SELECT unified_id, ruleset_name, effective_from, effective_until, "
            "source_url FROM tax_rulesets WHERE 1=1 "
        )
        tax_params: list[Any] = []
        if not include_expired:
            tax_sql += "AND (effective_until IS NULL OR effective_until >= date('now')) "
        tax_sql += "ORDER BY effective_from DESC LIMIT ?"
        tax_params.append(limit)
        tax_rows = conn.execute(tax_sql, tax_params).fetchall()
        tax_out = [{
            "ruleset_id": r["unified_id"],
            "name": r["ruleset_name"],
            "effective_from": r["effective_from"],
            "effective_until": r["effective_until"],
            "url": r["source_url"],
        } for r in tax_rows]

        # --- recent_enforcement ------------------------------------------
        enf_where: list[str] = []
        enf_params: list[Any] = []
        if pref_norm:
            enf_where.append("prefecture = ?")
            enf_params.append(pref_norm)
        enf_where.append(
            "(COALESCE(reason_excerpt,'') LIKE ? OR COALESCE(program_name_hint,'') LIKE ?)"
        )
        enf_params.extend([like, like])
        enf_sql = (
            "SELECT case_id, ministry, event_type, reason_excerpt, "
            "disclosed_date, source_url FROM enforcement_cases "
            f"WHERE {' AND '.join(enf_where)} "
            "ORDER BY COALESCE(disclosed_date,'') DESC, case_id LIMIT ?"
        )
        enf_params.append(limit)
        enf_rows = conn.execute(enf_sql, enf_params).fetchall()
        enf_out = [{
            "case_id": r["case_id"],
            "authority": r["ministry"],
            "action": r["event_type"] or (r["reason_excerpt"] or "")[:80],
            "published_at": r["disclosed_date"],
            "url": r["source_url"],
        } for r in enf_rows]
    finally:
        conn.close()

    payload: dict[str, Any] = {
        "industry": industry_norm,
        "prefecture": pref_norm,
        "company_size": company_size,
        "laws": laws_out,
        "certifications": certs_out,
        "tax_rulesets": tax_out,
        "recent_enforcement": enf_out,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    empty_sections = [
        name for name, arr in (
            ("laws", laws_out), ("certifications", certs_out),
            ("tax_rulesets", tax_out), ("recent_enforcement", enf_out),
        ) if not arr
    ]
    if len(empty_sections) == 4:
        envelope: dict[str, Any] = {"error": {
            "code": "no_matching_records",
            "message": f"industry={industry!r} prefecture={prefecture!r} で全セクション 0 件.",
            "hint": (
                "industry を JSIC 大分類 letter ('A'..'T') か '農業' / '製造業' などの "
                "和名で再試行、または prefecture=None で全国コーパスから探してください。"
            ),
        }}
        if input_warnings:
            envelope["input_warnings"] = input_warnings
        return envelope
    if empty_sections:
        payload["hint"] = (
            f"empty: {','.join(empty_sections)}. industry='{industry_norm}' の "
            f"LIKE keyword='{keyword}' で 0 件。より広い 業種コード ('A'..'T') か "
            "prefecture=None で再試行してください。"
        )
    if input_warnings:
        payload["input_warnings"] = input_warnings
    return payload


def _init_sentry_mcp() -> None:
    """Mirror of api.main._init_sentry for the stdio MCP server.

    We cannot reuse the FastAPI version because this process has no HTTP
    stack — Starlette/FastAPI integrations would be dead weight and would
    emit noisy warnings. Same scrubbers, same env vars.
    """
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk

        from jpintel_mcp.api.sentry_filters import (
            sentry_before_send,
            sentry_before_send_transaction,
        )
    except ImportError:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        send_default_pii=False,
        include_local_variables=False,
        max_breadcrumbs=50,
        before_send=sentry_before_send,
        before_send_transaction=sentry_before_send_transaction,
    )


# AutonoMath am_* tool package — importing triggers @mcp.tool registration
# for 24 new tools (10 in tools.py + 1 in tax_rule_tool.py + 5 in
# autonomath_wrappers.py + 1 in sunset_tool.py + 1 in annotation_tools.py +
# 1 in validation_tools.py + 2 in provenance_tools.py + 1 in
# multilingual_abstract_tool.py [R7 program_abstract_structured] + 1 in
# graph_traverse_tool.py [O7 heterogeneous KG walk over v_am_relation_all] +
# 1 in prerequisite_chain_tool.py [R5 前提認定 chain over am_prerequisite_bundle]).
# Must come after `mcp = FastMCP(...)` above so shared-instance decoration
# succeeds. Gated by AUTONOMATH_ENABLED for rollback safety — flip False
# if autonomath.db becomes unavailable.
#
# β1 wiring: the autonomath_tools submodules decorate their @mcp.tool
# functions WITHOUT @_with_mcp_telemetry (the in-file 38 tools all wrap
# manually). To get response-envelope v2 hint fields onto those tools
# too, we monkey-patch `mcp.tool()` for the duration of the import so
# every @mcp.tool inside the package is auto-wrapped via
# _with_mcp_telemetry (which now performs both telemetry + envelope
# merge). Patch is reverted before falling through to the rest of the
# file, so any post-import @mcp.tool calls remain manual.
if settings.autonomath_enabled:
    _orig_mcp_tool = mcp.tool

    def _mcp_tool_with_envelope(*deco_args: Any, **deco_kwargs: Any) -> Any:
        decorator = _orig_mcp_tool(*deco_args, **deco_kwargs)

        def _outer(fn: Any) -> Any:
            # Skip if telemetry wrapper is already present — defensive
            # against any module that decorates twice. We tag the wrapped
            # function with `_envelope_wired` so re-entry is a no-op.
            if not getattr(fn, "_envelope_wired", False):
                fn = _with_mcp_telemetry(fn)
                fn._envelope_wired = True  # type: ignore[attr-defined]
            return decorator(fn)

        return _outer

    mcp.tool = _mcp_tool_with_envelope  # type: ignore[method-assign]
    try:
        from jpintel_mcp.mcp import autonomath_tools  # noqa: E402,F401
    finally:
        mcp.tool = _orig_mcp_tool  # type: ignore[method-assign]
    # provenance_tools is auto-registered transitively via the package
    # __init__.py (V4 Phase 4: get_provenance + get_provenance_for_fact).

    # Re-export the registered _am tool under its short name so callers
    # can `from jpintel_mcp.mcp.server import search_acceptance_stats`.
    # `prefecture` is accepted as an alias for the underlying `region`
    # parameter to match the public spec ({program_name, year, prefecture}).
    #
    # Import is deferred to call-time to avoid a circular-import crash on
    # the api.main → api.autonomath → autonomath_tools.tools → server.py
    # path: when api.main pulls this module transitively, tools.py is still
    # mid-initialization, so a module-scope `from ...tools import X` fails.
    def search_acceptance_stats(  # noqa: D401 — thin re-export
        program_name: str | None = None,
        year: int | None = None,
        prefecture: str | None = None,
        region: str | None = None,
        industry: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Thin re-export of search_acceptance_stats_am with `prefecture`
        accepted as an alias for `region`. Returns the same dict shape
        (total / limit / offset / results / hint? / retry_with? / error?).
        """
        from jpintel_mcp.mcp.autonomath_tools.tools import (
            search_acceptance_stats_am as _search_acceptance_stats_am,
        )

        eff_region = region or prefecture
        return _search_acceptance_stats_am(
            program_name=program_name,
            year=year,
            region=eff_region,
            industry=industry,
            limit=limit,
            offset=offset,
        )


# Healthcare V3 stub package — 6 stub tools (P6-D W4 prep, scaffolding only).
# Importing the package triggers @mcp.tool registration. Real SQL bodies
# land in W4 (T+90d, 2026-08-04). Default-off so the public 55-tool
# manifest stays stable through the 2026-05-06 launch; operators flip
# AUTONOMATH_HEALTHCARE_ENABLED=1 to preview the contract surface (61
# tools = 55 + 6 stubs). See docs/healthcare_v3_plan.md.
if settings.healthcare_enabled:
    # Apply the same envelope-wiring monkey-patch (β1) to the stub
    # tools so they emit response-envelope v2 hint fields too.
    _orig_mcp_tool = mcp.tool

    def _mcp_tool_with_envelope_hc(*deco_args: Any, **deco_kwargs: Any) -> Any:
        decorator = _orig_mcp_tool(*deco_args, **deco_kwargs)

        def _outer(fn: Any) -> Any:
            if not getattr(fn, "_envelope_wired", False):
                fn = _with_mcp_telemetry(fn)
                fn._envelope_wired = True  # type: ignore[attr-defined]
            return decorator(fn)

        return _outer

    mcp.tool = _mcp_tool_with_envelope_hc  # type: ignore[method-assign]
    try:
        from jpintel_mcp.mcp import healthcare_tools  # noqa: E402,F401
    finally:
        mcp.tool = _orig_mcp_tool  # type: ignore[method-assign]


# Real Estate V5 stub package — 5 stub tools (P6-F W4 prep, scaffolding only).
# Importing the package triggers @mcp.tool registration. Real SQL bodies
# land at T+200d (target 2026-11-22), backed by migration 042 (already
# applied: real_estate_programs + zoning_overlays). Default-off so the
# public 55-tool manifest stays stable through the 2026-05-06 launch;
# operators flip AUTONOMATH_REAL_ESTATE_ENABLED=1 to preview the contract
# surface (60 tools = 55 + 5 stubs). See docs/real_estate_v5_plan.md.
if settings.real_estate_enabled:
    _orig_mcp_tool = mcp.tool

    def _mcp_tool_with_envelope_re(*deco_args: Any, **deco_kwargs: Any) -> Any:
        decorator = _orig_mcp_tool(*deco_args, **deco_kwargs)

        def _outer(fn: Any) -> Any:
            if not getattr(fn, "_envelope_wired", False):
                fn = _with_mcp_telemetry(fn)
                fn._envelope_wired = True  # type: ignore[attr-defined]
            return decorator(fn)

        return _outer

    mcp.tool = _mcp_tool_with_envelope_re  # type: ignore[method-assign]
    try:
        from jpintel_mcp.mcp import real_estate_tools  # noqa: E402,F401
    finally:
        mcp.tool = _orig_mcp_tool  # type: ignore[method-assign]


def run() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    _init_sentry_mcp()
    init_db()
    # === S3 HTTP FALLBACK: probe local DB at startup ===
    # Cache the fallback decision once. ``detect_fallback_mode()`` returns
    # True iff the local ``data/jpintel.db`` is empty / missing — typical
    # of a ``uvx autonomath-mcp`` install where the wheel ships without
    # data/. When True, the 10 wired tools route to ``api.autonomath.ai``
    # transparently; the remaining tools surface ``remote_only`` envelopes.
    # Logs the decision so operators see it in stdio handshake noise.
    _fallback = detect_fallback_mode()
    logger.info("startup_http_fallback_mode=%s", _fallback)
    # === END S3 HTTP FALLBACK ============================
    # === DEVICE FLOW AUTH PATCH: startup check ===
    # Logs whether a token is already stored in the OS keychain. No-op
    # if anonymous (50/month free quota applies). See jpintel_mcp.mcp.auth.
    ensure_authenticated()
    # === END DEVICE FLOW AUTH PATCH ==============
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run()
