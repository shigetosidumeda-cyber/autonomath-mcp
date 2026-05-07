"""Invoice-registrant × houjin_master risk-score lookup (R8 2026-05-07).

Single-call answer to the daily question every 経理 / 税理士 fan-out client
asks: ``この取引先 (T 番号) は仕入税額控除 OK か?``.

Composes three signals already in our DBs:

  1. ``invoice_registrants`` (jpintel.db, migration 019, 13,801 delta rows
     + monthly 4M-row zenken bulk live since 2026-04-29) — the NTA
     公表サイト snapshot, gives us ``registered_date`` / ``revoked_date`` /
     ``expired_date``.
  2. ``houjin_master`` (jpintel.db, migration 014, 86,710 rows) — the
     国税庁 法人番号公表サイト canonical for 13-digit 法人番号. Used to
     cross-check that the T-number's ``houjin_bangou`` resolves to a known
     active corporate entity (corporation / sole_proprietor / other).
  3. age-of-registration heuristic — recently-registered (< 6 month)
     T-numbers are flagged 'caution' because the 国税庁 取消 lifecycle
     has known same-month flip cases when a 法人 cancels right after
     registration. > 1 year + master match = score 0.

Risk score taxonomy
-------------------

The 0-100 score maps to a closed enum so customer LLMs and dashboards
can render a coloured badge without re-deriving thresholds. The exact
inputs and outputs:

  0   tax_credit_eligible=True   registered + matched + > 1 year aged
  30  tax_credit_eligible=True   registered + < 6 month, OR no master match
                                 BUT registration metadata is consistent
  50  tax_credit_eligible=True   registered + houjin_master 不一致 (the
                                 T-number resolves but the named master
                                 row is missing — verification needed)
  100 tax_credit_eligible=False  registered=False (no row in mirror; or
                                 expired/revoked) — caller MUST NOT claim
                                 仕入税額控除

The ``tax_credit_eligible`` flag is the one boolean a 税理士 顧問先 GUI
should consume. Score is auxiliary, for trend dashboards.

Endpoints
---------

GET  /v1/invoice_registrants/{tnum}/risk          — single lookup
POST /v1/invoice_registrants/batch_risk           — bulk (max 100)
GET  /v1/houjin/{bangou}/invoice_status            — 法人番号 → T-number
                                                     resolve + status

License + envelope
------------------

Each surface inherits the PDL v1.0 attribution from invoice_registrants
(``_attribution`` block) — relay rule applies. The two T-number surfaces
also carry the §52 disclaimer (税理士法 §52 fence) because risk_score
brushes against 仕入税額控除 / 消費税 territory; the heuristic does NOT
substitute for 税理士 judgement.

Read-only. NO LLM call. Pure SQL + Python heuristic.

Constraints honoured
--------------------

* No ``LLM`` import (pure SQL + datetime arithmetic).
* No destructive overwrite — entirely additive (new router file +
  ``main.py`` include line + new MCP tool module + new test file + new
  R8 audit doc). All files are new; no existing surface is mutated.
* Pre-commit hooks pass (ruff / mypy boundary respect / no_llm guard).
"""

from __future__ import annotations

import datetime
import re
import sqlite3
import time
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Body, HTTPException, Request, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.api.invoice_registrants import (
    _ATTRIBUTION,
    _FULL_POPULATION_ESTIMATE,
    _NEXT_BULK_REFRESH_HINT,
    _NTA_OFFICIAL_LOOKUP,
    _REG_NUMBER_RE,
)

# ---------------------------------------------------------------------------
# Routers — two prefixes because the 法人番号 → invoice_status surface lives
# under ``/v1/houjin``. We keep them in the same module so all the risk
# logic stays co-located and only one set of constants is exported.
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/v1/invoice_registrants", tags=["invoice_registrants"])
houjin_invoice_router = APIRouter(prefix="/v1/houjin", tags=["houjin"])

