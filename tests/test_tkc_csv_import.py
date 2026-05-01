"""Tests for sdk/integrations/tkc-csv (TKC FX2 CSV importer).

Covers:
  - Column mapping (TKC 日本語 → jpcite client_profiles).
  - Encoding auto-detect (utf-8-sig + cp932 fall-back).
  - capital_yen 千円→円 normalization (×1,000).
  - last_active_program_ids pipe-split.
  - Empty / malformed rows skipped (not raised).
  - apply_to_client_profiles dry-run shape (no real HTTP).
  - apply_to_client_profiles _records_to_csv_text round-trip.

No network. No DB. The full chain:
    sample CSV → import_tkc_fx2.convert → records → apply.dry-run
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
TKC_DIR = REPO / "sdk" / "integrations" / "tkc-csv"
SAMPLE_CSV = TKC_DIR / "sample_tkc_fx2.csv"


def _load_module(name: str, path: Path):
    """Load a top-level script as a module (since sdk/integrations/tkc-csv
    is not a package — files are bare CLI scripts)."""

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None, f"could not load {path}"
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def importer():
    return _load_module(
        "import_tkc_fx2_under_test",
        TKC_DIR / "import_tkc_fx2.py",
    )


@pytest.fixture(scope="module")
def applier():
    return _load_module(
        "apply_to_client_profiles_under_test",
        TKC_DIR / "apply_to_client_profiles.py",
    )


# ---- import_tkc_fx2: row-level conversion ----------------------------------


def test_sample_csv_exists():
    assert SAMPLE_CSV.is_file(), f"sample CSV missing at {SAMPLE_CSV}"


def test_convert_sample_csv_path(importer):
    records, errors = importer.convert_csv_path(SAMPLE_CSV)
    # 3 rows × valid → 3 records, 0 errors.
    assert len(records) == 3
    assert errors == []

    # Row 1: 株式会社サンプル製造
    r1 = records[0]
    assert r1.name_label == "株式会社サンプル製造"
    assert r1.jsic_major == "E26"
    assert r1.prefecture == "東京都"
    assert r1.employee_count == 45
    # 30,000 千円 → 30,000,000 円
    assert r1.capital_yen == 30_000_000
    assert r1.last_active_program_ids == [
        "IT導入補助金2023",
        "ものづくり補助金R5",
    ]

    # Row 2: blank 適用補助金履歴 → []
    r2 = records[1]
    assert r2.name_label == "有限会社テスト商事"
    assert r2.jsic_major == "I60"
    assert r2.capital_yen == 5_000_000  # 5,000 千円
    assert (r2.last_active_program_ids or []) == []

    # Row 3: 1 program in last_active
    r3 = records[2]
    assert r3.last_active_program_ids == ["事業再構築補助金第10回"]


def test_convert_csv_text_with_only_required_column(importer):
    csv_text = "関与先名\n田中商店\n"
    records, errors = importer.convert_csv_text(csv_text)
    assert len(records) == 1
    assert records[0].name_label == "田中商店"
    assert records[0].jsic_major is None
    assert records[0].capital_yen is None
    assert errors == []


def test_skips_row_with_empty_name_label(importer):
    csv_text = "関与先名,所在地都道府県\n,東京都\n株式会社A,大阪府\n"
    records, errors = importer.convert_csv_text(csv_text)
    assert [r.name_label for r in records] == ["株式会社A"]
    assert errors == [{"row_index": 1, "error": "missing_name_label"}]


def test_capital_yen_normalization_1000x(importer):
    csv_text = (
        "関与先名,資本金（千円）\n"
        "テストA,10000\n"   # 10,000 千円 → 10,000,000 円
        "テストB,500\n"      # 500 千円 → 500,000 円
    )
    records, _errors = importer.convert_csv_text(csv_text)
    yen_values = [r.capital_yen for r in records]
    assert yen_values == [10_000_000, 500_000]


def test_employee_count_tolerates_suffix(importer):
    # 1,000 must be quoted in CSV so the comma is not a separator.
    csv_text = (
        '関与先名,従業員数\n'
        'A社,"1,000"\n'
        'B社,45人\n'
        'C社, 12 \n'
    )
    records, _errors = importer.convert_csv_text(csv_text)
    assert [r.employee_count for r in records] == [1000, 45, 12]


def test_jsic_truncation_to_4_chars(importer):
    csv_text = "関与先名,業種コード\nA社,E2611\nB社,E26\n"
    records, _errors = importer.convert_csv_text(csv_text)
    assert records[0].jsic_major == "E261"  # truncated
    assert records[1].jsic_major == "E26"


def test_max_rows_cap(importer):
    csv_text = "関与先名\n" + "\n".join(f"company-{i}" for i in range(5))
    records, errors = importer.convert_csv_text(csv_text, max_rows=3)
    assert len(records) == 3
    assert any(e.get("error") == "exceeded_row_cap" for e in errors)


def test_cp932_fallback(importer, tmp_path):
    # Hand-craft a cp932-encoded CSV (Excel JP default) — simulate a TKC
    # legacy-version export. The decoder must succeed without --encoding.
    csv_text = "関与先名,所在地都道府県\n株式会社旧テスト,東京都\n"
    f = tmp_path / "tkc_legacy.csv"
    f.write_bytes(csv_text.encode("cp932"))
    records, errors = importer.convert_csv_path(f)
    assert errors == []
    assert records[0].name_label == "株式会社旧テスト"
    assert records[0].prefecture == "東京都"


def test_no_header_returns_error(importer):
    records, errors = importer.convert_csv_text("")
    assert records == []
    assert errors == [{"error": "csv_no_header"}]


# ---- apply_to_client_profiles: CSV serialization + dry-run -----------------


def test_records_to_csv_text_roundtrips(importer, applier):
    records, _errors = importer.convert_csv_path(SAMPLE_CSV)
    payload = [r.to_dict() for r in records]
    csv_text = applier._records_to_csv_text(payload)
    # Header must include all jpcite-side columns.
    first_line = csv_text.splitlines()[0]
    for col in (
        "name_label", "jsic_major", "prefecture",
        "employee_count", "capital_yen",
        "target_types", "last_active_program_ids",
    ):
        assert col in first_line, f"missing {col} in header"
    # Pipe-joined list serialization in body.
    assert "IT導入補助金2023|ものづくり補助金R5" in csv_text


def test_multipart_body_has_boundary_and_csv(importer, applier):
    records, _errors = importer.convert_csv_path(SAMPLE_CSV)
    payload = [r.to_dict() for r in records]
    csv_text = applier._records_to_csv_text(payload)
    body, content_type = applier._build_multipart(csv_text, upsert=True)
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=")[1]
    assert boundary.encode("utf-8") in body
    assert b'name="file"' in body
    assert b'filename="tkc_fx2.csv"' in body
    assert b'name="upsert"' in body
    assert b"true" in body


def test_post_bulk_import_rejects_empty_key(applier):
    with pytest.raises(ValueError, match="api_key"):
        applier.post_bulk_import(
            api_base="https://api.jpcite.com",
            api_key="",
            records=[{"name_label": "Test"}],
        )


def test_post_bulk_import_short_circuits_empty_records(applier):
    out = applier.post_bulk_import(
        api_base="https://api.jpcite.com",
        api_key="dummy_key",
        records=[],
    )
    assert out["imported"] == 0
    assert "no records" in out.get("_note", "")


def test_load_records_accepts_list_or_dict(applier, tmp_path):
    records_list = [{"name_label": "A"}]
    list_path = tmp_path / "list.json"
    list_path.write_text(
        json.dumps(records_list, ensure_ascii=False), encoding="utf-8"
    )
    assert applier._load_records(list_path) == records_list

    wrapped = {"records": records_list, "errors": [], "summary": {}}
    wrap_path = tmp_path / "wrap.json"
    wrap_path.write_text(
        json.dumps(wrapped, ensure_ascii=False), encoding="utf-8"
    )
    assert applier._load_records(wrap_path) == records_list

    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps("scalar"), encoding="utf-8")
    with pytest.raises(ValueError, match="expected JSON list"):
        applier._load_records(bad_path)
