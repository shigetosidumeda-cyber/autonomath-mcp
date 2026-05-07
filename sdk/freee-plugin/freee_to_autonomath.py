"""freee → jpcite glue layer.

A *stateless* adapter that maps freee 会計 API company / journal data into the
shape expected by jpcite ``GET /v1/programs/search``.

Security model
--------------
- The freee OAuth2 access_token is supplied by the **plugin caller** (個人 dev
  or agency). It is never persisted, logged, or transmitted anywhere except
  ``api.freee.co.jp``.
- The jpcite API key is also supplied by the caller. It is never persisted
  or logged. It is only sent to ``api.jpcite.com`` as ``X-API-Key``. It is not
  an OpenAI / Anthropic / Gemini key.
- This module is fully stateless; no globals, no caches, no disk writes.

Data model
----------
freee company endpoint (``GET /api/1/companies/{company_id}``) plus the trial
balance endpoint provide enough context to derive the six prefilter fields
jpcite cares about for ``search_programs``:

    industry_jsic        ← freee.company.business_industry_code
    revenue_yen          ← Σ trial_balance(売上高)
    expense_categories   ← freee account_items where category in (経費)
    employee_count       ← freee.company.employees_number
    prefecture           ← freee.company.prefecture_code → 都道府県名
    corporate_class      ← freee.company.company_type (kojin / houjin)

A single ``recommend()`` call returns up to 5 jpcite programs ranked by the
server's default scoring. Every returned row is guaranteed to carry a
``source_url`` field — items missing that field are dropped (defense-in-depth
against the noukaweb-class aggregator ban documented in CLAUDE.md).
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field

FREEE_API_BASE = "https://api.freee.co.jp"
JPCITE_API_BASE = "https://api.jpcite.com"

# JIS X 0401 都道府県コード (1-47) → 都道府県名. freee の prefecture_code は
# 0-origin ではなく JIS 準拠の 1-origin。
PREFECTURE_BY_CODE: dict[int, str] = {
    1: "北海道",
    2: "青森県",
    3: "岩手県",
    4: "宮城県",
    5: "秋田県",
    6: "山形県",
    7: "福島県",
    8: "茨城県",
    9: "栃木県",
    10: "群馬県",
    11: "埼玉県",
    12: "千葉県",
    13: "東京都",
    14: "神奈川県",
    15: "新潟県",
    16: "富山県",
    17: "石川県",
    18: "福井県",
    19: "山梨県",
    20: "長野県",
    21: "岐阜県",
    22: "静岡県",
    23: "愛知県",
    24: "三重県",
    25: "滋賀県",
    26: "京都府",
    27: "大阪府",
    28: "兵庫県",
    29: "奈良県",
    30: "和歌山県",
    31: "鳥取県",
    32: "島根県",
    33: "岡山県",
    34: "広島県",
    35: "山口県",
    36: "徳島県",
    37: "香川県",
    38: "愛媛県",
    39: "高知県",
    40: "福岡県",
    41: "佐賀県",
    42: "長崎県",
    43: "熊本県",
    44: "大分県",
    45: "宮崎県",
    46: "鹿児島県",
    47: "沖縄県",
}


class CompanyContext(BaseModel):
    """Normalized company snapshot derived from freee API responses."""

    industry_jsic: str | None = None
    revenue_yen: int | None = Field(default=None, ge=0)
    expense_categories: list[str] = Field(default_factory=list)
    employee_count: int | None = Field(default=None, ge=0)
    prefecture: str | None = None
    corporate_class: str | None = None  # "houjin" | "kojin"


class ProgramRecommendation(BaseModel):
    """Subset of jpcite program fields safe to surface in freee plugin UI."""

    unified_id: str
    title: str
    authority: str | None = None
    tier: str | None = None
    source_url: str  # required; rows lacking this are dropped upstream


def _safe_dict(d: Any) -> dict[str, Any]:
    """Return ``d`` if it is a dict, else an empty dict. Tolerates partial freee responses."""
    return d if isinstance(d, dict) else {}


def fetch_company_context(
    *,
    freee_access_token: str,
    company_id: int,
    http_client: httpx.Client | None = None,
) -> CompanyContext:
    """Pull the freee company record and shape it into ``CompanyContext``.

    The token is forwarded once to ``api.freee.co.jp`` and never retained.
    """
    if not freee_access_token or not isinstance(freee_access_token, str):
        raise ValueError("freee_access_token is required (caller-supplied)")

    owns_client = http_client is None
    client = http_client or httpx.Client(base_url=FREEE_API_BASE, timeout=15.0)
    try:
        resp = client.get(
            f"/api/1/companies/{company_id}",
            headers={
                "Authorization": f"Bearer {freee_access_token}",
                "X-Api-Version": "2020-06-15",
            },
        )
        resp.raise_for_status()
        payload = _safe_dict(resp.json()).get("company") or {}

        pref_code = payload.get("prefecture_code")
        pref_name = (
            PREFECTURE_BY_CODE.get(int(pref_code))
            if isinstance(pref_code, (int, str)) and str(pref_code).isdigit()
            else None
        )

        # freee の company_type: "kj" = 個人事業主, "zk" = 法人 が代表的
        ctype_raw = payload.get("company_type")
        if ctype_raw == "kj":
            corporate_class = "kojin"
        elif ctype_raw in {"zk", "houjin"}:
            corporate_class = "houjin"
        else:
            corporate_class = None

        return CompanyContext(
            industry_jsic=payload.get("business_industry_code") or None,
            revenue_yen=(
                int(payload["sales"])
                if isinstance(payload.get("sales"), (int, str))
                and str(payload.get("sales")).lstrip("-").isdigit()
                else None
            ),
            expense_categories=list(payload.get("expense_categories") or []),
            employee_count=(
                int(payload["employees_number"])
                if isinstance(payload.get("employees_number"), int)
                else None
            ),
            prefecture=pref_name,
            corporate_class=corporate_class,
        )
    finally:
        if owns_client:
            client.close()


def _build_search_params(ctx: CompanyContext, limit: int) -> dict[str, Any]:
    """Map ``CompanyContext`` to jpcite ``/v1/programs/search`` query params.

    Only the fields jpcite actually accepts as filters are forwarded; the
    rest serve as scoring context the server already infers from the prefecture
    + tier defaults.
    """
    params: dict[str, Any] = {"limit": int(limit)}
    if ctx.prefecture:
        params["prefecture"] = ctx.prefecture
    # Default to the tiers that surface on the jpcite landing page.
    params["tier"] = ["S", "A", "B"]
    if ctx.expense_categories:
        # Caller-derived purpose hints; jpcite maps these via its own ALIAS table.
        params["funding_purpose"] = ctx.expense_categories[:5]
    if ctx.corporate_class:
        params["target_type"] = [ctx.corporate_class]
    return params


def call_autonomath_search(
    *,
    autonomath_api_key: str,
    params: dict[str, Any],
    http_client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Invoke jpcite ``/v1/programs/search`` and return raw item dicts."""
    if not autonomath_api_key or not isinstance(autonomath_api_key, str):
        raise ValueError("autonomath_api_key is required (caller-supplied)")

    owns_client = http_client is None
    client = http_client or httpx.Client(base_url=JPCITE_API_BASE, timeout=15.0)
    try:
        resp = client.get(
            "/v1/programs/search",
            params=params,
            headers={
                "X-API-Key": autonomath_api_key,
                "User-Agent": "jpcite-freee-plugin/0.2",
            },
        )
        resp.raise_for_status()
        body = _safe_dict(resp.json())
        items = body.get("items") or body.get("results") or []
        return [x for x in items if isinstance(x, dict)]
    finally:
        if owns_client:
            client.close()


