"""AutonoMath MCP new tools — 8 tools wired to autonomath.db (wave 3, 2026-04-24).

Wave-2 delivered the stub scaffold (signatures + docstrings + envelope
shape). Wave-3 (this file) wires each tool to the real SQLite backend at
``/tmp/autonomath_infra_2026-04-24/autonomath.db`` (190K entities, 2.4M
facts, FTS5 trigram) and the graph store at
``/tmp/autonomath_infra_2026-04-24/graph/graph.sqlite`` (13K edges).

Data model (read-only):
  * ``am_entities``             — one row per record; ``raw_json`` keeps the
    lossless source payload (queryable via SQLite ``json_extract``).
  * ``am_entity_facts``         — normalized facts (EAV, ~2.4M rows). We use
    these sparingly — most tool queries go directly against ``raw_json``.
  * ``am_entities_fts``         — FTS5 trigram over ``primary_name`` +
    ``raw_json`` for free-text search.
  * ``am_law`` / ``am_authority`` / ``am_region`` — reference dimensions.
  * ``graph.sqlite::am_relation`` — directed edges, typed
    (prerequisite / compatible / incompatible / replaces / amends / related /
    has_authority / available_in / applies_to_industry / applies_to_size /
    references_law).

Envelope shape matches the existing 12 server.py tools exactly:
  ``{total, limit, offset, results[], hint?, retry_with?}`` — except for
  ``enum_values`` (utility) and ``related_programs`` (graph). The test
  harness at ``test_stub.py`` enforces this.

Merge plan (jpintel-mcp is READ ONLY per user instruction):
  At merge time, swap the ``mcp = FastMCP(...)`` init for
  ``from jpintel_mcp.mcp.server import mcp, _READ_ONLY`` and cut-and-paste
  the 8 tools over. DB helpers import transparently because
  ``db.py`` has no jpintel-mcp coupling.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp._http_fallback import (  # === S3 HTTP FALLBACK ===
    detect_fallback_mode_autonomath,
    http_call,
)
from jpintel_mcp.mcp.server import (
    _READ_ONLY,
    _enforce_limit_cap,
    _resolve_shaped_fields,
    mcp,
)

from .db import (
    connect_autonomath,
    execute_with_retry,
)
from .error_envelope import ErrorCode, make_error

logger = logging.getLogger("jpintel.mcp.new")


# ---------------------------------------------------------------------------
# Shared helpers.
# ---------------------------------------------------------------------------


def _clamp_limit(limit: int, cap: int = 100) -> int:
    return max(1, min(cap, limit))


def _clamp_offset(offset: int) -> int:
    return max(0, offset)


def _today_iso() -> str:
    """Today's date in JST (UTC+9), ISO YYYY-MM-DD."""
    return (datetime.now(UTC) + timedelta(hours=9)).date().isoformat()


_AS_OF_PATTERN = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|today)$")


def _resolve_as_of(
    as_of: str | None,
    field: str = "as_of",
) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve an `as_of` parameter to a concrete ISO date string.

    Accepts ``'today'`` (literal sentinel, mapped to JST today),
    ``'YYYY-MM-DD'`` ISO date, or ``None`` (treated as ``'today'``).
    Returns ``(resolved_iso, None)`` on success or ``(None, error_envelope)``
    on a malformed string. Empty/whitespace strings collapse to today
    (lenient; matches the default).
    """
    if as_of is None:
        return _today_iso(), None
    s = str(as_of).strip()
    if not s or s.lower() == "today":
        return _today_iso(), None
    if not _AS_OF_PATTERN.match(s):
        return None, make_error(
            code="invalid_date_format",
            message=(f"{field} must be 'today' or ISO YYYY-MM-DD, got {s!r}"),
            hint=(f"Pass {field}='today' (default) or {field}='2026-05-01'."),
            field=field,
            suggested_tools=["enum_values"],
        )
    if _parse_iso_date(s) is None:
        return None, make_error(
            code="invalid_date_format",
            message=f"{field}={s!r} is not a valid calendar date",
            hint=f"Use a real date, e.g. {field}='2026-05-01'.",
            field=field,
            suggested_tools=["enum_values"],
        )
    return s, None


def _safe_json_loads(s: str | None) -> dict[str, Any]:
    if not s:
        return {}
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {}


def _fts_escape(q: str) -> str:
    """[DEPRECATED 2026-04-29] Legacy quote-stripper. Kept as a no-arg
    shim because external callers may still import it; new code MUST
    use ``_build_fts_match`` (re-exported below) for any FTS5 MATCH
    expression. The legacy stripper let single-kanji trigram overlap
    (e.g. ``税額控除`` vs ``ふるさと納税``) leak through — see CLAUDE.md
    "Common gotchas" / api/programs.py header for the fix rationale.
    """
    return (q or "").strip().replace('"', "")


# Canonical FTS5 query rewriter — defeats the trigram single-kanji
# overlap false-positive (CLAUDE.md gotcha) by phrase-quoting every
# token, NFKC normalizing 全角 ASCII / 半角カナ paste, and OR-injecting
# the kana-expansion table for the common 30-ish readings. This is the
# same builder ``api/programs.py`` uses; importing keeps the two
# surfaces in lockstep so a fix in one place benefits both REST + MCP.
from jpintel_mcp.api.programs import _build_fts_match  # noqa: E402


def _like_escape(q: str) -> str:
    """Escape SQL LIKE operator wildcards for user-supplied strings."""
    return (q or "").replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


_REGION_CLUSTERS: dict[str, list[str]] = {
    "北海道": ["北海道"],
    "東北": ["青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"],
    "関東": ["茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"],
    "中部": [
        "新潟県",
        "富山県",
        "石川県",
        "福井県",
        "山梨県",
        "長野県",
        "岐阜県",
        "静岡県",
        "愛知県",
    ],
    "近畿": ["三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"],
    "中国": ["鳥取県", "島根県", "岡山県", "広島県", "山口県"],
    "四国": ["徳島県", "香川県", "愛媛県", "高知県"],
    "九州": ["福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県"],
    "沖縄": ["沖縄県"],
}


def _expand_region(region: str | None) -> list[str] | None:
    """Expand a region keyword into a list of 都道府県 names. Returns None
    if ``region`` is None. 'national' returns an empty list to signal
    「どの都道府県でもない=全国枠」."""
    if region is None:
        return None
    if region == "national":
        return []
    if region in _REGION_CLUSTERS:
        return _REGION_CLUSTERS[region]
    return [region]


def _authority_domain_hints(authority: str | None) -> list[str]:
    """Map a Japanese authority name to likely ``source_url_domain`` values."""
    if not authority:
        return []
    mapping = {
        "国税庁": ["nta.go.jp"],
        "財務省": ["mof.go.jp"],
        "経済産業省": ["meti.go.jp", "chusho.meti.go.jp"],
        "中小企業庁": ["chusho.meti.go.jp"],
        "農林水産省": ["maff.go.jp"],
        "総務省": ["soumu.go.jp"],
        "国土交通省": ["mlit.go.jp"],
        "厚生労働省": ["mhlw.go.jp"],
        "内閣府": ["cao.go.jp"],
        "環境省": ["env.go.jp"],
        "日本健康会議": ["kenko-keiei.jp", "kenkokaigi.jp"],
    }
    return mapping.get(authority, [])


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row}


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    # Be lenient: accept "2027-03-31", "2027-03-31 (...)", "2027/03/31", etc.
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _validate_iso_date(
    s: str | None, field: str = "date"
) -> tuple[str | None, dict[str, Any] | None]:
    """Return (normalized_iso, None) or (None, error_envelope)."""
    if s is None:
        return None, None
    s_stripped = (s or "").strip()
    if not s_stripped:
        return None, None
    if _parse_iso_date(s_stripped) is None:
        return None, make_error(
            code="invalid_date_format",
            message=f"{field} must be ISO YYYY-MM-DD, got {s_stripped!r}",
            hint=f"Pass ISO 8601 date, e.g. {field}='2026-05-01'.",
            field=field,
            suggested_tools=["enum_values"],
        )
    return s_stripped, None


def _classify_sqlite_error(exc: sqlite3.Error) -> ErrorCode:
    """Map a sqlite3 error to one of our error codes."""
    msg = str(exc).lower()
    if "locked" in msg or "busy" in msg:
        return "db_locked"
    if (
        "no such table" in msg
        or "no such column" in msg
        or "unable to open" in msg
        or "not a database" in msg
    ):
        return "db_unavailable"
    return "internal"


def _db_error(
    exc: sqlite3.Error,
    tool_name: str,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Produce an error envelope for a DB exception."""
    code = _classify_sqlite_error(exc)
    if code == "db_locked":
        msg = "database is locked after retry budget. Retry with backoff."
        hint = "Wait 200-500ms then retry the same call. Transient WAL race."
    elif code == "db_unavailable":
        msg = f"DB unavailable for {tool_name}: {type(exc).__name__}"
        hint = "Not client-fixable. Report to operator; data subsystem offline."
    else:
        msg = f"Unexpected DB error in {tool_name}: {type(exc).__name__}"
        hint = "Retry once; if persistent, report with the query args."
    logger.exception("%s: DB error", tool_name)
    return make_error(
        code=code,
        message=msg,
        hint=hint,
        limit=limit,
        offset=offset,
    )


def _safe_tool(func):
    """Decorator: catch DB / file errors at the tool boundary.

    Every ``@mcp.tool`` body can raise ``sqlite3.OperationalError`` via
    ``execute_with_retry`` (locked/busy) or ``FileNotFoundError`` via
    ``connect_autonomath`` (db missing). Without this
    wrapper those propagate as raw Python exceptions to the MCP
    transport; the customer LLM sees a stack-trace string with no
    ``error.code``. We convert them to the canonical envelope.

    Catch-all ``Exception`` is also handled → ``code="internal"`` so
    novel bugs also respect the contract. The wrapper preserves the
    tool's signature (name, docstring, annotations) so FastMCP's
    introspection keeps working.
    """

    @functools.wraps(func)
    def _wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except sqlite3.Error as exc:
            limit = int(kwargs.get("limit", 20) or 20)
            offset = int(kwargs.get("offset", 0) or 0)
            return _db_error(exc, func.__name__, limit=limit, offset=offset)
        except FileNotFoundError as exc:
            logger.exception("%s: DB file missing", func.__name__)
            return make_error(
                code="db_unavailable",
                message=f"DB file missing for {func.__name__}: {exc}",
                hint=(
                    "Not client-fixable. The SQLite file is absent; report to "
                    "operator. Do not retry."
                ),
            )
        except Exception as exc:  # pragma: no cover — catch-all safety net
            logger.exception("%s: unhandled", func.__name__)
            return make_error(
                code="internal",
                message=(f"Unhandled exception in {func.__name__}: {type(exc).__name__}"),
                hint=("Retry once with backoff; if persistent, fall back to an alternative tool."),
            )

    return _wrapper


# ---------------------------------------------------------------------------
# 1. search_tax_incentives
# ---------------------------------------------------------------------------


_TAX_AUTHORITIES = Literal[
    "国税庁",
    "財務省",
    "経済産業省",
    "中小企業庁",
    "農林水産省",
    "総務省",
    "国土交通省",
    "厚生労働省",
    "自治体",
]

_TAX_ENTITY = Literal[
    "中小企業",
    "小規模事業者",
    "個人事業主",
    "大企業",
    "認定事業者",
    "青色申告者",
    "農業法人",
    "特定事業者等",
]


def _row_to_tax(row: sqlite3.Row) -> dict[str, Any]:
    raw = _safe_json_loads(row["raw_json"])
    rate = (
        raw.get("benefit_amount")
        or raw.get("amount_or_rate")
        or raw.get("special_depreciation_rate")
    )
    return {
        "id": raw.get("id") or row["canonical_id"],
        "canonical_id": row["canonical_id"],
        "name": row["primary_name"],
        "kind": raw.get("type") or raw.get("kind"),
        "tax_category": raw.get("tax_category"),
        "authority": raw.get("authority") or raw.get("ministry"),
        "government_level": raw.get("government_level"),
        "target_taxpayer": raw.get("target_taxpayer"),
        "amount_or_rate": rate,
        "tax_credit_rate_standard": raw.get("tax_credit_rate_standard"),
        "tax_credit_rate_small": raw.get("tax_credit_rate_small"),
        "root_law": raw.get("root_law"),
        "application_period_from": raw.get("application_period_from"),
        "application_period_to": raw.get("application_period_to"),
        "prerequisite_certification": raw.get("prerequisite_certification"),
        "eligible_assets": raw.get("eligible_assets"),
        "compatible_with": raw.get("compatible_with"),
        "source_url": row["source_url"],
        "source_excerpt": raw.get("source_excerpt"),
        "fetched_at": row["fetched_at"],
        "confidence": row["confidence"],
        "source_topic": row["source_topic"],
    }


# Token-shaping helpers (dd_v3_09 / v8 P3-K). Each row builder returns the
# legacy "full" shape; these trim down to {minimal,standard} for list
# rendering. Default = minimal so unannotated callers get the smallest
# payload (~120 B/row vs ~700 B/row full). The full shape preserves the
# raw_json-derived columns (root_law, eligible_assets, compatible_with, etc.)
# for callers that pass fields="full" explicitly.
def _trim_tax_fields(record: dict[str, Any], fields: str) -> dict[str, Any]:
    if fields == "minimal":
        return {
            "id": record.get("id") or record.get("canonical_id"),
            "name": record.get("name"),
            "score": record.get("confidence", 0),
            "source_url": record.get("source_url"),
        }
    if fields == "standard":
        return {
            "id": record.get("id") or record.get("canonical_id"),
            "name": record.get("name"),
            "score": record.get("confidence", 0),
            "source_url": record.get("source_url"),
            "authority": record.get("authority"),
            "tax_category": record.get("tax_category"),
            "amount_or_rate": record.get("amount_or_rate"),
            "application_period_to": record.get("application_period_to"),
            "fetched_at": record.get("fetched_at"),
            "summary": ((record.get("source_excerpt") or record.get("name") or "")[:120]),
        }
    return record  # full = existing complete shape


