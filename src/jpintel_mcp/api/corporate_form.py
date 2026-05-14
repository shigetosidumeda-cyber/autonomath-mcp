"""REST handlers for the corporate-form × program eligibility matrix.

Surfaces the 法人格 → applicable-program lens that is otherwise scattered
across `am_target_profile` (43 rows of normalised entity-class buckets,
already anchored on 中小企業基本法 / 商業登記法 categories) and
`am_program_eligibility_predicate_json` (5,702 rows whose
``$.target_entity_types`` array carries the per-program form filter).

Two routes:

  * ``GET /v1/programs/by_corporate_form?form=<form>&industry_jsic=<axis>``
    Programs that EITHER explicitly list ``form`` in their predicate
    ``target_entity_types`` array OR carry no entity-type filter at all
    (treated as 'open to any 法人格'). Optional ``industry_jsic`` narrows
    further on the predicate's ``industries_jsic`` major-letter axis.

  * ``GET /v1/programs/{unified_id}/eligibility_by_form``
    For a single program, returns the explicit form-by-form eligibility
    matrix: every supported 法人格 mapped to ``allowed`` / ``not_allowed``
    / ``unspecified`` plus a short reason citing the predicate field that
    drove the verdict.

Pricing: ¥3/req metered (1 unit). Anonymous tier shares the 3/日 IP cap
via AnonIpLimitDep on the router mount in ``api/main.py``.

§52 envelope: every 2xx body carries a ``_disclaimer`` (税理士法 §52 fence)
plus a ``_form_caveat`` block documenting that the predicate JSON is
auto-extracted from the public corpus and may lag behind 公募要領 改訂.
LLM relays must surface both verbatim.

Read-only — opens autonomath.db in ``mode=ro`` so a misconfigured deploy
can never write to the unified DB through this surface. Pure SQL +
``json_extract`` — NO LLM call.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._envelope import StandardError, StandardResponse, wants_envelope_v2
from jpintel_mcp.api._error_envelope import safe_request_id
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

router = APIRouter(prefix="/v1/programs", tags=["programs"])


# ---------------------------------------------------------------------------
# 法人格 enum — canonical short codes (URL-safe) + their JP labels.
#
# These align 1:1 with `am_target_profile.entity_class` CHECK domain so a
# matrix lookup never needs a fuzzy-match step. We intentionally enumerate
# the eight shapes the customer brief calls out plus the three ``any`` /
# ``individual`` / ``foreign`` adapters that live in the same axis.
# ---------------------------------------------------------------------------

# (code, jp_label, am_target_profile.entity_class).
# The third element is the bucket we hand back into a target_profile join
# (multiple profiles may share a class — e.g. ``corporation`` covers
# 株式会社 + 合同会社 + 合資会社 + 大企業 + 中堅企業 etc).
_CORPORATE_FORMS: tuple[tuple[str, str, str], ...] = (
    ("kabushiki", "株式会社", "corporation"),
    ("goudou", "合同会社", "corporation"),
    ("goushi", "合資会社", "corporation"),
    ("goumei", "合名会社", "corporation"),
    ("npo", "NPO法人", "npo"),
    ("ippan_shadan", "一般社団法人", "association"),
    ("koueki_shadan", "公益社団法人", "association"),
    ("ippan_zaidan", "一般財団法人", "association"),
    ("koueki_zaidan", "公益財団法人", "association"),
    ("school", "学校法人", "school_corporation"),
    ("medical", "医療法人", "medical_corporation"),
    ("cooperative", "事業協同組合", "cooperative"),
    ("sole", "個人事業主", "sole_proprietor"),
    ("individual", "個人", "individual"),
    ("foreign", "外資系・外国法人", "foreign"),
)

# JP-label → code. Accepts either the URL-safe short code OR the canonical
# 法人格 string in Japanese; we NFKC the input first so 全角 → 半角.
_JP_TO_CODE: dict[str, str] = {jp: code for code, jp, _cls in _CORPORATE_FORMS}
_CODE_TO_LABEL: dict[str, str] = {code: jp for code, jp, _cls in _CORPORATE_FORMS}
_CODE_TO_CLASS: dict[str, str] = {code: cls for code, _jp, cls in _CORPORATE_FORMS}

# `target_entity_types` strings the predicate corpus actually uses. The
# canonical column is am_target_profile.entity_class but the predicate
# extractor in scripts/etl/ also writes legacy short-form values
# (``sole_proprietor`` / ``corporation`` / ``individual`` / ``npo``) and
# a handful of JP names (``法人`` / ``個人事業主`` / ``NPO法人``). We
# expand each form-code to the union of strings that COULD appear in
# the predicate JSON so the SQL filter is robust to drift.
#
# Note: when the customer asks for 株式会社 / 合同会社 specifically, we
# can only match the broader ``corporation`` / ``法人`` strings — the
# predicate corpus does NOT carry sub-form distinctions. The response
# echoes this caveat in `_form_caveat` so callers do not over-promise.
_FORM_TO_PREDICATE_VALUES: dict[str, tuple[str, ...]] = {
    "kabushiki": ("corporation", "法人", "株式会社"),
    "goudou": ("corporation", "法人", "合同会社"),
    "goushi": ("corporation", "法人", "合資会社"),
    "goumei": ("corporation", "法人", "合名会社"),
    "npo": ("npo", "NPO", "NPO法人", "特定非営利活動法人"),
    "ippan_shadan": ("association", "一般社団法人", "社団法人"),
    "koueki_shadan": ("association", "公益社団法人", "社団法人"),
    "ippan_zaidan": ("association", "一般財団法人", "財団法人"),
    "koueki_zaidan": ("association", "公益財団法人", "財団法人"),
    "school": ("school_corporation", "学校法人"),
    "medical": ("medical_corporation", "医療法人"),
    "cooperative": ("cooperative", "事業協同組合", "協同組合"),
    "sole": ("sole_proprietor", "個人事業主"),
    "individual": ("individual", "個人"),
    "foreign": ("foreign", "外国法人", "外資"),
}

# JSIC major axis (大分類) — 20 letters A-T per 統計法 industry classification.
# Used purely as an input validator; the predicate column stores values like
# ``["A", "D", "K"]`` or ``["E"]``.
_JSIC_MAJOR_RE = re.compile(r"^[A-T]$")

# Per-call program list cap. Same posture as discover.py / programs.py
# search — keeps the envelope under the 50 KB target on a hot path.
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200

# §52 fence. Mirrors api/houjin.py and api/tax_rulesets.py copy.
_DISCLAIMER = (
    "本情報は税務助言ではありません。jpcite は公的機関 (gBizINFO・国税庁・"
    "経済産業省・厚生労働省 等) が公表する制度・法令情報を検索・整理して"
    "提供するサービスで、税理士法 §52 / 行政書士法 §1の2 に基づき個別具体的な"
    "申請助言・書面作成代行は行いません。最終判断は資格を有する税理士・"
    "行政書士・社労士の確認のもと、必ず一次資料 (公募要領 / 公式 URL) と"
    "突き合わせてください。"
)

# 法人格 caveat — predicate JSON is auto-extracted from 公募要領 / 公式 URL
# corpora. The extractor recognises a coarse axis (corporation / sole_proprietor /
# npo / ...) but does NOT distinguish 株式会社 vs 合同会社 vs 合資会社. A
# program that lists ``corporation`` accepts every 会社法 法人 form unless
# 公募要領 separately excludes one. Surface this verbatim so callers do not
# over-claim "this 制度 is 合同会社-only".
_FORM_CAVEAT = (
    "法人格 axis は 公募要領 corpus からの自動抽出 (am_program_eligibility_"
    "predicate_json) に基づきます。corporation 1 値で 株式会社/合同会社/"
    "合資会社/合名会社 を一括カバーするため、サブ法人格 ('株式会社のみ'等) "
    "を分離する場合は 一次資料 公募要領 を直接ご確認ください。NPO・学校・"
    "医療・社団・財団・組合 は別 entity_class で個別に判定します。"
    "本 endpoint の predicate corpus は最終ロード snapshot (autonomath.db "
    "am_program_eligibility_predicate_json) であり、最新の 公募要領 改訂を "
    "反映していない可能性があります。"
)


# ---------------------------------------------------------------------------
# DB connection helpers
# ---------------------------------------------------------------------------


def _autonomath_db_path() -> Path:
    """Mirror api/houjin.py::_autonomath_db_path resolution."""
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[3] / "autonomath.db"


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open a read-only connection to autonomath.db. Returns None when
    the file is missing — the route then surfaces a structured 503.
    """
    p = _autonomath_db_path()
    if not p.exists() or p.stat().st_size == 0:
        return None
    uri = f"file:{p}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("PRAGMA query_only=1")
            conn.execute("PRAGMA temp_store=MEMORY")
        return conn
    except sqlite3.OperationalError:
        return None


