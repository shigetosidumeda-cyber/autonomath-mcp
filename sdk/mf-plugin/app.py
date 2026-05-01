"""FastAPI エントリ。

  /healthz                    Fly.io / uptime probe
  /oauth/{authorize,callback,logout}   MF OAuth2 (authorization_code)
  /mf-plugin/{search-*,check-*,me}    proxy to api.jpcite.com
  /static/*                   vanilla HTML UI (frontend/)
  /                           bounce to /oauth/authorize or /static/index.html

CSP `frame-ancestors` は MF Cloud の各製品 (会計 / 請求書 / 給与 等) ホスト群に
限定。inline script は popup UI 内のみ許可。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from config import MF_FRAME_ANCESTORS, load_settings
from oauth_callback import router as oauth_router
from proxy_endpoints import router as proxy_router


HERE = Path(__file__).parent
FRONTEND_DIR = HERE / "frontend"


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="jpcite-mf-plugin", version="0.2.0", docs_url=None, redoc_url=None)
    app.state.settings = settings

    # session: HttpOnly + Secure + SameSite=None (iframe 内で動作するため)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="jpcite_mf_sid",
        max_age=6 * 60 * 60,  # 6h
        same_site="none",
        https_only=settings.is_production,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        ancestors = " ".join(MF_FRAME_ANCESTORS)
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://jpcite.com; "
            "connect-src 'self'; "
            f"frame-ancestors 'self' {ancestors};"
        )
        response.headers["Content-Security-Policy"] = csp
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # X-Frame-Options を**送らない** (CSP frame-ancestors を優先するため)。
        return response

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        return {"ok": True, "version": "0.2.0"}

    app.include_router(oauth_router)
    app.include_router(proxy_router)
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def root(request: Request) -> RedirectResponse:
        sess = request.session.get("mf") or {}
        if not sess.get("access_token"):
            return RedirectResponse(url="/oauth/authorize", status_code=302)
        return RedirectResponse(url="/static/index.html", status_code=302)

    @app.exception_handler(404)
    async def not_found(_request: Request, _exc) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": "not_found",
                "_disclaimer": "税理士法 §52 — 本サービスは税理士業務に該当する個別アドバイスを行いません。",
            },
        )

    return app


app = create_app()


def run() -> None:  # pragma: no cover
    import uvicorn

    settings = load_settings()
    uvicorn.run("app:app", host="0.0.0.0", port=settings.port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    run()