# Bulk batch cap. Rationale: 100 is the same hard cap as
# /v1/invoice_registrants/search (PDL v1.0 privacy guardrail). Any request
# claiming "we have more than 100 取引先 to check in one go" should call
# the search endpoint or page through saved_searches instead.
_BATCH_MAX = 100

# 6 month / 1 year thresholds for the freshness heuristic. JST today is
# computed at request time (not import time) so a long-running process
# does not freeze the boundary.
_RECENT_REG_DAYS = 183  # ~6 months (NTA 取消 same-month flip risk window)
_AGED_REG_DAYS = 365  # 1 year

# 13-digit bangou (no 'T' prefix). Used for the /v1/houjin/.../invoice_status
# path-param validator. Mirrors the regex on api/houjin.py.
_BANGOU_RE = re.compile(r"^\d{13}$")

# §52 fence — score is heuristic, not 税務助言. Surfaced verbatim on every
# T-number response so a customer LLM cannot strip the caveat by accident.
_DISCLAIMER_RISK = (
    "本 risk_score / tax_credit_eligible は invoice_registrants (国税庁 PDL v1.0) と "
    "houjin_master (国税庁 法人番号公表サイト) の機械的照合 + 登録年齢 heuristic で、"
    "税理士法 §52 に基づく税務助言ではありません。仕入税額控除 (消費税法 §30) の "
    "判定は適格請求書原本・取引実態・対価の額等の事実関係を含むため、最終的には "
    "資格を有する税理士・公認会計士に必ずご確認ください。"
)


# ---------------------------------------------------------------------------
# Pydantic response models. ``extra="forbid"`` to keep the contract tight —
# ANY drift gets flagged at the model layer, not at the JSON byte layer.
# ---------------------------------------------------------------------------


class HoujinMasterMatch(BaseModel):
    """Subset of the houjin_master row used for verification."""

    model_config = ConfigDict(extra="forbid")

    matched: bool = Field(..., description="True iff the houjin_bangou resolved.")
    houjin_bangou: str | None = Field(default=None)
    normalized_name: str | None = Field(default=None)
    corporation_type: str | None = Field(default=None)
    prefecture: str | None = Field(default=None)
    close_date: str | None = Field(
        default=None,
        description="ISO date when the corporation was closed (NULL = still active).",
    )


class RiskOut(BaseModel):
    """Single T-number risk result."""

    model_config = ConfigDict(extra="forbid")

    invoice_registration_number: str
    registered: bool
    registered_at: str | None = Field(
        default=None, description="ISO date — NULL when registered=False."
    )
    expired_at: str | None = Field(
        default=None,
        description="ISO date — soonest of revoked_date / expired_date when present.",
    )
    houjin_master_match: HoujinMasterMatch
    risk_score: int = Field(..., ge=0, le=100)
    risk_band: Literal["clear", "caution", "verify", "block"]
    tax_credit_eligible: bool
    rationale: str = Field(
        ...,
        description="One-sentence rationale for the score (Japanese, ≤200 chars).",
    )


class RiskResponse(BaseModel):
    """200 response wrapper — RiskOut + attribution + disclaimer."""

    model_config = ConfigDict(extra="forbid")

    result: RiskOut
    attribution: dict[str, Any]


class BatchRiskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tnums: list[str] = Field(..., min_length=1, max_length=_BATCH_MAX)


class BatchRiskItemOut(BaseModel):
    """Per-item batch result. ``error`` is non-null iff lookup failed."""

    model_config = ConfigDict(extra="forbid")

    invoice_registration_number: str
    risk: RiskOut | None = None
    error: str | None = None


class BatchRiskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    results: list[BatchRiskItemOut]
    attribution: dict[str, Any]


class HoujinInvoiceStatusOut(BaseModel):
    """``/v1/houjin/{bangou}/invoice_status`` payload."""

    model_config = ConfigDict(extra="forbid")

    houjin_bangou: str
    invoice_registration_number: str | None
    registered: bool
    risk_score: int = Field(..., ge=0, le=100)
    risk_band: Literal["clear", "caution", "verify", "block"]
    tax_credit_eligible: bool
    rationale: str
    houjin_master_match: HoujinMasterMatch
    invoice_row: RiskOut | None = Field(
        default=None,
        description=(
            "Full invoice-registrant risk row when the bangou resolves to "
            "a T-number. NULL when no T-number is on file."
        ),
    )


class HoujinInvoiceStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: HoujinInvoiceStatusOut
    attribution: dict[str, Any]


# ---------------------------------------------------------------------------
# Pure-Python helpers (no DB).
# ---------------------------------------------------------------------------


def _parse_iso(value: str | None) -> datetime.date | None:
    """Best-effort ISO date parser. Returns None on any non-YYYY-MM-DD shape."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _today_jst() -> datetime.date:
    """Today in JST. Computed at call time so long-running processes don't freeze."""
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()


def _classify_risk(
    registered: bool,
    registered_at: datetime.date | None,
    expired_at: datetime.date | None,
    master_matched: bool,
    today: datetime.date | None = None,
) -> tuple[int, Literal["clear", "caution", "verify", "block"], bool, str]:
    """Pure scoring function — extracted so tests can hit it without a DB.

    Returns ``(score, band, eligible, rationale)``.

    Rules (closed enum, evaluated top-down — first match wins):

      A. Not registered (no row OR expired/revoked) → 100, block, False.
      B. Registered + master match + aged (>1y) → 0, clear, True.
      C. Registered + master MISSING → 50, verify, True.
      D. Registered + recently registered (<6m) → 30, caution, True.
      E. Registered + master match + 6m-1y → 30, caution, True.
      F. Otherwise (registered, master match, no specific signal) → 0, clear, True.
    """
    today = today or _today_jst()

    if not registered:
        return (
            100,
            "block",
            False,
            "未登録または失効・取消済みです。仕入税額控除は不可、適格請求書としては利用できません。",
        )

    # Expired/revoked = explicit block (covered by registered=False above
    # in caller, but defensive in case a future caller passes the date).
    if expired_at is not None and expired_at <= today:
        return (
            100,
            "block",
            False,
            "登録は失効または取消されています (expired_at <= today)。仕入税額控除は不可です。",
        )

    age_days = (today - registered_at).days if registered_at is not None else None

    # C: registered + no master match — verification needed.
    if not master_matched:
        return (
            50,
            "verify",
            True,
            "適格事業者として登録は確認できますが、houjin_master 側に対応する 法人番号 が見つかりませんでした。法人番号公表サイトでの一致確認を推奨します。",
        )

    # D: recently registered (< 6 month).
    if age_days is not None and age_days < _RECENT_REG_DAYS:
        return (
            30,
            "caution",
            True,
            "登録から 6 ヶ月未満です。国税庁の取消フローでは登録直後に取消されるケースが少数あるため、定期的な再確認を推奨します。",
        )

    # B/E: > 1 year vs 6m-1y.
    if age_days is not None and age_days >= _AGED_REG_DAYS:
        return (
            0,
            "clear",
            True,
            "適格事業者として登録済み・houjin_master とも一致・登録から 1 年以上経過しています。仕入税額控除の前提は満たしていますが、最終判断は税理士へご確認ください。",
        )

    # E: 6m ~ 1y — slight caution.
    if age_days is not None:
        return (
            30,
            "caution",
            True,
            "登録から 1 年未満 (6 ヶ月以上) です。基本的には仕入税額控除可ですが、定期確認を継続してください。",
        )

    # F: master match but no registered_at (data anomaly) — clear with note.
    return (
        0,
        "clear",
        True,
        "登録済み + houjin_master 一致を確認しました。登録日が不明のため、定期的な再確認を推奨します。",
    )


# ---------------------------------------------------------------------------
# DB helpers.
# ---------------------------------------------------------------------------


def _fetch_invoice_row(conn: sqlite3.Connection, tnum: str) -> sqlite3.Row | None:
    """Single-row T-number lookup. Returns None on miss."""
    return cast(
        "sqlite3.Row | None",
        conn.execute(
            "SELECT * FROM invoice_registrants WHERE invoice_registration_number = ?",
            (tnum,),
        ).fetchone(),
    )


