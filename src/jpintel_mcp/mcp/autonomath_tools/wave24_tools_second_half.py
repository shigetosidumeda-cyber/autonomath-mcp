"""wave24_tools_second_half — Chapter 10.7 後半 12 本 (#109-#120, 2026-05-04).

MASTER_PLAN_v1 §10.7 後半。Wave24 は §10.7 24 tool を 2 file に分割
(前半 #97-#108 = wave24_tools_first_half.py — 別 agent W1-15、後半 = この file)。

Tools shipped here
------------------

  #109 find_programs_by_jsic
      programs.jsic_major / middle / minor SELECT + tier filter。
      backing migration: wave24_113b (jsic columns) — 不在時 graceful。
      billing=1, NOT sensitive。

  #110 get_program_application_documents
      am_program_documents (wave24_138 想定) → 申請書類 list。
      backing: wave24_138 不在時 jpi_program_documents fallback。
      billing=1, sensitive (行政書士法 §1)。

  #111 find_adopted_companies_by_program
      jpi_adoption_records (現存 201,845 row) → 採択企業 list。
      billing=1, sensitive (個人情報保護法 / 信用情報法)。

  #112 score_application_probability  ★ 景表法 fence 強化 ★
      am_recommended_programs + am_capital_band_program_match +
      am_program_adoption_stats の 3 軸 join → 採択者プロファイル
      類似度 score (NOT probability)。「probability」「予測」表現は
      docstring と output schema で禁止。output field 名は `score`。
      billing=2, sensitive (景表法 + 行政書士法 §1)。

  #113 get_compliance_risk_score
      am_houjin_360_snapshot.derived_attrs_json から compliance_score 取り出し。
      billing=1, sensitive (信用情報法 / 弁護士法 §72 / 名誉毀損)。

  #114 simulate_tax_change_impact
      am_houjin_360_snapshot + am_tax_amendment_history join。
      billing=2, sensitive (税理士法 §52)。

  #115 find_complementary_subsidies
      am_program_combinations + am_program_calendar_12mo の 2-step join +
      時系列 overlap 計算。
      billing=1, sensitive (行政書士法 §1)。

  #116 get_program_keyword_analysis
      am_program_narrative + 事前計算済 TF-IDF cache 想定。
      cache 不在時 MeCab 実時間 tokenize に fallback (MeCab 不在時は
      naive word split)。billing=1, NOT sensitive。

  #117 get_industry_program_density
      am_region_program_density → 業種 × 地域密度。
      billing=1, NOT sensitive。

  #118 find_emerging_programs
      programs.first_seen_at で過去 N 日 filter。fallback = source_fetched_at。
      billing=1, NOT sensitive。

  #119 get_program_renewal_probability  ★ Wave22 forecast と異軸 ★
      am_amendment_diff の eligibility predicate diff 系列予測。
      docstring で「更新後の制度内容変化予測」(Wave22 forecast_program_renewal
      = 更新確率と異軸) を明示。billing=1, NOT sensitive。

  #120 get_houjin_subsidy_history
      jpi_adoption_records (houjin_bangou + since_year filter)。
      billing=1, sensitive (個人情報保護法 / 信用情報法)。

設計原則
---------
* @mcp.tool(annotations=_READ_ONLY) で self-register。registration を
  外部 file (server.py / __init__.py / main.py) に書く責務は別 agent
  W1-18。本 file は新 file 作成のみで実装。
* 全 tool: `total / limit / offset / results / _billing_unit / _next_calls`
  を envelope 必須 field として返す。
* error は error_envelope.make_error() に統一。
* sensitive 7 tool (#110-#115 + #120) は envelope_wrapper の SENSITIVE_TOOLS
  pre-registered 名で auto-disclaimer 注入される (S7 finding 2026-04-25
  既に envelope_wrapper.py:257-269 で登録済み)。本 file は inline でも
  `_disclaimer` を返さない (重複防止) — wrapper 側に任せる。
  ただし #112 のみ景表法 fence 強化のため inline で `_disclaimer_extra` 追加。
* 全 tool: NO LLM call (memory feedback_no_operator_llm_api 遵守)。
* 不在 table は try/except sqlite3.Error でグレース、空 result を返す。
* 末尾 `WAVE24_TOOLS_SECOND_HALF = [...]` で 12 callable を export。

NO Anthropic / OpenAI / Gemini / claude_agent_sdk import. CI guard
(tests/test_no_llm_in_production.py) 対応済み。
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import sqlite3
from collections import Counter
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.db.id_translator import normalize_program_id
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error as _raw_make_error
from .snapshot_helper import attach_corpus_snapshot


def make_error(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """make_error wrapper that always attaches the corpus_snapshot pair.

    W3-13 finding (2026-05-04): every customer-facing response —
    including error envelopes — must carry the auditor reproducibility
    pair. We wrap make_error here so every error-path return picks it
    up without having to touch every call site individually.
    """
    return attach_corpus_snapshot(_raw_make_error(*args, **kwargs))


def _finalize(body: dict[str, Any]) -> dict[str, Any]:
    """Attach corpus_snapshot pair to the impl response body. Idempotent."""
    return attach_corpus_snapshot(body)


logger = logging.getLogger("jpintel.mcp.autonomath.wave24_second_half")

# Env-gated registration. Default ON; flip to "0" for one-flag rollback.
_ENABLED = (
    get_flag("JPCITE_WAVE24_SECOND_HALF_ENABLED", "AUTONOMATH_WAVE24_SECOND_HALF_ENABLED", "1")
    == "1"
)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def _today_jst() -> datetime.date:
    """Today in JST."""
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()


def _open_db() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db RO conn or return error envelope dict."""
    try:
        return connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            hint="Ensure autonomath.db is present at the repo root or AUTONOMATH_DB_PATH.",
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
        )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Return True iff a sqlite table / view named `name` exists."""
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return bool(row)
    except sqlite3.Error:
        return False


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True iff `table` has a column named `column`."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == column for r in rows)
    except sqlite3.Error:
        return False


def _normalize_houjin(value: str | None) -> str:
    """Strip whitespace and a leading 'T' invoice prefix."""
    s = (value or "").strip().upper()
    if s.startswith("T") and len(s) == 14:
        s = s[1:]
    return s


def _to_unified(program_id: str) -> str:
    """Translate any ``program_id`` form to ``UNI-...`` for wave24 tables.

    Mirrors ``wave24_tools_first_half._to_unified`` — see that file for
    the full rationale. Wave24 substrate tables (``am_program_documents``,
    ``am_program_combinations`` etc.) key on ``program_unified_id``;
    customer LLMs may pass either ``UNI-...`` or ``program:...`` from
    upstream ``_next_calls``. Normalize once at the impl boundary so the
    SQL hits the right column without further branching. Falls back to
    the input on translation miss to preserve current behavior.
    """
    uni, _can = normalize_program_id(program_id)
    return uni or program_id


def _empty_envelope(
    *,
    billing_unit: int,
    limit: int,
    offset: int,
    next_calls: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a `total=0` graceful envelope when source tables are absent."""
    body: dict[str, Any] = {
        "total": 0,
        "limit": max(1, min(100, int(limit))),
        "offset": max(0, int(offset)),
        "results": [],
        "_billing_unit": billing_unit,
        "_next_calls": list(next_calls or []),
    }
    if extra:
        body.update(extra)
    return attach_corpus_snapshot(body)


# ---------------------------------------------------------------------------
# #109  find_programs_by_jsic
# ---------------------------------------------------------------------------


