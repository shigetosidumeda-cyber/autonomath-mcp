"""DD1 12-partner federated MCP expansion — unit tests.

Covers the additive DD1 surface delivered on 2026-05-17:

  * :func:`load_dd1_registry_12` — 12 curated partner rows.
  * :func:`recommend_handoff_12` — gap-keyword match against 12 partners
    (6 base + 6 expansion).
  * Wire-shape parity between the JSON, YAML, and ``.well-known``
    discovery artifact.
  * Non-regression vs the Wave 51 dim R 6-partner contract.

These tests do NOT exercise the SQLite ``am_federated_mcp_partner``
storage layer — that path is covered by
``tests/test_dim_r_federated_mcp.py``. They also do NOT replace
``tests/test_federated_mcp.py``; the base-6 contract must continue to
PASS independently.

Hard rules
----------
* No network call. No LLM SDK import. No HTTP.
* https only for every URL. Pydantic-validated on load.
* No aggregator MCP endpoints.
* No self-reference (jpcite / jpintel / autonomath).
"""

from __future__ import annotations

import json
import pathlib

import pytest
from pydantic import ValidationError

from jpintel_mcp.federated_mcp import (
    PARTNER_IDS as BASE_6_PARTNER_IDS,
)
from jpintel_mcp.federated_mcp import (
    FederatedRegistry,
    PartnerMcp,
)
from jpintel_mcp.federated_mcp.registry_12 import (
    DD1_BASE_6,
    DD1_EXPANSION_6,
    DD1_FEDERATED_PARTNERS_JSON,
    DD1_FEDERATED_PARTNERS_YAML,
    DD1_PARTNER_ALIASES_12,
    DD1_PARTNER_ALIASES_EXPANSION_6,
    DD1_PARTNER_IDS_12,
    load_dd1_registry_12,
    recommend_handoff_12,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
WELL_KNOWN_12 = REPO_ROOT / "site" / ".well-known" / "jpcite-federated-mcp-12-partners.json"
SCHEMA_PATH = REPO_ROOT / "schemas" / "jpcir" / "federated_partner.schema.json"


# ---------------------------------------------------------------------------
# Bundle 1: 12-partner registry shape
# ---------------------------------------------------------------------------


def test_dd1_registry_12_loads_twelve_partners() -> None:
    """The DD1 JSON must contain exactly the 12 curated partners."""
    reg = load_dd1_registry_12()
    assert len(reg) == 12
    assert reg.partner_ids == DD1_PARTNER_IDS_12


def test_dd1_registry_12_partner_ids_are_canonical_set() -> None:
    """The 12 partners are exactly the base 6 ∪ expansion 6."""
    reg = load_dd1_registry_12()
    expected = set(DD1_BASE_6) | set(DD1_EXPANSION_6)
    assert set(reg.partner_ids) == expected
    assert len(expected) == 12  # the two sets must be disjoint


def test_dd1_registry_12_partner_ids_are_alphabetical() -> None:
    """Canonical order is alphabetical for wire-shape stability."""
    reg = load_dd1_registry_12()
    ids = reg.partner_ids
    assert list(ids) == sorted(ids)


def test_dd1_registry_12_is_cached_singleton() -> None:
    """Repeated calls return the same instance (no I/O on hot path)."""
    reg_a = load_dd1_registry_12()
    reg_b = load_dd1_registry_12()
    assert reg_a is reg_b


def test_dd1_registry_12_no_self_reference() -> None:
    """jpcite / jpintel / autonomath must never appear in the roster."""
    reg = load_dd1_registry_12()
    for p in reg.partners:
        assert p.partner_id not in {"jpcite", "jpintel", "autonomath"}


def test_dd1_registry_12_no_aggregator_endpoints() -> None:
    """No third-party aggregator hosts allowed in mcp_endpoint."""
    reg = load_dd1_registry_12()
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


def test_dd1_registry_12_all_urls_https() -> None:
    """Every official_url and non-null mcp_endpoint must be https."""
    reg = load_dd1_registry_12()
    for p in reg.partners:
        assert str(p.official_url).startswith("https://"), p.partner_id
        if p.mcp_endpoint is not None:
            assert str(p.mcp_endpoint).startswith("https://"), p.partner_id


def test_dd1_registry_12_official_status_implies_mcp_endpoint() -> None:
    """Partners flagged ``official`` must carry an https MCP endpoint."""
    reg = load_dd1_registry_12()
    for p in reg.partners:
        if p.mcp_endpoint_status == "official":
            assert p.mcp_endpoint is not None
        else:
            assert p.mcp_endpoint is None


# ---------------------------------------------------------------------------
# Bundle 2: non-regression vs Wave 51 dim R base-6 contract
# ---------------------------------------------------------------------------


def test_dd1_preserves_wave51_base_6() -> None:
    """The 6 Wave 51 dim R base partners must still appear in the 12-roster."""
    assert set(DD1_BASE_6) == set(BASE_6_PARTNER_IDS)
    reg_12 = load_dd1_registry_12()
    for slug in BASE_6_PARTNER_IDS:
        assert slug in reg_12, f"base partner {slug} missing from DD1 12-roster"


def test_dd1_expansion_6_is_disjoint_from_base_6() -> None:
    """The 6 expansion partners must not collide with the base 6 slugs."""
    assert set(DD1_BASE_6).isdisjoint(set(DD1_EXPANSION_6))


# ---------------------------------------------------------------------------
# Bundle 3: gap-keyword recommendation (12-partner matcher)
# ---------------------------------------------------------------------------


def test_recommend_12_stripe_billing() -> None:
    """English 'stripe subscription' gap → stripe surfaces first."""
    recs = recommend_handoff_12(
        "reconcile the stripe subscription invoice for the client",
        max_results=3,
    )
    assert recs
    assert recs[0].partner_id == "stripe"


def test_recommend_12_salesforce_crm() -> None:
    """English 'salesforce opportunity' gap → salesforce wins."""
    recs = recommend_handoff_12(
        "pull the salesforce opportunity record for the lead", max_results=3
    )
    assert recs
    assert recs[0].partner_id == "salesforce"


def test_recommend_12_ms_teams_chat() -> None:
    """English 'microsoft teams' gap → ms_teams wins."""
    recs = recommend_handoff_12("look up the microsoft teams channel message", max_results=3)
    assert recs
    assert recs[0].partner_id == "ms_teams"


def test_recommend_12_google_drive_doc() -> None:
    """English 'google drive spreadsheet' gap → google_drive wins."""
    recs = recommend_handoff_12(
        "fetch the google drive spreadsheet from the user's drive", max_results=3
    )
    assert recs
    assert recs[0].partner_id == "google_drive"


def test_recommend_12_aws_bedrock_runtime() -> None:
    """English 'aws bedrock' gap → aws_bedrock wins."""
    recs = recommend_handoff_12("delegate this to an aws bedrock agent runtime", max_results=3)
    assert recs
    assert recs[0].partner_id == "aws_bedrock"


def test_recommend_12_claude_ai_cross_promo() -> None:
    """English 'claude.ai' gap → claude_ai wins."""
    recs = recommend_handoff_12("wire jpcite into claude.ai as an mcp_client", max_results=3)
    assert recs
    assert recs[0].partner_id == "claude_ai"


def test_recommend_12_japanese_stripe_alias() -> None:
    """Japanese 決済 alias → stripe wins."""
    recs = recommend_handoff_12(
        "クライアントの決済とサブスクリプションの請求を確認したい", max_results=3
    )
    assert recs
    assert recs[0].partner_id == "stripe"


def test_recommend_12_japanese_crm_alias() -> None:
    """Japanese 顧客管理 / 商談 alias → salesforce wins."""
    recs = recommend_handoff_12("顧客管理の商談パイプラインをsalesforceで確認したい", max_results=3)
    assert recs
    assert recs[0].partner_id == "salesforce"


def test_recommend_12_base_partner_still_works() -> None:
    """Wave 51 dim R base partners still resolve correctly (regression)."""
    recs = recommend_handoff_12("look up the pull request title on github", max_results=3)
    assert recs
    assert recs[0].partner_id == "github"


def test_recommend_12_never_returns_self_reference() -> None:
    """recommend_handoff_12 never surfaces jpcite / jpintel / autonomath."""
    recs = recommend_handoff_12(
        "invoice github linear notion slack accounting payroll stripe salesforce",
        max_results=12,
    )
    for r in recs:
        assert r.partner_id not in {"jpcite", "jpintel", "autonomath"}


def test_recommend_12_empty_query_raises() -> None:
    """Empty / whitespace query raises ValueError."""
    for bad in ("", "  ", "\n\t"):
        with pytest.raises(ValueError):
            recommend_handoff_12(bad)


def test_recommend_12_invalid_max_results_raises() -> None:
    """max_results < 1 raises ValueError."""
    with pytest.raises(ValueError):
        recommend_handoff_12("anything", max_results=0)


def test_recommend_12_max_results_caps_output() -> None:
    """max_results upper-bounds the returned tuple size (12-partner case)."""
    recs = recommend_handoff_12(
        "stripe salesforce ms_teams google_drive aws_bedrock claude.ai",
        max_results=3,
    )
    assert len(recs) <= 3


def test_recommend_12_unrelated_query_returns_empty() -> None:
    """A gap unrelated to any partner returns an empty tuple."""
    recs = recommend_handoff_12("quantum-mechanics nonsense baz qux", max_results=3)
    assert recs == ()


# ---------------------------------------------------------------------------
# Bundle 4: alias-map shape
# ---------------------------------------------------------------------------


def test_dd1_alias_map_12_covers_all_12_partners() -> None:
    """Every one of the 12 partners must have at least one alias entry."""
    for slug in DD1_PARTNER_IDS_12:
        assert slug in DD1_PARTNER_ALIASES_12, slug
        assert len(DD1_PARTNER_ALIASES_12[slug]) > 0, slug


def test_dd1_alias_map_expansion_covers_expansion_6() -> None:
    """The expansion alias map must cover exactly the 6 expansion partners."""
    assert set(DD1_PARTNER_ALIASES_EXPANSION_6.keys()) == set(DD1_EXPANSION_6)


# ---------------------------------------------------------------------------
# Bundle 5: data file shape (JSON + YAML companion)
# ---------------------------------------------------------------------------


def test_dd1_canonical_json_exists() -> None:
    """data/federated_partners_12.json must exist at the documented path."""
    assert DD1_FEDERATED_PARTNERS_JSON.exists()


def test_dd1_canonical_json_partners_match_partner_ids_constant() -> None:
    """The DD1 JSON partners[] must mirror DD1_PARTNER_IDS_12."""
    raw = json.loads(DD1_FEDERATED_PARTNERS_JSON.read_text(encoding="utf-8"))
    ids = tuple(p["partner_id"] for p in raw["partners"])
    assert ids == DD1_PARTNER_IDS_12
    assert raw["partner_count"] == 12


def test_dd1_canonical_json_each_row_validates() -> None:
    """Each row in the DD1 JSON validates as PartnerMcp."""
    raw = json.loads(DD1_FEDERATED_PARTNERS_JSON.read_text(encoding="utf-8"))
    for row in raw["partners"]:
        PartnerMcp.model_validate(row)


def test_dd1_yaml_companion_exists() -> None:
    """data/federated_mcp_partners.yaml must exist alongside the JSON."""
    assert DD1_FEDERATED_PARTNERS_YAML.exists()


def test_dd1_yaml_partner_count_marker() -> None:
    """The YAML must declare partner_count: 12 to match the JSON."""
    text = DD1_FEDERATED_PARTNERS_YAML.read_text(encoding="utf-8")
    assert "partner_count: 12" in text


def test_dd1_yaml_lists_each_partner_id() -> None:
    """Every DD1_PARTNER_IDS_12 slug must appear in the YAML body."""
    text = DD1_FEDERATED_PARTNERS_YAML.read_text(encoding="utf-8")
    for slug in DD1_PARTNER_IDS_12:
        assert f"partner_id: {slug}" in text, slug


# ---------------------------------------------------------------------------
# Bundle 6: .well-known discovery artifact
# ---------------------------------------------------------------------------


def test_dd1_well_known_exists() -> None:
    """The DD1 .well-known discovery JSON must exist."""
    assert WELL_KNOWN_12.exists()


def test_dd1_well_known_partner_count_and_ids() -> None:
    """The .well-known JSON must declare 12 partners with the canonical ids."""
    raw = json.loads(WELL_KNOWN_12.read_text(encoding="utf-8"))
    assert raw["partner_count"] == 12
    ids = tuple(p["partner_id"] for p in raw["partners"])
    assert ids == DD1_PARTNER_IDS_12


def test_dd1_well_known_interop_policy_enforces_first_party() -> None:
    """Interop policy must forbid LLM inference, aggregators, self-reference."""
    raw = json.loads(WELL_KNOWN_12.read_text(encoding="utf-8"))
    policy = raw["interop_policy"]
    assert policy["llm_inference_at_runtime"] is False
    assert policy["aggregator_endpoints_allowed"] is False
    assert policy["self_reference_allowed"] is False


def test_dd1_well_known_all_urls_https() -> None:
    """Every official_url + mcp_server_url in the .well-known is https."""
    raw = json.loads(WELL_KNOWN_12.read_text(encoding="utf-8"))
    for p in raw["partners"]:
        assert p["official_url"].startswith("https://"), p["partner_id"]
        if p["mcp_server_url"] is not None:
            assert p["mcp_server_url"].startswith("https://"), p["partner_id"]


def test_dd1_well_known_each_row_pydantic_compatible() -> None:
    """Each .well-known partner row must Pydantic-validate as PartnerMcp.

    Maps the .well-known shape (which carries discovery_priority + tier
    + category metadata) onto the PartnerMcp core fields and ensures
    the core shape is still valid.
    """
    raw = json.loads(WELL_KNOWN_12.read_text(encoding="utf-8"))
    for p in raw["partners"]:
        core = {
            "partner_id": p["partner_id"],
            "name": p["name"],
            "official_url": p["official_url"],
            "mcp_endpoint": p["mcp_server_url"],
            "mcp_endpoint_status": p["mcp_endpoint_status"],
            "capabilities": p["capabilities"],
            "use_when": p["use_when"],
        }
        PartnerMcp.model_validate(core)


# ---------------------------------------------------------------------------
# Bundle 7: hardening — no LLM / legacy brand
# ---------------------------------------------------------------------------


def test_dd1_registry_12_module_has_no_llm_import() -> None:
    """registry_12.py must not import any LLM SDK at runtime."""
    py = REPO_ROOT / "src" / "jpintel_mcp" / "federated_mcp" / "registry_12.py"
    text = py.read_text(encoding="utf-8")
    forbidden = (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
        "claude_agent_sdk",
    )
    for marker in forbidden:
        assert marker not in text, f"registry_12.py contains forbidden marker: {marker}"


def test_dd1_registry_12_module_has_no_legacy_brand() -> None:
    """registry_12.py must not carry legacy brand markers."""
    py = REPO_ROOT / "src" / "jpintel_mcp" / "federated_mcp" / "registry_12.py"
    text = py.read_text(encoding="utf-8")
    legacy_brand_en = "zeimu" + "-" + "kaikei" + ".ai"
    legacy_brand_jp = "税務会計AI"
    assert legacy_brand_en not in text
    assert legacy_brand_jp not in text


# ---------------------------------------------------------------------------
# Bundle 8: schema parity with PartnerMcp
# ---------------------------------------------------------------------------


def test_dd1_schema_required_fields_unchanged() -> None:
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


def test_dd1_partner_rejects_invalid_partner_id() -> None:
    """Pydantic must still reject malformed partner_id slugs (regression)."""
    for bad in ("AWS_BEDROCK", "1stripe", "ms-teams", "google drive", ""):
        with pytest.raises(ValidationError):
            PartnerMcp(
                partner_id=bad,
                name="x",
                official_url="https://example.com/",  # type: ignore[arg-type]
                mcp_endpoint=None,  # type: ignore[arg-type]
                mcp_endpoint_status="none_official",
                capabilities=("foo",),
                use_when="x",
            )


def test_dd1_partner_rejects_non_https_official_url() -> None:
    """official_url must still be https on new expansion rows."""
    with pytest.raises(ValidationError):
        PartnerMcp(
            partner_id="stripe",
            name="Stripe",
            official_url="http://docs.stripe.com/mcp",  # type: ignore[arg-type]
            mcp_endpoint=None,  # type: ignore[arg-type]
            mcp_endpoint_status="none_official",
            capabilities=("billing",),
            use_when="x",
        )


# ---------------------------------------------------------------------------
# Bundle 9: registry injection (custom shortlist)
# ---------------------------------------------------------------------------


def test_recommend_12_with_custom_registry() -> None:
    """Caller can pass a custom registry override even for the 12-matcher."""
    only = PartnerMcp(
        partner_id="only_one",
        name="Only",
        official_url="https://only.example.com/",  # type: ignore[arg-type]
        mcp_endpoint=None,  # type: ignore[arg-type]
        mcp_endpoint_status="none_official",
        capabilities=("unique_thing",),
        use_when="x",
    )
    reg = FederatedRegistry.from_partners((only,))
    recs = recommend_handoff_12("we need unique_thing here", registry=reg)
    assert len(recs) == 1
    assert recs[0].partner_id == "only_one"