def recommend(
    *,
    freee_access_token: str,
    company_id: int,
    autonomath_api_key: str,
    limit: int = 5,
    freee_client: httpx.Client | None = None,
    autonomath_client: httpx.Client | None = None,
) -> list[ProgramRecommendation]:
    """Top-level glue. Returns up to ``limit`` jpcite recommendations.

    Every returned row carries a ``source_url`` (rows without one are dropped).
    Tokens are only forwarded to their respective APIs and never logged.
    """
    if limit <= 0 or limit > 5:
        raise ValueError("limit must be in 1..5")

    ctx = fetch_company_context(
        freee_access_token=freee_access_token,
        company_id=company_id,
        http_client=freee_client,
    )
    params = _build_search_params(ctx, limit=limit)
    raw_items = call_autonomath_search(
        autonomath_api_key=autonomath_api_key,
        params=params,
        http_client=autonomath_client,
    )

    out: list[ProgramRecommendation] = []
    for raw in raw_items:
        url = raw.get("source_url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        out.append(
            ProgramRecommendation(
                unified_id=str(raw.get("unified_id") or raw.get("id") or ""),
                title=str(raw.get("title") or raw.get("name") or ""),
                authority=raw.get("authority"),
                tier=raw.get("tier"),
                source_url=url,
            )
        )
        if len(out) >= limit:
            break
    return out


__all__ = [
    "CompanyContext",
    "ProgramRecommendation",
    "PREFECTURE_BY_CODE",
    "fetch_company_context",
    "call_autonomath_search",
    "recommend",
]
