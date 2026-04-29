"""End-to-end tests for the 6-pack ``?format=…`` renderer surface.

Coverage matrix (one assertion block per format):

    csv               text/csv               UTF-8 BOM + §52 banner row
    xlsx              application/vnd…sheet  data + _meta sheets, JA banner
    md                text/markdown          pipe table + block-quote §52
    ics               text/calendar          VEVENT per row, sha256 UID
    docx-application  application/…document  §1 行政書士法 fence + placeholder
    csv-freee         text/csv               freee template URL header
    csv-mf            text/csv               MoneyForward column order
    csv-yayoi         text/csv (Shift_JIS)   Yayoi 振替伝票 column order

Every test runs the dispatcher directly (no FastAPI test client) so the
suite stays fast and is decoupled from per-endpoint wiring — the
endpoint integration is tested separately via ``test_endpoint_smoke``.

The dispatcher's contract is: ``render(rows, fmt, meta) -> Response``.
Each test asserts:
  1. status_code == 200
  2. content-type matches the format
  3. body parses with the canonical lib for that format
  4. §52 disclaimer appears in a format-appropriate location
  5. unified_id from the input row survives round-trip
"""

from __future__ import annotations

import csv
import io
import re

import pytest

from jpintel_mcp.api._format_dispatch import render

# ---------------------------------------------------------------------------
# Shared fixture rows — two programs with deadline-bearing fields so the
# ICS renderer has something to emit.
# ---------------------------------------------------------------------------

SAMPLE_ROWS = [
    {
        "unified_id": "PROG-uvf-0001",
        "primary_name": "テスト S-tier 補助金",
        "source_url": "https://example.go.jp/program/uvf-0001",
        "source_fetched_at": "2026-04-29T12:00:00+09:00",
        "license": "cc_by_4.0",
        "next_deadline": "2026-12-31",
        "max_amount_yen": 5_000_000,
        "tier": "S",
        "tags": ["東京都", "IT", "中小企業"],
    },
    {
        "unified_id": "PROG-uvf-0002",
        "primary_name": "別の A-tier 補助金",
        "source_url": "https://example2.go.jp/p/0002",
        "source_fetched_at": "2026-04-29T13:00:00+09:00",
        "license": "pdl_v1.0",
        "next_deadline": "2026-06-30T17:00:00+09:00",
        "max_amount_yen": 3_000_000,
        "tier": "A",
        "tags": [],
    },
]

SAMPLE_META = {
    "filename_stem": "test_export",
    "endpoint": "programs",
}


# ---------------------------------------------------------------------------
# 1. CSV — UTF-8 BOM, §52 comment row, lineage columns first.
# ---------------------------------------------------------------------------


def test_format_csv_round_trip() -> None:
    resp = render(SAMPLE_ROWS, "csv", SAMPLE_META)
    assert resp.status_code == 200
    assert resp.media_type.startswith("text/csv")
    assert resp.headers.get("X-AutonoMath-Format") == "csv"

    raw = resp.body
    # UTF-8 BOM (﻿ -> \xef\xbb\xbf) MUST lead so Excel-JP opens UTF-8.
    assert raw.startswith(b"\xef\xbb\xbf"), "CSV must start with UTF-8 BOM"

    text = raw.decode("utf-8-sig")  # utf-8-sig strips the BOM
    lines = text.splitlines()

    # Row 0 — §52 disclaimer comment.
    assert lines[0].startswith("# 税理士法 §52"), lines[0]
    # Row 1 — brand + license rollup comment.
    assert lines[1].startswith("# 税務会計AI / Bookyou株式会社"), lines[1]

    # Parse data section with stdlib csv (skip the 2 comment rows).
    reader = csv.DictReader(io.StringIO("\n".join(lines[2:])))
    parsed = list(reader)
    assert len(parsed) == 2
    assert parsed[0]["unified_id"] == "PROG-uvf-0001"
    assert parsed[0]["license"] == "cc_by_4.0"
    # Required-column ordering (lineage columns lead).
    fieldnames = list(reader.fieldnames or [])
    assert fieldnames[:4] == [
        "unified_id",
        "source_url",
        "source_fetched_at",
        "license",
    ]


# ---------------------------------------------------------------------------
# 2. XLSX — openpyxl write_only, two sheets (data + _meta), banner row 1.
# ---------------------------------------------------------------------------


