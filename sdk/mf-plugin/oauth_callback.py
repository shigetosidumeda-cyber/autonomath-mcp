"""MF Cloud OAuth2 (authorization_code grant) フロー。

エンドポイント:
  GET  /oauth/authorize  → MF 認可画面に redirect (state CSRF 付与)
  GET  /oauth/callback   → code + state を受け取り、token endpoint で交換
  POST /oauth/logout     → session 破棄 + revoke endpoint 呼び出し (best-effort)

注意:
  - MF の認可は事業者単位 (tenant) であり、個人ユーザー単位ではない。
  - access_token + refresh_token + tenant 情報は **server-side session** にのみ
    保持する (HttpOnly + Secure + SameSite=None クッキー、itsdangerous 署名)。
  - クライアント認証方式は CLIENT_SECRET_BASIC (Authorization ヘッダ)。
  - PKCE は MF アプリポータルで confidential client なら任意。本実装は
    state CSRF + secret_basic で十分とし、PKCE は将来 env スイッチで追加可能に
    フックを残す。
"""

from __future__ import annotations

import base64
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from config import Settings
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/oauth", tags=["oauth"])


# ---- helpers ---------------------------------------------------------------


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    """RFC6749 §2.3.1 Authorization: Basic ..."""
    raw = f"{client_id}:{client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _new_state() -> str:
    return secrets.token_urlsafe(32)


def _scrub_token(d: dict[str, Any]) -> dict[str, Any]:
    """log 出力前に access/refresh token を伏せる。"""
    safe = dict(d)
    for k in ("access_token", "refresh_token", "id_token"):
        if k in safe and safe[k]:
            safe[k] = f"<redacted len={len(safe[k])}>"
    return safe


# ---- routes ----------------------------------------------------------------


@router.get("/authorize")
def authorize(request: Request) -> RedirectResponse:
    """MF 認可エンドポイントに redirect。state を session に保存。"""
    settings: Settings = request.app.state.settings
    state = _new_state()
    request.session["oauth_state"] = state

    params = {
        "response_type": "code",
        "client_id": settings.mf_client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": settings.mf_scope,
        "state": state,
        # MF は prompt=consent で再同意を強制可能 (future use)。
    }
    target = f"{settings.mf_authorize_url}?{urlencode(params)}"
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
async def callback(
    request: Request,
    code: str = Query(..., min_length=1, max_length=2048),
    state: str = Query(..., min_length=1, max_length=128),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
) -> RedirectResponse:
    """MF からの redirect を受け、token endpoint で access_token を取得。"""
    settings: Settings = request.app.state.settings

    # ---- error path (user denied / invalid_request etc) ------------------
    if error:
        # error_description は MF 側の出力。token を含まない既定動作だが念のため
        # session に流し込まずに UI へクエリ転送する。
        msg = error_description or error
        return RedirectResponse(
            url=f"/static/index.html?auth_error={msg[:200]}",
            status_code=status.HTTP_302_FOUND,
        )

    # ---- state CSRF -------------------------------------------------------
    expected = request.session.pop("oauth_state", None)
    if not expected or not secrets.compare_digest(expected, state):
        raise HTTPException(status_code=400, detail="invalid_state")

    # ---- exchange code for token -----------------------------------------
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.redirect_uri,
    }
    headers = {
        "Authorization": _basic_auth_header(settings.mf_client_id, settings.mf_client_secret),
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(settings.mf_token_url, data=body, headers=headers)
    if resp.status_code != 200:
        # token 交換失敗。secret は body に含まれない (Authorization ヘッダ送信)
        # ため resp.text を出しても safe だが、念のため status のみ返す。
        raise HTTPException(
            status_code=502,
            detail=f"mf_token_exchange_failed: {resp.status_code}",
        )
    payload: dict[str, Any] = resp.json()

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="mf_token_missing_access_token")

    # ---- tenant 情報の取得 (best-effort) ---------------------------------
    # MF v2 は GET /tenants 等で事業者情報を引ける。失敗しても session を作る。
    tenant_uid: str | None = None
    tenant_name: str | None = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            tinfo = await client.get(
                f"{settings.mf_token_url.rsplit('/', 1)[0]}/tenants",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if tinfo.status_code == 200:
            tdata = tinfo.json()
            # MF 標準レスポンス形に合わせ、複数 tenant のうち先頭を採用。
            items = (
                tdata.get("data")
                or tdata.get("tenants")
                or (tdata if isinstance(tdata, list) else [])
            )
            if items:
                first = items[0]
                tenant_uid = first.get("uid") or first.get("id")
                tenant_name = first.get("name") or first.get("display_name")
    except httpx.HTTPError:
        pass  # tenant lookup は best-effort

    # ---- session 書き込み --------------------------------------------------
    request.session["mf"] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": int(payload.get("expires_in", 0) or 0),
        "scope": payload.get("scope", settings.mf_scope),
        "tenant_uid": tenant_uid,
        "tenant_name": tenant_name,
    }
    return RedirectResponse(url="/static/index.html", status_code=status.HTTP_302_FOUND)


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, Any]:
    """session を破棄し、MF 側にも revoke を送る (best-effort)。"""
    settings: Settings = request.app.state.settings
    mf_session = request.session.get("mf") or {}
    token = mf_session.get("access_token")
    request.session.clear()

    if token:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    settings.mf_revoke_url,
                    data={"token": token, "token_type_hint": "access_token"},
                    headers={
                        "Authorization": _basic_auth_header(
                            settings.mf_client_id, settings.mf_client_secret
                        ),
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
        except httpx.HTTPError:
            pass  # revoke 失敗は無視 (session 側はもう破棄済み)

    return {
        "ok": True,
        "_disclaimer": "税理士法 §52 — 本サービスは税理士業務に該当する個別アドバイスを行いません。",
    }


# ---- refresh helper (used by proxy_endpoints) ------------------------------


async def refresh_access_token(settings: Settings, refresh_token: str) -> dict[str, Any]:
    """access_token 期限切れ時に呼ぶ。proxy_endpoints から使用。"""
    body = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    headers = {
        "Authorization": _basic_auth_header(settings.mf_client_id, settings.mf_client_secret),
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(settings.mf_token_url, data=body, headers=headers)
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="mf_refresh_failed")
    return resp.json()


__all__ = ["router", "refresh_access_token"]
