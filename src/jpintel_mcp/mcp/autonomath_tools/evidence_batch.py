"""get_evidence_packet_batch — Bulk Evidence Packet composer MCP tool.

Mirrors the REST surface at ``POST /v1/evidence/packets/batch`` so MCP
clients can pull the same envelope shape (results[] + total / successful
/ failed / errors[] + _billing_unit / _next_calls / _disclaimer) without
round-tripping through HTTP. SAME composer as the single-record tool —
``EvidencePacketComposer.compose_for_program`` /
``EvidencePacketComposer.compose_for_houjin`` — never a parallel
implementation.

Pure SQLite + Python. NO LLM call.

Billing
-------

1 ¥3 unit per **successful** lookup (mirrors REST). A 100-lookup batch
that returns 99 packets + 1 not_found is billed ¥3 × 99 = ¥297 — failures
are NOT counted toward ``_billing_unit``.

The 121st tool in the Wave 24 list (added 2026-05-05).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.autonomath_tools.error_envelope import make_error
from jpintel_mcp.mcp.autonomath_tools.evidence_packet_tools import _get_composer
from jpintel_mcp.mcp.autonomath_tools.snapshot_helper import (
    attach_corpus_snapshot,
)
from jpintel_mcp.mcp.server import _READ_ONLY, mcp
from jpintel_mcp.services.evidence_packet import _DISCLAIMER

logger = logging.getLogger("jpintel.mcp.am.evidence_batch")

#: Hard cap on lookups per batch call. Mirrors
#: ``api.evidence_batch.MAX_BATCH_LOOKUPS`` so REST + MCP agree.
MAX_BATCH_LOOKUPS: int = 100

#: Env-gate. Default ON; flip "0" to disable without redeploy. Pairs with
#: the global AUTONOMATH_ENABLED gate at the package boundary.
_ENABLED = get_flag("JPCITE_EVIDENCE_BATCH_ENABLED", "AUTONOMATH_EVIDENCE_BATCH_ENABLED", "1") == "1"


def _impl_get_evidence_packet_batch(
    lookups: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Pure-Python core. Split out so tests bypass the @mcp.tool wrapper."""
    if not isinstance(lookups, list) or not lookups:
        return make_error(
            code="missing_required_arg",
            message="lookups must be a non-empty list of {kind, id} entries.",
            field="lookups",
        )
    if len(lookups) > MAX_BATCH_LOOKUPS:
        return make_error(
            code="out_of_range",
            message=(
                f"lookups must contain at most {MAX_BATCH_LOOKUPS} entries; got {len(lookups)}."
            ),
            field="lookups",
        )

    # Validate each lookup. Stop early on the first malformed entry —
    # the caller batched them; we reject the whole batch rather than
    # silently composing the valid subset (matches REST 422 posture).
    normalised: list[tuple[str, str]] = []
    for idx, raw in enumerate(lookups):
        if not isinstance(raw, dict):
            return make_error(
                code="invalid_input",
                message=f"lookups[{idx}] must be an object with kind+id keys.",
                field="lookups",
            )
        kind = (raw.get("kind") or "").strip().lower()
        sid = (raw.get("id") or "").strip()
        if not sid:
            return make_error(
                code="missing_required_arg",
                message=f"lookups[{idx}].id is required.",
                field="lookups",
            )
        if kind not in ("program", "houjin"):
            return make_error(
                code="invalid_enum",
                message=(
                    f"lookups[{idx}].kind must be 'program' or 'houjin'. "
                    "For multi-record query packets use the REST POST "
                    "/v1/evidence/packets/query endpoint."
                ),
                field="lookups",
            )
        normalised.append((kind, sid))

    composer = _get_composer()
    if composer is None:
        return make_error(
            code="db_unavailable",
            message=(
                "evidence_packet composer のデータソースが見つかりません。"
                "autonomath.db / data/jpintel.db のいずれかが欠落しています。"
            ),
            hint="AUTONOMATH_DB_PATH / JPINTEL_DB_PATH 環境変数を確認してください。",
        )

    # Lazy import to avoid a hard dependency cycle on api.evidence at
    # module load (api.evidence pulls in FastAPI which is heavy).
    from jpintel_mcp.api.evidence import _gate_evidence_envelope

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    corpus_snapshot_id: str | None = None
    successful = 0

    for idx, (kind, sid) in enumerate(normalised):
        try:
            if kind == "program":
                envelope = composer.compose_for_program(sid)
            else:
                envelope = composer.compose_for_houjin(sid)
        except Exception as exc:  # noqa: BLE001 — keep batch alive on per-row failures
            logger.warning(
                "evidence_batch composer raised idx=%s kind=%s id=%s err=%s",
                idx,
                kind,
                sid,
                exc,
            )
            errors.append(
                {
                    "index": idx,
                    "lookup": {"kind": kind, "id": sid},
                    "error": "composer_failure",
                }
            )
            continue
        if envelope is None:
            errors.append(
                {
                    "index": idx,
                    "lookup": {"kind": kind, "id": sid},
                    "error": "not_found",
                }
            )
            continue
        gated, _gate_summary = _gate_evidence_envelope(envelope)
        if corpus_snapshot_id is None:
            sid_val = gated.get("corpus_snapshot_id")
            if isinstance(sid_val, str) and sid_val:
                corpus_snapshot_id = sid_val
        results.append(gated)
        successful += 1

    # Build _next_calls — same shape as REST: surface a verify-not-found
    # hint per failed lookup (cap 5) + a free-text exploration hint when
    # any program lookup was supplied.
    next_calls: list[dict[str, Any]] = []
    failed_pairs = {(e["index"], e["error"]) for e in errors}
    for idx, (kind, sid) in enumerate(normalised):
        if (idx, "not_found") in failed_pairs:
            next_calls.append(
                {
                    "tool": "get_evidence_packet",
                    "args": {"subject_kind": kind, "subject_id": sid},
                    "reason": "verify_not_found",
                }
            )
            if len(next_calls) >= 5:
                break
    if any(k == "program" for k, _ in normalised):
        next_calls.append(
            {
                "tool": "get_evidence_packet_query",
                "reason": "free_text_exploration",
            }
        )

    body: dict[str, Any] = {
        "results": results,
        "total": len(normalised),
        "successful": successful,
        "failed": len(normalised) - successful,
        "errors": errors,
        "_billing_unit": successful,
        "_next_calls": next_calls,
        "_disclaimer": _DISCLAIMER,
        "corpus_snapshot_id": corpus_snapshot_id or "",
    }
    return attach_corpus_snapshot(body)


