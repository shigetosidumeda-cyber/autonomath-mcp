"""REST handlers for the advisor matching and Evidence-to-Expert Handoff surface.

Backed by migration 024's ``advisors`` + ``advisor_referrals`` tables and
migration 195's handoff ledger. The public product position is:

    API core: users and AI agents fetch evidence packets per request.
    Advisors: users can carry an evidence brief to a qualified professional.
              Non-lawyer advisor categories may use a tracked referral flow;
              lawyer categories are excluded from success-fee tracking.

Flow:
    1. Advisor discovers /advisors.html landing, clicks signup.
    2. POST /v1/advisors/signup creates an unverified row (verified_at NULL).
    3. Stripe Connect Express onboarding in the browser; on return we
       stash stripe_connect_account_id. POST /v1/advisors/verify-houjin/{id}
       then confirms the 法人番号 against invoice_registrants and provisionally
       flips verified_at.
    4. Search surface (/v1/programs/search?include_advisors=true) and
       /v1/advisors/handoffs/preview call
       query_matching_advisors() to attach up to 3 matches.
    5. User explicitly consents to contact an eligible advisor, then
       /v1/advisors/track mints a single-use
       referral_token, returns a redirect URL.
    6. Advisor reports conversion → /v1/advisors/report-conversion sets
       converted_at + commission_yen.
    7. Payout cron (future) runs Stripe Transfer, sets commission_paid_at.

Compliance notes:
    * 士業法 — each profession restricts commercial referrals differently.
      The signup and tracking paths keep lawyer success-fee flows out of
      self-serve referral tracking.
    * 景表法 — ranking methodology disclosed (/advisors.html §ranking).
    * APPI — houjin_bangou is public for incorporated entities. No 個人番号.
      ip_hash (salted sha256), not raw IP, on referral rows.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import sqlite3
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator

from jpintel_mcp.api._response_models import AdvisorDashboardResponse
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.api.vocab import _is_known_prefecture, _normalize_prefecture
from jpintel_mcp.config import settings

router = APIRouter(prefix="/v1/advisors", tags=["advisors"])

_log = logging.getLogger("jpintel.advisors")


# ---------------------------------------------------------------------------
# Enums & validation helpers
# ---------------------------------------------------------------------------

FirmType = Literal[
    "税理士法人",
    "認定支援機関",
    "社会保険労務士",
    "中小企業診断士",
    "行政書士",
    "弁護士",
    "銀行",
    "商工会議所",
    "その他",
]

# Specialty enum kept in sync with the signup form checkboxes. Extending
# the set is a schema-compatible change (values stored as a JSON array in
# specialties_json), but keep it tight — matching ranks on exact equality
# and a sprawling vocabulary weakens rank quality.
Specialty = Literal[
    "subsidy",  # 補助金
    "loan",  # 融資
    "tax",  # 税制
    "enforcement_defense",  # 行政処分 / 不利益処分対応
    "invoice",  # インボイス制度
    "ebook",  # 電帳法 / 電子帳簿保存法
]

Industry = Literal[
    "agriculture_forestry",
    "manufacturing",
    "manufacture",
    "it",
    "service",
    "construction",
    "retail",
]

_INDUSTRY_ALIASES = {
    "agri": "agriculture_forestry",
    "manufacture": "manufacturing",
}
_CANONICAL_INDUSTRIES = {
    "agriculture_forestry",
    "manufacturing",
    "it",
    "service",
    "construction",
    "retail",
}

CommissionModel = Literal["flat", "percent"]

_HOUJIN_BANGOU_RE = re.compile(r"^\d{13}$")
_REFERRAL_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_DASHBOARD_TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
_HANDOFF_PROFESSIONAL_BOUNDARY = (
    "このプレビューは士業候補への情報連携案です。個別の税務・法務・労務判断ではなく、"
    "最終判断と顧客への助言は有資格者または担当専門家の確認を前提とします。"
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _hash_ip(ip: str | None) -> str | None:
    """Salted sha256 of the caller IP for fraud detection.

    Raw IP is NOT stored (APPI minimization). The salt is
    ``settings.api_key_salt`` (already used for hash_api_key) so an
    operator rotating the salt invalidates retention-era ip_hash values —
    which is the desired behavior.
    """
    if not ip:
        return None
    return hashlib.sha256((settings.api_key_salt + ip).encode("utf-8")).hexdigest()


def _advisor_dashboard_token(advisor_id: int, contact_email: str | None = None) -> str:
    """Stable signed bearer token for the advisor self-serve dashboard URL."""
    message = f"advisor-dashboard|{advisor_id}|{contact_email or ''}".encode()
    return hmac.new(
        settings.api_key_salt.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()


def _verify_advisor_dashboard_token(
    advisor_id: int,
    contact_email: str | None,
    token: str | None,
) -> bool:
    if token is None or not _DASHBOARD_TOKEN_RE.match(token):
        return False
    expected = _advisor_dashboard_token(advisor_id, contact_email)
    return hmac.compare_digest(token, expected)


def _normalize_industry_or_422(industry: str | None) -> str | None:
    industry_norm = _INDUSTRY_ALIASES.get(industry, industry) if industry else None
    if industry_norm is not None and industry_norm not in _CANONICAL_INDUSTRIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unsupported industry: {industry}",
        )
    return industry_norm


def _known_gap_summary(gap: str | dict[str, Any]) -> str | None:
    if isinstance(gap, str):
        return gap
    for key in ("message_ja", "message", "gap_id", "section"):
        value = gap.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "structured_gap"


def _build_handoff_summary(payload: HandoffPreviewRequest) -> str:
    lines = [payload.summary]
    gap_summaries = [
        summary for gap in payload.known_gaps if (summary := _known_gap_summary(gap)) is not None
    ]
    if gap_summaries:
        lines.append("未確認事項: " + " / ".join(gap_summaries))
    lines.append("人手レビュー: " + ("必要" if payload.human_review_required else "不要"))
    lines.append(f"根拠レシート: {len(payload.source_receipts)}件")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pydantic I/O models
# ---------------------------------------------------------------------------


class AdvisorOut(BaseModel):
    """Public-facing advisor row. Excludes internal-only columns
    (stripe_connect_account_id, disabled_reason, raw success_count math)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    firm_name: str
    firm_name_kana: str | None = None
    firm_type: FirmType
    specialties: list[str]
    industries: list[str] | None = None
    prefecture: str
    city: str | None = None
    address: str | None = None
    contact_url: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    intro_blurb: str | None = None
    success_count: int = 0
    commission_model: CommissionModel = "flat"
    commission_yen_per_intro: int | None = 3000
    commission_rate_pct: int = 5
    verified_at: str | None = None


class MatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    results: list[AdvisorOut]
    ranking: dict[str, str] = Field(
        default_factory=lambda: {
            "method": "practice area, industry, region, and deterministic registration tie-break",
            "disclosure": (
                "候補表示順は掲載費、成約額、受任額、成約件数では上下しません。"
                "地域・業種・支援領域の一致度で並べ替えています。"
            ),
        }
    )


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    firm_name: str = Field(..., min_length=1, max_length=200)
    firm_name_kana: str | None = Field(default=None, max_length=200)
    houjin_bangou: str = Field(..., description="13 digits")
    firm_type: FirmType
    specialties: list[Specialty] = Field(..., min_length=1, max_length=6)
    industries: list[Industry] | None = Field(default=None, max_length=6)
    prefecture: str = Field(..., description="canonical ('東京都')")
    city: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=500)
    contact_url: HttpUrl | None = None
    contact_email: EmailStr
    contact_phone: str | None = Field(default=None, max_length=30)
    intro_blurb: str | None = Field(default=None, max_length=400)
    # Commission defaults to flat ¥3,000. Advisors can pick percent at signup
    # but the value is immutable afterwards without a re-verification pass.
    commission_model: CommissionModel = "flat"
    commission_rate_pct: int = Field(default=5, ge=1, le=30)
    commission_yen_per_intro: int = Field(default=3000, ge=100, le=100_000)
    # 特商法 + 士業法 自己確認 disclosure — front-end surfaces the checkbox
    # and the API rejects signups that don't affirm it. Purely paperwork
    # signal; we do not re-verify the 士業資格 itself.
    agreed_to_terms: bool = Field(..., description="must be true")

    @field_validator("houjin_bangou")
    @classmethod
    def _valid_houjin(cls, v: str) -> str:
        if not _HOUJIN_BANGOU_RE.match(v):
            raise ValueError("houjin_bangou must be 13 digits")
        return v

    @field_validator("industries", mode="before")
    @classmethod
    def _normalize_industries(cls, v: Any) -> Any:
        if isinstance(v, list):
            return [_INDUSTRY_ALIASES.get(str(item), item) for item in v]
        return v

    @field_validator("agreed_to_terms")
    @classmethod
    def _must_agree(cls, v: bool) -> bool:
        if not v:
            raise ValueError("agreed_to_terms must be true")
        return v


class SignupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advisor_id: int
    next_step: Literal["stripe_connect"] = "stripe_connect"
    stripe_connect_onboarding_url: str | None = Field(
        default=None,
        description=(
            "Returned when Stripe onboarding is available. Null when onboarding "
            "cannot be started immediately; the signup record is still created "
            "so the advisor can retry."
        ),
    )


class TrackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advisor_id: int
    source_query_hash: str | None = None
    source_program_id: str | None = Field(default=None, max_length=120)
    consent_granted: bool = Field(
        default=False,
        description=(
            "Must be true after the user explicitly agrees to leave the evidence "
            "handoff surface and contact this advisor. No referral token is minted "
            "before consent."
        ),
    )


class TrackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    redirect_url: str


class ReportConversionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referral_token: str
    conversion_value_yen: int | None = Field(default=None, ge=0)
    evidence_url: HttpUrl | None = None

    @field_validator("referral_token")
    @classmethod
    def _valid_token(cls, v: str) -> str:
        if not _REFERRAL_TOKEN_RE.match(v):
            raise ValueError("referral_token must be 32 hex chars")
        return v


class HandoffPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefecture: str = Field(..., min_length=1, max_length=40)
    industry: str | None = Field(default=None, max_length=80)
    specialty: Specialty | None = None
    known_gaps: list[str | dict[str, Any]] = Field(default_factory=list, max_length=20)
    human_review_required: bool = False
    source_receipts: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    summary: str = Field(..., min_length=1, max_length=2000)

    @field_validator("industry", mode="before")
    @classmethod
    def _blank_industry_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("known_gaps")
    @classmethod
    def _clean_known_gaps(cls, v: list[str | dict[str, Any]]) -> list[str | dict[str, Any]]:
        cleaned: list[str | dict[str, Any]] = []
        for item in v:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    cleaned.append(text)
            else:
                cleaned.append(item)
        too_long = [item for item in cleaned if isinstance(item, str) and len(item) > 240]
        if too_long:
            raise ValueError("known_gaps items must be 240 characters or fewer")
        return cleaned

    @field_validator("summary")
    @classmethod
    def _clean_summary(cls, v: str) -> str:
        summary = v.strip()
        if not summary:
            raise ValueError("summary must not be blank")
        return summary


class HandoffDisplayOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paid_influence: Literal[False] = False
    method: Literal["match_quality_then_registration_order"] = (
        "match_quality_then_registration_order"
    )


class HandoffPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handoff_summary: str
    professional_boundary: str
    matched_advisors: list[AdvisorOut]
    display_order: HandoffDisplayOrder = Field(default_factory=HandoffDisplayOrder)


# ---------------------------------------------------------------------------
# Row -> Pydantic
# ---------------------------------------------------------------------------


