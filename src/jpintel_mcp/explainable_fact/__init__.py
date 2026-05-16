"""Wave 51 dim O — Explainable / Verified knowledge graph metadata layer.

This package is the **reusable, router-agnostic** core for the dim O
"why can you claim that" layer described in
``feedback_explainable_fact_design``:

    * LLM hallucination rate of 25-40% is mainly driven by *unknown
      provenance* — agents can't decide whether to trust a fact.
    * Every jpcite fact must carry the 4-axis metadata envelope
      (source_doc + extracted_at + verified_by + confidence) so the
      consuming agent can answer "なぜそう言えるか" with zero LLM call.
    * Ed25519 signing closes the loop: a tampered fact fails verify
      cryptographically, no human review needed.

The existing REST surface (``src/jpintel_mcp/api/fact_verify.py``) already
implements the legacy single-fact verify endpoint. **This package adds
the atomic primitives** so the same model + signing logic runs across
REST, MCP tools, ETL composition, and offline operator scripts without
each call site re-implementing canonicalization / verification.

Public surface
--------------
    FactMetadata           — Pydantic model with the 4 mandatory axes
    VerifiedBy             — Literal type for the verified_by enum
    canonical_payload(...) -> bytes   (byte payload that gets signed)
    sign_fact(...)         -> bytes   (Ed25519 sign — caller owns the key)
    verify_fact(...)       -> bool    (Ed25519 verify against pubkey)
    load_public_key_from_env(env) -> Ed25519PublicKey | None

Non-goals
---------
* Does NOT generate, store, or load private keys. Caller-owned.
* Does NOT call any LLM API or external HTTP endpoint.
* Does NOT replace ``api/fact_verify``; it provides the primitives that
  router / MCP / ETL code can compose on top.
"""

from __future__ import annotations

from .metadata import FactMetadata, VerifiedBy
from .signing import (
    canonical_payload,
    load_public_key_from_env,
    sign_fact,
    verify_fact,
)

__all__ = [
    "FactMetadata",
    "VerifiedBy",
    "canonical_payload",
    "load_public_key_from_env",
    "sign_fact",
    "verify_fact",
]
