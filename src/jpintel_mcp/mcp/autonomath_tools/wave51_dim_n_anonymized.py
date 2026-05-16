"""Wave 51 dim N — Anonymized aggregate query MCP wrapper.

Single MCP tool that exposes the k-anonymity + PII-redact + audit-log
primitives in ``jpintel_mcp.anonymized_query`` so AI agents can ask
"how did similar entities fare?" without ever seeing 法人番号 / 氏名 /
住所. Pure rule-based — no LLM, no aggregator.

Hard constraints (CLAUDE.md):

* NO LLM call. Pure SQLite-or-callable + Python.
* 1 ¥3/billable unit per tool call.
* k=5 hard floor enforced via ``K_ANONYMITY_MIN`` module constant.
* PII redact policy version v1.1.0 (structured strip + 6-pattern text).
* Append-only JSONL audit log row per call.
* §52 / §47条の2 / §72 / §1 non-substitution disclaimer envelope.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.agent_runtime.contracts import Evidence, OutcomeContract
from jpintel_mcp.anonymized_query import (
    K_ANONYMITY_MIN,
    REDACT_POLICY_VERSION,
    check_k_anonymity,
    redact_pii_fields,
    redact_text,
    write_audit_entry,
)
from jpintel_mcp.anonymized_query.audit_log import cohort_hash
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.wave51_dim_n_anonymized")

_ENABLED = os.environ.get("AUTONOMATH_WAVE51_DIM_N_ENABLED", "1") in (
    "1",
    "true",
    "True",
    "yes",
    "on",
)

_DISCLAIMER = (
    "本 response は k-anonymity floor=5 + PII redact policy "
    f"{REDACT_POLICY_VERSION} を強制した anonymized cohort aggregate です。"
    "個別法人 / 個人の identifying field は構造的に剥がしてあり、reidentification "
    "は技術的に不能。税理士法 §52 / 公認会計士法 §47条の2 / 弁護士法 §72 / "
    "行政書士法 §1 の代替ではありません。"
)


def _today_iso_utc() -> str:
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _audit_path() -> Path:
    """Resolve the audit log destination, falling back to a temp file."""
    override = os.environ.get("ANONYMIZED_QUERY_AUDIT_LOG_PATH")
    if override:
        return Path(override)
    # Default: repo logs/ dir, fall back to tmp if unwriteable.
    default = Path(__file__).resolve().parents[4] / "logs" / "anonymized_query_audit.jsonl"
    try:
        default.parent.mkdir(parents=True, exist_ok=True)
        return default
    except OSError:  # pragma: no cover — read-only volume fallback
        return Path(tempfile.gettempdir()) / "anonymized_query_audit.jsonl"


def _scrub_sample(sample: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Run structured + text redact on a single cohort sample dict."""
    structured = redact_pii_fields(sample)
    text_hits: list[str] = []
    out: dict[str, Any] = {}
    for k, v in structured.items():
        if isinstance(v, str):
            cleaned, hits = redact_text(v)
            text_hits.extend(hits)
            out[k] = cleaned
        else:
            out[k] = v
    return out, sorted(set(text_hits))


