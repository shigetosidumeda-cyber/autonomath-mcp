"""Wave 51 dim R — Federated MCP recommendation (jpcite as hub).

This package is the **reusable, router-agnostic** core for the dim R
"jpcite hub" layer described in
``feedback_federated_mcp_recommendation``:

    * When an agent asks jpcite a question whose answer lives in a
      different MCP server (freee invoice / Notion doc / Slack chat /
      etc.), jpcite must NOT just say "no data" — it must recommend the
      partner MCP that does own the answer.
    * The recommendation is a deterministic capability-keyword match.
      No LLM inference, no aggregator, no third-party MCP server call.
    * jpcite becomes the hub of a 6-partner federation (freee, MF,
      Notion, Slack, GitHub, Linear). Agents chain calls themselves —
      jpcite never proxies partner traffic.

The companion storage layer lives in ``am_federated_mcp_partner``
(migration 278, seeded by ``scripts/etl/seed_federated_mcp_partners.py``)
and is consumed by the REST / MCP recommendation surface. **This package
adds the in-process primitives** so the same partner registry + gap
matcher can run from any caller (REST, MCP tool, ETL probe, offline CLI)
without each call site re-parsing JSON or duplicating the match
heuristic.

Public surface
--------------
    PartnerMcp                — Pydantic model for one curated partner.
    PartnerMcpEndpointStatus  — Literal type for mcp_endpoint_status.
    FederatedRegistry         — Frozen registry of the 6 curated partners.
    FEDERATED_PARTNERS_JSON   — Path to the canonical JSON shipped at
                                ``data/federated_partners.json``.
    recommend_handoff(query_gap) -> tuple[PartnerMcp, ...]
                              — Deterministic capability-keyword match.
    PARTNER_IDS               — Stable tuple of partner_ids for wire tests.

Non-goals
---------
* Does NOT call any LLM API or external HTTP endpoint at runtime.
* Does NOT proxy partner MCP traffic — agents call partners directly.
* Does NOT recommend jpcite itself; federation is to peers only.
* Does NOT replace the migration-278-backed SQLite catalogue; this
  package is the in-process façade over the same curated shortlist.
"""

from __future__ import annotations

from jpintel_mcp.federated_mcp.models import (
    PARTNER_ID_PATTERN,
    PartnerMcp,
    PartnerMcpEndpointStatus,
)
from jpintel_mcp.federated_mcp.recommend import recommend_handoff
from jpintel_mcp.federated_mcp.registry import (
    FEDERATED_PARTNERS_JSON,
    PARTNER_IDS,
    FederatedRegistry,
    load_default_registry,
)

__all__ = [
    "FEDERATED_PARTNERS_JSON",
    "PARTNER_IDS",
    "PARTNER_ID_PATTERN",
    "FederatedRegistry",
    "PartnerMcp",
    "PartnerMcpEndpointStatus",
    "load_default_registry",
    "recommend_handoff",
]
