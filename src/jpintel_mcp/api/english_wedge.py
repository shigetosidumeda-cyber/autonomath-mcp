"""REST handlers for the English-wedge / foreign-investor MCP tools.

Mirrors the 5 MCP tools shipped in
``jpintel_mcp.mcp.autonomath_tools.english_wedge`` at the REST surface
``/v1/en/*`` so foreign-investor (FDI / cross-border M&A / FATCA SaaS)
callers can hit either MCP or HTTPS without re-implementing the logic.

Routes
------

  GET  /v1/en/laws/search?q=...&limit=...
  GET  /v1/en/laws/{law_id}/articles/{article_no}
  GET  /v1/en/tax_treaty/{country_a}?country_b=JPN
  GET  /v1/en/foreign_capital_eligibility?houjin_bangou=...&program_id=...
  GET  /v1/en/fdi_subsidies?industry_jsic=...&foreign_pct=100&limit=20

Each route is a thin FastAPI wrapper around the MCP impl function; we
do NOT duplicate SQL or validation logic. The impl returns the canonical
envelope (``results / total / limit / offset / _disclaimer / _next_calls``).

Billing posture
---------------
1 ¥3 unit per call (税込 ¥3.30), uniform across all five endpoints. Same
``log_usage()`` convention as ``api/autonomath.py``. Anonymous callers
(no X-API-Key) pass through ``AnonIpLimitDep`` (3/day/IP). The router is
mounted with that dep in ``api/main.py``.

Disclaimer envelope
-------------------
Every response carries ``_disclaimer`` declaring 税理士法 §52 / 国際課税 /
弁護士法 §72 / FDI 規制 fence. The MCP impl already injects it; the REST
wrapper does not re-decorate.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query

from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.mcp.autonomath_tools.english_wedge import (
    _check_foreign_capital_eligibility_impl,
    _find_fdi_friendly_subsidies_impl,
    _get_law_article_en_impl,
    _get_tax_treaty_impl,
    _search_laws_en_impl,
)

logger = logging.getLogger("jpintel.api.english_wedge")

router = APIRouter(prefix="/v1/en", tags=["english-wedge"])


@router.get(
    "/laws/search",
    summary="Search Japanese laws (English text only) — e-Gov 日本法令外国語訳 corpus",
    description=(
        "Keyword search restricted to ``am_law_article`` rows with non-NULL "
        "``body_en`` (e-Gov 日本法令外国語訳, CC-BY 4.0). Returns EN excerpt + "
        "title + source_url. ¥3/req metered. Foreign-investor cohort entry."
    ),
)
def search_laws_en_route(
    q: Annotated[
        str, Query(min_length=1, max_length=200, description="English keyword (2+ chars).")
    ],
    limit: Annotated[int, Query(ge=1, le=50, description="Max results.")] = 10,
    conn: DbDep | None = None,  # noqa: B008
    ctx: ApiContextDep | None = None,  # noqa: B008
) -> dict[str, Any]:
    body = _search_laws_en_impl(q=q, limit=limit)
    if conn is not None and ctx is not None:
        log_usage(
            conn,
            ctx,
            "en.laws.search",
            params={"q": q[:60], "limit": limit},
            quantity=1,
            result_count=int(body.get("total") or 0),
            strict_metering=True,
        )
    return body


@router.get(
    "/laws/{law_id}/articles/{article_no}",
    summary="Get a single law article (English text) — e-Gov 日本法令外国語訳",
    description=(
        "Exact (law_id, article_no) lookup. Returns the e-Gov 英訳 EN body when "
        "present, else falls back to JP body with a ``warning`` field. The JP "
        "version remains the only legally authoritative text. ¥3/req metered."
    ),
)
def get_law_article_en_route(
    law_id: Annotated[
        str, Path(min_length=1, max_length=200, description="Canonical law id or law name.")
    ],
    article_no: Annotated[str, Path(min_length=1, max_length=50, description="Article number.")],
    conn: DbDep | None = None,  # noqa: B008
    ctx: ApiContextDep | None = None,  # noqa: B008
) -> dict[str, Any]:
    body = _get_law_article_en_impl(law_id=law_id, article_no=article_no)
    if conn is not None and ctx is not None:
        log_usage(
            conn,
            ctx,
            "en.laws.get_article",
            params={"law_id": law_id[:60], "article_no": article_no[:30]},
            quantity=1,
            result_count=1 if body.get("found") else 0,
            strict_metering=True,
        )
    return body


@router.get(
    "/tax_treaty/{country_a}",
    summary="Bilateral tax-treaty lookup (am_tax_treaty, MoF / NTA primary source)",
    description=(
        "Returns withholding-tax rates (dividend / interest / royalty / parent-"
        "subsidiary), PE threshold, info-exchange status, and MoAA arbitration "
        "flag for the bilateral DTA between ``country_a`` and ``country_b`` "
        "(default 'JPN'). 33 of ~80 jurisdictions hand-curated. ¥3/req metered."
    ),
)
def get_tax_treaty_route(
    country_a: Annotated[
        str,
        Path(min_length=2, max_length=3, description="ISO 3166-1 alpha-2 (e.g. 'US', 'GB', 'SG')."),
    ],
    country_b: Annotated[
        str, Query(min_length=2, max_length=3, description="Counterparty (default 'JPN').")
    ] = "JPN",
    conn: DbDep | None = None,  # noqa: B008
    ctx: ApiContextDep | None = None,  # noqa: B008
) -> dict[str, Any]:
    body = _get_tax_treaty_impl(country_a=country_a, country_b=country_b)
    if conn is not None and ctx is not None:
        log_usage(
            conn,
            ctx,
            "en.tax_treaty.get",
            params={"country_a": country_a, "country_b": country_b},
            quantity=1,
            result_count=1 if body.get("found") else 0,
            strict_metering=True,
        )
    return body


@router.get(
    "/foreign_capital_eligibility",
    summary="Per-program foreign-capital eligibility flag (am_subsidy_rule, migration 092)",
    description=(
        "Returns the most-restrictive ``foreign_capital_eligibility`` flag "
        "({eligible / eligible_with_caveat / case_by_case / excluded / silent}) "
        "for the given program. ``houjin_bangou`` is currently input echo only "
        "(flag is per-program). ¥3/req metered. 行政書士法 §1の2 / FDI 規制 fence."
    ),
)
def check_foreign_capital_eligibility_route(
    program_id: Annotated[
        str, Query(min_length=1, max_length=200, description="Program canonical_id or unified_id.")
    ],
    houjin_bangou: Annotated[
        str, Query(max_length=13, description="13-digit 法人番号 (optional).")
    ] = "",
    conn: DbDep | None = None,  # noqa: B008
    ctx: ApiContextDep | None = None,  # noqa: B008
) -> dict[str, Any]:
    body = _check_foreign_capital_eligibility_impl(
        houjin_bangou=houjin_bangou,
        program_id=program_id,
    )
    if conn is not None and ctx is not None:
        log_usage(
            conn,
            ctx,
            "en.foreign_capital_eligibility.check",
            params={
                "program_id": program_id[:60],
                "houjin_bangou": houjin_bangou or None,
            },
            quantity=1,
            result_count=1 if body.get("found") else 0,
            strict_metering=True,
        )
    return body


@router.get(
    "/fdi_subsidies",
    summary="Find FDI-eligible Japanese subsidies by industry (JSIC)",
    description=(
        "Filters programs by industry JSIC + ``foreign_capital_eligibility`` "
        "!= 'excluded'. Ranks eligible > eligible_with_caveat > case_by_case "
        "> silent. ¥3/req metered. ``foreign_pct`` is input echo (DB has no "
        "per-program threshold). 行政書士法 §1の2 / FDI 規制 / 国際課税 fence."
    ),
)
def find_fdi_friendly_subsidies_route(
    industry_jsic: Annotated[
        str, Query(min_length=1, max_length=10, description="JSIC code (major A-T or numeric).")
    ],
    foreign_pct: Annotated[
        int, Query(ge=0, le=100, description="Applicant foreign-equity %.")
    ] = 100,
    limit: Annotated[int, Query(ge=1, le=50, description="Max results.")] = 20,
    conn: DbDep | None = None,  # noqa: B008
    ctx: ApiContextDep | None = None,  # noqa: B008
) -> dict[str, Any]:
    body = _find_fdi_friendly_subsidies_impl(
        industry_jsic=industry_jsic,
        foreign_pct=foreign_pct,
        limit=limit,
    )
    if conn is not None and ctx is not None:
        log_usage(
            conn,
            ctx,
            "en.fdi_subsidies.find",
            params={
                "industry_jsic": industry_jsic,
                "foreign_pct": foreign_pct,
                "limit": limit,
            },
            quantity=1,
            result_count=int(body.get("total") or 0),
            strict_metering=True,
        )
    return body


__all__ = ["router"]
