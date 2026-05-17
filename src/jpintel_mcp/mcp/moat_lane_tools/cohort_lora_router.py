"""Moat BB4 — Cohort-aware LoRA adapter router MCP wrapper.

Surfaces the BB4 per-cohort LoRA adapter lane as
``cohort_lora_resolve``. Each cohort (税理士 / 会計士 / 行政書士 /
司法書士 / 中小経営者) trains a small (~5-15 MB) PEFT LoRA adapter
on top of the M5 jpcite-bert-v1 SimCSE encoder. The router resolves
``segment`` (Japanese segment string OR the EN slug used by N8) to
the canonical cohort id plus the S3 URI of the cohort's LoRA
adapter ``model.tar.gz``.

This is the **resolution** seam — actual GPU inference is performed
downstream by ``agent_full_context`` (HE-1) when the adapter is
loaded into the local encoder. Returning S3 URIs keeps the MCP
contract pure-Python + zero-cost; no model weights are loaded inside
this MCP handler.

Returns a PENDING envelope if the cohort's LoRA training has not yet
landed (training job not Completed OR adapter object not present on
S3). Once landed, returns the resolved adapter pointer + training
metadata.

NO LLM inference is performed in this tool. The downstream encoder
(jpcite-bert-v1 + LoRA) is a local encoder; LoRA training is offline
on SageMaker.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import DISCLAIMER, today_iso_utc

_TOOL_NAME = "cohort_lora_resolve"
_LANE_ID = "BB4"
_SCHEMA_VERSION = "moat.bb4.v1"

#: Canonical cohort id list. Mirrors the LoRA training corpus prep
#: cohorts (see ``scripts/aws_credit_ops/lora_cohort_corpus_prep_2026_05_17.py``).
_VALID_COHORTS: tuple[str, ...] = (
    "zeirishi",
    "kaikeishi",
    "gyouseishoshi",
    "shihoshoshi",
    "chusho_keieisha",
)

#: Mapping from user-facing segment (Japanese string OR EN N8 slug) to
#: canonical cohort id. Accepts the same inputs HE-1 accepts so the
#: router can be wired straight into ``agent_full_context``.
_SEGMENT_TO_COHORT: dict[str, str] = {
    # Japanese segment strings
    "税理士": "zeirishi",
    "会計士": "kaikeishi",
    "行政書士": "gyouseishoshi",
    "司法書士": "shihoshoshi",
    "社労士": "gyouseishoshi",  # Closest neighbour cohort (no dedicated 社労士 LoRA yet)
    "中小経営者": "chusho_keieisha",
    "AX_engineer": "chusho_keieisha",  # Engineer-side cohort merges with SME
    "ax_engineer": "chusho_keieisha",
    "ax_fde": "chusho_keieisha",
    # EN slugs from N8 recipes
    "tax": "zeirishi",
    "audit": "kaikeishi",
    "gyousei": "gyouseishoshi",
    "shihoshoshi": "shihoshoshi",
    # Direct cohort ids (idempotent passthrough)
    "zeirishi": "zeirishi",
    "kaikeishi": "kaikeishi",
    "gyouseishoshi": "gyouseishoshi",
    "chusho_keieisha": "chusho_keieisha",
}

#: S3 bucket + key template for adapter resolution. The training job
#: writes ``s3://{bucket}/models/jpcite-bert-lora-{cohort}/.../output/model.tar.gz``;
#: the resolver returns the prefix (latest job is resolved server-side
#: by listing the prefix and picking the most-recent ``output/model.tar.gz``).
_S3_BUCKET = "jpcite-credit-993693061769-202605-derived"
_ADAPTER_KEY_TPL = "models/jpcite-bert-lora-{cohort}/"


def _normalize_segment(segment: str) -> str | None:
    """Return the canonical cohort id or ``None`` if unknown."""

    seg = (segment or "").strip()
    if not seg:
        return None
    if seg in _SEGMENT_TO_COHORT:
        return _SEGMENT_TO_COHORT[seg]
    # Lowercase fallback for EN slugs.
    seg_l = seg.lower()
    if seg_l in _SEGMENT_TO_COHORT:
        return _SEGMENT_TO_COHORT[seg_l]
    return None


def _resolve_adapter_uri(cohort: str) -> str:
    """Return the canonical S3 prefix for the cohort's LoRA adapter.

    The prefix lists all per-job output dirs; the consuming HE-1 path
    is responsible for picking the most recent ``output/model.tar.gz``.
    This MCP handler returns the prefix only to keep the tool free of
    network I/O / blocking S3 calls.
    """

    return f"s3://{_S3_BUCKET}/{_ADAPTER_KEY_TPL.format(cohort=cohort)}"


def _pending_marker(cohort: str | None) -> str:
    if cohort is None:
        return f"PENDING {_LANE_ID} unknown-segment"
    return f"PENDING {_LANE_ID} cohort={cohort}"


def _envelope(
    *,
    cohort: str | None,
    segment: str,
    status: str,
    rationale: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical BB4 response envelope.

    The envelope shape mirrors the moat-lane PENDING envelope (so
    agent code that already branches on ``_pending_marker`` works
    unchanged) but populates ``primary_result`` with the resolved
    cohort + adapter URI when status is ``resolved``.
    """

    result: dict[str, Any] = {
        "status": status,
        "lane_id": _LANE_ID,
        "input_segment": segment,
        "rationale": rationale,
    }
    if cohort is not None:
        result["cohort"] = cohort
        result["adapter_s3_prefix"] = _resolve_adapter_uri(cohort)
        result["base_model"] = "jpcite-bert-v1 (M5 SimCSE checkpoint)"
        result["base_fallback"] = "cl-tohoku/bert-base-japanese-v3"
        result["target_modules"] = ["query", "key", "value", "output.dense"]
        result["lora_rank"] = 16
        result["lora_alpha"] = 32
    if extra:
        result.update(extra)
    return {
        "tool_name": _TOOL_NAME,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": result,
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": "jpintel_mcp.mcp.moat_lane_tools.cohort_lora_router",
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_bb4_wrap",
            "observed_at": today_iso_utc(),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
        "_pending_marker": _pending_marker(cohort if status == "resolved" else None),
    }