@mcp.tool(annotations=_READ_ONLY)
@_safe_tool
def search_tax_incentives(
    query: Annotated[
        str | None,
        Field(
            description=(
                "Free-text LIKE across name + target_taxpayer + "
                "root_law + eligible_assets. 3+ chars recommended "
                "(FTS5 trigram); 1-2 chars fall back to LIKE. "
                "Example: '経営強化税制' / '事業承継' / '特別償却' / "
                "'税額控除'."
            )
        ),
    ] = None,
    authority: Annotated[
        _TAX_AUTHORITIES | None,
        Field(
            description=(
                "Administering authority. Tax incentives are typically "
                "operated by 国税庁 (行政) + 経産省/農水省 etc. (制度所管)."
            )
        ),
    ] = None,
    industry: Annotated[
        str | None,
        Field(
            description=(
                "Sector keyword (resolved server-side against "
                "target_taxpayer + eligible_assets). Common: "
                "'農業', '製造業', '飲食業', 'IT', '建設業'."
            )
        ),
    ] = None,
    target_year: Annotated[
        int | None,
        Field(
            description=(
                "Fiscal year (西暦). 2025 = R7. Filter keeps rows where "
                "application_period_from <= :target_year-12-31 AND "
                "application_period_to >= :target_year-01-01."
            ),
            ge=1988,
            le=2099,
        ),
    ] = None,
    target_entity: Annotated[
        _TAX_ENTITY | None,
        Field(
            description=(
                "Applicant type. Tax incentives are tightly coupled to "
                "taxpayer class (青色申告者 / 中小企業者等 etc.) — "
                "filtering here prevents showing 大企業-only incentives "
                "to SMEs."
            )
        ),
    ] = None,
    natural_query: Annotated[
        str | None,
        Field(
            description=(
                "自然言語クエリ。指定すると query_rewrite 層が "
                "region / industry / size / authority / fiscal_year / "
                "funding_kind / purpose を自動抽出し、明示引数が空の "
                "スロットに充填する。明示引数が常に優先。"
                "例: '経産省の中小製造業向け令和8年度の税制優遇'."
            )
        ),
    ] = None,
    as_of: Annotated[
        str,
        Field(
            description=(
                "Effective-date filter (ISO YYYY-MM-DD or 'today'). "
                "Default 'today' (JST). Drops tax measures whose "
                "application_period_to has already passed; rows with "
                "no period_to are kept (treated as 恒久措置)."
            ),
            pattern=r"^(?:\d{4}-\d{2}-\d{2}|today)$",
        ),
    ] = "today",
    limit: Annotated[
        int,
        Field(
            description=(
                "Max rows. Token-shaping cap = 20 (dd_v3_09 / v8 P3-K); "
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
            description="Pagination offset (0-based row count to skip). Default 0. Combine with `limit` for paging through `total`.",
            ge=0,
        ),
    ] = 0,
    fields: Annotated[
        Literal["minimal", "standard", "full"],
        Field(
            description=(
                "Response shape per row. 'minimal' (default, ~120 B/row): "
                "{id, name, score, source_url}. "
                "'standard': + authority, tax_category, amount_or_rate, "
                "application_period_to, fetched_at, summary (source_excerpt "
                "truncated to 120 chars). "
                "'full': existing complete row including raw_json-derived "
                "fields (root_law, eligible_assets, compatible_with, "
                "tax_credit_rate_*, prerequisite_certification, etc.). "
                "Default switched to 'minimal' under dd_v3_09 / v8 P3-K "
                "token shaping; pass fields='full' when callers need the "
                "wider shape."
            ),
        ),
    ] = "minimal",
) -> dict[str, Any]:
    """DISCOVER (Tax): Search 35 Japanese tax incentives — corporate deductions (減価償却/試験研究費), tax credits (雇用/エネルギー/DX), special measures (租税特別措置).

    WHEN TO USE: User asks about 税額控除 / 租税特別措置 / 法人税 / 所得税 deductions or credits.
    WHEN NOT: For broader subsidies/grants → use search_programs. For specific tax rule lookup → use get_am_tax_rule.

    Returns rulesets with eligibility, applicable years, citation to NTA / 国税通達 / 措置法.

    [DISCOVER-TAX] Returns matching tax_measure records from the am_entities table with primary source URL. ~271 structured rows across 法人税 / 所得税 / 地方税 / 消費税. ¥3/req metered.
    Search Japanese tax incentives across 法人税 / 所得税 / 地方税 / 消費税 with structured amount_or_rate, root_law, application_period, prerequisite_certification.

    WHAT: ~271 structured records in `am_entities` where record_kind='tax_measure'
    (aggregated from 12_tax_incentives, 139_invoice_consumption_tax,
    140_income_tax_individual_deep, 149_corporate_tax_deep, 150_local_taxes_detail,
    26_agri_tax_incentives). Key columns: `amount_or_rate` (即時償却 vs 税額控除% vs
    非課税率), `root_law`, `application_period_from/to`, `prerequisite_certification`,
    `eligible_assets`. Every row cites 国税庁 / e-Gov / 財務省主税局 primary source.

    WHEN:
      - "事業承継税制の特例措置はいつまで適用できる?"
      - "中小企業経営強化税制 A 類型の税額控除率は?"
      - "インボイス制度の 2 割特例はいつ終わる?"
      - "農業経営基盤強化準備金の要件を教えて"
      - "経産省の中小製造業向け令和 8 年度の税制優遇は?" (natural_query 可)

    WHEN NOT:
      - `search_programs` instead for 補助金 / 助成金 (policy text, not tax rule).
      - `search_loan_programs` instead for 融資 (lending terms, not tax).
      - `search_certifications` instead for 認定制度 (cert may be a *prerequisite* for some
        tax incentives; this tool returns the tax rule itself).
      - `search_by_law` instead when the user names the **law** (租税特別措置法 etc.) and
        wants *all* program/tax/cert rows under it.

    RETURN: {total, limit, offset, results[], hint?, retry_with?}.

    LIMITATIONS:
      - FTS5 trigram causes single-kanji false hits (`税額控除` also matches rows mentioning
        only `税`). Wrap 2+ char kanji queries in quotes (`"税額控除"`) to force phrase match.
      - `target_year` filter uses `application_period_from/to`; rows lacking a window are
        excluded. 「適用期限なし (恒久措置)」 rows have `application_period_to=NULL` —
        they pass the filter but absence of a hard sunset is not guaranteed.
      - `amount_or_rate` is free-text ("7% 税額控除" / "即時償却" / "5年間 1/2 非課税"
        etc.); do not attempt numeric comparison. Surface verbatim.
      - `natural_query` scalar-extracts into region/industry/size/authority/fiscal_year but
        defers to explicit args. Scoped extraction (not full NLU).
      - `as_of` (default 'today' JST) drops sunset-expired rules; pass an ISO date
        (`as_of='2026-04-01'`) for historical "what was active at X" lookups. NULL-to
        rows (恒久措置) are always kept. `meta.data_as_of` echoes the resolved date.

    CHAIN:
      ← `intent_of` / `reason_answer` may route a tax-intent query here.
      → `search_certifications(query=prerequisite_certification)` when a row requires cert.
      → `search_by_law(law_name=root_law)` to see all co-governed rules.
      → `active_programs_at(date=pivot)` to check applicability at a specific date.
      DO NOT → chain `enum_values` after this; 本 tool の列は free-text が多い.

    EXAMPLE:
      Input:  query="事業承継", target_entity="中小企業", target_year=2026
      Output: {total: 2, limit: 20, offset: 0,
               results: [{name: "事業承継税制 特例措置",
                          amount_or_rate: "相続税・贈与税の猶予/免除",
                          application_period_to: "2027-12-31",
                          root_law: "租税特別措置法", ...}, ...]}

    0 件の場合は `hint` (再検索の提案) と `retry_with` (関連 tool 候補) を返します。
    """
    # === S3 HTTP FALLBACK ===
    if detect_fallback_mode_autonomath():
        clean = {
            "query": query,
            "authority": authority,
            "industry": industry,
            "target_year": target_year,
            "target_entity": target_entity,
            "natural_query": natural_query,
            "as_of": as_of,
            "limit": limit,
            "offset": offset,
            "fields": fields,
        }
        return http_call(
            "/v1/am/tax_incentives",
            params={k: v for k, v in clean.items() if v is not None},
        )
    # === END S3 HTTP FALLBACK ===
    # -- natural_query rewrite (wave-2 query_rewrite integration) -------------
    rewrite_plan: dict[str, Any] | None = None
    if natural_query:
        try:
            from query_rewrite.integrate import (
                rewrite_natural_query,
            )

            kwargs_in = {
                "authority": authority,
                "industry": industry,
                "fiscal_year": target_year,
            }
            merged, rp = rewrite_natural_query(
                natural_query,
                kwargs_in,
                allowed_keys={"authority", "industry", "fiscal_year"},
            )
            authority = merged.get("authority", authority)
            industry = merged.get("industry", industry)
            target_year = merged.get("fiscal_year", target_year)
            # If free-text query is empty, carry semantic residual forward.
            if not (query or "").strip() and merged.get("semantic_query"):
                query = merged["semantic_query"]
            rewrite_plan = rp.to_dict() if rp else None
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("query_rewrite failed: %s", exc)
    # ------------------------------------------------------------------------

    as_of_iso, as_of_err = _resolve_as_of(as_of, field="as_of")
    if as_of_err is not None:
        return as_of_err

    fields = _resolve_shaped_fields(fields)
    limit = _clamp_limit(limit)
    limit, limit_warnings = _enforce_limit_cap(limit, cap=20)
    offset = _clamp_offset(offset)

    conn = connect_autonomath()

    where: list[str] = ["e.record_kind = 'tax_measure'"]
    params: list[Any] = []
    use_fts = False

    q = (query or "").strip()
    if q:
        if len(q) >= 3:
            use_fts = True
        else:
            esc = _like_escape(q)
            where.append("(e.primary_name LIKE ? ESCAPE '\\' OR e.raw_json LIKE ? ESCAPE '\\')")
            params.extend([f"%{esc}%", f"%{esc}%"])

    if authority:
        hints = _authority_domain_hints(authority)
        if hints:
            placeholders = ",".join("?" for _ in hints)
            where.append(f"(e.source_url_domain IN ({placeholders}) OR e.raw_json LIKE ?)")
            params.extend(hints)
            params.append(f'%"{authority}"%')
        else:
            where.append("e.raw_json LIKE ?")
            params.append(f"%{authority}%")

    if industry:
        esc = _like_escape(industry)
        where.append("e.raw_json LIKE ? ESCAPE '\\'")
        params.append(f"%{esc}%")

    if target_entity:
        esc = _like_escape(target_entity)
        where.append(
            "(e.raw_json LIKE ? ESCAPE '\\' "
            "OR json_extract(e.raw_json, '$.target_taxpayer') LIKE ? ESCAPE '\\')"
        )
        params.extend([f"%{esc}%", f"%{esc}%"])

    if target_year is not None:
        # keep rows where window covers target_year (right-closed at Dec 31).
        # Some rows use 恒久 / null; we treat null-to as "permanent" and include.
        where.append(
            "((json_extract(e.raw_json,'$.application_period_from') IS NULL "
            "  OR substr(json_extract(e.raw_json,'$.application_period_from'),1,4) <= ?) "
            "AND (json_extract(e.raw_json,'$.application_period_to') IS NULL "
            "  OR substr(json_extract(e.raw_json,'$.application_period_to'),1,4) >= ?))"
        )
        params.extend([str(target_year), str(target_year)])

    # as_of filter: drop tax measures whose application_period_to is strictly
    # in the past relative to as_of_iso. NULL-tolerant (恒久措置 stays).
    where.append(
        "(json_extract(e.raw_json,'$.application_period_to') IS NULL "
        " OR substr(json_extract(e.raw_json,'$.application_period_to'),1,10) >= ?)"
    )
    params.append(as_of_iso)

    where_sql = " AND ".join(where)

    if use_fts:
        # FTS5 trigram search over primary_name + raw_json. Use the
        # canonical phrase-quoting builder so kanji compounds like
        # 「税額控除」 don't false-match 「ふるさと納税」 via single-kanji
        # trigram overlap (CLAUDE.md gotcha). If the rewriter returns
        # empty (punctuation-only / stripped), fall back to LIKE.
        fts_query = _build_fts_match(q)
        if not fts_query:
            esc = _like_escape(q)
            where.append("(e.primary_name LIKE ? ESCAPE '\\' OR e.raw_json LIKE ? ESCAPE '\\')")
            params.extend([f"%{esc}%", f"%{esc}%"])
            where_sql = " AND ".join(where)
            use_fts = False

    if use_fts:
        base_from = "am_entities e JOIN am_entities_fts f ON f.canonical_id = e.canonical_id"
        params_fts = [fts_query, *params]

        total_sql = (
            f"SELECT COUNT(*) FROM {base_from} WHERE f.am_entities_fts MATCH ? AND {where_sql}"
        )
        (total,) = conn.execute(total_sql, params_fts).fetchone()

        rows_sql = (
            f"SELECT e.* FROM {base_from} "
            f"WHERE f.am_entities_fts MATCH ? AND {where_sql} "
            f"ORDER BY e.confidence DESC, e.primary_name "
            f"LIMIT ? OFFSET ?"
        )
        rows = execute_with_retry(conn, rows_sql, [*params_fts, limit, offset])
    else:
        total_sql = f"SELECT COUNT(*) FROM am_entities e WHERE {where_sql}"
        (total,) = conn.execute(total_sql, params).fetchone()
        rows_sql = (
            f"SELECT e.* FROM am_entities e WHERE {where_sql} "
            f"ORDER BY e.confidence DESC, e.primary_name "
            f"LIMIT ? OFFSET ?"
        )
        rows = execute_with_retry(conn, rows_sql, [*params, limit, offset])

    results = [_trim_tax_fields(_row_to_tax(r), fields) for r in rows]

    payload: dict[str, Any] = {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "results": results,
        "meta": {"data_as_of": as_of_iso},
        "retrieval_note": (
            f"Filtered for tax measures effective as of {as_of_iso} JST "
            "(rows with no application_period_to are kept as 恒久措置)."
        ),
    }
    if limit_warnings:
        payload["input_warnings"] = limit_warnings
    if rewrite_plan is not None:
        payload["rewrite_plan"] = rewrite_plan
    if total == 0:
        err = make_error(
            code="no_matching_records",
            message="no 税制特例 (tax_measure) matched the filters.",
            hint=(
                "If the user meant 補助金 (cash grants), call search_programs. "
                "If 融資, call search_loan_programs. Use enum_values("
                "enum_name='tax_category') to list valid tax categories."
            ),
            retry_with=[
                "search_programs",
                "search_certifications",
                "search_by_law",
            ],
            suggested_tools=["enum_values"],
            limit=limit,
            offset=offset,
        )
        # Preserve the legacy hint/retry_with alongside the new error
        # envelope so existing clients that don't yet read ``error`` still
        # get actionable context.
        payload["hint"] = err["error"]["hint"]
        payload["retry_with"] = err["error"]["retry_with"]
        payload["error"] = err["error"]
    return payload


# ---------------------------------------------------------------------------
# 2. search_certifications
# ---------------------------------------------------------------------------


_CERT_AUTHORITIES = Literal[
    "経済産業省",
    "厚生労働省",
    "農林水産省",
    "内閣府",
    "環境省",
    "都道府県",
    "市町村",
    "日本健康会議",
    "認証機関",
]

_SIZE_VALUES = Literal["sole", "small", "sme", "mid", "large"]


def _row_to_cert(row: sqlite3.Row) -> dict[str, Any]:
    raw = _safe_json_loads(row["raw_json"])
    return {
        "id": raw.get("id") or row["canonical_id"],
        "canonical_id": row["canonical_id"],
        "program_name": raw.get("program_name") or row["primary_name"],
        "authority": raw.get("authority") or raw.get("certifying_org"),
        "root_law": raw.get("root_law"),
        "requirements": raw.get("requirements"),
        "benefits_after_certification": raw.get("benefits_after_certification"),
        "linked_subsidies": raw.get("linked_subsidies") or [],
        "linked_tax_incentives": raw.get("linked_tax_incentives") or [],
        "application_fee_yen": raw.get("application_fee_yen"),
        "processing_days_median": raw.get("processing_days_median"),
        "validity_years": raw.get("validity_years"),
        "target_size": raw.get("target_size") or raw.get("size_class"),
        "target_industries": raw.get("target_industries"),
        "official_url": raw.get("official_url") or row["source_url"],
        "source_url": row["source_url"],
        "fetched_at": row["fetched_at"],
        "confidence": row["confidence"],
        "source_topic": row["source_topic"],
    }


# Token-shaping for certifications (dd_v3_09 / v8 P3-K). The full shape
# preserves linked_subsidies / linked_tax_incentives / requirements which
# are the load-bearing columns for "what does this cert unlock?" callers
# — pass fields="full" explicitly when needed.
def _trim_cert_fields(record: dict[str, Any], fields: str) -> dict[str, Any]:
    if fields == "minimal":
        return {
            "id": record.get("id") or record.get("canonical_id"),
            "name": record.get("program_name"),
            "score": record.get("confidence", 0),
            "source_url": record.get("source_url"),
        }
    if fields == "standard":
        req = record.get("requirements")
        if isinstance(req, list):
            req_text = "; ".join(str(x) for x in req if x is not None)
        else:
            req_text = str(req) if req is not None else ""
        return {
            "id": record.get("id") or record.get("canonical_id"),
            "name": record.get("program_name"),
            "score": record.get("confidence", 0),
            "source_url": record.get("source_url"),
            "authority": record.get("authority"),
            "root_law": record.get("root_law"),
            "validity_years": record.get("validity_years"),
            "target_size": record.get("target_size"),
            "fetched_at": record.get("fetched_at"),
            "summary": (req_text[:120] if req_text else (record.get("program_name") or "")[:120]),
        }
    return record  # full = existing complete shape


@mcp.tool(annotations=_READ_ONLY)
@_safe_tool
def search_certifications(
    query: Annotated[
        str | None,
        Field(
            description=(
                "Free-text LIKE across program_name + requirements + "
                "benefits_after_certification. Example: '健康経営' / "
                "'えるぼし' / 'くるみん' / 'SDGs' / '経営革新'."
            )
        ),
    ] = None,
    authority: Annotated[
        _CERT_AUTHORITIES | None,
        Field(
            description=(
                "Issuing body. 経済産業省 / 日本健康会議 / 厚生労働省 / "
                "内閣府 / 都道府県 / 市町村, etc."
            )
        ),
    ] = None,
    size: Annotated[
        _SIZE_VALUES | None,
        Field(
            description="Applicant size class (closed-set, 中小企業基本法準拠). 'sole' = 個人事業主, 'small' = 小規模事業者 (製造20人/商業5人 以下), 'sme' = 中小企業, 'mid' = 中堅, 'large' = 大企業. None = 全 size 横断 (filter なし)."
        ),
    ] = None,
    industry: Annotated[
        str | None,
        Field(
            description="Sector keyword (LIKE substring on target_industries). e.g. '製造業' / '建設業' / 'IT' / '医療'. Use enum_values_am('industry') for JSIC 大分類 list."
        ),
    ] = None,
    as_of: Annotated[
        str,
        Field(
            description=(
                "Reference date (ISO YYYY-MM-DD or 'today'). Default "
                "'today' (JST). Certifications are durable (not "
                "windowed) so this is informational only — echoed in "
                "meta.data_as_of for audit / cache-key parity."
            ),
            pattern=r"^(?:\d{4}-\d{2}-\d{2}|today)$",
        ),
    ] = "today",
    limit: Annotated[
        int,
        Field(
            description=(
                "Max rows. Token-shaping cap = 20 (dd_v3_09 / v8 P3-K); "
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
            description="Pagination offset (0-based row count to skip). Default 0. Combine with `limit` for paging through `total`.",
            ge=0,
        ),
    ] = 0,
    fields: Annotated[
        Literal["minimal", "standard", "full"],
        Field(
            description=(
                "Response shape per row. 'minimal' (default, ~120 B/row): "
                "{id, name, score, source_url}. "
                "'standard': + authority, root_law, validity_years, "
                "target_size, fetched_at, summary (requirements truncated "
                "to 120 chars). "
                "'full': existing complete row including linked_subsidies, "
                "linked_tax_incentives, benefits_after_certification, "
                "requirements, target_industries, application_fee_yen, "
                "processing_days_median. Default switched to 'minimal' "
                "under dd_v3_09 / v8 P3-K token shaping; pass fields='full' "
                "to restore the legacy wide shape (the load-bearing fields "
                "for 'what does this cert unlock')."
            ),
        ),
    ] = "minimal",
) -> dict[str, Any]:
    """DISCOVER (Certifications): Search 66 Japanese certification programs (経営革新等支援機関認定 / 経営力向上計画 / 中小企業等経営強化法 etc.).

    WHEN TO USE: User asks about 認定制度 / 認定支援機関 / 経営革新承認.
    WHEN NOT: For non-certification subsidies → use search_programs. For specific authority data → use search_by_law.

    Returns certifications with issuing authority, eligibility, validity period.

    [CERT] Returns matching certification records (~53 rows: 健康経営優良法人 / えるぼし / くるみん / SDGs 未来都市 / 経営革新計画 / 経営力向上計画 等) with pre-joined linked_subsidies + linked_tax_incentives + benefits_after_certification. Output is search-derived; verify primary source for application requirements.
    Search Japanese business certifications with pre-joined linked_subsidies + linked_tax_incentives + benefits_after_certification.

    WHAT: ~53 records in `am_entities` where record_kind='certification'
    (aggregated from 09_certification_programs + 62_health_management_certification +
    sector-specific bundles). Key columns: `program_name`, `authority`, `requirements`,
    `benefits_after_certification[]`, `linked_subsidies[]`, `linked_tax_incentives[]`,
    `application_window`. Each row cites the issuing body's primary URL.

    WHEN:
      - "健康経営優良法人を取ると何が変わる?"
      - "えるぼし認定の要件は?"
      - "経営革新計画を取ったら使える補助金一覧"
      - "くるみん認定と健康経営、中小企業に向いてるのはどっち?"

    WHEN NOT:
      - `search_programs` instead for 補助金 / 助成金 definitions (cert is a prerequisite
        axis, not a funding program).
      - `search_tax_incentives` instead when the user already knows the tax rule and
        only needs the numeric rate.
      - `search_by_law` instead when the user names the **law** grounding the cert
        (e.g. 「中小企業等経営強化法に基づく認定」).

    RETURN: {total, limit, offset, results[], hint?, retry_with?}.

    LIMITATIONS:
      - `size` and `industry` are LIKE substring over `raw_json` (no normalized schema);
        typos silently skip matches. Prefer canonical tokens (`中小企業`, `製造業`).
      - `linked_subsidies[]` / `linked_tax_incentives[]` are **frozen at ingest time**;
        a new 補助金 citing this cert as prerequisite may not appear until the next
        nightly rebuild. Verify via `search_programs(query=cert_name)` reverse lookup.
      - Coverage is biased toward national certs (健康経営 / えるぼし / くるみん / 経営
        革新 / 経営力向上) — 自治体独自の認定 is sparse.

    CHAIN:
      ← `search_programs` / `search_tax_incentives` when a row has
        `prerequisite_certification` set — pass that name into `query` here.
      → `related_programs(program_id=cert_canonical_id)` for the full graph of linked
        programs (beyond the in-row snapshot).
      → `search_by_law(law_name=root_law)` when certs cluster under one law.

    EXAMPLE:
      Input:  query="健康経営", size="sme"
      Output: {total: 3, limit: 20, offset: 0,
               results: [{program_name: "健康経営優良法人 中小規模法人部門",
                          authority: "経済産業省 / 日本健康会議",
                          linked_subsidies: ["...", "..."],
                          linked_tax_incentives: [...], ...}],
               meta: {data_as_of: "2026-04-25"}}

    `as_of` is informational here (certifications are durable, no window
    column) — pass for parity with sibling search_* tools and to surface
    the snapshot date in `meta.data_as_of`.

    0 件の場合は `hint` (再検索の提案) と `retry_with` (関連 tool 候補) を返します。
    """
    # === S3 HTTP FALLBACK ===
    if detect_fallback_mode_autonomath():
        clean = {
            "query": query,
            "authority": authority,
            "size": size,
            "industry": industry,
            "as_of": as_of,
            "limit": limit,
            "offset": offset,
            "fields": fields,
        }
        return http_call(
            "/v1/am/certifications",
            params={k: v for k, v in clean.items() if v is not None},
        )
    # === END S3 HTTP FALLBACK ===
    as_of_iso, as_of_err = _resolve_as_of(as_of, field="as_of")
    if as_of_err is not None:
        return as_of_err

    fields = _resolve_shaped_fields(fields)
    limit = _clamp_limit(limit)
    limit, limit_warnings = _enforce_limit_cap(limit, cap=20)
    offset = _clamp_offset(offset)

    conn = connect_autonomath()

    where: list[str] = ["e.record_kind = 'certification'"]
    params: list[Any] = []
    use_fts = False

    q = (query or "").strip()
    if q:
        if len(q) >= 3:
            use_fts = True
        else:
            esc = _like_escape(q)
            where.append("e.raw_json LIKE ? ESCAPE '\\'")
            params.append(f"%{esc}%")

    if authority:
        hints = _authority_domain_hints(authority)
        conds: list[str] = ["e.raw_json LIKE ?"]
        auth_params: list[Any] = [f"%{authority}%"]
        if hints:
            placeholders = ",".join("?" for _ in hints)
            conds.append(f"e.source_url_domain IN ({placeholders})")
            auth_params.extend(hints)
        where.append("(" + " OR ".join(conds) + ")")
        params.extend(auth_params)

    if size:
        esc = _like_escape(size)
        where.append("e.raw_json LIKE ? ESCAPE '\\'")
        params.append(f"%{esc}%")

    if industry:
        esc = _like_escape(industry)
        where.append("e.raw_json LIKE ? ESCAPE '\\'")
        params.append(f"%{esc}%")

    where_sql = " AND ".join(where)

    if use_fts:
        # Phrase-quote via the canonical FTS5 rewriter (see search_tax_incentives
        # for rationale — defeats trigram single-kanji overlap). Empty rewrite
        # output means fall back to LIKE.
        fts_query = _build_fts_match(q)
        if not fts_query:
            esc = _like_escape(q)
            where.append("(e.primary_name LIKE ? ESCAPE '\\' OR e.raw_json LIKE ? ESCAPE '\\')")
            params.extend([f"%{esc}%", f"%{esc}%"])
            where_sql = " AND ".join(where)
            use_fts = False

    if use_fts:
        base_from = "am_entities e JOIN am_entities_fts f ON f.canonical_id = e.canonical_id"
        params_fts = [fts_query, *params]

        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM {base_from} WHERE f.am_entities_fts MATCH ? AND {where_sql}",
            params_fts,
        ).fetchone()
        rows = execute_with_retry(
            conn,
            f"SELECT e.* FROM {base_from} "
            f"WHERE f.am_entities_fts MATCH ? AND {where_sql} "
            f"ORDER BY e.confidence DESC, e.primary_name "
            f"LIMIT ? OFFSET ?",
            [*params_fts, limit, offset],
        )
    else:
        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM am_entities e WHERE {where_sql}", params
        ).fetchone()
        rows = execute_with_retry(
            conn,
            f"SELECT e.* FROM am_entities e WHERE {where_sql} "
            f"ORDER BY e.confidence DESC, e.primary_name "
            f"LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )

    results = [_trim_cert_fields(_row_to_cert(r), fields) for r in rows]

    payload: dict[str, Any] = {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "results": results,
        "meta": {"data_as_of": as_of_iso},
        "retrieval_note": (
            f"Snapshot of certifications as of {as_of_iso} JST. "
            "Certifications are durable (no application window), so "
            "as_of is informational only."
        ),
    }
    if limit_warnings:
        payload["input_warnings"] = limit_warnings
    if total == 0:
        err = make_error(
            code="no_matching_records",
            message="no 認定・認証制度 matched the filters.",
            hint=(
                "If the user asked for 補助金 (cash), switch to search_programs. "
                "If linked subsidies are the goal, call related_programs after "
                "resolving a cert id."
            ),
            retry_with=[
                "search_programs",
                "search_tax_incentives",
                "related_programs",
            ],
            suggested_tools=["enum_values"],
            limit=limit,
            offset=offset,
        )
        payload["hint"] = err["error"]["hint"]
        payload["retry_with"] = err["error"]["retry_with"]
        payload["error"] = err["error"]
    return payload


# ---------------------------------------------------------------------------
# 3. list_open_programs
# ---------------------------------------------------------------------------


_REGION_VALUES = Literal[
    "北海道",
    "東北",
    "関東",
    "中部",
    "近畿",
    "中国",
    "四国",
    "九州",
    "沖縄",
    "national",
]


def _row_to_program(row: sqlite3.Row) -> dict[str, Any]:
    raw = _safe_json_loads(row["raw_json"])
    return {
        "unified_id": raw.get("unified_id") or row["canonical_id"],
        "canonical_id": row["canonical_id"],
        "primary_name": raw.get("program_name") or row["primary_name"],
        "authority_name": raw.get("authority_name") or raw.get("ministry"),
        "authority_level": raw.get("authority_level"),
        "prefecture": raw.get("prefecture"),
        "program_kind": raw.get("program_kind"),
        "target_types": raw.get("target_types"),
        "amount_max_man_yen": raw.get("amount_max_man_yen"),
        "subsidy_rate": raw.get("subsidy_rate"),
        "application_window_open": (
            raw.get("application_open")
            or raw.get("application_window_open")
            or raw.get("application_period_from")
        ),
        "application_window_close": (
            raw.get("application_close")
            or raw.get("application_window_close")
            or raw.get("application_period_to")
        ),
        "round_label": raw.get("round_label"),
        "source_url": row["source_url"],
        "fetched_at": row["fetched_at"],
        "confidence": row["confidence"],
        "source_topic": row["source_topic"],
    }


@mcp.tool(annotations=_READ_ONLY)
@_safe_tool
def list_open_programs(
    on_date: Annotated[
        str | None,
        Field(
            description=(
                "ISO date (YYYY-MM-DD). Defaults to server-side today (JST). "
                "Legacy alias kept for backward compat — `as_of` is the "
                "preferred parameter (it accepts the literal 'today' too)."
            )
        ),
    ] = None,
    as_of: Annotated[
        str,
        Field(
            description=(
                "Pivot date (ISO YYYY-MM-DD or 'today'). Default 'today' "
                "(JST). Equivalent to `on_date`; if both supplied, an "
                "explicit `on_date` wins (legacy precedence)."
            ),
            pattern=r"^(?:\d{4}-\d{2}-\d{2}|today)$",
        ),
    ] = "today",
    region: Annotated[
        _REGION_VALUES | str | None,
        Field(
            description=(
                "Geographic scope filter (closed-set: '全国' / 47都道府県 + "
                "8 region 略称 e.g. '関東', '近畿'). Matches `region` column. "
                "Pass None for all regions."
            )
        ),
    ] = None,
    industry: Annotated[
        str | None,
        Field(
            description=(
                "Sector keyword (LIKE match against `industry` column). "
                "Free-text Japanese; common values: '製造業', '農業', "
                "'IT', '建設業', '小売'. Pass None for all industries."
            )
        ),
    ] = None,
    size: Annotated[
        _SIZE_VALUES | None,
        Field(
            description=(
                "Applicant size class (closed-set per 中小企業基本法). 'small' "
                "= 小規模事業者 (製造20人/商業5人 以下), 'sme' = 中小企業, "
                "'large' = 大企業, 'all' = 全社規模. None = no filter."
            )
        ),
    ] = None,
    natural_query: Annotated[
        str | None,
        Field(
            description=(
                "自然言語クエリ。指定すると query_rewrite 層が "
                "region/industry/size/on_date (OPEN_NOW) を自動抽出する。"
                "明示引数が常に優先。例: '今開いてる関東の中小製造業補助金'."
            )
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Max rows. Clamped to [1, 100]. Default 20.", ge=1, le=100),
    ] = 20,
) -> dict[str, Any]:
    """[TIMELINE] Returns programs whose application window covers the given date (default=今日 JST), sorted by days-until-close ascending. Output is search-derived; verify primary source (source_url) for the actual deadline before submission.
    List programs whose application window covers a given date, sorted by days-until-close ascending.

    WHAT: `am_entities` where record_kind='program', filtered by JSON
    `application_period_from/to` (or `application_open/close` /
    `application_window_open/close`). Rows with **no** window field at all are
    EXCLUDED (emits `hint` when coverage is partial). Returns `days_left` per row.

    WHEN:
      - "今開いてる補助金は?"
      - "2026-05-01 時点で応募できる補助金は?"
      - "関東の中小製造業で、今週締切の補助金は?"
      - "今開いてる関東の中小製造業補助金" (natural_query 可)

    WHEN NOT:
      - `search_programs` instead for the full catalog regardless of 募集窓口.
      - `active_programs_at` instead when the user asks 「〜時点で **有効だった**」
        (effective window, not application window — past tense historical queries).
      - `search_acceptance_stats` instead for 「採択された件数 / 採択率」(past
        adoption data, not current open calls).

    RETURN: {total, limit, offset, results[], pivot_date, hint?, retry_with?}.
    Each result row adds `days_left` (float; negative means past-due if edge case).

    LIMITATIONS:
      - **Coverage is partial**. Many program rows store 通年 / 随時 / empty or leave
        the window fields NULL — those rows are silently dropped. Missing rows do
        NOT mean the program is closed; verify via source URL.
      - Window is encoded in **>= 3 different JSON keys** across ingest topics
        (`application_period_*`, `application_open/close`,
        `application_window_open/close`). We COALESCE but schema drift may still
        hide rows — flag as `retry_with: ["search_programs"]` when hit=0.
      - `pivot_date` defaults to **JST today** (server-side). If the caller's
        timezone differs from JST, explicitly pass `on_date`.
      - `region="national"` means non-prefecture programs; passing a prefecture
        string narrows to that prefecture **only** (does not include national rows).

    CHAIN:
      → `get_program(unified_id=row.item_id)` for full detail of a candidate.
      → `search_acceptance_stats(program_name=row.item_name)` to gauge competitiveness.
      → `check_exclusions(program_ids=[...])` before the user commits to multiple
        simultaneous applications.
      DO NOT → loop `list_open_programs` on different dates; use a single
        `active_programs_at` call instead for historical sweeps.

    EXAMPLE:
      Input:  on_date="2026-05-01", region="関東", size="sme"
      Output: {total: 12, limit: 20, offset: 0, pivot_date: "2026-05-01",
               results: [{item_id: "...", item_name: "...",
                          days_left: 7.0, region: "東京都", ...}, ...]}

    0 件の場合は `hint` (再検索の提案) と `retry_with` (関連 tool 候補) を返します。
    """
    # === S3 HTTP FALLBACK ===
    if detect_fallback_mode_autonomath():
        clean = {
            "on_date": on_date,
            "as_of": as_of,
            "region": region,
            "industry": industry,
            "size": size,
            "natural_query": natural_query,
            "limit": limit,
        }
        return http_call(
            "/v1/am/open_programs",
            params={k: v for k, v in clean.items() if v is not None},
        )
    # === END S3 HTTP FALLBACK ===
    # -- natural_query rewrite ------------------------------------------------
    rewrite_plan: dict[str, Any] | None = None
    if natural_query:
        try:
            from query_rewrite.integrate import (
                rewrite_natural_query,
            )

            kwargs_in = {
                "region": region,
                "industry": industry,
                "size": size,
                "on_date": on_date,
            }
            merged, rp = rewrite_natural_query(
                natural_query,
                kwargs_in,
                allowed_keys={"region", "industry", "size", "on_date", "only_open"},
            )
            region = merged.get("region", region)
            industry = merged.get("industry", industry)
            size = merged.get("size", size)
            on_date = merged.get("on_date", on_date)
            rewrite_plan = rp.to_dict() if rp else None
        except Exception as exc:  # pragma: no cover
            logger.warning("query_rewrite failed: %s", exc)
    # ------------------------------------------------------------------------

    limit = _clamp_limit(limit)
    offset = 0

    # Precedence: explicit `on_date` (legacy) > `as_of` > default 'today'.
    # Both validate; both collapse to the same pivot ISO string.
    if on_date is not None:
        pivot, err = _validate_iso_date(on_date, field="on_date")
        if err is not None:
            return err
    else:
        pivot = None
    if pivot is None:
        pivot, err = _resolve_as_of(as_of, field="as_of")
        if err is not None:
            return err

    conn = connect_autonomath()

    where: list[str] = [
        "e.record_kind = 'program'",
        # Require at least one window bound so we don't mis-return rows lacking
        # any temporal signal.
        "(json_extract(e.raw_json,'$.application_period_from') IS NOT NULL "
        " OR json_extract(e.raw_json,'$.application_open') IS NOT NULL "
        " OR json_extract(e.raw_json,'$.application_window_open') IS NOT NULL)",
        # Window covers pivot (NULL-tolerant).
        "(COALESCE(json_extract(e.raw_json,'$.application_period_from'),"
        " json_extract(e.raw_json,'$.application_open'),"
        " json_extract(e.raw_json,'$.application_window_open'),"
        " '0000-01-01') <= ?)",
        "(COALESCE(json_extract(e.raw_json,'$.application_period_to'),"
        " json_extract(e.raw_json,'$.application_close'),"
        " json_extract(e.raw_json,'$.application_window_close'),"
        " '9999-12-31') >= ?)",
    ]
    params: list[Any] = [pivot, pivot]

    prefectures = _expand_region(region)
    if prefectures is not None:
        if len(prefectures) == 0:
            # national-only
            where.append(
                "(json_extract(e.raw_json,'$.authority_level') IS NULL "
                "OR json_extract(e.raw_json,'$.authority_level') NOT IN "
                "('prefecture','municipality'))"
            )
        else:
            placeholders = ",".join("?" for _ in prefectures)
            where.append(f"json_extract(e.raw_json,'$.prefecture') IN ({placeholders})")
            params.extend(prefectures)

    if industry:
        esc = _like_escape(industry)
        where.append("e.raw_json LIKE ? ESCAPE '\\'")
        params.append(f"%{esc}%")

    if size:
        esc = _like_escape(size)
        where.append("e.raw_json LIKE ? ESCAPE '\\'")
        params.append(f"%{esc}%")

    where_sql = " AND ".join(where)

    (total,) = conn.execute(
        f"SELECT COUNT(*) FROM am_entities e WHERE {where_sql}", params
    ).fetchone()

    order_expr = (
        "julianday(COALESCE(json_extract(e.raw_json,'$.application_period_to'),"
        " json_extract(e.raw_json,'$.application_close'),"
        " json_extract(e.raw_json,'$.application_window_close'),"
        " '9999-12-31')) - julianday(?)"
    )

    rows = execute_with_retry(
        conn,
        f"SELECT e.*, ({order_expr}) AS days_left "
        f"FROM am_entities e WHERE {where_sql} "
        f"ORDER BY days_left ASC, e.primary_name "
        f"LIMIT ? OFFSET ?",
        [pivot, *params, limit, offset],
    )

    pivot_date = _parse_iso_date(pivot)
    results: list[dict[str, Any]] = []
    for r in rows:
        d = _row_to_program(r)
        close = _parse_iso_date(d.get("application_window_close"))
        if close is not None and pivot_date is not None:
            d["days_until_close"] = (close - pivot_date).days
        else:
            d["days_until_close"] = None
        d["window_status"] = "open"
        results.append(d)

    payload: dict[str, Any] = {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "results": results,
        "pivot_date": pivot,
        "meta": {"data_as_of": pivot},
        "retrieval_note": (
            f"Filtered for programs with application window covering "
            f"{pivot} JST (~40% of catalog has window data; rows without "
            "window are excluded — see search_programs for full catalog)."
        ),
    }
    if rewrite_plan is not None:
        payload["rewrite_plan"] = rewrite_plan
    if total == 0:
        err = make_error(
            code="no_matching_records",
            message="no programs have an application window covering this date.",
            hint=(
                "application_window coverage is ~40% of programs; rows without "
                "window data are excluded by design. Try search_programs without "
                "the window filter, or active_programs_at for effectivity-window "
                "semantics."
            ),
            retry_with=["search_programs", "active_programs_at"],
            suggested_tools=["enum_values"],
            retry_args={"on_date": None},
            limit=limit,
            offset=offset,
        )
        payload["hint"] = err["error"]["hint"]
        payload["retry_with"] = err["error"]["retry_with"]
        payload["error"] = err["error"]
    return payload


# ---------------------------------------------------------------------------
# 4. enum_values
# ---------------------------------------------------------------------------


_EnumName = Literal[
    "authority",
    "tier",
    "industry",
    "funding_purpose",
    "target_type",
    "region",
    "tax_category",
    "program_kind",
    "loan_type",
    "event_type",
    "ministry",
    "certification_authority",
]


_ENUM_SPECS: dict[str, dict[str, Any]] = {
    "authority": {
        "sql": (
            "SELECT json_extract(raw_json,'$.authority_name') AS v, COUNT(*) n "
            "FROM am_entities WHERE v IS NOT NULL AND v != '' GROUP BY v "
            "ORDER BY n DESC"
        ),
        "description": "programs.authority_name の独立値 (frequency ≥ 1)",
    },
    "ministry": {
        "sql": (
            "SELECT json_extract(raw_json,'$.ministry') AS v, COUNT(*) n "
            "FROM am_entities WHERE v IS NOT NULL AND v != '' GROUP BY v "
            "ORDER BY n DESC"
        ),
        "description": "programs.ministry の独立値",
    },
    "certification_authority": {
        "sql": (
            "SELECT json_extract(raw_json,'$.authority') AS v, COUNT(*) n "
            "FROM am_entities WHERE record_kind='certification' AND v IS NOT NULL "
            "GROUP BY v ORDER BY n DESC"
        ),
        "description": "certifications.authority の独立値",
    },
    "tier": {
        "sql": (
            "SELECT CASE WHEN confidence>=0.9 THEN 'S' "
            "WHEN confidence>=0.8 THEN 'A' "
            "WHEN confidence>=0.6 THEN 'B' "
            "WHEN confidence>=0.3 THEN 'C' "
            "ELSE 'X' END AS v, COUNT(*) n "
            "FROM am_entities GROUP BY v ORDER BY n DESC"
        ),
        "description": "am_entities.confidence から導出した Tier 分布",
    },
    "industry": {
        "sql": (
            "SELECT jsic_name_ja AS v, COUNT(*) n FROM am_industry_jsic "
            "WHERE jsic_level='major' GROUP BY v ORDER BY n DESC"
        ),
        "description": "JSIC 大分類 (有効値 = 業種別検索に渡せる)",
    },
    "funding_purpose": {
        "sql": (
            "SELECT json_extract(raw_json,'$.program_kind') AS v, COUNT(*) n "
            "FROM am_entities WHERE record_kind='program' AND v IS NOT NULL "
            "GROUP BY v ORDER BY n DESC"
        ),
        "description": "programs.program_kind の独立値",
    },
    "target_type": {
        "sql": (
            "SELECT v, COUNT(*) n FROM ("
            "SELECT DISTINCT e.canonical_id, je.value AS v "
            "FROM am_entities e, "
            "json_each(COALESCE(json_extract(e.raw_json,'$.target_types'),'[]')) je "
            "WHERE e.record_kind='program'"
            ") GROUP BY v ORDER BY n DESC"
        ),
        "description": "programs.target_types の要素独立値",
    },
    "region": {
        "sql": (
            "SELECT name_ja AS v, COUNT(*) n FROM am_region "
            "WHERE region_level='prefecture' GROUP BY v ORDER BY n DESC"
        ),
        "description": "47 都道府県 (prefecture level)",
    },
    "tax_category": {
        "sql": (
            "SELECT json_extract(raw_json,'$.tax_category') AS v, COUNT(*) n "
            "FROM am_entities WHERE record_kind='tax_measure' AND v IS NOT NULL "
            "GROUP BY v ORDER BY n DESC"
        ),
        "description": "tax_measure.tax_category の独立値",
    },
    "program_kind": {
        "sql": (
            "SELECT json_extract(raw_json,'$.program_kind') AS v, COUNT(*) n "
            "FROM am_entities WHERE record_kind='program' AND v IS NOT NULL "
            "GROUP BY v ORDER BY n DESC"
        ),
        "description": "programs.program_kind の独立値",
    },
    "loan_type": {
        "sql": (
            "SELECT json_extract(raw_json,'$.loan_type') AS v, COUNT(*) n "
            "FROM am_entities WHERE source_topic='08_loan_programs' AND v IS NOT NULL "
            "GROUP BY v ORDER BY n DESC"
        ),
        "description": "loan_programs.loan_type の独立値",
    },
    "event_type": {
        "sql": (
            "SELECT json_extract(raw_json,'$.event_type') AS v, COUNT(*) n "
            "FROM am_entities WHERE record_kind='enforcement' AND v IS NOT NULL "
            "GROUP BY v ORDER BY n DESC"
        ),
        "description": "enforcement.event_type の独立値",
    },
}


@mcp.tool(annotations=_READ_ONLY)
@_safe_tool
def enum_values_am(
    enum_name: Annotated[
        _EnumName,
        Field(
            description="Enum field to enumerate. Closed-set: 'authority', 'tier', 'industry' (JSIC 大分類), 'funding_purpose', 'target_type', 'region' (47 都道府県), 'tax_category', 'program_kind', 'loan_type', 'event_type', 'ministry', 'certification_authority'."
        ),
    ],
) -> dict[str, Any]:
    """[UTILITY] Returns the canonical enum values + row counts for filter arguments used by other tools (target_type / authority_level / funding_purpose / prefecture / program_kind 等), so callers can avoid typos that cause 0-hit searches.
    Probe canonical enum values with live row-count, so downstream search_* filters never silently drop matches from typos.

    WHAT: Live aggregation over `am_entities.raw_json` (no materialized view; each
    call < 200ms thanks to `functools.lru_cache` per process). Returns per-value
    frequency; values are ranked descending by count so top-N is representative.

    WHEN:
      - "target_type の指定可能値は?"
      - "authority_level は何を受け付ける?"
      - After a zero-hit `search_*` call, to confirm the filter value was canonical.
      - 新しい session で初回 search の前に一度だけ呼んで vocabulary を確認.

    WHEN NOT:
      - Skip if you already know the canonical value (don't re-call each turn).
      - For **free-text** (prefecture 都道府県フル名, program name, 法人番号 等)
        の verification には使うな — enum は有限集合のみ。
      - `get_meta` instead when the user asks "データはいつ更新された / 何件ある?"
        (coverage / freshness, not enum values).

    RETURN: {enum_name, values[], frequency_map: {value: count}, last_updated, description}.
    NOTE: envelope shape **differs** from search_* tools — this is a utility, not a list.

    LIMITATIONS:
      - Values are de-duplicated across EN/JP synonyms (`個人事業主` vs `sole_proprietor`
        may both appear). Prefer the JP form for JP-facing copy; matcher side
        normalizes on search.
      - `frequency_map` reflects the **current** DB snapshot. Long-tail values with
        count=1 are not reliable filter targets.
      - Invalid `enum_name` returns the hybrid shape with `error` populated and
        `values=[]` — do not treat `values=[]` as "no data".

    CHAIN:
      → any `search_*` tool with a verified value.
      DO NOT → call `enum_values` more than once per enum per session; cache the
        result client-side. Do not chain `enum_values → enum_values` for different
        enums unless actually needed.

    EXAMPLE:
      Input:  enum_name="target_type"
      Output: {enum_name: "target_type",
               values: ["中小企業", "個人事業主", ...],
               frequency_map: {"中小企業": 3124, "個人事業主": 2744, ...},
               last_updated: "2026-04-24",
               description: "Applicant type tag; JP / EN synonyms coexist."}
    """
    return _enum_values_cached(enum_name)


@functools.lru_cache(maxsize=32)
def _enum_values_cached(enum_name: str) -> dict[str, Any]:
    """Cached enum aggregation. Enum queries scan the whole am_entities table
    (json_extract) and can take ~1s; the result is stable for the DB snapshot
    so we memoize per process. `enum_values` is intended to be called once
    per session (see docstring WHEN NOT)."""
    spec = _ENUM_SPECS.get(enum_name)
    if spec is None:
        err = make_error(
            code="invalid_enum",
            message=f"enum '{enum_name}' is not registered.",
            hint=(
                f"Valid enum_name values: {sorted(_ENUM_SPECS.keys())}. "
                "Call enum_values with one of those to list its values."
            ),
            field="enum_name",
            retry_args={"enum_name": sorted(_ENUM_SPECS.keys())[0]},
        )
        # Return a hybrid: keep legacy shape for clients, add error.
        return {
            "enum_name": enum_name,
            "values": [],
            "frequency_map": {},
            "last_updated": None,
            "description": f"enum '{enum_name}' is not registered.",
            "error": err["error"],
        }

    conn = connect_autonomath()
    rows = execute_with_retry(conn, spec["sql"])
    values: list[str] = []
    freq: dict[str, int] = {}
    for r in rows:
        v = r["v"]
        n = int(r["n"])
        if v is None:
            continue
        v_str = str(v)
        if not v_str:
            continue
        values.append(v_str)
        freq[v_str] = n

    return {
        "enum_name": enum_name,
        "values": values,
        "frequency_map": freq,
        "last_updated": _today_iso(),
        "description": spec["description"],
    }


# ---------------------------------------------------------------------------
# 5. search_by_law
# ---------------------------------------------------------------------------


def _law_aliases(law_name: str) -> list[str]:
    """Return [canonical + aliases] from am_law / am_alias."""
    conn = connect_autonomath()
    names: list[str] = [law_name]
    rows = execute_with_retry(
        conn,
        "SELECT canonical_id, canonical_name, short_name FROM am_law "
        "WHERE canonical_name LIKE ? OR short_name LIKE ?",
        [f"%{law_name}%", f"%{law_name}%"],
    )
    for r in rows:
        names.append(r["canonical_name"])
        if r["short_name"]:
            names.append(r["short_name"])
    # am_alias wider lookup
    alias_rows = execute_with_retry(
        conn,
        "SELECT DISTINCT a2.alias FROM am_alias a1 "
        "JOIN am_alias a2 ON a2.canonical_id = a1.canonical_id "
        "  AND a2.entity_table = a1.entity_table "
        "WHERE a1.entity_table='am_law' AND a1.alias LIKE ?",
        [f"%{law_name}%"],
    )
    for r in alias_rows:
        names.append(r["alias"])
    # dedup while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


@mcp.tool(annotations=_READ_ONLY)
@_safe_tool
def search_by_law(
    law_name: Annotated[
        str,
        Field(
            description=(
                "Law name (fuzzy LIKE). Canonical ('租税特別措置法') or "
                "colloquial ('大店立地法') accepted."
            )
        ),
    ],
    article: Annotated[
        str | None,
        Field(
            description="Optional 条項 filter (LIKE substring on raw_json). Format examples: '第22条' / '第42条の12の4' / '附則第3条'. Most rows lack 条項 metadata so a strict article filter often drops to 0 — `hint` will recommend retrying without."
        ),
    ] = None,
    amendment_date: Annotated[
        str | None,
        Field(
            description="Optional ISO date (YYYY-MM-DD) of law amendment. Rows with `amendment_date IS NULL` (恒久法) are still returned to avoid false-dropping."
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Max rows. Clamped to [1, 100]. Default 20.", ge=1, le=100),
    ] = 20,
    offset: Annotated[
        int,
        Field(
            description="Pagination offset (0-based row count to skip). Default 0. Combine with `limit` for paging through `total`.",
            ge=0,
        ),
    ] = 0,
) -> dict[str, Any]:
    """[DISCOVER-LAW] Returns programs / tax_measures / certifications / law rows linked to a given law name (canonical or colloquial). Uses `am_alias` + `am_law.short_name` for alias resolution. Output is search-derived; verify primary source (source_url) for legal interpretation.
    Cross-kind enumeration of programs / tax_measures / certifications / law entries grounded in a single 法令.

    WHAT: Joins across `am_entities` (record_kind IN program / tax_measure /
    certification / law) on the `root_law` / `references_law` JSON fields plus a
    graph-table `references_law` edge walk. Alias resolution uses `am_law` +
    `am_alias` tables (`law_aliases_tried` 配列を返り値に含める — 検索対象が透明).

    WHEN:
      - "大店立地法に基づく届出が必要な制度は?"
      - "租税特別措置法 第 42 条の 12 の 4 関連の制度を一覧"
      - "中小企業等経営強化法で使える支援策は?"
      - "省エネ法改正後に新しく出た補助金は?"

    WHEN NOT:
      - `search_programs` instead when the user names a **program** directly (not a law).
      - `search_tax_incentives` instead when the user names a **tax measure** directly.
      - `related_programs` instead when the user asks 「A の前提になる / A と併用可能な」
        (program-to-program graph walk, not law-based enumeration).

    RETURN: {total, limit, offset, results[], law_aliases_tried[], hint?, retry_with?}.
    Each result has `item_kind` (program / tax_incentive / certification / law),
    `item_id`, `item_name`, `root_law`, `article`, `law_no`, `amendment_date`,
    `match_method` (exact / alias).

    LIMITATIONS:
      - `article` filter is LIKE substring on `raw_json`; **most rows lack 条項
        metadata** — a specific article filter frequently drops all rows. When
        result=0 with article, the `hint` surfaces the advice to retry without.
      - `amendment_date` filter accepts rows with `amendment_date IS NULL`
        (恒久法) to avoid false-dropping.
      - Alias expansion is lexical (LIKE), so 「公害防止法」 like colloquial names
        may over-match. Review `law_aliases_tried` in the response to verify intent.
      - Hit counts are **biased toward national programs** — 自治体 条例 coverage
        is sparse.

    CHAIN:
      → `search_programs(query=item_name)` / `search_tax_incentives(query=item_name)` /
        `search_certifications(query=item_name)` for full detail per hit.
      → `active_programs_at(date=amendment_date)` to see 施行時点の有効制度.
      → `related_programs(program_id=item_id)` to see a specific row's relation graph.

    EXAMPLE:
      Input:  law_name="中小企業等経営強化法"
      Output: {total: 18, limit: 20, offset: 0,
               law_aliases_tried: ["中小企業等経営強化法", "経営強化法"],
               results: [{item_kind: "program", item_id: "...",
                          item_name: "中小企業経営強化税制", match_method: "exact", ...}, ...]}

    0 件の場合は `hint` (再検索の提案) と `retry_with` (関連 tool 候補) を返します。
    """
    limit = _clamp_limit(limit)
    offset = _clamp_offset(offset)
    if not law_name or not law_name.strip():
        return make_error(
            code="missing_required_arg",
            message="law_name is required.",
            hint=(
                "Pass a law name (canonical or colloquial). Example: "
                "law_name='租税特別措置法' or '大店立地法'."
            ),
            field="law_name",
            suggested_tools=["enum_values", "search_programs"],
            limit=limit,
            offset=offset,
        )
    law_name = law_name.strip()
    if amendment_date is not None:
        _, err = _validate_iso_date(amendment_date, field="amendment_date")
        if err is not None:
            return err

    aliases = _law_aliases(law_name)

    conn = connect_autonomath()

    # We look in root_law JSON field + raw_json substring (OR law entities themselves).
    # NOTE (Wave-12 perf): we evaluated a FTS5 trigram pre-filter here but kept
    # LIKE because the FTS index has ~23 rows with truncated raw_json content
    # that LIKE still matches via the full body text. Strict result-set
    # equivalence would be broken. Revisit after FTS rebuild.
    like_conds: list[str] = []
    params: list[Any] = []
    for a in aliases:
        esc = _like_escape(a)
        like_conds.append(
            "(json_extract(e.raw_json,'$.root_law') LIKE ? ESCAPE '\\' "
            "OR e.primary_name LIKE ? ESCAPE '\\' "
            "OR e.raw_json LIKE ? ESCAPE '\\')"
        )
        params.extend([f"%{esc}%", f"%{esc}%", f"%{esc}%"])

    where: list[str] = [
        "e.record_kind IN ('program','tax_measure','certification','law')",
        "(" + " OR ".join(like_conds) + ")",
    ]

    if article:
        esc = _like_escape(article)
        where.append("e.raw_json LIKE ? ESCAPE '\\'")
        params.append(f"%{esc}%")

    if amendment_date:
        where.append(
            "(json_extract(e.raw_json,'$.amendment_date') IS NULL "
            "OR json_extract(e.raw_json,'$.amendment_date') <= ?)"
        )
        params.append(amendment_date)

    where_sql = " AND ".join(where)

    (total,) = conn.execute(
        f"SELECT COUNT(*) FROM am_entities e WHERE {where_sql}", params
    ).fetchone()
    rows = execute_with_retry(
        conn,
        f"SELECT e.* FROM am_entities e WHERE {where_sql} "
        f"ORDER BY e.record_kind, e.confidence DESC, e.primary_name "
        f"LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )

    results: list[dict[str, Any]] = []
    for r in rows:
        raw = _safe_json_loads(r["raw_json"])
        item_kind_map = {
            "program": "program",
            "tax_measure": "tax_incentive",
            "certification": "certification",
            "law": "law",
        }
        results.append(
            {
                "item_kind": item_kind_map[r["record_kind"]],
                "item_id": r["canonical_id"],
                "item_name": r["primary_name"],
                "root_law": raw.get("root_law"),
                "article": raw.get("article") or raw.get("law_article"),
                "law_no": raw.get("law_no") or raw.get("law_number"),
                "amendment_date": raw.get("amendment_date"),
                "match_method": "alias" if law_name not in (raw.get("root_law") or "") else "exact",
                "source_url": r["source_url"],
                "fetched_at": r["fetched_at"],
                "confidence": r["confidence"],
            }
        )

    payload: dict[str, Any] = {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "results": results,
        "law_aliases_tried": aliases,
    }
    if total == 0:
        err = make_error(
            code="no_matching_records",
            message="no entities reference this law.",
            hint=(
                "Try the canonical name via search_programs(q=...) or check "
                "enum_values(enum_name='authority'). The law_aliases_tried "
                "array above shows what names we searched."
            ),
            retry_with=[
                "search_programs",
                "search_tax_incentives",
                "search_certifications",
            ],
            suggested_tools=["enum_values", "search_programs"],
            limit=limit,
            offset=offset,
            extra={"law_aliases_tried": aliases},
        )
        payload["hint"] = err["error"]["hint"]
        payload["retry_with"] = err["error"]["retry_with"]
        payload["error"] = err["error"]
    if article and not any("article" in r for r in results):
        existing = payload.get("hint", "") or ""
        payload["hint"] = (
            existing + " (article filter: most rows lack 条項 metadata; try without article)"
        ).strip()
    return payload


# ---------------------------------------------------------------------------
# 6. active_programs_at
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
@_safe_tool
def active_programs_at(
    date: Annotated[
        str,
        Field(description="ISO date (YYYY-MM-DD). Effective-window pivot."),
    ],
    region: Annotated[
        _REGION_VALUES | str | None,
        Field(
            description="Geographic scope. Closed-set: '北海道'/'東北'/'関東'/'中部'/'近畿'/'中国'/'四国'/'九州'/'沖縄'/'national', or 47 都道府県名 (e.g. '東京都'). NULL = all regions."
        ),
    ] = None,
    industry: Annotated[
        str | None,
        Field(
            description="Sector keyword (LIKE substring on target_industries). e.g. '製造業' / '建設業' / '農業' / 'IT'. Use enum_values_am('industry') for JSIC 大分類 list."
        ),
    ] = None,
    size: Annotated[
        _SIZE_VALUES | None,
        Field(
            description="Applicant size class (closed-set, 中小企業基本法準拠). 'sole' = 個人事業主, 'small' = 小規模事業者 (製造20人/商業5人 以下), 'sme' = 中小企業, 'mid' = 中堅, 'large' = 大企業. None = 全 size 横断 (filter なし)."
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Max rows. Clamped to [1, 100]. Default 20.", ge=1, le=100),
    ] = 20,
) -> dict[str, Any]:
    """[TIMELINE] 任意の ISO 日付 pivot で **effective window (施行〜廃止) が及ぶ** 制度 + 税制を列挙する — `list_open_programs` が 募集窓口 を、本 tool は 制度の **存在期間** を見る (歴史的 "XX年時点で有効だった制度" の効力期間 lookup 用途).
    Return programs and tax_measures whose effectivity window (not application window) spans a given ISO date, with on_date_status hints (active / about_to_close / just_started).

    WHAT: `am_entities` where record_kind IN ('program', 'tax_measure'),
    filtered by effective_from / effective_to (falls back to application_period_*).
    Required: at least one temporal field is non-null on the row (otherwise
    EXCLUDED; avoids false-positive sweep). Adds `on_date_status` per row:
    `active` / `about_to_close` (≤30 days to close) / `just_started` (≤30 days
    from open).

    WHEN:
      - "2020-04-01 時点で有効だった 雇用調整助成金 特例措置は?"
      - "2023-10-01 のインボイス開始時点で申請可能だった税制は?"
      - "コロナ特例 (2020-2023) の 制度スナップショットを比較したい"
      - "今日時点で有効な 省エネ税制 を全部出して"

    WHEN NOT:
      - `list_open_programs` instead when the user asks 「今 / 募集中 / 締切が
        近い」(application window, not effectivity — 募集窓口のみ).
      - `search_programs` instead for the full catalog regardless of date.
      - `search_by_law(amendment_date=...)` instead when the pivot is a **law
        amendment date** and the user wants programs amended *after* it.

    RETURN: {total, limit, offset, results[], pivot_date, hint?, retry_with?}.
    Each row: `item_kind` (program / tax_incentive), `item_id`, `item_name`,
    `effective_from`, `effective_to`, `on_date_status`, `region`,
    `target_industries`, `authority_level`, source lineage.

    LIMITATIONS:
      - **Effectivity coverage is partial**. We fall back to `application_period_*`
        when `effective_*` is missing — the two concepts **can differ** for 恒久
        制度 that were amended but not re-scoped. Cross-check via `search_by_law`
        for amendment detail.
      - Certifications and loan programs are OUT OF SCOPE (record_kind filter).
      - `on_date_status=about_to_close` threshold is ±30 days; adjust downstream if
        the user needs a different horizon.
      - 法律改正による 経過措置 (grandfathering) は JSON schema で表現していない —
        rows that **officially expired** but still applicable to pre-expiry
        applicants may not show here.

    CHAIN:
      ← `search_by_law` produces `amendment_date` → pivot this tool.
      → `get_program(unified_id=row.item_id)` / `search_tax_incentives(query=...)`
        for full detail.
      → `search_enforcement_cases(disclosed_from=date)` to cross-check what went
        wrong during that window.

    EXAMPLE:
      Input:  date="2020-04-01", region="national", size="sme"
      Output: {total: 42, limit: 20, offset: 0, pivot_date: "2020-04-01",
               results: [{item_kind: "program", item_name: "雇用調整助成金 特例",
                          effective_from: "2020-02-14", effective_to: "2023-03-31",
                          on_date_status: "active", ...}, ...]}
    """
    limit = _clamp_limit(limit)
    offset = 0
    if not date or not date.strip():
        return make_error(
            code="missing_required_arg",
            message="date (ISO YYYY-MM-DD) is required.",
            hint="Pass ISO 8601 date, e.g. date='2020-04-01'.",
            field="date",
            limit=limit,
            offset=offset,
        )
    pivot, err = _validate_iso_date(date, field="date")
    if err is not None:
        return err
    assert pivot is not None  # date non-empty, validate succeeded

    conn = connect_autonomath()

    where: list[str] = [
        "e.record_kind IN ('program','tax_measure')",
        # Require at least ONE temporal signal so we don't false-positive
        # everything (many rows have no period fields).
        "(json_extract(e.raw_json,'$.effective_from') IS NOT NULL "
        " OR json_extract(e.raw_json,'$.effective_window_from') IS NOT NULL "
        " OR json_extract(e.raw_json,'$.application_period_from') IS NOT NULL "
        " OR json_extract(e.raw_json,'$.application_open') IS NOT NULL "
        " OR json_extract(e.raw_json,'$.effective_to') IS NOT NULL "
        " OR json_extract(e.raw_json,'$.application_period_to') IS NOT NULL "
        " OR json_extract(e.raw_json,'$.application_close') IS NOT NULL)",
        # effective_from <= pivot (fall back to application_period_from)
        "(COALESCE("
        " json_extract(e.raw_json,'$.effective_from'),"
        " json_extract(e.raw_json,'$.effective_window_from'),"
        " json_extract(e.raw_json,'$.application_period_from'),"
        " json_extract(e.raw_json,'$.application_open'),"
        " '0000-01-01') <= ?)",
        "(COALESCE("
        " json_extract(e.raw_json,'$.effective_to'),"
        " json_extract(e.raw_json,'$.effective_window_to'),"
        " json_extract(e.raw_json,'$.application_period_to'),"
        " json_extract(e.raw_json,'$.application_close'),"
        " '9999-12-31') >= ?)",
    ]
    params: list[Any] = [pivot, pivot]

    prefectures = _expand_region(region)
    if prefectures is not None:
        if len(prefectures) == 0:
            where.append(
                "(json_extract(e.raw_json,'$.authority_level') IS NULL "
                "OR json_extract(e.raw_json,'$.authority_level') NOT IN "
                "('prefecture','municipality'))"
            )
        else:
            placeholders = ",".join("?" for _ in prefectures)
            where.append(f"json_extract(e.raw_json,'$.prefecture') IN ({placeholders})")
            params.extend(prefectures)

    if industry:
        esc = _like_escape(industry)
        where.append("e.raw_json LIKE ? ESCAPE '\\'")
        params.append(f"%{esc}%")

    if size:
        esc = _like_escape(size)
        where.append("e.raw_json LIKE ? ESCAPE '\\'")
        params.append(f"%{esc}%")

    where_sql = " AND ".join(where)

    (total,) = conn.execute(
        f"SELECT COUNT(*) FROM am_entities e WHERE {where_sql}", params
    ).fetchone()
    rows = execute_with_retry(
        conn,
        f"SELECT e.* FROM am_entities e WHERE {where_sql} "
        f"ORDER BY e.record_kind, e.primary_name "
        f"LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )

    pivot_date = _parse_iso_date(pivot)
    results: list[dict[str, Any]] = []
    for r in rows:
        raw = _safe_json_loads(r["raw_json"])
        eff_from = (
            raw.get("effective_from")
            or raw.get("effective_window_from")
            or raw.get("application_period_from")
            or raw.get("application_open")
        )
        eff_to = (
            raw.get("effective_to")
            or raw.get("effective_window_to")
            or raw.get("application_period_to")
            or raw.get("application_close")
        )
        status = "active"
        close_d = _parse_iso_date(eff_to)
        from_d = _parse_iso_date(eff_from)
        if pivot_date:
            if close_d and (close_d - pivot_date).days <= 30:
                status = "about_to_close"
            elif from_d and (pivot_date - from_d).days <= 30:
                status = "just_started"
        results.append(
            {
                "item_kind": ("tax_incentive" if r["record_kind"] == "tax_measure" else "program"),
                "item_id": r["canonical_id"],
                "item_name": r["primary_name"],
                "effective_from": eff_from,
                "effective_to": eff_to,
                "on_date_status": status,
                "region": raw.get("prefecture") or raw.get("region"),
                "target_industries": raw.get("target_industries") or raw.get("target_types"),
                "authority_level": raw.get("authority_level"),
                "source_url": r["source_url"],
                "fetched_at": r["fetched_at"],
                "confidence": r["confidence"],
            }
        )

    payload: dict[str, Any] = {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "results": results,
        "pivot_date": pivot,
    }
    if total == 0:
        err = make_error(
            code="no_matching_records",
            message="no rows had an effectivity window covering this date.",
            hint=(
                "Coverage is partial; some rows fall back to application_* "
                "window. Try list_open_programs for the application window, or "
                "search_programs without date filter."
            ),
            retry_with=["list_open_programs", "search_programs"],
            suggested_tools=["enum_values"],
            limit=limit,
            offset=offset,
        )
        payload["hint"] = err["error"]["hint"]
        payload["retry_with"] = err["error"]["retry_with"]
        payload["error"] = err["error"]
    return payload


# ---------------------------------------------------------------------------
# 7. related_programs
# ---------------------------------------------------------------------------


_RelationType = Literal[
    "prerequisite",
    "compatible",
    "incompatible",
    "successor",
    "predecessor",
    "similar",
]

# Map our external vocab to the graph's internal relation_type names.
_RELATION_GRAPH_MAP: dict[str, list[str]] = {
    "prerequisite": ["prerequisite"],
    "compatible": ["compatible"],
    "incompatible": ["incompatible"],
    "successor": ["replaces"],  # A replaces B -> B's successor is A (reverse lookup)
    "predecessor": ["replaces"],  # symmetric walk on reverse
    "similar": ["related"],
}


def _resolve_seed_in_graph(seed_id: str) -> str | None:
    """Resolve a user-supplied seed id to an ``am_entities.canonical_id``.

    Rewritten 2026-04-29: previously queried ``am_node`` from
    ``graph.sqlite`` which no longer exists. Now reads ``am_entities``
    in autonomath.db directly (same store ``graph_traverse_tool.py``
    uses successfully).

    Resolution order:
      1. exact ``canonical_id`` hit
      2. exact ``primary_name`` hit (caller passed a display name)
      3. alias hit via ``am_alias.alias_text``
      4. loose ``primary_name LIKE %seed%`` (last-resort, ranked by
         confidence DESC so the highest-tier match wins)

    Returns ``None`` when no candidate exists. The caller surfaces a
    ``seed_not_found`` envelope with retry hints.
    """
    aconn = connect_autonomath()
    # 1. direct canonical_id
    row = aconn.execute(
        "SELECT canonical_id FROM am_entities WHERE canonical_id = ?", [seed_id]
    ).fetchone()
    if row:
        return row["canonical_id"]
    # 2. exact primary_name
    row = aconn.execute(
        "SELECT canonical_id FROM am_entities WHERE primary_name = ? "
        "ORDER BY confidence DESC LIMIT 1",
        [seed_id],
    ).fetchone()
    if row:
        return row["canonical_id"]
    # 3. alias hit (am_alias may not exist on minimal builds — guard).
    try:
        row = aconn.execute(
            "SELECT canonical_id FROM am_alias WHERE alias_text = ? LIMIT 1",
            [seed_id],
        ).fetchone()
        if row:
            return row["canonical_id"]
    except sqlite3.OperationalError:
        pass
    # 4. loose primary_name LIKE
    esc = _like_escape(seed_id)
    row = aconn.execute(
        "SELECT canonical_id FROM am_entities WHERE primary_name LIKE ? ESCAPE '\\' "
        "ORDER BY confidence DESC LIMIT 1",
        [f"%{esc}%"],
    ).fetchone()
    if row:
        return row["canonical_id"]
    return None


@_safe_tool
def related_programs(
    program_id: Annotated[
        str,
        Field(
            description="Seed node id (canonical_id from any search_* tool — e.g. 'UNI-xxxxxxxxxx' for programs, 'TAX-xxx', 'CERT-xxx', 'LAW-xxx'). Falls back to display-name LIKE match when exact lookup misses."
        ),
    ],
    relation_types: Annotated[
        list[_RelationType] | None,
        Field(
            description="Relation axes to walk (OR). Closed-set values: 'prerequisite', 'compatible', 'incompatible', 'successor' (replaces, reverse), 'predecessor' (replaces, forward), 'similar' (related). NULL = all 6 axes."
        ),
    ] = None,
    depth: Annotated[
        int,
        Field(
            description="Graph traversal depth (1 or 2).",
            ge=1,
            le=2,
        ),
    ] = 1,
    max_edges: Annotated[
        int,
        Field(
            description=(
                "Hard safety cap on total edges returned. Prevents graph "
                "explosion on dense hub nodes (has_authority hub has 4541 "
                "edges out). Default 100, hard cap 500."
            ),
            ge=1,
            le=500,
        ),
    ] = 100,
) -> dict[str, Any]:
    """[DISCOVER-GRAPH] Returns related programs along 6 relation axes (prerequisite / compatible / incompatible / successor / predecessor / similar), 1-2 hops from a seed program / tax / cert. Walks am_relation (18,489 edges / ~13K nodes). Output is search-derived; verify primary source for compatibility decisions.
    Graph walk over am_relation (18,489 edges) seeded on one program/tax/cert, returning up to 6 relation axes and 2-hop neighbors.

    WHAT: `graph.sqlite::am_relation` — 18,489 directed edges across ~13K nodes.
    External vocab → internal relation_type:
      prerequisite → prerequisite
      compatible → compatible
      incompatible → incompatible
      successor → replaces (reverse edge walk)
      predecessor → replaces (forward edge walk)
      similar → related
    Seed resolution: accepts `canonical_id` from any `search_*`, or display name;
    falls back to LIKE match on am_node.display_name when exact fails.

    WHEN:
      - "事業再構築補助金の前提になる認定は?"
      - "IT 導入補助金と併用可能な補助金は?"
      - "持続化補助金が 2026 年度で何に変わった?" (successor 取得)
      - "この税制と似た制度 (other ministries) は?"

    WHEN NOT:
      - `search_by_law` instead when the user names a **law** (not a program).
      - `check_exclusions(program_ids=[...])` instead when the user already has
        a candidate set and asks 「併給可否」 — that runs the 181 rule engine,
        which is more authoritative than `relation_type='incompatible'`.
      - `search_programs` instead when the user has only a keyword, not a seed id.

    RETURN: {seed_id, seed_kind, seed_name?, relations: {relation_type: [{from_id,
    to_id, relation_type, confidence, evidence}, ...]}, nodes: [...], total_edges,
    depth, hint?, retry_with?, error?}.
    NOTE: envelope shape **differs** from search_*; this is a graph result.

    LIMITATIONS:
      - **Hub explosion**: `has_authority` hub 単体で 4,541 edges out — `max_edges`
        (default 100, hard cap 500) で強制切り詰め、`edge_cap_hit=True` で通知。
        密な node を seed に置くと打ち切られる前提で扱うこと。
      - `depth` is capped at 2. Deeper graph exploration should be done in
        multiple calls with the next frontier as a seed.
      - `incompatible` edges are **provisional** — authoritative 併給可否 判定は
        必ず `check_exclusions` (jpintel) に回せ。This tool's edges are derived
        from 要綱 extraction and may miss 相互排他 rules.
      - Seed resolution by display name is LIKE — wrong LIKE hits return edges
        for an unintended node. Prefer canonical_id.

    CHAIN:
      ← `search_programs` / `search_tax_incentives` / `search_certifications`
        produces the `canonical_id` → pass to `program_id`.
      → `get_program(unified_id=edge.to_id)` for the neighbor's detail.
      → `check_exclusions(program_ids=[seed, *compatible_ids])` to validate
        併給 可否 against the authoritative 181 rule set.
      DO NOT → call `related_programs` recursively with each neighbor — walk
        in single hop, process with `check_exclusions`, then decide.

    EXAMPLE:
      Input:  program_id="it-dounyu-2026",
              relation_types=["prerequisite", "compatible"]
      Output: {seed_id: "it-dounyu-2026", seed_kind: "program",
               seed_name: "IT 導入補助金",
               relations: {prerequisite: [...], compatible: [...]},
               nodes: [...], total_edges: 12, depth: 1}
    """
    if not program_id or not program_id.strip():
        err = make_error(
            code="missing_required_arg",
            message="program_id is required.",
            hint=(
                "Pass a canonical_id from search_programs / search_tax_incentives "
                "/ search_certifications results."
            ),
            field="program_id",
            suggested_tools=["search_programs", "search_tax_incentives"],
        )
        # Graph shape stub so tolerant consumers don't crash on missing keys.
        return {
            "seed_id": "",
            "seed_kind": "unknown",
            "relations": {},
            "nodes": [],
            "total_edges": 0,
            "depth": 0,
            "error": err["error"],
        }
    program_id = program_id.strip()
    depth = max(1, min(2, depth))
    max_edges = max(1, min(500, max_edges))
    resolved_relations = relation_types or [
        "prerequisite",
        "compatible",
        "incompatible",
        "successor",
    ]

    node_id = _resolve_seed_in_graph(program_id)

    result: dict[str, Any] = {
        "seed_id": program_id,
        "seed_kind": "unknown",
        "relations": {rt: [] for rt in resolved_relations},
        "nodes": [],
        "total_edges": 0,
        "depth": depth,
    }

    if node_id is None:
        err = make_error(
            code="seed_not_found",
            message=f"seed id '{program_id}' not found in graph.",
            hint=(
                "Call search_programs / search_tax_incentives / search_certifications "
                "first to get a canonical_id, then retry with that id."
            ),
            retry_with=["check_exclusions", "search_programs"],
            suggested_tools=["search_programs", "search_tax_incentives", "search_certifications"],
            field="program_id",
        )
        result["hint"] = err["error"]["hint"]
        result["retry_with"] = err["error"]["retry_with"]
        result["error"] = err["error"]
        return result

    aconn = connect_autonomath()
    seed_row = aconn.execute(
        "SELECT canonical_id, record_kind, primary_name FROM am_entities WHERE canonical_id=?",
        [node_id],
    ).fetchone()
    if seed_row:
        result["seed_id"] = seed_row["canonical_id"]
        result["seed_kind"] = seed_row["record_kind"]
        result["seed_name"] = seed_row["primary_name"]

    # BFS over am_relation in autonomath.db (24,004 edges in v_am_relation_all
    # / 23,805 in am_relation; we walk am_relation directly since the
    # facts-origin rows duplicate via the view UNION). Cycle suppression
    # via seen_edges tuple (s, t, relation_type).
    neighbor_ids: set[str] = set()
    total_edges = 0
    seen_edges: set[tuple[str, str, str]] = set()

    frontier = {node_id}
    edge_cap_hit = False
    for _hop in range(depth):
        next_frontier: set[str] = set()
        if not frontier or edge_cap_hit:
            break
        for rt in resolved_relations:
            if edge_cap_hit:
                break
            graph_rts = _RELATION_GRAPH_MAP.get(rt, [rt])
            for grt in graph_rts:
                if edge_cap_hit:
                    break
                # Direction:
                #   - successor: A replaces B  =>  successor of B is A.
                #     We want neighbors of seed=B, so look up edges where
                #     target_entity_id IN frontier (and source becomes
                #     the new neighbor).
                #   - predecessor: A replaces B  =>  predecessor of A is B.
                #     Forward walk: source IN frontier, target is neighbor.
                #   - all other types: forward walk source -> target.
                placeholders = ",".join("?" for _ in frontier)
                if rt == "successor":
                    sql = (
                        f"SELECT source_entity_id AS s, target_entity_id AS t, "
                        f"relation_type, confidence, evidence_fact_ids "
                        f"FROM am_relation "
                        f"WHERE relation_type=? "
                        f"AND target_entity_id IN ({placeholders}) "
                        f"AND target_entity_id IS NOT NULL"
                    )
                else:
                    sql = (
                        f"SELECT source_entity_id AS s, target_entity_id AS t, "
                        f"relation_type, confidence, evidence_fact_ids "
                        f"FROM am_relation "
                        f"WHERE relation_type=? "
                        f"AND source_entity_id IN ({placeholders}) "
                        f"AND target_entity_id IS NOT NULL"
                    )
                rows = aconn.execute(sql, [grt, *frontier]).fetchall()
                for row in rows:
                    key = (row["s"], row["t"], row["relation_type"])
                    if key in seen_edges:
                        continue
                    seen_edges.add(key)
                    if rt == "successor":
                        # Flip orientation so the response always points
                        # away from the seed (from_id = seed-side).
                        from_id, to_id = row["t"], row["s"]
                    else:
                        from_id, to_id = row["s"], row["t"]
                    result["relations"].setdefault(rt, []).append(
                        {
                            "from_id": from_id,
                            "to_id": to_id,
                            "relation_type": rt,
                            "confidence": row["confidence"],
                            "evidence": row["evidence_fact_ids"],
                        }
                    )
                    neighbor_ids.add(to_id)
                    next_frontier.add(to_id)
                    total_edges += 1
                    if total_edges >= max_edges:
                        edge_cap_hit = True
                        break
        frontier = next_frontier
    result["edge_cap_hit"] = edge_cap_hit
    result["max_edges"] = max_edges

    # Attach node metadata for the neighbor frontier.
    if neighbor_ids:
        placeholders = ",".join("?" for _ in neighbor_ids)
        node_rows = aconn.execute(
            f"SELECT canonical_id, record_kind, primary_name FROM am_entities "
            f"WHERE canonical_id IN ({placeholders})",
            list(neighbor_ids),
        ).fetchall()
        result["nodes"] = [
            {
                "id": r["canonical_id"],
                "kind": r["record_kind"],
                "primary_name": r["primary_name"],
            }
            for r in node_rows
        ]

    result["total_edges"] = total_edges
    if total_edges == 0:
        err = make_error(
            code="no_matching_records",
            message=f"no edges across relation_types={resolved_relations} for this seed.",
            hint=(
                f"Seed '{result.get('seed_name', program_id)}' exists but has no "
                "out-edges for the requested relation_types. Try depth=2, broaden "
                "relation_types, or call check_exclusions directly."
            ),
            retry_with=["check_exclusions", "search_programs"],
            suggested_tools=["search_programs"],
        )
        result["hint"] = err["error"]["hint"]
        result["retry_with"] = err["error"]["retry_with"]
        result["error"] = err["error"]
    return result


# ---------------------------------------------------------------------------
# 8. search_acceptance_stats
# ---------------------------------------------------------------------------


def _row_to_stat(row: sqlite3.Row) -> dict[str, Any]:
    raw = _safe_json_loads(row["raw_json"])
    accepted = raw.get("accepted")
    applicants = raw.get("applicants")
    rate = raw.get("acceptance_rate")
    if rate is None and accepted is not None and applicants:
        try:
            rate = round(float(accepted) / float(applicants), 4)
        except (TypeError, ValueError, ZeroDivisionError):
            rate = None
    granted_amount = raw.get("granted_amount_total_yen")
    granted_count = raw.get("granted_count") or accepted
    avg_grant = None
    if granted_amount and granted_count:
        try:
            avg_grant = int(float(granted_amount) / float(granted_count))
        except (TypeError, ValueError, ZeroDivisionError):
            avg_grant = None
    return {
        "program_name": raw.get("program_name") or row["primary_name"],
        "program_canonical_id": row["canonical_id"],
        "round_label": raw.get("round_label"),
        "round_number": raw.get("round_number"),
        "sub_type": raw.get("sub_type"),
        "fiscal_year": raw.get("fiscal_year"),
        "announced_date": raw.get("announced_date"),
        "applicants": applicants,
        "accepted": accepted,
        "acceptance_rate": rate,
        "granted_count": granted_count,
        "granted_amount_total_yen": granted_amount,
        "budget_total_yen": raw.get("budget_total_yen"),
        "avg_grant_yen": avg_grant,
        "source_url": row["source_url"],
        "source_excerpt": raw.get("source_excerpt"),
        "fetched_at": row["fetched_at"],
        "confidence": row["confidence"],
        "source_topic": row["source_topic"],
    }


@mcp.tool(annotations=_READ_ONLY)
@_safe_tool
def search_acceptance_stats_am(
    program_name: Annotated[
        str | None,
        Field(
            description=(
                "Program 名称の部分一致 (LIKE %name%). 制度名 / 公募名 / 通称 のいずれもヒット. "
                "例: '事業再構築', 'ものづくり', 'IT導入'. "
                "未指定なら全 program を横断."
            ),
        ),
    ] = None,
    year: Annotated[
        int | None,
        Field(
            description=(
                "Fiscal year filter (西暦, 4-digit, e.g. 2024). Filters on "
                "`fiscal_year` column. Range 2010-2099. Pass None to span "
                "all years (default)."
            ),
            ge=2010,
            le=2099,
        ),
    ] = None,
    region: Annotated[
        _REGION_VALUES | str | None,
        Field(
            description=(
                "Geographic scope filter (closed-set: '全国' / 47都道府県 + "
                "8 region 略称). Matches `region` column on the row. Pass "
                "None to skip filter. Use '全国' to keep only nationwide rows."
            )
        ),
    ] = None,
    industry: Annotated[
        str | None,
        Field(
            description=(
                "Sector keyword (LIKE match against `industry` column). "
                "Free-text; common values: '製造業', '農業', 'IT', "
                "'建設業'. Pass None to span all industries."
            )
        ),
    ] = None,
    as_of: Annotated[
        str,
        Field(
            description=(
                "Snapshot date (ISO YYYY-MM-DD or 'today'). Default "
                "'today' (JST). Acceptance stats are historical / "
                "immutable, so as_of is informational only — echoed in "
                "meta.data_as_of for cache-key parity with sibling "
                "search_* tools."
            ),
            pattern=r"^(?:\d{4}-\d{2}-\d{2}|today)$",
        ),
    ] = "today",
    limit: Annotated[
        int,
        Field(description="Max rows. Clamped to [1, 100]. Default 20.", ge=1, le=100),
    ] = 20,
    offset: Annotated[
        int,
        Field(
            description="Pagination offset (0-based row count to skip). Default 0. Combine with `limit` for paging through `total`.",
            ge=0,
        ),
    ] = 0,
) -> dict[str, Any]:
    """[EVIDENCE] Returns adoption statistics (応募件数 / 採択件数 / 採択率 / 予算額) per (program × fiscal_year × round). Aggregated from METI / MAFF published sources. Output is search-derived; verify primary source for figures cited in business decisions.
    Search adoption statistics (applications / acceptances / acceptance rate / budget) per program × fiscal_year × round.

    WHAT: `am_entities` rows where `source_topic IN
    ('01_meti_acceptance_stats', '02_maff_acceptance_stats',
    '05_adoption_additional')`. Grain: (program × 第N次 × 年度). Key fields on
    row: `program_name`, `fiscal_year`, `round_number`, `application_count`,
    `acceptance_count`, `acceptance_rate`, `budget_yen`, `announced_date`.

    WHEN:
      - "ものづくり補助金の第 14 次の採択率は?"
      - "事業再構築補助金 2024 年度の採択件数推移"
      - "IT 導入補助金 過去 3 年の倍率変化"
      - "農水省系補助金で採択率が一番高いのは?"

    WHEN NOT:
      - `search_case_studies` (jpintel) instead when the user wants **具体 採択
        企業** (recipient profiles) — this tool returns aggregate counts, not
        individual recipient names.
      - `search_programs` instead for 制度定義 (eligibility / amount / window).
      - `search_enforcement_cases` (jpintel) instead for 不正受給 / 返還 history
        — opposite signal to adoption.

    RETURN: {total, limit, offset, results[], hint?, retry_with?}.
    Each result row has the key fields above plus source_url + fetched_at for
    lineage.

    LIMITATIONS:
      - Coverage is **skewed toward METI / MAFF** publishable 採択発表 — 自治体
        単独事業や 新しい公募 (未発表) は空である。Missing rounds do NOT mean
        the program was unpopular.
      - `acceptance_rate` is computed `acceptance_count / application_count` when
        both are present; for rows with only 採択件数 公表 (分母が非公開) it is NULL.
      - `program_name` matching is LIKE substring on `primary_name` +
        `raw_json.program_name` + `canonical_id`. Name drift year-over-year
        (「ものづくり・商業・サービス生産性向上促進補助金」 ≠ 「ものづくり補助金」)
        — consider passing the shorter form.
      - `year` filter matches both `fiscal_year` and first 4 chars of
        `announced_date` — 発表 遅延があると year 1 ずれる。ピンポイントは避ける。

    CHAIN:
      ← `search_programs` produces the canonical program name → this call.
      → `search_case_studies(program_used=program_name)` (jpintel) for actual
        recipient examples to pair with stats.
      → `list_open_programs(on_date=today)` to see whether the program is still
        active for future applications.

    EXAMPLE:
      Input:  program_name="ものづくり補助金", year=2024
      Output: {total: 3, limit: 20, offset: 0,
               results: [{program_name: "ものづくり補助金", fiscal_year: 2024,
                          round_number: 17, application_count: 6589,
                          acceptance_count: 3970, acceptance_rate: 0.602, ...}],
               meta: {data_as_of: "2026-04-25"}}

    `as_of` is informational here (acceptance stats are historical /
    immutable) — pass for parity with sibling search_* tools.

    0 件の場合は `hint` (再検索の提案) と `retry_with` (関連 tool 候補) を返します。
    """
    as_of_iso, as_of_err = _resolve_as_of(as_of, field="as_of")
    if as_of_err is not None:
        return as_of_err

    limit = _clamp_limit(limit)
    offset = _clamp_offset(offset)

    conn = connect_autonomath()

    where: list[str] = [
        "e.record_kind IN ('adoption','statistic')",
        "e.source_topic IN ('01_meti_acceptance_stats','02_maff_acceptance_stats','05_adoption_additional')",
    ]
    params: list[Any] = []

    if program_name:
        esc = _like_escape(program_name.strip())
        where.append(
            "(e.primary_name LIKE ? ESCAPE '\\' "
            "OR json_extract(e.raw_json,'$.program_name') LIKE ? ESCAPE '\\' "
            "OR e.canonical_id = ?)"
        )
        params.extend([f"%{esc}%", f"%{esc}%", program_name.strip()])

    if year is not None:
        where.append(
            "(CAST(json_extract(e.raw_json,'$.fiscal_year') AS INTEGER) = ? "
            " OR substr(json_extract(e.raw_json,'$.announced_date'),1,4) = ?)"
        )
        params.extend([year, str(year)])

    if region:
        esc = _like_escape(region)
        where.append("e.raw_json LIKE ? ESCAPE '\\'")
        params.append(f"%{esc}%")

    if industry:
        esc = _like_escape(industry)
        where.append("e.raw_json LIKE ? ESCAPE '\\'")
        params.append(f"%{esc}%")

    where_sql = " AND ".join(where)

    (total,) = conn.execute(
        f"SELECT COUNT(*) FROM am_entities e WHERE {where_sql}", params
    ).fetchone()
    rows = execute_with_retry(
        conn,
        f"SELECT e.* FROM am_entities e WHERE {where_sql} "
        f"ORDER BY e.primary_name, "
        f" CAST(json_extract(e.raw_json,'$.fiscal_year') AS INTEGER) DESC NULLS LAST, "
        f" CAST(json_extract(e.raw_json,'$.round_number') AS INTEGER) DESC NULLS LAST "
        f"LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )

    results = [_row_to_stat(r) for r in rows]

    payload: dict[str, Any] = {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "results": results,
        "meta": {"data_as_of": as_of_iso},
        "retrieval_note": (
            f"Snapshot of acceptance stats as of {as_of_iso} JST. "
            "Acceptance stats are historical / immutable, so as_of is "
            "informational only (echoed for cache-key parity)."
        ),
    }
    if total == 0:
        # Empty-hit envelope: echo what the caller filtered on +
        # nearest-broader queries so the agent doesn't burn another
        # ¥3/req on a near-miss retry. Coverage is METI/MAFF biased,
        # so dropping `year` or `region` is the most common fix.
        filters_applied = {
            k: v
            for k, v in [
                ("program_name", program_name),
                ("year", year),
                ("region", region),
                ("industry", industry),
            ]
            if v
        }
        suggestions: list[str] = []
        if year is not None:
            suggestions.append(
                "Drop 'year' to see all years for this program — coverage "
                "skews toward 公表済み rounds, recent 公募 may be empty."
            )
        if region:
            suggestions.append("Drop 'region' — many programs only publish 全国 stats.")
        if industry:
            suggestions.append("Drop 'industry' — sector tagging is sparse on the source PDFs.")
        if program_name:
            suggestions.append(
                "search_programs(q=program_name) で正式名称を確認してから "
                "採択実績 を再検索 (年度ごとに表記揺れあり)."
            )
        suggestions.append(
            "enum_values_am(field='program_name_for_stats') で集計対象 "
            "プログラム一覧 (METI/MAFF 公表 ベース)."
        )
        err = make_error(
            code="no_matching_records",
            message="no 採択実績 rows matched.",
            hint=(
                "Check program_name spelling via search_programs(q=...) first, "
                "or relax the year filter."
            ),
            retry_with=["search_programs", "search_case_studies"],
            suggested_tools=["search_programs"],
            retry_args={"year": None},
            limit=limit,
            offset=offset,
        )
        payload["hint"] = {
            "message": (
                "No acceptance stats matched. 集計データが存在する 組合せか確認してください。"
            ),
            "filters_applied": filters_applied,
            "suggestions": suggestions,
        }
        payload["retry_with"] = err["error"]["retry_with"]
        payload["error"] = err["error"]
    return payload


# ---------------------------------------------------------------------------
# 9. intent_of — classify a query into one of the 10 intent clusters.
# 10. reason_answer — full Layer 7 pipeline: classify → slots → bind → skeleton.
#
# These two are the public surface of the reasoning layer. Customer LLMs pass
# their natural-language query and get a skeleton with every verifiable value
# (URL, date, amount, program list) pre-filled. They fill in the narrative,
# keeping hallucination on verifiable facts near zero.
# ---------------------------------------------------------------------------


_PERSONAS = Literal[
    "sme_owner",  # P1: 小規模製造業 owner ("is there money for me?")
    "tax_advisor",  # P2: 税務相談士
    "agri_corp",  # P3: 農業法人 (Konosu-style)
    "consultant",  # P4: コンサルタント mapping 制度 for a client
    "ma_advisor",  # P5: M&A 相談士
    "municipality",  # P6: 自治体 担当者 (intent08 peer-compare)
    "generic",  # default — no persona-specific reweighting
]


def _reasoning_import():
    """Lazy import of the reasoning package so test harness and CI that
    don't have yaml installed can still load tools.py."""
    # Ensure infra root is on sys.path (same pattern as query_rewrite).
    import sys as _sys
    from pathlib import Path as _Path

    root = str(_Path(__file__).resolve().parent.parent)
    if root not in _sys.path:
        _sys.path.insert(0, root)
    from reasoning import match as _match_mod  # noqa: F401
    from reasoning import query_types as _qt_mod  # noqa: F401

    return _match_mod, _qt_mod


# TODO(2026-04-29): intent_of is currently broken — _reasoning_import()
# fails with ModuleNotFoundError because the `reasoning` package is not
# present in the install (smoke test 2026-04-29 returns
# `subsystem_unavailable` on every invocation). Gated behind
# AUTONOMATH_REASONING_ENABLED (default False) so the broken tool stays
# out of `tools/list`. Same gate also covers `reason_answer` below
# (shared `_reasoning_import()` failure mode). To re-enable: bundle the
# `reasoning` package into the install (or place it on a sys.path the
# package can resolve from `Path(__file__).resolve().parent.parent`).
@_safe_tool
def intent_of(
    query: Annotated[
        str,
        Field(
            description=(
                "自然言語の顧客クエリ (JP)。例: "
                "'事業承継税制の特例措置はいつまで?', "
                "'熊本県 製造業 従業員30人で使える補助金は?'."
            ),
        ),
    ],
) -> dict[str, Any]:
    """[INTENT-CLASSIFY] Returns classification of a JP natural-language query into one of 10 intent clusters (i01_filter / i02_deadline / i03_successor / i04_tax_sunset / i05_cert_howto / i06_compat / i07_adoption / i08_peer_compare / i09_succession / i10_wage_dx_gx) using a keyword scorer, with confidence + all_scores. Pre-step for `reason_answer`.
    Deterministic keyword-scorer classification of a JP natural-language query into 1 of 10 canonical intent clusters.

    WHAT: `reasoning.match.classify_intent()` の public surface.
    keyword scorer (length-weighted softmax) で 10 intent に振り分け、all_scores
    に ranked score 全件を audit trail として添付. API は呼ばない (完全 offline).

    WHEN:
      - 顧客 LLM が `reason_answer` を呼ぶ前に 「この質問は どの tree で答えるべきか」
        を先に確認したい時
      - confidence が低い (< 0.5) と予想される 拮抗 query の branching 判断
      - intent mismatch デバッグ (期待した intent が top-1 でない理由の解析)
      - end-user の質問を log して intent 分布を可視化したい時

    WHEN NOT:
      - `reason_answer` instead when you actually want the answer skeleton — this
        tool only classifies; it doesn't query the DB or bind facts.
      - Skip entirely if you're going straight to a specific `search_*` tool
        (intent_of は fallback 用に常駐、必須ではない).

    RETURN: {intent_id, intent_name_ja, confidence, all_scores: [{intent_id, score}], sample_queries: [...], error?}.
    NOTE: envelope shape **differs** from search_*; this is a classifier result.

    LIMITATIONS:
      - Classifier is **keyword-based** — morphology / long-distance context は見ない。
        「〜**ではない**」のような否定語は score に直接影響しない (i08 ではない、のような
        否定 intent は存在しない).
      - confidence < 0.5 は実運用で頻発する (top-1 と top-2 の score 差が薄い)。
        その場合は branching (2 intent を両方試す) か `reason_answer` に回す。
      - 10 intent に収まらないクエリは i01 fallback に寄る傾向がある。`all_scores`
        を見て決断。
      - subsystem (reasoning package) が import 失敗すると `error` 入りで返る;
        fall back to `search_*` と retry_with で指示。

    CHAIN:
      → `reason_answer(query=same_query)` when confidence >= 0.5, to get the
        bound skeleton.
      → direct `search_*` (search_programs / search_tax_incentives /
        search_certifications 等) when intent is clearly known from the classifier.
      DO NOT → re-call `intent_of` on the same string; it's deterministic.

    EXAMPLE:
      Input:  query="事業承継税制 M&A 買い手で 1 億円"
      Output: {intent_id: "i09_succession_closure",
               intent_name_ja: "事業承継・廃業",
               confidence: 0.72,
               all_scores: [{intent_id: "i09_...", score: 0.72},
                            {intent_id: "i04_tax_measure_sunset", score: 0.18}, ...],
               sample_queries: ["...", "..."]}
    """
    if not query or not query.strip():
        err = make_error(
            code="missing_required_arg",
            message="query is required.",
            hint="Pass a non-empty natural-language query string.",
            field="query",
        )
        return {
            "intent_id": None,
            "intent_name_ja": None,
            "confidence": 0.0,
            "all_scores": [],
            "sample_queries": [],
            "error": err["error"],
        }
    try:
        _match_mod, _qt_mod = _reasoning_import()
    except Exception as e:
        err = make_error(
            code="subsystem_unavailable",
            message=f"reasoning package import failed: {type(e).__name__}",
            hint=(
                "Optional reasoning subsystem offline. Fall back to "
                "search_programs / search_tax_incentives / search_certifications."
            ),
            retry_with=["search_programs", "search_tax_incentives", "search_certifications"],
        )
        return {
            "intent_id": None,
            "intent_name_ja": None,
            "confidence": 0.0,
            "all_scores": [],
            "sample_queries": [],
            "error": err["error"],
        }

    intent_id, confidence, ranked = _match_mod.classify_intent(query.strip())
    try:
        intent = _qt_mod.get_intent(intent_id)
        name_ja = intent.name_ja
        samples = list(intent.sample_queries)
    except Exception:
        name_ja = None
        samples = []

    return {
        "intent_id": intent_id,
        "intent_name_ja": name_ja,
        "confidence": confidence,
        "all_scores": [{"intent_id": iid, "score": s} for iid, s in ranked],
        "sample_queries": samples,
    }


# TODO(2026-04-29): reason_answer is currently broken — same root cause
# as `intent_of` above (`_reasoning_import()` ModuleNotFoundError). Gated
# behind AUTONOMATH_REASONING_ENABLED (default False) so the broken tool
# stays out of `tools/list`. Re-enabled together with intent_of once the
# `reasoning` package lands.
@_safe_tool
def reason_answer(
    query: Annotated[
        str,
        Field(
            description=(
                "自然言語の顧客クエリ (JP)。intent_of で事前分類した結果と"
                "矛盾しないよう同じ文字列を使うこと。"
            ),
        ),
    ],
    persona: Annotated[
        _PERSONAS | None,
        Field(
            description=(
                "顧客種別ヒント。現状は audit / telemetry 用途 (intent "
                "boost は行わない — 分類は keyword scorer が決定論的に担当)。"
                "Future: persona 別の skeleton variant のため保持。"
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """[REASON-ANSWER] Runs intent classification + slot extraction + DB bind + skeleton render in one call. Returns an answer_skeleton with verifiable values (URL / 日付 / 金額 / 制度名 / 先行制度) bound from DB, plus a missing_data list of slots that could not be filled. Customer LLM polishes the skeleton text; missing_data tokens must not be fabricated.
    One-shot pipeline: classify_intent → extract_slots → load_tree → bind_precomputed + bind_iXX (live DB) → render_skeleton, returning a fact-complete skeleton plus explicit missing_data list.

    WHAT: pipeline = `query → classify_intent → extract_slots → load_tree →
    bind_precomputed + bind_iXX (DB 実接続) → render_skeleton`.
    外部 API は呼ばず、DB (autonomath + graph) のみで bind. 返値の
    `answer_skeleton` には `<<<missing:KEY>>>` トークンが「埋められなかった
    箇所」として **残る** (顧客 LLM がハルシを止める設計)。`missing_data`
    配列に KEY を重複なく列挙。

    WHEN:
      - 顧客 LLM が最小ハルシで制度回答を生成したい時 (core 使途)
      - 1 tool call で intent + slots + bound facts + skeleton を一括入手したい時
      - マルチホップ質問 (「熊本県 × 製造業 × 従業員 30 人」) を bound URL +
        日付 + 金額つきで一度に返したい時
      - 営業 / 提案書生成など、ハルシが直接 詐欺 / 景表法 リスクになる用途

    WHEN NOT:
      - `intent_of` instead when you only need classification (no DB bind, no
        skeleton rendering — cheaper).
      - 直接 `search_programs` / `search_tax_incentives` 等 instead when the
        intent is obvious and you want raw row data, not a rendered skeleton.
      - `search_programs` + `get_program` pair instead for simple 制度名 lookup
        where a skeleton would be overkill.

    RETURN: {intent, intent_name_ja, filters_extracted, answer_skeleton,
    confidence, missing_data[], precompute_gaps[], source_urls[], db_bind_ok,
    db_bind_notes[], persona_hint, retry_with[], error?}.
    NOTE: envelope shape **differs** from search_*; this is a pipeline result.

    LIMITATIONS:
      - **`<<<missing:KEY>>>` トークンを LLM が fabricate してはいけない**。
        missing_data に列挙されている key は「本当にデータが無い」signal であり、
        LLM が勝手に埋めるとハルシ (= 詐欺リスク)。end user には「出典未取得」
        と明示するか、`retry_with` の tool を後段で呼んで詰める。
      - `<<<precompute gap: ...>>>` は別 class の欠損 (precompute pipeline 側の
        bug/データ不足)。`precompute_gaps[]` に列挙、修正は運用側の仕事。
      - confidence < 0.4 のとき intent 分類の信頼が低い → retry_with に `intent_of`
        が入る。判断は顧客 LLM 側。
      - `persona` は現状 audit/telemetry のみ (intent boost はしない)。future
        extension の placeholder.
      - subsystem (reasoning) が import 失敗すると `error` 入りで返る。fall
        back は retry_with の tool を使う。

    CHAIN:
      ← `intent_of(query=same)` を先に呼んで confidence を見て分岐する運用可。
      → `search_programs` / `search_tax_incentives` / `search_certifications` /
        `list_open_programs` / `get_program` / `check_exclusions` — retry_with
        配列に intent 別の推奨 tool が入る。**missing_data を埋めるには retry_with
        を順に呼ぶ**。
      DO NOT → `reason_answer` を同一 query で再呼び出し (deterministic);
      DO NOT → LLM 側で missing_data を "なかったことにして" skeleton を polish
        しない (= ハルシ = 詐欺リスク)。

    EXAMPLE:
      Input:  query="熊本県 製造業 従業員 30 人で使える補助金は?"
      Output: {intent: "i01_filter_programs_by_profile",
               intent_name_ja: "業種×地域×規模で使える補助金一覧",
               filters_extracted: {"region": "熊本県", "industry": "製造業", "size": "sme"},
               answer_skeleton: "## 国の補助金\\n- ...\\n## 熊本県 独自\\n<<<missing:prefectural_bullets>>>",
               confidence: 0.88,
               missing_data: ["prefectural_bullets"],
               source_urls: ["https://www.chusho.meti.go.jp/...", ...],
               db_bind_ok: true,
               retry_with: ["search_programs", "list_open_programs"]}
    """
    if not query or not query.strip():
        err = make_error(
            code="missing_required_arg",
            message="query is required.",
            hint="Pass a non-empty natural-language query string.",
            field="query",
        )
        return {
            "intent": None,
            "intent_name_ja": None,
            "filters_extracted": {},
            "answer_skeleton": "",
            "confidence": 0.0,
            "missing_data": [],
            "precompute_gaps": [],
            "source_urls": [],
            "db_bind_ok": False,
            "db_bind_notes": [],
            "persona_hint": persona,
            "retry_with": [],
            "error": err["error"],
        }

    try:
        _match_mod, _qt_mod = _reasoning_import()
    except Exception as e:
        err = make_error(
            code="subsystem_unavailable",
            message=f"reasoning package import failed: {type(e).__name__}",
            hint=(
                "Optional reasoning subsystem offline. Fall back to "
                "search_programs / search_tax_incentives / intent_of."
            ),
            retry_with=["search_programs", "search_tax_incentives", "intent_of"],
        )
        return {
            "intent": None,
            "intent_name_ja": None,
            "filters_extracted": {},
            "answer_skeleton": "",
            "confidence": 0.0,
            "missing_data": [],
            "precompute_gaps": [],
            "source_urls": [],
            "db_bind_ok": False,
            "db_bind_notes": [],
            "persona_hint": persona,
            "retry_with": err["error"]["retry_with"],
            "error": err["error"],
        }

    q = query.strip()

    try:
        result = _match_mod.match(q)
    except Exception as e:
        logger.exception("reason_answer: match() raised")
        err = make_error(
            code="internal",
            message=f"reasoning match() failed: {type(e).__name__}",
            hint="Unhandled reasoning error. Retry once; if persistent fall back to search_*.",
            retry_with=["intent_of", "search_programs", "search_tax_incentives"],
        )
        return {
            "intent": None,
            "intent_name_ja": None,
            "filters_extracted": {},
            "answer_skeleton": "",
            "confidence": 0.0,
            "missing_data": [],
            "precompute_gaps": [],
            "source_urls": [],
            "db_bind_ok": False,
            "db_bind_notes": [],
            "persona_hint": persona,
            "retry_with": err["error"]["retry_with"],
            "error": err["error"],
        }

    # Translate match.py slots to a stable user-facing schema
    _slot_alias = {
        "prefecture": "region",
        "jsic_industry": "industry",
        "business_size": "size",
    }
    filters_extracted: dict[str, Any] = {}
    for k, v in (result.slots or {}).items():
        if v is None:
            continue
        filters_extracted[_slot_alias.get(k, k)] = v

    # Extract <<<missing:KEY>>> tokens — these are the placeholders the
    # binder could not fill. Customer LLMs MUST NOT fabricate values here.
    import re as _re

    raw_skeleton = result.answer_skeleton or ""
    missing_data = sorted(set(_re.findall(r"<<<missing:([a-z_0-9]+)>>>", raw_skeleton)))
    # Also include <<<precompute gap: ...>>> markers as a distinct class.
    precompute_gaps = sorted(set(_re.findall(r"<<<precompute gap: ([^>]+)>>>", raw_skeleton)))
    # P7 fix 2026-04-25: substitute raw tokens in the prose-facing skeleton so
    # downstream LLMs cannot paste `<<<missing:foo>>>` into customer answers.
    # Machine-readable signal stays in missing_data / precompute_gaps arrays.
    # Rollback gate: AUTONOMATH_STRIP_MISSING_TOKENS="0" returns the raw
    # skeleton verbatim (default "1" applies the strip).
    if os.environ.get("AUTONOMATH_STRIP_MISSING_TOKENS", "1") != "0":
        safe_skeleton = _re.sub(r"<<<missing:[a-z_0-9]+>>>", "(該当データなし)", raw_skeleton)
        safe_skeleton = _re.sub(r"<<<precompute gap: [^>]+>>>", "(集計準備中)", safe_skeleton)
    else:
        safe_skeleton = raw_skeleton

    db_bind = (result.bound or {}).get("db_bind") or {}
    source_urls = list(db_bind.get("source_urls") or [])
    bind_notes = list(db_bind.get("notes") or [])
    bound_ok = bool(db_bind.get("bound_ok"))

    # intent metadata
    try:
        intent = _qt_mod.get_intent(result.intent_id)
        intent_name = intent.name_ja
    except Exception:
        intent_name = None

    # retry_with heuristic: if confidence is low OR many missing, suggest
    # downstream tool fallbacks so the LLM knows what to call next.
    retry_with: list[str] = []
    if result.confidence < 0.4:
        retry_with.append("intent_of")  # let LLM re-classify
    if not bound_ok:
        retry_with.append("search_programs")
    if missing_data:
        # Top intents that pair well with specific tools
        tool_map = {
            "i02_program_deadline_documents": ["list_open_programs", "get_program"],
            "i04_tax_measure_sunset": ["search_tax_incentives"],
            "i05_certification_howto": ["search_certifications"],
            "i06_compat_incompat_stacking": ["check_exclusions", "related_programs"],
            "i07_adoption_cases": ["search_acceptance_stats", "search_case_studies"],
            "i03_program_successor_revision": ["search_by_law", "active_programs_at"],
            "i01_filter_programs_by_profile": ["search_programs", "list_open_programs"],
            "i09_succession_closure": ["search_programs", "search_tax_incentives"],
            "i10_wage_dx_gx_themed": ["search_programs", "search_tax_incentives"],
            "i08_similar_municipality_programs": ["search_programs"],
        }
        retry_with.extend(tool_map.get(result.intent_id, []))

    return {
        "intent": result.intent_id,
        "intent_name_ja": intent_name,
        "filters_extracted": filters_extracted,
        "answer_skeleton": safe_skeleton,
        "confidence": result.confidence,
        "missing_data": missing_data,
        "precompute_gaps": precompute_gaps,
        "source_urls": source_urls,
        "db_bind_ok": bound_ok,
        "db_bind_notes": bind_notes,
        "persona_hint": persona,
        "retry_with": retry_with,
    }


# ---------------------------------------------------------------------------
# Conditional MCP tool registration for currently-broken tools.
# `intent_of` + `reason_answer` are gated by AUTONOMATH_REASONING_ENABLED
# (reasoning package not installed). They keep their @_safe_tool wrap
# (defined above) so the function objects stay importable for tests; only
# the @mcp.tool registration is suppressed when the gate is False.
#
# `related_programs` was historically gated behind AUTONOMATH_GRAPH_ENABLED
# because the prior implementation queried a non-existent ``am_node`` table
# in graph.sqlite. 2026-04-29: rewritten to read am_relation + am_entities
# in autonomath.db directly (same pattern as graph_traverse_tool.py). The
# gate default flipped to True in config.py so the fixed tool is registered
# out of the box; flip ``AUTONOMATH_GRAPH_ENABLED=0`` to suppress
# registration if a regression surfaces.
# ---------------------------------------------------------------------------

if settings.autonomath_graph_enabled:
    related_programs = mcp.tool(annotations=_READ_ONLY)(related_programs)

if settings.autonomath_reasoning_enabled:
    intent_of = mcp.tool(annotations=_READ_ONLY)(intent_of)
    reason_answer = mcp.tool(annotations=_READ_ONLY)(reason_answer)


# ---------------------------------------------------------------------------
# Exports — the 10 tools (8 wave-3 DB tools + 2 reasoning tools).
# ---------------------------------------------------------------------------

__all__ = [
    "mcp",
    "search_tax_incentives",
    "search_certifications",
    "list_open_programs",
    "enum_values_am",
    "search_by_law",
    "active_programs_at",
    "related_programs",
    "search_acceptance_stats_am",
    "intent_of",
    "reason_answer",
]
