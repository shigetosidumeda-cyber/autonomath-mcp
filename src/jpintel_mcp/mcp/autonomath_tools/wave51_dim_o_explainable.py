"""Wave 51 dim O — Explainable / verified knowledge graph MCP wrappers.

Two MCP tools that expose the Ed25519-based sign + verify primitives in
``jpintel_mcp.explainable_fact`` (Wave 51 dim O) over the same
canonicalization the existing ``api/fact_verify`` endpoint uses. The
agent can: (1) emit a deterministic ``sign_fact`` request that returns
the canonical payload + (when an operator-supplied private key hex is
provided via env) the 64-byte Ed25519 signature; (2) call ``verify_fact``
with a hex signature + the 4-axis metadata and get a boolean verify
verdict — no LLM hop, no HTTP, fully deterministic.

Hard constraints (CLAUDE.md):

* NO LLM call. Pure cryptography + Python.
* 1 ¥3/billable unit per tool call.
* Private keys are NEVER persisted by these wrappers. The sign path
  reads a hex-encoded private key from
  ``AUTONOMATH_FACT_SIGN_PRIVATE_KEY`` env only when the operator opts
  in; absent that env, ``sign_fact`` returns the canonical payload +
  ``signed=False`` + an explanatory ``hint`` for downstream agents.
* §52 / §47条の2 / §72 / §1 non-substitution disclaimer envelope.
* MCP tool registration is import-time side-effect; safe with FastMCP
  deferred tool list snapshot.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
from typing import Annotated, Any

from pydantic import Field, ValidationError

from jpintel_mcp.agent_runtime.contracts import Evidence, OutcomeContract
from jpintel_mcp.config import settings
from jpintel_mcp.explainable_fact import (
    FactMetadata,
    canonical_payload,
    load_public_key_from_env,
)
from jpintel_mcp.explainable_fact import verify_fact as _ef_verify_fact
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.wave51_dim_o_explainable")

_ENABLED = os.environ.get("AUTONOMATH_WAVE51_DIM_O_ENABLED", "1") in (
    "1",
    "true",
    "True",
    "yes",
    "on",
)

_PRIVATE_KEY_ENV = "AUTONOMATH_FACT_SIGN_PRIVATE_KEY"

_DISCLAIMER = (
    "本 response は Wave 51 dim O explainable fact 層の Ed25519 sign / verify "
    "プリミティブの構造的アクセサです。署名鍵の保管・運用は事業者責任、署名検証 "
    "結果は事実の真正性の機械的判定であって法的助言ではありません。"
    "税理士法 §52 / 公認会計士法 §47条の2 / 弁護士法 §72 / 行政書士法 §1 の代替ではありません。"
)


def _today_iso_utc() -> str:
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_metadata(
    source_doc: str,
    extracted_at: str,
    verified_by: str,
    confidence: float,
) -> tuple[FactMetadata | None, dict[str, Any] | None]:
    """Build a FactMetadata or return a make_error envelope on validation fail."""
    try:
        meta = FactMetadata(
            source_doc=source_doc,
            extracted_at=extracted_at,
            verified_by=verified_by,  # noqa  # runtime Pydantic validates the Literal
            confidence=confidence,
        )
    except ValidationError as exc:
        return None, make_error(
            code="invalid_input",
            message=f"fact metadata failed validation: {exc.error_count()} error(s).",
            hint=(
                "source_doc must be non-empty; verified_by ∈ "
                "{manual, cron_etl_v3, ed25519_sig}; confidence ∈ [0.0, 1.0]."
            ),
        )
    return meta, None


def _wrap_envelope(
    *,
    tool_name: str,
    primary_result: dict[str, Any],
    support_state: str,
    receipt_id: str,
    display_name: str,
) -> dict[str, Any]:
    evidence_type = "absence_observation" if support_state == "absent" else "structured_record"
    evidence = Evidence(
        evidence_id=f"dim_o_{tool_name}_evidence",
        claim_ref_ids=(f"dim_o_{tool_name}_claim",),
        receipt_ids=(receipt_id,),
        evidence_type=evidence_type,
        support_state=support_state,
        temporal_envelope=f"{_dt.date.today().isoformat()}/observed",
        observed_at=_today_iso_utc(),
    )
    outcome = OutcomeContract(
        outcome_contract_id=f"dim_o_{tool_name}",
        display_name=display_name,
        packet_ids=(f"packet_dim_o_{tool_name}",),
        billable=True,
    )
    return {
        "tool_name": tool_name,
        "schema_version": "wave51.dim_o.v1",
        "primary_result": primary_result,
        "evidence": evidence.model_dump(mode="json"),
        "outcome_contract": outcome.model_dump(mode="json"),
        "citations": [],
        "results": [],
        "total": 1 if support_state != "absent" else 0,
        "limit": 1,
        "offset": 0,
        "_billing_unit": 1,
        "_disclaimer": _DISCLAIMER,
    }


def _sign_fact_impl(
    fact_id: str,
    source_doc: str,
    extracted_at: str,
    verified_by: str,
    confidence: float,
) -> dict[str, Any]:
    """Build canonical payload and (optionally) Ed25519-sign it.

    Returns the canonical payload bytes (hex) so downstream agents can
    verify deterministically. If the operator-supplied private key env
    is set, also emits the 64-byte signature; otherwise returns
    ``signed=False`` with a hint.
    """
    if not fact_id or not fact_id.strip():
        return make_error(
            code="missing_required_arg",
            message="fact_id is required.",
            field="fact_id",
        )

    meta, err = _build_metadata(source_doc, extracted_at, verified_by, confidence)
    if err is not None:
        return err
    assert meta is not None  # for type-checker

    try:
        payload_bytes = canonical_payload(fact_id, meta)
    except ValueError as exc:
        return make_error(
            code="invalid_argument",
            message=str(exc),
            field="fact_id",
        )

    payload_hex = payload_bytes.hex()

    signed = False
    signature_hex: str | None = None
    hint: str | None = None
    privkey_hex = os.environ.get(_PRIVATE_KEY_ENV)
    if privkey_hex:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )

            raw = bytes.fromhex(privkey_hex.strip())
            if len(raw) != 32:
                hint = "private key length != 32 bytes; signing skipped."
            else:
                priv = Ed25519PrivateKey.from_private_bytes(raw)
                signature_hex = priv.sign(payload_bytes).hex()
                signed = True
        except Exception as exc:  # pragma: no cover — crypto guard
            hint = f"signing failed: {type(exc).__name__}"
    else:
        hint = (
            "AUTONOMATH_FACT_SIGN_PRIVATE_KEY env not set; returning canonical "
            "payload only. Operator must supply a 32-byte hex private key to "
            "produce signatures."
        )

    primary: dict[str, Any] = {
        "fact_id": fact_id,
        "canonical_payload_hex": payload_hex,
        "canonical_payload_len": len(payload_bytes),
        "metadata": meta.model_dump(mode="json"),
        "signed": signed,
        "signature_hex": signature_hex,
        "hint": hint,
    }
    return _wrap_envelope(
        tool_name="sign_fact",
        primary_result=primary,
        support_state="supported",
        receipt_id=f"dim_o_sign_{fact_id}",
        display_name="Wave 51 dim O — sign_fact (Ed25519 canonical payload + optional signature)",
    )


def _verify_fact_impl(
    fact_id: str,
    source_doc: str,
    extracted_at: str,
    verified_by: str,
    confidence: float,
    signature_hex: str,
) -> dict[str, Any]:
    """Verify a hex-encoded Ed25519 signature against fact + metadata."""
    if not fact_id or not fact_id.strip():
        return make_error(
            code="missing_required_arg",
            message="fact_id is required.",
            field="fact_id",
        )
    if not signature_hex or not signature_hex.strip():
        return make_error(
            code="missing_required_arg",
            message="signature_hex is required.",
            field="signature_hex",
        )

    try:
        sig_bytes = bytes.fromhex(signature_hex.strip())
    except ValueError:
        return make_error(
            code="invalid_argument",
            message="signature_hex must be a valid hex string.",
            field="signature_hex",
        )
    if len(sig_bytes) != 64:
        return make_error(
            code="invalid_argument",
            message=f"Ed25519 signature must be exactly 64 bytes, got {len(sig_bytes)}.",
            field="signature_hex",
        )

    meta, err = _build_metadata(source_doc, extracted_at, verified_by, confidence)
    if err is not None:
        return err
    assert meta is not None

    pubkey = load_public_key_from_env()
    if pubkey is None:
        return make_error(
            code="subsystem_unavailable",
            message="public key not configured.",
            hint=(
                "Operator must set AUTONOMATH_FACT_SIGN_PUBLIC_KEY to a 32-byte "
                "hex Ed25519 public key. Verification skipped."
            ),
        )

    try:
        ok = _ef_verify_fact(fact_id, meta, sig_bytes, pubkey)
    except ValueError as exc:
        return make_error(
            code="invalid_argument",
            message=str(exc),
            field="signature_hex",
        )

    support_state = "supported" if ok else "contested"
    primary: dict[str, Any] = {
        "fact_id": fact_id,
        "metadata": meta.model_dump(mode="json"),
        "signature_valid": ok,
    }
    return _wrap_envelope(
        tool_name="verify_fact",
        primary_result=primary,
        support_state=support_state,
        receipt_id=f"dim_o_verify_{fact_id}",
        display_name="Wave 51 dim O — verify_fact (Ed25519 signature verify)",
    )


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def sign_fact(
        fact_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=128,
                description="Stable fact identifier (matches am_entity_fact / fact_verify keys).",
            ),
        ],
        source_doc: Annotated[
            str,
            Field(
                min_length=1,
                max_length=512,
                description="Primary-source citation identifier (法令番号 / 公報号 / first-party URL).",
            ),
        ],
        extracted_at: Annotated[
            str,
            Field(
                min_length=1,
                max_length=40,
                description="ISO 8601 timestamp of ETL extraction.",
            ),
        ],
        verified_by: Annotated[
            str,
            Field(
                description="One of {manual, cron_etl_v3, ed25519_sig}.",
            ),
        ],
        confidence: Annotated[
            float,
            Field(
                ge=0.0,
                le=1.0,
                description="Confidence score in [0.0, 1.0].",
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 dim O sign_fact. Builds the canonical UTF-8 payload bytes for (fact_id, FactMetadata 4-axis). Returns canonical_payload_hex deterministically (single source of truth shared with api/fact_verify). When AUTONOMATH_FACT_SIGN_PRIVATE_KEY env is set (32-byte hex), emits Ed25519 64-byte signature_hex; otherwise signed=False + hint. NO LLM, no HTTP, single ¥3 unit. Private keys NEVER persisted by this wrapper."""
        return _sign_fact_impl(
            fact_id=fact_id,
            source_doc=source_doc,
            extracted_at=extracted_at,
            verified_by=verified_by,
            confidence=confidence,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def verify_fact(
        fact_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=128,
                description="Stable fact identifier.",
            ),
        ],
        source_doc: Annotated[
            str,
            Field(
                min_length=1,
                max_length=512,
                description="Primary-source citation identifier.",
            ),
        ],
        extracted_at: Annotated[
            str,
            Field(
                min_length=1,
                max_length=40,
                description="ISO 8601 timestamp of ETL extraction.",
            ),
        ],
        verified_by: Annotated[
            str,
            Field(
                description="One of {manual, cron_etl_v3, ed25519_sig}.",
            ),
        ],
        confidence: Annotated[
            float,
            Field(
                ge=0.0,
                le=1.0,
                description="Confidence score in [0.0, 1.0].",
            ),
        ],
        signature_hex: Annotated[
            str,
            Field(
                min_length=128,
                max_length=128,
                description="Hex-encoded 64-byte Ed25519 signature (128 hex chars).",
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 dim O verify_fact. Resolves the operator public key from AUTONOMATH_FACT_SIGN_PUBLIC_KEY env (32-byte hex), then verifies the 64-byte Ed25519 signature over canonical_payload(fact_id, FactMetadata). signature_valid=True ⇒ fact + metadata unmodified since signing. NO LLM, no HTTP, single ¥3 unit."""
        return _verify_fact_impl(
            fact_id=fact_id,
            source_doc=source_doc,
            extracted_at=extracted_at,
            verified_by=verified_by,
            confidence=confidence,
            signature_hex=signature_hex,
        )


__all__ = ["_sign_fact_impl", "_verify_fact_impl"]
