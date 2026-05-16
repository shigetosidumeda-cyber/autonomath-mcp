from __future__ import annotations

import asyncio

from jpintel_mcp.mcp.federation import build_federation_manifest
from jpintel_mcp.mcp.transport_metadata import (
    a2a_transport_advertisements,
    mcp_transport_manifest_meta,
    mcp_transport_names,
)


def test_transport_metadata_advertises_streamable_http() -> None:
    meta = mcp_transport_manifest_meta()

    assert mcp_transport_names() == ["stdio", "sse", "streamable_http"]
    assert meta["transports"] == ["stdio", "sse", "streamable_http"]
    assert meta["transport_endpoints"]["streamable_http"]["type"] == "streamable_http"
    assert meta["transport_endpoints"]["streamable_http"]["url"].endswith("/v1/mcp/streamable_http")


def test_a2a_agent_card_uses_shared_transport_metadata() -> None:
    from jpintel_mcp.api.a2a import agent_card

    card = asyncio.run(agent_card())

    assert card["transport"] == a2a_transport_advertisements()
    assert "mcp_stdio" in card["transport"]
    assert "mcp_streamable_http" in card["transport"]


def test_federation_manifest_uses_shared_transport_metadata() -> None:
    manifest = build_federation_manifest()

    assert manifest["capabilities"]["transport"] == mcp_transport_names()


def test_meta_transport_endpoint_uses_shared_transport_metadata() -> None:
    from jpintel_mcp.api.meta import list_transports

    payload = list_transports().body.decode("utf-8")

    assert '"streamable_http"' in payload
    assert "https://api.jpcite.com/v1/mcp/streamable_http" in payload
