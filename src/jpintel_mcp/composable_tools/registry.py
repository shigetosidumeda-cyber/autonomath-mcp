"""Default composed tools registry.

Surfaces the canonical 4-tool initial cohort for Wave 51 dim P. Imported
by REST / MCP wrappers, ETL scripts, and tests to obtain a stable list
of composed tools without restating the names.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from jpintel_mcp.composable_tools.tools import (
    EligibilityAuditWorkpaper,
    InvoiceCompatibilityCheck,
    MaDueDiligencePack,
    SubsidyEligibilityFull,
)

if TYPE_CHECKING:
    from jpintel_mcp.composable_tools.base import ComposableTool


def register_default_tools() -> tuple[ComposableTool, ...]:
    """Return fresh instances of the 4 initial composed tools.

    A new instance is constructed per call so callers can mutate /
    subclass without sharing state. Order matters for wire stability —
    tests assert ``[t.composed_tool_name for t in register_default_tools()]``
    is exactly the expected 4-tuple.
    """
    return (
        EligibilityAuditWorkpaper(),
        SubsidyEligibilityFull(),
        MaDueDiligencePack(),
        InvoiceCompatibilityCheck(),
    )


#: Canonical 4-tuple of composed-tool names. Pinned for wire-shape
#: regression tests; bumping requires a coordinated manifest bump.
DEFAULT_COMPOSED_TOOLS: Final[tuple[str, ...]] = (
    "eligibility_audit_workpaper",
    "subsidy_eligibility_full",
    "ma_due_diligence_pack",
    "invoice_compatibility_check",
)


__all__ = [
    "DEFAULT_COMPOSED_TOOLS",
    "register_default_tools",
]
