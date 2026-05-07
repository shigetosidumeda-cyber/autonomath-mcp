"""corporate_form_tools — 法人格 × program eligibility matrix (no LLM).

Two MCP tools mirroring the REST surface in ``api/corporate_form.py``:

  * ``programs_by_corporate_form_am(form, industry_jsic=None, limit=50)``
    Programs that the predicate JSON marks as accessible to the given
    法人格 (株式会社 / 合同会社 / NPO / 一般社団 / 公益社団 / 学校 /
    医療 / 個人事業主 等), optionally narrowed by JSIC 大分類.

  * ``program_eligibility_by_form_am(unified_id)``
    For a single program, the form-by-form eligibility matrix
    (allowed / not_allowed) for all 15 supported 法人格 codes.

Both share the implementation in ``api/corporate_form.py`` so the REST
and MCP surfaces stay in lockstep.

NO LLM. Single ¥3/req billing event per tool call. §52 / 行政書士法 §1
disclaimer envelope on every result — output is information retrieval,
not 申請代理 / 税務助言 / 経営判断.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import time
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.autonomath_tools.error_envelope import make_error
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

logger = logging.getLogger("jpintel.mcp.autonomath.corporate_form")

# Env-gate: default ON, flip "0" to disable without redeploy.
_ENABLED = os.environ.get("AUTONOMATH_CORPORATE_FORM_ENABLED", "1") == "1"


def _open_autonomath_ro() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db read-only via file URI.

    Mirrors the helper in api/corporate_form.py — soft-fail returns a
    make_error envelope when the DB is missing so the MCP caller gets a
    structured failure mode instead of an unhandled exception.
    """
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        db_path = raw
    else:
        # Repo root: this file is at src/jpintel_mcp/mcp/autonomath_tools/.
        from pathlib import Path

        db_path = str(Path(__file__).resolve().parents[4] / "autonomath.db")

    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["search_programs", "list_open_programs"],
        )


def _open_jpintel_ro() -> sqlite3.Connection | None:
    """Open jpintel.db read-only. Returns None on failure — the matrix
    surface degrades gracefully (predicate-side evidence still surfaces).
    """
    db_path = os.environ.get("JPINTEL_DB_PATH", "data/jpintel.db")
    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


# ---------------------------------------------------------------------------
# Pure-Python core — imported by REST + MCP. Kept in this module to avoid
# a circular import (api -> mcp_tool -> api would otherwise round-trip).
# ---------------------------------------------------------------------------


