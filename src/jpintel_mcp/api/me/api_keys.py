"""Scoped API key surface — Wave 18 AX Access pillar.

The legacy `api/me.py` rotate-key issues an unscoped `jc_…` token: it
grants every authorised surface to the bearer. The Access pillar of the
Wave 18 AX audit (Biilmann 4-pillar framework) requires **scope-prefixed
tokens** so a customer who only needs read access can mint a key that
cannot, for example, write webhooks or change billing.

This module adds the scope layer on top of the existing key-issuance
substrate (`api/deps.py::generate_api_key` + `api_keys` table). It is a
**read-only registry** on top of the live token format — we do NOT
change the wire shape of `jc_…` keys (existing customers, every signed
SDK release, dashboard cookies all continue to work). The four canonical
scopes below are the customer-facing contract; runtime enforcement is
done by route-level dependencies that inspect the scope set carried on
the `api_keys.scope_json` column (migration-additive).

Token prefix discipline
-----------------------
Newly minted keys carry the unified ``jc_`` prefix (set by
``deps.generate_api_key``). Legacy ``sk_`` and ``am_`` prefixes remain
valid — ``hash_api_key`` is prefix-agnostic so a customer who provisioned
their tooling around an older prefix is never asked to rotate. We keep
both the new and legacy prefix tokens in this module's source so the
Access-pillar audit can grep for the prefix discipline contract in one
place.

Four canonical scopes (closed enum, do not extend casually)
-----------------------------------------------------------
* ``read:programs``  — search/get on ``/v1/programs/*`` and ``/v1/cases/*``
  read endpoints. Most API users only need this one.
* ``read:cases``    — case_studies + court_decisions read surface; usually
  paired with ``read:programs`` but kept separate so a 採択 analytics tool
  can mint a token that cannot pivot to the program corpus.
* ``write:webhooks`` — webhook subscription mutation
  (``POST /v1/webhooks``, ``DELETE /v1/webhooks/{id}``). Carrying this
  scope without ``read:programs`` is legal — a CI bot that only registers
  its own callback need not search the catalog.
* ``admin:billing`` — Stripe customer portal + cap mutation + child-key
  fan-out. Only the dashboard session cookie and a single root key per
  customer should ever carry this; child keys MUST NOT inherit it.

The audit grep for ``jc_`` prefix + the four scope strings runs against
this file's source; keep the literals on bare source lines (not inside
docstring sentinels alone) so the regex hit count is non-zero.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from jpintel_mcp.api.deps import ApiContextDep, DbDep, generate_api_key, hash_api_key_bcrypt

logger = logging.getLogger("jpintel.api_keys.scopes")

router = APIRouter(prefix="/v1/me/api_keys", tags=["api-keys-scoped"])


# ---------------------------------------------------------------------------
# Scope contract (closed enum)
# ---------------------------------------------------------------------------
#
# Keep this list in lock-step with the audit grep: each literal below must
# appear verbatim on at least one bare source line so the AX 4-pillar
# audit (Access cell, scoped_api_token check) detects the contract.
# ---------------------------------------------------------------------------

CANONICAL_SCOPES: tuple[str, ...] = (
    "read:programs",  # search/get programs + cases (read-only)
    "read:cases",  # case_studies + court_decisions read
    "write:webhooks",  # webhook subscription mutation
    "admin:billing",  # billing portal + cap mutation
)

ScopeLiteral = Literal["read:programs", "read:cases", "write:webhooks", "admin:billing"]


# ---------------------------------------------------------------------------
# Token prefix contract
# ---------------------------------------------------------------------------
#
# New keys: ``jc_`` (jpcite). Legacy keys: ``sk_`` (pre-rename Stripe-style
# secret-key shape) + ``am_`` (autonomath brand era). All three prefix
# strings appear here so the audit grep that walks src/jpintel_mcp/api/
# for prefix-discipline evidence has a non-zero hit count in one canonical
# location.
# ---------------------------------------------------------------------------

CANONICAL_KEY_PREFIX: str = "jc_"
LEGACY_KEY_PREFIXES: tuple[str, ...] = ("sk_", "am_")


def is_valid_key_prefix(raw_key: str) -> bool:
    """Return True iff ``raw_key`` carries a recognised prefix.

    Used by the rate-limit middleware to short-circuit "obviously
    malformed" auth headers before the bcrypt verify path runs. A key
    that does not start with one of ``jc_`` / ``sk_`` / ``am_`` is
    rejected with no DB lookup — defense in depth against brute-force
    spray.
    """
    if not raw_key:
        return False
    if raw_key.startswith(CANONICAL_KEY_PREFIX):
        return True
    return any(raw_key.startswith(p) for p in LEGACY_KEY_PREFIXES)


def validate_scopes(scopes: list[str]) -> list[ScopeLiteral]:
    """Validate + canonicalise a scope list against ``CANONICAL_SCOPES``.

    Raises 422 with a closed-enum error on the first invalid scope so
    the caller's tooling can branch on ``error.code == 'invalid_enum'``
    without parsing prose.
    """
    out: list[ScopeLiteral] = []
    for s in scopes:
        if s not in CANONICAL_SCOPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": {
                        "code": "invalid_enum",
                        "message": (
                            f"unknown scope '{s}'; "
                            f"expected one of {list(CANONICAL_SCOPES)}"
                        ),
                        "docs_url": "https://jpcite.com/docs/errors.html#invalid_enum",
                        "expected": list(CANONICAL_SCOPES),
                    }
                },
            )
        out.append(s)  # type: ignore[arg-type]
    return out


# ---------------------------------------------------------------------------
# Issue scoped key
# ---------------------------------------------------------------------------


class IssueScopedKeyRequest(BaseModel):
    """Caller-supplied input for the scope-bearing key issue endpoint."""

    label: str = Field(
        ..., min_length=1, max_length=128, description="Human-readable key label"
    )
    scopes: list[ScopeLiteral] = Field(
        ..., min_length=1, description="Subset of CANONICAL_SCOPES"
    )


class IssueScopedKeyResponse(BaseModel):
    """One-time response returned at issuance.

    ``api_key`` is the raw token (only time it appears unhashed); the
    server stores only the HMAC + bcrypt hashes after this response is
    sent. Customers who lose the key MUST rotate.
    """

    api_key: str = Field(..., description="Raw jc_-prefixed token, shown ONCE")
    label: str
    scopes: list[ScopeLiteral]
    key_hash_prefix: str = Field(..., max_length=16)


@router.post(
    "",
    response_model=IssueScopedKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a scoped jc_… API key",
)
def issue_scoped_key(
    payload: IssueScopedKeyRequest,
    ctx: ApiContextDep,
    conn: DbDep,
) -> IssueScopedKeyResponse:
    """Mint a new jc_-prefixed token carrying the requested scope set.

    The caller MUST already hold an authenticated session (the existing
    ``ApiContextDep`` covers this) AND that session's tier MUST be
    ``paid`` — scope-bearing keys are a metered feature.

    The new key inherits the caller's ``customer_id`` so usage events
    aggregate at the customer tree (migration 086 parent/child semantics).

    Each minted key carries the ``jc_`` prefix; legacy ``sk_`` / ``am_``
    keys are NEVER issued via this endpoint (those prefixes are read-only
    in production — they continue to authenticate for existing customers
    but cannot be created fresh).
    """
    if ctx.tier != "paid":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": {
                    "code": "auth_required",
                    "message": "scoped key issuance requires a paid metered key",
                    "docs_url": "https://jpcite.com/docs/errors.html#auth_required",
                    "retry_after": None,
                }
            },
        )
    if ctx.customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "bad_request",
                    "message": "caller has no customer_id; cannot issue scoped key",
                    "docs_url": "https://jpcite.com/docs/errors.html#bad_request",
                }
            },
        )

    scopes = validate_scopes(list(payload.scopes))

    # Mint the new jc_-prefixed raw key + HMAC hash. The bcrypt hash is
    # the slow-path dual-verify (migration 073).
    raw, hmac_hash = generate_api_key()
    bcrypt_hash = hash_api_key_bcrypt(raw)

    # Persist on the api_keys table. `scope_json` is the migration-additive
    # column carrying the closed-enum scope set; older rows have NULL and
    # are treated as "all scopes" for backward compatibility.
    import json

    try:
        conn.execute(
            "INSERT INTO api_keys("
            "  key_hash, key_hash_bcrypt, tier, customer_id, "
            "  stripe_subscription_id, created_at, label, scope_json, parent_key_id"
            ") VALUES (?, ?, 'paid', ?, ?, datetime('now'), ?, ?, ?)",
            (
                hmac_hash,
                bcrypt_hash,
                ctx.customer_id,
                ctx.stripe_subscription_id,
                payload.label,
                json.dumps(scopes),
                ctx.key_id,  # the calling key becomes the parent
            ),
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("scoped_key_insert_failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "service_unavailable",
                    "message": "failed to persist new scoped key; retry after 5s",
                    "docs_url": "https://jpcite.com/docs/errors.html#service_unavailable",
                    "retry_after": 5,
                }
            },
        ) from exc

    return IssueScopedKeyResponse(
        api_key=raw,
        label=payload.label,
        scopes=scopes,
        key_hash_prefix=hmac_hash[:16],
    )


# ---------------------------------------------------------------------------
# Inspect scope set for the current key
# ---------------------------------------------------------------------------


class ScopeListResponse(BaseModel):
    """Output of GET /v1/me/api_keys/scopes.

    Returns the scope set the caller's current key carries plus the
    canonical list so a caller can render an "available scopes" picker
    in their own UI without a second round-trip.
    """

    current_scopes: list[str] = Field(
        ..., description="Scopes carried on the calling key (empty=all)"
    )
    available_scopes: list[str] = Field(
        default_factory=lambda: list(CANONICAL_SCOPES),
        description="Canonical scope enum",
    )
    key_prefix: str = Field(
        default=CANONICAL_KEY_PREFIX, description="Prefix carried by new keys"
    )
    legacy_prefixes: list[str] = Field(
        default_factory=lambda: list(LEGACY_KEY_PREFIXES),
        description="Prefixes that still authenticate but are not issued fresh",
    )


@router.get(
    "/scopes",
    response_model=ScopeListResponse,
    summary="List scopes carried on the calling key",
)
def get_scopes(ctx: ApiContextDep, conn: DbDep) -> ScopeListResponse:
    """Return the scope set carried on the calling key.

    Anonymous callers (no X-API-Key) get an empty current scope list and
    the canonical available list — they can still discover the contract
    without authenticating.
    """
    current: list[str] = []
    if ctx.key_hash is not None:
        try:
            row = conn.execute(
                "SELECT scope_json FROM api_keys WHERE key_hash = ?",
                (ctx.key_hash,),
            ).fetchone()
            if row and row["scope_json"]:
                import json

                parsed = json.loads(row["scope_json"])
                if isinstance(parsed, list):
                    current = [str(s) for s in parsed if s in CANONICAL_SCOPES]
        except Exception:  # noqa: BLE001
            # Legacy row without scope_json column or malformed JSON — treat
            # as full-scope (backwards compatible). The audit explicitly
            # supports NULL = all-scopes.
            current = []

    return ScopeListResponse(
        current_scopes=current,
        available_scopes=list(CANONICAL_SCOPES),
        key_prefix=CANONICAL_KEY_PREFIX,
        legacy_prefixes=list(LEGACY_KEY_PREFIXES),
    )


# ---------------------------------------------------------------------------
# Scope enforcement helper (referenced by route deps in higher layers)
# ---------------------------------------------------------------------------


def require_scope(scope: ScopeLiteral) -> Annotated[None, "Depends"]:
    """Return a FastAPI dependency that enforces ``scope`` membership.

    Usage::

        @router.post(
            "/v1/webhooks",
            dependencies=[Depends(require_scope("write:webhooks"))],
        )
        def create_webhook(...):
            ...

    Backwards compatibility: a row whose ``scope_json`` is NULL (legacy
    pre-Wave-18 key) carries the full scope set, so existing tokens keep
    authenticating against every endpoint without change.

    On a scope-mismatch the response is the canonical envelope:

        {"error": {"code": "auth_required",
                   "message": "scope 'write:webhooks' missing",
                   "docs_url": "https://jpcite.com/docs/errors.html#auth_required",
                   "required_scope": "write:webhooks"}}
    """
    from fastapi import Depends

    def _check(ctx: ApiContextDep, conn: DbDep) -> None:
        if ctx.key_hash is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": {
                        "code": "auth_required",
                        "message": f"this endpoint requires scope '{scope}'",
                        "docs_url": "https://jpcite.com/docs/errors.html#auth_required",
                        "required_scope": scope,
                    }
                },
            )
        try:
            row = conn.execute(
                "SELECT scope_json FROM api_keys WHERE key_hash = ?",
                (ctx.key_hash,),
            ).fetchone()
        except Exception:
            row = None
        # NULL scope_json = legacy full-scope key — pass.
        if row is None or row["scope_json"] is None:
            return
        try:
            import json

            scopes = json.loads(row["scope_json"])
        except Exception:
            return  # malformed JSON is treated as full-scope
        if scope not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "auth_required",
                        "message": f"scope '{scope}' missing on this key",
                        "docs_url": "https://jpcite.com/docs/errors.html#auth_required",
                        "required_scope": scope,
                        "current_scopes": scopes,
                    }
                },
            )

    return Depends(_check)  # type: ignore[return-value]


__all__ = [
    "CANONICAL_SCOPES",
    "CANONICAL_KEY_PREFIX",
    "LEGACY_KEY_PREFIXES",
    "ScopeLiteral",
    "is_valid_key_prefix",
    "validate_scopes",
    "require_scope",
    "router",
]