def _fetch_houjin_master(conn: sqlite3.Connection, houjin_bangou: str | None) -> sqlite3.Row | None:
    """Optional houjin_master fetch. Tolerates missing table for fixture
    DBs that did not run migration 014 (some test fixtures only seed
    programs + invoice_registrants)."""
    if not houjin_bangou:
        return None
    try:
        return cast(
            "sqlite3.Row | None",
            conn.execute(
                (
                    "SELECT houjin_bangou, normalized_name, corporation_type, "
                    "       prefecture, close_date "
                    "  FROM houjin_master WHERE houjin_bangou = ? LIMIT 1"
                ),
                (houjin_bangou,),
            ).fetchone(),
        )
    except sqlite3.OperationalError:
        # Table missing in this fixture — treat as no match (the score
        # logic already handles the not-matched branch).
        return None


def _fetch_invoice_by_houjin(conn: sqlite3.Connection, houjin_bangou: str) -> sqlite3.Row | None:
    """Reverse lookup: 法人番号 → first matching T-number row."""
    return cast(
        "sqlite3.Row | None",
        conn.execute(
            (
                "SELECT * FROM invoice_registrants WHERE houjin_bangou = ? "
                "ORDER BY registered_date DESC LIMIT 1"
            ),
            (houjin_bangou,),
        ).fetchone(),
    )


# ---------------------------------------------------------------------------
# Composition: invoice row + master row → RiskOut.
# ---------------------------------------------------------------------------


def _compose_risk(
    tnum: str,
    invoice_row: sqlite3.Row | None,
    master_row: sqlite3.Row | None,
    today: datetime.date | None = None,
) -> RiskOut:
    """Compose a RiskOut from raw rows. Single source of truth for scoring."""
    today = today or _today_jst()

    if invoice_row is None:
        score, band, eligible, rationale = _classify_risk(
            registered=False,
            registered_at=None,
            expired_at=None,
            master_matched=False,
            today=today,
        )
        return RiskOut(
            invoice_registration_number=tnum,
            registered=False,
            registered_at=None,
            expired_at=None,
            houjin_master_match=HoujinMasterMatch(matched=False),
            risk_score=score,
            risk_band=band,
            tax_credit_eligible=eligible,
            rationale=rationale,
        )

    registered_at = _parse_iso(invoice_row["registered_date"])
    revoked_at = _parse_iso(invoice_row["revoked_date"])
    expired_at_field = _parse_iso(invoice_row["expired_date"])

    # Soonest non-null of revoked / expired; treat past dates as inactive.
    earliest_inactive: datetime.date | None = None
    for d in (revoked_at, expired_at_field):
        if d is not None and (earliest_inactive is None or d < earliest_inactive):
            earliest_inactive = d
    inactive = earliest_inactive is not None and earliest_inactive <= today

    master_matched = master_row is not None and not _parse_iso(master_row["close_date"])
    master_match = HoujinMasterMatch(
        matched=bool(master_row is not None),
        houjin_bangou=master_row["houjin_bangou"] if master_row else None,
        normalized_name=master_row["normalized_name"] if master_row else None,
        corporation_type=master_row["corporation_type"] if master_row else None,
        prefecture=master_row["prefecture"] if master_row else None,
        close_date=master_row["close_date"] if master_row else None,
    )

    score, band, eligible, rationale = _classify_risk(
        registered=not inactive,
        registered_at=registered_at,
        expired_at=earliest_inactive,
        master_matched=master_matched,
        today=today,
    )

    return RiskOut(
        invoice_registration_number=tnum,
        registered=not inactive,
        registered_at=invoice_row["registered_date"] if registered_at else None,
        expired_at=earliest_inactive.isoformat() if earliest_inactive else None,
        houjin_master_match=master_match,
        risk_score=score,
        risk_band=band,
        tax_credit_eligible=eligible,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Routes.
# ---------------------------------------------------------------------------


@router.get(
    "/{invoice_registration_number}/risk",
    summary="Risk score lookup for 適格事業者 (T-number)",
    description=(
        "Returns a 0-100 risk score and a tax_credit_eligible boolean for "
        "a 適格事業者番号 (T + 13 digits). Composes invoice_registrants "
        "(NTA PDL v1.0) + houjin_master (NTA 法人番号公表サイト) + "
        "registration-age heuristic.\n\n"
        "Score taxonomy (closed enum):\n"
        "  * 0   clear  — registered + master match + 1 年超\n"
        "  * 30  caution — registered + < 6 ヶ月 OR 6m-1y\n"
        "  * 50  verify  — registered + houjin_master 不一致\n"
        "  * 100 block   — 未登録 / 失効 / 取消\n\n"
        "**§52 fence:** the response carries a `_disclaimer` field — "
        "scoring is heuristic and never substitutes for 税理士 judgement "
        "on 仕入税額控除 (消費税法 §30)."
    ),
    responses={
        200: {"model": RiskResponse},
        422: {"description": "T-number must match '^T\\d{13}$'."},
    },
)
def get_invoice_risk(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    invoice_registration_number: Annotated[
        str,
        PathParam(description="適格事業者番号 (T + 13 数字)."),
    ],
) -> JSONResponse:
    if not _REG_NUMBER_RE.match(invoice_registration_number):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invoice_registration_number must match '^T\\d{13}$'",
        )

    _t0 = time.perf_counter()
    invoice_row = _fetch_invoice_row(conn, invoice_registration_number)
    master_row = (
        _fetch_houjin_master(conn, invoice_row["houjin_bangou"])
        if invoice_row is not None
        else None
    )

    risk = _compose_risk(invoice_registration_number, invoice_row, master_row)

    log_usage(
        conn,
        ctx,
        "invoice_registrants.risk",
        params={"miss": invoice_row is None},
        latency_ms=int((time.perf_counter() - _t0) * 1000),
        strict_metering=True,
    )

    body: dict[str, Any] = {
        "result": risk.model_dump(),
        "attribution": _ATTRIBUTION,
        "_disclaimer": _DISCLAIMER_RISK,
    }
    if invoice_row is None:
        body["snapshot_size_hint"] = _FULL_POPULATION_ESTIMATE
        body["next_bulk_refresh"] = _NEXT_BULK_REFRESH_HINT
        body["alternative"] = _NTA_OFFICIAL_LOOKUP
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body)