def _normalize_form(raw: str) -> str | None:
    """Resolve URL-safe short code OR Japanese label OR raw entity_class
    bucket to the canonical short code. Returns ``None`` on miss.

    Examples
    --------
    'goudou'   → 'goudou'
    '合同会社' → 'goudou'
    'corporation' → 'kabushiki'  (ambiguous; defaults to 株式会社 surface)
    """
    if not raw:
        return None
    s = raw.strip()
    # Direct short-code hit.
    if s in _CODE_TO_LABEL:
        return s
    # JP label hit.
    if s in _JP_TO_CODE:
        return _JP_TO_CODE[s]
    # entity_class bucket — return the FIRST short code that maps to it.
    for code, _jp, cls in _CORPORATE_FORMS:
        if cls == s:
            return code
    return None


def _form_predicate_filter_sql(form_code: str) -> tuple[str, list[str]]:
    """Build a SQL fragment + bind-args that match a predicate row whose
    ``$.target_entity_types`` JSON array contains ANY of the strings we
    accept for ``form_code``, OR which has NO ``target_entity_types`` key
    at all (treated as 'open to any form' per the data dictionary).
    """
    candidates = _FORM_TO_PREDICATE_VALUES[form_code]
    # `EXISTS (SELECT 1 FROM json_each(...) WHERE value IN (?, ?, ...))`
    # is index-safe because json_each is a vtab join SQLite handles
    # natively. We OR with the 'no target_entity_types key at all' branch
    # so universally-open programs surface for every form code.
    placeholders = ", ".join("?" for _ in candidates)
    sql = (
        "(json_extract(predicate_json, '$.target_entity_types') IS NULL "
        " OR EXISTS (SELECT 1 FROM json_each("
        "    json_extract(predicate_json, '$.target_entity_types')"
        " ) WHERE value IN (" + placeholders + ")))"
    )
    return sql, list(candidates)


