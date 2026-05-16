"""Wave 51 dim S — tests for the copilot_scaffold router-agnostic module.

Distinct from the Wave 47 integration tests (``test_dim_s_copilot_scaffold``
exercises migration 279 + the ``am_copilot_widget_config`` SQLite layer);
this module-level suite covers the **router-agnostic primitives** under
``src/jpintel_mcp/copilot_scaffold/``:

    * EmbedConfig Pydantic model — fields validated, https enforced
    * load_default_hosts — 4 canonical hosts (freee / MF / Notion / Slack)
    * load_host — single host lookup, KeyError on unknown
    * McpProxy — pure dispatcher, NO LLM inference
    * AtomicToolRegistry protocol — fake injection
    * OAuthBridge — mint / verify state token round-trip
    * OAuthBridge.build_authorize_url — URL builder, https enforced
    * LLM-0 invariant — proxy file has zero LLM SDK imports
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from jpintel_mcp.copilot_scaffold import (
    HOST_DATA_FILE,
    SUPPORTED_HOSTS,
    AtomicToolRegistry,
    EmbedConfig,
    McpProxy,
    McpProxyResult,
    OAuthBridge,
    load_default_hosts,
    load_host,
)
from jpintel_mcp.copilot_scaffold.proxy import (
    DISPATCH_ERROR_CODES,
    PROXY_RESULT_SCHEMA_VERSION,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeRegistry:
    """Deterministic atomic-callable registry for tests.

    Mirrors :class:`AtomicToolRegistry` but never invokes anything real
    or network-bound; satisfies the Protocol structurally.
    """

    def __init__(self, tools: dict[str, Any] | None = None) -> None:
        self._tools = tools or {}

    def has(self, name: str, /) -> bool:
        return name in self._tools

    def call(self, name: str, /, **kwargs: Any) -> Any:
        if name not in self._tools:
            raise KeyError(name)
        impl = self._tools[name]
        return impl(**kwargs)


def _minimal_config(host: str = "freee") -> EmbedConfig:
    return EmbedConfig(
        host_saas_id=host,  # type: ignore[arg-type]
        allowed_origins=("https://example.com",),
        mcp_proxy_token="x" * 32,
        oauth_redirect_uri="https://example.com/cb",
    )


# ---------------------------------------------------------------------------
# 1. EmbedConfig validation
# ---------------------------------------------------------------------------


def test_embed_config_minimum_valid() -> None:
    cfg = _minimal_config()
    assert cfg.host_saas_id == "freee"
    assert cfg.allowed_origins == ("https://example.com",)
    assert cfg.mcp_proxy_token.startswith("x")
    assert cfg.oauth_redirect_uri == "https://example.com/cb"


def test_embed_config_rejects_unknown_host_saas_id() -> None:
    with pytest.raises(ValidationError):
        EmbedConfig(
            host_saas_id="github",  # type: ignore[arg-type]
            allowed_origins=("https://example.com",),
            mcp_proxy_token="x" * 32,
            oauth_redirect_uri="https://example.com/cb",
        )


def test_embed_config_rejects_http_origin() -> None:
    with pytest.raises(ValidationError):
        EmbedConfig(
            host_saas_id="freee",
            allowed_origins=("http://insecure.example.com",),
            mcp_proxy_token="x" * 32,
            oauth_redirect_uri="https://example.com/cb",
        )


def test_embed_config_rejects_http_redirect_uri() -> None:
    with pytest.raises(ValidationError):
        EmbedConfig(
            host_saas_id="freee",
            allowed_origins=("https://example.com",),
            mcp_proxy_token="x" * 32,
            oauth_redirect_uri="http://insecure.example.com/cb",
        )


def test_embed_config_rejects_short_proxy_token() -> None:
    with pytest.raises(ValidationError):
        EmbedConfig(
            host_saas_id="freee",
            allowed_origins=("https://example.com",),
            mcp_proxy_token="short",  # 5 chars
            oauth_redirect_uri="https://example.com/cb",
        )


def test_embed_config_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        EmbedConfig.model_validate(
            {
                "host_saas_id": "freee",
                "allowed_origins": ["https://example.com"],
                "mcp_proxy_token": "x" * 32,
                "oauth_redirect_uri": "https://example.com/cb",
                "secret_typo_field": "leak",
            }
        )


def test_embed_config_is_frozen() -> None:
    cfg = _minimal_config()
    with pytest.raises(ValidationError):
        cfg.mcp_proxy_token = "rebound"  # type: ignore[misc]


def test_embed_config_requires_at_least_one_origin() -> None:
    with pytest.raises(ValidationError):
        EmbedConfig(
            host_saas_id="freee",
            allowed_origins=(),
            mcp_proxy_token="x" * 32,
            oauth_redirect_uri="https://example.com/cb",
        )


# ---------------------------------------------------------------------------
# 2. Bundled data file: 4 canonical hosts
# ---------------------------------------------------------------------------


def test_supported_hosts_constant_matches_spec() -> None:
    assert frozenset({"freee", "moneyforward", "notion", "slack"}) == SUPPORTED_HOSTS


def test_load_default_hosts_returns_all_four() -> None:
    hosts = load_default_hosts()
    assert {h.host_saas_id for h in hosts} == SUPPORTED_HOSTS
    assert len(hosts) == 4


def test_load_host_each_supported_id() -> None:
    for host_id in SUPPORTED_HOSTS:
        cfg = load_host(host_id)
        assert cfg.host_saas_id == host_id
        # Every origin AND redirect URI must be https — enforced at
        # load time, this assertion is a belt-and-braces guard against
        # the JSON file being edited to weaken the contract.
        for origin in cfg.allowed_origins:
            assert origin.startswith("https://")
        assert cfg.oauth_redirect_uri.startswith("https://")


def test_load_host_raises_on_unknown_id() -> None:
    with pytest.raises(KeyError):
        load_host("github")


def test_data_file_path_lives_in_repo_data_dir() -> None:
    # Belt-and-braces: the bundled file must be at repo-root data/ so
    # Fly volume mount + GHA runner + dev shell all resolve the same path.
    assert HOST_DATA_FILE.name == "copilot_hosts.json"
    assert HOST_DATA_FILE.parent.name == "data"
    assert HOST_DATA_FILE.exists()


def test_load_default_hosts_with_fixture_path_rejects_missing_hosts(tmp_path: Path) -> None:
    """Fixture file missing one of the 4 supported hosts must fail load."""
    bad = tmp_path / "bad_hosts.json"
    bad.write_text(
        json.dumps(
            [
                {
                    "host_saas_id": "freee",
                    "allowed_origins": ["https://example.com"],
                    "mcp_proxy_token": "x" * 32,
                    "oauth_redirect_uri": "https://example.com/cb",
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_default_hosts(path=bad)


# ---------------------------------------------------------------------------
# 3. McpProxy — pure dispatcher invariants
# ---------------------------------------------------------------------------


def test_proxy_dispatch_happy_path() -> None:
    reg = _FakeRegistry({"search_programs": lambda **kw: {"hits": kw.get("q", "")}})
    proxy = McpProxy(reg)
    result = proxy.dispatch("search_programs", q="IT導入補助金")
    assert isinstance(result, McpProxyResult)
    assert result.ok is True
    assert result.payload == {"hits": "IT導入補助金"}
    assert result.error_code is None
    assert result.tool_name == "search_programs"
    assert result.schema_version == PROXY_RESULT_SCHEMA_VERSION


def test_proxy_dispatch_tool_not_found() -> None:
    proxy = McpProxy(_FakeRegistry())
    r = proxy.dispatch("nonexistent_tool")
    assert r.ok is False
    assert r.error_code == "tool_not_found"
    assert r.payload is None
    assert "nonexistent_tool" in r.error_message


def test_proxy_dispatch_respects_allowlist() -> None:
    reg = _FakeRegistry(
        {
            "search_programs": lambda **_: {"hits": 1},
            "internal_admin": lambda **_: {"secret": True},
        }
    )
    proxy = McpProxy(reg, allowed_tools=frozenset({"search_programs"}))
    ok = proxy.dispatch("search_programs", q="x")
    blocked = proxy.dispatch("internal_admin")
    assert ok.ok is True
    assert blocked.ok is False
    assert blocked.error_code == "tool_not_allowed"
    assert blocked.payload is None


def test_proxy_dispatch_catches_atomic_exception() -> None:
    def boom(**_: Any) -> Any:
        raise RuntimeError("atomic blew up")

    reg = _FakeRegistry({"boom": boom})
    proxy = McpProxy(reg)
    r = proxy.dispatch("boom")
    assert r.ok is False
    assert r.error_code == "tool_raised"
    assert "RuntimeError" in r.error_message
    assert "atomic blew up" in r.error_message


def test_proxy_never_performs_llm_inference() -> None:
    """The proxy is structurally inference-free.

    Every successful dispatch returns ``llm_inference_performed=False``
    so the widget UI can transparently surface the fact to end users.
    """
    reg = _FakeRegistry({"search_programs": lambda **_: {"ok": True}})
    proxy = McpProxy(reg)
    r = proxy.dispatch("search_programs")
    assert r.llm_inference_performed is False


def test_proxy_dispatch_error_codes_enum_stable() -> None:
    """The error-code enum is part of the wire contract."""
    assert (
        frozenset({"tool_not_found", "tool_not_allowed", "tool_raised", "invalid_kwargs"})
        == DISPATCH_ERROR_CODES
    )


def test_proxy_allowed_tools_property_returns_configured_set() -> None:
    proxy = McpProxy(_FakeRegistry(), allowed_tools=frozenset({"a", "b"}))
    assert proxy.allowed_tools == frozenset({"a", "b"})

    unrestricted = McpProxy(_FakeRegistry())
    assert unrestricted.allowed_tools is None


def test_proxy_registry_protocol_structural() -> None:
    """The Protocol must accept any class that implements has + call."""
    reg: AtomicToolRegistry = _FakeRegistry({"x": lambda **_: 1})
    # Mypy-style structural check — runtime just confirms duck typing.
    assert reg.has("x") is True
    assert reg.call("x") == 1


def test_proxy_module_has_no_llm_imports() -> None:
    """Wave 51 dim S core invariant: the proxy file is LLM-free.

    Mirrors ``tests/test_no_llm_in_production.py`` but scopes the
    assertion to this single file so a regression here fails before
    the global CI guard.
    """
    proxy_file = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "jpintel_mcp"
        / "copilot_scaffold"
        / "proxy.py"
    )
    src = proxy_file.read_text(encoding="utf-8")
    forbidden_imports = (
        "import anthropic",
        "import openai",
        "import google.generativeai",
        "import langchain",
        "import claude_agent_sdk",
        "import mistralai",
        "import cohere",
        "import groq",
        "import replicate",
        "import together",
        "import vertexai",
        "import bedrock_runtime",
        "from anthropic",
        "from openai",
        "from google.generativeai",
        "from langchain",
        "from claude_agent_sdk",
        "from mistralai",
        "from cohere",
        "from groq",
        "from replicate",
        "from together",
        "from vertexai",
        "from bedrock_runtime",
    )
    for bad in forbidden_imports:
        assert bad not in src, (
            f"LLM SDK import {bad!r} leaked into copilot_scaffold/proxy.py "
            f"(violates feedback_copilot_scaffold_only_no_llm)"
        )


# ---------------------------------------------------------------------------
# 4. OAuthBridge — state-token mint/verify + authorize URL
# ---------------------------------------------------------------------------


def test_oauth_bridge_mint_verify_round_trip() -> None:
    bridge = OAuthBridge("test_secret_must_be_at_least_16_bytes_long")
    state = bridge.mint_state("freee")
    assert bridge.verify_state("freee", state) is True


def test_oauth_bridge_rejects_short_secret() -> None:
    with pytest.raises(ValueError):
        OAuthBridge("short")  # < 16 bytes


def test_oauth_bridge_state_bound_to_host() -> None:
    """A state minted for freee must NOT verify under another host id."""
    bridge = OAuthBridge("test_secret_must_be_at_least_16_bytes_long")
    state = bridge.mint_state("freee")
    assert bridge.verify_state("slack", state) is False
    assert bridge.verify_state("moneyforward", state) is False


def test_oauth_bridge_verify_rejects_malformed_token() -> None:
    bridge = OAuthBridge("test_secret_must_be_at_least_16_bytes_long")
    assert bridge.verify_state("freee", "") is False
    assert bridge.verify_state("freee", "noseparator") is False
    assert bridge.verify_state("freee", "too.many.dots") is False
    assert bridge.verify_state("freee", ".missing_nonce") is False
    assert bridge.verify_state("freee", "missing_hmac.") is False


def test_oauth_bridge_build_authorize_url_happy_path() -> None:
    bridge = OAuthBridge("test_secret_must_be_at_least_16_bytes_long")
    state = bridge.mint_state("freee")
    url = bridge.build_authorize_url(
        authorize_endpoint="https://accounts.freee.co.jp/public_api/authorize",
        client_id="abc123",
        redirect_uri="https://secure.freee.co.jp/oauth/callback/jpcite",
        state=state,
        scopes=("read", "write"),
    )
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.freee.co.jp"
    assert qs["client_id"] == ["abc123"]
    assert qs["state"] == [state]
    assert qs["response_type"] == ["code"]
    assert qs["scope"] == ["read write"]


def test_oauth_bridge_build_authorize_url_rejects_http_endpoint() -> None:
    bridge = OAuthBridge("test_secret_must_be_at_least_16_bytes_long")
    with pytest.raises(ValueError):
        bridge.build_authorize_url(
            authorize_endpoint="http://insecure.example.com/authorize",
            client_id="abc",
            redirect_uri="https://example.com/cb",
            state="x",
        )


def test_oauth_bridge_build_authorize_url_rejects_http_redirect() -> None:
    bridge = OAuthBridge("test_secret_must_be_at_least_16_bytes_long")
    with pytest.raises(ValueError):
        bridge.build_authorize_url(
            authorize_endpoint="https://example.com/authorize",
            client_id="abc",
            redirect_uri="http://insecure.example.com/cb",
            state="x",
        )


def test_oauth_bridge_build_authorize_url_rejects_empty_client_id() -> None:
    bridge = OAuthBridge("test_secret_must_be_at_least_16_bytes_long")
    with pytest.raises(ValueError):
        bridge.build_authorize_url(
            authorize_endpoint="https://example.com/authorize",
            client_id="",
            redirect_uri="https://example.com/cb",
            state="x",
        )


def test_oauth_bridge_mint_rejects_empty_host() -> None:
    bridge = OAuthBridge("test_secret_must_be_at_least_16_bytes_long")
    with pytest.raises(ValueError):
        bridge.mint_state("")


# ---------------------------------------------------------------------------
# 5. Widget HTML — vanilla, no framework, has no LLM SDK ref
# ---------------------------------------------------------------------------


def test_widget_html_exists_and_is_vanilla() -> None:
    widget = Path(__file__).resolve().parent.parent / "site" / "embed" / "widget.html"
    assert widget.exists(), "site/embed/widget.html must ship as part of dim S"
    src = widget.read_text(encoding="utf-8")
    # Vanilla HTML+JS — no framework, no inference SDK pulled at runtime.
    forbidden = (
        "anthropic",
        "openai",
        "@anthropic-ai",
        "@openai",
        "react.production.min.js",
        "vue.global.prod.js",
        "angular.min.js",
    )
    lower = src.lower()
    for bad in forbidden:
        assert bad not in lower, (
            f"widget.html must not reference {bad!r} — scaffold is "
            f"vanilla HTML+JS without LLM SDKs or JS frameworks"
        )
    # The widget MUST self-declare it is scaffold-only / LLM-0.
    assert "scaffold" in lower
    assert "schema_version" in src  # widget posts the schema_version field
