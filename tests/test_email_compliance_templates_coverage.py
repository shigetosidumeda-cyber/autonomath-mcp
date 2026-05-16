"""Coverage tests for `jpintel_mcp.email.compliance_templates` (lane #5).

Pure Jinja2 rendering with no IO — fast, deterministic. Asserts on the
rendered HTML / text to lock in:
  * footer 特商法 + unsubscribe link presence (regulatory hard rule)
  * subject prefix `【jpcite】` (brand contract)
  * area grouping ordered by canonical AREAS_SUPPORTED
"""

from __future__ import annotations

import pytest

from jpintel_mcp.email import compliance_templates as ct

# ---------------------------------------------------------------------------
# AREA_LABELS_JA constants
# ---------------------------------------------------------------------------


def test_area_labels_cover_all_supported_areas() -> None:
    assert set(ct.AREA_LABELS_JA.keys()) == set(ct.AREAS_SUPPORTED)


def test_area_labels_have_japanese_strings() -> None:
    for label in ct.AREA_LABELS_JA.values():
        assert isinstance(label, str) and len(label) >= 2


# ---------------------------------------------------------------------------
# compose_alert_email — realtime mode
# ---------------------------------------------------------------------------


def _subscriber() -> ct.Subscriber:
    return {
        "id": 42,
        "email": "test@example.com",
        "prefecture": "東京都",
        "plan": "paid",
        "unsubscribe_token": "tok_abc",
        "areas_of_interest": ["invoice", "subsidy"],
        "industry_codes": [],
    }


def _change(area: str = "invoice", title: str = "Test 改正") -> ct.Change:
    return {
        "unified_id": "p-001",
        "table": "programs",
        "area": area,
        "title": title,
        "summary": "サマリー本文",
        "source_url": "https://example.com/src",
        "detail_url": "https://jpcite.com/p/001",
        "updated_at": "2026-05-17",
    }


def test_compose_alert_email_realtime_has_jpcite_subject() -> None:
    out = ct.compose_alert_email(_subscriber(), [_change()], mode="realtime")
    assert out["subject"].startswith("【jpcite】")
    assert "1件" in out["subject"]


def test_compose_alert_email_digest_mode_uses_period_label() -> None:
    out = ct.compose_alert_email(
        _subscriber(),
        [_change(), _change(area="subsidy")],
        mode="digest",
        period_label="2026-05",
    )
    assert out["subject"].startswith("【jpcite】")
    assert "2026-05" in out["subject"]
    assert "2件" in out["subject"]


def test_compose_alert_email_html_contains_unsubscribe_link() -> None:
    out = ct.compose_alert_email(_subscriber(), [_change()])
    assert "tok_abc" in out["html"]
    assert "alerts-unsubscribe.html" in out["html"]


def test_compose_alert_email_html_contains_tokushoho_footer() -> None:
    out = ct.compose_alert_email(_subscriber(), [_change()])
    assert "Bookyou" in out["html"]
    assert "T8010001213708" in out["html"]
    assert "tokushoho.html" in out["html"]


def test_compose_alert_email_text_renders_plain_text() -> None:
    out = ct.compose_alert_email(_subscriber(), [_change()])
    # Plain-text body must NOT contain raw HTML tags.
    assert "<html" not in out["text"]
    assert "Bookyou" in out["text"]
    # The text footer carries the canonical legal links + 配信停止 line.
    assert "配信を停止する" in out["text"]
    assert "tokushoho.html" in out["text"]


def test_compose_alert_email_raises_when_email_missing() -> None:
    sub: ct.Subscriber = dict(_subscriber())  # type: ignore[assignment]
    sub.pop("email", None)
    with pytest.raises(ValueError, match="email is required"):
        ct.compose_alert_email(sub, [_change()])


def test_compose_alert_email_raises_when_token_missing() -> None:
    sub: ct.Subscriber = dict(_subscriber())  # type: ignore[assignment]
    sub.pop("unsubscribe_token", None)
    with pytest.raises(ValueError, match="unsubscribe_token"):
        ct.compose_alert_email(sub, [_change()])


