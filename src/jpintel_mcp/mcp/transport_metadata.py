"""Shared MCP transport advertisement metadata.

The package entrypoint remains stdio, while public discovery surfaces also
advertise the HTTP transports that web/A2A clients can route against.
Keeping this in one module prevents the registry manifest, A2A card, and
federation surface from drifting.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Final

MCP_PRIMARY_TRANSPORT: Final[str] = "stdio"
MCP_TRANSPORT_NAMES: Final[tuple[str, ...]] = ("stdio", "sse", "streamable_http")

MCP_TRANSPORTS_NOTE: Final[str] = (
    "stdio is the package install/default entrypoint (uvx autonomath-mcp). "
    "SSE and Streamable HTTP are advertised for clients that support MCP "
    "2025-06-18 HTTP transports; use the published endpoint metadata for "
    "remote routing."
)

MCP_TRANSPORT_ENDPOINTS: Final[dict[str, dict[str, Any]]] = {
    "stdio": {
        "type": "stdio",
        "status": "production_default",
        "command": "uvx autonomath-mcp",
        "install_url": "https://jpcite.com/integrations/?src=mcp_registry",
    },
    "sse": {
        "type": "sse",
        "status": "advertised",
        "url": "https://api.jpcite.com/v1/mcp/sse",
        "method": "GET",
        "protocol": "mcp-2025-06-18",
    },
    "streamable_http": {
        "type": "streamable_http",
        "status": "advertised",
        "url": "https://api.jpcite.com/v1/mcp/streamable_http",
        "method": "POST",
        "protocol": "mcp-2025-06-18",
    },
}


def mcp_transport_names() -> list[str]:
    """Return manifest-order transport names."""
    return list(MCP_TRANSPORT_NAMES)


def mcp_transport_manifest_meta() -> dict[str, Any]:
    """Return a JSON-serialisable manifest metadata block."""
    return {
        "transports": mcp_transport_names(),
        "transports_note": MCP_TRANSPORTS_NOTE,
        "transport_endpoints": deepcopy(MCP_TRANSPORT_ENDPOINTS),
    }


def a2a_transport_advertisements() -> list[str]:
    """Return A2A Agent Card transport identifiers."""
    return ["http_json", *(f"mcp_{name}" for name in MCP_TRANSPORT_NAMES)]


__all__ = [
    "MCP_PRIMARY_TRANSPORT",
    "MCP_TRANSPORT_ENDPOINTS",
    "MCP_TRANSPORT_NAMES",
    "MCP_TRANSPORTS_NOTE",
    "a2a_transport_advertisements",
    "mcp_transport_manifest_meta",
    "mcp_transport_names",
]