def _industry_predicate_filter_sql(industry_jsic: str) -> tuple[str, list[str]]:
    """Filter on `$.industries_jsic`. Same pattern: row passes if it has
    no industries_jsic key OR if the array contains the given letter.
    """
    sql = (
        "(json_extract(predicate_json, '$.industries_jsic') IS NULL "
        " OR EXISTS (SELECT 1 FROM json_each("
        "    json_extract(predicate_json, '$.industries_jsic')"
        " ) WHERE value = ?))"
    )
    return sql, [industry_jsic]


def _mark_envelope_v2_served(request: Request) -> None:
    with contextlib.suppress(Exception):
        request.state.envelope_v2_served = True


# ---------------------------------------------------------------------------
# Route 1 — programs by corporate form (× optional industry).
# ---------------------------------------------------------------------------


@router.get(
    "/by_corporate_form",
    summary="Programs filtered by 法人格 (× optional JSIC industry)",
    description=(
        "Returns up to `limit` programs whose extracted eligibility "
        "predicate matches the given 法人格 (株式会社 / 合同会社 / NPO / "
        "一般社団 / 公益社団 / 学校 / 医療 / 個人事業主 等). "
        "Optionally further filters by JSIC major-letter axis (A-T).\n\n"
        "**Match semantics:** a program passes when its predicate "
        "`$.target_entity_types` array contains a value compatible with "
        "the form OR when the predicate carries NO entity-type filter at "
        "all (treated as 'open to any 法人格'). The same logic applies to "
        "`$.industries_jsic` when `industry_jsic` is supplied.\n\n"
        "**Pricing:** ¥3/call (1 unit), regardless of result count. "
        "Anonymous callers share the 3/日 per-IP cap (JST 翌日 00:00 リセット).\n\n"
        "**§52 envelope:** every 2xx body carries `_disclaimer` (税理士法 §52 "
        "fence) + `_form_caveat` (predicate-axis precision note). LLM "
        "relays must surface both verbatim."
    ),
    responses={
        200: {
            "description": (
                "List envelope. `applied_filters` echoes the resolved "
                "form code + JP label + JSIC letter; `programs` is the "
                "filtered list (each row carries `unified_id`, "
                "`primary_name`, `tier`, `prefecture`, `program_kind`, "
                "`amount_max_man_yen`, `source_url`, "
                "`predicate_target_entity_types`, `predicate_industries_jsic`)."
            )
        },
        422: {
            "description": (
                "form must be a recognised short code or JP label "
                "(株式会社 / 合同会社 / NPO 等) OR industry_jsic must "
                "match `^[A-T]$`."
            )
        },
        503: {"description": "autonomath.db unreachable (partial deploy)."},
    },
)
def list_programs_by_corporate_form(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    form: Annotated[
        str,
        Query(
            min_length=1,
            max_length=64,
            description=(
                "法人格. Accepts URL-safe short code (`kabushiki` / "
                "`goudou` / `npo` / `ippan_shadan` / `school` / `medical` / "
                "`sole` / ...) OR Japanese label (`株式会社` / `合同会社` / "
                "`NPO法人` / `一般社団法人` / `学校法人` / `医療法人` / "
                "`個人事業主` 等)."
            ),
            examples=["goudou", "株式会社", "npo", "school"],
        ),
    ],
    industry_jsic: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=1,
            pattern=r"^[A-T]$",
            description=("Optional JSIC 大分類 1-letter axis (A=農業..T=分類不能)."),
            examples=["D", "P"],
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=_MAX_LIMIT,
            description=f"Per-call cap (default {_DEFAULT_LIMIT}, max {_MAX_LIMIT}).",
        ),
    ] = _DEFAULT_LIMIT,
) -> JSONResponse:
    """Programs eligible for the given 法人格 (× optional JSIC).

    Joins ``am_program_eligibility_predicate_json`` with ``programs`` on
    ``unified_id`` so we can return both the predicate axis evidence and
    the human-readable program metadata in one shot.
    """
    _t0 = time.perf_counter()

    form_code = _normalize_form(form)
    if form_code is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            (
                "form must be one of: "
                + ", ".join(sorted(_CODE_TO_LABEL.keys()))
                + " (or the matching JP label)."
            ),
        )

    if industry_jsic is not None and not _JSIC_MAJOR_RE.match(industry_jsic):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "industry_jsic must match '^[A-T]$' (1 letter, uppercase).",
        )

    am_conn = _open_autonomath_ro()
    if am_conn is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "autonomath.db unavailable",
        )

    try:
        form_sql, form_args = _form_predicate_filter_sql(form_code)
        clauses: list[str] = [form_sql]
        bind_args: list[Any] = list(form_args)
        if industry_jsic is not None:
            ind_sql, ind_args = _industry_predicate_filter_sql(industry_jsic)
            clauses.append(ind_sql)
            bind_args.extend(ind_args)
        where_sql = " AND ".join(clauses)

        # We LEFT JOIN programs because:
        #  (a) `programs` may live in jpintel.db, not autonomath.db; the
        #      legacy single-DB build of autonomath.db has an empty stub.
        #      `attached?` lookup would force a cross-DB ATTACH which the
        #      project bans (CLAUDE.md "no ATTACH / cross-DB JOIN").
        #  (b) when the program row is absent, we still surface the
        #      predicate-side evidence (unified_id + the matched axis) so
        #      callers can follow up with /v1/programs/{unified_id}.
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
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"autonomath.db query failed: {exc}",
            ) from exc

        # Hydrate `programs` metadata from the local jpintel.db connection
        # (DbDep). Best-effort: if a program_id is not present in jpintel.db
        # (mismatched snapshots) we just leave the metadata fields null.
        unified_ids = [r["unified_id"] for r in rows if r["unified_id"]]
        meta: dict[str, dict[str, Any]] = {}
        if unified_ids:
            placeholders = ", ".join("?" for _ in unified_ids)
            try:
                meta_rows = conn.execute(
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

        programs_out: list[dict[str, Any]] = []
        for r in rows:
            uid = r["unified_id"]
            m = meta.get(uid, {})
            # `predicate_target_entity_types` round-trips as a JSON string;
            # parse it so callers don't have to.
            try:
                tet = (
                    json.loads(r["predicate_target_entity_types"])
                    if r["predicate_target_entity_types"]
                    else None
                )
            except (TypeError, json.JSONDecodeError):
                tet = None
            try:
                ind = (
                    json.loads(r["predicate_industries_jsic"])
                    if r["predicate_industries_jsic"]
                    else None
                )
            except (TypeError, json.JSONDecodeError):
                ind = None
            try:
                pref_arr = (
                    json.loads(r["predicate_prefectures"]) if r["predicate_prefectures"] else None
                )
            except (TypeError, json.JSONDecodeError):
                pref_arr = None
            try:
                purp_arr = (
                    json.loads(r["predicate_funding_purposes"])
                    if r["predicate_funding_purposes"]
                    else None
                )
            except (TypeError, json.JSONDecodeError):
                purp_arr = None

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
                    "predicate_target_entity_types": tet,
                    "predicate_industries_jsic": ind,
                    "predicate_prefectures": pref_arr,
                    "predicate_funding_purposes": purp_arr,
                    "predicate_confidence": r["predicate_confidence"],
                    "predicate_extraction_method": r["predicate_extraction_method"],
                }
            )
    finally:
        am_conn.close()

    body: dict[str, Any] = {
        "applied_filters": {
            "form_code": form_code,
            "form_label": _CODE_TO_LABEL[form_code],
            "form_entity_class": _CODE_TO_CLASS[form_code],
            "industry_jsic": industry_jsic,
            "limit": int(limit),
        },
        "programs": programs_out,
        "count": len(programs_out),
        "_disclaimer": _DISCLAIMER,
        "_form_caveat": _FORM_CAVEAT,
    }

    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "programs.by_corporate_form",
        latency_ms=_latency_ms,
        params={"form": form_code, "industry_jsic": industry_jsic},
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="programs.by_corporate_form",
        request_params={"form": form_code, "industry_jsic": industry_jsic},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    if wants_envelope_v2(request):
        _mark_envelope_v2_served(request)
        env = StandardResponse.sparse(
            programs_out,
            request_id=safe_request_id(request),
            citations=[],
            query_echo={
                "normalized_input": {
                    "form": form_code,
                    "industry_jsic": industry_jsic,
                },
                "applied_filters": body["applied_filters"],
                "unparsed_terms": [],
            },
            latency_ms=_latency_ms,
            billable_units=1,
            client_tag=getattr(request.state, "client_tag", None),
        )
        return JSONResponse(
            content=env.to_wire(),
            headers={"X-Envelope-Version": "v2"},
        )
    return JSONResponse(content=body)


