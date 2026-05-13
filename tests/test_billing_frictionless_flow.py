"""Wave 48 tick#2: frictionless billing funnel (pricing + onboarding) tests.

Verifies the "ユーザーからの課金導線ノンフリクション、迷子ゼロ" deliverable:

    1. site/onboarding.html exists and contains a linear 4-step wizard
       (free -> signup -> topup -> use) with the documented payment rails.
    2. site/assets/billing_progress.js exposes the 4 STEPS and a 30s idle
       hint, and is referenced by pricing.html and onboarding.html.
    3. pricing.html has a "¥0 から始められる" frictionless callout near the
       hero and a billing_progress mount target.
    4. Breadcrumb chain home -> pricing -> ... is present on onboarding.
    5. No tier hierarchy / SaaS-UI proposal words leaked in
       (feedback_keep_it_simple / feedback_autonomath_no_ui).
    6. No legacy brand strings leaked.

The test is intentionally offline / read-only — no LLM API, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PRICING_PATH = REPO_ROOT / "site" / "pricing.html"
ONBOARDING_PATH = REPO_ROOT / "site" / "onboarding.html"
PROGRESS_JS_PATH = REPO_ROOT / "site" / "assets" / "billing_progress.js"


# 4-step linear flow: each entry is (step id, JA label fragment, primary href).
EXPECTED_STEPS: list[tuple[str, str, str]] = [
    ("free", "無料で試す", "/playground.html"),
    ("signup", "サインイン", "/login.html"),
    ("topup", "topup", "/dashboard.html#billing-section"),
    ("use", "API", "/dashboard.html"),
]


@pytest.fixture(scope="module")
def pricing_html() -> str:
    return PRICING_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def onboarding_html() -> str:
    return ONBOARDING_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def progress_js() -> str:
    return PROGRESS_JS_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Files exist with non-trivial bodies
# ---------------------------------------------------------------------------


def test_onboarding_page_exists() -> None:
    assert ONBOARDING_PATH.exists(), "site/onboarding.html must exist"
    assert ONBOARDING_PATH.stat().st_size > 3000, "onboarding.html should be >3 KB"


def test_progress_js_exists() -> None:
    assert PROGRESS_JS_PATH.exists(), "site/assets/billing_progress.js must exist"
    assert PROGRESS_JS_PATH.stat().st_size > 1500, "progress JS should be >1.5 KB"


# ---------------------------------------------------------------------------
# 2. 4-step linear chain present (free -> signup -> topup -> use)
# ---------------------------------------------------------------------------


def test_onboarding_has_four_steps(onboarding_html: str) -> None:
    for step_id, label_fragment, href_fragment in EXPECTED_STEPS:
        marker = f'data-step-id="{step_id}"'
        assert marker in onboarding_html, f"missing step block: {marker}"
        assert label_fragment in onboarding_html, (
            f"missing label fragment for step '{step_id}': {label_fragment}"
        )
        assert href_fragment in onboarding_html, (
            f"missing primary CTA href for step '{step_id}': {href_fragment}"
        )


def test_onboarding_step_order_is_linear(onboarding_html: str) -> None:
    """Steps must appear in the documented order (free -> signup -> topup -> use)."""
    positions = []
    for step_id, _label, _href in EXPECTED_STEPS:
        idx = onboarding_html.find(f'data-step-id="{step_id}"')
        assert idx >= 0, f"step '{step_id}' missing in HTML"
        positions.append(idx)
    assert positions == sorted(positions), f"steps appear out of order: {positions}"


def test_onboarding_has_progress_bar(onboarding_html: str) -> None:
    assert 'role="progressbar"' in onboarding_html
    assert 'aria-valuemax="4"' in onboarding_html
    assert "ob-progress-fill" in onboarding_html


def test_onboarding_has_payment_rails(onboarding_html: str) -> None:
    """3 payment rails (Credit Wallet, x402, Stripe) all advertised."""
    for rail in ("Credit Wallet", "x402", "Stripe"):
        assert rail in onboarding_html, f"missing payment rail mention: {rail}"


def test_onboarding_has_skip_optional(onboarding_html: str) -> None:
    """Each non-final step provides an in-flow skip link (sub-task 6)."""
    skip_markers = re.findall(r'data-skip="step-\d"', onboarding_html)
    assert len(skip_markers) >= 3, f"expected >=3 skip links, found {len(skip_markers)}"


def test_onboarding_has_cost_saving_reminders(onboarding_html: str) -> None:
    """Each step body must include a ob-saving block (cost saving reminder)."""
    occurrences = onboarding_html.count('class="ob-saving"')
    assert occurrences >= 4, f"expected >=4 cost saving callouts, found {occurrences}"


# ---------------------------------------------------------------------------
# 3. Progress JS exposes the 4-step model + idle hint
# ---------------------------------------------------------------------------


def test_progress_js_defines_four_steps(progress_js: str) -> None:
    for step_id, _label, _href in EXPECTED_STEPS:
        assert f'id: "{step_id}"' in progress_js, f"billing_progress.js missing step id: {step_id}"


def test_progress_js_preserves_billing_payment_step_aliases(progress_js: str) -> None:
    assert "normalizeStepId" in progress_js
    assert 'id === "billing" || id === "payment"' in progress_js
    assert 'return "topup"' in progress_js


def test_progress_js_has_idle_detection(progress_js: str) -> None:
    assert "IDLE_MS" in progress_js, "missing IDLE_MS constant"
    assert "30000" in progress_js, "30s idle threshold must be 30000"
    assert "showIdleHint" in progress_js, "missing idle-hint modal function"


def test_progress_js_exposes_global(progress_js: str) -> None:
    assert "window.jpciteBillingProgress" in progress_js
    assert "mount" in progress_js


def test_progress_js_has_no_external_deps(progress_js: str) -> None:
    """Anti-pattern guard: no LLM-API or 3rd-party SDK import (feedback_no_operator_llm_api)."""
    forbidden = [
        "anthropic",
        "openai",
        "@anthropic",
        "import {",  # ESM static import — script must be classic script
    ]
    lowered = progress_js.lower()
    for token in forbidden:
        assert token not in lowered, f"billing_progress.js must not contain '{token}'"


# ---------------------------------------------------------------------------
# 4. pricing.html integration (callout + progress mount + script tag)
# ---------------------------------------------------------------------------


def test_pricing_has_frictionless_callout(pricing_html: str) -> None:
    assert "¥0 から始められます" in pricing_html, (
        "pricing.html missing '¥0 から始められます' frictionless callout"
    )
    assert "pricing-frictionless" in pricing_html


def test_pricing_links_to_onboarding(pricing_html: str) -> None:
    assert "/onboarding.html" in pricing_html, (
        "pricing.html must link to /onboarding.html (avoid 迷子)"
    )


def test_pricing_mounts_progress_strip(pricing_html: str) -> None:
    assert "data-billing-progress" in pricing_html
    assert "billing_progress.js" in pricing_html


# ---------------------------------------------------------------------------
# 5. Breadcrumb chain (迷子ゼロ): home -> pricing -> onboarding
# ---------------------------------------------------------------------------


def test_onboarding_has_breadcrumb(onboarding_html: str) -> None:
    assert 'aria-label="パンくずリスト"' in onboarding_html
    # Linear chain: home -> pricing -> onboarding
    assert '<a href="/">ホーム</a>' in onboarding_html
    assert '<a href="pricing.html">料金</a>' in onboarding_html
    assert 'aria-current="page">はじめての方</span>' in onboarding_html


def test_onboarding_recap_lists_all_four_steps(onboarding_html: str) -> None:
    """The bottom recap row should chain all 4 steps in order."""
    recap_idx = onboarding_html.find('class="ob-recap"')
    assert recap_idx > 0, "ob-recap block missing"
    recap_block = onboarding_html[recap_idx : recap_idx + 800]
    for _, _label, href in EXPECTED_STEPS:
        assert href in recap_block, f"recap missing href {href}"


# ---------------------------------------------------------------------------
# 6. Anti-pattern guards (feedback_keep_it_simple / feedback_autonomath_no_ui /
#    feedback_zero_touch_solo / feedback_legacy_brand_marker)
# ---------------------------------------------------------------------------


FORBIDDEN_TIER_WORDS = [
    "Starter プラン",
    "Pro プラン",
    "Enterprise プラン",
    "Business プラン",
    "tier 1",
    "tier 2",
    "tier 3",
    "プラン階層",
]


def test_onboarding_no_tier_hierarchy(onboarding_html: str) -> None:
    for token in FORBIDDEN_TIER_WORDS:
        assert token not in onboarding_html, (
            f"feedback_keep_it_simple violation: '{token}' must not appear"
        )


FORBIDDEN_HUMAN_TOUCH = [
    "onboarding call",
    "営業担当",
    "アカウントマネージャー",
    "専用 Slack",
    "DPA 個別調印",
]


def test_onboarding_no_human_touch_features(onboarding_html: str) -> None:
    for token in FORBIDDEN_HUMAN_TOUCH:
        assert token not in onboarding_html, (
            f"feedback_zero_touch_solo violation: '{token}' must not appear"
        )


FORBIDDEN_LEGACY_BRAND = ["税務会計AI", "zeimu-kaikei.ai", "AutonoMath"]


def test_onboarding_no_legacy_brand_in_body(onboarding_html: str) -> None:
    # Strip JSON-LD blocks — historical bridge markers are allowed there but
    # not in user-visible body copy (feedback_legacy_brand_marker).
    body_match = re.search(r"<body\b[^>]*>(.*)</body>", onboarding_html, flags=re.DOTALL)
    assert body_match, "onboarding.html missing <body>"
    body = body_match.group(1)
    for token in FORBIDDEN_LEGACY_BRAND:
        assert token not in body, f"feedback_legacy_brand_marker: '{token}' must not appear in body"


# ---------------------------------------------------------------------------
# 7. HTML well-formedness sanity (cheap check, no full parser)
# ---------------------------------------------------------------------------


def test_onboarding_html_balanced(onboarding_html: str) -> None:
    assert onboarding_html.lstrip().startswith("<!DOCTYPE html>")
    assert onboarding_html.rstrip().endswith("</html>")
    # Anchors and articles balanced
    assert onboarding_html.count("<article") == onboarding_html.count("</article>")
    assert onboarding_html.count("<section") == onboarding_html.count("</section>")
