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

import contextlib
import hashlib
import hmac as _hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta, timezone
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
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
    except (TypeError, ValueError):
        return str(payload)


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _legacy_key() -> dict[str, Any]:
    return {"v": 1, "s": settings.audit_seal_secret, "retired_at": None}


def _load_keys() -> list[dict[str, Any]]:
    """Return audit-seal HMAC keys from the live environment.

    ``JPINTEL_AUDIT_SEAL_KEYS`` is intentionally read on every call so a
    rotation secret update takes effect without a process restart. The
    production boot gate validates the value strictly; this helper is lenient
    and falls back to the legacy single-secret path in dev/test.
    """
    raw = os.getenv("JPINTEL_AUDIT_SEAL_KEYS")
    if not raw or not raw.strip():
        return [_legacy_key()]

    keys: list[dict[str, Any]] = []
    try:
        stripped = raw.strip()
        if stripped[0] in "[{":
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                parsed = [parsed]
            if not isinstance(parsed, list):
                return [_legacy_key()]
            items = parsed
        else:
            items = [part.strip() for part in stripped.split(",")]
    except (json.JSONDecodeError, TypeError, ValueError, IndexError):
        return [_legacy_key()]

    for fallback_version, item in enumerate(items, start=1):
        retired_at = None
        if isinstance(item, dict):
            secret = item.get("s")
            version_raw = item.get("v", item.get("key_version", fallback_version))
            retired_at = item.get("retired_at")
        else:
            secret = item
            version_raw = fallback_version
        if not isinstance(secret, str) or not secret:
            continue
        try:
            version = int(version_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            version = fallback_version
        keys.append({"v": version, "s": secret, "retired_at": retired_at})

    if not keys:
        return [_legacy_key()]
    return sorted(keys, key=lambda key: int(key["v"]))


def _active_key() -> dict[str, Any]:
    keys = _load_keys()
    active = [key for key in keys if key.get("retired_at") in (None, "")]
    candidates = active or keys
    return max(candidates, key=lambda key: int(key["v"]))


def _key_for_version(key_version: int) -> dict[str, Any]:
    for key in _load_keys():
        if int(key["v"]) == int(key_version):
            return key
    raise ValueError(f"unknown audit seal key_version: {key_version}")


def _hmac_for_secret(
    call_id: str,
    ts: str,
    query_hash: str,
    response_hash: str,
    secret: str,
    *,
    seal_id: str | None = None,
    corpus_snapshot_id: str | None = None,
) -> str:
    payload = f"{call_id}|{ts}|{query_hash}|{response_hash}"
    if seal_id is not None or corpus_snapshot_id is not None:
        payload = f"{payload}|{seal_id or ''}|{corpus_snapshot_id or ''}"
    return _hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _payload_sig_for_secret(payload: bytes, secret: str) -> str:
    return _hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def sign(payload: bytes) -> dict[str, Any]:
    """Sign arbitrary canonical payload bytes with the active audit-seal key."""
    key = _active_key()
    return {
        "alg": "HMAC-SHA256",
        "key_version": int(key["v"]),
        "sig": _payload_sig_for_secret(payload, str(key["s"])),
    }


def verify(payload: bytes, seal: dict[str, Any] | str) -> bool:
    """Verify a ``sign`` envelope, trying all keys when no version is present."""
    if isinstance(seal, str):
        expected_sig = seal
        key_version = None
    elif isinstance(seal, dict):
        expected_sig = seal.get("sig") or seal.get("hmac") or ""
        key_version = seal.get("key_version")
    else:
        return False
    if not isinstance(expected_sig, str):
        return False

    if key_version is not None:
        try:
            key = _key_for_version(int(key_version))
        except (TypeError, ValueError):
            return False
        actual = _payload_sig_for_secret(payload, str(key["s"]))
        return _hmac.compare_digest(actual, expected_sig)

    for key in _load_keys():
        actual = _payload_sig_for_secret(payload, str(key["s"]))
        if _hmac.compare_digest(actual, expected_sig):
            return True
    return False


def compute_hmac(
    call_id: str,
    ts: str,
    query_hash: str,
    response_hash: str,
    *,
    key_version: int | None = None,
    seal_id: str | None = None,
    corpus_snapshot_id: str | None = None,
) -> str:
    """Return the HMAC-SHA256 hex digest binding the seal fields.

    The legacy signature surface is the 4 core hash fields. New §17.D
    public seals also bind ``seal_id`` and ``corpus_snapshot_id`` so a
    persisted row cannot swap the public verify id or snapshot label
    while keeping ``verified=true``.
    """
    key = _active_key() if key_version is None else _key_for_version(key_version)
    return _hmac_for_secret(
        call_id,
        ts,
        query_hash,
        response_hash,
        str(key["s"]),
        seal_id=seal_id,
        corpus_snapshot_id=corpus_snapshot_id,
    )


def verify_hmac(
    call_id: str,
    ts: str,
    query_hash: str,
    response_hash: str,
    expected_hmac: str,
    *,
    key_version: int | None = None,
    seal_id: str | None = None,
    corpus_snapshot_id: str | None = None,
) -> bool:
    """Constant-time HMAC verify. Returns False on any mismatch."""
    if key_version is not None:
        try:
            actual = compute_hmac(
                call_id,
                ts,
                query_hash,
                response_hash,
                key_version=key_version,
                seal_id=seal_id,
                corpus_snapshot_id=corpus_snapshot_id,
            )
        except (TypeError, ValueError):
            return False
        return _hmac.compare_digest(actual, expected_hmac)

    for key in _load_keys():
        actual = _hmac_for_secret(
            call_id,
            ts,
            query_hash,
            response_hash,
            str(key["s"]),
            seal_id=seal_id,
            corpus_snapshot_id=corpus_snapshot_id,
        )
        if _hmac.compare_digest(actual, expected_hmac):
            return True
    return False


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
                        if (
                            isinstance(u, str)
                            and u.startswith(("http://", "https://"))
                            and u not in seen
                        ):
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


#: JST timezone for the corpus_snapshot_id `YYYY-MM-DD` derivation.
_JST = timezone(timedelta(hours=9))

#: Process-local cache for the corpus_snapshot_id (task §17.D — refresh every
#: 6 hours, computed once per process boot, surfaced via
#: ``GET /v1/meta/corpus_snapshot`` and embedded in the audit_seal envelope).
#: The value is a ``corpus-YYYY-MM-DD`` string derived from the JST date of
#: ``MAX(am_source.last_verified)`` on autonomath.db. ``_lock`` protects the
#: read/refresh path under concurrent FastAPI workers; sqlite reads are short.
_CORPUS_SNAPSHOT_TTL_SECONDS = 6 * 3600
_corpus_snapshot_cache: dict[str, Any] = {
    "value": None,  # str | None — ``corpus-YYYY-MM-DD`` once seeded
    "computed_at": 0.0,  # monotonic seconds, 0 == never computed
}
_corpus_snapshot_lock = threading.Lock()


def _derive_corpus_snapshot_id() -> str:
    """Return ``corpus-YYYY-MM-DD`` for the current corpus state.

    Reads ``MAX(am_source.last_verified)`` from autonomath.db and converts
    that timestamp to a JST date. When the DB / table / column is absent
    (test envs where autonomath.db is a 0-byte placeholder) we fall back
    to today's JST date so the field is always populated.

    Never raises — any sqlite or filesystem failure collapses to the
    today-fallback so the response path is never blocked on corpus probe.
    """
    today_jst = datetime.now(_JST).strftime("corpus-%Y-%m-%d")
    try:
        db_path = settings.autonomath_db_path
    except Exception:  # noqa: BLE001 — config probe never fatal
        return today_jst
    if not db_path.exists() or db_path.stat().st_size == 0:
        return today_jst
    try:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            row = conn.execute("SELECT MAX(last_verified) FROM am_source").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return today_jst
    if not row or not row[0]:
        return today_jst
    raw = str(row[0])
    # ``last_verified`` is stored as ``YYYY-MM-DD HH:MM:SS`` UTC. Parse
    # tolerantly (with or without 'T', with or without timezone) and
    # convert to JST so the date label rolls over at JST midnight.
    parsed: datetime | None = None
    candidates = [raw, raw.replace(" ", "T")]
    if "+" not in raw and "Z" not in raw:
        candidates.append(raw.replace(" ", "T") + "+00:00")
    for cand in candidates:
        try:
            parsed = datetime.fromisoformat(cand)
            break
        except ValueError:
            continue
    if parsed is None:
        return today_jst
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(_JST).strftime("corpus-%Y-%m-%d")


def get_corpus_snapshot_id(*, force_refresh: bool = False) -> str:
    """Return the cached ``corpus-YYYY-MM-DD`` snapshot id.

    Computed once per process boot and refreshed every 6 hours. The cache
    is process-local — each worker computes independently. Performance:
    cache hit is a single dict lookup (sub-microsecond); the recompute
    path runs at most every 6 hours per worker.
    """
    now = time.monotonic()
    with _corpus_snapshot_lock:
        cached = _corpus_snapshot_cache.get("value")
        computed_at = _corpus_snapshot_cache.get("computed_at", 0.0)
        if (
            not force_refresh
            and isinstance(cached, str)
            and now - float(computed_at) < _CORPUS_SNAPSHOT_TTL_SECONDS
        ):
            return cached
        value = _derive_corpus_snapshot_id()
        _corpus_snapshot_cache["value"] = value
        _corpus_snapshot_cache["computed_at"] = now
        return value


def _reset_corpus_snapshot_cache_for_tests() -> None:
    """Test helper — drop the cached snapshot id."""
    with _corpus_snapshot_lock:
        _corpus_snapshot_cache["value"] = None
        _corpus_snapshot_cache["computed_at"] = 0.0


def _key_hash_prefix(api_key_hash: str | None) -> str:
    """Return the first 8 chars of the api_key_hash for the seal envelope.

    The full hash is statutory evidence and stays in the DB (audit_seals
    row). Customers see only the prefix in the response so their logs
    can group seals by key without leaking the full hash. Empty string
    when no key (anon path — but anon never reaches this codepath today).
    """
    if not api_key_hash:
        return ""
    return str(api_key_hash)[:8]


def _retention_until_for_seal(seal: dict[str, Any]) -> str:
    try:
        issued_at = datetime.fromisoformat(seal["ts"])
    except (KeyError, TypeError, ValueError):
        issued_at = datetime.now(UTC)
    return (issued_at + timedelta(days=365 * _RETENTION_YEARS + 2)).isoformat()


def _seal_key_version(seal: dict[str, Any]) -> int:
    try:
        return int(seal.get("key_version") or 1)
    except (TypeError, ValueError):
        return 1


def _execute_seal_insert(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...],
) -> None:
    cur = conn.execute(sql, params)
    if cur.rowcount != 1:
        raise sqlite3.IntegrityError(f"audit_seals insert rowcount={cur.rowcount}; expected 1")


