"""copilot_scaffold — Dim S embedded copilot scaffold surface.

Wave 46 dim 19 SFGH booster (2026-05-12)
========================================

Implements the Dim S design (`feedback_copilot_scaffold_only_no_llm`):
ship widget scaffold + MCP proxy + OAuth bridge for partner SaaS embed
(freee / Money Forward / Notion / Slack), but with **NO LLM inference**
inside the operator process. The customer SaaS is expected to bring its
own LLM (Anthropic / OpenAI / etc.); jpcite only renders the deterministic
scaffold and proxies the underlying MCP / REST surfaces.

Endpoints
---------
    GET  /v1/copilot/scaffold/{partner}
        Returns a JSON envelope describing the widget mount point,
        the MCP proxy URL, the OAuth bridge URL, and the static asset
        bundle URL. Partner is one of {freee, mf, notion, slack}.
        200 -> {partner, widget_html_skeleton, mcp_proxy_url,
                 oauth_bridge_url, asset_bundle_url, _disclaimer,
                 _billing_unit, _no_llm}
        404 -> {detail: "unknown partner"} for non-whitelisted values.

    GET  /v1/copilot/scaffold/partners
        Returns the static partner whitelist for discovery.
        200 -> {partners: [...], total: N, _no_llm: true}

Hard constraints (CLAUDE.md + feedback_copilot_scaffold_only_no_llm):

  * **NO LLM call.** No Anthropic / OpenAI / Gemini import. The widget
    HTML skeleton is a static string template — variable interpolation
    only, no model inference.
  * **NO heavy DB scan.** Pure Python dict lookup against a hard-coded
    partner registry (constant module-level dict, no I/O).
  * 1 ¥3/req billing unit per call (scaffold + partners discovery).
  * 弁護士法 §72 / 行政書士法 §1 / 税理士法 §52 disclaimer envelope.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("jpintel.api.copilot_scaffold")

router = APIRouter(prefix="/v1/copilot/scaffold", tags=["copilot_scaffold"])

_DISCLAIMER = (
    "本 copilot scaffold は widget mount + MCP proxy + OAuth bridge の "
    "静的足場のみを提供します。実際の自然言語応答 / 推論は埋込先 SaaS "
    "の自社 LLM が担い、jpcite 側で LLM 呼出は一切行いません。"
    "本 endpoint は弁護士法 §72 / 行政書士法 §1 / 税理士法 §52 等の "
    "資格独占役務には該当しません。"
)

# Partner registry. Each entry describes the deterministic scaffold that
# the customer SaaS will mount inside its own UI. mcp_proxy_url and
# oauth_bridge_url point at jpcite's existing MCP and OAuth endpoints —
# the scaffold simply tells the embedder where they live.
_PARTNER_REGISTRY: dict[str, dict[str, str]] = {
    "freee": {
        "display_name": "freee 会計",
        "widget_id": "jpcite-copilot-freee",
        "mcp_proxy_path": "/mcp/sse",
        "oauth_bridge_path": "/v1/integrations/freee/oauth/start",
        "asset_bundle": "/assets/copilot/freee.js",
    },
    "mf": {
        "display_name": "Money Forward クラウド",
        "widget_id": "jpcite-copilot-mf",
        "mcp_proxy_path": "/mcp/sse",
        "oauth_bridge_path": "/v1/integrations/mf/oauth/start",
        "asset_bundle": "/assets/copilot/mf.js",
    },
    "notion": {
        "display_name": "Notion",
        "widget_id": "jpcite-copilot-notion",
        "mcp_proxy_path": "/mcp/sse",
        "oauth_bridge_path": "/v1/integrations/notion/oauth/start",
        "asset_bundle": "/assets/copilot/notion.js",
    },
    "slack": {
        "display_name": "Slack",
        "widget_id": "jpcite-copilot-slack",
        "mcp_proxy_path": "/mcp/sse",
        "oauth_bridge_path": "/v1/integrations/slack/oauth/start",
        "asset_bundle": "/assets/copilot/slack.js",
    },
}


class ScaffoldResponse(BaseModel):
    partner: str
    display_name: str
    widget_html_skeleton: str
    mcp_proxy_url: str
    oauth_bridge_url: str
    asset_bundle_url: str
    no_llm: bool = Field(
        default=True,
        description="Always true — jpcite scaffold never invokes an LLM",
    )
    billing_unit: int = Field(default=1)
    disclaimer: str = Field(default=_DISCLAIMER)


class PartnersResponse(BaseModel):
    partners: list[str]
    total: int
    no_llm: bool = Field(default=True)
    disclaimer: str = Field(default=_DISCLAIMER)


def _build_widget_skeleton(widget_id: str, mcp_proxy_url: str) -> str:
    """Render the deterministic HTML scaffold for a partner widget.

    NO LLM. Pure f-string template. The customer SaaS LLM hooks into
    the `data-mcp-proxy` attribute to drive its own tool-use loop.
    """
    return (
        f'<div id="{widget_id}" '
        f'class="jpcite-copilot-widget" '
        f'data-mcp-proxy="{mcp_proxy_url}" '
        f'data-no-llm="true">'
        f"</div>"
    )


def _build_full_url(path: str) -> str:
    """Compose absolute URL — pointing at the public jpcite host."""
    base = "https://jpcite-mcp.fly.dev"
    return f"{base}{path}"


@router.get("/partners", response_model=PartnersResponse)
async def list_partners() -> PartnersResponse:
    """List the curated partner whitelist for embedded copilot scaffold."""
    return PartnersResponse(
        partners=sorted(_PARTNER_REGISTRY.keys()),
        total=len(_PARTNER_REGISTRY),
    )


@router.get("/{partner}", response_model=ScaffoldResponse)
async def get_scaffold(partner: str) -> ScaffoldResponse:
    """Return the deterministic scaffold envelope for one partner.

    NO LLM. The customer SaaS receives a static HTML skeleton +
    proxy / bridge URLs and is responsible for plumbing its own LLM.
    """
    entry: dict[str, str] | None = _PARTNER_REGISTRY.get(partner)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown partner '{partner}'. "
            f"Allowed: {sorted(_PARTNER_REGISTRY.keys())}",
        )

    mcp_proxy_url = _build_full_url(entry["mcp_proxy_path"])
    oauth_bridge_url = _build_full_url(entry["oauth_bridge_path"])
    asset_bundle_url = _build_full_url(entry["asset_bundle"])

    return ScaffoldResponse(
        partner=partner,
        display_name=entry["display_name"],
        widget_html_skeleton=_build_widget_skeleton(
            entry["widget_id"], mcp_proxy_url,
        ),
        mcp_proxy_url=mcp_proxy_url,
        oauth_bridge_url=oauth_bridge_url,
        asset_bundle_url=asset_bundle_url,
    )


# Module-level sanity check — assert NO LLM imports leaked into this
# file. The `import sys` + module-name check is cheap and catches the
# `feedback_copilot_scaffold_only_no_llm` constraint at import time.
def _verify_no_llm_imports() -> dict[str, Any]:
    """Smoke check for guard tests. Returns import audit envelope."""
    import sys

    banned = {"anthropic", "openai", "google.generativeai", "cohere"}
    leaked = sorted(banned & set(sys.modules))
    return {
        "no_llm_verified": not leaked,
        "leaked_imports": leaked,
        "module": __name__,
    }