def _anonymized_aggregate_query_impl(
    industry: str | None,
    region: str | None,
    size: str | None,
    cohort_size: int,
    aggregates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """k-anonymity gate + audit row for one anonymized cohort query.

    Caller passes the cohort filter triple (industry / region / size) and
    the pre-computed ``cohort_size`` from their own SQL. We gate on
    K_ANONYMITY_MIN, redact the optional aggregates dict, write one audit
    row, and return the canonical envelope.
    """
    # Type / value validation up front so audit log only captures rows we
    # actually want to record.
    if not isinstance(cohort_size, int) or isinstance(cohort_size, bool):
        return make_error(
            code="invalid_input",
            message="cohort_size must be an int.",
            field="cohort_size",
        )
    if cohort_size < 0:
        return make_error(
            code="out_of_range",
            message="cohort_size must be >= 0.",
            field="cohort_size",
        )

    # k-anonymity check.
    k_result = check_k_anonymity(cohort_size)
    cohort_hex = cohort_hash(industry, region, size)

    redacted_aggregates: dict[str, Any] = {}
    pii_hits_total: set[str] = set()
    if k_result.ok and aggregates:
        scrubbed, hits = _scrub_sample(aggregates)
        redacted_aggregates = scrubbed
        pii_hits_total.update(hits)

    # Map k-anonymity result.reason -> audit-log enum (avoid 'ok'+reason
    # mismatch validation).
    audit_reason: str
    if k_result.ok:
        audit_reason = "ok"
    elif k_result.reason == "negative_cohort":
        audit_reason = "negative_cohort"
    else:
        audit_reason = "cohort_too_small"

    audit_path = _audit_path()
    try:
        write_audit_entry(
            cohort_hash_hex=cohort_hex,
            redact_policy_version=REDACT_POLICY_VERSION,
            cohort_size=cohort_size,
            reason=audit_reason,
            pii_hits=sorted(pii_hits_total),
            path=audit_path,
        )
    except OSError as exc:  # pragma: no cover — disk full / read-only
        logger.warning("anonymized_aggregate_query: audit write failed: %s", exc)

    support_state = "supported" if k_result.ok else "absent"
    evidence_type = "absence_observation" if support_state == "absent" else "structured_record"
    evidence = Evidence(
        evidence_id="dim_n_anonymized_aggregate_evidence",
        claim_ref_ids=("dim_n_anonymized_aggregate_claim",),
        receipt_ids=(f"dim_n_aggregate_{cohort_hex[:16]}",),
        evidence_type=evidence_type,
        support_state=support_state,
        temporal_envelope=f"{_dt.date.today().isoformat()}/observed",
        observed_at=_today_iso_utc(),
    )
    outcome = OutcomeContract(
        outcome_contract_id="dim_n_anonymized_aggregate_query",
        display_name="Wave 51 dim N — anonymized aggregate query (k=5 + PII redact)",
        packet_ids=("packet_dim_n_anonymized_aggregate_query",),
        billable=True,
    )

    primary: dict[str, Any] = {
        "cohort_hash": cohort_hex,
        "cohort_size": cohort_size,
        "k_anonymity_floor": K_ANONYMITY_MIN,
        "k_anonymity_ok": k_result.ok,
        "k_anonymity_reason": k_result.reason,
        "redact_policy_version": REDACT_POLICY_VERSION,
        "pii_hits": sorted(pii_hits_total),
        "aggregates": redacted_aggregates if k_result.ok else {},
        "audit_log_path": str(audit_path),
    }

    return {
        "tool_name": "anonymized_aggregate_query",
        "schema_version": "wave51.dim_n.v1",
        "primary_result": primary,
        "evidence": evidence.model_dump(mode="json"),
        "outcome_contract": outcome.model_dump(mode="json"),
        "citations": [],
        "results": [],
        "total": 1 if k_result.ok else 0,
        "limit": 1,
        "offset": 0,
        "_billing_unit": 1,
        "_disclaimer": _DISCLAIMER,
    }


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def anonymized_aggregate_query(
        industry: Annotated[
            str | None,
            Field(
                default=None,
                max_length=64,
                description="Industry cohort filter (JSIC major / display name).",
            ),
        ] = None,
        region: Annotated[
            str | None,
            Field(
                default=None,
                max_length=32,
                description="Region cohort filter (都道府県 / region code).",
            ),
        ] = None,
        size: Annotated[
            str | None,
            Field(
                default=None,
                max_length=32,
                description="Size cohort filter (e.g. 'sme', '中小企業', 'large').",
            ),
        ] = None,
        cohort_size: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "Pre-computed number of underlying entities in the cohort. "
                    "Must be >= K_ANONYMITY_MIN (5) to surface aggregates."
                ),
            ),
        ] = 0,
        aggregates: Annotated[
            dict[str, Any] | None,
            Field(
                default=None,
                description=(
                    "Optional pre-computed aggregate dict (avg, count, etc.). "
                    "PII fields are stripped before return."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[ANONYMIZED, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 dim N k-anonymity + PII-redact gate. Returns aggregates only when cohort_size >= K_ANONYMITY_MIN (5); otherwise returns absent envelope. PII fields in optional aggregates dict are stripped via structured whitelist + 6-pattern text redact (policy version dim-n-v1.1.0). Writes one append-only JSONL audit row per call. NO LLM, single ¥3 unit. 1M-entity statistical layer moat."""
        return _anonymized_aggregate_query_impl(
            industry=industry,
            region=region,
            size=size,
            cohort_size=cohort_size,
            aggregates=aggregates,
        )


__all__ = ["_anonymized_aggregate_query_impl"]
