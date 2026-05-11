"""magic-link verify: email + 6 digit code → JWT 24h."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from base64 import urlsafe_b64encode

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, EmailStr

router = APIRouter(prefix="/v1/me", tags=["me-auth"])


class LoginVerifyRequest(BaseModel):
    email: EmailStr
    code: str


class LoginVerifyResponse(BaseModel):
    ok: bool
    jwt: str | None = None
    expires_at: int


def _conn() -> sqlite3.Connection:
    db_path = os.environ.get("AUTONOMATH_DB_PATH", "data/autonomath.db")
    return sqlite3.connect(db_path)


@router.post("/login_verify", response_model=LoginVerifyResponse)
def login_verify(req: LoginVerifyRequest, response: Response) -> LoginVerifyResponse:
    email = req.email.lower()
    code = req.code.strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(status_code=400, detail="code must be 6 digits")
    now = int(time.time())
    code_hash = hashlib.sha256(f"{email}:{code}".encode()).hexdigest()
    conn = _conn()
    # Find matching active code
    cur = conn.execute(
        "SELECT issued_at, expires_at FROM magic_link_codes WHERE email = ? AND code_hash = ? AND consumed = 0 AND expires_at > ?",
        (email, code_hash, now),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="invalid or expired code")
    # Mark consumed
    conn.execute(
        "UPDATE magic_link_codes SET consumed = 1 WHERE email = ? AND issued_at = ?",
        (email, row[0]),
    )
    conn.commit()
    # Mint JWT (HS256, 24h)
    secret = os.environ.get("JPCITE_SESSION_SECRET", "dev-secret-do-not-use-in-prod-please-set-env")
    exp = now + 86400
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": email, "iat": now, "exp": exp}
    h_b64 = (
        urlsafe_b64encode(json.dumps(header, separators=(",", ":")).encode()).rstrip(b"=").decode()
    )
    p_b64 = (
        urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    )
    sig = hmac.new(secret.encode(), f"{h_b64}.{p_b64}".encode(), hashlib.sha256).digest()
    sig_b64 = urlsafe_b64encode(sig).rstrip(b"=").decode()
    jwt = f"{h_b64}.{p_b64}.{sig_b64}"
    response.set_cookie(
        key="jpcite_session",
        value=jwt,
        max_age=86400,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return LoginVerifyResponse(ok=True, jwt=jwt, expires_at=exp)