def _load_json_array(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(val, list):
        return []
    return [_INDUSTRY_ALIASES.get(str(x), str(x)) for x in val]


def _row_to_advisor(row: sqlite3.Row) -> AdvisorOut:
    return AdvisorOut(
        id=row["id"],
        firm_name=row["firm_name"],
        firm_name_kana=row["firm_name_kana"],
        firm_type=row["firm_type"],
        specialties=_load_json_array(row["specialties_json"]),
        industries=_load_json_array(row["industries_json"]) or None,
        prefecture=row["prefecture"],
        city=row["city"],
        address=row["address"],
        contact_url=row["contact_url"],
        contact_email=row["contact_email"],
        contact_phone=row["contact_phone"],
        intro_blurb=row["intro_blurb"],
        success_count=row["success_count"],
        commission_model=row["commission_model"],
        commission_yen_per_intro=row["commission_yen_per_intro"],
        commission_rate_pct=row["commission_rate_pct"],
        verified_at=row["verified_at"],
    )


# ---------------------------------------------------------------------------
# Core matching — also called from programs.py via query_matching_advisors()
# ---------------------------------------------------------------------------


def query_matching_advisors(
    conn: sqlite3.Connection,
    prefecture: str | None,
    industry: str | None = None,
    specialty: str | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return up to ``limit`` verified+active advisors ranked by match strength.

    Ranking (higher is better):
        1. prefecture exact match
        2. industry appears in industries_json
        3. specialty appears in specialties_json
        4. id asc (deterministic tie-break)

    Soft-match semantics: a NULL filter dimension contributes 0 to the score.
    We deliberately return fewer than ``limit`` rows rather than widening
    the net — surfacing an Osaka advisor on a 北海道 search is worse than
    surfacing none, because the advisor pays per-referral and we'd burn
    their budget on irrelevant clicks.

    Callable from programs.py without going through HTTP — that's why this
    lives at module top-level, not as a method on a router.
    """
    if limit < 1:
        limit = 1
    if limit > 10:
        limit = 10

    pref_canon = _normalize_prefecture(prefecture)

    # Score is computed in SQL to keep the hot path index-friendly. The
    # CASE expressions each yield 0 or a positive weight; ORDER BY score
    # DESC puts the best match first. Weights are ordinal (pref >> industry
    # >> specialty) so no ambiguity between two different 2-dim matches.
    score_parts: list[str] = []
    params: list[Any] = []

    if pref_canon:
        score_parts.append("(CASE WHEN prefecture = ? THEN 100 ELSE 0 END)")
        params.append(pref_canon)
    if industry:
        # JSON LIKE match. Keep the legacy agriculture slug as a read alias
        # so existing rows still rank while public inputs use the clearer
        # agriculture_forestry value.
        industry_slugs = [industry]
        if industry == "agriculture_forestry":
            industry_slugs.append("agri")
        elif industry == "manufacturing":
            industry_slugs.append("manufacture")
        like_parts = " OR ".join("industries_json LIKE ?" for _ in industry_slugs)
        score_parts.append(f"(CASE WHEN {like_parts} THEN 20 ELSE 0 END)")
        params.extend(f'%"{slug}"%' for slug in industry_slugs)
    if specialty:
        score_parts.append("(CASE WHEN specialties_json LIKE ? THEN 10 ELSE 0 END)")
        params.append(f'%"{specialty}"%')

    score_sql = " + ".join(score_parts) if score_parts else "0"

    # WHERE: verified + active only. Pre-filter prefecture when specified —
    # with the hard "no cross-prefecture spill" rule above, this is an
    # index hit via idx_advisors_prefecture, much tighter than scoring the
    # whole table.
    where_parts = ["verified_at IS NOT NULL", "active = 1"]
    if pref_canon:
        where_parts.append("prefecture = ?")
        params.append(pref_canon)

    sql = (
        f"SELECT *, ({score_sql}) AS _score FROM advisors "
        f"WHERE {' AND '.join(where_parts)} "
        f"ORDER BY _score DESC, id ASC "
        f"LIMIT ?"
    )
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_advisor(r).model_dump() for r in rows]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/match",
    responses={200: {"model": MatchResponse}},
)
def match_advisors(
    conn: DbDep,
    ctx: ApiContextDep,
    prefecture: Annotated[
        str | None,
        Query(description="都道府県. Accepts canonical, short, or romaji."),
    ] = None,
    specialty: Annotated[Specialty | None, Query()] = None,
    industry: Annotated[
        str | None,
        Query(
            description=(
                "Industry slug. Prefer agriculture_forestry or manufacturing; "
                "legacy agri/manufacture aliases are accepted."
            )
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=10)] = 3,
) -> JSONResponse:
    """Top ``limit`` advisors matching the supplied filters.

    Returns public advisor profile fields and a deterministic match score.
    """
    industry_norm = _normalize_industry_or_422(industry)
    results = query_matching_advisors(
        conn,
        prefecture=prefecture,
        industry=industry_norm,
        specialty=specialty,
        limit=limit,
    )
    log_usage(conn, ctx, "advisors.match", strict_metering=True)
    return JSONResponse(
        content={
            "total": len(results),
            "results": results,
            "ranking": {
                "method": (
                    "practice area, industry, region, and deterministic registration tie-break"
                ),
                "disclosure": (
                    "候補表示順は掲載費、成約額、受任額、成約件数では上下しません。"
                    "地域・業種・支援領域の一致度で並べ替えています。"
                ),
            },
        }
    )


@router.post(
    "/handoffs/preview",
    response_model=HandoffPreviewResponse,
)
def preview_advisor_handoff(
    payload: HandoffPreviewRequest,
    conn: DbDep,
) -> JSONResponse:
    """Preview an advisor handoff without creating referrals or stored records.

    This is a read-only handoff draft surface: it uses the existing advisor
    matcher, but intentionally does not mint referral tokens, store source
    receipts, write usage events, or persist caller-provided summary text.
    """
    if not _is_known_prefecture(payload.prefecture):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "prefecture unrecognized")
    pref_canon = _normalize_prefecture(payload.prefecture)

    matched = query_matching_advisors(
        conn,
        prefecture=pref_canon,
        industry=_normalize_industry_or_422(payload.industry),
        specialty=payload.specialty,
        limit=3,
    )
    body = HandoffPreviewResponse(
        handoff_summary=_build_handoff_summary(payload),
        professional_boundary=_HANDOFF_PROFESSIONAL_BOUNDARY,
        matched_advisors=[AdvisorOut.model_validate(m) for m in matched],
    ).model_dump(mode="json")
    return JSONResponse(content=body)


@router.post(
    "/track",
    responses={200: {"model": TrackResponse}},
)
def track_click(
    payload: TrackRequest,
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Record a referral click and mint a single-use redirect token.

    The returned ``redirect_url`` is ``advisor.contact_url`` with
    ``?ref=<token>`` appended, or a fallback to an in-domain contact page
    when the advisor didn't supply one. 5% or ¥3,000 commission (model
    dependent) is resolved at conversion time, not click time.
    """
    row = conn.execute(
        "SELECT id, contact_url, firm_type, verified_at, active FROM advisors WHERE id = ?",
        (payload.advisor_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "advisor not found")
    if row["verified_at"] is None or row["active"] != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "advisor not active or not verified")
    if row["firm_type"] == "弁護士":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "弁護士カテゴリでは成果課金型のreferral trackingを利用できません",
        )
    if not payload.consent_granted:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "advisor referral tracking requires explicit user consent",
        )

    token = secrets.token_hex(16)  # 32 hex chars
    ip = request.client.host if request.client else None
    conn.execute(
        "INSERT INTO advisor_referrals"
        " (referral_token, advisor_id, source_query_hash, source_program_id,"
        "  ip_hash, clicked_at)"
        " VALUES (?,?,?,?,?,?)",
        (
            token,
            payload.advisor_id,
            payload.source_query_hash,
            payload.source_program_id,
            _hash_ip(ip),
            _now_iso(),
        ),
    )

    base_url = row["contact_url"] or f"https://jpcite.com/advisors.html#a{row['id']}"
    sep = "&" if "?" in base_url else "?"
    redirect_url = f"{base_url}{sep}ref={token}"

    log_usage(conn, ctx, "advisors.track", strict_metering=True)
    return JSONResponse(content={"token": token, "redirect_url": redirect_url})


