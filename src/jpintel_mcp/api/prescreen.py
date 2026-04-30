"""Eligibility prescreen — the "judgment" surface over the catalog.

Why this exists: search_programs is keyword-oriented. It answers
"which programs mention X?". Prescreen is profile-oriented: "given that I am
a 5ha 稲作 sole proprietor in 茨城県 planning ¥8M of equipment investment,
which programs could I plausibly apply to, and why?".

The two are complementary — search is discovery by text, prescreen is
discovery by fit. LLM agents building "help this SMB find support" flows
should prefer prescreen because it reduces keyword-guessing round-trips.

v1 scope (intentionally narrow):
  - Match against prefecture (direct + national fallback).
  - Match against target_types (sole_proprietor / corporation; EN+JP aliases).
  - Amount sufficiency check when `planned_investment_man_yen` is supplied.
  - Flag programs that are matched by an exclusion_rules `prerequisite`
    condition the caller has NOT declared (e.g., 認定新規就農者).
  - Rank: tier (S>A>B>C) → positive-match count → amount_max_man_yen desc.

Explicitly out of scope for v1:
  - Fuzzy 業種 → target_types bridging (kept verbatim for now).
  - exclusion_rules `exclude` / `combine_ok` pairwise logic — that's about
    "if applying for X, can I also apply for Y" and needs a caller-supplied
    "applying_for" list we don't have yet.
  - Automatic 法人番号 lookup (caller passes it as identity only).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.api.vocab import (
    _normalize_industry_jsic,
    _normalize_prefecture,
)
from jpintel_mcp.utils.slug import program_static_url

router = APIRouter(prefix="/v1/programs", tags=["programs"])

# Per-handler structured event log. The /v1/programs request envelope
# (latency / status / error_class) is already emitted by
# `_QueryTelemetryMiddleware` in api/main.py; this channel adds the
# prescreen-specific business fields (result tier distribution, profile
# fill ratio, caveat surfacing) that the middleware cannot see.
# Consumers: weekly digest, SLO conformance reports.
_event_log = logging.getLogger("autonomath.prescreen")


# ---------------------------------------------------------------------------
# I/O shapes
# ---------------------------------------------------------------------------


class PrescreenRequest(BaseModel):
    """Caller's business profile. All fields optional — the more you supply,
    the sharper the scoring. An empty profile returns the same default
    ranking search_programs uses (tier first), just wrapped in the prescreen
    envelope so the caller gets a consistent shape."""

    model_config = ConfigDict(extra="forbid")

    prefecture: Annotated[
        str | None,
        Field(
            description=(
                "Caller's prefecture. Accepts canonical ('東京都'), short ('東京'), "
                "or romaji ('Tokyo'). Use '全国' / 'national' / None to skip "
                "the prefecture filter entirely (you still get national programs)."
            ),
            max_length=40,
        ),
    ] = None
    industry_jsic: Annotated[
        str | None,
        Field(
            description=(
                "JSIC 大分類 letter (A..T). Accepts JP names ('製造業', '農業'). "
                "Used for hints only in v1 — does not exclude programs because "
                "program-level industry tagging coverage is thin."
            ),
            max_length=10,
        ),
    ] = None
    is_sole_proprietor: Annotated[
        bool | None,
        Field(
            description=(
                "True = 個人事業主. False = 法人 (incl. 株式会社/合同会社/組合). "
                "None = unspecified (match against both target_types)."
            ),
        ),
    ] = None
    employee_count: Annotated[
        int | None,
        Field(ge=0, le=100000, description="Number of employees."),
    ] = None
    revenue_yen: Annotated[
        int | None,
        Field(
            ge=0,
            description="Annual revenue in JPY (NOT 万円). Used for SME/大企業 split only.",
        ),
    ] = None
    founded_year: Annotated[
        int | None,
        Field(
            ge=1800,
            le=2100,
            description="Western calendar year of incorporation / founding.",
        ),
    ] = None
    planned_investment_man_yen: Annotated[
        float | None,
        Field(
            ge=0,
            description=(
                "Planned project cost in 万円 (NOT 円). Used for amount "
                "sufficiency check — programs whose amount_max_man_yen is "
                "below this value are flagged as 'undersized'."
            ),
        ),
    ] = None
    houjin_bangou: Annotated[
        str | None,
        Field(
            description="13-digit 国税庁 法人番号. Stored for identity only.",
            max_length=13,
        ),
    ] = None
    declared_certifications: Annotated[
        list[str] | None,
        Field(
            description=(
                "Certifications the caller has declared (e.g., '認定新規就農者', "
                "'認定農業者', '経営革新計画承認'). Used to suppress "
                "'prerequisite-missing' flags."
            ),
            max_length=20,
        ),
    ] = None
    limit: Annotated[
        int,
        Field(ge=1, le=50, description="Max rows to return. Default 10."),
    ] = 10
    company_url: Annotated[
        str | None,
        Field(
            description=(
                "Honeypot. Real callers MUST leave this null/empty. The web "
                "form hides this field via CSS; only autofilled bots populate it. "
                "Any non-empty value is treated as abuse and rejected."
            ),
            max_length=500,
        ),
    ] = None


class PrescreenMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unified_id: str
    primary_name: str
    tier: str | None
    authority_level: str | None
    prefecture: str | None
    amount_max_man_yen: float | None
    official_url: str | None
    # Site-relative SEO page path (`/programs/{slug}-{sha1-6}.html`).
    # Result cards / mailto bodies should link to this — building
    # `/programs/{unified_id}.html` instead is a 404 (no such file
    # exists; static pages are slug-named).
    static_url: str | None = Field(
        default=None,
        description=(
            "Site-relative path to the program's static SEO page on "
            "jpcite.com. Computed from primary_name + unified_id "
            "via jpintel_mcp.utils.slug. Use this for deep-links."
        ),
    )
    fit_score: int = Field(
        description=(
            "Heuristic positive-match count in v1 (higher = better fit). "
            "Ranges 0..~5. NOT a probability; compare rows within one response only."
        ),
    )
    match_reasons: list[str] = Field(
        description="Human-readable reasons this row scored positively."
    )
    caveats: list[str] = Field(
        description=(
            "Conditions the caller has NOT met or we couldn't verify "
            "(e.g., missing 認定新規就農者 prerequisite, amount_max below "
            "planned_investment). Empty list == no known caveats."
        )
    )


class PrescreenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_considered: int = Field(
        description=(
            "Rows passing the hard prefecture / national filter before "
            "ranking. `results` is ranked top-N of this set."
        )
    )
    limit: int
    results: list[PrescreenMatch]
    profile_echo: dict[str, Any] = Field(
        description=(
            "The normalized profile actually used for matching, so the "
            "caller can verify e.g. that 'Tokyo' -> '東京都'."
        )
    )


# ---------------------------------------------------------------------------
# Matching logic (pure; no DB) + DB candidate fetch
# ---------------------------------------------------------------------------


# target_types vocabulary is EN/JP mixed in the DB (memory:
# project_registry_vocab_drift). We can't fix the DB in this PR, so we
# normalize on the query side: "sole_proprietor" matches all of these
# tokens equivalently.
_SOLE_PROP_ALIASES = {
    "sole_proprietor",
    "sole-proprietor",
    "個人事業主",
    "個人農業者",
    "individual",
}
_CORPORATION_ALIASES = {
    "corporation",
    "corp",
    "法人",
    "法人全般",
    "農業法人",
    "中小企業",
    "中小製造業",
    "小規模事業者",
    "小規模企業",
}


def _target_type_token_matches(
    tokens: list[str], is_sole_proprietor: bool | None
) -> tuple[bool, str | None]:
    """Return (matched, matched_token). Unknown/empty list -> (True, None)
    so we don't punish programs that just haven't tagged target_types."""
    if not tokens:
        return True, None
    if is_sole_proprietor is None:
        return True, None
    expected = _SOLE_PROP_ALIASES if is_sole_proprietor else _CORPORATION_ALIASES
    for tok in tokens:
        if tok in expected:
            return True, tok
    return False, None


def _fetch_candidates(
    conn: sqlite3.Connection,
    prefecture: str | None,
    limit_candidates: int = 500,
) -> list[sqlite3.Row]:
    """Pull a candidate set of up to `limit_candidates` rows that at least
    match on prefecture (direct or national). Tier-X and excluded rows are
    dropped here; per-row scoring happens in Python so we can build reasons."""
    where = ["excluded = 0", "COALESCE(tier,'X') != 'X'"]
    params: list[Any] = []
    if prefecture:
        # Either this prefecture OR a national / unassigned program.
        where.append(
            "(prefecture = ? OR prefecture IS NULL OR prefecture = '全国' "
            "OR authority_level = 'national')"
        )
        params.append(prefecture)
    sql = (
        "SELECT unified_id, primary_name, tier, authority_level, prefecture, "
        "amount_max_man_yen, official_url, target_types_json, "
        "funding_purpose_json "
        "FROM programs "
        "WHERE " + " AND ".join(where) + " "
        "ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 "
        "WHEN 'C' THEN 3 ELSE 4 END, amount_max_man_yen DESC "
        "LIMIT ?"
    )
    params.append(limit_candidates)
    return conn.execute(sql, params).fetchall()


def _fetch_prerequisite_rules(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """prerequisite rules keyed by program_a (the program that requires
    the prerequisite). Used to attach caveats to matches."""
    rows = conn.execute(
        "SELECT rule_id, program_a, program_b, description "
        "FROM exclusion_rules WHERE kind = 'prerequisite'"
    ).fetchall()
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        key = r["program_a"]
        if not key:
            continue
        out.setdefault(key, []).append(
            {
                "rule_id": r["rule_id"],
                "prerequisite": r["program_b"],
                "description": r["description"],
            }
        )
    return out


def _score_row(
    row: sqlite3.Row,
    profile: PrescreenRequest,
    prerequisite_rules: dict[str, list[dict[str, Any]]],
) -> PrescreenMatch:
    reasons: list[str] = []
    caveats: list[str] = []
    score = 0

    # Prefecture reason
    if profile.prefecture:
        if row["prefecture"] == profile.prefecture:
            reasons.append(f"prefecture 一致: {profile.prefecture}")
            score += 2
        elif row["authority_level"] == "national" or row["prefecture"] in (None, "全国"):
            reasons.append("国の全国制度 (prefecture 非限定)")
            score += 1

    # Target-type reason
    try:
        targets = json.loads(row["target_types_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        targets = []
    matched, tok = _target_type_token_matches(targets, profile.is_sole_proprietor)
    if profile.is_sole_proprietor is not None:
        if matched and tok:
            label = "個人事業主" if profile.is_sole_proprietor else "法人"
            reasons.append(f"target_types に {label} 相当 ({tok}) を含む")
            score += 1
        elif not matched:
            label = "個人事業主" if profile.is_sole_proprietor else "法人"
            caveats.append(f"{label} は target_types に含まれていません (対象外の可能性)")
            # score is not penalized; we still show the row — the caller
            # may have tagged themselves wrong and want to see it.

    # Amount sufficiency
    amount_max = row["amount_max_man_yen"]
    if profile.planned_investment_man_yen is not None and amount_max is not None:
        # amount_max is 万円. planned_investment is also 万円.
        if amount_max >= profile.planned_investment_man_yen:
            reasons.append(
                f"amount_max {amount_max:.0f}万円 ≥ 予定投資 {profile.planned_investment_man_yen:.0f}万円"
            )
            score += 1
        else:
            caveats.append(
                f"amount_max {amount_max:.0f}万円 < 予定投資 {profile.planned_investment_man_yen:.0f}万円 "
                "— 足りない可能性 (他制度と併用検討)"
            )

    # Prerequisite caveat (only flag missing prerequisites)
    declared = set(profile.declared_certifications or [])
    for rule in prerequisite_rules.get(row["unified_id"], []):
        prereq = rule.get("prerequisite")
        if prereq and prereq not in declared:
            caveats.append(
                f"前提条件: {prereq} (未申告). 根拠: {rule['rule_id']}"
            )

    return PrescreenMatch(
        unified_id=row["unified_id"],
        primary_name=row["primary_name"],
        tier=row["tier"],
        authority_level=row["authority_level"],
        prefecture=row["prefecture"],
        amount_max_man_yen=amount_max,
        official_url=row["official_url"],
        static_url=program_static_url(row["primary_name"], row["unified_id"]),
        fit_score=score,
        match_reasons=reasons,
        caveats=caveats,
    )


def run_prescreen(conn: sqlite3.Connection, profile: PrescreenRequest) -> PrescreenResponse:
    """Pure function for REST + MCP parity. Assumes `profile.prefecture` and
    `profile.industry_jsic` are already normalized by the caller."""
    rows = _fetch_candidates(conn, profile.prefecture, limit_candidates=500)
    prereq_rules = _fetch_prerequisite_rules(conn)
    scored = [_score_row(r, profile, prereq_rules) for r in rows]

    # Rank by fit_score desc, then tier (already reflected in DB order as
    # tiebreak via ORDER BY in _fetch_candidates). Stable sort preserves the
    # tier/amount pre-sort for ties.
    scored.sort(key=lambda m: m.fit_score, reverse=True)
    top = scored[: profile.limit]

    return PrescreenResponse(
        total_considered=len(scored),
        limit=profile.limit,
        results=top,
        profile_echo={
            "prefecture": profile.prefecture,
            "industry_jsic": profile.industry_jsic,
            "is_sole_proprietor": profile.is_sole_proprietor,
            "planned_investment_man_yen": profile.planned_investment_man_yen,
            "declared_certifications": profile.declared_certifications or [],
        },
    )


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------


@router.post(
    "/prescreen",
    response_model=PrescreenResponse,
    summary="Prescreen — rank programs by fit to a business profile",
    description=(
        "Profile-oriented match: given a caller's `prefecture` / "
        "`industry_jsic` / `is_sole_proprietor` / `employee_count` / "
        "`planned_investment_man_yen` / declared `held_certifications`, "
        "return ranked candidate programs with per-row `reasons[]` and "
        "`caveats[]`.\n\n"
        "**When to use prescreen vs search:** `/v1/programs/search` "
        "answers 'which programs mention X?' (keyword discovery). "
        "Prescreen answers 'which programs could *I* plausibly apply to, "
        "and why?' (fit judgment). LLM agents building 'help this SMB "
        "find support' flows should prefer prescreen — it cuts the "
        "keyword-guessing round-trips.\n\n"
        "**Scope (v1):** prefecture (direct + 全国 fallback), "
        "target_types (sole_proprietor / corporation, EN+JP aliases), "
        "amount sufficiency vs `planned_investment_man_yen`, and "
        "exclusion-rule prerequisite flagging (e.g. 認定新規就農者 "
        "required but not declared). Ranking: tier (S>A>B>C) → match "
        "count → amount_max_man_yen desc."
    ),
    responses={
        200: {
            "description": "Ranked prescreen matches with reasons + caveats.",
            "content": {
                "application/json": {
                    "example": {
                        "total_considered": 312,
                        "limit": 20,
                        "results": [
                            {
                                "unified_id": "UNI-2611050f9a",
                                "primary_name": "小規模事業者持続化補助金",
                                "tier": "B",
                                "authority_level": "national",
                                "prefecture": "全国",
                                "amount_max_man_yen": 200.0,
                                "official_url": "https://r3.jizokukahojokin.info/",
                                "static_url": "/programs/shoukibo-jigyousha-jizokuka-hojokin-2611050f9a.html",
                                "fit_score": 3,
                                "match_reasons": [
                                    "prefecture match: 全国 program covers 東京都",
                                    "target_types に 個人事業主 相当 (sole_proprietor) を含む",
                                    "amount_max 200万円 ≥ 予定投資 80万円",
                                ],
                                "caveats": [],
                            }
                        ],
                        "profile_echo": {
                            "prefecture": "東京都",
                            "industry_jsic": "G",
                            "is_sole_proprietor": True,
                            "planned_investment_man_yen": 80,
                            "declared_certifications": [],
                        },
                    }
                }
            },
        },
        400: {"description": "Malformed profile."},
    },
)
def prescreen_programs(
    conn: DbDep,
    ctx: ApiContextDep,
    profile: PrescreenRequest,
) -> PrescreenResponse:
    """Rank programs by fit to a caller business profile.

    This is the "judgment" complement to `/v1/programs/search`'s "discovery".
    See `src/jpintel_mcp/api/prescreen.py` module docstring for scope.
    """
    if profile.company_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_input",
        )
    # Normalize at the boundary; run_prescreen assumes already-canonical.
    normalized = profile.model_copy(
        update={
            "prefecture": _normalize_prefecture(profile.prefecture),
            "industry_jsic": _normalize_industry_jsic(profile.industry_jsic),
        }
    )
    try:
        result = run_prescreen(conn, normalized)
    except sqlite3.Error as exc:  # defensive — surfaces as 500 with detail
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"prescreen query failed: {exc}",
        ) from exc
    log_usage(conn, ctx, "programs.prescreen")
    # Emit per-prescreen structured event. PII-free: only the normalized
    # profile shape (presence flags + aggregate tier dist + counts) is
    # captured. The middleware envelope already carries latency / status
    # / request_id — this line adds the business signal needed to track
    # the prescreen p95 < 500ms SLO and to detect "all results = X tier"
    # degradation. Logging never blocks the response.
    try:
        tier_dist: dict[str, int] = {}
        for m in result.results:
            tier_dist[m.tier] = tier_dist.get(m.tier, 0) + 1
        caveat_count = sum(len(m.caveats) for m in result.results)
        profile_filled = sum(
            1
            for v in (
                normalized.prefecture,
                normalized.industry_jsic,
                normalized.is_sole_proprietor,
                normalized.planned_investment_man_yen,
            )
            if v is not None and v != ""
        )
        _event_log.info(
            json.dumps(
                {
                    "event": "prescreen",
                    "tier": ctx.tier,
                    "total_considered": result.total_considered,
                    "result_count": len(result.results),
                    "tier_dist": tier_dist,
                    "caveat_count": caveat_count,
                    "profile_filled": profile_filled,
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        # Telemetry must never break a successful response.
        pass
    return result