def _find_programs_by_jsic_impl(
    jsic_major: str | None = None,
    jsic_middle: str | None = None,
    jsic_minor: str | None = None,
    tier: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Filter jpi_programs by JSIC code + tier (graceful when columns absent)."""
    if not (jsic_major or jsic_middle or jsic_minor):
        return make_error(
            code="missing_required_arg",
            message="At least one of jsic_major / jsic_middle / jsic_minor is required.",
            hint="JSIC major (A..T) is the most common starting point.",
            field="jsic_major",
        )
    if jsic_major is not None:
        jm = jsic_major.strip().upper()
        if not (len(jm) == 1 and jm.isalpha()):
            return make_error(
                code="invalid_enum",
                message=f"jsic_major must be a single letter A..T (got {jsic_major!r}).",
                field="jsic_major",
            )
        jsic_major = jm
    if tier is not None and tier not in ("S", "A", "B", "C"):
        return make_error(
            code="invalid_enum",
            message=f"tier must be one of S/A/B/C (got {tier!r}).",
            field="tier",
        )
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_program_adoption_stats",
            "args": {"program_id": "<unified_id from results[]>"},
            "rationale": "JSIC narrowing → drill into per-program adoption stats.",
        },
        {
            "tool": "get_industry_program_density",
            "args": {"jsic_major": jsic_major or "*"},
            "rationale": "Compare per-region density against the same JSIC slice.",
        },
    ]

    # Graceful: jpi_programs may lack jsic_* columns until wave24_113b lands.
    has_jsic_major = _column_exists(conn, "jpi_programs", "jsic_major")
    has_jsic_middle = _column_exists(conn, "jpi_programs", "jsic_middle")
    has_jsic_minor = _column_exists(conn, "jpi_programs", "jsic_minor")
    if not (has_jsic_major or has_jsic_middle or has_jsic_minor):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "data_quality": {
                    "missing_columns": [
                        "jpi_programs.jsic_major",
                        "jpi_programs.jsic_middle",
                        "jpi_programs.jsic_minor",
                    ],
                    "caveat": "wave24_113b migration not yet applied — graceful empty.",
                },
            },
        )

    # `jpi_programs.excluded` is the live quarantine flag (default 0,
    # `tier='X'` rows carry 1). Some legacy / partial test DBs may
    # have been built without it — gate gracefully so the SELECT does
    # not crash with `no such column: excluded`.
    has_excluded = _column_exists(conn, "jpi_programs", "excluded")
    where: list[str] = ["excluded = 0"] if has_excluded else []
    params: list[Any] = []
    if jsic_major and has_jsic_major:
        where.append("jsic_major = ?")
        params.append(jsic_major)
    if jsic_middle and has_jsic_middle:
        where.append("jsic_middle = ?")
        params.append(jsic_middle.strip())
    if jsic_minor and has_jsic_minor:
        where.append("jsic_minor = ?")
        params.append(jsic_minor.strip())
    if tier:
        where.append("tier = ?")
        params.append(tier)
    if not where:
        where.append("1=1")
    where_sql = " AND ".join(where)

    try:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS n FROM jpi_programs WHERE {where_sql}",
            params,
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            f"""
            SELECT unified_id, primary_name, tier, prefecture, authority_name,
                   amount_max_man_yen, source_url, source_fetched_at
              FROM jpi_programs
             WHERE {where_sql}
             ORDER BY (CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 9 END),
                      primary_name
             LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpi_programs query failed: {exc}",
        )

    results = [dict(r) for r in rows]
    return _finalize(
        {
            "filter": {
                "jsic_major": jsic_major,
                "jsic_middle": jsic_middle,
                "jsic_minor": jsic_minor,
                "tier": tier,
            },
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": results,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #110  get_program_application_documents
# ---------------------------------------------------------------------------


def _get_program_application_documents_impl(
    program_id: str,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return application document list for a program.

    Primary source: am_program_documents (wave24_138 想定).
    Graceful fallback: jpi_program_documents (existing) when wave24_138 absent.
    """
    if not program_id or not isinstance(program_id, str):
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    pid = _to_unified(program_id.strip())
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "bundle_application_kit",
            "args": {"program_id": pid, "profile": {}},
            "rationale": "Documents → kit assembly with cover-letter scaffold.",
        },
        {
            "tool": "find_adopted_companies_by_program",
            "args": {"program_id": pid},
            "rationale": "Surface 採択 cohort to cross-reference required docs.",
        },
    ]

    rows: list[sqlite3.Row] = []
    source_table: str | None = None
    if _table_exists(conn, "am_program_documents"):
        try:
            rows = conn.execute(
                """
                SELECT doc_name, doc_kind, is_required, url, source_url
                  FROM am_program_documents
                 WHERE program_unified_id = ?
                 ORDER BY is_required DESC, doc_name
                 LIMIT ? OFFSET ?
                """,
                (pid, limit, offset),
            ).fetchall()
            source_table = "am_program_documents"
        except sqlite3.Error:
            rows = []
    if not rows and _table_exists(conn, "jpi_program_documents"):
        try:
            rows = conn.execute(
                """
                SELECT doc_name, doc_kind, is_required, url, source_url
                  FROM jpi_program_documents
                 WHERE program_id = ?
                 ORDER BY is_required DESC, doc_name
                 LIMIT ? OFFSET ?
                """,
                (pid, limit, offset),
            ).fetchall()
            source_table = "jpi_program_documents"
        except sqlite3.Error:
            rows = []

    results = [dict(r) for r in rows]
    if source_table is None:
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "program_id": pid,
                "data_quality": {
                    "missing_tables": ["am_program_documents", "jpi_program_documents"],
                    "caveat": "wave24_138 migration not yet applied — graceful empty.",
                },
            },
        )
    return _finalize(
        {
            "program_id": pid,
            "source_table": source_table,
            "total": len(results),
            "limit": limit,
            "offset": offset,
            "results": results,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #111  find_adopted_companies_by_program
# ---------------------------------------------------------------------------


def _find_adopted_companies_by_program_impl(
    program_id: str | None = None,
    program_name_partial: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """jpi_adoption_records SELECT — list 採択 companies for a program."""
    if not (program_id or program_name_partial):
        return make_error(
            code="missing_required_arg",
            message="One of program_id / program_name_partial is required.",
            field="program_id",
        )
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_houjin_subsidy_history",
            "args": {"houjin_bangou": "<from results[].houjin_bangou>"},
            "rationale": "Drill into the 法人's full subsidy history.",
        },
        {
            "tool": "get_program_adoption_stats",
            "args": {"program_id": program_id or "<resolve_first>"},
            "rationale": "Surface aggregate adoption stats for the same program.",
        },
    ]

    if not _table_exists(conn, "jpi_adoption_records"):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "data_quality": {
                    "missing_tables": ["jpi_adoption_records"],
                },
            },
        )

    where: list[str] = []
    params: list[Any] = []
    if program_id:
        norm_pid = _to_unified(program_id.strip())
        where.append("(program_id = ? OR program_id_hint = ?)")
        params.extend([norm_pid, norm_pid])
    if program_name_partial:
        where.append("program_name_raw LIKE ?")
        params.append(f"%{program_name_partial.strip()}%")
    where_sql = " AND ".join(where) if where else "1=1"

    try:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS n FROM jpi_adoption_records WHERE {where_sql}",
            params,
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            f"""
            SELECT houjin_bangou, company_name_raw, program_id, program_name_raw,
                   round_label, announced_at, prefecture, municipality,
                   industry_jsic_medium, amount_granted_yen, source_url
              FROM jpi_adoption_records
             WHERE {where_sql}
             ORDER BY announced_at DESC, id DESC
             LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpi_adoption_records query failed: {exc}",
        )

    return _finalize(
        {
            "program_id": program_id,
            "program_name_partial": program_name_partial,
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": [dict(r) for r in rows],
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #112  score_application_probability   ★ 景表法 fence 強化 ★
#
# 重要:
#   - 本 score は採択者プロファイル類似度 (similarity) であり、
#     採択確率 (probability) の予測ではない。
#   - output field 名は `score` であり `probability` ではない。
#   - 景表法違反リスクのため広告・営業利用禁止。
#   - 本 file 内で「probability」は禁止フレーズ周辺以外で使わない。
# ---------------------------------------------------------------------------


_DISCLAIMER_112_INLINE = (
    "本 score は am_recommended_programs + am_capital_band_program_match + "
    "am_program_adoption_stats 由来の採択者プロファイル類似度 (similarity) で、"
    "採択確率 (probability) の予測ではない。output field 名は `score` であり "
    "`probability` ではない。本 score を「採択保証」「採択率予測」として "
    "広告・営業に使用することは景表法 (不当景品類及び不当表示防止法) "
    "違反のリスクがあるため禁止。申請可否判断 (行政書士法 §1) の代替ではなく、"
    "確定判断は資格を有する行政書士・中小企業診断士へ。"
)


def _score_application_probability_impl(
    houjin_bangou: str,
    program_id: str,
) -> dict[str, Any]:
    """Compute similarity score between a houjin and a program.

    本 score は採択者プロファイル類似度 (similarity) で、採択確率 (probability)
    の予測ではない。3 axes:
      1. recommended_programs       (operator-side recommendation strength)
      2. capital_band_program_match (capital band fit)
      3. program_adoption_stats     (industry / region distribution match)

    Tables wave24_126 / wave24_134 / wave24_135 不在時は graceful score=null。
    """
    if not houjin_bangou or not isinstance(houjin_bangou, str):
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required (13-digit 法人番号).",
            field="houjin_bangou",
        )
    hb = _normalize_houjin(houjin_bangou)
    if not (hb.isdigit() and len(hb) == 13):
        return make_error(
            code="invalid_enum",
            message=f"houjin_bangou must be 13 digits (got {hb!r}).",
            field="houjin_bangou",
        )
    if not program_id or not isinstance(program_id, str):
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    pid = _to_unified(program_id.strip())

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "find_adopted_companies_by_program",
            "args": {"program_id": pid, "limit": 10},
            "rationale": "Inspect actual adopted cohort behind the similarity feed.",
        },
        {
            "tool": "get_program_application_documents",
            "args": {"program_id": pid},
            "rationale": "Surface required documents for the same program.",
        },
        {
            "tool": "get_houjin_subsidy_history",
            "args": {"houjin_bangou": hb},
            "rationale": "Cross-check 法人 prior subsidy footprint.",
        },
    ]

    base_extra = {
        "houjin_bangou": hb,
        "program_id": pid,
        # Inline 景表法 fence (envelope_wrapper auto-disclaimer is
        # ALSO injected via SENSITIVE_TOOLS — the inline copy makes
        # the fence robust against wrapper bypass paths).
        "_disclaimer_extra": _DISCLAIMER_112_INLINE,
    }

    axis_recommended: float | None = None
    axis_capital: float | None = None
    axis_adoption: float | None = None
    missing_tables: list[str] = []

    # Axis 1: am_recommended_programs
    if _table_exists(conn, "am_recommended_programs"):
        try:
            row = conn.execute(
                """
                SELECT similarity_score
                  FROM am_recommended_programs
                 WHERE houjin_bangou = ? AND program_unified_id = ?
                 LIMIT 1
                """,
                (hb, pid),
            ).fetchone()
            if row and row["similarity_score"] is not None:
                axis_recommended = float(row["similarity_score"])
        except sqlite3.Error:
            pass
    else:
        missing_tables.append("am_recommended_programs")

    # Axis 2: am_capital_band_program_match
    if _table_exists(conn, "am_capital_band_program_match"):
        try:
            row = conn.execute(
                """
                SELECT match_score
                  FROM am_capital_band_program_match
                 WHERE houjin_bangou = ? AND program_unified_id = ?
                 LIMIT 1
                """,
                (hb, pid),
            ).fetchone()
            if row and row["match_score"] is not None:
                axis_capital = float(row["match_score"])
        except sqlite3.Error:
            pass
    else:
        missing_tables.append("am_capital_band_program_match")

    # Axis 3: am_program_adoption_stats
    if _table_exists(conn, "am_program_adoption_stats"):
        try:
            row = conn.execute(
                """
                SELECT industry_distribution_json, region_distribution_json
                  FROM am_program_adoption_stats
                 WHERE program_unified_id = ?
                 ORDER BY fy DESC
                 LIMIT 1
                """,
                (pid,),
            ).fetchone()
            if row:
                # Heuristic: if 法人 industry / pref maps into the published
                # distribution, score = density share. Read aux tables to
                # resolve the 法人's industry + prefecture.
                industry_share = 0.0
                region_share = 0.0
                try:
                    h_row = conn.execute(
                        """
                        SELECT industry_jsic_medium, prefecture
                          FROM jpi_houjin_master
                         WHERE houjin_bangou = ?
                         LIMIT 1
                        """,
                        (hb,),
                    ).fetchone()
                except sqlite3.Error:
                    h_row = None
                jsic_med = (h_row["industry_jsic_medium"] if h_row else None) or ""
                pref = (h_row["prefecture"] if h_row else None) or ""
                if row["industry_distribution_json"] and jsic_med:
                    try:
                        ind = json.loads(row["industry_distribution_json"])
                        industry_share = float(ind.get(jsic_med, 0.0) or 0.0)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        industry_share = 0.0
                if row["region_distribution_json"] and pref:
                    try:
                        reg = json.loads(row["region_distribution_json"])
                        region_share = float(reg.get(pref, 0.0) or 0.0)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        region_share = 0.0
                axis_adoption = (industry_share + region_share) / 2.0
        except sqlite3.Error:
            pass
    else:
        missing_tables.append("am_program_adoption_stats")

    # Composite score (similarity, NOT a forecast)
    parts: list[float] = [
        v for v in (axis_recommended, axis_capital, axis_adoption) if v is not None
    ]
    score: float | None = round(sum(parts) / len(parts), 4) if parts else None

    return _finalize(
        {
            **base_extra,
            # Field 名は `score` で固定 (probability ではない)
            "score": score,
            "score_kind": "applicant_profile_similarity",
            "score_unit": "0.0..1.0",
            "score_breakdown": {
                "recommended_axis": axis_recommended,
                "capital_band_axis": axis_capital,
                "adoption_distribution_axis": axis_adoption,
                "axes_used": len(parts),
            },
            "data_quality": {
                "missing_tables": missing_tables,
                "axes_resolved": len(parts),
                "caveat": (
                    "本 score は採択者プロファイル類似度であり、採択確率の予測 ("
                    "forecast) ではない。axes_used < 3 は signal 弱、score=null は "
                    "全 axis 不在。"
                ),
            },
            "total": 1 if score is not None else 0,
            "limit": 1,
            "offset": 0,
            "results": ([{"score": score}] if score is not None else []),
            "_billing_unit": 2,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #113  get_compliance_risk_score
# ---------------------------------------------------------------------------


def _get_compliance_risk_score_impl(
    houjin_bangou: str,
) -> dict[str, Any]:
    """Pull derived_attrs_json.compliance_score from am_houjin_360_snapshot."""
    if not houjin_bangou or not isinstance(houjin_bangou, str):
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required (13-digit 法人番号).",
            field="houjin_bangou",
        )
    hb = _normalize_houjin(houjin_bangou)
    if not (hb.isdigit() and len(hb) == 13):
        return make_error(
            code="invalid_enum",
            message=f"houjin_bangou must be 13 digits (got {hb!r}).",
            field="houjin_bangou",
        )

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_houjin_360_am",
            "args": {"houjin_bangou": hb},
            "rationale": "Surface the full 360 view behind the score.",
        },
        {
            "tool": "get_houjin_360_snapshot_history",
            "args": {"houjin_bangou": hb},
            "rationale": "Compare current score against the time-series.",
        },
    ]

    if not _table_exists(conn, "am_houjin_360_snapshot"):
        return _empty_envelope(
            billing_unit=1,
            limit=1,
            offset=0,
            next_calls=next_calls,
            extra={
                "houjin_bangou": hb,
                "compliance_score": None,
                "data_quality": {"missing_tables": ["am_houjin_360_snapshot"]},
            },
        )

    try:
        row = conn.execute(
            """
            SELECT derived_attrs_json, snapshot_month
              FROM am_houjin_360_snapshot
             WHERE houjin_bangou = ?
             ORDER BY snapshot_month DESC
             LIMIT 1
            """,
            (hb,),
        ).fetchone()
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"am_houjin_360_snapshot query failed: {exc}",
        )

    score: float | None = None
    derived: dict[str, Any] = {}
    snapshot_month: str | None = None
    if row:
        snapshot_month = row["snapshot_month"]
        try:
            derived = json.loads(row["derived_attrs_json"] or "{}")
            raw = derived.get("compliance_score")
            if raw is not None:
                score = float(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            score = None

    return _finalize(
        {
            "houjin_bangou": hb,
            "snapshot_month": snapshot_month,
            "compliance_score": score,
            "score_unit": "0.0..1.0",
            "derived_attrs_keys": sorted(derived.keys()) if derived else [],
            "total": 1 if score is not None else 0,
            "limit": 1,
            "offset": 0,
            "results": (
                [{"houjin_bangou": hb, "compliance_score": score, "snapshot_month": snapshot_month}]
                if score is not None
                else []
            ),
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #114  simulate_tax_change_impact
# ---------------------------------------------------------------------------


def _simulate_tax_change_impact_impl(
    houjin_bangou: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Estimate program-eligibility impact of recent tax amendments on a 法人."""
    if not houjin_bangou or not isinstance(houjin_bangou, str):
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required (13-digit 法人番号).",
            field="houjin_bangou",
        )
    hb = _normalize_houjin(houjin_bangou)
    if not (hb.isdigit() and len(hb) == 13):
        return make_error(
            code="invalid_enum",
            message=f"houjin_bangou must be 13 digits (got {hb!r}).",
            field="houjin_bangou",
        )
    today = _today_jst()
    if fiscal_year is None:
        fy = today.year if today.month >= 4 else today.year - 1
    else:
        try:
            fy = int(fiscal_year)
        except (TypeError, ValueError):
            return make_error(
                code="invalid_enum",
                message=f"fiscal_year must be int (got {fiscal_year!r}).",
                field="fiscal_year",
            )
    fy_start = datetime.date(fy, 4, 1).isoformat()
    fy_end = datetime.date(fy + 1, 3, 31).isoformat()

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_tax_amendment_cycle",
            "args": {"tax_ruleset_id": "<from results[]>"},
            "rationale": "Drill into per-ruleset amendment cycle.",
        },
        {
            "tool": "prepare_kessan_briefing",
            "args": {"houjin_bangou": hb, "fiscal_year": fy},
            "rationale": "Surface 決算期 briefing for the same FY window.",
        },
    ]

    snapshot_present = _table_exists(conn, "am_houjin_360_snapshot")
    history_present = _table_exists(conn, "am_tax_amendment_history")
    if not (snapshot_present and history_present):
        return _empty_envelope(
            billing_unit=2,
            limit=20,
            offset=0,
            next_calls=next_calls,
            extra={
                "houjin_bangou": hb,
                "fiscal_year": fy,
                "data_quality": {
                    "missing_tables": [
                        t
                        for t, ok in [
                            ("am_houjin_360_snapshot", snapshot_present),
                            ("am_tax_amendment_history", history_present),
                        ]
                        if not ok
                    ],
                },
            },
        )

    snap_row = None
    try:
        snap_row = conn.execute(
            """
            SELECT snapshot_month, derived_attrs_json
              FROM am_houjin_360_snapshot
             WHERE houjin_bangou = ?
             ORDER BY snapshot_month DESC
             LIMIT 1
            """,
            (hb,),
        ).fetchone()
    except sqlite3.Error:
        snap_row = None

    amendments: list[dict[str, Any]] = []
    try:
        rows = conn.execute(
            """
            SELECT amendment_id, tax_ruleset_id, ruleset_name, change_kind,
                   prev_value, new_value, effective_from, source_url
              FROM am_tax_amendment_history
             WHERE effective_from BETWEEN ? AND ?
             ORDER BY effective_from ASC
             LIMIT 100
            """,
            (fy_start, fy_end),
        ).fetchall()
        amendments = [dict(r) for r in rows]
    except sqlite3.Error:
        amendments = []

    derived: dict[str, Any] = {}
    if snap_row:
        try:
            derived = json.loads(snap_row["derived_attrs_json"] or "{}")
        except (json.JSONDecodeError, TypeError, ValueError):
            derived = {}

    # Heuristic impact: each amendment touching a ruleset id present in
    # the 法人 snapshot's `applicable_tax_rulesets` list counts.
    applicable: list[str] = []
    if isinstance(derived.get("applicable_tax_rulesets"), list):
        applicable = [str(x) for x in derived["applicable_tax_rulesets"]]
    impacted = [a for a in amendments if str(a.get("tax_ruleset_id") or "") in set(applicable)]

    return _finalize(
        {
            "houjin_bangou": hb,
            "fiscal_year": fy,
            "fy_window": {"start": fy_start, "end": fy_end},
            "snapshot_month": (snap_row["snapshot_month"] if snap_row else None),
            "applicable_tax_rulesets": applicable,
            "amendments_in_window": len(amendments),
            "impacted_rulesets_count": len(impacted),
            "results": impacted[:20],
            "total": len(impacted),
            "limit": 20,
            "offset": 0,
            "_billing_unit": 2,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #115  find_complementary_subsidies
# ---------------------------------------------------------------------------


def _find_complementary_subsidies_impl(
    program_id: str,
    months_window: int = 12,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """2-step join: am_program_combinations × am_program_calendar_12mo + 時系列 overlap."""
    if not program_id or not isinstance(program_id, str):
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    pid = _to_unified(program_id.strip())
    months_window = max(1, min(int(months_window), 24))
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_program_calendar_12mo",
            "args": {"program_id": pid},
            "rationale": "Surface the calendar grid behind the overlap calc.",
        },
        {
            "tool": "find_combinable_programs",
            "args": {"program_id": pid},
            "rationale": "Cross-check exclusion / combinability rules.",
        },
    ]

    combo_present = _table_exists(conn, "am_program_combinations")
    calendar_present = _table_exists(conn, "am_program_calendar_12mo")
    if not (combo_present or calendar_present):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "program_id": pid,
                "data_quality": {
                    "missing_tables": [
                        t
                        for t, ok in [
                            ("am_program_combinations", combo_present),
                            ("am_program_calendar_12mo", calendar_present),
                        ]
                        if not ok
                    ],
                },
            },
        )

    # Step 1: candidates from combinations table
    candidates: list[dict[str, Any]] = []
    if combo_present:
        try:
            rows = conn.execute(
                """
                SELECT peer_program_id, combinable, confidence, reason
                  FROM (
                    SELECT program_b_unified_id AS peer_program_id, combinable, confidence, reason
                      FROM am_program_combinations
                     WHERE program_a_unified_id = ? AND combinable = 1
                    UNION ALL
                    SELECT program_a_unified_id AS peer_program_id, combinable, confidence, reason
                      FROM am_program_combinations
                     WHERE program_b_unified_id = ? AND combinable = 1
                  )
                 ORDER BY confidence DESC
                 LIMIT 100
                """,
                (pid, pid),
            ).fetchall()
            candidates = [dict(r) for r in rows]
        except sqlite3.Error:
            candidates = []

    # Step 2: time-overlap calc against 12-month calendar
    today = _today_jst()
    cutoff = today + datetime.timedelta(days=30 * months_window)
    today_iso = today.isoformat()
    cutoff_iso = cutoff.isoformat()

    enriched: list[dict[str, Any]] = []
    if calendar_present:
        for cand in candidates:
            peer_pid = cand.get("peer_program_id")
            if not peer_pid:
                continue
            try:
                cal_rows = conn.execute(
                    """
                    SELECT month_start, is_open, deadline
                      FROM am_program_calendar_12mo
                     WHERE program_unified_id = ? AND month_start BETWEEN ? AND ?
                     ORDER BY month_start ASC
                    """,
                    (peer_pid, today_iso, cutoff_iso),
                ).fetchall()
            except sqlite3.Error:
                cal_rows = []
            open_months = [r["month_start"] for r in cal_rows if r["is_open"]]
            cand_out = dict(cand)
            cand_out["overlap_open_months"] = open_months
            cand_out["overlap_open_count"] = len(open_months)
            cand_out["overlap_first_open_month"] = open_months[0] if open_months else None
            enriched.append(cand_out)

    enriched.sort(
        key=lambda c: (c.get("overlap_open_count", 0), c.get("confidence", 0.0) or 0.0),
        reverse=True,
    )
    page = enriched[offset : offset + limit]
    return _finalize(
        {
            "program_id": pid,
            "months_window": months_window,
            "today": today_iso,
            "cutoff": cutoff_iso,
            "total": len(enriched),
            "limit": limit,
            "offset": offset,
            "results": page,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #116  get_program_keyword_analysis
# ---------------------------------------------------------------------------


def _try_mecab_tokenize(text: str) -> list[str]:
    """Best-effort Japanese tokenize (MeCab if available, naive split otherwise)."""
    try:
        import MeCab
    except Exception:
        # Naive fallback: 2-char window over CJK + ascii words.
        out: list[str] = []
        for token in re.findall(r"[A-Za-z0-9]+|[一-龥ぁ-んァ-ヶー]+", text):
            if len(token) <= 1:
                continue
            if re.match(r"^[A-Za-z0-9]+$", token):
                out.append(token.lower())
                continue
            for i in range(len(token) - 1):
                out.append(token[i : i + 2])
        return out
    try:
        tagger = MeCab.Tagger("-Owakati")
        words = tagger.parse(text or "").strip().split()
        return [w for w in words if len(w) >= 2]
    except Exception:
        return []


_STOPWORDS_JA = {
    "こと",
    "もの",
    "これ",
    "それ",
    "あれ",
    "ため",
    "など",
    "から",
    "まで",
    "により",
    "について",
    "において",
    "ある",
    "する",
    "いる",
    "なる",
    "され",
    "本",
    "当",
    "対象",
    "事業",
    "事業者",
    "の",
    "を",
    "に",
    "は",
    "が",
}


def _get_program_keyword_analysis_impl(
    program_id: str,
    top_k: int = 30,
) -> dict[str, Any]:
    """Return per-program keywords (TF-IDF cache preferred, MeCab fallback)."""
    if not program_id or not isinstance(program_id, str):
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    pid = _to_unified(program_id.strip())
    top_k = max(1, min(int(top_k), 100))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_program_narrative",
            "args": {"program_id": pid, "lang": "ja", "section": "overview"},
            "rationale": "Surface the underlying narrative behind the keyword cloud.",
        },
        {
            "tool": "find_emerging_programs",
            "args": {"days": 90},
            "rationale": "Cross-check whether keywords overlap with new programs.",
        },
    ]

    # Try pre-computed TF-IDF cache first
    keywords: list[dict[str, Any]] = []
    source = "fallback_naive"
    if _table_exists(conn, "am_program_keyword_cache"):
        try:
            rows = conn.execute(
                """
                SELECT keyword, tfidf_score
                  FROM am_program_keyword_cache
                 WHERE program_id = ?
                 ORDER BY tfidf_score DESC
                 LIMIT ?
                """,
                (pid, top_k),
            ).fetchall()
            if rows:
                keywords = [
                    {"keyword": r["keyword"], "score": float(r["tfidf_score"])} for r in rows
                ]
                source = "tfidf_cache"
        except sqlite3.Error:
            keywords = []

    if not keywords:
        # Live tokenize over am_program_narrative
        narrative_present = _table_exists(conn, "am_program_narrative")
        if not narrative_present:
            return _empty_envelope(
                billing_unit=1,
                limit=top_k,
                offset=0,
                next_calls=next_calls,
                extra={
                    "program_id": pid,
                    "source": "missing",
                    "data_quality": {
                        "missing_tables": [
                            "am_program_keyword_cache",
                            "am_program_narrative",
                        ],
                    },
                },
            )
        try:
            text_rows = conn.execute(
                """
                SELECT section, lang, body_text
                  FROM am_program_narrative
                 WHERE program_id = ? AND lang = 'ja'
                """,
                (pid,),
            ).fetchall()
        except sqlite3.Error:
            text_rows = []
        joined = "\n".join((r["body_text"] or "") for r in text_rows)
        if not joined.strip():
            return _empty_envelope(
                billing_unit=1,
                limit=top_k,
                offset=0,
                next_calls=next_calls,
                extra={
                    "program_id": pid,
                    "source": "empty_narrative",
                },
            )
        tokens = _try_mecab_tokenize(joined)
        tokens = [t for t in tokens if t not in _STOPWORDS_JA]
        cnt = Counter(tokens)
        total_t = sum(cnt.values()) or 1
        keywords = [
            {
                "keyword": w,
                "score": round(c / total_t, 6),
                "freq": c,
            }
            for w, c in cnt.most_common(top_k)
        ]
        source = "mecab_live" if "MeCab" in str(type(_try_mecab_tokenize)) else source

    return _finalize(
        {
            "program_id": pid,
            "source": source,
            "total": len(keywords),
            "limit": top_k,
            "offset": 0,
            "results": keywords,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #117  get_industry_program_density
# ---------------------------------------------------------------------------


def _get_industry_program_density_impl(
    jsic_major: str | None = None,
    region_code: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """SELECT from am_region_program_density."""
    if not (jsic_major or region_code):
        return make_error(
            code="missing_required_arg",
            message="One of jsic_major / region_code is required.",
            field="jsic_major",
        )
    if jsic_major is not None:
        jm = jsic_major.strip().upper()
        if not (len(jm) == 1 and jm.isalpha()):
            return make_error(
                code="invalid_enum",
                message=f"jsic_major must be a single letter A..T (got {jsic_major!r}).",
                field="jsic_major",
            )
        jsic_major = jm
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "find_programs_by_jsic",
            "args": {"jsic_major": jsic_major or "*"},
            "rationale": "Drill into the program list behind the density.",
        },
        {
            "tool": "find_emerging_programs",
            "args": {"days": 90},
            "rationale": "Cross-check whether new programs shift density.",
        },
    ]

    if not _table_exists(conn, "am_region_program_density"):
        # Fallback: try the existing aggregates that share the same shape
        for fallback_table in (
            "industry_program_density",
            "jpi_industry_program_density",
        ):
            if not _table_exists(conn, fallback_table):
                continue
            where: list[str] = []
            params: list[Any] = []
            if jsic_major and _column_exists(conn, fallback_table, "jsic_major"):
                where.append("jsic_major = ?")
                params.append(jsic_major)
            if region_code and _column_exists(conn, fallback_table, "region_code"):
                where.append("region_code = ?")
                params.append(region_code.strip())
            where_sql = " AND ".join(where) if where else "1=1"
            try:
                rows = conn.execute(
                    f"""
                    SELECT *
                      FROM {fallback_table}
                     WHERE {where_sql}
                     LIMIT ? OFFSET ?
                    """,
                    params + [limit, offset],
                ).fetchall()
                results = [dict(r) for r in rows]
                # W5-4 (2026-05-04): fallback-table path must also carry the
                # corpus_snapshot_id + corpus_checksum reproducibility pair.
                return _finalize(
                    {
                        "filter": {"jsic_major": jsic_major, "region_code": region_code},
                        "source_table": fallback_table,
                        "total": len(results),
                        "limit": limit,
                        "offset": offset,
                        "results": results,
                        "_billing_unit": 1,
                        "_next_calls": next_calls,
                    }
                )
            except sqlite3.Error:
                continue
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "filter": {"jsic_major": jsic_major, "region_code": region_code},
                "data_quality": {
                    "missing_tables": [
                        "am_region_program_density",
                        "industry_program_density",
                        "jpi_industry_program_density",
                    ],
                },
            },
        )

    where = []
    params = []
    if jsic_major:
        where.append("jsic_major = ?")
        params.append(jsic_major)
    if region_code:
        where.append("region_code = ?")
        params.append(region_code.strip())
    where_sql = " AND ".join(where) if where else "1=1"

    try:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS n FROM am_region_program_density WHERE {where_sql}",
            params,
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            f"""
            SELECT jsic_major, region_code, region_name, program_count, density_per_capita
              FROM am_region_program_density
             WHERE {where_sql}
             ORDER BY density_per_capita DESC, program_count DESC
             LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"am_region_program_density query failed: {exc}",
        )
    return _finalize(
        {
            "filter": {"jsic_major": jsic_major, "region_code": region_code},
            "source_table": "am_region_program_density",
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": [dict(r) for r in rows],
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #118  find_emerging_programs
# ---------------------------------------------------------------------------


def _find_emerging_programs_impl(
    days: int = 90,
    tier: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """List programs newly observed within the past `days` days."""
    days = max(1, min(int(days), 730))
    if tier is not None and tier not in ("S", "A", "B", "C"):
        return make_error(
            code="invalid_enum",
            message=f"tier must be one of S/A/B/C (got {tier!r}).",
            field="tier",
        )
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    cutoff = (_today_jst() - datetime.timedelta(days=days)).isoformat()

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_program_narrative",
            "args": {"program_id": "<from results[]>", "lang": "ja", "section": "overview"},
            "rationale": "Surface narrative for the new programs.",
        },
        {
            "tool": "get_program_keyword_analysis",
            "args": {"program_id": "<from results[]>"},
            "rationale": "Surface keyword profile to spot policy themes.",
        },
    ]

    has_first_seen = _column_exists(conn, "jpi_programs", "first_seen_at")
    date_col = "first_seen_at" if has_first_seen else "source_fetched_at"
    if not _column_exists(conn, "jpi_programs", date_col):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "data_quality": {
                    "missing_columns": [
                        f"jpi_programs.{date_col}",
                    ],
                    "caveat": "first_seen_at not yet populated — use source_fetched_at as proxy.",
                },
            },
        )

    where = [f"{date_col} >= ?", "excluded = 0"]
    params: list[Any] = [cutoff]
    if tier:
        where.append("tier = ?")
        params.append(tier)
    where_sql = " AND ".join(where)

    try:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS n FROM jpi_programs WHERE {where_sql}",
            params,
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            f"""
            SELECT unified_id, primary_name, tier, prefecture, authority_name,
                   amount_max_man_yen, source_url, {date_col} AS observed_at
              FROM jpi_programs
             WHERE {where_sql}
             ORDER BY {date_col} DESC, primary_name
             LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpi_programs query failed: {exc}",
        )
    return _finalize(
        {
            "days_window": days,
            "cutoff": cutoff,
            "date_column_used": date_col,
            "tier": tier,
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": [dict(r) for r in rows],
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #119  get_program_renewal_probability   ★ Wave22 forecast と異軸 ★
#
# 重要:
#   本 tool は「更新後の制度内容変化予測」(eligibility predicate diff 系列)。
#   Wave22 既存 forecast_program_renewal (= 更新確率) とは異軸。重複ではない。
#   field 名は `predicate_diff_forecast` であり renewal probability ではない。
# ---------------------------------------------------------------------------


def _get_program_renewal_probability_impl(
    program_id: str,
    horizon_months: int = 12,
) -> dict[str, Any]:
    """Forecast the *content* shift across the next renewal cycle.

    本 tool は「更新後の制度内容変化予測」(eligibility predicate の diff 系列予測)。
    Wave22 既存 forecast_program_renewal (更新確率 = 続くかどうかの forecast)
    とは異軸。重複ではない。

    Mechanism: count am_amendment_diff rows where field_name は eligibility-class
    predicate (target_types / amount_max_yen / eligibility_text 等) で、
    過去 5 cycle 平均の per-cycle 変化数を horizon に scale する。
    """
    if not program_id or not isinstance(program_id, str):
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    pid = _to_unified(program_id.strip())
    horizon_months = max(1, min(int(horizon_months), 60))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "forecast_program_renewal",
            "args": {"program_id": pid},
            "rationale": (
                "Different axis: forecast_program_renewal = 更新確率。本 tool = "
                "更新後の制度内容変化予測。両 axis を併読して 設計判断を補強。"
            ),
        },
        {
            "tool": "get_program_calendar_12mo",
            "args": {"program_id": pid},
            "rationale": "Surface the next-12-month cycle behind the diff forecast.",
        },
    ]

    if not _table_exists(conn, "am_amendment_diff"):
        return _empty_envelope(
            billing_unit=1,
            limit=20,
            offset=0,
            next_calls=next_calls,
            extra={
                "program_id": pid,
                "predicate_diff_forecast": None,
                "data_quality": {"missing_tables": ["am_amendment_diff"]},
            },
        )

    eligibility_predicates = (
        "eligibility_text",
        "target_types",
        "target_types_json",
        "amount_max_yen",
        "amount_max_man_yen",
        "amount_min_yen",
        "subsidy_rate",
        "funding_purpose",
        "funding_purpose_json",
        "application_window",
    )
    placeholders = ",".join("?" for _ in eligibility_predicates)

    try:
        rows = conn.execute(
            f"""
            SELECT field_name, detected_at, prev_value, new_value, source_url
              FROM am_amendment_diff
             WHERE entity_id = ?
               AND field_name IN ({placeholders})
             ORDER BY detected_at ASC
            """,
            (pid, *eligibility_predicates),
        ).fetchall()
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"am_amendment_diff query failed: {exc}",
        )

    diffs = [dict(r) for r in rows]
    if not diffs:
        return _empty_envelope(
            billing_unit=1,
            limit=20,
            offset=0,
            next_calls=next_calls,
            extra={
                "program_id": pid,
                "predicate_diff_forecast": 0.0,
                "data_quality": {
                    "caveat": "No eligibility-predicate diffs recorded for this program.",
                },
            },
        )

    # Per-year diff rate, then scale to horizon_months.
    timestamps = []
    for d in diffs:
        ts = d.get("detected_at")
        if not ts:
            continue
        try:
            timestamps.append(datetime.date.fromisoformat(str(ts)[:10]))
        except (ValueError, TypeError):
            continue
    if len(timestamps) < 2:
        rate_per_month = float(len(timestamps))
    else:
        span_days = max(1, (timestamps[-1] - timestamps[0]).days)
        rate_per_month = float(len(timestamps)) / max(1.0, span_days / 30.0)
    forecast = round(rate_per_month * horizon_months, 3)

    # Per-field histogram for transparency.
    by_field = Counter(d["field_name"] for d in diffs if d.get("field_name"))
    return _finalize(
        {
            "program_id": pid,
            "horizon_months": horizon_months,
            "predicate_diff_forecast": forecast,
            "forecast_unit": "expected_predicate_diffs_in_horizon",
            "forecast_kind": "eligibility_predicate_diff_count",
            "axis_note": (
                "本 forecast は更新後の制度内容変化 (eligibility predicate diff) の"
                "予測で、Wave22 forecast_program_renewal (更新確率) とは異軸。"
            ),
            "by_field": dict(by_field),
            "diffs_observed": len(diffs),
            "first_observed_at": timestamps[0].isoformat() if timestamps else None,
            "last_observed_at": timestamps[-1].isoformat() if timestamps else None,
            "results": diffs[:20],
            "total": len(diffs),
            "limit": 20,
            "offset": 0,
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# #120  get_houjin_subsidy_history
# ---------------------------------------------------------------------------


def _get_houjin_subsidy_history_impl(
    houjin_bangou: str,
    since_year: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """jpi_adoption_records SELECT scoped by houjin_bangou + since_year."""
    if not houjin_bangou or not isinstance(houjin_bangou, str):
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required (13-digit 法人番号).",
            field="houjin_bangou",
        )
    hb = _normalize_houjin(houjin_bangou)
    if not (hb.isdigit() and len(hb) == 13):
        return make_error(
            code="invalid_enum",
            message=f"houjin_bangou must be 13 digits (got {hb!r}).",
            field="houjin_bangou",
        )
    if since_year is not None:
        try:
            since_year = int(since_year)
        except (TypeError, ValueError):
            return make_error(
                code="invalid_enum",
                message=f"since_year must be int (got {since_year!r}).",
                field="since_year",
            )
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    next_calls = [
        {
            "tool": "get_houjin_360_am",
            "args": {"houjin_bangou": hb},
            "rationale": "Surface the full 360 view alongside the subsidy timeline.",
        },
        {
            "tool": "get_compliance_risk_score",
            "args": {"houjin_bangou": hb},
            "rationale": "Cross-check compliance score against subsidy footprint.",
        },
    ]

    if not _table_exists(conn, "jpi_adoption_records"):
        return _empty_envelope(
            billing_unit=1,
            limit=limit,
            offset=offset,
            next_calls=next_calls,
            extra={
                "houjin_bangou": hb,
                "data_quality": {"missing_tables": ["jpi_adoption_records"]},
            },
        )

    where = ["houjin_bangou = ?"]
    params: list[Any] = [hb]
    if since_year is not None:
        where.append("substr(announced_at, 1, 4) >= ?")
        params.append(f"{since_year:04d}")
    where_sql = " AND ".join(where)

    try:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS n, COALESCE(SUM(amount_granted_yen), 0) AS total_yen "
            f"FROM jpi_adoption_records WHERE {where_sql}",
            params,
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        total_yen = int(total_row["total_yen"]) if total_row else 0
        rows = conn.execute(
            f"""
            SELECT id, program_id, program_name_raw, round_label, announced_at,
                   prefecture, municipality, industry_jsic_medium,
                   amount_granted_yen, amount_project_total_yen, source_url
              FROM jpi_adoption_records
             WHERE {where_sql}
             ORDER BY announced_at DESC, id DESC
             LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpi_adoption_records query failed: {exc}",
        )

    return _finalize(
        {
            "houjin_bangou": hb,
            "since_year": since_year,
            "total": total,
            "total_amount_granted_yen": total_yen,
            "limit": limit,
            "offset": offset,
            "results": [dict(r) for r in rows],
            "_billing_unit": 1,
            "_next_calls": next_calls,
        }
    )


# ---------------------------------------------------------------------------
# Tool registration (only when AUTONOMATH_ENABLED + W1-18 import path).
# ---------------------------------------------------------------------------


# Public callables — order mirrors the 12 numbered slots #109..#120.
_TOOL_FUNCS: tuple[tuple[str, Any], ...] = (
    ("find_programs_by_jsic", _find_programs_by_jsic_impl),
    ("get_program_application_documents", _get_program_application_documents_impl),
    ("find_adopted_companies_by_program", _find_adopted_companies_by_program_impl),
    ("score_application_probability", _score_application_probability_impl),
    ("get_compliance_risk_score", _get_compliance_risk_score_impl),
    ("simulate_tax_change_impact", _simulate_tax_change_impact_impl),
    ("find_complementary_subsidies", _find_complementary_subsidies_impl),
    ("get_program_keyword_analysis", _get_program_keyword_analysis_impl),
    ("get_industry_program_density", _get_industry_program_density_impl),
    ("find_emerging_programs", _find_emerging_programs_impl),
    ("get_program_renewal_probability", _get_program_renewal_probability_impl),
    ("get_houjin_subsidy_history", _get_houjin_subsidy_history_impl),
)


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def find_programs_by_jsic(
        jsic_major: Annotated[
            str | None,
            Field(description="JSIC major (single letter A..T)."),
        ] = None,
        jsic_middle: Annotated[
            str | None,
            Field(description="JSIC middle (2 chars)."),
        ] = None,
        jsic_minor: Annotated[
            str | None,
            Field(description="JSIC minor (3 chars)."),
        ] = None,
        tier: Annotated[
            str | None,
            Field(description="Tier filter: S / A / B / C."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="Page size.")] = 20,
        offset: Annotated[int, Field(ge=0, description="Page offset.")] = 0,
    ) -> dict[str, Any]:
        """Filter the public program catalog by JSIC code (major/middle/minor) + tier (S/A/B/C). Pure SELECT, NO LLM."""
        return _find_programs_by_jsic_impl(
            jsic_major=jsic_major,
            jsic_middle=jsic_middle,
            jsic_minor=jsic_minor,
            tier=tier,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def get_program_application_documents(
        program_id: Annotated[
            str,
            Field(
                description="Target program id — accepts BOTH unified_id (UNI-...) and am_entities canonical_id (program:...). Internal translator routes to the right column."
            ),
        ],
        limit: Annotated[int, Field(ge=1, le=100, description="Page size.")] = 50,
        offset: Annotated[int, Field(ge=0, description="Page offset.")] = 0,
    ) -> dict[str, Any]:
        """Application document list for a program. Returns known document metadata only; §1 行政書士法 sensitive — list 提供のみ、書面作成は対象外。"""
        return _get_program_application_documents_impl(
            program_id=program_id,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def find_adopted_companies_by_program(
        program_id: Annotated[
            str | None,
            Field(
                description="Target program id — accepts BOTH unified_id (UNI-...) and am_entities canonical_id (program:...). Internal translator routes to the right column."
            ),
        ] = None,
        program_name_partial: Annotated[
            str | None,
            Field(description="Partial program name (LIKE)."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="Page size.")] = 20,
        offset: Annotated[int, Field(ge=0, description="Page offset.")] = 0,
    ) -> dict[str, Any]:
        """Adopted-company list for a program (jpi_adoption_records, 201,845 rows). 個人情報保護法 / 信用情報法 sensitive — public 採択 list のみ、与信判断には流用しない。"""
        return _find_adopted_companies_by_program_impl(
            program_id=program_id,
            program_name_partial=program_name_partial,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def score_application_probability(
        houjin_bangou: Annotated[
            str,
            Field(description="13-digit 法人番号 (with or without 'T' prefix)."),
        ],
        program_id: Annotated[
            str,
            Field(
                description="Target program id — accepts BOTH unified_id (UNI-...) and am_entities canonical_id (program:...). Internal translator routes to the right column."
            ),
        ],
    ) -> dict[str, Any]:
        """採択者プロファイル類似度 score (similarity)。本 score は採択確率 (probability) の予測ではない。output field 名は `score`。景表法違反リスクのため広告・営業利用禁止。3 軸 join: am_recommended_programs + am_capital_band_program_match + am_program_adoption_stats。billing=2 単位、行政書士法 §1 sensitive。"""
        return _score_application_probability_impl(
            houjin_bangou=houjin_bangou,
            program_id=program_id,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def get_compliance_risk_score(
        houjin_bangou: Annotated[
            str,
            Field(description="13-digit 法人番号 (with or without 'T' prefix)."),
        ],
    ) -> dict[str, Any]:
        """Compliance score derived from am_houjin_360_snapshot.derived_attrs_json.compliance_score. 信用情報法 / 弁護士法 §72 / 名誉毀損 sensitive — heuristic, 与信代替不可。"""
        return _get_compliance_risk_score_impl(houjin_bangou=houjin_bangou)

    @mcp.tool(annotations=_READ_ONLY)
    def simulate_tax_change_impact(
        houjin_bangou: Annotated[
            str,
            Field(description="13-digit 法人番号 (with or without 'T' prefix)."),
        ],
        fiscal_year: Annotated[
            int | None,
            Field(description="Fiscal year (April-March). Default = current FY."),
        ] = None,
    ) -> dict[str, Any]:
        """Tax-amendment impact simulation: am_houjin_360_snapshot.applicable_tax_rulesets × am_tax_amendment_history within FY window. billing=2 単位、税理士法 §52 sensitive — 試算のみ、税務代理は対象外。"""
        return _simulate_tax_change_impact_impl(
            houjin_bangou=houjin_bangou,
            fiscal_year=fiscal_year,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def find_complementary_subsidies(
        program_id: Annotated[
            str,
            Field(
                description="Target program id — accepts BOTH unified_id (UNI-...) and am_entities canonical_id (program:...). Internal translator routes to the right column."
            ),
        ],
        months_window: Annotated[
            int,
            Field(ge=1, le=24, description="Calendar overlap horizon (months)."),
        ] = 12,
        limit: Annotated[int, Field(ge=1, le=100, description="Page size.")] = 20,
        offset: Annotated[int, Field(ge=0, description="Page offset.")] = 0,
    ) -> dict[str, Any]:
        """Complementary subsidies via 2-step join: am_program_combinations × am_program_calendar_12mo + 時系列 overlap calc. 行政書士法 §1 sensitive."""
        return _find_complementary_subsidies_impl(
            program_id=program_id,
            months_window=months_window,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def get_program_keyword_analysis(
        program_id: Annotated[
            str,
            Field(
                description="Target program id — accepts BOTH unified_id (UNI-...) and am_entities canonical_id (program:...). Internal translator routes to the right column."
            ),
        ],
        top_k: Annotated[int, Field(ge=1, le=100, description="Top K keywords.")] = 30,
    ) -> dict[str, Any]:
        """Per-program keyword cloud. Source: am_program_keyword_cache (TF-IDF pre-computed) preferred, MeCab live tokenize over am_program_narrative as fallback (naive 2-char window when MeCab absent). NOT sensitive."""
        return _get_program_keyword_analysis_impl(
            program_id=program_id,
            top_k=top_k,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def get_industry_program_density(
        jsic_major: Annotated[
            str | None,
            Field(description="JSIC major (single letter A..T)."),
        ] = None,
        region_code: Annotated[
            str | None,
            Field(description="Region (5-digit JIS X 0401/0402) code."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="Page size.")] = 20,
        offset: Annotated[int, Field(ge=0, description="Page offset.")] = 0,
    ) -> dict[str, Any]:
        """Per-industry × region program density (am_region_program_density). Fallback: industry_program_density / jpi_industry_program_density. NOT sensitive."""
        return _get_industry_program_density_impl(
            jsic_major=jsic_major,
            region_code=region_code,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def find_emerging_programs(
        days: Annotated[
            int,
            Field(ge=1, le=730, description="Look-back window (days)."),
        ] = 90,
        tier: Annotated[
            str | None,
            Field(description="Tier filter: S / A / B / C."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="Page size.")] = 20,
        offset: Annotated[int, Field(ge=0, description="Page offset.")] = 0,
    ) -> dict[str, Any]:
        """Programs newly observed in the past N days using first_seen_at or source_fetched_at. NOT sensitive."""
        return _find_emerging_programs_impl(
            days=days,
            tier=tier,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def get_program_renewal_probability(
        program_id: Annotated[
            str,
            Field(
                description="Target program id — accepts BOTH unified_id (UNI-...) and am_entities canonical_id (program:...). Internal translator routes to the right column."
            ),
        ],
        horizon_months: Annotated[
            int,
            Field(ge=1, le=60, description="Forecast horizon (months)."),
        ] = 12,
    ) -> dict[str, Any]:
        """更新後の制度内容変化予測 (eligibility predicate diff 系列予測)。output field 名は `predicate_diff_forecast`。am_amendment_diff の eligibility predicate field のみを集計、horizon_months に scale。NOT sensitive (statistical)."""
        return _get_program_renewal_probability_impl(
            program_id=program_id,
            horizon_months=horizon_months,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def get_houjin_subsidy_history(
        houjin_bangou: Annotated[
            str,
            Field(description="13-digit 法人番号 (with or without 'T' prefix)."),
        ],
        since_year: Annotated[
            int | None,
            Field(description="Filter announced_at year >= since_year."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=200, description="Page size.")] = 50,
        offset: Annotated[int, Field(ge=0, description="Page offset.")] = 0,
    ) -> dict[str, Any]:
        """法人別補助金交付履歴 (jpi_adoption_records, houjin_bangou + since_year filter, total_amount_granted_yen 含む). 個人情報保護法 / 信用情報法 sensitive — 公表交付決定 list 由来、与信判断には流用しない。"""
        return _get_houjin_subsidy_history_impl(
            houjin_bangou=houjin_bangou,
            since_year=since_year,
            limit=limit,
            offset=offset,
        )


# ---------------------------------------------------------------------------
# Public exports — W1-18 imports this list to register at server.py boot.
# Order matches §10.7 #109..#120.
# ---------------------------------------------------------------------------

WAVE24_TOOLS_SECOND_HALF: list[Any] = [fn for _name, fn in _TOOL_FUNCS]


__all__ = [
    "WAVE24_TOOLS_SECOND_HALF",
    "_find_programs_by_jsic_impl",
    "_get_program_application_documents_impl",
    "_find_adopted_companies_by_program_impl",
    "_score_application_probability_impl",
    "_get_compliance_risk_score_impl",
    "_simulate_tax_change_impact_impl",
    "_find_complementary_subsidies_impl",
    "_get_program_keyword_analysis_impl",
    "_get_industry_program_density_impl",
    "_find_emerging_programs_impl",
    "_get_program_renewal_probability_impl",
    "_get_houjin_subsidy_history_impl",
]