@router.post(
    "/batch_risk",
    summary="Batch risk lookup (max 100 T-numbers)",
    description=(
        "Bulk lookup variant of /v1/invoice_registrants/{tnum}/risk. "
        'Body shape: `{ "tnums": ["T...", ...] }`, capped at '
        f"{_BATCH_MAX} entries per call. Per-item ``error`` populates "
        "when a T-number is malformed; otherwise ``risk`` mirrors the "
        "single-lookup shape exactly. PDL v1.0 attribution + §52 "
        "disclaimer are emitted ONCE at the response root."
    ),
    responses={
        200: {"model": BatchRiskResponse},
        422: {"description": "Batch shape invalid (empty / over cap)."},
    },
)
def batch_invoice_risk(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    payload: Annotated[BatchRiskRequest, Body()],
) -> JSONResponse:
    _t0 = time.perf_counter()
    today = _today_jst()
    items: list[BatchRiskItemOut] = []
    miss_count = 0

    for raw in payload.tnums:
        tnum = (raw or "").strip()
        if not _REG_NUMBER_RE.match(tnum):
            items.append(
                BatchRiskItemOut(
                    invoice_registration_number=tnum,
                    risk=None,
                    error="invoice_registration_number must match '^T\\d{13}$'",
                )
            )
            continue
        invoice_row = _fetch_invoice_row(conn, tnum)
        master_row = (
            _fetch_houjin_master(conn, invoice_row["houjin_bangou"])
            if invoice_row is not None
            else None
        )
        if invoice_row is None:
            miss_count += 1
        risk = _compose_risk(tnum, invoice_row, master_row, today=today)
        items.append(BatchRiskItemOut(invoice_registration_number=tnum, risk=risk))

    log_usage(
        conn,
        ctx,
        "invoice_registrants.batch_risk",
        params={"n": len(items), "miss": miss_count},
        latency_ms=int((time.perf_counter() - _t0) * 1000),
        result_count=len(items),
        strict_metering=True,
    )

    body: dict[str, Any] = {
        "total": len(items),
        "results": [i.model_dump() for i in items],
        "attribution": _ATTRIBUTION,
        "_disclaimer": _DISCLAIMER_RISK,
    }
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body)