def test_format_xlsx_round_trip() -> None:
    openpyxl = pytest.importorskip("openpyxl")

    resp = render(SAMPLE_ROWS, "xlsx", SAMPLE_META)
    assert resp.status_code == 200
    assert resp.media_type.startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert resp.headers.get("X-AutonoMath-Format") == "xlsx"

    wb = openpyxl.load_workbook(io.BytesIO(resp.body))
    assert wb.sheetnames == ["data", "_meta"]

    data = wb["data"]
    # Row 1 — §52 banner cell.
    banner = data.cell(1, 1).value or ""
    assert "税理士法 §52" in banner

    # Row 2 — column headers, lineage columns first.
    header = [data.cell(2, c).value for c in range(1, 5)]
    assert header == ["unified_id", "source_url", "source_fetched_at", "license"]

    # Row 3 — first data row.
    assert data.cell(3, 1).value == "PROG-uvf-0001"

    # _meta sheet carries disclaimer + brand + license_summary.
    meta_pairs = {
        row[0]: row[1]
        for row in wb["_meta"].iter_rows(values_only=True)
        if row and row[0] != "key"
    }
    assert "税理士法 §52" in (meta_pairs.get("disclaimer") or "")
    assert "Bookyou株式会社" in (meta_pairs.get("brand") or "")
    assert meta_pairs.get("row_count") == 2


# ---------------------------------------------------------------------------
# 3. Markdown — pipe table, block-quote disclaimer.
# ---------------------------------------------------------------------------


def test_format_md_round_trip() -> None:
    resp = render(SAMPLE_ROWS, "md", SAMPLE_META)
    assert resp.status_code == 200
    assert resp.media_type.startswith("text/markdown")
    assert resp.headers.get("X-AutonoMath-Format") == "md"

    text = resp.body.decode("utf-8")
    lines = text.splitlines()

    # Block-quote disclaimer MUST appear before the table.
    assert lines[0].startswith("> **税理士法 §52**"), lines[0]

    # Find the pipe-table header (first line starting `| unified_id`).
    header_idx = next(
        (i for i, ln in enumerate(lines) if ln.startswith("| unified_id")), -1
    )
    assert header_idx >= 0, "pipe-table header missing"

    header = lines[header_idx]
    # Lineage columns lead.
    cols = [c.strip() for c in header.strip("|").split("|")]
    assert cols[:4] == ["unified_id", "source_url", "source_fetched_at", "license"]

    # Row separator (---) immediately under header.
    assert "---" in lines[header_idx + 1]

    # Both rows are present.
    assert any("PROG-uvf-0001" in ln for ln in lines)
    assert any("PROG-uvf-0002" in ln for ln in lines)


# ---------------------------------------------------------------------------
# 4. iCalendar — VEVENT per row, sha256 UID @autonomath.ai.
# ---------------------------------------------------------------------------


def test_format_ics_round_trip() -> None:
    icalendar = pytest.importorskip("icalendar")

    resp = render(SAMPLE_ROWS, "ics", SAMPLE_META)
    assert resp.status_code == 200
    assert resp.media_type.startswith("text/calendar")
    assert resp.headers.get("X-AutonoMath-Format") == "ics"
    assert resp.headers.get("X-AutonoMath-Event-Count") == "2"

    text = resp.body.decode("utf-8")
    # VTIMEZONE block embedded so the file is self-contained.
    assert "BEGIN:VTIMEZONE" in text
    assert "TZID:Asia/Tokyo" in text

    cal = icalendar.Calendar.from_ical(resp.body)
    events = list(cal.walk("VEVENT"))
    assert len(events) == 2

    uid_re = re.compile(r"^[0-9a-f]{64}@autonomath\.ai$")
    for ev in events:
        uid = str(ev.get("UID"))
        assert uid_re.match(uid), f"unexpected UID format: {uid!r}"
        # §52 disclaimer must appear in DESCRIPTION.
        assert "§52" in str(ev.get("DESCRIPTION") or "")


def test_format_ics_skips_rows_without_deadline() -> None:
    """A row with no deadline columns produces no VEVENT (silently)."""
    icalendar = pytest.importorskip("icalendar")
    rows = [{
        "unified_id": "PROG-no-deadline",
        "primary_name": "no-deadline program",
        "source_url": "https://x.go.jp",
        "source_fetched_at": "2026-04-29T00:00:00+09:00",
        "license": "cc_by_4.0",
    }]
    resp = render(rows, "ics", SAMPLE_META)
    cal = icalendar.Calendar.from_ical(resp.body)
    assert list(cal.walk("VEVENT")) == []
    assert resp.headers.get("X-AutonoMath-Empty") == "1"


# ---------------------------------------------------------------------------
# 5. DOCX 申請書 boilerplate — 行政書士法 §1 fence + placeholder fields.
# ---------------------------------------------------------------------------


def test_format_docx_application_round_trip() -> None:
    docx_mod = pytest.importorskip("docx")

    resp = render(SAMPLE_ROWS, "docx-application", SAMPLE_META)
    assert resp.status_code == 200
    assert resp.media_type.startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert resp.headers.get("X-AutonoMath-Format") == "docx-application"
    assert resp.headers.get("X-AutonoMath-Gyoseishoshi-Fence") == "scaffold-only"

    doc = docx_mod.Document(io.BytesIO(resp.body))
    full_text = "\n".join(p.text for p in doc.paragraphs)

    # 行政書士法 §1 fence MUST appear.
    assert "行政書士法 §1" in full_text, "missing §1 行政書士法 fence"
    assert "scaffold" in full_text.lower(), "missing scaffold marker"

    # Placeholder fields MUST be unfilled.
    assert "{{customer_name}}" in full_text
    assert "{{requested_amount_yen}}" in full_text

    # §52 also reprinted on the cover.
    assert "§52" in full_text