# ---------------------------------------------------------------------------
# Route 2 — eligibility-by-form matrix for one program.
# ---------------------------------------------------------------------------


_UNIFIED_ID_RE = re.compile(r"^UNI-[0-9a-f]{10}$")


def _classify_form_against_predicate(
    form_code: str, predicate_target_entity_types: list[str] | None
) -> tuple[str, str]:
    """Return ``(verdict, reason)`` for one form against one program's
    predicate ``target_entity_types`` array.

    Verdict semantics
    -----------------
    * ``allowed``      — predicate either lists no entity-type filter
                         (universally open) OR explicitly contains a
                         compatible value for this form.
    * ``not_allowed``  — predicate has a target_entity_types list AND
                         none of its values are compatible with this form.
    * ``unspecified``  — caller code path never reaches here (kept for
                         forward compatibility with future signal sources).
    """
    if predicate_target_entity_types is None:
        return (
            "allowed",
            "predicate に target_entity_types 制約が無いため全法人格を許容",
        )
    candidates = set(_FORM_TO_PREDICATE_VALUES[form_code])
    matched = [v for v in predicate_target_entity_types if v in candidates]
    if matched:
        return (
            "allowed",
            "predicate の target_entity_types が " + "/".join(matched) + " を含む",
        )
    return (
        "not_allowed",
        (
            "predicate の target_entity_types は "
            + "/".join(predicate_target_entity_types)
            + " のみを対象としており、本法人格は含まれない"
        ),
    )


