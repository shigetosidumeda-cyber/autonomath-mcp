"""EmbedConfig — Pydantic-validated per-host configuration for dim S.

Each row of ``data/copilot_hosts.json`` deserializes into one
:class:`EmbedConfig` instance. The model is intentionally **frozen +
extra='forbid'** so a typo in the host data file fails loudly at load
time rather than silently dropping fields that downstream consumers
expect.

Fields
------
host_saas_id:
    Canonical short identifier (``freee`` / ``moneyforward`` / ``notion``
    / ``slack``). MUST be one of :data:`SUPPORTED_HOSTS` so the proxy
    layer can pattern-match without re-deriving from Pydantic
    introspection.
allowed_origins:
    Tuple of allowed browser origins for the embedded widget's
    ``postMessage`` and CORS preflight. Every origin MUST start with
    ``https://`` — embedded widgets are never served from plain HTTP.
mcp_proxy_token:
    Per-host token the widget includes in the ``X-Jpcite-Proxy-Token``
    header. NOT a customer API key — it scopes the proxy endpoint to
    the embedded surface so traffic from random origins gets 403'd
    before the dispatch happens. Rotate per host as needed.
oauth_redirect_uri:
    The host SaaS's OAuth callback URL. Used by :class:`OAuthBridge` to
    build authorize URLs. MUST start with ``https://`` and live under
    the host's own apex (no jpcite-owned origin in the redirect).

The bundled JSON file lives at the repo-root ``data/`` directory so the
same path resolves from REST handlers (Fly volume mount), MCP server
(stdio), and tests (pytest cwd = repo root). The data file is the
**source of truth** — to add a 5th host, edit the JSON and update
:data:`SUPPORTED_HOSTS` here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Repo-root data file containing the 4 canonical host configs.
HOST_DATA_FILE: Final[Path] = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "copilot_hosts.json"
)

#: Frozen set of supported host identifiers. Adding a 5th host requires
#: updating BOTH the JSON file AND this constant — the duplication is
#: deliberate so a typo in the JSON file cannot smuggle in an unknown
#: host without a code-review-visible diff here.
SUPPORTED_HOSTS: Final[frozenset[str]] = frozenset({"freee", "moneyforward", "notion", "slack"})

#: Literal alias used by :class:`EmbedConfig.host_saas_id` so static
#: type-checkers (mypy --strict) can refuse unknown ids at the call
#: site instead of waiting for the runtime Pydantic validator.
HostSaasId = Literal["freee", "moneyforward", "notion", "slack"]


class EmbedConfig(BaseModel):
    """Per-host embed configuration.

    Frozen + ``extra='forbid'`` so any unknown field in the JSON file
    raises a ``ValidationError`` at load time — silent drift is the
    failure mode this module exists to prevent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    host_saas_id: HostSaasId = Field(
        description=(
            "Canonical short identifier of the host SaaS. MUST match one "
            "of the 4 supported ids; any other value fails validation."
        ),
    )
    allowed_origins: tuple[str, ...] = Field(
        min_length=1,
        description=(
            "Tuple of allowed browser origins (https://...) for the "
            "embedded widget's postMessage + CORS preflight. At least "
            "one origin is required so the host SaaS has at least one "
            "place that can render the widget."
        ),
    )
    mcp_proxy_token: str = Field(
        min_length=16,
        description=(
            "Per-host proxy token included in X-Jpcite-Proxy-Token "
            "header. 16+ chars so a brute-force scan across hosts is "
            "non-trivial without further sampling."
        ),
    )
    oauth_redirect_uri: str = Field(
        min_length=1,
        description=(
            "Host SaaS's OAuth callback URL. Used by OAuthBridge to "
            "build authorize URLs. MUST start with https://."
        ),
    )

    @field_validator("allowed_origins")
    @classmethod
    def _validate_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Every allowed origin MUST start with ``https://``.

        Embedded widgets must never load over plain HTTP — the widget
        posts MCP tool requests from the host SaaS to the jpcite proxy
        endpoint, and a downgrade attack on the host's TLS would let an
        attacker re-write the tool calls in transit.
        """
        for origin in value:
            if not origin.startswith("https://"):
                raise ValueError(
                    f"allowed_origins entries must start with 'https://'; "
                    f"got {origin!r}. Plain HTTP would expose embed traffic to MITM."
                )
        return value

    @field_validator("oauth_redirect_uri")
    @classmethod
    def _validate_redirect_uri(cls, value: str) -> str:
        """OAuth redirect URI must be served over HTTPS."""
        if not value.startswith("https://"):
            raise ValueError(
                f"oauth_redirect_uri must start with 'https://'; got {value!r}. "
                f"OAuth state tokens over HTTP are vulnerable to interception."
            )
        return value


def load_default_hosts(path: Path | None = None) -> list[EmbedConfig]:
    """Load all 4 canonical host configs from the bundled JSON file.

    Parameters
    ----------
    path:
        Optional override of :data:`HOST_DATA_FILE`. Useful for tests
        with a fixture JSON. Defaults to the bundled data file.

    Returns
    -------
    list[EmbedConfig]
        List of EmbedConfig in the order they appear in the JSON file.
        The bundled file is deterministically ordered (freee →
        moneyforward → notion → slack) so downstream code can rely on
        a stable iteration order without re-sorting.

    Raises
    ------
    FileNotFoundError
        If the JSON file is missing. The bundled file ships in-repo so
        this only fires on a misconfigured path override.
    pydantic.ValidationError
        If any row fails the EmbedConfig validators.
    """
    src = path if path is not None else HOST_DATA_FILE
    raw = json.loads(src.read_text(encoding="utf-8"))
    hosts: list[EmbedConfig] = [EmbedConfig.model_validate(row) for row in raw]
    # Defensive: enforce the SUPPORTED_HOSTS contract here as well so a
    # JSON file with the right number of rows but a duplicated or
    # mistyped id is caught immediately.
    ids = {h.host_saas_id for h in hosts}
    if ids != SUPPORTED_HOSTS:
        missing = SUPPORTED_HOSTS - ids
        extra = ids - SUPPORTED_HOSTS
        raise ValueError(
            f"copilot_hosts.json must contain exactly the 4 supported hosts; "
            f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
        )
    return hosts


def load_host(host_saas_id: str, *, path: Path | None = None) -> EmbedConfig:
    """Load the EmbedConfig for one host_saas_id.

    Parameters
    ----------
    host_saas_id:
        One of :data:`SUPPORTED_HOSTS`. Any other value raises
        ``KeyError`` so callers do not need to special-case ``None``.
    path:
        Optional override of :data:`HOST_DATA_FILE`.
    """
    if host_saas_id not in SUPPORTED_HOSTS:
        raise KeyError(
            f"unknown host_saas_id {host_saas_id!r}; supported={sorted(SUPPORTED_HOSTS)!r}"
        )
    for cfg in load_default_hosts(path=path):
        if cfg.host_saas_id == host_saas_id:
            return cfg
    # load_default_hosts already enforces SUPPORTED_HOSTS so this is
    # structurally unreachable; the explicit raise keeps the type
    # checker happy and documents the invariant.
    raise KeyError(f"host_saas_id {host_saas_id!r} absent from data file")


__all__ = [
    "HOST_DATA_FILE",
    "SUPPORTED_HOSTS",
    "EmbedConfig",
    "HostSaasId",
    "load_default_hosts",
    "load_host",
]