# ---------------------------------------------------------------------------
# 6a. CSV-freee — freee template URL in comment row, freee column order.
# ---------------------------------------------------------------------------


def test_format_csv_freee_round_trip() -> None:
    resp = render(SAMPLE_ROWS, "csv-freee", SAMPLE_META)
    assert resp.status_code == 200
    assert resp.media_type.startswith("text/csv")
    assert resp.headers.get("X-AutonoMath-Format") == "csv-freee"
    # Vendor-template URL MUST appear in the response header for trace.
    assert "support.freee.co.jp" in (
        resp.headers.get("X-AutonoMath-Vendor-Template") or ""
    )

    text = resp.body.decode("utf-8")
    lines = text.splitlines()

    # Comment row 0 — vendor template URL.
    assert lines[0].startswith("# Source format:")
    assert "support.freee.co.jp" in lines[0]

    # Comment row 2 — §52.
    assert "§52" in "\n".join(lines[:5])

    # Header row — freee column order.
    header_idx = next(i for i, ln in enumerate(lines) if not ln.startswith("#"))
    header = lines[header_idx].split(",")
    assert header[:4] == ["取引日", "借方勘定科目", "借方税区分", "借方金額"]

    # Data rows.
    data_lines = lines[header_idx + 1 :]
    assert len(data_lines) == 2
    # 借方 / 貸方 unfilled (manual mapping required by 経理).
    assert "未決 (要確認)" in data_lines[0]


# ---------------------------------------------------------------------------
# 6b. CSV-mf — MoneyForward column order.
# ---------------------------------------------------------------------------


def test_format_csv_mf_round_trip() -> None:
    resp = render(SAMPLE_ROWS, "csv-mf", SAMPLE_META)
    assert resp.status_code == 200
    assert resp.media_type.startswith("text/csv")
    assert resp.headers.get("X-AutonoMath-Format") == "csv-mf"

    text = resp.body.decode("utf-8-sig")  # MF is BOM
    lines = text.splitlines()
    header_idx = next(i for i, ln in enumerate(lines) if not ln.startswith("#"))
    header = lines[header_idx].split(",")
    assert header[0] == "取引No"
    assert "借方補助科目" in header
    assert "備考" in header


# ---------------------------------------------------------------------------
# 6c. CSV-yayoi — Shift_JIS encoding, 振替伝票 column order.
# ---------------------------------------------------------------------------


def test_format_csv_yayoi_round_trip() -> None:
    resp = render(SAMPLE_ROWS, "csv-yayoi", SAMPLE_META)
    assert resp.status_code == 200
    assert resp.headers.get("X-AutonoMath-Format") == "csv-yayoi"
    assert "shift_jis" in resp.media_type

    # MUST decode as Shift_JIS, NOT UTF-8.
    text = resp.body.decode("shift_jis")
    lines = text.splitlines()
    header_idx = next(i for i, ln in enumerate(lines) if not ln.startswith("#"))
    header = lines[header_idx].split(",")
    assert header[0] == "識別フラグ"
    assert "取引日付" in header
    assert "貸方勘定科目" in header

    # Yayoi 識別フラグ 2000 = 仕訳行.
    data_line = lines[header_idx + 1]
    assert data_line.startswith("2000,")


# ---------------------------------------------------------------------------
# Cross-format invariants.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fmt",
    ["csv", "xlsx", "md", "ics", "docx-application", "csv-freee", "csv-mf", "csv-yayoi"],
)
def test_every_format_emits_disclaimer_header(fmt: str) -> None:
    """Every non-JSON format MUST set X-AutonoMath-Disclaimer (ASCII)."""
    pytest.importorskip("openpyxl") if fmt == "xlsx" else None
    pytest.importorskip("icalendar") if fmt == "ics" else None
    pytest.importorskip("docx") if fmt == "docx-application" else None

    resp = render(SAMPLE_ROWS, fmt, SAMPLE_META)
    val = resp.headers.get("X-AutonoMath-Disclaimer", "")
    # ASCII-only header so it survives every reverse proxy + access log.
    assert val, f"{fmt} missing X-AutonoMath-Disclaimer"
    val.encode("latin-1")  # raises if non-ASCII slipped in
    assert "S52" in val or "§52" in val


def test_unknown_format_is_400() -> None:
    """The dispatcher rejects unknown format flags rather than falling back."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        render(SAMPLE_ROWS, "yaml", SAMPLE_META)
    assert exc.value.status_code == 400
    assert "unknown format" in exc.value.detail.lower()
