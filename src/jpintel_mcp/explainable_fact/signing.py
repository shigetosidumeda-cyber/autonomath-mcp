"""Ed25519 sign + verify helpers for explainable facts (dim O).

The signing surface lives in this **router-agnostic** module so REST,
MCP, ETL, and offline operator scripts share one canonicalization and
one verify path. The wire format mirrors the existing
``api/fact_verify.py`` convention (64-byte raw Ed25519 signature over a
JSON canonical payload), so an Ed25519 signature emitted here can be
verified by that endpoint and vice versa.

Security
--------
* This module **never** generates or stores private keys. Test fixtures
  generate ephemeral private keys in-memory and discard them.
* The public key is resolved either:
    1. Caller-supplied (preferred, e.g. operator passes
       ``AUTONOMATH_FACT_SIGN_PUBLIC_KEY`` env)
    2. From the env var directly via :func:`load_public_key_from_env`
* No external HTTP / LLM API is invoked.

Canonical payload
-----------------
The signed payload is the UTF-8 encoding of ``json.dumps`` over a dict
containing the fact identifier plus the 4 metadata axes, with:

    * ``sort_keys=True``                (key ordering stable)
    * ``separators=(",", ":")``         (no whitespace)
    * ``ensure_ascii=False``            (non-ASCII source_doc preserved)

The same canonicalization is used by ``api/fact_verify._build_payload``
so dim O signatures interoperate with the Wave 43 fact_verify pipeline.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only imports so the module is importable even when
    # `cryptography` is absent in a stripped-down environment. Runtime
    # behaviour raises ImportError loud-and-clear at the call site.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    from .metadata import FactMetadata


_PUBLIC_KEY_ENV = "AUTONOMATH_FACT_SIGN_PUBLIC_KEY"


def canonical_payload(fact_id: str, metadata: FactMetadata) -> bytes:
    """Build the canonical UTF-8 byte payload that gets signed/verified.

    The order is fixed (sort_keys=True) so the same fact + metadata
    always produces the same payload bytes regardless of insertion order
    in the caller. Any drift between sign-time and verify-time payload
    construction would silently invalidate every signature, so this
    function is the single source of truth for both sides.
    """
    if not fact_id:
        raise ValueError("fact_id must be a non-empty string")
    payload = {
        "fact_id": fact_id,
        "source_doc": metadata.source_doc,
        "extracted_at": metadata.extracted_at,
        "verified_by": metadata.verified_by,
        "confidence": metadata.confidence,
    }
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_fact(
    fact_id: str,
    metadata: FactMetadata,
    private_key: Ed25519PrivateKey,
) -> bytes:
    """Sign a fact + metadata pair with an Ed25519 private key.

    The private key is passed in by the caller — this module **never**
    stores, loads, or persists private keys. Returns the 64-byte raw
    Ed25519 signature suitable for storage in
    ``am_fact_signature.ed25519_sig`` BLOB(64).

    The caller is responsible for the private-key lifecycle (HSM /
    KMS / offline air-gapped signer) per the standard operator policy
    in `docs/_internal/`.
    """
    payload = canonical_payload(fact_id, metadata)
    return private_key.sign(payload)


def verify_fact(
    fact_id: str,
    metadata: FactMetadata,
    signature: bytes,
    public_key: Ed25519PublicKey,
) -> bool:
    """Verify an Ed25519 signature over a fact + metadata pair.

    Returns ``True`` iff the signature is valid for the canonical
    payload. Any tampering of either the fact_id or the metadata
    (including a single bit flip in confidence) causes ``False``.

    Raises ``ValueError`` for an obviously malformed signature length
    (anything other than 64 bytes), since the wire format is the raw
    Ed25519 64-byte signature. The :func:`api.fact_verify._verify_signature`
    legacy helper accepts framed 80-byte signatures for back-compat;
    dim O is greenfield so we keep the strict 64-byte requirement here.
    """
    # Local import so the module is importable in an environment that
    # ships without `cryptography` — only call sites pay the import
    # cost, and the error message is clear.
    from cryptography.exceptions import InvalidSignature

    if len(signature) != 64:
        raise ValueError(
            f"Ed25519 signature must be exactly 64 bytes, got {len(signature)}"
        )

    payload = canonical_payload(fact_id, metadata)
    try:
        public_key.verify(signature, payload)
        return True
    except InvalidSignature:
        return False


def load_public_key_from_env(
    env_var: str = _PUBLIC_KEY_ENV,
) -> Ed25519PublicKey | None:
    """Resolve the operator public key from an env var (hex-encoded).

    Mirrors ``api/fact_verify._ed25519_public_key_bytes`` so the same
    deployment env var unlocks both the REST endpoint and this
    module's verify helpers. Returns ``None`` when the env var is
    unset or non-hex; the caller is expected to surface a clear
    "key_unconfigured" error envelope in that case rather than
    silently accept unsigned facts.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )

    raw = os.environ.get(env_var)
    if not raw:
        return None
    raw = raw.strip()
    try:
        pubkey_bytes = bytes.fromhex(raw)
    except ValueError:
        return None
    if len(pubkey_bytes) != 32:
        return None
    try:
        return Ed25519PublicKey.from_public_bytes(pubkey_bytes)
    except Exception:  # pragma: no cover — cryptography internal guard
        return None


__all__ = [
    "canonical_payload",
    "load_public_key_from_env",
    "sign_fact",
    "verify_fact",
]