@router.post(
    "/signup",
    responses={
        200: {"model": SignupResponse},
        409: {"description": "houjin_bangou already registered"},
    },
)
def signup_advisor(
    payload: SignupRequest,
    conn: DbDep,
) -> JSONResponse:
    """Create an unverified advisor profile + return Stripe Connect onboarding URL.

    Self-serve, no API key required (prospective advisors don't have one
    yet). verified_at stays NULL until both:
      (a) /verify-houjin/{id} succeeds against invoice_registrants, AND
      (b) Stripe Connect account.updated webhook reports capabilities.transfers=active.

    For advisors seeded from the 中小企業庁 認定支援機関 public list,
    scripts/seed_advisors.py sets verified_at directly at seed time — this
    handler path is for self-serve signups only.
    """
    pref_canon = _normalize_prefecture(payload.prefecture)
    if pref_canon is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "prefecture unrecognized")
    if payload.firm_type == "弁護士" and payload.commission_model == "percent":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "弁護士案件では受任報酬比の手数料モデルをセルフサーブで選択できません",
        )

    existing = conn.execute(
        "SELECT id FROM advisors WHERE houjin_bangou = ?",
        (payload.houjin_bangou,),
    ).fetchone()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "houjin_bangou already registered; contact info@bookyou.net to reclaim",
        )

    now = _now_iso()
    cur = conn.execute(
        "INSERT INTO advisors"
        " (houjin_bangou, firm_name, firm_name_kana, firm_type, specialties_json,"
        "  industries_json, prefecture, city, address, contact_url, contact_email,"
        "  contact_phone, intro_blurb, commission_rate_pct, commission_yen_per_intro,"
        "  commission_model, source_url, source_fetched_at, active, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
        (
            payload.houjin_bangou,
            payload.firm_name,
            payload.firm_name_kana,
            payload.firm_type,
            json.dumps(payload.specialties, ensure_ascii=False),
            json.dumps(payload.industries, ensure_ascii=False) if payload.industries else None,
            pref_canon,
            payload.city,
            payload.address,
            str(payload.contact_url) if payload.contact_url else None,
            payload.contact_email,
            payload.contact_phone,
            payload.intro_blurb,
            payload.commission_rate_pct,
            payload.commission_yen_per_intro,
            payload.commission_model,
            "https://jpcite.com/advisors.html",
            now,
            now,
            now,
        ),
    )
    advisor_id = cur.lastrowid
    if advisor_id is None:
        raise RuntimeError("INSERT did not return a lastrowid")

    onboarding_url = _create_stripe_connect_onboarding(advisor_id, payload.contact_email)

    return JSONResponse(
        content={
            "advisor_id": advisor_id,
            "next_step": "stripe_connect",
            "stripe_connect_onboarding_url": onboarding_url,
        }
    )


