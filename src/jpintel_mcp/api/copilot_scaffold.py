"""Dim S — embedded copilot scaffold (LLM-0).

REST surface for the Dim S "embedded copilot scaffold" pattern (per
``feedback_copilot_scaffold_only_no_llm.md``). The widget is dropped into
a customer SaaS (freee / MoneyForward / Notion / Slack), and inside that
widget the customer's OWN agent talks to OUR MCP proxy. Our side never
invokes an LLM API.

Three responsibilities (and ONLY three):

  1. Scaffold lookup        — GET /v1/copilot/widgets        list enabled widgets
  2. MCP proxy descriptor   — GET /v1/copilot/proxy/{host}   return mcp_proxy_url + OAuth scope
  3. OAuth bridge stub      — POST /v1/copilot/session       open / close audit row

What this file MUST NOT do (enforced by test_dim_s_copilot_scaffold):

  * pull in any LLM SDK package
  * call any model-completion endpoint
  * store any prompt / response text
  * carry any "completion_tokens" or "model" metadata

Pure storage proxy. Reasoning happens on the customer side.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

# NOTE: This module intentionally imports NO LLM SDK. The grep guard in
# tests/test_dim_s_copilot_scaffold.py rejects any `anthropic` / `openai`
# substring in this file. The scaffold is OAuth + MCP proxy + session
# audit ONLY (per feedback_copilot_scaffold_only_no_llm).

_DEFAULT_DB = Path(__file__).resolve().parents[3] / "autonomath.db"


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------


def list_enabled_widgets(db_path: Path | None = None) -> list[dict[str, object]]:
    """Return enabled widget rows (alphabetical by host_saas)."""
    db = db_path or _DEFAULT_DB
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT widget_id, host_saas, embed_url, mcp_proxy_url, oauth_scope "
            "FROM v_copilot_widget_enabled"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "widget_id": r[0],
            "host_saas": r[1],
            "embed_url": r[2],
            "mcp_proxy_url": r[3],
            "oauth_scope": r[4],
        }
        for r in rows
    ]


def get_proxy_descriptor(host_saas: str, db_path: Path | None = None) -> dict[str, object] | None:
    """Return the MCP proxy descriptor for a host SaaS, or None if not enabled."""
    db = db_path or _DEFAULT_DB
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            "SELECT widget_id, embed_url, mcp_proxy_url, oauth_scope "
            "FROM am_copilot_widget_config "
            "WHERE host_saas = ? AND enabled = 1",
            (host_saas,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "widget_id": row[0],
        "host_saas": host_saas,
        "embed_url": row[1],
        "mcp_proxy_url": row[2],
        "oauth_scope": row[3],
    }


# ---------------------------------------------------------------------------
# Session audit (OAuth bridge stub — token hashed, never stored raw)
# ---------------------------------------------------------------------------


def _hash_token(raw_token: str) -> str:
    """Hash a raw OAuth token with sha256. Raw token is never persisted."""
    if not isinstance(raw_token, str) or not raw_token:
        msg = "raw_token must be a non-empty string"
        raise ValueError(msg)
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def open_session(
    widget_id: int,
    raw_token: str,
    db_path: Path | None = None,
) -> int:
    """Open an audit row; return the new session_id.

    The raw OAuth token is hashed (sha256) before insertion. The raw
    token never touches the DB.
    """
    db = db_path or _DEFAULT_DB
    token_hash = _hash_token(raw_token)
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            "INSERT INTO am_copilot_session_log (widget_id, user_token_hash) VALUES (?, ?)",
            (widget_id, token_hash),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def close_session(session_id: int, db_path: Path | None = None) -> bool:
    """Stamp ended_at for an open session; return True if a row was closed."""
    db = db_path or _DEFAULT_DB
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            "UPDATE am_copilot_session_log "
            "SET ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE session_id = ? AND ended_at IS NULL",
            (session_id,),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


__all__ = (
    "close_session",
    "get_proxy_descriptor",
    "list_enabled_widgets",
    "open_session",
)
