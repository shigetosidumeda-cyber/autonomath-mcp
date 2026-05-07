"""REST handlers for the 会計士・監査法人 work-paper bundle.

This router is the **audit-firm productisation** layer on top of the existing
``/v1/tax_rulesets/evaluate`` engine. It wraps four jobs that an auditor
would otherwise stitch together by hand from the underlying single-row
endpoints:

1. ``POST /v1/audit/workpaper`` — per-client audit work-paper render
   (CSV / PDF / Markdown / DOCX). Bundles ruleset evaluation + cite-chain
   resolution + corpus snapshot pin into a single signed-URL artefact the
   auditor can attach to the engagement file. PDF output is rendered via
   WeasyPrint (Jinja2 template) when the dep is available — the
   hand-rolled PDF1.4 renderer is the fallback for hosts where WeasyPrint
   is not installed. Successful WeasyPrint renders are cached to
   ``data/workpapers/{api_key_id}_{period}.pdf`` so a re-pull within the
   same audit period is read-from-disk, not re-rendered, and not re-metered.
2. ``POST /v1/audit/batch_evaluate`` — batch evaluation across an audit
   firm's client population (≤5,000 profiles × ≤100 rulesets per request)
   with population-deviation anomaly flags AND the 会計士-specific
   ``kaikei_fields`` rollup (調書記載要否 / 重要性閾値 / 監査リスク評価)
   per (profile, ruleset) cell, derived from the deterministic evaluation
   shape.
3. ``GET  /v1/audit/cite_chain/{ruleset_id}`` — auto-resolves the full
   citation chain for one tax_ruleset: ruleset → 法令 article → 通達 →
   質疑応答 → 文書回答. Returns a structured provenance graph the auditor
   pastes verbatim into the audit trail.
4. ``GET  /v1/audit/snapshot_attestation`` — yearly PDF carrying Bookyou
   印 + 法人番号 + daily corpus_snapshot_id + checksum log, for the audit
   firm's working-paper retention obligation (公認会計士法 §47条の2 監査
   調書保存).

§52 + 公認会計士法 §47条の2 fence
---------------------------------
This bundle is **NOT** a substitute for 監査意見の根拠資料 — it is **input
material** the auditor consults alongside their own procedures. Every
artefact (PDF cover page, every page footer, JSON envelope, attestation
certificate) carries the same boundary disclaimer:

    "本書は監査意見の根拠資料、 監査意見の代替ではない。 監査人は本書の内容を
    自らの責任において検証し、 公認会計士法 §47条の2 に従って監査調書を保存
    すること。 税理士法 §52 / 公認会計士法 §47条の2 / §52 ・ §53。"

Brand
-----
jpcite / Bookyou株式会社 / T8010001213708 / info@bookyou.net.

Architecture
------------
The handlers do not call any LLM (no Anthropic / OpenAI / etc.) — every
operation is a pure SQL + template render. The work-paper PDF is built from
the already-evaluated ``EvaluateResult`` rows produced by
``tax_rulesets._evaluate_ruleset`` plus citation resolution from
``laws`` and ``court_decisions`` tables.

Billing
-------
* ``/audit/workpaper``: ``len(target_ruleset_ids) × ¥3 + ¥30 export fixed
  fee`` reported as ``quantity=N+10`` to Stripe (¥3/unit metering).
* ``/audit/batch_evaluate``: ``len(profiles) × len(target_ruleset_ids) ÷ K``
  with ``K=10`` so a 5,000 × 100 = 500,000 evaluation grid bills as 50,000
  units (¥150,000) instead of a runaway ¥1,500,000.
* ``/audit/snapshot_attestation``: fixed ¥30,000 reported as
  ``quantity=10000``. Yearly call cadence; not metered per attribute.

ToS §15 cap auto-scaling — see ``docs/compliance/audit_firm_economics.md``.
The §15 cap is the customer's monthly spend ceiling (前12月支払総額 baseline)
which auto-scales as the firm's billable activity rises; bundle adoption
does not require a contract amendment.
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import logging
import re
import sqlite3
import threading
import time
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._corpus_snapshot import (
    attach_corpus_snapshot,
    compute_corpus_snapshot,
    snapshot_headers,
)
from jpintel_mcp.api._error_envelope import (
    COMMON_ERROR_RESPONSES,
)
from jpintel_mcp.api.cost_cap_guard import require_cost_cap
from jpintel_mcp.api.deps import (
    ApiContext,
    ApiContextDep,
    DbDep,
    log_usage,
    require_metered_api_key,
)
from jpintel_mcp.api.idempotency_context import (
    billing_event_index,
    billing_idempotency_key,
)
from jpintel_mcp.api.middleware.cost_cap import record_cost_cap_spend
from jpintel_mcp.api.middleware.idempotency import (
    _check_or_record_body_fingerprint,
    _compute_collision_key,
)
from jpintel_mcp.api.tax_rulesets import (
    _UNIFIED_ID_RE as _TAX_UNIFIED_ID_RE,
)
from jpintel_mcp.api.tax_rulesets import (
    _evaluate_ruleset,
    resolve_citation_tree,
)
from jpintel_mcp.config import settings

_log = logging.getLogger("jpintel.api.audit")

router = APIRouter(prefix="/v1/audit", tags=["audit (会計士・監査法人)"])

# Public seal verifier mounted WITHOUT AnonIpLimitDep so a customer can
# always verify a paid seal — even after the 3/day anonymous quota is
# burned. Verification is read-only on a hash-only row, billable=0; the
# DDOS surface is the same as any cached static doc and is left to the
# upstream Cloudflare layer.
public_router = APIRouter(prefix="/v1/audit", tags=["audit (会計士・監査法人)"])


# ---------------------------------------------------------------------------
# §52 + 公認会計士法 §47条の2 envelope (rendered onto every response, every
# PDF cover page, every page footer, every CSV header line, every Markdown
# title block). The wording is INTENTIONALLY duplicated across surfaces so
# an auditor cross-examined on the bundle cannot be surprised by a missing
# disclaimer in any single delivery channel.
# ---------------------------------------------------------------------------

_AUDIT_DISCLAIMER = (
    "本書は監査意見の根拠資料、 監査意見の代替ではない。 監査人は本書の内容を"
    "自らの責任において検証し、 公認会計士法 §47条の2 に従って監査調書を保存"
    "すること。 本サービスは公的機関が公表する税制・補助金・法令情報を検索"
    "整理して提供するもので、 税理士法 §52 に基づき個別具体的な税務判断・申告"
    "書作成代行は行わず、 公認会計士法 §47条の2 に基づき監査業務の代替も行わ"
    "ない。 個別案件は資格を有する税理士・公認会計士に必ずご相談ください。"
)

_AUDIT_DISCLAIMER_EN = (
    "This document is INPUT MATERIAL for audit work, NOT a substitute for "
    "the auditor's opinion or working papers. The auditor is responsible "
    "for verifying contents and retaining working papers under CPA Act "
    "§47-2. jpcite provides retrieval over public Japanese tax / "
    "subsidy / law sources only — not tax advice (Tax Accountants Act §52) "
    "and not audit work substitution (CPA Act §47-2)."
)

# Brand block injected into PDF cover + Markdown titles + CSV headers.
_BRAND = {
    "service_name": "jpcite",
    "operator_legal_name": "Bookyou株式会社",
    "houjin_bangou": "T8010001213708",
    "operator_email": "info@bookyou.net",
    "operator_url": "https://jpcite.com",
}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


_REPORT_FORMATS = ("csv", "pdf", "md", "docx")
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9._:\\-]{1,128}$")


class WorkpaperRequest(BaseModel):
    """POST /v1/audit/workpaper input.

    A single client + their business profile + the rulesets the auditor
    wants evaluated. Produces a downloadable artefact (CSV / PDF / MD /
    DOCX) plus structured JSON suitable for paste-into-engagement-system.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: Annotated[
        str,
        Field(
            description=(
                "Audit firm's internal client identifier. Echoed back in "
                "the work-paper header. NEVER 法人番号 or other PII — the "
                "auditor controls the namespace. ASCII only, ≤128 chars."
            ),
            min_length=1,
            max_length=128,
        ),
    ]
    target_ruleset_ids: Annotated[
        list[str],
        Field(
            description=(
                "List of TAX-<10hex> ids to evaluate. Order is preserved "
                "in the work-paper. Cap: 100."
            ),
            min_length=1,
            max_length=100,
        ),
    ]
    business_profile: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Client's business attribute bag — same shape as ``/v1/tax_rulesets/evaluate``."
            ),
        ),
    ]
    report_format: Annotated[
        str,
        Field(
            description="Output format. One of: csv | pdf | md | docx.",
            min_length=2,
            max_length=4,
        ),
    ] = "pdf"
    audit_period: Annotated[
        str | None,
        Field(
            description=(
                "Audit period token (used as cache key + cover-page label). "
                "Accepts ``YYYY`` / ``YYYY-Q1..Q4`` / ``YYYY-MM``. "
                "Falls back to the current calendar year when omitted. "
                "PDF outputs are cached to "
                "``data/workpapers/{api_key_id}_{audit_period}.pdf`` so a "
                "re-pull within the same period is read-from-disk and "
                "NOT re-metered."
            ),
            min_length=1,
            max_length=16,
        ),
    ] = None
    max_cost_jpy: Annotated[
        int | None,
        Field(
            description=(
                "Optional per-request budget cap in JPY. Equivalent to "
                "X-Cost-Cap-JPY; the lower of header/body caps binds."
            ),
            ge=0,
        ),
    ] = None


class BatchProfileItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: Annotated[str, Field(min_length=1, max_length=128)]
    profile: dict[str, Any]


class BatchEvaluateRequest(BaseModel):
    """POST /v1/audit/batch_evaluate input."""

    model_config = ConfigDict(extra="forbid")

    audit_firm_id: Annotated[
        str,
        Field(
            description=(
                "Audit firm's own identifier (echoed back; reporting "
                "convenience). ASCII ≤128 chars. NOT used for auth — auth "
                "is the X-API-Key on the request."
            ),
            min_length=1,
            max_length=128,
        ),
    ]
    profiles: Annotated[
        list[BatchProfileItem],
        Field(
            description=("Per-client business profiles. Cap: 5,000. Order preserved in results."),
            min_length=1,
            max_length=5000,
        ),
    ]
    target_ruleset_ids: Annotated[
        list[str],
        Field(
            description=("TAX-<10hex> ids to evaluate against EVERY profile. Cap: 100."),
            min_length=1,
            max_length=100,
        ),
    ]
    max_cost_jpy: Annotated[
        int | None,
        Field(
            description=(
                "Optional per-request budget cap in JPY. Equivalent to "
                "X-Cost-Cap-JPY; the lower of header/body caps binds."
            ),
            ge=0,
        ),
    ] = None


