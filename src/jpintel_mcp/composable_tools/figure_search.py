"""Wave 51 dim P (M3 extension) — figure semantic search composable tool.

This module ships the **fifth** composable tool —
``search_figures_by_topic`` — introduced by AWS moat Lane M3 (multi-modal
CLIP-Japanese figure embeddings, 2026-05-17). The tool wraps the M3
vec0 substrate (``am_figure_embeddings`` + ``am_figure_embeddings_vec``
per migration ``200_am_figure_embeddings``) behind the canonical
:class:`ComposableTool` contract so customer agents can query figures
("飲食店向け補助金フロー図", "農地集約 体系図", "事業承継 stepwise
フロー", etc.) with a single ¥3/req composed call.

Why a separate module
---------------------
The original 4 composed tools in :mod:`jpintel_mcp.composable_tools.tools`
orbit the 139-tool *text-only* atomic surface. M3 introduces a *new
vector space* (512-dim vision-text aligned CLIP-Japanese, distinct from
the 1024-dim ``intfloat/multilingual-e5-large`` text encoder migrated
in 166). Bundling the figure search next to text-only composed tools
would muddle the compression-ratio promise on either surface, so it
ships as its own composed tool with a deliberate single atomic
dependency (``search_figures_by_topic_atomic``) plus a graceful
``support_state="absent"`` fallback when the M3 substrate is empty
(e.g. before the first SageMaker Processing Job drains).

Non-negotiable rules (mirrored from feedback_composable_tools_pattern)
----------------------------------------------------------------------
* **No LLM call.** CLIP-Japanese is an encoder-only image+text
  alignment model. The atomic surface accepts a plain string topic +
  delegates query-embedding to the same encoder; no Anthropic /
  OpenAI / Bedrock / google.generativeai dependency.
* **No aggregator fetch.** Vec query runs against jpcite SQLite +
  sqlite-vec, identical to the migration 166 surface.
* **No partial-fail abandon.** When the atomic dependency is missing
  or returns empty, the wrapper returns a :class:`ComposedEnvelope`
  with ``support_state="absent"`` and a ``warnings`` entry pointing
  at the SageMaker Processing Job status — never raises.
* **JPCIR envelope reuse.** Returns :class:`ComposedEnvelope` per
  Wave 51 dim P contract; the underlying :class:`Evidence` +
  :class:`OutcomeContract` types are the canonical agent_runtime
  models, no fresh namespace.

Public surface
--------------
    SearchFiguresByTopic        — ``ComposableTool`` subclass.
    M3_TOOL_NAMES               — canonical 1-tuple for wire stability.
    register_m3_tools()         — fresh instances per call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

from jpintel_mcp.agent_runtime.contracts import (
    Evidence,
    OutcomeContract,
)
from jpintel_mcp.composable_tools.base import (
    AtomicRegistry,
    ComposableTool,
    ComposedEnvelope,
    ComposedToolError,
)

#: Compose-tool name surfaced by the FastMCP registry + REST router.
SEARCH_FIGURES_BY_TOPIC_NAME: Final[str] = "search_figures_by_topic"

#: 1-tuple of M3 tool names. Pinned for wire-shape regression tests; bump
#: requires a coordinated manifest update.
M3_TOOL_NAMES: Final[tuple[str, ...]] = (SEARCH_FIGURES_BY_TOPIC_NAME,)

#: Canonical name of the atomic this composed tool dispatches to.
SEARCH_FIGURES_ATOMIC: Final[str] = "search_figures_by_topic_atomic"

#: CLIP-Japanese model id used by the M3 SageMaker Processing Job.
#: Surfaced in the composed envelope so downstream agents can pattern
#: -match on the encoder identity (the M3 vec space is NOT comparable
#: to the migration 166 text vec space).
M3_EMBEDDING_MODEL: Final[str] = "rinna/japanese-clip-vit-b-16"
M3_EMBEDDING_DIM: Final[int] = 512
M3_VEC_SPACE: Final[str] = "m3_clip_jp_v1"

#: Tuple of valid ``figure_kind`` filter values surfaced to callers.
#: Mirrors the column-level CHECK constraint envisaged for migration
#: 200 (``raster`` / ``vector`` / ``table_image`` / ``unknown``).
ALLOWED_FIGURE_KINDS: Final[frozenset[str]] = frozenset(
    {"raster", "vector", "table_image", "unknown"}
)


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _support_state(figures: list[dict[str, Any]]) -> str:
    """Resolve ``support_state`` from the atomic figure count.

    M3 is a single-atomic composed tool so the
    ``_support_state_for(payload_richness)`` helper in
    :mod:`jpintel_mcp.composable_tools.tools` simplifies to a binary
    test — return ``supported`` when at least one figure came back,
    else ``absent``.
    """
    return "supported" if figures else "absent"


class SearchFiguresByTopic(ComposableTool):
    """Composable wrapper around the M3 figure-vec retrieval atomic.

    Atomic dependencies (1):
        * ``search_figures_by_topic_atomic`` — vec0 KNN over
          ``am_figure_embeddings_vec`` joined to ``am_figure_embeddings``
          for source_url + caption + page metadata.

    Required ``kwargs``:
        * ``topic`` (str): natural-language description, e.g.
          ``"飲食店向け補助金フロー図"`` / ``"農地集約 体系図"``.

    Optional ``kwargs``:
        * ``top_k`` (int, default 10): vec0 KNN cap.
        * ``figure_kind`` (str | None): filter — one of
          ``raster`` / ``vector`` / ``table_image`` / ``unknown``.
    """

    @property
    def composed_tool_name(self) -> str:
        """Return the canonical composed-tool name."""
        return SEARCH_FIGURES_BY_TOPIC_NAME

    @property
    def atomic_dependencies(self) -> tuple[str, ...]:
        """Declare the 1 atomic this composed tool depends on."""
        return (SEARCH_FIGURES_ATOMIC,)

    @property
    def outcome_contract(self) -> OutcomeContract:
        """Return the :class:`OutcomeContract` for this composed tool."""
        return OutcomeContract(
            outcome_contract_id=f"composed_{self.composed_tool_name}",
            display_name="Search figures by topic (CLIP-Japanese 512-dim multi-modal)",
            packet_ids=(f"packet_{self.composed_tool_name}",),
            billable=True,
        )

    def compose(
        self,
        registry: AtomicRegistry,
        /,
        **kwargs: Any,
    ) -> ComposedEnvelope:
        """Run the figure-vec query via the injected atomic registry.

        Returns a :class:`ComposedEnvelope` whose ``primary_result`` is a
        dict with ``figures``: an ordered list of
        ``{figure_id, caption, source_url, page_no, similarity, s3_key,
        figure_kind}`` rows.  When the atomic returns empty, the envelope
        is still returned with ``support_state="absent"`` so the caller
        can surface the M3-not-ready hint rather than retry.
        """
        topic = kwargs.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            raise ComposedToolError("search_figures_by_topic requires a non-empty 'topic' string")
        top_k = kwargs.get("top_k", 10)
        if not isinstance(top_k, int) or top_k <= 0:
            top_k = 10
        figure_kind = kwargs.get("figure_kind")
        if figure_kind is not None and figure_kind not in ALLOWED_FIGURE_KINDS:
            figure_kind = None

        atomic_result = registry.call(
            SEARCH_FIGURES_ATOMIC,
            topic=topic,
            top_k=top_k,
            figure_kind=figure_kind,
        )
        figures: list[dict[str, Any]] = list(atomic_result.payload.get("figures", []))
        citations = atomic_result.citations
        warnings = list(atomic_result.notes)
        if not figures:
            warnings.append(
                "M3 atomic returned no figures — substrate may not have "
                "drained yet (check s3://jpcite-credit-993693061769-202605-derived/"
                "figure_embeddings/) or the topic is out-of-distribution."
            )

        support_state = _support_state(figures)
        evidence = Evidence(
            evidence_id=f"composed_evidence_{self.composed_tool_name}_v1",
            claim_ref_ids=(f"composed_claim_{self.composed_tool_name}_v1",),
            receipt_ids=(f"composed_receipt_{self.composed_tool_name}_{SEARCH_FIGURES_ATOMIC}",),
            evidence_type=(
                "derived_inference" if support_state == "supported" else "absence_observation"
            ),
            support_state=support_state,
            temporal_envelope="point_in_time",
            observed_at=_now_iso(),
        )
        primary: dict[str, Any] = {
            "topic": topic,
            "top_k": top_k,
            "figure_kind_filter": figure_kind,
            "figures": figures,
            "embedding_model": M3_EMBEDDING_MODEL,
            "embedding_dim": M3_EMBEDDING_DIM,
            "vec_space": M3_VEC_SPACE,
        }
        return ComposedEnvelope(
            composed_tool_name=self.composed_tool_name,
            evidence=evidence,
            outcome_contract=self.outcome_contract,
            composed_steps=self.atomic_dependencies,
            primary_result=primary,
            citations=citations,
            warnings=tuple(warnings),
            compression_ratio=len(self.atomic_dependencies),
        )


def register_m3_tools() -> tuple[ComposableTool, ...]:
    """Return fresh instances of the M3 composed tools (currently 1).

    Order matters for wire stability — tests assert
    ``tuple(t.composed_tool_name for t in register_m3_tools())`` equals
    :data:`M3_TOOL_NAMES`.
    """
    return (SearchFiguresByTopic(),)


__all__ = [
    "ALLOWED_FIGURE_KINDS",
    "M3_EMBEDDING_DIM",
    "M3_EMBEDDING_MODEL",
    "M3_TOOL_NAMES",
    "M3_VEC_SPACE",
    "SEARCH_FIGURES_ATOMIC",
    "SEARCH_FIGURES_BY_TOPIC_NAME",
    "SearchFiguresByTopic",
    "register_m3_tools",
]
