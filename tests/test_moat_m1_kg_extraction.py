"""Tests for the M1 KG extraction upstream module.

Exercises ``jpintel_mcp.moat.m1_kg_extraction`` against synthetic
Japanese-government-PDF-style text fragments. No DB / network access —
pure-function tests.
"""

from __future__ import annotations

from jpintel_mcp.moat.m1_kg_extraction import (
    ExtractionResult,
    cjk_char_ratio,
    extract_entities,
    extract_kg,
    extract_relations,
    total_entities,
    total_relations,
)


def test_extract_entities_houjin_canonical_form() -> None:
    """13-digit houjin_bangou is harvested with leading non-zero guard."""
    text = "事業者番号: 2380001003581 / 9999999999999 / 0000000000123"
    out = extract_entities(text)
    houjins = [e for e in out if e.kind == "houjin"]
    # Leading-zero stub rejected; all-same-digit stub rejected; 9999... has
    # set(h) size 1 → rejected; 2380001003581 is valid.
    assert any(e.value == "2380001003581" for e in houjins)
    assert not any(e.value == "0000000000123" for e in houjins)
    assert not any(e.value == "9999999999999" for e in houjins)


def test_extract_entities_iso_date_normalisation() -> None:
    """ISO + 西暦 date variants normalise to YYYY-MM-DD."""
    text = "発行日: 2024/05/27\n施行日: 2024-5-1\n更新日: 2024年5月27日"
    out = extract_entities(text)
    dates = [e for e in out if e.kind == "date"]
    iso_values = {e.value for e in dates}
    assert "2024-05-27" in iso_values
    assert "2024-05-01" in iso_values


def test_extract_entities_reiwa_date() -> None:
    """Reiwa-form dates parse to 西暦 (2018 + N)."""
    text = "令和5年4月1日"
    out = extract_entities(text)
    dates = [e for e in out if e.kind == "date"]
    assert any(e.value == "2023-04-01" for e in dates)


def test_extract_entities_amount_yen_scaling() -> None:
    """100万円 → 1_000_000 yen; 5億円 → 500_000_000 yen."""
    text = "上限額: 100万円 / 採択時 5億円 / 月額 1,234円"
    out = extract_entities(text)
    amounts = [e for e in out if e.kind == "amount"]
    values = {e.value for e in amounts}
    assert 1_000_000 in values
    assert 500_000_000 in values
    assert 1_234 in values


def test_extract_entities_postal_code_strict_boundary() -> None:
    """13-digit houjin tails are NOT misread as postal codes."""
    text = "〒100-0001\n2380001003581"
    out = extract_entities(text)
    postals = [e for e in out if e.kind == "postal_code"]
    # Only one postal — the explicit 〒 form. The 13-digit number must
    # NOT register as 100-3581.
    assert len(postals) == 1
    assert postals[0].value == "100-0001"


def test_extract_entities_url_trailing_punct_strip() -> None:
    """URL surface drops trailing dots / commas / semicolons."""
    text = "詳細は https://example.go.jp/path/?x=1, または ..."
    out = extract_entities(text)
    urls = [e for e in out if e.kind == "url"]
    assert urls
    assert urls[0].surface.endswith("=1")


def test_extract_entities_cjk_dict_off_by_default() -> None:
    """Dictionary extractors (program / law / authority) require opt-in."""
    text = "中小企業支援事業について、経済産業省は租税特別措置法第42条を適用する。"
    out_off = extract_entities(text, cjk_dict=False)
    kinds_off = {e.kind for e in out_off}
    assert "program" not in kinds_off
    assert "law" not in kinds_off
    assert "authority" not in kinds_off
    out_on = extract_entities(text, cjk_dict=True)
    kinds_on = {e.kind for e in out_on}
    assert "program" in kinds_on
    assert "law" in kinds_on
    assert "authority" in kinds_on


def test_extract_relations_co_occurrence_within_page() -> None:
    """program × law on the same page yields references_law."""
    text = "本事業の中小企業支援事業は租税特別措置法第42条の4を対象とする。"
    result = extract_kg(text, page=3, cjk_dict=True)
    rels = result.relations
    types = {r.relation_type for r in rels}
    assert "references_law" in types


def test_extract_relations_canonical_relation_types() -> None:
    """Emitted relation_types stay inside the canonical frozenset."""
    canonical = {
        "has_authority",
        "applies_to_region",
        "applies_to_industry",
        "related",
        "references_law",
    }
    text = "経済産業省 中小企業支援事業 租税特別措置法 株式会社サンプル"
    result = extract_kg(text, page=1, cjk_dict=True)
    for r in result.relations:
        assert r.relation_type in canonical, r


def test_cjk_char_ratio_garbled_ocr_low() -> None:
    """Garbled Textract ASCII-only output has near-zero CJK ratio."""
    garbled = "** 2024/5/27\n(\n22 14\n--\n********\n11\n****\nB\nX\n1450001002338\n"
    assert cjk_char_ratio(garbled) < 0.05
    assert cjk_char_ratio("経済産業省は中小企業を支援") > 0.5


def test_extract_kg_stable_ordering() -> None:
    """Same input → identical entity / relation ordering."""
    text = "2024/5/27\n2380001003581\n令和5年4月1日\nhttps://example.go.jp/"
    a = extract_kg(text, page=1)
    b = extract_kg(text, page=1)
    assert [e.surface for e in a.entities] == [e.surface for e in b.entities]
    assert [r.relation_type for r in a.relations] == [r.relation_type for r in b.relations]


def test_total_helpers_return_dicts() -> None:
    """`total_entities` / `total_relations` return per-kind counts."""
    text = "2380001003581\n2024/5/27\nhttps://example.go.jp/"
    r = extract_kg(text, page=1)
    e_counts = total_entities(r)
    r_counts = total_relations(r)
    assert isinstance(e_counts, dict)
    assert isinstance(r_counts, dict)
    assert e_counts.get("houjin", 0) >= 1


def test_extract_kg_returns_extraction_result_dataclass() -> None:
    """Return type is a frozen ExtractionResult dataclass."""
    r = extract_kg("2380001003581", page=1)
    assert isinstance(r, ExtractionResult)
    assert r.char_count == len("2380001003581")
    assert r.page_count == 1
    # Relations may be empty on a houjin-only single-page text.
    _ = extract_relations(r.entities)


def test_extract_entities_empty_input_returns_empty() -> None:
    """Empty / whitespace-only input returns []."""
    assert extract_entities("") == []
    assert extract_entities("   \n\t") == []