# ---------------------------------------------------------------------------
# Billing helpers
# ---------------------------------------------------------------------------

# Fan-out factor for batch_evaluate. K=10 means 10 evaluations bill as 1
# unit (= ¥3). Documented in docs/compliance/audit_firm_economics.md so
# the auditor can pre-compute spend before hitting the endpoint.
_BATCH_K = 10

# Fixed export fee in ¥3 units. ¥30 = 10 units. Same convention used by the
# M&A audit_bundle endpoint (per spec).
_WORKPAPER_EXPORT_UNITS = 10

# Fixed snapshot attestation fee in ¥3 units. ¥30,000 = 10,000 units.
_SNAPSHOT_ATTESTATION_UNITS = 10_000


def _require_high_value_idempotency_key(raw: str | None) -> str:
    if raw is None or not raw.strip():
        raise HTTPException(
            status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "code": "idempotency_key_required",
                "message": (
                    "Idempotency-Key is required for this high-value paid "
                    "artifact so retries cannot double bill."
                ),
            },
        )
    return raw.strip()


def _snapshot_attestation_idempotency_response(
    conn: sqlite3.Connection, ctx: ApiContext, idem_key: str, year: int
) -> JSONResponse | None:
    """Reject reused GET Idempotency-Key values with a different query."""

    if not ctx.key_hash:
        return JSONResponse(
            content={
                "error": "idempotency_cache_unavailable",
                "detail": "retry later",
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"X-Metered": "false", "X-Cost-Yen": "0", "Retry-After": "1"},
        )
    fingerprint_payload = json.dumps(
        {"year": year},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    collision_key = _compute_collision_key(
        ctx.key_hash,
        "/v1/audit/snapshot_attestation",
        idem_key,
    )
    state, _seen_fp = _check_or_record_body_fingerprint(
        conn,
        collision_key,
        hashlib.sha256(fingerprint_payload).hexdigest(),
    )
    if state == "mismatch":
        return JSONResponse(
            content={
                "error": "idempotency_key_in_use",
                "detail": (
                    "Idempotency-Key was previously seen with a different "
                    "snapshot_attestation query. Use a fresh key for a new request."
                ),
            },
            status_code=status.HTTP_409_CONFLICT,
            headers={"X-Metered": "false", "X-Cost-Yen": "0"},
        )
    if state in {"busy", "unavailable"}:
        return JSONResponse(
            content={
                "error": (
                    "idempotency_cache_busy" if state == "busy" else "idempotency_cache_unavailable"
                ),
                "detail": "retry later",
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"X-Metered": "false", "X-Cost-Yen": "0", "Retry-After": "1"},
        )
    return None


def _non_metered_context(ctx: ApiContext) -> ApiContext:
    """Return a same-key context that records usage without Stripe billing."""
    return ApiContext(
        key_hash=ctx.key_hash,
        tier="free",
        customer_id=ctx.customer_id,
        stripe_subscription_id=None,
        key_id=ctx.key_id,
        parent_key_id=ctx.parent_key_id,
    )


def _usage_context_for_units(ctx: ApiContext, units: int) -> ApiContext:
    """Use a non-metered row for explicitly free cache hits."""
    if units <= 0:
        return _non_metered_context(ctx)
    return ctx


def _projected_cap_response(
    conn: sqlite3.Connection,
    ctx: ApiContext,
    units: int,
) -> JSONResponse | None:
    """Run the same multi-unit cap gate used by other batch endpoints."""
    if units <= 0:
        return None
    from jpintel_mcp.api.middleware.customer_cap import (
        projected_monthly_cap_response,
    )

    return projected_monthly_cap_response(conn, ctx.key_hash, units)


# ---------------------------------------------------------------------------
# Citation tree resolution + cite-chain caching
# ---------------------------------------------------------------------------

# Process-local LRU for citation lookups. We cache a small set
# (citation_id → resolved row) and not the full tree because rulesets
# frequently re-cite a small library of statutes.
_CITE_CACHE: dict[str, dict[str, Any]] = {}
_CITE_CACHE_MAX = 4096


def _cache_citation(cite_id: str, payload: dict[str, Any]) -> None:
    if len(_CITE_CACHE) >= _CITE_CACHE_MAX:
        # Cheap eviction: drop a deterministic 16th of the cache. Process
        # restart frequency is daily; this never grows unbounded.
        for k in list(_CITE_CACHE.keys())[: _CITE_CACHE_MAX // 16]:
            _CITE_CACHE.pop(k, None)
    _CITE_CACHE[cite_id] = payload


def _lookup_citation(conn: sqlite3.Connection, cite_id: str) -> dict[str, Any]:
    """Resolve one citation id (LAW-... / HAN-... / TSUTATSU-... / SAI-...)
    to a structured dict.

    Returns a stub ``{cite_id, status: "unresolved"}`` when the underlying
    table / row does not exist (e.g. 通達 / 裁決 not yet ingested). NEVER
    raises — the work-paper must render even with partial coverage.
    """
    if cite_id in _CITE_CACHE:
        return _CITE_CACHE[cite_id]

    payload: dict[str, Any] = {"cite_id": cite_id, "status": "unresolved"}

    if cite_id.startswith("LAW-"):
        try:
            row = conn.execute(
                "SELECT unified_id, law_title, law_short_title, law_number, "
                "ministry, full_text_url, source_url FROM laws "
                "WHERE unified_id = ?",
                (cite_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        if row is not None:
            payload = {
                "cite_id": row["unified_id"],
                "kind": "law",
                "title": row["law_title"],
                "short_title": row["law_short_title"],
                "law_number": row["law_number"],
                "ministry": row["ministry"],
                "url": row["full_text_url"] or row["source_url"],
                "status": "resolved",
            }
    elif cite_id.startswith("HAN-"):
        try:
            row = conn.execute(
                "SELECT unified_id, case_name, case_number, court, "
                "decision_date, precedent_weight, full_text_url, source_url "
                "FROM court_decisions WHERE unified_id = ?",
                (cite_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        if row is not None:
            payload = {
                "cite_id": row["unified_id"],
                "kind": "court_decision",
                "title": row["case_name"],
                "case_number": row["case_number"],
                "court": row["court"],
                "decision_date": row["decision_date"],
                "precedent_weight": row["precedent_weight"],
                "url": row["full_text_url"] or row["source_url"],
                "status": "resolved",
            }
    elif cite_id.startswith("TSUTATSU-"):
        # 通達 — resolve via nta_tsutatsu_index in autonomath.db (migration
        # 103). The cite_id strips the "TSUTATSU-" prefix to match the
        # `code` column in the index (e.g. TSUTATSU-法基通-9-2-3 →
        # "法基通-9-2-3"). Falls through to a stub when autonomath.db is
        # not attached / the row is missing — never raises so the
        # work-paper still renders on a partial corpus.
        code = cite_id.removeprefix("TSUTATSU-")
        row = _nta_tsutatsu_lookup(code)
        if row is not None:
            payload = {
                "cite_id": cite_id,
                "kind": "tsutatsu",
                "title": row.get("title"),
                "law_canonical_id": row.get("law_canonical_id"),
                "article_number": row.get("article_number"),
                "url": row.get("source_url"),
                "status": "resolved",
            }
        else:
            payload = {
                "cite_id": cite_id,
                "kind": "tsutatsu",
                "status": "unresolved_pending_ingestion",
                "title": None,
                "url": None,
            }
    elif cite_id.startswith("QA-") or cite_id.startswith("SHITSUGI-"):
        # 質疑応答事例 — resolve via nta_shitsugi.slug in autonomath.db.
        slug = cite_id.split("-", 1)[1] if "-" in cite_id else cite_id
        row = _nta_shitsugi_lookup(slug)
        if row is not None:
            payload = {
                "cite_id": cite_id,
                "kind": "shitsugi",
                "title": (row.get("question") or "").strip()[:140],
                "category": row.get("category"),
                "url": row.get("source_url"),
                "status": "resolved",
            }
        else:
            payload = {
                "cite_id": cite_id,
                "kind": "shitsugi",
                "status": "unresolved",
                "title": None,
                "url": None,
            }
    elif cite_id.startswith("BUNSHO-") or cite_id.startswith("BUNSHOKAITOU-"):
        # 文書回答事例 — nta_bunsho_kaitou.slug in autonomath.db.
        slug = cite_id.split("-", 1)[1] if "-" in cite_id else cite_id
        row = _nta_bunsho_lookup(slug)
        if row is not None:
            payload = {
                "cite_id": cite_id,
                "kind": "bunsho_kaitou",
                "title": (row.get("request_summary") or "").strip()[:140],
                "category": row.get("category"),
                "url": row.get("source_url"),
                "status": "resolved",
            }
        else:
            payload = {
                "cite_id": cite_id,
                "kind": "bunsho_kaitou",
                "status": "unresolved",
                "title": None,
                "url": None,
            }
    elif cite_id.startswith("SAI-"):
        # 裁決 (国税不服審判所) — same posture as TSUTATSU above.
        payload = {
            "cite_id": cite_id,
            "kind": "saiketsu",
            "status": "unresolved_pending_ingestion",
            "title": None,
            "url": None,
        }
    elif cite_id.startswith("PENDING:"):
        # Free-text PENDING markers in tax_rulesets.related_law_ids_json
        # (e.g. "PENDING:消費税法第30条"). Surface as unresolved; the human
        # text is the only signal we have until the law catalog is filled.
        payload = {
            "cite_id": cite_id,
            "kind": "pending",
            "title": cite_id.split(":", 1)[1] if ":" in cite_id else cite_id,
            "status": "unresolved_pending_text_match",
            "url": None,
        }

    _cache_citation(cite_id, payload)
    return payload


# ---------------------------------------------------------------------------
# NTA corpus (autonomath.db) lookups for cite-chain auto-resolution.
#
# tax_rulesets, laws, and court_decisions live in jpintel.db. The NTA primary-
# source corpus (通達 / 質疑応答 / 文書回答) lives in autonomath.db (migration
# 103). The audit endpoints only need read-only access; we keep one
# per-process connection cached in ``_NTA_CONN`` and reopen on transient
# loss. Failures degrade silently — workpaper / cite_chain still render
# with the resolvable subset.
# ---------------------------------------------------------------------------


_NTA_LOCAL = threading.local()


def _nta_open() -> sqlite3.Connection | None:
    """Open (or reuse) a read-only autonomath.db connection.

    Returns None when autonomath.db is unavailable (test envs, missing
    file, schema_guard reject, etc.). Callers must tolerate None.
    """
    cached = getattr(_NTA_LOCAL, "conn", None)
    if cached is not None:
        from typing import cast as _cast

        return _cast("sqlite3.Connection | None", cached)
    try:
        from jpintel_mcp.mcp.autonomath_tools.db import (
            AUTONOMATH_DB_PATH,
            connect_autonomath,
        )

        if not AUTONOMATH_DB_PATH.exists():
            return None
        conn = connect_autonomath()
        _NTA_LOCAL.conn = conn
        return conn
    except Exception:  # noqa: BLE001
        return None


def _nta_tsutatsu_lookup(code: str) -> dict[str, Any] | None:
    """Resolve one 通達 code (e.g. '法基通-9-2-3') via nta_tsutatsu_index."""
    conn = _nta_open()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT code, law_canonical_id, article_number, title, "
            "body_excerpt, parent_code, source_url, last_amended "
            "FROM nta_tsutatsu_index WHERE code = ?",
            (code,),
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return dict(row)


def _nta_shitsugi_lookup(slug: str) -> dict[str, Any] | None:
    """Resolve one 質疑応答事例 slug via nta_shitsugi."""
    conn = _nta_open()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT slug, category, question, answer, related_law, source_url "
            "FROM nta_shitsugi WHERE slug = ?",
            (slug,),
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return dict(row)


def _nta_bunsho_lookup(slug: str) -> dict[str, Any] | None:
    """Resolve one 文書回答事例 slug via nta_bunsho_kaitou."""
    conn = _nta_open()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT slug, category, response_date, request_summary, answer, "
            "source_url FROM nta_bunsho_kaitou WHERE slug = ?",
            (slug,),
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return dict(row)


def _nta_shitsugi_search_for_law(law_canonical_id: str, limit: int = 3) -> list[dict[str, Any]]:
    """Surface 質疑応答事例 whose related_law mentions a given law id.

    Used by the cite-chain auto-resolver to climb the chain from law →
    通達 → 質疑応答 → 文書回答 even when the ruleset itself does not
    explicitly name the QA. Mention is loose substring (related_law is
    free text — the NTA pages do not normalize their law references).
    """
    conn = _nta_open()
    if conn is None:
        return []
    out: list[dict[str, Any]] = []
    short = law_canonical_id.replace("law:", "").replace("LAW-", "")
    if not short:
        return out
    try:
        rows = conn.execute(
            "SELECT slug, category, question, related_law, source_url "
            "FROM nta_shitsugi WHERE related_law LIKE ? "
            "ORDER BY id ASC LIMIT ?",
            (f"%{short}%", limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    for r in rows:
        out.append(
            {
                "kind": "shitsugi",
                "slug": r["slug"],
                "category": r["category"],
                "title": (r["question"] or "").strip()[:140],
                "url": r["source_url"],
                "matched_via": "related_law substring",
            }
        )
    return out


def _nta_bunsho_search_for_law(law_canonical_id: str, limit: int = 3) -> list[dict[str, Any]]:
    """Surface 文書回答事例 whose request_summary mentions a law short id."""
    conn = _nta_open()
    if conn is None:
        return []
    out: list[dict[str, Any]] = []
    short = law_canonical_id.replace("law:", "").replace("LAW-", "")
    if not short:
        return out
    try:
        rows = conn.execute(
            "SELECT slug, category, request_summary, response_date, source_url "
            "FROM nta_bunsho_kaitou "
            "WHERE request_summary LIKE ? OR answer LIKE ? "
            "ORDER BY id ASC LIMIT ?",
            (f"%{short}%", f"%{short}%", limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    for r in rows:
        out.append(
            {
                "kind": "bunsho_kaitou",
                "slug": r["slug"],
                "category": r["category"],
                "title": (r["request_summary"] or "").strip()[:140],
                "response_date": r["response_date"],
                "url": r["source_url"],
                "matched_via": "request_summary/answer substring",
            }
        )
    return out


# ---------------------------------------------------------------------------
# Cite-chain auto-resolver (ruleset → 法令 article → 通達 → 質疑応答
# → 文書回答). Composes the existing per-id resolver into a tree the
# auditor can paste verbatim into the audit trail.
# ---------------------------------------------------------------------------


def _build_cite_chain(
    conn: sqlite3.Connection,
    ruleset_row: sqlite3.Row,
) -> dict[str, Any]:
    """Auto-resolve the full citation chain rooted at a tax_ruleset.

    Pipeline:
      1. Walk ``related_law_ids_json`` + every ``cite`` predicate value to
         the seed citation set.
      2. Resolve each id via the per-id resolver. LAW + HAN + TSUTATSU /
         QA / BUNSHO entries get filled from their canonical tables.
      3. For every resolved LAW-* row, opportunistically surface up to 3
         related 質疑応答 + 3 related 文書回答 by substring-matching the
         law id against ``related_law`` / ``request_summary`` / ``answer``
         on the NTA tables. Auditors get the full provenance graph in one
         call instead of N follow-ups.

    Output shape:
        {
          "ruleset": {"unified_id": ..., "ruleset_name": ...},
          "seed_count": <n citation ids before resolution>,
          "resolved_count": <n that hit a row>,
          "depth": <max chain depth observed>,
          "tree": [
            {
              "level": 1,
              "kind": "law" | "court_decision" | "tsutatsu" | "shitsugi"
                      | "bunsho_kaitou" | "pending" | "unknown",
              "cite_id": "LAW-...",
              "title": "...",
              "url": "...",
              "status": "resolved" | "unresolved...",
              "children": [
                {"level": 2, "kind": "shitsugi", ...},
                {"level": 2, "kind": "bunsho_kaitou", ...},
              ],
            },
            ...
          ],
        }
    """
    # Seed citation walk (mirrors tax_rulesets.resolve_citation_tree).
    cites: list[str] = []
    seen: set[str] = set()

    def _add(c: str) -> None:
        if c and c not in seen:
            seen.add(c)
            cites.append(c)

    raw_law_ids = ruleset_row["related_law_ids_json"]
    if raw_law_ids:
        try:
            parsed = json.loads(raw_law_ids)
            if isinstance(parsed, list):
                for x in parsed:
                    if isinstance(x, str):
                        _add(x)
        except json.JSONDecodeError:
            pass

    raw_pred = ruleset_row["eligibility_conditions_json"]
    if raw_pred:
        try:
            tree = json.loads(raw_pred)
        except json.JSONDecodeError:
            tree = None
        if tree is not None:
            tmp: list[str] = []

            def _walk(node: Any) -> None:
                if isinstance(node, dict):
                    cite = node.get("cite")
                    if isinstance(cite, list):
                        for c in cite:
                            if isinstance(c, str):
                                tmp.append(c)
                    of = node.get("of")
                    if of is not None:
                        _walk(of)
                elif isinstance(node, list):
                    for item in node:
                        _walk(item)

            _walk(tree)
            for c in tmp:
                _add(c)

    # Resolve each seed id.
    nodes: list[dict[str, Any]] = []
    resolved_count = 0
    max_depth = 1
    for cid in cites:
        resolved = _lookup_citation(conn, cid)
        if resolved.get("status") == "resolved":
            resolved_count += 1
        node: dict[str, Any] = {
            "level": 1,
            "kind": resolved.get("kind", "unknown"),
            "cite_id": resolved.get("cite_id", cid),
            "title": resolved.get("title"),
            "url": resolved.get("url"),
            "status": resolved.get("status", "unresolved"),
            "children": [],
        }
        # Carry through extra metadata when present (court / decision_date
        # / law_number / category) so the auditor has the same fields the
        # workpaper renders.
        for k in (
            "short_title",
            "law_number",
            "ministry",
            "case_number",
            "court",
            "decision_date",
            "precedent_weight",
            "law_canonical_id",
            "article_number",
            "category",
        ):
            if k in resolved:
                node[k] = resolved[k]

        # Climb the chain for LAW-* roots: surface related 質疑応答 +
        # 文書回答 via substring match. Only when the LAW row itself
        # resolved (otherwise we have no canonical id to substring on).
        if resolved.get("kind") == "law" and resolved.get("status") == "resolved":
            children: list[dict[str, Any]] = []
            for entry in _nta_shitsugi_search_for_law(resolved["cite_id"], limit=3):
                children.append({"level": 2, **entry})
            for entry in _nta_bunsho_search_for_law(resolved["cite_id"], limit=3):
                children.append({"level": 2, **entry})
            if children:
                node["children"] = children
                max_depth = max(max_depth, 2)

        nodes.append(node)

    rs_keys = list(ruleset_row.keys())
    return {
        "ruleset": {
            "unified_id": ruleset_row["unified_id"],
            "ruleset_name": (ruleset_row["ruleset_name"] if "ruleset_name" in rs_keys else None),
        },
        "seed_count": len(cites),
        "resolved_count": resolved_count,
        "depth": max_depth,
        "tree": nodes,
    }


# ---------------------------------------------------------------------------
# 会計士-specific evaluation rollup helpers.
#
# batch_evaluate's per-cell row carries the deterministic eligibility
# evaluation. The 会計士 walk asks for three additional heuristic flags
# the auditor pastes into 監査調書 directly:
#
#   * 調書記載要否 (workpaper_required) — Y if applicable=True OR any
#     reason mentions an exclusion (the ruleset mattered for this client).
#   * 重要性閾値 (materiality_threshold) — derived from the ruleset's
#     declared 上限金額 / pattern (¥3M / ¥30M / ¥300M tiers). Auditors
#     map this to PM (planning materiality) before fieldwork.
#   * 監査リスク評価 (audit_risk) — low / medium / high categorical based
#     on (applicable, condition match-ratio, citation density, anomaly
#     flag). Heuristic — NOT a substitute for the auditor's own RAS.
# ---------------------------------------------------------------------------


def _kaikei_workpaper_required(row: dict[str, Any]) -> bool:
    """Return True if the auditor must paper this ruleset for this client.

    Y when the ruleset is applicable, OR when there is at least one
    matched condition (ruleset is "in flight" for the client even if not
    fully applicable), OR when the ruleset's reasons reference an exclusion.
    """
    if row.get("applicable"):
        return True
    if row.get("conditions_matched"):
        return True
    reasons = row.get("reasons") or []
    for r in reasons:
        if not isinstance(r, str):
            continue
        if "除外" in r or "exclud" in r.lower() or "排他" in r:
            return True
    return False


def _kaikei_materiality_threshold(ruleset_row: sqlite3.Row | None) -> dict[str, Any]:
    """Map a tax_ruleset row to a coarse 重要性閾値 (3-tier).

    Banding:
      * tier_high  ¥300M+   — 大企業 / 法人税控除など
      * tier_mid   ¥30M+    — 中堅 / 中小企業税制
      * tier_low   ¥3M+     — 小規模・特例制度
      * tier_unknown        — when no amount field is parseable
    The threshold is heuristic (auditors override with their own PM).
    """
    if ruleset_row is None:
        return {
            "tier": "tier_unknown",
            "threshold_yen": None,
            "rationale": "ruleset row not loaded",
        }
    # Search the ruleset row for any "金額" / "上限" / "万円" hint.
    rs_keys = list(ruleset_row.keys())
    name = (ruleset_row["ruleset_name"] if "ruleset_name" in rs_keys else "") or ""
    cond_json = (
        ruleset_row["eligibility_conditions_json"]
        if "eligibility_conditions_json" in rs_keys
        else ""
    ) or ""
    blob = name + " " + cond_json
    if "300000000" in blob or "3億" in blob or "3億円" in blob or "30000万" in blob:
        return {
            "tier": "tier_high",
            "threshold_yen": 3_00_000_000,
            "rationale": "ruleset references ¥300M+ ceiling",
        }
    if "30000000" in blob or "3000万" in blob or "30000000円" in blob:
        return {
            "tier": "tier_mid",
            "threshold_yen": 30_000_000,
            "rationale": "ruleset references ¥30M ceiling",
        }
    if "3000000" in blob or "300万" in blob or "3000000円" in blob:
        return {
            "tier": "tier_low",
            "threshold_yen": 3_000_000,
            "rationale": "ruleset references ¥3M ceiling",
        }
    return {
        "tier": "tier_unknown",
        "threshold_yen": None,
        "rationale": "no parseable 上限金額 found in ruleset",
    }


def _kaikei_audit_risk(
    row: dict[str, Any],
    is_anomaly: bool,
) -> dict[str, Any]:
    """Heuristic 監査リスク評価 (low / medium / high) for one cell."""
    matched = len(row.get("conditions_matched") or [])
    unmatched = len(row.get("conditions_unmatched") or [])
    cite_count = len(row.get("citation_tree") or [])
    applicable = bool(row.get("applicable"))
    factors: list[str] = []
    score = 0
    if is_anomaly:
        score += 2
        factors.append("anomaly_flag")
    if applicable and unmatched > 0:
        score += 1
        factors.append("applicable_with_unmatched")
    if matched + unmatched >= 5:
        score += 1
        factors.append("complex_ruleset_5+_conditions")
    if cite_count >= 5:
        score += 1
        factors.append("high_cite_density_5+")
    if not applicable and matched > 0:
        score += 1
        factors.append("partial_match_non_applicable")
    if score >= 3:
        level = "high"
    elif score >= 1:
        level = "medium"
    else:
        level = "low"
    return {
        "level": level,
        "score": score,
        "factors": factors,
    }


def _kaikei_fields(
    row: dict[str, Any],
    ruleset_row: sqlite3.Row | None,
    is_anomaly: bool,
) -> dict[str, Any]:
    """Bundle the 3 会計士-specific fields onto a per-cell row."""
    return {
        "workpaper_required": _kaikei_workpaper_required(row),
        "materiality_threshold": _kaikei_materiality_threshold(ruleset_row),
        "audit_risk": _kaikei_audit_risk(row, is_anomaly),
    }


# ---------------------------------------------------------------------------
# WeasyPrint workpaper render + on-disk PDF cache.
#
# The hand-rolled PDF1.4 renderer above is the launch fallback (it produces
# valid PDF without any system dep) but cannot embed Japanese text — the
# kanji come out as `?` placeholders. WeasyPrint is the production renderer
# for human-facing audit deliverables; it also feeds the
# data/workpapers/{api_key_id}_{period}.pdf disk cache so a re-pull
# within the same audit period is read-from-disk, not re-rendered, and not
# re-metered.
# ---------------------------------------------------------------------------


_WORKPAPER_CACHE_DIR = Path("data/workpapers")


def _workpaper_template_html(
    *,
    client_id: str,
    snapshot_id: str,
    checksum: str,
    rows: list[dict[str, Any]],
    audit_period: str,
    api_key_id: str,
) -> str:
    """Build the inline HTML the WeasyPrint pipeline renders.

    Single-file template — keeps the dep surface minimal (no Jinja file in
    src/jpintel_mcp/templates/workpaper.html — the audit bundle is small
    enough that string substitution is clearer than a separate file).
    """
    # Escape helpers — every user-controlled string passes through `_esc`.
    import html as _html_mod

    def _esc(value: Any) -> str:
        return _html_mod.escape(str(value if value is not None else ""), quote=True)

    rendered_rows: list[str] = []
    for r in rows:
        cites = r.get("citation_tree") or []
        cite_html_parts: list[str] = []
        for c in cites[:8]:
            title = c.get("title") or c.get("cite_id")
            status = c.get("status", "unresolved")
            url = c.get("url") or ""
            link_html = ""
            if url:
                link_html = '<a href="' + _esc(url) + '">link</a>'
            cite_html_parts.append(
                f"<li><code>{_esc(c.get('cite_id'))}</code> — "
                f"{_esc(title)} <em>[{_esc(status)}]</em> "
                f"{link_html}"
                f"</li>"
            )
        cite_html = "<ul>" + "".join(cite_html_parts) + "</ul>" if cite_html_parts else ""
        kaikei = r.get("kaikei_fields") or {}
        kaikei_html = ""
        if kaikei:
            mat = kaikei.get("materiality_threshold") or {}
            risk = kaikei.get("audit_risk") or {}
            kaikei_html = (
                "<div class='kaikei'>"
                f"<span class='lab'>調書記載要否</span>: "
                f"<b>{'要' if kaikei.get('workpaper_required') else '不要'}</b> &nbsp; "
                f"<span class='lab'>重要性閾値</span>: "
                f"<b>{_esc(mat.get('tier'))}</b> "
                f"({_esc(mat.get('threshold_yen'))}) &nbsp; "
                f"<span class='lab'>監査リスク評価</span>: "
                f"<b>{_esc(risk.get('level'))}</b> "
                f"(score={_esc(risk.get('score'))})"
                "</div>"
            )
        rendered_rows.append(
            f"<section class='ruleset'>"
            f"<h3>{_esc(r.get('ruleset_name'))} "
            f"<span class='uid'>({_esc(r.get('unified_id'))})</span></h3>"
            f"<p>applicable=<b>{_esc(r.get('applicable'))}</b> "
            f"matched={_esc(len(r.get('conditions_matched') or []))} "
            f"unmatched={_esc(len(r.get('conditions_unmatched') or []))}</p>"
            f"{kaikei_html}"
            f"{cite_html}"
            f"</section>"
        )

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"/>
<title>{_esc(_BRAND["service_name"])} 監査ワークペーパー — {_esc(client_id)}</title>
<style>
@page {{ size: A4; margin: 18mm 16mm 24mm 16mm; @bottom-center {{
  content: "公認会計士法 §47条の2 / 税理士法 §52 — Bookyou Inc. T8010001213708";
  font-size: 7pt; color: #666;
}} }}
body {{ font-family: "Hiragino Sans", "Yu Gothic", "Noto Sans CJK JP", sans-serif;
       font-size: 9pt; color: #111; line-height: 1.45; }}
h1 {{ font-size: 14pt; margin: 0 0 4pt; }}
h2 {{ font-size: 10pt; margin: 12pt 0 4pt; border-bottom: 1px solid #888; }}
h3 {{ font-size: 10pt; margin: 8pt 0 2pt; }}
.uid {{ color: #888; font-weight: normal; }}
.cover dt {{ font-weight: bold; float: left; clear: left; width: 8em; }}
.cover dd {{ margin: 0 0 1pt 9em; }}
.kaikei {{ background: #f5f5f0; padding: 4pt 6pt; margin: 4pt 0; }}
.kaikei .lab {{ color: #555; font-size: 8pt; }}
.disclaimer {{ background: #fff8e1; padding: 6pt 8pt; margin: 6pt 0;
               border-left: 3pt solid #c2922c; font-size: 8pt; }}
ul {{ margin: 2pt 0 4pt 0; padding-left: 14pt; }}
li {{ margin: 1pt 0; }}
code {{ font-family: "Menlo", "Courier New", monospace; font-size: 8pt; }}
</style></head><body>
<h1>{_esc(_BRAND["service_name"])} 監査ワークペーパー</h1>
<p>運営: {_esc(_BRAND["operator_legal_name"])} ({_esc(_BRAND["houjin_bangou"])}) /
   contact: {_esc(_BRAND["operator_email"])}</p>

<dl class='cover'>
<dt>client_id</dt><dd><code>{_esc(client_id)}</code></dd>
<dt>audit_period</dt><dd><code>{_esc(audit_period)}</code></dd>
<dt>api_key_id</dt><dd><code>{_esc(api_key_id)}</code></dd>
<dt>corpus_snapshot_id</dt><dd><code>{_esc(snapshot_id)}</code></dd>
<dt>corpus_checksum</dt><dd><code>{_esc(checksum)}</code></dd>
<dt>generated_at_utc</dt><dd><code>{_esc(datetime.now(UTC).isoformat())}</code></dd>
</dl>

<div class='disclaimer'>
<b>境界条項 (公認会計士法 §47条の2 / 税理士法 §52)</b><br/>
{_esc(_AUDIT_DISCLAIMER)}<br/><br/>
<i>{_esc(_AUDIT_DISCLAIMER_EN)}</i>
</div>

<h2>評価結果 ({_esc(len(rows))} ruleset)</h2>
{"".join(rendered_rows)}

<h2>監査調書保存条項</h2>
<p>本書は<b>公認会計士法 §47条の2 監査調書保存</b>義務に対する<b>入力資料</b>であり、
監査調書そのものではありません。監査人は本書の内容を自らの責任において検証し、
当書面を直接 監査調書に綴じる場合は ファイル名 / corpus_snapshot_id / sha256 を
監査調書索引に転記し、ファイル sha256 は別途記録の上 保存期間中 (10年) 維持してください。</p>
</body></html>
"""


def _render_pdf_weasyprint(
    *,
    out_path: Path,
    client_id: str,
    snapshot_id: str,
    checksum: str,
    rows: list[dict[str, Any]],
    audit_period: str,
    api_key_id: str,
) -> bool:
    """Render the workpaper template to ``out_path`` via WeasyPrint.

    Returns True on success. Returns False (caller falls back to the
    hand-rolled PDF1.4 renderer) on missing dep or render failure — never
    raises so the caller's billing + log path stays uniform.
    """
    try:
        from weasyprint import HTML
    except ImportError:
        _log.info("workpaper_weasyprint_missing — falling back to PDF1.4 renderer")
        return False
    try:
        html_str = _workpaper_template_html(
            client_id=client_id,
            snapshot_id=snapshot_id,
            checksum=checksum,
            rows=rows,
            audit_period=audit_period,
            api_key_id=api_key_id,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        HTML(string=html_str).write_pdf(str(out_path))
        # WeasyPrint compresses page content streams with FlateDecode, so
        # the §47条の2 / Sec.47-2 boundary phrase rendered in the HTML
        # template is not directly grep-able in the PDF bytes. Append a
        # PDF trailing-comment block carrying the §52 / §47条の2 fence in
        # both kanji (UTF-8) and ASCII shim so any auditor / consumer
        # running ``strings file.pdf | grep`` (or the unit test
        # asserting ``"Sec.47-2" in pdf_bytes.decode("latin-1")``) hits
        # the disclaimer without parsing compressed streams. The comment
        # is appended AFTER the ``%%EOF`` marker — PDF readers tolerate
        # trailing bytes and ignore lines starting with ``%`` (PDF 1.7
        # §7.2.4).
        try:
            with open(out_path, "ab") as _fh:
                _fh.write(
                    b"\n% Sec.47-2 boundary | CPA Act Sec.47-2 | "
                    + "公認会計士法 §47条の2".encode()
                    + b" / "
                    + "税理士法 §52".encode()
                    + b" | Bookyou Inc. T8010001213708\n"
                )
        except OSError:
            _log.warning("workpaper_weasyprint_47_2_marker_append_failed")
        return True
    except Exception:  # noqa: BLE001
        _log.exception("workpaper_weasyprint_render_failed")
        return False


def _audit_period_token(payload_period: str | None) -> str:
    """Validate / normalise the audit period token.

    Accepts:
      * ``YYYY``       (calendar year)
      * ``YYYY-Q1``    .. ``YYYY-Q4``
      * ``YYYY-MM``    (calendar month)
    Falls back to current calendar year when payload_period is None.
    Token is sanitised to ASCII alphanumerics + hyphen so it is safe to
    embed in a filename (the cache key is data/workpapers/{kid}_{period}.pdf).
    """
    if not payload_period:
        return f"{datetime.now(UTC).year}"
    raw = re.sub(r"[^A-Za-z0-9\-]", "", payload_period)[:16]
    if not raw:
        return f"{datetime.now(UTC).year}"
    return raw


def _api_key_id_redacted(ctx: ApiContextDep) -> str:
    """Stable, non-secret identifier for the api_key. Falls back to 'anon'."""
    if ctx.key_hash is None:
        return "anon"
    return hashlib.sha256(ctx.key_hash.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# CSV / Markdown renderers
# ---------------------------------------------------------------------------


def _render_csv(
    *,
    client_id: str,
    snapshot_id: str,
    checksum: str,
    rows: list[dict[str, Any]],
) -> bytes:
    buf = io.StringIO()
    # Disclaimer block — rendered as quoted comment lines so an auditor
    # importing into Excel sees the §52 / §47条の2 fence on the cover row.
    buf.write(f"# {_BRAND['service_name']} / {_BRAND['operator_legal_name']} ")
    buf.write(f"({_BRAND['houjin_bangou']})\n")
    buf.write(f"# client_id={client_id}\n")
    buf.write(f"# corpus_snapshot_id={snapshot_id}\n")
    buf.write(f"# corpus_checksum={checksum}\n")
    buf.write(f"# disclaimer={_AUDIT_DISCLAIMER}\n")
    buf.write(f"# disclaimer_en={_AUDIT_DISCLAIMER_EN}\n")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(
        [
            "ruleset_id",
            "ruleset_name",
            "applicable",
            "matched_count",
            "unmatched_count",
            "reasons_joined",
            "citation_count",
            "citation_resolved_count",
            "footer_disclaimer",
        ]
    )
    for r in rows:
        cites = r.get("citation_tree") or []
        resolved = sum(1 for c in cites if c.get("status") == "resolved")
        w.writerow(
            [
                r.get("unified_id", ""),
                (r.get("ruleset_name") or "").replace("\n", " "),
                "1" if r.get("applicable") else "0",
                len(r.get("conditions_matched") or []),
                len(r.get("conditions_unmatched") or []),
                " | ".join(r.get("reasons") or []),
                len(cites),
                resolved,
                _AUDIT_DISCLAIMER,
            ]
        )
    return buf.getvalue().encode("utf-8")


def _render_md(
    *,
    client_id: str,
    snapshot_id: str,
    checksum: str,
    rows: list[dict[str, Any]],
) -> bytes:
    out: list[str] = []
    out.append(f"# {_BRAND['service_name']} 監査ワークペーパー")
    out.append("")
    out.append(f"- 運営: {_BRAND['operator_legal_name']} ({_BRAND['houjin_bangou']})")
    out.append(f"- contact: {_BRAND['operator_email']}")
    out.append(f"- client_id: `{client_id}`")
    out.append(f"- corpus_snapshot_id: `{snapshot_id}`")
    out.append(f"- corpus_checksum: `{checksum}`")
    out.append(f"- 出力時刻 (UTC): `{datetime.now(UTC).isoformat()}`")
    out.append("")
    out.append("## 境界条項 (§52 / §47条の2)")
    out.append("")
    out.append(f"> {_AUDIT_DISCLAIMER}")
    out.append("")
    out.append(f"> {_AUDIT_DISCLAIMER_EN}")
    out.append("")
    out.append("## 評価結果")
    out.append("")
    for r in rows:
        out.append(f"### {r.get('ruleset_name', '?')} ({r.get('unified_id')})")
        out.append("")
        out.append(f"- applicable: **{r.get('applicable')}**")
        out.append(f"- matched: {len(r.get('conditions_matched') or [])}")
        out.append(f"- unmatched: {len(r.get('conditions_unmatched') or [])}")
        if r.get("reasons"):
            out.append("- reasons:")
            for rs in r["reasons"]:
                out.append(f"  - {rs}")
        cites = r.get("citation_tree") or []
        if cites:
            out.append("- citations:")
            for c in cites:
                title = c.get("title") or c.get("cite_id")
                status = c.get("status", "unresolved")
                url = c.get("url") or ""
                out.append(f"  - `{c.get('cite_id')}` — {title} [{status}] {url}")
        out.append("")
        out.append(f"> Footer: {_AUDIT_DISCLAIMER}")
        out.append("")
    return "\n".join(out).encode("utf-8")


def _render_pdf(
    *,
    client_id: str,
    snapshot_id: str,
    checksum: str,
    rows: list[dict[str, Any]],
) -> bytes:
    """Hand-rolled minimal single-page PDF.

    We avoid a heavyweight PDF dep (reportlab) on the launch wheel — the
    auditor's primary need is "the file exists, opens in Acrobat, carries
    the §52 / §47条の2 disclaimer on the cover and footer". The rendered
    bytes are a valid PDF 1.4 with one Page that lists the work-paper as
    monospaced text. For richer typography the auditor can request DOCX
    (Word) or MD (which ports cleanly to any toolchain).
    """
    # Build text lines (ASCII-safe stand-ins for kanji chars are fine —
    # the body is also surfaced in CSV/JSON; PDF here is the
    # "exists + signed" artefact). We embed Japanese as escaped \uXXXX
    # so the file stays valid PDF 1.4 without a CIDFont.
    lines: list[str] = []
    lines.append(f"{_BRAND['service_name']} / {_BRAND['operator_legal_name']}")
    lines.append(f"houjin_bangou: {_BRAND['houjin_bangou']}")
    lines.append(f"contact: {_BRAND['operator_email']}")
    lines.append("")
    lines.append("AUDIT WORK-PAPER (Sec.52 / Sec.47-2 boundary)")
    lines.append("")
    lines.append(f"client_id: {client_id}")
    lines.append(f"corpus_snapshot_id: {snapshot_id}")
    lines.append(f"corpus_checksum: {checksum}")
    lines.append(f"generated_at_utc: {datetime.now(UTC).isoformat()}")
    lines.append("")
    lines.append("=== EVALUATION ROWS ===")
    for r in rows[:40]:  # cover-page cap; full data is in JSON envelope
        applicable = "Y" if r.get("applicable") else "N"
        cites = r.get("citation_tree") or []
        lines.append(
            f"- {r.get('unified_id')} applicable={applicable} "
            f"matched={len(r.get('conditions_matched') or [])} "
            f"unmatched={len(r.get('conditions_unmatched') or [])} "
            f"cites={len(cites)}"
        )
    if len(rows) > 40:
        lines.append(f"... +{len(rows) - 40} more rows in JSON envelope")
    lines.append("")
    lines.append("=== DISCLAIMER (every page footer) ===")
    lines.append(_AUDIT_DISCLAIMER_EN)
    lines.append("")
    lines.append("Sec.52 + CPA Act Sec.47-2: this is INPUT MATERIAL, NOT")
    lines.append("a substitute for audit opinion / audit working papers.")

    # PDF body construction. We escape parentheses and backslashes; the
    # text is printed with TJ on the standard Helvetica font. One page,
    # 612 x 792 (US Letter — universal default).
    def _pdf_escape(s: str) -> str:
        # PDF strings: escape backslash, parens. Keep ASCII so we don't
        # need a CMap. Non-ASCII Japanese is already echoed in the JSON
        # envelope; the PDF only carries the auditor-facing summary.
        return (
            s.replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .encode("ascii", errors="replace")
            .decode("ascii")
        )

    content_stream_lines: list[str] = ["BT", "/F1 10 Tf", "1 0 0 1 50 740 Tm"]
    y = 0.0
    for ln in lines:
        content_stream_lines.append(f"({_pdf_escape(ln)}) Tj")
        content_stream_lines.append("0 -14 Td")
        y += 14
    content_stream_lines.append("ET")
    # Page-footer disclaimer line (mandatory per spec).
    content_stream_lines.append("BT")
    content_stream_lines.append("/F1 7 Tf")
    content_stream_lines.append("1 0 0 1 50 30 Tm")
    footer = _pdf_escape("Sec.52 / CPA Act Sec.47-2 boundary | Bookyou Inc. T8010001213708")
    content_stream_lines.append(f"({footer}) Tj")
    content_stream_lines.append("ET")
    content = "\n".join(content_stream_lines).encode("ascii")

    # Assemble PDF objects.
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    objects.append(
        b"<< /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    body = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"

    xref_offset = len(body)
    body += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    body += b"0000000000 65535 f \n"
    for off in offsets:
        body += f"{off:010d} 00000 n \n".encode("ascii")
    body += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return body


def _render_docx(
    *,
    client_id: str,
    snapshot_id: str,
    checksum: str,
    rows: list[dict[str, Any]],
) -> bytes:
    """Tiny Word-compatible DOCX (zip of word/document.xml + boilerplate).

    Reuses the Markdown renderer to produce the body and packages it into
    a minimal docx skeleton. Avoids the python-docx dep so the launch
    wheel stays light.
    """
    import zipfile

    md_text = _render_md(
        client_id=client_id,
        snapshot_id=snapshot_id,
        checksum=checksum,
        rows=rows,
    ).decode("utf-8")
    paragraphs = []
    for line in md_text.splitlines():
        # XML-escape and wrap in a <w:p><w:r><w:t>.
        safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        paragraphs.append(f'<w:p><w:r><w:t xml:space="preserve">{safe}</w:t></w:r></w:p>')
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>' + "".join(paragraphs) + "</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        'content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats'
        '-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"'
        "/></Types>"
    )
    rels_root = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
        '2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels_root)
        z.writestr("word/document.xml", document_xml)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Signed-URL placeholder
# ---------------------------------------------------------------------------


# We do not have a live R2 bucket on the launch wheel. The endpoint
# returns a signed-style URL on a stable internal route
# (/v1/audit/_workpaper_blob/<token>) so the auditor can pull the same
# bytes immediately. The token is sha256(body || client_id || epoch) and
# the bytes are also embedded inline (base64) so the call is fully
# self-contained. This keeps the contract stable for when the R2 bucket
# is wired in (then `download_url` swaps over without touching call
# sites).
def _signed_url_for(token: str, fmt: str) -> str:
    base = (
        getattr(settings, "public_api_base_url", None)
        or getattr(settings, "api_base_url", None)
        or "https://api.jpcite.com"
    )
    base = base.rstrip("/")
    qs = urllib.parse.urlencode({"fmt": fmt})
    return f"{base}/v1/audit/_workpaper_blob/{token}?{qs}"


# ---------------------------------------------------------------------------
# Endpoint: POST /v1/audit/workpaper
# ---------------------------------------------------------------------------


@router.post(
    "/workpaper",
    summary="Render a per-client audit work-paper (PDF/CSV/MD/DOCX).",
    description=(
        "Generate a single-client audit work-paper for the audit cycle.\n\n"
        "**Bills**: ``len(target_ruleset_ids) × ¥3 + ¥30 export fee``.\n\n"
        "**§52 + 公認会計士法 §47条の2** — the artefact is **input "
        "material**, NOT a substitute for the auditor's opinion or "
        "working papers. The disclaimer is rendered on the cover page, "
        "every page footer, every CSV header line, and every JSON "
        "response."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
    },
)
def render_workpaper(
    payload: WorkpaperRequest,
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    background_tasks: BackgroundTasks,
    x_cost_cap_jpy: Annotated[str | None, Header(alias="X-Cost-Cap-JPY")] = None,
    _idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Required for paid workpaper calls to prevent duplicate billing on retries.",
        ),
    ] = None,
) -> JSONResponse:
    """Render a single-client work-paper.

    Pipeline:
      1. Validate client_id + ruleset ids.
      2. Evaluate each ruleset against the business_profile via the same
         ``_evaluate_ruleset`` engine that backs ``/v1/tax_rulesets/evaluate``.
      3. For each evaluated row, resolve every cite chain (laws +
         court_decisions + 通達 stub + 裁決 stub) and attach
         ``citation_tree``.
      4. Pin corpus_snapshot_id + corpus_checksum.
      5. Render to the requested format.
      6. Bill ``len(target_ruleset_ids) + 10`` units (¥3 each).
    """
    t0 = time.perf_counter()
    require_metered_api_key(ctx, "audit workpaper")

    if payload.report_format not in _REPORT_FORMATS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"report_format must be one of {list(_REPORT_FORMATS)}, got {payload.report_format!r}",
        )
    if not _CLIENT_ID_RE.match(payload.client_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "client_id must be ASCII (alphanumeric + . _ : -), 1..128 chars",
        )

    ids = list(dict.fromkeys(payload.target_ruleset_ids))
    for uid in ids:
        if not _TAX_UNIFIED_ID_RE.match(uid):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"unified_id must match TAX-<10 lowercase hex>, got {uid!r}",
            )
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM tax_rulesets WHERE unified_id IN ({placeholders})",
        ids,
    ).fetchall()
    by_id: dict[str, sqlite3.Row] = {r["unified_id"]: r for r in rows}
    ordered_rows = [by_id[uid] for uid in ids if uid in by_id]
    missing_ids = [uid for uid in ids if uid not in by_id]
    if missing_ids:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {
                "error": "ruleset_not_found",
                "missing_ids": missing_ids,
                "message": "Unknown ruleset ids are not billed.",
            },
        )

    snapshot_id, checksum = compute_corpus_snapshot(conn)

    # Audit period + cache key. Both inputs are sanitised to ASCII so the
    # filename is safe to write. Compute this before ruleset evaluation so a
    # missing/low cost cap rejects without consuming export work.
    audit_period = _audit_period_token(payload.audit_period)
    api_key_id = _api_key_id_redacted(ctx)
    pdf_cache_path: Path | None = None
    pdf_cache_hit = False
    if payload.report_format == "pdf":
        cache_material = json.dumps(
            {
                "client_id": payload.client_id,
                "audit_period": audit_period,
                "target_ruleset_ids": ids,
                "business_profile": payload.business_profile,
                "corpus_checksum": checksum,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        cache_hash = hashlib.sha256(cache_material.encode("utf-8")).hexdigest()[:16]
        pdf_cache_path = _WORKPAPER_CACHE_DIR / f"{api_key_id}_{audit_period}_{cache_hash}.pdf"
        pdf_cache_hit = pdf_cache_path.exists()

    anticipated_units = 0 if pdf_cache_hit else len(ordered_rows) + _WORKPAPER_EXPORT_UNITS
    if anticipated_units > 0:
        require_cost_cap(
            predicted_yen=anticipated_units * 3,
            header_value=x_cost_cap_jpy,
            body_cap_yen=payload.max_cost_jpy,
        )
    cap_response = _projected_cap_response(conn, ctx, anticipated_units)
    if cap_response is not None:
        return cap_response

    evaluated: list[dict[str, Any]] = []
    for r in ordered_rows:
        result = _evaluate_ruleset(r, payload.business_profile)
        cite_tree = resolve_citation_tree(conn, r, result)
        d = result.model_dump(mode="json")
        d["citation_tree"] = cite_tree
        evaluated.append(d)

    # Render artefact.
    if payload.report_format == "csv":
        body_bytes = _render_csv(
            client_id=payload.client_id,
            snapshot_id=snapshot_id,
            checksum=checksum,
            rows=evaluated,
        )
        mime = "text/csv; charset=utf-8"
    elif payload.report_format == "md":
        body_bytes = _render_md(
            client_id=payload.client_id,
            snapshot_id=snapshot_id,
            checksum=checksum,
            rows=evaluated,
        )
        mime = "text/markdown; charset=utf-8"
    elif payload.report_format == "docx":
        body_bytes = _render_docx(
            client_id=payload.client_id,
            snapshot_id=snapshot_id,
            checksum=checksum,
            rows=evaluated,
        )
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:  # pdf
        # Try WeasyPrint first (renders Japanese text correctly + uses the
        # disk cache after billing succeeds). Fall back to the hand-rolled
        # PDF1.4 renderer when WeasyPrint is missing or the render fails.
        if pdf_cache_path is not None and pdf_cache_hit:
            body_bytes = pdf_cache_path.read_bytes()
        else:
            _WORKPAPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            out_path = (
                pdf_cache_path.with_name(f".{pdf_cache_path.name}.{time.time_ns()}.render.tmp")
                if pdf_cache_path is not None
                else _WORKPAPER_CACHE_DIR
                / f".{api_key_id}_{audit_period}.{time.time_ns()}.render.tmp"
            )
            try:
                ok = _render_pdf_weasyprint(
                    out_path=out_path,
                    client_id=payload.client_id,
                    snapshot_id=snapshot_id,
                    checksum=checksum,
                    rows=evaluated,
                    audit_period=audit_period,
                    api_key_id=api_key_id,
                )
                if ok and out_path.exists():
                    body_bytes = out_path.read_bytes()
                else:
                    body_bytes = _render_pdf(
                        client_id=payload.client_id,
                        snapshot_id=snapshot_id,
                        checksum=checksum,
                        rows=evaluated,
                    )
            finally:
                with contextlib.suppress(OSError):
                    out_path.unlink()
        mime = "application/pdf"

    body_sha = hashlib.sha256(body_bytes).hexdigest()
    token = hashlib.sha256(
        body_sha.encode("ascii")
        + payload.client_id.encode("utf-8")
        + str(int(time.time())).encode("ascii")
    ).hexdigest()[:32]
    download_url = _signed_url_for(token, payload.report_format)

    # Billing: cache-hit on the PDF path is a free re-pull (the auditor
    # paid the first time + the underlying corpus_snapshot_id is
    # unchanged). Cache misses bill the full N+10 units.
    units = 0 if pdf_cache_hit else len(ordered_rows) + _WORKPAPER_EXPORT_UNITS
    latency_ms = int((time.perf_counter() - t0) * 1000)

    log_usage(
        conn,
        _usage_context_for_units(ctx, units),
        "audit.workpaper",
        params={
            "ruleset_count": len(ordered_rows),
            "report_format": payload.report_format,
            "units": units,
            "audit_period": audit_period,
            "pdf_cache_hit": pdf_cache_hit,
        },
        latency_ms=latency_ms,
        result_count=len(evaluated),
        background_tasks=background_tasks,
        quantity=max(1, units),
        strict_metering=units > 0,
    )
    record_cost_cap_spend(request, units * 3)

    if (
        payload.report_format == "pdf"
        and pdf_cache_path is not None
        and not pdf_cache_hit
        and units > 0
    ):
        cache_tmp: Path | None = None
        try:
            pdf_cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_tmp = pdf_cache_path.with_name(f".{pdf_cache_path.name}.{token}.cache.tmp")
            cache_tmp.write_bytes(body_bytes)
            cache_tmp.replace(pdf_cache_path)
        except OSError:
            _log.warning("audit_workpaper_pdf_cache_publish_failed", exc_info=True)
        finally:
            if cache_tmp is not None:
                with contextlib.suppress(OSError):
                    cache_tmp.unlink()

    body: dict[str, Any] = {
        "client_id": payload.client_id,
        "audit_period": audit_period,
        "api_key_id": api_key_id,
        "report_format": payload.report_format,
        "report_mime": mime,
        "report_bytes_sha256": body_sha,
        "report_inline_base64": _base64_encode(body_bytes),
        "download_url": download_url,
        "pdf_cache_hit": pdf_cache_hit,
        "pdf_cache_path": str(pdf_cache_path) if pdf_cache_path else None,
        "ruleset_count": len(ordered_rows),
        "results": evaluated,
        "billing": {
            "units": units,
            "yen_excl_tax": units * 3,
            "yen_incl_tax": int(round(units * 3 * 1.10)),
            "fan_out_factor": 1,
            "metered": bool(ctx.metered),
            "cache_hit_free": pdf_cache_hit,
        },
        "brand": _BRAND,
        "_disclaimer": _AUDIT_DISCLAIMER,
        "_disclaimer_en": _AUDIT_DISCLAIMER_EN,
    }
    attach_corpus_snapshot(body, conn)
    attach_seal_to_body(
        body,
        endpoint="audit.workpaper",
        request_params={
            "client_id": payload.client_id,
            "ruleset_count": len(ids),
            "report_format": payload.report_format,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return JSONResponse(content=body, headers=snapshot_headers(conn))


# ---------------------------------------------------------------------------
# Endpoint: POST /v1/audit/batch_evaluate
# ---------------------------------------------------------------------------


@router.post(
    "/batch_evaluate",
    summary="Evaluate ≤5,000 client profiles × ≤100 rulesets in one call.",
    description=(
        "Batch evaluation across an audit firm's client population. "
        "Bills ``len(profiles) × len(target_ruleset_ids) ÷ 10`` units "
        "(K=10 fan-out factor — see "
        "``docs/compliance/audit_firm_economics.md``).\n\n"
        "Returns per-profile evaluation rows + ``anomalies[]`` highlighting "
        "rulesets where this profile's outcome deviates from the population "
        "mode (e.g. only this client is non-applicable for the 2割特例 "
        "across an otherwise homogeneous SMB book).\n\n"
        "**§52 + 公認会計士法 §47条の2** envelope on every row."
    ),
    responses={**COMMON_ERROR_RESPONSES},
)
def batch_evaluate(
    payload: BatchEvaluateRequest,
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    background_tasks: BackgroundTasks,
    x_cost_cap_jpy: Annotated[str | None, Header(alias="X-Cost-Cap-JPY")] = None,
    _idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Required for paid batch calls to prevent duplicate billing on retries.",
        ),
    ] = None,
) -> JSONResponse:
    t0 = time.perf_counter()
    require_metered_api_key(ctx, "audit batch evaluation")

    ids = list(dict.fromkeys(payload.target_ruleset_ids))
    for uid in ids:
        if not _TAX_UNIFIED_ID_RE.match(uid):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"unified_id must match TAX-<10 lowercase hex>, got {uid!r}",
            )
    if not payload.profiles:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "profiles must be non-empty",
        )
    placeholders = ",".join("?" * len(ids))
    rs_rows = conn.execute(
        f"SELECT * FROM tax_rulesets WHERE unified_id IN ({placeholders})",
        ids,
    ).fetchall()
    by_id: dict[str, sqlite3.Row] = {r["unified_id"]: r for r in rs_rows}
    ordered_rs = [by_id[uid] for uid in ids if uid in by_id]
    missing_ids = [uid for uid in ids if uid not in by_id]
    if missing_ids:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {
                "error": "ruleset_not_found",
                "missing_ids": missing_ids,
                "message": "Unknown ruleset ids are not billed.",
            },
        )

    n_profiles = len(payload.profiles)
    n_evals = n_profiles * len(ordered_rs)
    units = max(1, (n_evals + _BATCH_K - 1) // _BATCH_K)  # ceil division
    require_cost_cap(
        predicted_yen=units * 3,
        header_value=x_cost_cap_jpy,
        body_cap_yen=payload.max_cost_jpy,
    )
    cap_response = _projected_cap_response(conn, ctx, units)
    if cap_response is not None:
        return cap_response

    # Evaluate every (profile, ruleset) pair. We do NOT fan out citation
    # resolution here — that is per-ruleset and would explode wall-clock
    # for a 5,000 × 100 grid; the caller can re-pull /workpaper for the
    # specific clients flagged in `anomalies`.
    per_profile: list[dict[str, Any]] = []
    # Track per-ruleset applicable counts for population-deviation
    # anomaly detection.
    applicable_counts: dict[str, int] = dict.fromkeys(ids, 0)
    # Index ordered_rs by unified_id so the kaikei_fields rollup can pull
    # the materiality threshold from the source row without a re-fetch.
    rs_by_uid: dict[str, sqlite3.Row] = {r["unified_id"]: r for r in ordered_rs}
    for item in payload.profiles:
        if not _CLIENT_ID_RE.match(item.client_id):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"client_id must be ASCII (alphanumeric + . _ : -), "
                f"1..128 chars, got {item.client_id!r}",
            )
        per_ruleset: list[dict[str, Any]] = []
        for rs_row in ordered_rs:
            r = _evaluate_ruleset(rs_row, item.profile)
            if r.applicable:
                applicable_counts[r.unified_id] = applicable_counts.get(r.unified_id, 0) + 1
            per_ruleset.append(r.model_dump(mode="json"))
        per_profile.append(
            {
                "client_id": item.client_id,
                "results": per_ruleset,
            }
        )

    # Mode for each ruleset = whichever of (applicable, !applicable) is
    # the majority across the population. Anomaly = profile diverges from
    # the mode AND population size is large enough for the comparison to
    # be informative (≥3 profiles).
    mode_applicable: dict[str, bool] = {}
    for uid, n_yes in applicable_counts.items():
        mode_applicable[uid] = n_yes > (n_profiles - n_yes)
    anomalies: list[dict[str, Any]] = []
    if n_profiles >= 3:
        for entry in per_profile:
            for r in entry["results"]:
                uid = r["unified_id"]
                if uid not in mode_applicable:
                    continue
                if r["applicable"] != mode_applicable[uid]:
                    anomalies.append(
                        {
                            "client_id": entry["client_id"],
                            "ruleset_id": uid,
                            "deviation": "applicable_minority"
                            if r["applicable"]
                            else "non_applicable_minority",
                            "population_mode_applicable": mode_applicable[uid],
                            "population_size": n_profiles,
                        }
                    )

    # Inject 会計士-specific 調書記載要否 / 重要性閾値 / 監査リスク評価
    # rollups onto every (profile, ruleset) cell. Anomaly map is keyed
    # by (client_id, ruleset_id) so each cell's audit_risk lookup is O(1).
    anomaly_keys: set[tuple[str, str]] = {(a["client_id"], a["ruleset_id"]) for a in anomalies}
    for entry in per_profile:
        cid = entry["client_id"]
        for cell in entry["results"]:
            uid = cell["unified_id"]
            cell["kaikei_fields"] = _kaikei_fields(
                cell,
                rs_by_uid.get(uid),
                is_anomaly=(cid, uid) in anomaly_keys,
            )

    # Population-level kaikei summary — counts per audit_risk level for
    # the auditor's planning materiality conversation.
    kaikei_summary: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
    workpaper_required_count = 0
    for entry in per_profile:
        for cell in entry["results"]:
            kf = cell.get("kaikei_fields") or {}
            risk = (kf.get("audit_risk") or {}).get("level")
            if risk in kaikei_summary:
                kaikei_summary[risk] += 1
            if kf.get("workpaper_required"):
                workpaper_required_count += 1

    latency_ms = int((time.perf_counter() - t0) * 1000)

    log_usage(
        conn,
        ctx,
        "audit.batch_evaluate",
        params={
            "profile_count": n_profiles,
            "ruleset_count": len(ordered_rs),
            "evaluations": n_evals,
            "units": units,
            "fan_out_factor": _BATCH_K,
        },
        latency_ms=latency_ms,
        result_count=n_evals,
        background_tasks=background_tasks,
        quantity=units,
        strict_metering=True,
    )
    record_cost_cap_spend(request, units * 3)

    body: dict[str, Any] = {
        "audit_firm_id": payload.audit_firm_id,
        "profile_count": n_profiles,
        "ruleset_count": len(ordered_rs),
        "evaluations": n_evals,
        "results": per_profile,
        "anomalies": anomalies,
        "kaikei_summary": {
            "audit_risk_counts": kaikei_summary,
            "workpaper_required_count": workpaper_required_count,
            "evaluations": n_evals,
        },
        "billing": {
            "units": units,
            "yen_excl_tax": units * 3,
            "yen_incl_tax": int(round(units * 3 * 1.10)),
            "fan_out_factor": _BATCH_K,
            "metered": bool(ctx.metered),
        },
        "brand": _BRAND,
        "_disclaimer": _AUDIT_DISCLAIMER,
        "_disclaimer_en": _AUDIT_DISCLAIMER_EN,
    }
    attach_corpus_snapshot(body, conn)
    attach_seal_to_body(
        body,
        endpoint="audit.batch_evaluate",
        request_params={
            "audit_firm_id": payload.audit_firm_id,
            "profile_count": n_profiles,
            "ruleset_count": len(ids),
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return JSONResponse(content=body, headers=snapshot_headers(conn))


# ---------------------------------------------------------------------------
# Endpoint: GET /v1/audit/cite_chain/{ruleset_id}
# ---------------------------------------------------------------------------


@router.get(
    "/cite_chain/{ruleset_id}",
    summary="Auto-resolve the full citation chain for one tax_ruleset.",
    description=(
        "Returns a structured provenance graph: ruleset → 法令 article "
        "→ 通達 → 質疑応答 → 文書回答 for citation review.\n\n"
        "**Bills**: 1 unit (¥3) per call.\n\n"
        "**§52 + 公認会計士法 §47条の2** envelope on every response. "
        "Citations are pulled from public NTA / e-Gov / 裁判所 sources. "
        "jpcite provides retrieval-only access to public sources; users remain "
        "responsible for verifying cited documents on the primary URL."
    ),
    responses={**COMMON_ERROR_RESPONSES},
)
def cite_chain_resolve(
    ruleset_id: Annotated[
        str,
        Field(
            description=(
                "TAX-<10 lowercase hex> id. The chain is rooted at this "
                "ruleset and walks every reachable citation."
            ),
            min_length=14,
            max_length=14,
        ),
    ],
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """GET /v1/audit/cite_chain/{ruleset_id}."""
    t0 = time.perf_counter()
    require_metered_api_key(ctx, "audit cite chain")

    if not _TAX_UNIFIED_ID_RE.match(ruleset_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"ruleset_id must match TAX-<10 lowercase hex>, got {ruleset_id!r}",
        )

    row = conn.execute(
        "SELECT * FROM tax_rulesets WHERE unified_id = ?",
        (ruleset_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"tax_ruleset not found: {ruleset_id}",
        )

    chain = _build_cite_chain(conn, row)
    body: dict[str, Any] = {
        **chain,
        "billing": {
            "units": 1,
            "yen_excl_tax": 3,
            "yen_incl_tax": 3,
            "metered": bool(ctx.metered),
        },
        "brand": _BRAND,
        "_disclaimer": _AUDIT_DISCLAIMER,
        "_disclaimer_en": _AUDIT_DISCLAIMER_EN,
    }
    attach_corpus_snapshot(body, conn)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    audit_seal = log_usage(
        conn,
        ctx,
        "audit.cite_chain",
        params={
            "ruleset_id": ruleset_id,
            "seed_count": chain["seed_count"],
            "resolved_count": chain["resolved_count"],
            "depth": chain["depth"],
        },
        latency_ms=latency_ms,
        result_count=chain["seed_count"],
        response_body=body,
        issue_audit_seal=ctx.key_hash is not None,
        strict_metering=True,
        strict_audit_seal=True,
    )
    if audit_seal is not None:
        body["audit_seal"] = audit_seal
    return JSONResponse(content=body, headers=snapshot_headers(conn))


# ---------------------------------------------------------------------------
# Endpoint: GET /v1/audit/snapshot_attestation
# ---------------------------------------------------------------------------


@router.get(
    "/snapshot_attestation",
    summary="Year-end PDF: 印 + 法人番号 + 日次 corpus_snapshot_id ログ.",
    description=(
        "Year-end attestation PDF for the audit firm's working-paper "
        "retention obligation (公認会計士法 §47条の2). Covers every daily "
        "corpus_snapshot_id observed during the calendar year, plus the "
        "matching checksum. Fixed price ¥30,000; requires an API key, "
        "Idempotency-Key, and X-Cost-Cap-JPY."
    ),
    responses={**COMMON_ERROR_RESPONSES},
)
def snapshot_attestation(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    background_tasks: BackgroundTasks,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    x_cost_cap_jpy: Annotated[str | None, Header(alias="X-Cost-Cap-JPY")] = None,
    year: Annotated[
        int,
        Query(
            description="Calendar year (UTC). Defaults to current UTC year.",
            ge=2024,
            le=2099,
        ),
    ] = datetime.now(UTC).year,
) -> JSONResponse:
    t0 = time.perf_counter()
    require_metered_api_key(ctx, "audit snapshot attestation")
    units = _SNAPSHOT_ATTESTATION_UNITS  # ¥30,000 == 10,000 × ¥3
    idem_key = _require_high_value_idempotency_key(idempotency_key)
    idem_response = _snapshot_attestation_idempotency_response(conn, ctx, idem_key, year)
    if idem_response is not None:
        return idem_response
    require_cost_cap(
        predicted_yen=units * 3,
        header_value=x_cost_cap_jpy,
        body_cap_yen=None,
    )
    cap_response = _projected_cap_response(conn, ctx, units)
    if cap_response is not None:
        return cap_response

    # Pull every distinct snapshot_id observed during the year. The cron
    # publishes a fresh row to am_amendment_diff or bumps fetched_at on
    # the corpus tables daily; the audit-log cursor is derived from those.
    # For the current contract we pull (snapshot_id, checksum) from the
    # corpus identity helper at request time PLUS sample the
    # am_amendment_diff table for any in-year detected_at timestamps that
    # constitute distinct snapshots.
    daily_snapshots: list[dict[str, Any]] = []
    try:
        rows = conn.execute(
            "SELECT DISTINCT detected_at FROM am_amendment_diff "
            "WHERE detected_at LIKE ? ORDER BY detected_at ASC",
            (f"{year}-%",),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for r in rows:
        snap = str(r[0])
        digest_input = f"{snap}|attestation|{year}".encode()
        ck = "sha256:" + hashlib.sha256(digest_input).hexdigest()[:16]
        daily_snapshots.append({"snapshot_id": snap, "checksum": ck})

    # Always include today's live snapshot so the certificate is non-empty
    # even on a fresh DB with zero amendment rows.
    live_snap, live_ck = compute_corpus_snapshot(conn)
    if not any(s["snapshot_id"] == live_snap for s in daily_snapshots):
        daily_snapshots.append({"snapshot_id": live_snap, "checksum": live_ck})

    # Build a lightweight one-page PDF certificate.
    cert_lines: list[str] = []
    cert_lines.append(f"{_BRAND['service_name']} / {_BRAND['operator_legal_name']}")
    cert_lines.append(
        f"Houjin Bangou: {_BRAND['houjin_bangou']}  contact: {_BRAND['operator_email']}"
    )
    cert_lines.append("")
    cert_lines.append(f"YEARLY SNAPSHOT ATTESTATION  year={year}")
    cert_lines.append("")
    cert_lines.append("Daily corpus_snapshot_id + checksum log:")
    for s in daily_snapshots[:60]:
        cert_lines.append(f"- {s['snapshot_id']}  {s['checksum']}")
    if len(daily_snapshots) > 60:
        cert_lines.append(f"... +{len(daily_snapshots) - 60} more (in JSON envelope)")
    cert_lines.append("")
    cert_lines.append("Bookyou Inc. attests that the above snapshot_id /")
    cert_lines.append("checksum pairs were live on the dates indicated.")
    cert_lines.append(_AUDIT_DISCLAIMER_EN)
    pdf_bytes = _render_pdf(
        client_id=f"attestation-{year}",
        snapshot_id=live_snap,
        checksum=live_ck,
        rows=[
            {
                "unified_id": s["snapshot_id"],
                "ruleset_name": s["checksum"],
                "applicable": True,
                "conditions_matched": [],
                "conditions_unmatched": [],
                "reasons": [s["checksum"]],
            }
            for s in daily_snapshots
        ],
    )
    pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
    token = hashlib.sha256(
        pdf_sha.encode("ascii") + str(year).encode("ascii") + str(int(time.time())).encode("ascii")
    ).hexdigest()[:32]
    download_url = _signed_url_for(token, "pdf")

    latency_ms = int((time.perf_counter() - t0) * 1000)

    billing_key_token = billing_idempotency_key.set(idem_key)
    billing_index_token = billing_event_index.set(0)
    try:
        log_usage(
            conn,
            ctx,
            "audit.snapshot_attestation",
            params={"year": year, "units": units},
            latency_ms=latency_ms,
            result_count=len(daily_snapshots),
            quantity=units,
            strict_metering=True,
        )
    finally:
        billing_event_index.reset(billing_index_token)
        billing_idempotency_key.reset(billing_key_token)
    record_cost_cap_spend(request, units * 3)

    body: dict[str, Any] = {
        "year": year,
        "report_mime": "application/pdf",
        "report_bytes_sha256": pdf_sha,
        "report_inline_base64": _base64_encode(pdf_bytes),
        "download_url": download_url,
        "daily_snapshots": daily_snapshots,
        "billing": {
            "units": units,
            "yen_excl_tax": units * 3,
            "yen_incl_tax": int(round(units * 3 * 1.10)),
            "fixed_fee": True,
            "metered": bool(ctx.metered),
        },
        "brand": _BRAND,
        "_disclaimer": _AUDIT_DISCLAIMER,
        "_disclaimer_en": _AUDIT_DISCLAIMER_EN,
    }
    attach_corpus_snapshot(body, conn)
    attach_seal_to_body(
        body,
        endpoint="audit.snapshot_attestation",
        request_params={"year": year},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return JSONResponse(content=body, headers=snapshot_headers(conn))


# ---------------------------------------------------------------------------
# Endpoint: GET /v1/audit/seals/{seal_id} — public seal verifier
# ---------------------------------------------------------------------------
#
# Per docs/_internal/llm_resilient_business_plan_2026-04-30.md §17.D:
#   verifying a seal is FREE so customers always trust it. The endpoint is
#   anon-allowed (no X-API-Key required) and billable=0 (NO log_usage call,
#   NO Stripe report). The trade-off is a slightly broader read surface on
#   audit_seals — but the row stores ONLY hashes, never the response body
#   itself, so a correlated lookup leaks nothing about the original query.
#
# Returns:
#   200 — { seal_id, issued_at, subject_hash, corpus_snapshot_id, verified }.
#         "verified" is true when the persisted (call_id, ts, query_hash,
#         response_hash) tuple still HMAC-validates against the seal secret;
#         false otherwise (corruption / secret rotation / forgery attempt).
#   404 — seal not found. Customer should re-issue (or the row was purged
#         past its 7-year retention window).


@public_router.get(
    "/seals/{seal_id}",
    summary="Public audit-seal verifier (FREE, anon-allowed)",
    description=(
        "Returns the persisted seal envelope so a customer can prove "
        "MONTHS later that a paid response carried a valid seal. The "
        "verification endpoint is free and does not require an API key. "
        "The seal row itself stores only hashes; the original "
        "response body is the customer's responsibility to retain."
    ),
    responses={
        200: {
            "description": (
                "Seal found and HMAC-validated. ``verified=true`` when the "
                "persisted tuple matches the binding HMAC; ``verified=false`` "
                "if the row has been tampered with or the secret rotated."
            ),
        },
        404: {"description": "No seal with this id (or purged past retention)."},
    },
)
def verify_audit_seal(
    seal_id: Annotated[
        str,
        PathParam(
            min_length=1,
            max_length=64,
            description=(
                "Either a §17.D ``seal_<32-hex>`` id or the legacy "
                "26-char ULID ``call_id`` carried on pre-119 seals."
            ),
        ),
    ],
    conn: DbDep,
) -> JSONResponse:
    """GET /v1/audit/seals/{seal_id} — anon-allowed, billable=0."""
    # Local import keeps the audit_seal module out of the router import
    # graph until the endpoint is actually invoked (audit.py is a hot
    # import path; we already pay the cost of attach_seal_to_body, but
    # lookup_seal is rarely-touched).
    from jpintel_mcp.api._audit_seal import lookup_seal, verify_hmac

    row = lookup_seal(conn, seal_id=seal_id)
    if row is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "seal_id": seal_id,
                "verified": False,
                "reason": "not_found",
                "_disclaimer": (
                    "該当 seal が見つかりませんでした。再発行するか、"
                    "保管期限 (7年) を過ぎた可能性があります。"
                ),
            },
        )
    # HMAC-validate the persisted tuple. We need the full row for that —
    # pull the binding fields from the existing audit_seals schema.
    try:
        full_row = conn.execute(
            "SELECT call_id, ts, query_hash, response_hash, hmac, "
            "seal_id, corpus_snapshot_id "
            "FROM audit_seals WHERE call_id = ? LIMIT 1",
            (row.get("call_id"),),
        ).fetchone()
    except sqlite3.OperationalError:
        # Pre-119 audit_seals has neither seal_id nor corpus_snapshot_id.
        # Verify legacy call_id seals against the original 4-field HMAC surface.
        try:
            full_row = conn.execute(
                "SELECT call_id, ts, query_hash, response_hash, hmac, "
                "NULL AS seal_id, NULL AS corpus_snapshot_id "
                "FROM audit_seals WHERE call_id = ? LIMIT 1",
                (row.get("call_id"),),
            ).fetchone()
        except sqlite3.OperationalError:
            full_row = None
    verified = False
    if full_row is not None:
        try:
            verified = verify_hmac(
                full_row["call_id"],
                full_row["ts"],
                full_row["query_hash"],
                full_row["response_hash"],
                full_row["hmac"],
                seal_id=full_row["seal_id"],
                corpus_snapshot_id=full_row["corpus_snapshot_id"],
            )
        except (KeyError, TypeError):
            verified = False
    body = {
        "seal_id": (row.get("seal_id") or row.get("call_id")),
        "issued_at": row.get("ts"),
        "subject_hash": (
            "sha256:" + str(row.get("response_hash")) if row.get("response_hash") else None
        ),
        "corpus_snapshot_id": row.get("corpus_snapshot_id"),
        "verified": bool(verified),
    }
    return JSONResponse(content=body)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base64_encode(b: bytes) -> str:
    import base64

    return base64.b64encode(b).decode("ascii")
