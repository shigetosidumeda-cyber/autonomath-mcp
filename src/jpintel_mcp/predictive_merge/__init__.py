"""Wave 51 L4 — predictive_merge_daily (AX Layer 6 cron input).

This package implements the deterministic daily merge that combines the
Dim K predictive registry (``predictive_service``) with the Dim Q
time-machine snapshot tree (``time_machine``) to produce a 24h-ahead
predictive artifact described in
``docs/_internal/WAVE51_L3_L4_L5_DESIGN.md``::

    cron 名 / 役割: predictive_merge_daily
    Dim K (predictive houjin_watch / program_window / amendment_diff) と
    Dim Q (time-machine as_of 月次 snapshot) を merge し、24h 先
    prediction を生成。stale な prediction は as_of で時間軸補正。
    daily 02:00 JST (Wave 51 L4 / AX Layer 6)

The module is **router-agnostic** so the same primitives serve:

* MCP tool surface (a future ``recommend_predictive_merge`` family tool).
* REST surface (a future ``/v1/predictive/merge_daily`` router).
* AX Layer 6 cron (``scripts/cron/ax_layer_6_predictive_merge.py``).
* Tests, without spinning up FastMCP / FastAPI / DB handles.

Hard constraints (enforced structurally, not by convention):

- **No LLM SDK import**: no ``anthropic`` / ``openai`` /
  ``google.generativeai`` / ``claude_agent_sdk``. The merge is a
  deterministic join + time-axis correction; no inference, no embedding
  lookup. CI guard ``tests/test_no_llm_in_production.py`` enforces.
- **No live HTTP / DB**: the event source is the dim K JSONL log; the
  snapshot source is the dim Q file-based registry. Nothing here opens
  a socket or a database handle.
- **Pure / deterministic**: same events + same snapshots + same
  ``run_at`` → byte-identical :class:`MergedDailyArtifact`. No clock,
  no random, no env-var.

See ``merge.py`` for the merger + classifier, and ``models.py`` for the
Pydantic envelopes.

Public surface
--------------
    MergedPrediction        — Pydantic, one time-corrected prediction row.
    MergePolicy             — Pydantic, declarative knob bundle.
    MergedDailyArtifact     — Pydantic, full artifact envelope.
    MergeEventType          — Literal type alias for the dim K event types.
    CorrectionReason        — Literal type alias for the 3 reasons.
    classify_horizon        — Pure helper exposing the reason logic.
    merge_event             — Per-event merger (atomic helper).
    run_daily_merge         — One-shot facade returning a MergedDailyArtifact.
    MERGE_SCHEMA_VERSION    — Schema-version literal pinned on the artifact.
"""

from __future__ import annotations

from jpintel_mcp.predictive_merge.merge import (
    classify_horizon,
    merge_event,
    run_daily_merge,
)
from jpintel_mcp.predictive_merge.models import (
    MERGE_SCHEMA_VERSION,
    CorrectionReason,
    MergeEventType,
    MergedDailyArtifact,
    MergedPrediction,
    MergePolicy,
)

__all__ = [
    "MERGE_SCHEMA_VERSION",
    "CorrectionReason",
    "MergeEventType",
    "MergePolicy",
    "MergedDailyArtifact",
    "MergedPrediction",
    "classify_horizon",
    "merge_event",
    "run_daily_merge",
]