@router.get(
    "/{unified_id}/eligibility_by_form",
    summary="Per-program 法人格 eligibility matrix",
    description=(
        "Returns the explicit form-by-form eligibility verdict for a "
        "single program: for each of the supported 法人格 codes (15 axes "
        "covering 株式会社 / 合同会社 / 合資会社 / 合名会社 / NPO / "
        "一般社団 / 公益社団 / 一般財団 / 公益財団 / 学校 / 医療 / "
        "事業協同組合 / 個人事業主 / 個人 / 外国法人), the response "
        "states `allowed` / `not_allowed` plus a reason citing the "
        "predicate field that drove the verdict.\n\n"
        "**Pricing:** ¥3/call (1 unit). Anonymous callers share the "
        "3/日 per-IP cap.\n\n"
        "**§52 envelope:** every 2xx body carries `_disclaimer` "
        "(税理士法 §52 fence) + `_form_caveat` (predicate-axis precision)."
    ),
    responses={
        200: {
            "description": (
                "Eligibility matrix. `matrix` is keyed by form code; each "
                "entry carries `label`, `entity_class`, `verdict`, "
                "`reason`. `predicate_target_entity_types` echoes the raw "
                "predicate input so callers can audit the reasoning."
            )
        },
        404: {"description": "no predicate row for this unified_id"},
        422: {"description": "unified_id must match '^UNI-[0-9a-f]{10}$'"},
        503: {"description": "autonomath.db unreachable"},
    },
)
def get_program_eligibility_by_form(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    unified_id: Annotated[
        str,
        PathParam(
            min_length=14,
            max_length=14,
            pattern=r"^UNI-[0-9a-f]{10}$",
            description="Stable program unified_id (UNI-<10 hex>).",
            examples=["UNI-000780f85e"],
        ),
    ],
) -> JSONResponse:
    _t0 = time.perf_counter()

    if not _UNIFIED_ID_RE.match(unified_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "unified_id must match '^UNI-[0-9a-f]{10}$'",
        )

    am_conn = _open_autonomath_ro()
    if am_conn is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "autonomath.db unavailable",
        )

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
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"autonomath.db query failed: {exc}",
            ) from exc
    finally:
        am_conn.close()

    if row is None:
        if wants_envelope_v2(request):
            _mark_envelope_v2_served(request)
            err = StandardError.not_found(
                "program_predicate",
                unified_id,
                developer_message=(
                    "no predicate row for this unified_id; the program "
                    "may exist in `programs` but its eligibility predicate "
                    "has not been extracted yet."
                ),
            )
            env = StandardResponse.from_error(
                err,
                request_id=safe_request_id(request),
                query_echo={
                    "normalized_input": {"unified_id": unified_id},
                    "applied_filters": {"unified_id": unified_id},
                    "unparsed_terms": [],
                },
                billable_units=0,
            )
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content=env.to_wire(),
                headers={"X-Envelope-Version": "v2"},
            )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "detail": (
                    "no predicate row for this unified_id; the program "
                    "may exist in `programs` but its eligibility predicate "
                    "has not been extracted yet."
                ),
                "unified_id": unified_id,
                "_disclaimer": _DISCLAIMER,
                "_form_caveat": _FORM_CAVEAT,
            },
        )

    try:
        predicate = json.loads(row["predicate_json"]) if row["predicate_json"] else {}
    except (TypeError, json.JSONDecodeError):
        predicate = {}
    target_entity_types: list[str] | None = predicate.get("target_entity_types")
    if target_entity_types is not None and not isinstance(target_entity_types, list):
        target_entity_types = None  # malformed corpus row — degrade to 'open'

    matrix: dict[str, dict[str, Any]] = {}
    for code, label, cls in _CORPORATE_FORMS:
        verdict, reason = _classify_form_against_predicate(code, target_entity_types)
        matrix[code] = {
            "label": label,
            "entity_class": cls,
            "verdict": verdict,
            "reason": reason,
        }

    # Hydrate the program-side metadata for caller convenience (best-effort).
    program_meta: dict[str, Any] = {}
    try:
        meta_row = conn.execute(
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

    body: dict[str, Any] = {
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
    }

    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "programs.eligibility_by_form",
        latency_ms=_latency_ms,
        params={"unified_id": unified_id},
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="programs.eligibility_by_form",
        request_params={"unified_id": unified_id},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    if wants_envelope_v2(request):
        _mark_envelope_v2_served(request)
        env = StandardResponse.sparse(
            [body],
            request_id=safe_request_id(request),
            citations=[],
            query_echo={
                "normalized_input": {"unified_id": unified_id},
                "applied_filters": {"unified_id": unified_id},
                "unparsed_terms": [],
            },
            latency_ms=_latency_ms,
            billable_units=1,
            client_tag=getattr(request.state, "client_tag", None),
        )
        return JSONResponse(
            content=env.to_wire(),
            headers={"X-Envelope-Version": "v2"},
        )
    return JSONResponse(content=body)
