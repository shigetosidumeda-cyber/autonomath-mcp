"""Tests for the launch-v1 hallucination_guard YAML + matcher.

Covers:
  1. yaml schema is well-formed (60 entries, required fields, allowed enum values)
  2. match() detects a known phrase
  3. match() returns [] for unrelated text
  4. severity field is mandatory on every entry
  5. all 5 audience × 6 vertical enum values appear at least once
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from jpintel_mcp.self_improve import loop_a_hallucination_guard as guard  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = REPO_ROOT / "data" / "hallucination_guard.yaml"

ALLOWED_SEVERITY = {"high", "medium", "low"}
ALLOWED_AUDIENCE = {"税理士", "行政書士", "SMB", "VC", "Dev"}
ALLOWED_VERTICAL = {"補助金", "税制", "融資", "認定", "行政処分", "法令"}
REQUIRED_FIELDS = ("phrase", "severity", "correction", "audience", "vertical")


@pytest.fixture(scope="module")
def entries() -> list[dict]:
    raw = yaml.safe_load(DATA_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict) and "entries" in raw, "yaml must have top-level `entries:` key"
    rows = raw["entries"]
    assert isinstance(rows, list)
    return rows


def test_yaml_schema_valid(entries):
    """Schema: 60 entries, every required field present, every enum value allowed."""
    assert len(entries) == 60, f"launch v1 expects 60 entries, got {len(entries)}"
    for i, e in enumerate(entries):
        assert isinstance(e, dict), f"entry {i} not a dict"
        for k in REQUIRED_FIELDS:
            assert k in e, f"entry {i} missing field `{k}`"
            assert e[k] not in (None, ""), f"entry {i} has empty `{k}`"
        assert e["severity"] in ALLOWED_SEVERITY, f"entry {i} bad severity {e['severity']!r}"
        assert e["audience"] in ALLOWED_AUDIENCE, f"entry {i} bad audience {e['audience']!r}"
        assert e["vertical"] in ALLOWED_VERTICAL, f"entry {i} bad vertical {e['vertical']!r}"
        # law_basis is optional but if present must be a non-empty string
        if "law_basis" in e and e["law_basis"] is not None:
            assert isinstance(e["law_basis"], str) and e["law_basis"].strip()


def test_match_detects_known_phrase(entries):
    """match() should detect a phrase that is verbatim in the corpus."""
    sample_phrase = entries[0]["phrase"]
    text = f"先日のセミナーで「{sample_phrase}」と説明されたが本当か"
    hits = guard.match(text)
    assert len(hits) >= 1
    assert any(h["phrase"] == sample_phrase for h in hits)


def test_match_returns_empty_for_unrelated_text():
    """match() returns [] when no phrase matches."""
    assert guard.match("今日はとても良い天気です。散歩に行きます。") == []
    assert guard.match("") == []


def test_severity_field_required_on_every_entry(entries):
    """severity must be present and non-empty on every row."""
    missing = [i for i, e in enumerate(entries) if "severity" not in e or not e["severity"]]
    assert missing == [], f"entries missing severity: {missing}"
    bad = [i for i, e in enumerate(entries) if e["severity"] not in ALLOWED_SEVERITY]
    assert bad == [], f"entries with bad severity: {bad}"


def test_all_audience_and_vertical_enum_values_present(entries):
    """Every one of 5 audience × 6 vertical must be represented (2 phrases each)."""
    seen_audience = {e["audience"] for e in entries}
    seen_vertical = {e["vertical"] for e in entries}
    assert (
        seen_audience == ALLOWED_AUDIENCE
    ), f"missing audience: {ALLOWED_AUDIENCE - seen_audience}"
    assert (
        seen_vertical == ALLOWED_VERTICAL
    ), f"missing vertical: {ALLOWED_VERTICAL - seen_vertical}"
    # Each (audience, vertical) cell must have exactly 2 phrases
    from collections import Counter

    cell_counts = Counter((e["audience"], e["vertical"]) for e in entries)
    bad_cells = {k: v for k, v in cell_counts.items() if v != 2}
    assert bad_cells == {}, f"cells without exactly 2 phrases: {bad_cells}"