def programs_by_corporate_form_impl(
    form: str,
    *,
    industry_jsic: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Match programs whose predicate accepts ``form``."""
    from jpintel_mcp.api.corporate_form import (
        _CODE_TO_CLASS,
        _CODE_TO_LABEL,
        _DISCLAIMER,
        _FORM_CAVEAT,
        _JSIC_MAJOR_RE,
        _form_predicate_filter_sql,
        _industry_predicate_filter_sql,
        _normalize_form,
    )

    form_code = _normalize_form(form)
    if form_code is None:
        return make_error(
            code="invalid_enum",
            message=(
                "form must be one of: "
                + ", ".join(sorted(_CODE_TO_LABEL.keys()))
                + " (or the matching JP label)."
            ),
            field="form",
            hint=(
                "URL-safe short codes: kabushiki / goudou / npo / "
                "ippan_shadan / school / medical / sole / individual / ..."
            ),
        )
    if industry_jsic is not None and not _JSIC_MAJOR_RE.match(industry_jsic):
        return make_error(
            code="invalid_enum",
            message="industry_jsic must match '^[A-T]$' (1 letter A-T).",
            field="industry_jsic",
        )
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    conn_or_err = _open_autonomath_ro()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    am_conn = conn_or_err

    try:
        form_sql, form_args = _form_predicate_filter_sql(form_code)
        clauses: list[str] = [form_sql]
        bind_args: list[Any] = list(form_args)
        if industry_jsic is not None:
            ind_sql, ind_args = _industry_predicate_filter_sql(industry_jsic)
            clauses.append(ind_sql)
            bind_args.extend(ind_args)
        where_sql = " AND ".join(clauses)
        bind_args.append(int(limit))

        sql = f"""
            SELECT
                p.program_id  AS unified_id,
                json_extract(p.predicate_json, '$.target_entity_types') AS predicate_target_entity_types,
                json_extract(p.predicate_json, '$.industries_jsic')     AS predicate_industries_jsic,
                json_extract(p.predicate_json, '$.prefectures')         AS predicate_prefectures,
                json_extract(p.predicate_json, '$.funding_purposes')    AS predicate_funding_purposes,
                p.confidence       AS predicate_confidence,
                p.extraction_method AS predicate_extraction_method
              FROM am_program_eligibility_predicate_json p
             WHERE {where_sql}
             ORDER BY p.program_id ASC
             LIMIT ?
        """
        try:
            rows = am_conn.execute(sql, bind_args).fetchall()
        except sqlite3.OperationalError as exc:
            return make_error(
                code="db_unavailable",
                message=f"autonomath.db query failed: {exc}",
            )
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()

    # Hydrate programs metadata via jpintel.db (best-effort).
    unified_ids = [r["unified_id"] for r in rows if r["unified_id"]]
    meta: dict[str, dict[str, Any]] = {}
    if unified_ids:
        jp_conn = _open_jpintel_ro()
        if jp_conn is not None:
            try:
                placeholders = ", ".join("?" for _ in unified_ids)
                meta_rows = jp_conn.execute(
                    f"""
                    SELECT unified_id, primary_name, tier, prefecture,
                           authority_level, authority_name, program_kind,
                           amount_max_man_yen, subsidy_rate, source_url,
                           official_url
                      FROM programs
                     WHERE unified_id IN ({placeholders})
                       AND COALESCE(excluded, 0) = 0
                       AND tier IN ('S', 'A', 'B', 'C')
                    """,
                    unified_ids,
                ).fetchall()
                meta = {dict(r)["unified_id"]: dict(r) for r in meta_rows}
            except sqlite3.OperationalError:
                meta = {}
            finally:
                with contextlib.suppress(sqlite3.Error):
                    jp_conn.close()

    programs_out: list[dict[str, Any]] = []
    for r in rows:
        uid = r["unified_id"]
        m = meta.get(uid, {})

        def _parse(raw: str | None) -> Any:
            if not raw:
                return None
            try:
                return json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                return None

        programs_out.append(
            {
                "unified_id": uid,
                "primary_name": m.get("primary_name"),
                "tier": m.get("tier"),
                "prefecture": m.get("prefecture"),
                "authority_level": m.get("authority_level"),
                "authority_name": m.get("authority_name"),
                "program_kind": m.get("program_kind"),
                "amount_max_man_yen": m.get("amount_max_man_yen"),
                "subsidy_rate": m.get("subsidy_rate"),
                "source_url": m.get("source_url") or m.get("official_url"),
                "predicate_target_entity_types": _parse(r["predicate_target_entity_types"]),
                "predicate_industries_jsic": _parse(r["predicate_industries_jsic"]),
                "predicate_prefectures": _parse(r["predicate_prefectures"]),
                "predicate_funding_purposes": _parse(r["predicate_funding_purposes"]),
                "predicate_confidence": r["predicate_confidence"],
                "predicate_extraction_method": r["predicate_extraction_method"],
            }
        )

    return {
        "applied_filters": {
            "form_code": form_code,
            "form_label": _CODE_TO_LABEL[form_code],
            "form_entity_class": _CODE_TO_CLASS[form_code],
            "industry_jsic": industry_jsic,
            "limit": int(limit),
        },
        "programs": programs_out,
        "count": len(programs_out),
        "total": len(programs_out),
        "results": programs_out,
        "_disclaimer": _DISCLAIMER,
        "_form_caveat": _FORM_CAVEAT,
        "_next_calls": [
            {
                "tool": "program_eligibility_by_form_am",
                "args": {
                    "unified_id": (programs_out[0]["unified_id"] if programs_out else None),
                },
                "rationale": (
                    "Top match の form-by-form 適用表 (matrix) を確認 "
                    "(株式会社 / 合同会社 / NPO 等 15 axes)。"
                ),
            },
            {
                "tool": "check_funding_stack_am",
                "args": {
                    "program_ids": [p["unified_id"] for p in programs_out[:3]],
                },
                "rationale": ("Top 3 法人格-fit programs を 併用可否 マトリクスに渡す。"),
            },
        ],
    }


def program_eligibility_by_form_impl(unified_id: str) -> dict[str, Any]:
    """Form-by-form eligibility matrix for one program."""
    from jpintel_mcp.api.corporate_form import (
        _CORPORATE_FORMS,
        _DISCLAIMER,
        _FORM_CAVEAT,
        _UNIFIED_ID_RE,
        _classify_form_against_predicate,
    )

    if not unified_id or not _UNIFIED_ID_RE.match(unified_id):
        return make_error(
            code="invalid_enum",
            message="unified_id must match '^UNI-[0-9a-f]{10}$'",
            field="unified_id",
        )

    conn_or_err = _open_autonomath_ro()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    am_conn = conn_or_err
    try:
        try:
            row = am_conn.execute(
                """
                SELECT program_id,
                       predicate_json,
                       confidence,
                       extraction_method
                  FROM am_program_eligibility_predicate_json
                 WHERE program_id = ?
                 LIMIT 1
                """,
                (unified_id,),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            return make_error(
                code="db_unavailable",
                message=f"autonomath.db query failed: {exc}",
            )
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()

    if row is None:
        return make_error(
            code="not_found",
            message=(
                "no predicate row for this unified_id; the program may "
                "exist in `programs` but its eligibility predicate has "
                "not been extracted yet."
            ),
            field="unified_id",
        )

    try:
        predicate = json.loads(row["predicate_json"]) if row["predicate_json"] else {}
    except (TypeError, json.JSONDecodeError):
        predicate = {}
    target_entity_types: list[str] | None = predicate.get("target_entity_types")
    if target_entity_types is not None and not isinstance(target_entity_types, list):
        target_entity_types = None

    matrix: dict[str, dict[str, Any]] = {}
    for code, label, cls in _CORPORATE_FORMS:
        verdict, reason = _classify_form_against_predicate(code, target_entity_types)
        matrix[code] = {
            "label": label,
            "entity_class": cls,
            "verdict": verdict,
            "reason": reason,
        }

    program_meta: dict[str, Any] = {}
    jp_conn = _open_jpintel_ro()
    if jp_conn is not None:
        try:
            meta_row = jp_conn.execute(
                """
                SELECT unified_id, primary_name, tier, prefecture, program_kind,
                       amount_max_man_yen, subsidy_rate, source_url, official_url
                  FROM programs
                 WHERE unified_id = ?
                """,
                (unified_id,),
            ).fetchone()
            if meta_row is not None:
                program_meta = dict(meta_row)
        except sqlite3.OperationalError:
            program_meta = {}
        finally:
            with contextlib.suppress(sqlite3.Error):
                jp_conn.close()

    return {
        "unified_id": unified_id,
        "program": {
            "primary_name": program_meta.get("primary_name"),
            "tier": program_meta.get("tier"),
            "prefecture": program_meta.get("prefecture"),
            "program_kind": program_meta.get("program_kind"),
            "amount_max_man_yen": program_meta.get("amount_max_man_yen"),
            "subsidy_rate": program_meta.get("subsidy_rate"),
            "source_url": (program_meta.get("source_url") or program_meta.get("official_url")),
        },
        "matrix": matrix,
        "predicate_target_entity_types": target_entity_types,
        "predicate_confidence": row["confidence"],
        "predicate_extraction_method": row["extraction_method"],
        "_disclaimer": _DISCLAIMER,
        "_form_caveat": _FORM_CAVEAT,
        "_next_calls": [
            {
                "tool": "programs_by_corporate_form_am",
                "args": {"form": "kabushiki"},
                "rationale": (
                    "Bridge to the inverse axis: list other programs "
                    "open to 株式会社 (or any other 法人格)。"
                ),
            },
        ],
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------
if _ENABLED:

    @mcp.tool(annotations=_READ_ONLY)
    def programs_by_corporate_form_am(
        form: Annotated[
            str,
            Field(
                description=(
                    "法人格. URL-safe short code (kabushiki / goudou / "
                    "goushi / goumei / npo / ippan_shadan / koueki_shadan / "
                    "ippan_zaidan / koueki_zaidan / school / medical / "
                    "cooperative / sole / individual / foreign) OR "
                    "Japanese label (株式会社 / 合同会社 / NPO法人 / "
                    "一般社団法人 / 学校法人 / 医療法人 / 個人事業主 等)."
                ),
                examples=["goudou", "株式会社", "npo"],
            ),
        ],
        industry_jsic: Annotated[
            str | None,
            Field(
                description=("Optional JSIC 大分類 1-letter axis (A=農業 .. T=分類不能)."),
                examples=["D", "P"],
                max_length=1,
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=200,
                description="返却 programs の最大件数。Clamped to [1, 200]. Default 50.",
            ),
        ] = 50,
    ) -> dict[str, Any]:
        """[CORPORATE-FORM-AM] 法人格 × 制度 適用 matcher。NO LLM, ¥3/req metered. `_disclaimer` 必須。

        WHAT: ``am_program_eligibility_predicate_json`` の
        ``$.target_entity_types`` 軸 (5,702 rows) を法人格 short code に
        正規化し、与えられた form (株式会社 / 合同会社 / NPO / 一般社団 /
        公益社団 / 学校 / 医療 / 個人事業主 等) に該当する program を
        返却。``industry_jsic`` を与えると ``$.industries_jsic`` で
        さらに絞り込み。

        WHEN:
          - 「私の法人格 (合同会社) で使える制度を narrow したい」
          - 「個人事業主 NG 制度を frame out したい」
          - 「NPO 法人で建設業向け補助金を探したい (form=npo, industry_jsic=D)」

        WHEN NOT:
          - 法人格 不明 / 検索 → search_programs (free-text)
          - 都道府県 軸 → programs_by_region_am
          - 個別 program の form 適用表 → program_eligibility_by_form_am

        RETURNS (envelope):
          {
            applied_filters: {form_code, form_label, form_entity_class,
                              industry_jsic, limit},
            programs: [
              {unified_id, primary_name, tier, prefecture, program_kind,
               amount_max_man_yen, source_url,
               predicate_target_entity_types, predicate_industries_jsic,
               predicate_prefectures, predicate_funding_purposes,
               predicate_confidence, predicate_extraction_method},
              ...
            ],
            count, total, results,  # all = same list (FastMCP convention)
            _disclaimer,             # 税理士法 §52 / 行政書士法 §1 fence
            _form_caveat,            # predicate-axis precision note
            _next_calls: [...]       # composition hints
          }
        """
        _t0 = time.perf_counter()
        out = programs_by_corporate_form_impl(
            form=form,
            industry_jsic=industry_jsic,
            limit=limit,
        )
        if isinstance(out, dict) and out.get("error"):
            return out
        out["_latency_ms"] = int((time.perf_counter() - _t0) * 1000)
        return out

    @mcp.tool(annotations=_READ_ONLY)
    def program_eligibility_by_form_am(
        unified_id: Annotated[
            str,
            Field(
                min_length=14,
                max_length=14,
                pattern=r"^UNI-[0-9a-f]{10}$",
                description="Stable program unified_id (UNI-<10 hex>).",
                examples=["UNI-000780f85e"],
            ),
        ],
    ) -> dict[str, Any]:
        """[CORPORATE-FORM-AM] 制度別 法人格 適用表 (15 axes)。NO LLM, ¥3/req metered. `_disclaimer` 必須。

        WHAT: 1 program について、株式会社 / 合同会社 / 合資会社 / 合名会社 /
        NPO / 一般社団 / 公益社団 / 一般財団 / 公益財団 / 学校 / 医療 /
        事業協同組合 / 個人事業主 / 個人 / 外国法人 の 15 法人格について
        ``allowed`` / ``not_allowed`` を判定し、根拠 (predicate
        target_entity_types) を併記する。

        WHEN:
          - 「IT導入補助金 を 合同会社 が申請できるか?」
          - 「事業再構築補助金 の対象法人格を一覧で確認したい」
          - 「個人事業主 NG 制度を 1 個別チェック」

        WHEN NOT:
          - form 別の program list → programs_by_corporate_form_am
          - 法人 360 view → get_houjin_360_am
          - 制度本体の narrative → program_abstract_structured /
            search_programs(unified_id=...)

        RETURNS (envelope):
          {
            unified_id,
            program: {primary_name, tier, prefecture, program_kind,
                      amount_max_man_yen, subsidy_rate, source_url},
            matrix: {
              kabushiki:    {label, entity_class, verdict, reason},
              goudou:       {...},
              ...,
              foreign:      {...}
            },
            predicate_target_entity_types: [...] | null,
            predicate_confidence: float,
            predicate_extraction_method: 'rule_based'|'llm_extracted'|'manual',
            _disclaimer, _form_caveat, _next_calls
          }
        """
        _t0 = time.perf_counter()
        out = program_eligibility_by_form_impl(unified_id=unified_id)
        if isinstance(out, dict) and out.get("error"):
            return out
        out["_latency_ms"] = int((time.perf_counter() - _t0) * 1000)
        return out
