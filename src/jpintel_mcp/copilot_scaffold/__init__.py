"""Wave 51 dim S — Embedded copilot scaffold (widget + MCP proxy + OAuth bridge).

This package is the **reusable, router-agnostic** core for the dim S
"embedded copilot scaffold" layer described in
``feedback_copilot_scaffold_only_no_llm``:

    * 顧客 SaaS (freee / MoneyForward / Notion / Slack 等) の画面内に
      jpcite copilot widget を embed すると、agent UX の最終形
      (zero-click integration) になる。
    * **但し** 我々が LLM API を呼ぶと ¥0.5/req 構造で即赤字
      (`feedback_autonomath_no_api_use`). よって scaffold (UI + MCP
      proxy + auth bridge) のみ提供、推論は顧客側 LLM で完結させる。

The package therefore provides **three primitives** plus **zero LLM
inference**:

1. :class:`EmbedConfig` — per-host configuration (Pydantic, validated).
2. :class:`McpProxy` — pure dispatcher that forwards MCP tool calls to
   the registered jpcite atomic-callable registry. **MUST NOT** call any
   LLM. Tests assert this invariant.
3. :class:`OAuthBridge` — URL builder for the OAuth handshake (state
   token + redirect URI). It does **not** perform the OAuth exchange
   itself — that lives in the host SaaS / customer infra.

The 4 SaaS host configs ship in ``data/copilot_hosts.json`` and are
loaded by :func:`load_default_hosts`. The HTML widget (~50 lines vanilla
JS, no framework) lives at ``site/embed/widget.html`` and posts MCP
tool requests to the proxy endpoint registered by the host SaaS.

Public surface
--------------
    EmbedConfig             — Pydantic config per host SaaS.
    McpProxy                — pure dispatcher (no LLM).
    McpProxyResult          — return shape from McpProxy.dispatch.
    OAuthBridge             — state-token URL builder (no exchange).
    AtomicToolRegistry      — protocol the proxy dispatches against.
    HOST_DATA_FILE          — Path to bundled ``data/copilot_hosts.json``.
    SUPPORTED_HOSTS         — frozenset of 4 supported host_saas_ids.
    load_default_hosts()    — list[EmbedConfig] of all 4 hosts.
    load_host(host_saas_id) — EmbedConfig for a specific host.

Non-goals
---------
* Does NOT call any LLM API or external HTTP endpoint.
* Does NOT replace ``src/jpintel_mcp/api/copilot_scaffold.py`` (which is
  the DB-backed audit-log helper landed via migration 279). This module
  is the **router-agnostic** layer that any future consumer (REST / MCP
  / static site / offline ETL) can compose without dragging FastAPI /
  SQLite handles.
* Does NOT execute the OAuth code-exchange step. :class:`OAuthBridge`
  builds the authorize URL + verifies the state token; the
  authorization-code → access-token exchange is the host SaaS's
  responsibility (their LLM, their credentials, their cost).
"""

from __future__ import annotations

from .config import (
    HOST_DATA_FILE,
    SUPPORTED_HOSTS,
    EmbedConfig,
    load_default_hosts,
    load_host,
)
from .oauth_bridge import OAuthBridge
from .proxy import AtomicToolRegistry, McpProxy, McpProxyResult

__all__ = [
    "HOST_DATA_FILE",
    "SUPPORTED_HOSTS",
    "AtomicToolRegistry",
    "EmbedConfig",
    "McpProxy",
    "McpProxyResult",
    "OAuthBridge",
    "load_default_hosts",
    "load_host",
]