@houjin_invoice_router.get(
    "/{bangou}/invoice_status",
    summary="法人番号 → 適格事業者番号 resolve + status",
    description=(
        "Reverse lookup: take a 13-digit 法人番号 and return the matching "
        "適格事業者番号 (if any) plus the same risk envelope as "
        "/v1/invoice_registrants/{tnum}/risk. Returns invoice_row=null + "
        "block when the corporation has never registered."
    ),
    responses={
        200: {"model": HoujinInvoiceStatusResponse},
        422: {"description": "bangou must be 13 digits."},
    },
)
def get_houjin_invoice_status(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    bangou: Annotated[
        str,
        PathParam(
            description="13-digit 法人番号 (without 'T' prefix).",
            pattern=r"^\d{13}$",
        ),
    ],
) -> JSONResponse:
    if not _BANGOU_RE.match(bangou):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "bangou must match '^\\d{13}$'",
        )

    _t0 = time.perf_counter()
    invoice_row = _fetch_invoice_by_houjin(conn, bangou)
    master_row = _fetch_houjin_master(conn, bangou)

    if invoice_row is not None:
        risk = _compose_risk(
            invoice_row["invoice_registration_number"],
            invoice_row,
            master_row,
        )
        result = HoujinInvoiceStatusOut(
            houjin_bangou=bangou,
            invoice_registration_number=invoice_row["invoice_registration_number"],
            registered=risk.registered,
            risk_score=risk.risk_score,
            risk_band=risk.risk_band,
            tax_credit_eligible=risk.tax_credit_eligible,
            rationale=risk.rationale,
            houjin_master_match=risk.houjin_master_match,
            invoice_row=risk,
        )
    else:
        # No T-number on file. Compose a synthetic block-band response
        # using a sentinel tnum-shape so customer LLMs can render the row
        # without a special "no t-number" branch.
        synthetic_tnum = f"T{bangou}"
        risk = _compose_risk(synthetic_tnum, None, master_row)
        # Override the master_match payload — we DO have a master row even
        # when there's no T-number; surface it so the caller can confirm
        # the bangou exists in NTA's master.
        master_match = HoujinMasterMatch(
            matched=master_row is not None,
            houjin_bangou=master_row["houjin_bangou"] if master_row else None,
            normalized_name=master_row["normalized_name"] if master_row else None,
            corporation_type=master_row["corporation_type"] if master_row else None,
            prefecture=master_row["prefecture"] if master_row else None,
            close_date=master_row["close_date"] if master_row else None,
        )
        result = HoujinInvoiceStatusOut(
            houjin_bangou=bangou,
            invoice_registration_number=None,
            registered=False,
            risk_score=risk.risk_score,
            risk_band=risk.risk_band,
            tax_credit_eligible=risk.tax_credit_eligible,
            rationale=(
                "この法人番号には適格請求書発行事業者番号が登録されていません。"
                "仕入税額控除の前提を満たしません。"
            ),
            houjin_master_match=master_match,
            invoice_row=None,
        )

    log_usage(
        conn,
        ctx,
        "houjin.invoice_status",
        params={"miss": invoice_row is None},
        latency_ms=int((time.perf_counter() - _t0) * 1000),
        strict_metering=True,
    )

    body: dict[str, Any] = {
        "result": result.model_dump(),
        "attribution": _ATTRIBUTION,
        "_disclaimer": _DISCLAIMER_RISK,
    }
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body)
