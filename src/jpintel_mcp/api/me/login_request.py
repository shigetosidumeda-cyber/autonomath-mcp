"""magic-link login request: email → 6 digit code → mail."""
# ruff: noqa: SIM115,SIM117,BLE001,E501,F401,F841,PTH123,S301,S314,S603,UP017


from __future__ import annotations

import os
import secrets
import smtplib
import sqlite3
import time
from email.mime.text import MIMEText

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

router = APIRouter(prefix="/v1/me", tags=["me-auth"])


class LoginRequest(BaseModel):
    email: EmailStr


class LoginRequestResponse(BaseModel):
    sent: bool
    expires_in_seconds: int
    reuse_existing_code: bool


def _conn() -> sqlite3.Connection:
    db_path = os.environ.get("AUTONOMATH_DB_PATH", "data/autonomath.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS magic_link_codes (
        email TEXT NOT NULL,
        code_hash TEXT NOT NULL,
        issued_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        consumed INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (email, issued_at)
    )""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mlc_email_active ON magic_link_codes(email, consumed, expires_at)"
    )
    conn.commit()


@router.post("/login_request", response_model=LoginRequestResponse)
def login_request(req: LoginRequest) -> LoginRequestResponse:
    """Request a 6-digit magic-link code. Returns reuse_existing_code=true if active code exists."""
    email = req.email.lower()
    now = int(time.time())
    expires_at = now + 900  # 15 min TTL
    conn = _conn()
    _ensure_table(conn)
    # Check active (non-consumed, not expired) code
    row = conn.execute(
        "SELECT code_hash, expires_at FROM magic_link_codes WHERE email = ? AND consumed = 0 AND expires_at > ? ORDER BY issued_at DESC LIMIT 1",
        (email, now),
    ).fetchone()
    if row:
        return LoginRequestResponse(
            sent=False, expires_in_seconds=row["expires_at"] - now, reuse_existing_code=True
        )
    # Generate new 6-digit code
    code = f"{secrets.randbelow(1_000_000):06d}"
    # Hash code with email salt (bcrypt-like)
    import hashlib

    code_hash = hashlib.sha256(f"{email}:{code}".encode()).hexdigest()
    conn.execute(
        "INSERT INTO magic_link_codes (email, code_hash, issued_at, expires_at) VALUES (?, ?, ?, ?)",
        (email, code_hash, now, expires_at),
    )
    conn.commit()
    # Send mail (xrea bookyou.net smtp、memory reference_bookyou_mail)
    try:
        _send_mail(email, code)
    except Exception as e:
        # log but don't reveal SMTP errors
        print(f"[login_request] mail send failed for {email}: {e}")
    return LoginRequestResponse(sent=True, expires_in_seconds=900, reuse_existing_code=False)


def _send_mail(email: str, code: str) -> None:
    smtp_host = os.environ.get("BOOKYOU_SMTP_HOST", "s374.xrea.com")
    smtp_port = int(os.environ.get("BOOKYOU_SMTP_PORT", "587"))
    smtp_user = os.environ.get("BOOKYOU_SMTP_USER", "info")  # local part only
    smtp_pass = os.environ.get("BOOKYOU_SMTP_PASS", "")
    if not smtp_pass:
        return  # dev mode skip
    msg = MIMEText(
        f"jpcite ログインコード:\n\n  {code}\n\n15 分以内にダッシュボードで入力してください。\n\n"
        f"心当たりがない場合はこのメールを破棄してください。\n\n"
        f"Bookyou株式会社 / info@bookyou.net",
        _charset="utf-8",
    )
    msg["Subject"] = f"jpcite ログインコード: {code}"
    msg["From"] = "info@bookyou.net"
    msg["To"] = email
    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.send_message(msg)
