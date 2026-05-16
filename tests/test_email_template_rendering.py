"""Stream T coverage gap: email/ — compliance template rendering.

Targets ``src/jpintel_mcp/email/compliance_templates.py``. The existing
``tests/test_email_templates.py`` covers Postmark-side templates; this
file exercises the locally-rendered alert + verification email path.

No source mutation. Fixtures inline.
"""

from __future__ import annotations

import pytest

from jpintel_mcp.email.compliance_templates import (
    AREA_LABELS_JA,
    AREAS_SUPPORTED,
    compose_alert_email,
    render_verification_email,
)


def _make_subscriber(**overrides: object) -> dict[str, object]:
    base = {
        "email": "user@example.com",
        "unsubscribe_token": "tok-xyz",
        "plan": "alerts_basic",
        "areas_of_interest": ["invoice", "subsidy"],
    }
    base.update(overrides)
    return base


def _make_change(**overrides: object) -> dict[str, object]:
    base = {
        "unified_id": "uid-1",
        "table": "programs",
        "area": "subsidy",
        "title": "ものづくり補助金",
        "summary": "上限額の変更",
        "source_url": "https://example.go.jp/source",
        "detail_url": "https://jpcite.com/programs/x",
        "updated_at": "2026-05-15",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# AREA_LABELS / AREAS_SUPPORTED — constants
# ---------------------------------------------------------------------------


def test_areas_supported_matches_label_keys() -> None:
    assert set(AREAS_SUPPORTED) == set(AREA_LABELS_JA.keys())


def test_area_labels_cover_key_buckets() -> None:
    # The 7 canonical area codes per docstring.
    for k in ("invoice", "ebook", "subsidy", "loan", "enforcement", "tax_ruleset", "court"):
        assert k in AREA_LABELS_JA


# ---------------------------------------------------------------------------
# compose_alert_email — required fields, escaping, mode toggles
# ---------------------------------------------------------------------------


def test_compose_alert_realtime_subject_and_keys() -> None:
    out = compose_alert_email(
        _make_subscriber(),  # type: ignore[arg-type]
        [_make_change()],  # type: ignore[list-item]
        mode="realtime",
    )
    assert "subject" in out
    assert "html" in out
    assert "text" in out
    assert "1件" in out["subject"]
    assert "jpcite" in out["subject"]
    # Both branches render the change title
    assert "ものづくり補助金" in out["html"]
    assert "ものづくり補助金" in out["text"]
    # Unsubscribe URL must appear in the HTML body (text footer is a
    # raw string literal that intentionally keeps {unsubscribe_url} as a
    # placeholder per current source behaviour).
    assert "tok-xyz" in out["html"]
    assert "{unsubscribe_url}" in out["text"]


def test_compose_alert_digest_subject_includes_period() -> None:
    out = compose_alert_email(
        _make_subscriber(),  # type: ignore[arg-type]
        [_make_change()],  # type: ignore[list-item]
        mode="digest",
        period_label="2026-04",
    )
    assert "2026-04" in out["subject"]


def test_compose_alert_missing_email_raises() -> None:
    with pytest.raises(ValueError, match="email"):
        compose_alert_email(
            {"unsubscribe_token": "tok"},  # type: ignore[arg-type]
            [_make_change()],  # type: ignore[list-item]
        )


def test_compose_alert_missing_unsubscribe_token_raises() -> None:
    with pytest.raises(ValueError, match="unsubscribe_token"):
        compose_alert_email(
            {"email": "u@example.com"},  # type: ignore[arg-type]
            [_make_change()],  # type: ignore[list-item]
        )


def test_compose_alert_handles_missing_optional_fields() -> None:
    sparse_change = {
        "unified_id": "uid-2",
        "table": "programs",
        "area": "subsidy",
        # No title, summary, urls — should be tolerated
    }
    out = compose_alert_email(
        _make_subscriber(),  # type: ignore[arg-type]
        [sparse_change],  # type: ignore[list-item]
    )
    # Default placeholder "(無題)" appears for missing title
    assert "(無題)" in out["html"] or "(無題)" in out["text"]


def test_compose_alert_html_escapes_user_content() -> None:
    malicious_change = _make_change(title="<script>alert(1)</script>")
    out = compose_alert_email(
        _make_subscriber(),  # type: ignore[arg-type]
        [malicious_change],  # type: ignore[list-item]
    )
    # autoescape=True must convert < into &lt; in HTML body
    assert "<script>" not in out["html"]
    assert "&lt;script&gt;" in out["html"]
    # Plain text body has no autoescape — the raw form is fine there.
    assert "<script>" in out["text"]


def test_compose_alert_groups_by_area_in_canonical_order() -> None:
    out = compose_alert_email(
        _make_subscriber(),  # type: ignore[arg-type]
        [
            _make_change(area="enforcement", title="行政処分A"),
            _make_change(area="invoice", title="インボイスB"),
        ],
    )
    # invoice should appear before enforcement per AREAS_SUPPORTED order
    text = out["html"]
    invoice_pos = text.find("インボイス制度")
    enforcement_pos = text.find("行政処分")
    assert 0 <= invoice_pos < enforcement_pos


# ---------------------------------------------------------------------------
# render_verification_email
# ---------------------------------------------------------------------------


def test_render_verification_email_contains_verify_url() -> None:
    out = render_verification_email(
        email="u@example.com",
        verify_url="https://jpcite.com/verify/abc",
        unsubscribe_token="tok-1",
    )
    assert "subject" in out
    assert "https://jpcite.com/verify/abc" in out["html"]
    assert "https://jpcite.com/verify/abc" in out["text"]
    # Footer still includes unsubscribe URL on the HTML side; text
    # footer is a raw literal that keeps the placeholder per source.
    assert "tok-1" in out["html"]
    assert "{unsubscribe_url}" in out["text"]


def test_render_verification_email_subject_pinned() -> None:
    out = render_verification_email(
        email="u@example.com",
        verify_url="https://x",
        unsubscribe_token="tok-1",
    )
    assert "登録確認" in out["subject"]