def _ensure_unique_seal_id(conn: sqlite3.Connection, seal_id: str | None) -> None:
    if not seal_id:
        return
    try:
        row = conn.execute(
            "SELECT 1 FROM audit_seals WHERE seal_id = ? LIMIT 1",
            (seal_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return
    if row is not None:
        raise sqlite3.IntegrityError(f"duplicate audit seal_id: {seal_id}")


def _log_seal_persist_failure(
    conn: sqlite3.Connection,
    *,
    endpoint: str,
    api_key_hash: str | None,
    seal: dict[str, Any],
    reason: str,
) -> None:
    """Best-effort §52 telemetry for a paid response emitted without a seal."""
    with contextlib.suppress(Exception):
        conn.execute(
            "INSERT INTO audit_log_section52("
            "sampled_at, tool, request_hash, response_hash, "
            "disclaimer_present, advisory_terms_in_response, violation"
            ") VALUES (?,?,?,?,?,?,?)",
            (
                datetime.now(UTC).isoformat(),
                f"audit_seal.persist:{endpoint}",
                str(seal.get("query_hash") or ""),
                str(seal.get("response_hash") or ""),
                1,
                json.dumps(
                    [
                        {
                            "event_type": "seal_persist_fail",
                            "api_key_hash_prefix": _key_hash_prefix(api_key_hash),
                            "reason": reason[:200],
                        }
                    ],
                    ensure_ascii=False,
                ),
                1,
            ),
        )


def build_seal(
    *,
    endpoint: str,
    request_params: dict[str, Any] | None,
    response_body: Any,
    client_tag: str | None = None,
    api_key_hash: str | None = None,
    corpus_snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Build the audit_seal envelope dict (without persistence).

    Returned dict carries BOTH legacy fields (``call_id`` / ``ts`` /
    ``query_hash`` / ``response_hash`` / ``source_urls`` / ``hmac`` —
    used for the HMAC verification path) AND the §17.D task-spec
    surface (``seal_id`` / ``issued_at`` / ``subject_hash`` /
    ``key_hash_prefix`` / ``corpus_snapshot_id`` / ``verify_endpoint`` /
    ``_disclaimer``) so customer agents can copy the seal verbatim into
    their work-paper without picking field names.

    Persistence happens separately via :func:`persist_seal` so a sandbox
    / test path can use the dict without touching SQLite.

    Performance: SHA-256 of a ~50KB JSON body + a single HMAC measures
    well under 5ms on the API hot path (Q4 perf-diff bench).
    """
    call_id = _new_call_id()
    ts = datetime.now(UTC).isoformat()
    query_hash = _sha256_hex(_canonical_json(request_params or {}))
    response_hash = _sha256_hex(_canonical_json(response_body))
    source_urls = extract_source_urls(response_body)
    snapshot_id = corpus_snapshot_id or get_corpus_snapshot_id()
    seal_id = "seal_" + uuid.uuid4().hex
    key = _active_key()
    hmac_hex = _hmac_for_secret(
        call_id,
        ts,
        query_hash,
        response_hash,
        str(key["s"]),
        seal_id=seal_id,
        corpus_snapshot_id=snapshot_id,
    )
    seal: dict[str, Any] = {
        # ----- §17.D customer-facing surface -----------------------------
        "seal_id": seal_id,
        "issued_at": ts,
        "subject_hash": "sha256:" + response_hash,
        "key_hash_prefix": _key_hash_prefix(api_key_hash),
        "corpus_snapshot_id": snapshot_id,
        "verify_endpoint": f"/v1/audit/seals/{seal_id}",
        "_disclaimer": "verify_endpoint で seal の真正性を確認してください。",
        # ----- legacy fields (HMAC verification path) --------------------
        "call_id": call_id,
        "ts": ts,
        "endpoint": endpoint,
        "query_hash": query_hash,
        "response_hash": response_hash,
        "source_urls": source_urls,
        "alg": "HMAC-SHA256",
        "key_version": int(key["v"]),
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

    The insert is strict: a duplicate key, missing table, or zero-row insert
    raises so callers can avoid returning an unverifiable seal.

    Migration 119 added ``seal_id`` + ``corpus_snapshot_id`` columns. We
    INSERT them when present; on a pre-119 schema the second INSERT path
    falls back to the legacy column set so the row still lands.
    """
    retention_until = _retention_until_for_seal(seal)
    seal_id = seal.get("seal_id")
    corpus_snapshot_id = seal.get("corpus_snapshot_id")
    key_version = _seal_key_version(seal)
    source_urls_json = json.dumps(seal.get("source_urls", []), ensure_ascii=False)
    started_transaction = False
    insert_attempts: tuple[tuple[str, tuple[Any, ...]], ...] = (
        (
            "INSERT INTO audit_seals("
            "  call_id, api_key_hash, ts, endpoint, query_hash, response_hash,"
            "  source_urls_json, client_tag, hmac, retention_until,"
            "  seal_id, corpus_snapshot_id, key_version"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                seal["call_id"],
                api_key_hash,
                seal["ts"],
                seal["endpoint"],
                seal["query_hash"],
                seal["response_hash"],
                source_urls_json,
                seal.get("client_tag"),
                seal["hmac"],
                retention_until,
                seal_id,
                corpus_snapshot_id,
                key_version,
            ),
        ),
        (
            "INSERT INTO audit_seals("
            "  call_id, api_key_hash, ts, endpoint, query_hash, response_hash,"
            "  source_urls_json, client_tag, hmac, retention_until,"
            "  seal_id, corpus_snapshot_id"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                seal["call_id"],
                api_key_hash,
                seal["ts"],
                seal["endpoint"],
                seal["query_hash"],
                seal["response_hash"],
                source_urls_json,
                seal.get("client_tag"),
                seal["hmac"],
                retention_until,
                seal_id,
                corpus_snapshot_id,
            ),
        ),
        (
            "INSERT INTO audit_seals("
            "  call_id, api_key_hash, ts, endpoint, query_hash, response_hash,"
            "  source_urls_json, client_tag, hmac, retention_until,"
            "  key_version"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                seal["call_id"],
                api_key_hash,
                seal["ts"],
                seal["endpoint"],
                seal["query_hash"],
                seal["response_hash"],
                source_urls_json,
                seal.get("client_tag"),
                seal["hmac"],
                retention_until,
                key_version,
            ),
        ),
        (
            "INSERT INTO audit_seals("
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
                source_urls_json,
                seal.get("client_tag"),
                seal["hmac"],
                retention_until,
            ),
        ),
    )

    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            started_transaction = True
        _ensure_unique_seal_id(conn, str(seal_id) if seal_id else None)
        last_operational_error: sqlite3.OperationalError | None = None
        for sql, params in insert_attempts:
            try:
                _execute_seal_insert(conn, sql, params)
            except sqlite3.OperationalError as exc:
                last_operational_error = exc
                continue
            if started_transaction:
                conn.execute("COMMIT")
            return
        if last_operational_error is not None:
            raise last_operational_error
        raise sqlite3.OperationalError("audit_seals insert did not run")
    except Exception:
        if started_transaction:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
        raise


