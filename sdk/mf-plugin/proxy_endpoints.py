"""zeimu-kaikei.ai の REST API へのプロキシエンドポイント。

エンドポイント (全て session 認可必須):
  POST /mf-plugin/search-tax-incentives        → /v1/am/tax/search
  POST /mf-plugin/search-subsidies             → /v1/programs/search
  POST /mf-plugin/check-invoice-registrant     → /v1/invoice_registrants/{T+13桁}
  POST /mf-plugin/search-laws                  → /v1/laws/search
  POST /mf-plugin/search-court-decisions       → /v1/court_decisions/search

仕様:
  - upstream の zeimu-kaikei.ai に対しては Bookyou 所有の **サービスキー**
    (zk_live_...) を X-API-Key ヘッダで付与する。MF の access_token は
    upstream には**転送しない** (ヘッダリーク防止)。
  - upstream のレスポンスはそのまま返すが、`_disclaimer` フィールドが無ければ
    付与する (税理士法 §52 への一貫性)。
  - MF tenant の都道府県情報を検索クエリの初期値に使うのは UI 側の責務。
    本ルータでは tenant_uid を将来的な audit に備えて X-MF-Tenant-Uid ヘッダで
    upstream に渡す (PII では無く、Bookyou と MF 双方で billing 整合に使う)。
  - log には access_token / refresh_token を絶対に出さない。
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException, Request, status


router = APIRouter(prefix="/mf-plugin", tags=["proxy"])


_INVOICE_NUMBER_RE = re.compile(r"^T\d{13}$")


def _disclaimer() -> str:
    return (
        "税理士法 §52 — 本サービスは情報提供のみを目的とし、"
        "個別の税務相談・申告書作成等の税理士業務には該当しません。"
        "最終的な税務判断は貴社の顧問税理士にご確認ください。"
    )


def _ensure_authed(request: Request) -> dict[str, Any]:
    sess = request.session.get("mf")
    if not sess or not sess.get("access_token"):
        raise HTTPException(status_code=401, detail="mf_not_authorized")
    return sess


def _attach_disclaimer(payload: Any) -> Any:
    if isinstance(payload, dict):
        payload.setdefault("_disclaimer", _disclaimer())
    return payload


async def _proxy_get(request: Request, upstream_path: str, params: dict[str, Any]) -> Any:
    settings = request.app.state.settings
    sess = _ensure_authed(request)
    headers = {
        "X-API-Key": settings.zeimu_kaikei_api_key,
        "Accept": "application/json",
        # tenant_uid はあくまで識別子。氏名やメール等の PII は転送しない。
        "X-MF-Tenant-Uid": sess.get("tenant_uid") or "",
        "X-Plugin-Source": "mf-cloud",
    }
    url = f"{settings.zeimu_kaikei_base_url.rstrip('/')}{upstream_path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params, headers=headers)
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="upstream_unavailable")
    if resp.status_code == 429:
        raise HTTPException(status_code=429, detail="rate_limited")
    try:
        body = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="upstream_non_json")
    return _attach_disclaimer(body), resp.status_code


# ---- routes ----------------------------------------------------------------


@router.post("/search-tax-incentives")
async def search_tax_incentives(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    keyword = (payload.get("keyword") or "").strip()
    pref = (payload.get("prefecture") or "").strip() or None
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword_required")
    body, sc = await _proxy_get(
        request,
        "/v1/am/tax/search",
        {"q": keyword, "prefecture": pref, "limit": 5},
    )
    return body


@router.post("/search-subsidies")
async def search_subsidies(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    keyword = (payload.get("keyword") or "").strip()
    pref = (payload.get("prefecture") or "").strip() or None
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword_required")
    body, sc = await _proxy_get(
        request,
        "/v1/programs/search",
        {"q": keyword, "prefecture": pref, "limit": 5, "tier": "S,A,B"},
    )
    return body


@router.post("/check-invoice-registrant")
async def check_invoice_registrant(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    raw = (payload.get("registration_number") or "").strip().upper()
    # T-13 → T13 等の正規化
    normalized = raw.replace("-", "").replace(" ", "")
    if not _INVOICE_NUMBER_RE.match(normalized):
        raise HTTPException(
            status_code=400,
            detail="registration_number must match T+13 digits",
        )
    body, sc = await _proxy_get(
        request,
        f"/v1/invoice_registrants/{normalized}",
        {},
    )
    return body


@router.post("/search-laws")
async def search_laws(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    keyword = (payload.get("keyword") or "").strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword_required")
    body, sc = await _proxy_get(
        request,
        "/v1/laws/search",
        {"q": keyword, "limit": 5},
    )
    return body


@router.post("/search-court-decisions")
async def search_court_decisions(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    keyword = (payload.get("keyword") or "").strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword_required")
    body, sc = await _proxy_get(
        request,
        "/v1/court_decisions/search",
        {"q": keyword, "limit": 5},
    )
    return body


@router.get("/me")
async def me(request: Request) -> dict[str, Any]:
    """UI が起動時に呼ぶ。tenant 表示と認可状態のみ返す。token は返さない。"""
    sess = request.session.get("mf") or {}
    if not sess.get("access_token"):
        return {"authed": False, "_disclaimer": _disclaimer()}
    return {
        "authed": True,
        "tenant_uid": sess.get("tenant_uid"),
        "tenant_name": sess.get("tenant_name"),
        "scope": sess.get("scope"),
        "_disclaimer": _disclaimer(),
    }


__all__ = ["router"]