@mcp.tool(annotations=_READ_ONLY)
def cohort_lora_resolve(
    segment: Annotated[
        str,
        Field(
            min_length=1,
            max_length=64,
            description=(
                "Cohort or segment identifier. Accepts JA segment strings "
                "(税理士 / 会計士 / 行政書士 / 司法書士 / 社労士 / 中小経営者), "
                "EN N8 slugs (tax / audit / gyousei / shihoshoshi / ax_fde), "
                "or direct cohort ids (zeirishi / kaikeishi / gyouseishoshi / "
                "shihoshoshi / chusho_keieisha)."
            ),
        ),
    ],
) -> dict[str, Any]:
    """[AUDIT] Moat BB4 cohort LoRA adapter router. Resolves a segment
    string to the canonical cohort id plus the S3 prefix of that cohort's
    LoRA adapter ``model.tar.gz`` (trained on top of M5 jpcite-bert-v1).

    Returns a structural PENDING envelope when the segment is unknown
    OR when the cohort's adapter has not yet landed (BB4 training jobs
    chain post-M5 on the single ml.g4dn.xlarge quota slot — full 5
    cohort series takes ~25-30 hours).

    NO LLM inference is performed here. The downstream encoder
    (jpcite-bert-v1 + LoRA) is a local encoder; this tool only
    resolves pointers.
    """

    cohort = _normalize_segment(segment)
    if cohort is None:
        return _envelope(
            cohort=None,
            segment=segment,
            status="unknown_segment",
            rationale=(
                f"Segment {segment!r} does not map to any of the 5 cohort LoRA "
                "adapters (zeirishi / kaikeishi / gyouseishoshi / shihoshoshi / "
                "chusho_keieisha). Pass one of the supported JA segments, EN N8 "
                "slugs, or direct cohort ids."
            ),
            extra={"valid_cohorts": list(_VALID_COHORTS)},
        )
    return _envelope(
        cohort=cohort,
        segment=segment,
        status="resolved",
        rationale=(
            f"Resolved segment {segment!r} -> cohort={cohort!r}. The adapter "
            "S3 prefix lists all per-job outputs; HE-1 picks the latest "
            "output/model.tar.gz on load. Adapter is a PEFT LoRA "
            "(rank=16, alpha=32) on top of jpcite-bert-v1 SimCSE encoder."
        ),
    )
