"""Tests for Dim N anonymized_query surface (Wave 46).

Closes the Wave 46 dim 19 / dim N (2.14/10) gap: PII-redacted
k-anonymity ≥ 5 network query so agents can ask "how did similar
entities fare?" without exposing per-entity data.

Hard constraints exercised:
  * k=5 hard cap enforced at module level (not query-param)
  * PII redact whitelist surfaces only cohort + aggregate fields
  * Audit log captures every call (hashed filter + decision)
  * No LLM SDK import
  * §52 / §47条の2 / §72 / §1 disclaimer parity envelope
  * Redact policy version pinned in response
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_ANONYMIZED = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "anonymized_query.py"


def _import_anonymized_module():
    """Load the anonymized_query module by file path."""
    spec = importlib.util.spec_from_file_location("_anonymized_test_mod", SRC_ANONYMIZED)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_anonymized_test_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Module-load tests
# ---------------------------------------------------------------------------


def test_anonymized_file_exists() -> None:
    """Module file must exist on disk."""
    assert SRC_ANONYMIZED.exists(), (
        "src/jpintel_mcp/api/anonymized_query.py is required to close "
        "dim 19 / dim N REST sub-criterion."
    )
    src = SRC_ANONYMIZED.read_text(encoding="utf-8")
    assert 'router = APIRouter(prefix="/v1/network"' in src
    assert 'tags=["anonymized-query"]' in src


def test_anonymized_no_llm_imports() -> None:
    """anonymized_query.py must NOT import any LLM SDK."""
    src = SRC_ANONYMIZED.read_text(encoding="utf-8")
    banned = (
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
    )
    for needle in banned:
        pattern = rf"^\s*(import|from)\s+{re.escape(needle)}\b"
        assert not re.search(pattern, src, re.MULTILINE), f"LLM SDK import detected: {needle}"


def test_anonymized_disclaimer_present() -> None:
    """Surface must carry the §52 / §47条の2 / §72 / §1 disclaimer."""
    src = SRC_ANONYMIZED.read_text(encoding="utf-8")
    assert "税理士法" in src and "52" in src
    assert "公認会計士法" in src and "47条の2" in src
    assert "弁護士法" in src and "72" in src
    assert "行政書士法" in src and "1" in src


def test_anonymized_k_anonymity_hard_cap_constant() -> None:
    """K_ANONYMITY_MIN must be a module constant, not a query param.

    Per feedback_anonymized_query_pii_redact: k=5 hard cap is enforced
    from day 1 and cannot be lowered at runtime. The cap is a code
    constant; a regression that introduced a `?k=` query param would
    fail this test.
    """
    mod = _import_anonymized_module()
    assert mod.K_ANONYMITY_MIN >= 5, (
        "K_ANONYMITY_MIN must be >= 5 (feedback_anonymized_query_pii_redact)"
    )
    # The constant must NOT appear as a query param default in the file.
    src = SRC_ANONYMIZED.read_text(encoding="utf-8")
    assert "Query(K_ANONYMITY_MIN" not in src
    assert "Query(default=K_ANONYMITY_MIN" not in src
    assert "k_anonymity_min: int =" not in src


# ---------------------------------------------------------------------------
# k-anonymity verify
# ---------------------------------------------------------------------------


def test_k_anonymity_redact_whitelist_blocks_pii() -> None:
    """``redact_response`` strips any field outside the whitelist.

    Even if the substrate accidentally returns houjin_number / address /
    contact, the response shaper must drop those keys.
    """
    mod = _import_anonymized_module()
    filters = {
        "industry_jsic_major": "E",
        "region_code": "13101",
        "size_bucket": "medium",
    }
    # Simulate a substrate row that erroneously includes PII-bearing fields.
    aggregates_with_pii = {
        "cohort_size": 12,
        "top_program_id_anon": "anon_xxxxx",
        "mean_amount_yen": 5_000_000,
        "median_amount_yen": 4_500_000,
        # These PII fields MUST be stripped:
        "houjin_number": "1234567890123",
        "company_name": "株式会社XX",
        "address": "東京都中央区...",
        "contact_email": "ceo@example.jp",
    }
    out = mod.redact_response(filters, aggregates_with_pii)
    # PII fields are dropped at the shaper layer.
    assert "houjin_number" not in out
    assert "company_name" not in out
    assert "address" not in out
    assert "contact_email" not in out
    # Cohort + aggregate fields surface.
    assert out["industry_jsic_major"] == "E"
    assert out["cohort_size"] == 12
    assert out["mean_amount_yen"] == 5_000_000


def test_k_anonymity_audit_log_records_call() -> None:
    """Every call writes one row to the audit log (hashed filter)."""
    mod = _import_anonymized_module()
    snapshot_before = len(mod.get_audit_log_snapshot())
    filters = {"industry_jsic_major": "F"}
    # Direct call to internal audit hook (the REST handler exercises this).
    mod._audit_log_call(filters, cohort_size=10, decision="served")
    snapshot_after = mod.get_audit_log_snapshot()
    assert len(snapshot_after) == snapshot_before + 1
    last = snapshot_after[-1]
    assert last["decision"] == "served"
    assert last["cohort_size"] == 10
    assert last["redact_policy_version"] == mod.REDACT_POLICY_VERSION
    # Filter hash is 16 hex chars (sha256 prefix).
    assert isinstance(last["filter_hash"], str)
    assert len(last["filter_hash"]) == 16
    assert re.match(r"^[0-9a-f]{16}$", last["filter_hash"])


def test_k_anonymity_aggregate_cohort_deterministic() -> None:
    """``aggregate_cohort`` is deterministic: same filter → same cohort."""
    mod = _import_anonymized_module()
    f = {"industry_jsic_major": "E", "region_code": "13101"}
    out_a = mod.aggregate_cohort(f)
    out_b = mod.aggregate_cohort(f)
    assert out_a == out_b
    # Different filters → different cohort sizes (high probability).
    out_c = mod.aggregate_cohort({"industry_jsic_major": "F"})
    # Both non-None and well-formed.
    assert isinstance(out_a["cohort_size"], int)
    assert isinstance(out_c["cohort_size"], int)


def test_k_anonymity_response_whitelist_immutable() -> None:
    """``_RESPONSE_WHITELIST`` must NOT contain any per-entity PII field."""
    mod = _import_anonymized_module()
    whitelist = mod._RESPONSE_WHITELIST
    banned_pii_fields = (
        "houjin_number",
        "company_name",
        "address",
        "phone",
        "contact_email",
        "representative_name",
        "ceo_name",
    )
    for field in banned_pii_fields:
        assert field not in whitelist, f"PII field {field} must not be in response whitelist"


def test_validate_filters_accepts_valid_input() -> None:
    """``_validate_filters`` accepts well-formed cohort filter input."""
    mod = _import_anonymized_module()
    out = mod._validate_filters(
        {
            "industry_jsic_major": "E",
            "region_code": "13101",
            "size_bucket": "small",
        }
    )
    assert out["industry_jsic_major"] == "E"
    assert out["region_code"] == "13101"
    assert out["size_bucket"] == "small"


def test_validate_filters_rejects_bad_industry() -> None:
    """``_validate_filters`` raises on out-of-range industry code."""
    mod = _import_anonymized_module()
    with pytest.raises(ValueError, match=r"industry_jsic_major"):
        mod._validate_filters({"industry_jsic_major": "Z"})
    with pytest.raises(ValueError, match=r"industry_jsic_major"):
        mod._validate_filters({"industry_jsic_major": "EE"})
    with pytest.raises(ValueError, match=r"industry_jsic_major"):
        mod._validate_filters({"industry_jsic_major": ""})


def test_validate_filters_rejects_bad_region() -> None:
    """``_validate_filters`` raises when region_code is not 5-digit."""
    mod = _import_anonymized_module()
    with pytest.raises(ValueError, match=r"region_code"):
        mod._validate_filters({"industry_jsic_major": "E", "region_code": "13"})
    with pytest.raises(ValueError, match=r"region_code"):
        mod._validate_filters({"industry_jsic_major": "E", "region_code": "abc12"})


def test_validate_filters_rejects_bad_size_bucket() -> None:
    """``_validate_filters`` raises when size_bucket is not in enum."""
    mod = _import_anonymized_module()
    with pytest.raises(ValueError, match=r"size_bucket"):
        mod._validate_filters({"industry_jsic_major": "E", "size_bucket": "tiny"})


# ---------------------------------------------------------------------------
# PII strip end-to-end
# ---------------------------------------------------------------------------


def test_pii_strip_end_to_end() -> None:
    """End-to-end shaping: filters → aggregate → redact → no PII leaks.

    Uses the public aggregate_cohort + redact_response pipeline (the
    same one the REST handler calls) and asserts the final response
    dict contains zero PII-like fields.
    """
    mod = _import_anonymized_module()
    filters = {
        "industry_jsic_major": "E",
        "region_code": "13101",
        "size_bucket": "small",
    }
    aggregates = mod.aggregate_cohort(filters)
    out = mod.redact_response(filters, aggregates)

    # Whitelist intersection check.
    for key in out:
        assert key in mod._RESPONSE_WHITELIST or key.startswith("_"), (
            f"unexpected field {key} in response — possible PII leak"
        )

    # No string value in the response should look like a 13-digit
    # houjin_number or 11-digit phone (deep-content PII smoke).
    for value in out.values():
        if isinstance(value, str):
            assert not re.match(r"^\d{13}$", value), f"13-digit houjin-like value leaked: {value}"
            assert not re.match(r"^\d{10,11}$", value), f"phone-like value leaked: {value}"


def test_redact_policy_version_pinned() -> None:
    """REDACT_POLICY_VERSION is a non-empty pinned string."""
    mod = _import_anonymized_module()
    assert isinstance(mod.REDACT_POLICY_VERSION, str)
    assert mod.REDACT_POLICY_VERSION.startswith("v")
    # Semantic-version-ish: vX.Y.Z
    assert re.match(r"^v\d+\.\d+\.\d+$", mod.REDACT_POLICY_VERSION)


# ---------------------------------------------------------------------------
# Wiring sanity: main.py imports the experimental router
# ---------------------------------------------------------------------------


def test_main_py_includes_anonymized_query() -> None:
    """``api/main.py`` must wire the experimental router."""
    main = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "main.py"
    src = main.read_text(encoding="utf-8")
    assert "jpintel_mcp.api.anonymized_query" in src, (
        "main.py must include anonymized_query via _include_experimental_router"
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
