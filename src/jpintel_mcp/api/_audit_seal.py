"""Audit-seal HMAC helper (税理士事務所 bundle, 2026-04-29).

Why this exists
---------------
税理士事務所 customers using AutonoMath as a back-end for client advisory
work need a tamper-evident receipt for every metered call so the resulting
work product carries a verifiable provenance chain that survives 国税庁
査察 / 税理士法 §41 帳簿等保存義務 / 弁護士法 §72 boundary review.

Each metered response carries an `audit_seal` envelope field:

    {
      "call_id":     "01HW2J3...",         // ULID-flavored, 26 chars
      "ts":          "2026-04-29T12:34:56+00:00",
      "query_hash":  "sha256-hex...",      // canonical-JSON SHA-256
      "response_hash": "sha256-hex...",    // PII-redacted body SHA-256
      "source_urls": ["https://nta.go.jp/..."],
      "hmac":        "sha256-hex..."       // signed HMAC over the seal
    }

The `hmac` field is computed against `settings.audit_seal_secret` which is
DISTINCT from `settings.api_key_salt` — leaking one does not compromise
the other. The secret is held by Bookyou株式会社 ONLY; customers cannot
forge a seal even with full DB access.

Storage
-------
The seal is also persisted to `audit_seals` (migration 089) for 7-year
statutory retention per 税理士法 §41 / 法人税法 §150-2 / 所得税法 §148.
The customer can later re-verify the seal via
`GET /v1/me/audit_seal/{call_id}` (¥3 metered).

Cost note
---------
Computing the seal is in-process — no Anthropic / Stripe / external
calls. The DB INSERT happens in `_record_usage_async` so the request
hot path never waits on the seal write.

This module purposefully avoids the autonomath_disclaimer surface
(SENSITIVE_TOOLS in envelope_wrapper.py) — the seal is a security
primitive, not a customer-LLM prompt fragment.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import secrets
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from jpintel_mcp.config import settings

# 7-year retention per 税理士法 §41 帳簿等保存義務 / 法人税法 §150-2.
# Calendar years (365×7 + 2 leap days) is close enough — the cron sweep
# rounds to the day.
_RETENTION_YEARS = 7

# Crockford-style base32 alphabet for ULID call_ids. Avoids ambiguous
# chars (I/L/O/U) so a customer who reads back a call_id over the phone
# to support does not transcribe "0" as "O" or "1" as "I".
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _new_call_id() -> str:
    """Return a 26-char ULID-flavored id (10-char ms timestamp + 16-char rand).

    Not a true RFC ULID (no monotonic counter) — a 16-char Crockford
    random suffix is plenty for our scale (~10^9 IDs/ms collision-free
    by birthday bound). Sortable by prefix for time-range scans.
    """
    ms = int(time.time() * 1000)
    # 10 chars × 5 bits = 50 bits of timestamp (~35 years from 1970).
    ts_chars = []
    for _ in range(10):
        ts_chars.append(_CROCKFORD[ms & 0x1F])
        ms >>= 5
    ts_part = "".join(reversed(ts_chars))
    rand_chars = []
    for _ in range(16):
        rand_chars.append(_CROCKFORD[secrets.randbits(5)])
    return ts_part + "".join(rand_chars)


def _canonical_json(payload: Any) -> str:
    """Return a deterministic JSON string for hashing.

    sort_keys + no whitespace + ensure_ascii=False so Japanese strings
    don't expand to \\uXXXX escapes (which would change the hash for
    cosmetic reasons). Falls back to str() for non-JSON-serializable
    leaves so the hasher never raises.
    """
    if payload is None:
        return ""
    try:
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            default=str,
        )
    except (TypeError, ValueError):
        return str(payload)


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def compute_hmac(call_id: str, ts: str, query_hash: str, response_hash: str) -> str:
    """Return the HMAC-SHA256 hex digest binding the seal fields.

    The signature surface is intentionally narrow (4 fields) so the
    customer's verification routine is straightforward — they don't
    need to sort source_urls or worry about unicode normalization
    for the URL list. The URL list itself is verified by reading the
    persisted row at /v1/me/audit_seal/{call_id} and comparing.
    """
    payload = f"{call_id}|{ts}|{query_hash}|{response_hash}"
    return _hmac.new(
        settings.audit_seal_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_hmac(
    call_id: str,
    ts: str,
    query_hash: str,
    response_hash: str,
    expected_hmac: str,
) -> bool:
    """Constant-time HMAC verify. Returns False on any mismatch."""
    actual = compute_hmac(call_id, ts, query_hash, response_hash)
    return _hmac.compare_digest(actual, expected_hmac)


def extract_source_urls(response_body: Any, *, max_urls: int = 32) -> list[str]:
    """Walk a response dict/list and pluck `source_url` / `source_urls` leaves.

    Limits to ``max_urls`` to keep the seal row bounded — a sub-query
    response that returns 100 programs has 100 source_urls but we only
    persist the first 32. Order is preserved (stable for verification).
    """
    out: list[str] = []
    seen: set[str] = set()

    def _walk(node: Any) -> None:
        if len(out) >= max_urls:
            return
        if isinstance(node, dict):
            for key in ("source_url", "source_urls", "primary_source_url"):
                v = node.get(key)
                if isinstance(v, str) and v.startswith(("http://", "https://")):
                    if v not in seen:
                        seen.add(v)
                        out.append(v)
                elif isinstance(v, list):
                    for u in v:
                        if isinstance(u, str) and u.startswith(("http://", "https://")):
                            if u not in seen:
                                seen.add(u)
                                out.append(u)
            for v in node.values():
                if len(out) >= max_urls:
                    return
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                if len(out) >= max_urls:
                    return
                _walk(item)

    _walk(response_body)
    return out[:max_urls]


def build_seal(
    *,
    endpoint: str,
    request_params: dict[str, Any] | None,
    response_body: Any,
    client_tag: str | None = None,
) -> dict[str, Any]:
    """Build the audit_seal envelope dict (without persistence).

    Returned dict is the exact shape inserted into the response under
    the ``audit_seal`` key. Persistence happens separately via
    :func:`persist_seal` so a sandbox / test path can use the dict
    without touching SQLite.
    """
    call_id = _new_call_id()
    ts = datetime.now(UTC).isoformat()
    query_hash = _sha256_hex(_canonical_json(request_params or {}))
    response_hash = _sha256_hex(_canonical_json(response_body))
    source_urls = extract_source_urls(response_body)
    hmac_hex = compute_hmac(call_id, ts, query_hash, response_hash)
    seal: dict[str, Any] = {
        "call_id": call_id,
        "ts": ts,
        "endpoint": endpoint,
        "query_hash": query_hash,
        "response_hash": response_hash,
        "source_urls": source_urls,
        "hmac": hmac_hex,
    }
    if client_tag:
        seal["client_tag"] = client_tag
    return seal


def persist_seal(
    conn: sqlite3.Connection,
    *,
    seal: dict[str, Any],
    api_key_hash: str,
) -> None:
    """Insert the seal into audit_seals with 7-year retention.

    Best-effort: if the table is missing (migration 089 not yet applied)
    or the INSERT fails, we swallow the error so the customer-facing
    response is never blocked. Operators see the failure via the usual
    sqlite3 OperationalError path on the daily cron sweep.
    """
    try:
        retention_until = (
            datetime.fromisoformat(seal["ts"]) + timedelta(days=365 * _RETENTION_YEARS + 2)
        ).isoformat()
    except (TypeError, ValueError):
        retention_until = (datetime.now(UTC) + timedelta(days=365 * _RETENTION_YEARS + 2)).isoformat()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO audit_seals("
            "  call_id, api_key_hash, ts, endpoint, query_hash, response_hash,"
            "  source_urls_json, client_tag, hmac, retention_until"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                seal["call_id"],
                api_key_hash,
                seal["ts"],
                seal["endpoint"],
                seal["query_hash"],
                seal["response_hash"],
                json.dumps(seal.get("source_urls", []), ensure_ascii=False),
                seal.get("client_tag"),
                seal["hmac"],
                retention_until,
            ),
        )
    except sqlite3.OperationalError:
        # Migration 089 not applied yet — never block the customer
        # response on an audit_seal write failure. Same posture as
        # log_empty_search.
        pass


__all__ = [
    "build_seal",
    "compute_hmac",
    "extract_source_urls",
    "persist_seal",
    "verify_hmac",
]