def _create_stripe_connect_onboarding(advisor_id: int, email: str) -> str | None:
    """Create a Stripe Connect Express account + AccountLink for onboarding.

    Returns the hosted onboarding URL, or None when Stripe is not configured
    (dev / CI paths). A None return is NOT an error — the signup row is
    still created and the advisor can retry via a dashboard link later.
    """
    if not settings.stripe_secret_key:
        _log.warning(
            "stripe_not_configured advisor_id=%s skipping_connect_onboarding",
            advisor_id,
        )
        return None
    try:
        import stripe  # local import — stripe is heavy and optional for tests

        stripe.api_key = settings.stripe_secret_key
        if settings.stripe_api_version:
            stripe.api_version = settings.stripe_api_version

        acct = stripe.Account.create(
            type="express",
            country="JP",
            email=email,
            capabilities={
                # Express accounts in JP only need `transfers` for outbound
                # platform-to-advisor Transfer. We do NOT enable
                # card_payments (advisors aren't charging end users through
                # us; we're only paying them).
                "transfers": {"requested": True},
            },
            business_type="company",
            metadata={"advisor_id": str(advisor_id), "platform": "jpcite"},
        )

        link = stripe.AccountLink.create(
            account=acct.id,
            refresh_url=f"https://jpcite.com/advisors.html?stripe=refresh&advisor_id={advisor_id}",
            return_url=(
                "https://jpcite.com/advisors.html"
                f"?dashboard=1&advisor_id={advisor_id}&acct={acct.id}"
                f"&token={_advisor_dashboard_token(advisor_id, email)}"
            ),
            type="account_onboarding",
        )
        # Connection between advisor row and Stripe account is established
        # via the Connect webhook (account.updated) — not inlined here so
        # we don't depend on DB state from within the Stripe SDK call.
        return link.url
    except Exception:
        _log.exception("stripe_connect_create_failed advisor_id=%s", advisor_id)
        return None


@router.post(
    "/verify-houjin/{advisor_id}",
    responses={
        200: {"description": "verified"},
        404: {"description": "advisor not found"},
        422: {"description": "houjin_bangou not found in NTA registry"},
    },
)
def verify_houjin(advisor_id: int, conn: DbDep) -> JSONResponse:
    """Confirm the advisor's 法人番号 exists in invoice_registrants (migration 019).

    Provisional verification: sets advisors.verified_at to the current
    timestamp when the 法人番号 is found. Full verification still waits
    on Stripe Connect webhook reporting capabilities.transfers=active —
    query_matching_advisors() filters on verified_at alone today, so this
    provisional gate is the public-visibility switch.

    For 認定支援機関 rows seeded from the 中小企業庁 public list,
    seed_advisors.py sets verified_at directly and this endpoint is a
    no-op idempotent success.
    """
    row = conn.execute(
        "SELECT id, houjin_bangou, verified_at FROM advisors WHERE id = ?",
        (advisor_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "advisor not found")
    if row["verified_at"] is not None:
        return JSONResponse(
            content={"status": "already_verified", "verified_at": row["verified_at"]}
        )

    # Lookup in invoice_registrants. The schema stores houjin_bangou as a
    # nullable soft reference; sole-prop registrants have NULL. We require
    # a match on houjin_bangou (not on the registration number) so we
    # confirm "this legal entity exists" rather than "this specific invoice
    # registration exists". Either is fine for verification intent.
    try:
        found = conn.execute(
            "SELECT 1 FROM invoice_registrants WHERE houjin_bangou = ? LIMIT 1",
            (row["houjin_bangou"],),
        ).fetchone()
    except sqlite3.OperationalError:
        # invoice_registrants not migrated yet (e.g. fresh dev DB without
        # 019 applied). Fall back to "trust but flag" — verify anyway and
        # let the reviewer catch bad-faith entries out of band. This is
        # intentionally permissive: the Stripe Connect gate is the
        # real control for payout flow.
        found = None
        _log.warning("invoice_registrants_missing advisor_id=%s fallback_verify", advisor_id)

    if found is None:
        # No match — but for 認定支援機関 rows the 中小企業庁 list is the
        # authority, not NTA. Reject self-serve unverified rows with a
        # useful error; seeded rows never hit this path.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "houjin_bangou not found in 適格請求書発行事業者 registry. 登録後に再試行してください.",
        )

    now = _now_iso()
    conn.execute(
        "UPDATE advisors SET verified_at = ?, updated_at = ? WHERE id = ?",
        (now, now, advisor_id),
    )
    return JSONResponse(content={"status": "verified", "verified_at": now})