def attach_seal_to_body(
    body: dict[str, Any],
    *,
    endpoint: str,
    request_params: dict[str, Any] | None,
    api_key_hash: str | None,
    conn: sqlite3.Connection | None = None,
    client_tag: str | None = None,
) -> dict[str, Any]:
    """Build, attach, and persist an audit_seal for the given body.

    Mutates ``body`` in place (adding the ``audit_seal`` key) only after
    persistence is confirmed. If persistence fails, the response remains
    useful but carries ``_seal_unavailable`` instead of an unverifiable seal.

    No-op when ``api_key_hash`` is None (anon path — sealing requires a
    key for both customer-side ownership and statutory retention).

    Performance budget (§17 step 5): seal generation < 5ms per response.
    The hot path is hash + HMAC + uuid + a single sqlite INSERT — well
    inside the 5ms budget on the typical paid endpoint body size.
    """
    if not api_key_hash:
        return body
    seal = build_seal(
        endpoint=endpoint,
        request_params=request_params,
        response_body=body,
        client_tag=client_tag,
        api_key_hash=api_key_hash,
    )
    if conn is None:
        body["audit_seal"] = seal
        return body
    try:
        persist_seal(conn, seal=seal, api_key_hash=api_key_hash)
    except Exception as exc:
        body["_seal_unavailable"] = True
        _log_seal_persist_failure(
            conn,
            endpoint=endpoint,
            api_key_hash=api_key_hash,
            seal=seal,
            reason=f"{exc.__class__.__name__}: {exc}",
        )
        return body

    body["audit_seal"] = seal
    return body


