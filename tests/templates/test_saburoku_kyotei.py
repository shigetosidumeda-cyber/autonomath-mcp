"""Tests for 36協定 deterministic template renderer."""

from __future__ import annotations

import re

import pytest

from jpintel_mcp.templates.saburoku_kyotei import (
    FIELD_ALIASES,
    REQUIRED_FIELDS,
    TemplateError,
    get_required_fields,
    get_template_metadata,
    render_36_kyotei,
)

VALID_FIELDS = {
    "company_name": "Bookyou株式会社",
    "address": "東京都文京区小日向2-22-1",
    "representative": "梅田茂利",
    "industry": "情報通信業",
    "employee_count": "10",
    "agreement_period_start": "令和8年4月1日",
    "agreement_period_end": "令和9年3月31日",
    "max_overtime_hours_per_month": "45",
    "max_overtime_hours_per_year": "360",
    "holiday_work_days_per_month": "2",
}


def test_happy_path_all_fields_filled():
    out = render_36_kyotei(VALID_FIELDS)
    assert "Bookyou株式会社" in out
    assert "東京都文京区小日向2-22-1" in out
    assert "梅田茂利" in out
    assert "情報通信業" in out
    assert "令和8年4月1日" in out
    assert "令和9年3月31日" in out


def test_no_unsubstituted_placeholders():
    out = render_36_kyotei(VALID_FIELDS)
    leftover = re.findall(r"\{[a-z_]+\}", out)
    assert leftover == []


def test_alias_support_japanese_keys():
    aliased = {
        "会社名": "Bookyou株式会社",
        "住所": "東京都文京区小日向2-22-1",
        "代表者": "梅田茂利",
        "業種": "情報通信業",
        "労働者数": "10",
        "協定有効期間開始日": "令和8年4月1日",
        "協定有効期間終了日": "令和9年3月31日",
        "月間時間外労働時間": "45",
        "年間時間外労働時間": "360",
        "月間休日労働日数": "2",
    }
    out_aliased = render_36_kyotei(aliased)
    out_canonical = render_36_kyotei(VALID_FIELDS)
    assert out_aliased == out_canonical


def test_partial_alias_mix():
    mixed = dict(VALID_FIELDS)
    mixed.pop("company_name")
    mixed["屋号"] = "Bookyou株式会社"
    out = render_36_kyotei(mixed)
    assert "Bookyou株式会社" in out


def test_missing_field_raises():
    incomplete = dict(VALID_FIELDS)
    incomplete.pop("representative")
    with pytest.raises(TemplateError) as exc:
        render_36_kyotei(incomplete)
    assert "representative" in str(exc.value)
    assert "missing required fields" in str(exc.value)


def test_multiple_missing_fields_listed():
    incomplete = {"company_name": "X", "address": "Y"}
    with pytest.raises(TemplateError) as exc:
        render_36_kyotei(incomplete)
    msg = str(exc.value)
    assert "representative" in msg
    assert "industry" in msg


def test_unknown_field_raises():
    bad = dict(VALID_FIELDS)
    bad["nonexistent_field"] = "value"
    with pytest.raises(TemplateError) as exc:
        render_36_kyotei(bad)
    assert "unknown field" in str(exc.value)
    assert "nonexistent_field" in str(exc.value)


def test_metadata_shape():
    meta = get_template_metadata()
    assert meta["uses_llm"] is False
    assert meta["template_id"] == "saburoku_kyotei"
    assert meta["method"] == "deterministic_template_substitution"
    assert len(meta["required_fields"]) == 10


def test_required_fields_count():
    assert len(REQUIRED_FIELDS) == 10
    assert len(FIELD_ALIASES) == 10


def test_get_required_fields_introspection():
    fields = get_required_fields()
    assert len(fields) == 10
    assert "company_name" in fields
    assert "会社名" in fields["company_name"]
    assert isinstance(fields["company_name"], list)


def test_numeric_value_coerced_to_string():
    fields = dict(VALID_FIELDS)
    fields["employee_count"] = 10
    fields["max_overtime_hours_per_month"] = 45
    out = render_36_kyotei(fields)
    assert "10 名" in out
    assert "45 時間" in out
