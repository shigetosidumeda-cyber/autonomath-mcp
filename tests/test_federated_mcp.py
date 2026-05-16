"""Wave 51 dim R — federated_mcp module unit tests.

Covers the in-process module surface delivered by
``src/jpintel_mcp/federated_mcp/``:

  * :class:`PartnerMcp` Pydantic validation + immutability.
  * :class:`FederatedRegistry` size / lookup / self-reference rejection.
  * :func:`recommend_handoff` gap-keyword match for the 6 curated
    partners (freee / mf / notion / slack / github / linear).
  * Schema parity with ``schemas/jpcir/federated_partner.schema.json``.
  * JSON-file shape + alphabetical canonical order.

These tests do NOT exercise the SQLite ``am_federated_mcp_partner``
layer — that path is covered by ``tests/test_dim_r_federated_mcp.py``
(Wave 47 storage tests, separate concern).

Hard rules
----------
* No network call. No LLM SDK import. No HTTP.
* No mutation of cached registry between tests — every test that
  needs a custom shortlist builds it via
  :meth:`FederatedRegistry.from_partners`.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from pydantic import ValidationError

from jpintel_mcp.federated_mcp import (
    FEDERATED_PARTNERS_JSON,
    PARTNER_IDS,
    FederatedRegistry,
    PartnerMcp,
    load_default_registry,
    recommend_handoff,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "jpcir" / "federated_partner.schema.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_partner(
    partner_id: str = "freee",
    name: str = "freee 会計",
    official_url: str = "https://developer.freee.co.jp/",
    mcp_endpoint: str | None = None,
    mcp_endpoint_status: str = "none_official",
    capabilities: tuple[str, ...] = ("accounting", "invoice"),
    use_when: str = "Query needs private accounting ledger.",
) -> PartnerMcp:
    """Construct a partner row with sensible defaults for tests."""
    return PartnerMcp(
        partner_id=partner_id,
        name=name,
        official_url=official_url,  # type: ignore[arg-type]
        mcp_endpoint=mcp_endpoint,  # type: ignore[arg-type]
        mcp_endpoint_status=mcp_endpoint_status,  # type: ignore[arg-type]
        capabilities=capabilities,
        use_when=use_when,
    )


# ---------------------------------------------------------------------------
# Bundle 1: PartnerMcp model
# ---------------------------------------------------------------------------


def test_partner_mcp_round_trip() -> None:
    """Construct + serialise + reconstruct round-trip is lossless."""
    p = _make_partner()
    dumped = p.model_dump(mode="json")
    rebuilt = PartnerMcp.model_validate(dumped)
    assert rebuilt == p


def test_partner_mcp_is_frozen() -> None:
    """Partner rows must be immutable — mutating raises."""
    p = _make_partner()
    with pytest.raises(ValidationError):
        p.partner_id = "other"  # type: ignore[misc]


def test_partner_mcp_rejects_unknown_field() -> None:
    """extra='forbid' guarantees no silent typo absorption."""
    with pytest.raises(ValidationError):
        PartnerMcp.model_validate(
            {
                "partner_id": "freee",
                "name": "freee 会計",
                "official_url": "https://developer.freee.co.jp/",
                "mcp_endpoint": None,
                "mcp_endpoint_status": "none_official",
                "capabilities": ["accounting"],
                "use_when": "test",
                "stray_field": "boom",
            }
        )


def test_partner_mcp_rejects_invalid_partner_id() -> None:
    """partner_id must match ^[a-z][a-z0-9_]*$."""
    for bad in ("Freee", "1freee", "free-ee", "fr eee", ""):
        with pytest.raises(ValidationError):
            _make_partner(partner_id=bad)


def test_partner_mcp_rejects_non_https_official_url() -> None:
    """official_url must be https."""
    with pytest.raises(ValidationError):
        _make_partner(official_url="http://developer.freee.co.jp/")


def test_partner_mcp_accepts_none_mcp_endpoint() -> None:
    """mcp_endpoint may be None when status is none_official."""
    p = _make_partner(mcp_endpoint=None, mcp_endpoint_status="none_official")
    assert p.mcp_endpoint is None
    assert p.mcp_endpoint_status == "none_official"


def test_partner_mcp_rejects_invalid_status() -> None:
    """mcp_endpoint_status must be one of the literal enum values."""
    with pytest.raises(ValidationError):
        _make_partner(mcp_endpoint_status="third_party")


def test_partner_mcp_has_capability() -> None:
    """has_capability returns True iff the tag is listed."""
    p = _make_partner(capabilities=("accounting", "invoice"))
    assert p.has_capability("accounting") is True
    assert p.has_capability("payroll") is False


# ---------------------------------------------------------------------------
# Bundle 2: FederatedRegistry (custom shortlist)
# ---------------------------------------------------------------------------


def test_registry_rejects_duplicate_partner_id() -> None:
    """Duplicate slugs must raise at construction."""
    a = _make_partner(partner_id="freee")
    b = _make_partner(partner_id="freee", name="dup")
    with pytest.raises(ValueError, match="duplicate"):
        FederatedRegistry.from_partners((a, b))


def test_registry_rejects_self_reference() -> None:
    """jpcite / jpintel / autonomath must never appear as partners."""
    for forbidden in ("jpcite", "jpintel", "autonomath"):
        bad = _make_partner(partner_id=forbidden)
        with pytest.raises(ValueError, match="self-reference"):
            FederatedRegistry.from_partners((bad,))


def test_registry_get_and_require() -> None:
    """get returns None on miss; require raises KeyError."""
    p = _make_partner()
    reg = FederatedRegistry.from_partners((p,))
    assert reg.get("freee") is p
    assert reg.get("missing") is None
    with pytest.raises(KeyError):
        reg.require("missing")


def test_registry_contains() -> None:
    """__contains__ accepts only strings."""
    reg = FederatedRegistry.from_partners((_make_partner(),))
    assert "freee" in reg
    assert "missing" not in reg
    assert 42 not in reg  # type: ignore[comparison-overlap]


def test_registry_len_and_partner_ids() -> None:
    """len + partner_ids agree on size + order."""
    a = _make_partner(partner_id="freee")
    b = _make_partner(partner_id="github", capabilities=("code",))
    reg = FederatedRegistry.from_partners((a, b))
    assert len(reg) == 2
    assert reg.partner_ids == ("freee", "github")


# ---------------------------------------------------------------------------
# Bundle 3: load_default_registry — the shipped 6-partner shortlist
# ---------------------------------------------------------------------------


def test_default_registry_loads_six_partners() -> None:
    """The shipped JSON must contain exactly the 6 curated partners."""
    reg = load_default_registry()
    assert len(reg) == 6
    assert reg.partner_ids == PARTNER_IDS


def test_default_registry_partner_ids_are_canonical_set() -> None:
    """The 6 partners are exactly freee / github / linear / mf / notion / slack."""
    reg = load_default_registry()
    assert set(reg.partner_ids) == {
        "freee",
        "github",
        "linear",
        "mf",
        "notion",
        "slack",
    }


def test_default_registry_partner_ids_are_alphabetical() -> None:
    """Canonical order is alphabetical for wire-shape stability."""
    reg = load_default_registry()
    ids = reg.partner_ids
    assert list(ids) == sorted(ids)


def test_default_registry_is_cached_singleton() -> None:
    """Repeated calls return the same instance (no I/O on hot path)."""
    reg_a = load_default_registry()
    reg_b = load_default_registry()
    assert reg_a is reg_b


def test_default_registry_official_mcp_endpoints_match_first_party() -> None:
    """Partners flagged ``official`` must carry a first-party https URL."""
    reg = load_default_registry()
    for p in reg.partners:
        if p.mcp_endpoint_status == "official":
            assert p.mcp_endpoint is not None
            assert str(p.mcp_endpoint).startswith("https://")
        else:
            assert p.mcp_endpoint is None


def test_default_registry_no_aggregator_endpoints() -> None:
    """No third-party aggregator hosts (pulsemcp / smithery / glama) allowed."""
    reg = load_default_registry()
    forbidden_hosts = ("pulsemcp", "smithery.ai", "glama.ai", "mcp.so")
    for p in reg.partners:
        if p.mcp_endpoint is None:
            continue
        endpoint = str(p.mcp_endpoint).lower()
        for host in forbidden_hosts:
            assert host not in endpoint, (
                f"{p.partner_id} mcp_endpoint must be first-party, "
                f"got aggregator-like host: {endpoint}"
            )


def test_default_registry_official_urls_are_https() -> None:
    """Every official_url must be https for SEO + audit hygiene."""
    reg = load_default_registry()
    for p in reg.partners:
        assert str(p.official_url).startswith("https://"), p.partner_id


# ---------------------------------------------------------------------------
# Bundle 4: recommend_handoff — gap-keyword matcher
# ---------------------------------------------------------------------------


def test_recommend_invoice_freee() -> None:
    """English 'invoice' gap → freee surfaces in the result tuple."""
    recs = recommend_handoff("I need the invoice #1234 from freee", max_results=3)
    assert recs
    assert recs[0].partner_id == "freee"


def test_recommend_pull_request_github() -> None:
    """Gap mentioning 'pull request' → github wins."""
    recs = recommend_handoff("look up the pull request title on github", max_results=3)
    assert recs
    assert recs[0].partner_id == "github"


def test_recommend_notion_doc() -> None:
    """Gap about 'notion wiki' → notion wins."""
    recs = recommend_handoff("find a notion wiki page about onboarding", max_results=3)
    assert recs
    assert recs[0].partner_id == "notion"


def test_recommend_slack_chat() -> None:
    """Gap about 'slack message' → slack wins."""
    recs = recommend_handoff("send a slack message to #general", max_results=3)
    assert recs
    assert recs[0].partner_id == "slack"


def test_recommend_linear_issue() -> None:
    """Gap about 'linear cycle' → linear wins."""
    recs = recommend_handoff("show linear cycle progress", max_results=3)
    assert recs
    assert recs[0].partner_id == "linear"


def test_recommend_japanese_mf_alias() -> None:
    """Japanese マネーフォワード alias → mf wins."""
    recs = recommend_handoff("マネーフォワードクラウドの請求書を確認したい", max_results=3)
    assert recs
    assert recs[0].partner_id == "mf"


def test_recommend_japanese_kaikei_alias_picks_accounting_partner() -> None:
    """Generic 経理 / 会計データ alias surfaces freee + mf."""
    recs = recommend_handoff("クライアントの経理データを取得したい", max_results=3)
    rec_ids = {r.partner_id for r in recs}
    assert "freee" in rec_ids or "mf" in rec_ids


def test_recommend_empty_query_raises() -> None:
    """Empty / whitespace query raises ValueError."""
    for bad in ("", "  ", "\n\t"):
        with pytest.raises(ValueError):
            recommend_handoff(bad)


def test_recommend_invalid_max_results_raises() -> None:
    """max_results < 1 raises ValueError."""
    with pytest.raises(ValueError):
        recommend_handoff("invoice", max_results=0)


def test_recommend_returns_empty_tuple_on_no_match() -> None:
    """A gap mentioning none of the partners' capabilities → empty tuple."""
    recs = recommend_handoff("completely unrelated topic about quantum mechanics", max_results=3)
    assert recs == ()