def lookup_seal(
    conn: sqlite3.Connection,
    *,
    seal_id: str,
) -> dict[str, Any] | None:
    """Return the persisted seal row for the given ``seal_id`` or None.

    Used by the public verify endpoint at ``GET /v1/audit/seals/{seal_id}``.
    Tolerates pre-migration-119 schemas (no ``seal_id`` column) by falling
    back to the legacy ``call_id`` lookup — a customer who issued a seal
    on the legacy code path can still verify via the same URL by supplying
    their ``call_id`` value (the response shape carries both formats).
    """
    try:
        row = conn.execute(
            "SELECT call_id, ts, response_hash, hmac, seal_id, corpus_snapshot_id "
            "FROM audit_seals WHERE seal_id = ? LIMIT 1",
            (seal_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    if row is None:
        # Fallback: legacy call_id lookup (no seal_id column or no row).
        try:
            row = conn.execute(
                "SELECT call_id, ts, response_hash, hmac, NULL AS seal_id, "
                "NULL AS corpus_snapshot_id FROM audit_seals "
                "WHERE call_id = ? LIMIT 1",
                (seal_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None:
            return None
    keys = row.keys() if hasattr(row, "keys") else None
    if keys:
        return {k: row[k] for k in keys}
    # tuple fallback
    return {
        "call_id": row[0],
        "ts": row[1],
        "response_hash": row[2],
        "hmac": row[3],
        "seal_id": row[4] if len(row) > 4 else None,
        "corpus_snapshot_id": row[5] if len(row) > 5 else None,
    }


__all__ = [
    "attach_seal_to_body",
    "build_seal",
    "compute_hmac",
    "extract_source_urls",
    "get_corpus_snapshot_id",
    "lookup_seal",
    "persist_seal",
    "sign",
    "verify",
    "verify_hmac",
]