def test_compose_alert_email_handles_missing_change_fields() -> None:
    # All Change keys optional — placeholders fill in for missing values.
    minimal: ct.Change = {"area": "invoice"}
    out = ct.compose_alert_email(_subscriber(), [minimal])
    assert "(無題)" in out["html"]


def test_compose_alert_email_unknown_area_routes_to_other_bucket() -> None:
    weird = _change()
    weird["area"] = "definitely_not_a_real_area"
    out = ct.compose_alert_email(_subscriber(), [weird])
    # Should render the 「その他」 fallback bucket label.
    assert "その他" in out["html"]


def test_compose_alert_email_groups_by_area() -> None:
    changes = [
        _change(area="invoice", title="A1"),
        _change(area="subsidy", title="B1"),
        _change(area="invoice", title="A2"),
    ]
    out = ct.compose_alert_email(_subscriber(), changes)
    # invoice section appears before subsidy section per AREAS_SUPPORTED order.
    inv_idx = out["html"].find(ct.AREA_LABELS_JA["invoice"])
    sub_idx = out["html"].find(ct.AREA_LABELS_JA["subsidy"])
    assert 0 <= inv_idx < sub_idx


def test_compose_alert_email_zero_changes_still_renders() -> None:
    out = ct.compose_alert_email(_subscriber(), [])
    assert "【jpcite】" in out["subject"]
    assert "0件" in out["subject"]


def test_compose_alert_email_digest_with_no_period_label() -> None:
    # period_label is optional in digest mode.
    out = ct.compose_alert_email(
        _subscriber(),
        [_change()],
        mode="digest",
    )
    assert out["subject"].startswith("【jpcite】")


# ---------------------------------------------------------------------------
# render_verification_email
# ---------------------------------------------------------------------------


def test_render_verification_email_subject_is_canonical() -> None:
    out = ct.render_verification_email(
        email="new@example.com",
        verify_url="https://jpcite.com/verify?t=zzz",
        unsubscribe_token="tok_v",
    )
    assert "登録確認" in out["subject"]
    assert "【jpcite】" in out["subject"]


def test_render_verification_email_html_includes_verify_button_url() -> None:
    out = ct.render_verification_email(
        email="new@example.com",
        verify_url="https://jpcite.com/verify?t=xyz123",
        unsubscribe_token="tok_v",
    )
    assert "https://jpcite.com/verify?t=xyz123" in out["html"]
    assert "登録を確認する" in out["html"]


def test_render_verification_email_text_has_verify_url() -> None:
    out = ct.render_verification_email(
        email="new@example.com",
        verify_url="https://jpcite.com/verify?t=tttt",
        unsubscribe_token="tok_v",
    )
    assert "https://jpcite.com/verify?t=tttt" in out["text"]
    assert "<html" not in out["text"]


def test_render_verification_email_footer_includes_unsubscribe() -> None:
    out = ct.render_verification_email(
        email="new@example.com",
        verify_url="https://jpcite.com/verify?t=k",
        unsubscribe_token="tok_unsub_verify",
    )
    assert "tok_unsub_verify" in out["html"]


# ---------------------------------------------------------------------------
# Internal helpers (_unsubscribe_url, _group_by_area)
# ---------------------------------------------------------------------------


def test_unsubscribe_url_uses_canonical_host() -> None:
    url = ct._unsubscribe_url("tok_x")
    assert url == "https://jpcite.com/alerts-unsubscribe.html?token=tok_x"


def test_group_by_area_preserves_canonical_order() -> None:
    # Insert in reverse order — groups must still respect AREAS_SUPPORTED.
    changes = [
        _change(area="court"),
        _change(area="invoice"),
        _change(area="subsidy"),
    ]
    grouped = ct._group_by_area(changes)
    keys = list(grouped.keys())
    # invoice precedes subsidy precedes court per AREAS_SUPPORTED.
    assert keys.index("invoice") < keys.index("subsidy")
    assert keys.index("subsidy") < keys.index("court")


def test_group_by_area_collects_other_bucket() -> None:
    changes = [_change(area="invoice"), _change(area="not_a_real_area")]
    grouped = ct._group_by_area(changes)
    assert "_other" in grouped
    assert len(grouped["_other"]) == 1


def test_group_by_area_empty_input_returns_empty_dict() -> None:
    assert ct._group_by_area([]) == {}