def test_recommend_max_results_caps_output() -> None:
    """max_results upper-bounds the returned tuple size."""
    recs = recommend_handoff("invoice github linear notion slack accounting", max_results=2)
    assert len(recs) <= 2


def test_recommend_never_returns_self_reference() -> None:
    """recommend_handoff never surfaces jpcite as a partner."""
    recs = recommend_handoff("invoice github linear notion slack accounting payroll", max_results=6)
    for r in recs:
        assert r.partner_id != "jpcite"
        assert r.partner_id != "jpintel"
        assert r.partner_id != "autonomath"


def test_recommend_stable_order_for_tied_scores() -> None:
    """Same-score partners come back in alphabetical partner_id order."""
    # Build a custom registry where two partners tie on capability hit count.
    a = _make_partner(
        partner_id="alpha",
        official_url="https://alpha.example.com/",
        capabilities=("shared_tag",),
    )
    b = _make_partner(
        partner_id="beta",
        official_url="https://beta.example.com/",
        capabilities=("shared_tag",),
    )
    reg = FederatedRegistry.from_partners((b, a))  # insertion order swapped
    recs = recommend_handoff("this query has shared_tag in it", registry=reg, max_results=2)
    assert [r.partner_id for r in recs] == ["alpha", "beta"]


def test_recommend_with_custom_registry() -> None:
    """Caller can pass a custom registry override."""
    only = _make_partner(
        partner_id="only_one",
        official_url="https://only.example.com/",
        capabilities=("unique_thing",),
    )
    reg = FederatedRegistry.from_partners((only,))
    recs = recommend_handoff("we need unique_thing here", registry=reg)
    assert len(recs) == 1
    assert recs[0].partner_id == "only_one"