# ---------------------------------------------------------------------------
# MCP tool registration. Gated by AUTONOMATH_EVIDENCE_BATCH_ENABLED + the
# global AUTONOMATH_ENABLED.
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def get_evidence_packet_batch(
        lookups: Annotated[
            list[dict[str, Any]],
            Field(
                description=(
                    f"Up to {MAX_BATCH_LOOKUPS} `{{kind, id}}` lookups. Each "
                    "entry: kind ∈ ('program', 'houjin'), id = unified_id "
                    "(UNI-...) / canonical_id (program:...) / 13-digit "
                    "法人番号. 1 ¥3 unit per SUCCESSFUL lookup; failures "
                    "are NOT billed. 101+ entries returns an error envelope."
                ),
                min_length=1,
                max_length=MAX_BATCH_LOOKUPS,
            ),
        ],
    ) -> dict[str, Any]:
        """[EVIDENCE-PACKET-BATCH] Bulk Evidence Packet composer — up to 100 {kind, id} lookups in one call. Returns {results[], total, successful, failed, errors[], _billing_unit, _next_calls, _disclaimer, corpus_snapshot_id, audit_seal}. SAME composer as get_evidence_packet. NO LLM. ¥3 × successful only.

        WHAT: Resolves N {kind, id} lookups against the same composer used
        by get_evidence_packet, returns the bundle as one envelope. Each
        entry surfaces the full per-fact provenance + compat-matrix rule
        verdicts (program only) like the single-record tool. Failures
        (not_found / composer_failure) appear in errors[] with the
        original lookup payload + index so the caller can stitch
        results back to inputs.

        WHEN:
          - Need evidence for >5 subjects in one round-trip (LLM agent
            workflow that wants to fetch 100 programs at once)
          - Building 稟議資料 across a portfolio of programs / houjin
          - Bulk pre-fetch before answer generation across many subjects

        WHEN NOT:
          - Single-subject lookup → get_evidence_packet
          - Free-text query → use REST POST /v1/evidence/packets/query

        BILLING: 1 successful lookup = 1 ¥3 unit. 100-lookup batch with
        99 hits + 1 not_found is ¥297 (not ¥300). _billing_unit echoes
        the actual unit count so the caller can reconcile against
        Stripe usage_records.
        """
        return _impl_get_evidence_packet_batch(lookups=lookups)


__all__ = [
    "MAX_BATCH_LOOKUPS",
    "_impl_get_evidence_packet_batch",
]
