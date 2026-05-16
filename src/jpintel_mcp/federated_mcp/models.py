"""Pydantic models for Wave 51 dim R federated-MCP recommendation.

The model mirrors ``schemas/jpcir/federated_partner.schema.json`` 1:1.
Parity is exercised by tests in ``tests/test_federated_mcp.py`` —
adding or renaming a field requires touching both surfaces.

This module is intentionally schema-only. The registry + gap-matcher
live in sibling modules so consumers can import ``PartnerMcp`` for
typing alone without pulling the JSON-file loader.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

#: Canonical regex for partner_id slugs. Mirrored in the JSON schema.
PARTNER_ID_PATTERN: str = r"^[a-z][a-z0-9_]*$"

#: Canonical regex for capability tags. Mirrored in the JSON schema.
CAPABILITY_PATTERN: str = r"^[a-z][a-z0-9_]*$"

#: Status enum for ``PartnerMcp.mcp_endpoint_status``.
#:
#: ``official``      — partner operates a public MCP endpoint we can cite
#:                     against first-party docs.
#: ``none_official`` — partner has no public MCP yet; downstream agents
#:                     fall back to REST/GraphQL via ``official_url``.
PartnerMcpEndpointStatus = Literal["official", "none_official"]


class PartnerMcp(BaseModel):
    """One curated federated-MCP partner row.

    Immutable by config — agents and callers MUST treat partner rows
    as read-only fixtures. Mutating a partner mid-run would invalidate
    the audit log entries that reference its slug.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    partner_id: str = Field(
        ...,
        min_length=1,
        max_length=32,
        pattern=PARTNER_ID_PATTERN,
        description=(
            "Stable short slug for the partner. Used as the canonical join "
            "key with am_federated_mcp_partner.partner_id (migration 278)."
        ),
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "Display name. May contain Japanese / English / spaces. "
            "Surfaced verbatim to agents in recommendation envelopes."
        ),
    )
    official_url: HttpUrl = Field(
        ...,
        description=(
            "Canonical first-party developer-portal / product URL for the "
            "partner. ALWAYS https. Used for human verification of the "
            "recommendation surface."
        ),
    )
    mcp_endpoint: HttpUrl | None = Field(
        ...,
        description=(
            "Official partner-operated MCP server endpoint when one "
            "exists, otherwise None. NEVER a third-party aggregator "
            "endpoint — only first-party-confirmed MCP URLs."
        ),
    )
    mcp_endpoint_status: PartnerMcpEndpointStatus = Field(
        ...,
        description=(
            "Disposition of mcp_endpoint. official = first-party hosted "
            "MCP confirmed via partner docs. none_official = partner has "
            "no public MCP yet, fall back to REST/GraphQL via official_url."
        ),
    )
    capabilities: tuple[str, ...] = Field(
        ...,
        min_length=1,
        max_length=16,
        description=(
            "Capability tags describing what the partner MCP / API can "
            "do. Used by gap-matching keyword lookup. Lowercase ascii "
            "tokens matching CAPABILITY_PATTERN."
        ),
    )
    use_when: str = Field(
        ...,
        min_length=1,
        max_length=280,
        description=(
            "One-sentence guidance (English) telling an agent when to "
            "hand off to this partner. Shown verbatim in recommendation "
            "envelopes."
        ),
    )

    @field_validator("official_url", "mcp_endpoint")
    @classmethod
    def _enforce_https_scheme(cls, value: HttpUrl | None) -> HttpUrl | None:
        """Reject non-https URLs even though HttpUrl alone would accept them.

        Pydantic v2 ``HttpUrl`` permits ``http://`` by default; the dim R
        contract requires every recommendation URL to be https for SEO
        + audit hygiene + browser security mixed-content rules.
        """
        if value is None:
            return value
        if value.scheme != "https":
            raise ValueError(f"federated partner URL must use https, got scheme={value.scheme!r}")
        return value

    def has_capability(self, tag: str) -> bool:
        """Return True iff ``tag`` is one of this partner's capabilities."""
        return tag in self.capabilities


__all__ = [
    "CAPABILITY_PATTERN",
    "PARTNER_ID_PATTERN",
    "PartnerMcp",
    "PartnerMcpEndpointStatus",
]
