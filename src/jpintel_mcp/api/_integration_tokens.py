"""Encrypted credential storage for the workflow-integrations 5-pack.

Per migration 105, ``integration_accounts`` holds one Fernet-encrypted blob
per ``(api_key_hash, provider)`` pair. Encryption key is the env var
``INTEGRATION_TOKEN_SECRET`` (Fernet 32-byte url-safe base64 key); no
plaintext secret is ever persisted at rest.

Three providers are wired here:

* ``google_sheets`` — refresh+access token pair (OAuth 2.0, customer-owned
  Google Cloud project). The customer auths via
  ``/v1/integrations/google/start`` → callback → token row stored.
* ``kintone`` — domain + app_id + customer-issued API token. No OAuth;
  customer pastes the token into ``/v1/integrations/kintone/connect``.
* ``postmark_inbound`` — presence-flag + reply-from address. No secret;
  enables routing of inbound parse webhooks for the calling api key.

Why a small helper module (vs. inlining into ``integrations.py``):

* The Fernet key handling has its own surface — invalid env, decryption
  failures must surface a 503 (not a 500) so the customer sees "rotate
  the operator secret" rather than a generic error envelope.
* Two separate routers consume this (``api/integrations.py`` for the
  start/callback/sync, ``scripts/cron/sync_kintone.py`` for the daily
  fan-out). A shared helper keeps the JSON schema for ``encrypted_blob``
  in one place.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

logger = logging.getLogger("jpintel.integrations.tokens")


def _fernet():
    """Return a Fernet / MultiFernet instance using the operator secret.

    ``INTEGRATION_TOKEN_SECRET`` may be a single 32-byte url-safe base64
    Fernet key OR a comma-separated list. The first key is the active
    signer (encryption uses key[0]); subsequent keys decrypt legacy
    ciphertexts so the operator can rotate without invalidating stored
    Google / kintone / Postmark credential rows.

    Raises HTTP 503 when the operator secret is missing/malformed. We
    surface 503 (not 500) so the dashboard can render a "the operator has
    not finished setup" message instead of an opaque traceback.
    """
    raw = os.environ.get("INTEGRATION_TOKEN_SECRET")
    if not raw:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "integration token storage not configured "
            "(operator must set INTEGRATION_TOKEN_SECRET)",
        )
    try:
        from cryptography.fernet import Fernet, MultiFernet

        candidates = [k.strip() for k in raw.split(",") if k.strip()]
        if len(candidates) == 1:
            return Fernet(candidates[0].encode("utf-8"))
        return MultiFernet([Fernet(k.encode("utf-8")) for k in candidates])
    except Exception as exc:  # noqa: BLE001
        logger.error("integration_token_secret_invalid: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "integration token storage misconfigured (Fernet key invalid)",
        ) from exc


def encrypt_blob(payload: dict[str, Any]) -> bytes:
    """Encrypt a JSON-serializable dict to a Fernet ciphertext blob."""
    fernet = _fernet()
    return fernet.encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def decrypt_blob(blob: bytes) -> dict[str, Any]:
    """Decrypt a Fernet ciphertext into the original dict.

    Decryption failures surface as 503 (rotated key) rather than 401, so a
    customer hitting a stale encrypted row gets "operator must rotate"
    triage rather than "your credentials are bad".
    """
    fernet = _fernet()
    try:
        plain = fernet.decrypt(blob)
    except Exception as exc:  # noqa: BLE001 — Fernet raises InvalidToken
        logger.warning("integration_token_decrypt_failed: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "stored integration credential cannot be decrypted "
            "(operator INTEGRATION_TOKEN_SECRET may have rotated)",
        ) from exc
    try:
        return json.loads(plain.decode("utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("integration_token_blob_corrupt")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "stored integration credential is corrupt",
        ) from exc


def upsert_account(
    db: sqlite3.Connection,
    *,
    api_key_hash: str,
    provider: str,
    payload: dict[str, Any],
    display_handle: str | None,
) -> int:
    """Insert or replace a row in ``integration_accounts``. Returns row id."""
    if provider not in ("google_sheets", "kintone", "postmark_inbound"):
        raise ValueError(f"unknown integration provider: {provider}")
    blob = encrypt_blob(payload)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    db.execute(
        """
        INSERT INTO integration_accounts
            (api_key_hash, provider, encrypted_blob, display_handle,
             created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (api_key_hash, provider) DO UPDATE SET
            encrypted_blob = excluded.encrypted_blob,
            display_handle = excluded.display_handle,
            updated_at = excluded.updated_at,
            revoked_at = NULL
        """,
        (api_key_hash, provider, blob, display_handle, now, now),
    )
    db.commit()
    row = db.execute(
        "SELECT id FROM integration_accounts "
        "WHERE api_key_hash = ? AND provider = ?",
        (api_key_hash, provider),
    ).fetchone()
    return int(row["id"]) if row else 0


def load_account(
    db: sqlite3.Connection,
    *,
    api_key_hash: str,
    provider: str,
) -> dict[str, Any] | None:
    """Return the decrypted credential payload, or None if not connected."""
    row = db.execute(
        "SELECT encrypted_blob, display_handle, revoked_at "
        "FROM integration_accounts "
        "WHERE api_key_hash = ? AND provider = ?",
        (api_key_hash, provider),
    ).fetchone()
    if row is None or row["revoked_at"]:
        return None
    payload = decrypt_blob(row["encrypted_blob"])
    payload["_display_handle"] = row["display_handle"]
    return payload


def revoke_account(
    db: sqlite3.Connection, *, api_key_hash: str, provider: str
) -> bool:
    """Mark a credential row revoked. Returns True if a row was updated."""
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cur = db.execute(
        "UPDATE integration_accounts SET revoked_at = ? "
        "WHERE api_key_hash = ? AND provider = ? AND revoked_at IS NULL",
        (now, api_key_hash, provider),
    )
    db.commit()
    return cur.rowcount > 0


def record_sync(
    db: sqlite3.Connection,
    *,
    api_key_hash: str,
    provider: str,
    idempotency_key: str,
    saved_search_id: int | None,
    status_label: str,
    result_count: int,
    error_class: str | None = None,
) -> tuple[bool, int]:
    """Insert into ``integration_sync_log`` with idempotency-key dedup.

    Returns ``(is_new, log_row_id)``. When ``is_new`` is False, the caller
    should NOT bill again — the existing row already accounted for one
    ¥3 charge against the api_key.
    """
    try:
        cur = db.execute(
            """INSERT INTO integration_sync_log
                   (api_key_hash, provider, idempotency_key, saved_search_id,
                    status, result_count, error_class)
                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                api_key_hash,
                provider,
                idempotency_key,
                saved_search_id,
                status_label,
                result_count,
                error_class,
            ),
        )
        db.commit()
        return True, int(cur.lastrowid or 0)
    except sqlite3.IntegrityError:
        # UNIQUE (provider, idempotency_key) — already delivered. Return
        # the existing row id and signal "not new".
        row = db.execute(
            "SELECT id FROM integration_sync_log "
            "WHERE provider = ? AND idempotency_key = ?",
            (provider, idempotency_key),
        ).fetchone()
        return False, int(row["id"]) if row else 0


__all__ = [
    "decrypt_blob",
    "encrypt_blob",
    "load_account",
    "record_sync",
    "revoke_account",
    "upsert_account",
]