# ---------------------------------------------------------------------------
# Bundle 5: JSON schema parity + data-file shape
# ---------------------------------------------------------------------------


def test_schema_file_exists_and_loads() -> None:
    """schemas/jpcir/federated_partner.schema.json must load as JSON."""
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert raw["title"] == "PartnerMcp"
    assert raw["type"] == "object"
    assert raw["additionalProperties"] is False


def test_schema_required_fields_match_pydantic_model() -> None:
    """JSON schema required[] must match the Pydantic model fields."""
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    expected = {
        "partner_id",
        "name",
        "official_url",
        "mcp_endpoint",
        "mcp_endpoint_status",
        "capabilities",
        "use_when",
    }
    assert set(raw["required"]) == expected
    assert set(PartnerMcp.model_fields.keys()) == expected


def test_data_json_path_exists() -> None:
    """data/federated_partners.json must exist at the repo-root location."""
    assert FEDERATED_PARTNERS_JSON.exists()


def test_data_json_partners_match_partner_ids_constant() -> None:
    """The shipped JSON partners[] must mirror PARTNER_IDS."""
    raw = json.loads(FEDERATED_PARTNERS_JSON.read_text(encoding="utf-8"))
    ids = tuple(p["partner_id"] for p in raw["partners"])
    assert ids == PARTNER_IDS


def test_data_json_partners_each_validate_against_pydantic() -> None:
    """Each row in the shipped JSON validates as PartnerMcp."""
    raw = json.loads(FEDERATED_PARTNERS_JSON.read_text(encoding="utf-8"))
    for row in raw["partners"]:
        PartnerMcp.model_validate(row)  # raises on parity drift


def test_no_legacy_brand_in_module() -> None:
    """Federated_mcp source must not carry legacy brand markers."""
    module_dir = REPO_ROOT / "src" / "jpintel_mcp" / "federated_mcp"
    legacy_brand_en = "zeimu" + "-" + "kaikei" + ".ai"
    legacy_brand_jp = "税務会計AI"
    for py in module_dir.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert legacy_brand_en not in text, py.name
        assert legacy_brand_jp not in text, py.name


def test_no_llm_import_in_module() -> None:
    """Federated_mcp must not import any LLM SDK at runtime."""
    module_dir = REPO_ROOT / "src" / "jpintel_mcp" / "federated_mcp"
    forbidden = (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
        "claude_agent_sdk",
    )
    for py in module_dir.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{py.name} contains forbidden marker: {marker}"