@router.post(
    "/stripe-connect-webhook",
    include_in_schema=False,
)
async def stripe_connect_webhook(request: Request, conn: DbDep) -> JSONResponse:
    """Handle Stripe Connect `account.updated` events.

    Flips `stripe_connect_account_id` onto the advisor row (keyed by
    ``metadata.advisor_id`` set at Account.create time). When
    ``capabilities.transfers == 'active'`` we also bump verified_at IF
    the 法人番号 has already been verified — this completes the two-stage
    verification gate (houjin lookup + Stripe payouts enabled).

    Unconfigured Stripe = 503 so the webhook registrar knows to retry.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Stripe not configured")
    try:
        import stripe

        stripe.api_key = settings.stripe_secret_key

        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")
        # Separate secret from the main billing webhook (STRIPE_WEBHOOK_SECRET).
        # Read via getattr so this module stays importable when the setting
        # isn't declared yet — operator adds STRIPE_CONNECT_WEBHOOK_SECRET
        # to config.py alongside the main signing secret when wiring live.
        secret = getattr(settings, "stripe_connect_webhook_secret", "") or ""
        if secret:
            event = stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
                payload, sig, secret, tolerance=300
            )
        else:
            # Dev fallback — skip signature verification only when no secret
            # is configured (CI / offline). In prod the setting must be set.
            event = json.loads(payload.decode("utf-8"))
    except stripe.SignatureVerificationError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"bad signature: {e}") from e
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"webhook parse: {e}") from e

    etype = event.get("type") if isinstance(event, dict) else event.type
    if etype != "account.updated":
        return JSONResponse(content={"ok": True, "ignored": etype})

    data = event["data"]["object"] if isinstance(event, dict) else event.data.object
    acct_id = data.get("id") if isinstance(data, dict) else data.id
    metadata = data.get("metadata", {}) if isinstance(data, dict) else (data.metadata or {})
    advisor_id_raw = (
        metadata.get("advisor_id") if isinstance(metadata, dict) else metadata.get("advisor_id")
    )
    if advisor_id_raw is None:
        return JSONResponse(content={"ok": True, "ignored": "no advisor_id in metadata"})
    try:
        advisor_id = int(advisor_id_raw)
    except (TypeError, ValueError):
        return JSONResponse(content={"ok": True, "ignored": "bad advisor_id"})

    capabilities = (
        data.get("capabilities", {}) if isinstance(data, dict) else dict(data.capabilities or {})
    )
    transfers_active = capabilities.get("transfers") == "active"

    conn.execute(
        "UPDATE advisors SET stripe_connect_account_id = ?, updated_at = ? WHERE id = ?",
        (acct_id, _now_iso(), advisor_id),
    )

    if transfers_active:
        # Only set verified_at if it's NULL — a seeded advisor may already
        # be verified by the 中小企業庁 list and we don't want to overwrite
        # its source timestamp.
        conn.execute(
            "UPDATE advisors SET verified_at = COALESCE(verified_at, ?), updated_at = ?"
            " WHERE id = ?",
            (_now_iso(), _now_iso(), advisor_id),
        )

    return JSONResponse(content={"ok": True, "advisor_id": advisor_id})


@router.post(
    "/report-conversion",
    responses={
        200: {"description": "conversion recorded"},
        404: {"description": "token unknown"},
        409: {"description": "already converted"},
    },
)
def report_conversion(
    payload: ReportConversionRequest,
    conn: DbDep,
) -> JSONResponse:
    """Advisor marks a referral as converted. Commission computed + queued.

    The ``referral_token`` is a single-referral bearer credential.
    """
    row = conn.execute(
        "SELECT r.id, r.advisor_id, r.converted_at, a.firm_type, a.commission_model,"
        "       a.commission_rate_pct, a.commission_yen_per_intro"
        " FROM advisor_referrals r JOIN advisors a ON a.id = r.advisor_id"
        " WHERE r.referral_token = ?",
        (payload.referral_token,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "referral_token unknown")
    if row["converted_at"] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "referral already marked as converted")
    if row["firm_type"] == "弁護士":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "弁護士カテゴリでは紹介料・成約手数料・受任報酬連動手数料を記録できません",
        )

    # Commission computation. Flat = fixed yen. Percent = rate_pct * value,
    # requires conversion_value_yen. The 30% cap is schema-enforced.
    if row["commission_model"] == "percent":
        if payload.conversion_value_yen is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "conversion_value_yen required for percent commission",
            )
        commission = int(payload.conversion_value_yen * row["commission_rate_pct"] / 100)
    else:
        commission = row["commission_yen_per_intro"] or 3000

    now = _now_iso()
    conn.execute(
        "UPDATE advisor_referrals"
        " SET converted_at = ?, conversion_value_yen = ?,"
        "     conversion_evidence_url = ?, commission_yen = ?"
        " WHERE id = ?",
        (
            now,
            payload.conversion_value_yen,
            str(payload.evidence_url) if payload.evidence_url else None,
            commission,
            row["id"],
        ),
    )
    # Ranking signal bump. success_count is the cumulative VERIFIED
    # conversion count (we treat the Stripe Transfer later as the audit
    # proof); incrementing here is a provisional signal that gets clawed
    # back by a reverse-transaction path if the transfer later fails.
    conn.execute(
        "UPDATE advisors SET success_count = success_count + 1, updated_at = ? WHERE id = ?",
        (now, row["advisor_id"]),
    )
    return JSONResponse(
        content={
            "status": "recorded",
            "commission_yen": commission,
            "payout_scheduled": True,
        }
    )


@router.get("/{advisor_id}/dashboard-data", response_model=AdvisorDashboardResponse)
def dashboard_data(
    advisor_id: int,
    conn: DbDep,
    token: Annotated[str | None, Query(description="signed advisor dashboard token")] = None,
) -> JSONResponse:
    """Self-serve dashboard backing data: referrals + earnings summary.

    Authentication: a signed HMAC ``?token=...`` is required. The token is
    issued in the Stripe Connect Express return URL (or a future magic-link
    email) so the advisor can arrive from Stripe without an API key while
    keeping dashboard data non-public.
    """
    a = conn.execute(
        "SELECT * FROM advisors WHERE id = ?",
        (advisor_id,),
    ).fetchone()
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "advisor not found")
    if not _verify_advisor_dashboard_token(advisor_id, a["contact_email"], token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "advisor dashboard token required")

    refs = conn.execute(
        "SELECT id, referral_token, source_program_id, clicked_at, converted_at,"
        "       conversion_value_yen, commission_yen, commission_paid_at"
        " FROM advisor_referrals"
        " WHERE advisor_id = ?"
        " ORDER BY clicked_at DESC"
        " LIMIT 200",
        (advisor_id,),
    ).fetchall()

    summary = conn.execute(
        "SELECT"
        "  COUNT(*) AS clicks,"
        "  SUM(CASE WHEN converted_at IS NOT NULL THEN 1 ELSE 0 END) AS conversions,"
        "  SUM(CASE WHEN converted_at IS NOT NULL AND commission_paid_at IS NULL"
        "           THEN commission_yen ELSE 0 END) AS unpaid_yen,"
        "  SUM(CASE WHEN commission_paid_at IS NOT NULL"
        "           THEN commission_yen ELSE 0 END) AS paid_yen"
        " FROM advisor_referrals"
        " WHERE advisor_id = ?",
        (advisor_id,),
    ).fetchone()

    advisor = _row_to_advisor(a).model_dump()
    advisor["contact_email"] = "<email-redacted>" if advisor.get("contact_email") else None
    advisor["contact_phone"] = "<phone-redacted>" if advisor.get("contact_phone") else None

    return JSONResponse(
        content={
            "advisor": advisor,
            "summary": {
                "clicks": summary["clicks"] or 0,
                "conversions": summary["conversions"] or 0,
                "unpaid_yen": summary["unpaid_yen"] or 0,
                "paid_yen": summary["paid_yen"] or 0,
            },
            "referrals": [
                {
                    "id": r["id"],
                    "token_prefix": r["referral_token"][:8] + "…",
                    "source_program_id": r["source_program_id"],
                    "clicked_at": r["clicked_at"],
                    "converted_at": r["converted_at"],
                    "conversion_value_yen": r["conversion_value_yen"],
                    "commission_yen": r["commission_yen"],
                    "commission_paid_at": r["commission_paid_at"],
                }
                for r in refs
            ],
        }
    )
