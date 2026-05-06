"""Tests for Tier 1 envelope CS features (P3-M++, dd_v8_08).

Six features (A/B/D/E/F/J) are wired into:
  - src/jpintel_mcp/mcp/autonomath_tools/cs_features.py  (helpers)
  - src/jpintel_mcp/mcp/autonomath_tools/envelope_wrapper.py  (build_envelope
    integration via meta block + error enrichment)
  - src/jpintel_mcp/mcp/autonomath_tools/error_envelope.py  (user_message
    auto-attach in make_error)
  - scripts/cron/predictive_billing_alert.py  (D - billing alert)

We test each helper in isolation AND verify build_envelope round-trips
each field correctly. The opt-out (fields="minimal") MUST drop the meta
block entirely.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

# Ensure src/ is on path for direct test runs.
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.mcp.autonomath_tools.cs_features import (  # noqa: E402
    USER_MESSAGES,
    build_meta,
    compute_billing_alert,
    compute_token_estimate,
    derive_alternative_intents,
    derive_input_warnings,
    derive_suggestions,
    enhance_error_with_retry,
    onboarding_tips_for_age_days,
    user_message_for_error,
)
from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import (  # noqa: E402
    ENVELOPE_API_VERSION,
    build_envelope,
    with_envelope,
)
from jpintel_mcp.mcp.autonomath_tools.error_envelope import make_error  # noqa: E402

# ---------------------------------------------------------------------------
# Feature A — Contextual help
# ---------------------------------------------------------------------------


def test_derive_suggestions_empty_returns_tool_specific():
    s = derive_suggestions("search_tax_incentives", "empty")
    assert isinstance(s, list)
    assert len(s) > 0
    assert len(s) <= 3
    assert all(isinstance(x, str) and len(x) > 0 for x in s)


def test_derive_suggestions_rich_returns_empty():
    assert derive_suggestions("search_tax_incentives", "rich") == []


def test_derive_suggestions_unknown_tool_falls_back():
    s = derive_suggestions("unknown_tool_xyz", "empty")
    assert len(s) > 0


def test_derive_alternative_intents_keyword_match():
    out = derive_alternative_intents(
        "search_tax_incentives",
        "税額控除に関する条文",
        status="empty",
    )
    # Tax + law keywords should both fire something
    assert len(out) >= 1
    assert any("税制" in s or "法令" in s for s in out)


def test_derive_alternative_intents_rich_returns_empty():
    out = derive_alternative_intents(
        "x",
        "税制 control",
        status="rich",
    )
    assert out == []


def test_derive_alternative_intents_dedupes_keywords():
    """Same query that triggers multiple regexes should still dedupe."""
    out = derive_alternative_intents(
        "x",
        "補助金 助成 採択 採択率",  # 補助/助成 + 採択/採択率
        status="empty",
    )
    # At most 3 entries; no duplicates.
    assert len(out) == len(set(out))
    assert len(out) <= 3


def test_derive_input_warnings_year_below_coverage():
    w = derive_input_warnings(
        "search_tax_incentives",
        {"target_year": 2010},
    )
    assert len(w) == 1
    assert "範囲外" in w[0]


def test_derive_input_warnings_year_above_coverage():
    w = derive_input_warnings(
        "search_tax_incentives",
        {"fy": 2030},
    )
    assert len(w) == 1


def test_derive_input_warnings_limit_too_high():
    w = derive_input_warnings("any", {"limit": 500})
    assert any("limit" in s for s in w)


def test_derive_input_warnings_no_issues():
    w = derive_input_warnings(
        "search_tax_incentives",
        {"target_year": 2024, "limit": 20},
    )
    assert w == []


# ---------------------------------------------------------------------------
# Feature B — Token estimate / wall_time
# ---------------------------------------------------------------------------


def test_compute_token_estimate_safe_side():
    # 100 ASCII chars = 100 bytes; byte/3 -> ~34 tokens.
    payload = "a" * 100
    est = compute_token_estimate(payload)
    assert est >= 30
    assert est <= 50  # safe side, not absurdly inflated


def test_compute_token_estimate_dict():
    est = compute_token_estimate({"results": [{"name": "ものづくり補助金"}]})
    assert est > 0


def test_compute_token_estimate_handles_unserializable():
    # `set` is not JSON-serializable; must not raise.
    class Weird:
        pass

    est = compute_token_estimate(Weird())
    assert est > 0


# ---------------------------------------------------------------------------
# Feature F — Onboarding nudge
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("day", [0, 1, 3, 7])
def test_onboarding_tips_anchor_days_have_message(day: int):
    tips = onboarding_tips_for_age_days(day)
    assert len(tips) >= 1
    assert all(isinstance(t, str) for t in tips)


@pytest.mark.parametrize("day", [2, 4, 5, 6, 8, 30, 100])
def test_onboarding_tips_off_anchor_days_empty(day: int):
    assert onboarding_tips_for_age_days(day) == []


def test_onboarding_tips_none_age_returns_empty():
    assert onboarding_tips_for_age_days(None) == []


# ---------------------------------------------------------------------------
# Feature J — Plain-Japanese error messages
# ---------------------------------------------------------------------------


def test_user_message_known_codes_all_have_messages():
    """Every code in error_envelope.ERROR_CODES has a Japanese message."""
    from jpintel_mcp.mcp.autonomath_tools.error_envelope import ERROR_CODES

    for code in ERROR_CODES:
        msg = user_message_for_error(code)
        assert msg, f"missing user_message for {code}"
        # Contains at least one CJK char (rough sanity)
        assert any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in msg)


def test_user_message_http_status_fallback():
    msg = user_message_for_error(http_status=429)
    assert "1 分" in msg or "リトライ" in msg


def test_user_message_unknown_falls_back_to_generic():
    msg = user_message_for_error("totally_made_up_code")
    assert msg
    msg2 = user_message_for_error(http_status=499)
    assert msg2  # 4xx generic


def test_make_error_attaches_user_message():
    """make_error() auto-attaches a Japanese user_message for every
    canonical ErrorCode. (rate_limit_exceeded is HTTP-layer-only and
    not in the closed enum, but db_locked is.)"""
    payload = make_error("db_locked", "DB busy")
    assert "user_message" in payload["error"]
    assert payload["error"]["user_message"] == USER_MESSAGES["db_locked"]


# ---------------------------------------------------------------------------
# Feature E — Intelligent retry suggestion
# ---------------------------------------------------------------------------


def test_enhance_error_with_retry_rate_limit():
    err = {"code": "rate_limit_exceeded", "message": "x"}
    out = enhance_error_with_retry(err)
    assert out["retry_after"] == 60
    assert out["user_message"]


def test_enhance_error_with_retry_db_unavailable_has_alternate():
    err = {"code": "db_unavailable", "message": "boom"}
    out = enhance_error_with_retry(err)
    assert out["retry_after"] >= 1
    assert out["alternate_endpoint"].startswith("https://")


def test_enhance_error_with_retry_503_status():
    err = {"code": "internal", "message": "x"}
    out = enhance_error_with_retry(err, http_status=503)
    # internal also gets retry_after baseline=15
    assert "retry_after" in out


def test_enhance_error_does_not_overwrite_existing_keys():
    err = {
        "code": "rate_limit_exceeded",
        "retry_after": 999,
        "user_message": "custom",
    }
    out = enhance_error_with_retry(err)
    assert out["retry_after"] == 999
    assert out["user_message"] == "custom"


# ---------------------------------------------------------------------------
# Feature D — Predictive billing alert
# ---------------------------------------------------------------------------


def test_compute_billing_alert_below_floor_returns_none():
    alert = compute_billing_alert(
        current_month_count=50,
        rolling_avg_count=10,
    )
    assert alert is None


def test_compute_billing_alert_no_history_returns_none():
    alert = compute_billing_alert(
        current_month_count=500,
        rolling_avg_count=0,
    )
    assert alert is None


def test_compute_billing_alert_below_threshold_returns_none():
    alert = compute_billing_alert(
        current_month_count=200,
        rolling_avg_count=100,  # 2x, below default 3x
    )
    assert alert is None


def test_compute_billing_alert_triggers_at_threshold():
    alert = compute_billing_alert(
        current_month_count=500,
        rolling_avg_count=100,  # 5x
    )
    assert alert is not None
    assert alert["multiplier"] == 5.0
    assert alert["current"] == 500
    assert alert["recommended_action"]


# ---------------------------------------------------------------------------
# build_meta — aggregate behavior
# ---------------------------------------------------------------------------


def test_build_meta_minimal_returns_none():
    out = build_meta(
        tool_name="search_tax_incentives",
        status="empty",
        query_echo="x",
        latency_ms=1.0,
        results=[],
        fields="minimal",
    )
    assert out is None


def test_build_meta_standard_includes_all_fields():
    out = build_meta(
        tool_name="search_tax_incentives",
        status="empty",
        query_echo="税額控除",
        latency_ms=42.5,
        results=[],
        kwargs={"target_year": 2030, "limit": 10},
    )
    assert out is not None
    # Token + wall_time always present
    assert "token_estimate" in out
    assert "wall_time_ms" in out
    assert out["wall_time_ms"] == 42.5
    # Suggestions fire on empty
    assert "suggestions" in out
    # Input warnings fire because year > coverage
    assert "input_warnings" in out
    assert any("範囲外" in w for w in out["input_warnings"])
    # Alternative intents from "税" keyword
    assert "alternative_intents" in out


def test_build_meta_rich_drops_empty_lists():
    """When status='rich', suggestions/alt_intents should be empty and
    therefore omitted from the meta dict (compactness)."""
    out = build_meta(
        tool_name="search_tax_incentives",
        status="rich",
        query_echo="x",
        latency_ms=1.0,
        results=[{"id": 1}, {"id": 2}, {"id": 3}],
    )
    assert out is not None
    assert "suggestions" not in out
    assert "alternative_intents" not in out
    # Numeric fields still present
    assert "token_estimate" in out
    assert "wall_time_ms" in out


def test_build_meta_keys_sorted_alphabetically():
    out = build_meta(
        tool_name="search_tax_incentives",
        status="empty",
        query_echo="補助",
        latency_ms=1.0,
        results=[],
    )
    assert out is not None
    keys = list(out.keys())
    assert keys == sorted(keys)


def test_build_meta_onboarding_tips_d0():
    """A freshly issued key (created seconds ago) must produce D+0 tip."""
    now_iso = datetime.now(UTC).isoformat()
    out = build_meta(
        tool_name="list_open_programs",
        status="rich",
        query_echo="",
        latency_ms=1.0,
        results=[{"id": 1}, {"id": 2}, {"id": 3}],
        api_key_created_at=now_iso,
    )
    assert out is not None
    assert "tips" in out
    assert any("ようこそ" in t for t in out["tips"])


def test_build_meta_onboarding_tips_d2_silent():
    """D+2 is NOT an anchor day — no tips."""
    two_days_ago = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    out = build_meta(
        tool_name="list_open_programs",
        status="rich",
        query_echo="",
        latency_ms=1.0,
        results=[{"id": 1}, {"id": 2}, {"id": 3}],
        api_key_created_at=two_days_ago,
    )
    assert out is not None
    assert "tips" not in out  # empty list dropped


def test_build_meta_onboarding_handles_bad_iso():
    out = build_meta(
        tool_name="list_open_programs",
        status="rich",
        query_echo="",
        latency_ms=1.0,
        results=[{"id": 1}, {"id": 2}, {"id": 3}],
        api_key_created_at="not-a-date",
    )
    assert out is not None
    # No crash; tips silently missing.
    assert "tips" not in out


# ---------------------------------------------------------------------------
# build_envelope integration
# ---------------------------------------------------------------------------


def test_build_envelope_carries_meta_block_by_default():
    env = build_envelope(
        tool_name="search_tax_incentives",
        results=[],
        query_echo="税",
        latency_ms=10.0,
    )
    assert "meta" in env
    assert isinstance(env["meta"], dict)


def test_build_envelope_minimal_drops_meta():
    env = build_envelope(
        tool_name="search_tax_incentives",
        results=[],
        query_echo="x",
        latency_ms=10.0,
        fields="minimal",
    )
    assert "meta" not in env


def test_build_envelope_error_gets_user_message_and_retry():
    err = {"code": "rate_limit_exceeded", "message": "throttled", "severity": "hard"}
    env = build_envelope(
        tool_name="search_tax_incentives",
        results=[],
        latency_ms=1.0,
        error=err,
    )
    assert env["status"] == "error"
    assert env["error"]["user_message"]
    assert env["error"]["retry_after"] == 60


def test_build_envelope_error_503_gets_alternate_endpoint():
    err = {"code": "internal", "message": "x", "severity": "hard"}
    env = build_envelope(
        tool_name="search_tax_incentives",
        results=[],
        latency_ms=1.0,
        error=err,
        http_status=503,
    )
    assert env["error"]["alternate_endpoint"].startswith("https://")


def test_build_envelope_api_version_bumped():
    env = build_envelope(
        tool_name="search_tax_incentives",
        results=[],
        latency_ms=1.0,
    )
    # 1.1 reflects the additive meta block.
    assert env["api_version"] == ENVELOPE_API_VERSION
    assert env["api_version"] == "1.1"


def test_build_envelope_legacy_fields_preserved():
    """Backward compat: legacy clients reading total/limit/offset/hint
    must still see those fields exactly as before."""
    env = build_envelope(
        tool_name="search_tax_incentives",
        results=[{"id": 1}],
        latency_ms=1.0,
        legacy_extras={"total": 1, "limit": 20, "offset": 0, "hint": "ok"},
    )
    assert env["total"] == 1
    assert env["limit"] == 20
    assert env["offset"] == 0
    assert env["hint"] == "ok"
    assert env["status"] == "sparse"


# ---------------------------------------------------------------------------
# with_envelope decorator integration
# ---------------------------------------------------------------------------


def _fake_tool_returns_results(*, query: str | None = None, limit: int = 5):
    return {"results": [{"id": 1, "name": query}], "total": 1, "limit": limit}


def _fake_tool_returns_empty(*, query: str | None = None, limit: int = 5):
    return {"results": [], "total": 0, "limit": limit}


def test_with_envelope_minimal_strips_meta():
    wrapped = with_envelope("fake_search", query_arg="query")(
        _fake_tool_returns_results,
    )
    out = wrapped(query="税", __envelope_fields__="minimal")
    assert "meta" not in out


def test_with_envelope_default_includes_meta():
    wrapped = with_envelope("fake_search", query_arg="query")(
        _fake_tool_returns_results,
    )
    out = wrapped(query="税")
    assert "meta" in out


def test_with_envelope_strips_internal_kwargs_from_tool():
    """The wrapped tool must NOT see __envelope_fields__ or
    __api_key_created_at__ in its kwargs."""
    captured: dict[str, Any] = {}

    def fake(*, query: str | None = None, limit: int = 5):
        captured["kwargs"] = {"query": query, "limit": limit}
        return {"results": []}

    wrapped = with_envelope("fake", query_arg="query")(fake)
    wrapped(
        query="x",
        limit=3,
        __envelope_fields__="minimal",
        __api_key_created_at__=datetime.now(UTC).isoformat(),
    )
    # If our wrapper leaked control-plane args, fake() would have raised
    # TypeError. Reaching here means the strip worked.
    assert captured["kwargs"]["query"] == "x"
    assert captured["kwargs"]["limit"] == 3


def test_with_envelope_empty_status_has_suggestions_in_meta():
    wrapped = with_envelope("search_tax_incentives", query_arg="query")(
        _fake_tool_returns_empty,
    )
    out = wrapped(query="税額控除")
    assert "meta" in out
    assert "suggestions" in out["meta"]
    assert "alternative_intents" in out["meta"]


def test_with_envelope_d0_onboarding_tips_visible():
    wrapped = with_envelope("list_open_programs", query_arg="query")(
        _fake_tool_returns_results,
    )
    now_iso = datetime.now(UTC).isoformat()
    out = wrapped(query="x", __api_key_created_at__=now_iso)
    assert "meta" in out
    assert "tips" in out["meta"]
