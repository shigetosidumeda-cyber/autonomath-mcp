"""Wave 51 dim P — Composable tools (server-side atomic composition).

This package wraps the existing atomic 139+ MCP tools with **server-side**
composition. The driver intent is described in
``feedback_composable_tools_pattern`` (Wave 43 Dim P, ratified for Wave 51)::

    現 139 MCP tools は atomic (1 tool = 1 機能).
    顧客 workflow は通常 5-10 step.
    7 call 連発 → composed 1 call で ¥3 × 7 → ¥3 × 1 で 7 倍経済化.

Why this module exists in its own package
-----------------------------------------
The atomic MCP layer lives in ``src/jpintel_mcp/mcp/`` and is wired against
the FastMCP server registry. Composed tools must remain agnostic of that
wiring so they can be reused from:

* MCP tool surface (1 composed tool = 1 ``@mcp.tool``).
* REST surface (``api/composed.py`` or any future router).
* Offline composition manifests / ETL probes.
* Tests, without spinning up a FastMCP runtime.

The atomic functions therefore live behind a thin :class:`AtomicRegistry`
protocol — production code injects the real atomic Python callables (the
ones the FastMCP wrappers ultimately call); tests inject deterministic
fakes. This is the canonical "1 call covers 5-10 step workflow"
performance multiplier per Wave 51 dim P spec.

What this module is NOT
-----------------------
* **Not MCP-to-MCP recursion.** Composed tools invoke atomic Python
  callables directly via the injected registry — never re-enter the MCP
  protocol. MCP-to-MCP recursion would re-spend the metering budget the
  composition layer exists to compress.
* **Not an LLM router.** No ``anthropic`` / ``openai`` / ``google.generativeai``
  import. The composition order is deterministic (declared via
  :class:`ComposableTool.atomic_dependencies`); no inference step picks
  a different sequence at request time.
* **Not a new contract namespace.** Composed tool envelopes reuse the
  canonical :class:`Evidence` / ``Citation`` / :class:`OutcomeContract`
  models from ``agent_runtime.contracts`` and ``api._envelope``. The
  envelope type returned by :meth:`ComposableTool.run` is :class:`ComposedEnvelope`,
  a structural wrapper around those existing types — not a fresh one.

Public surface
--------------
    ComposableTool              — abstract base for one composed tool.
    ComposedEnvelope            — return type, wraps Evidence + Citations.
    AtomicRegistry              — protocol of injected atomic callables.
    AtomicCallResult            — uniform shape returned by atomic shims.
    register_default_tools()    — emits the 4 initial composed tools.
    eligibility_audit_workpaper — 税理士 monthly audit composed tool.
    subsidy_eligibility_full    — 補助金 7-step full eligibility check.
    ma_due_diligence_pack       — M&A DD bundle.
    invoice_compatibility_check — 適格事業者照合 + corporate enrichment.

Non-negotiable rule
-------------------
Every composed tool MUST declare its atomic dependencies up front in
``atomic_dependencies``. If a future atomic tool is renamed or removed,
:meth:`ComposableTool.validate_registry` raises before any partial side
effects are committed. This prevents "skip the missing one" silent
degradation that would erode the composition guarantee.
"""

from __future__ import annotations

from jpintel_mcp.composable_tools.base import (
    AtomicCallResult,
    AtomicRegistry,
    ComposableTool,
    ComposedEnvelope,
    ComposedToolError,
)
from jpintel_mcp.composable_tools.registry import (
    DEFAULT_COMPOSED_TOOLS,
    register_default_tools,
)
from jpintel_mcp.composable_tools.tools import (
    EligibilityAuditWorkpaper,
    InvoiceCompatibilityCheck,
    MaDueDiligencePack,
    SubsidyEligibilityFull,
)
from jpintel_mcp.composable_tools.wave51_chains import (
    WAVE51_CHAIN_TOOLS,
    EvidenceWithProvenance,
    FederatedHandoffWithAudit,
    SessionAwareEligibilityCheck,
    TemporalComplianceAudit,
    register_wave51_chains,
)

__all__ = [
    "DEFAULT_COMPOSED_TOOLS",
    "WAVE51_CHAIN_TOOLS",
    "AtomicCallResult",
    "AtomicRegistry",
    "ComposableTool",
    "ComposedEnvelope",
    "ComposedToolError",
    "EligibilityAuditWorkpaper",
    "EvidenceWithProvenance",
    "FederatedHandoffWithAudit",
    "InvoiceCompatibilityCheck",
    "MaDueDiligencePack",
    "SessionAwareEligibilityCheck",
    "SubsidyEligibilityFull",
    "TemporalComplianceAudit",
    "register_default_tools",
    "register_wave51_chains",
]
