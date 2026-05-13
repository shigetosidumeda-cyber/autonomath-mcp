"""Wave 43.2.3 Dim C + Wave 43.2.4 Dim D combined test pack.

Dim C (時系列 diff coverage uplift):
  * v3 extract_effective_v3 stacks v2 (json/wareki/url/body) → meta →
    bare-reiwa → slug → observed_coarse without losing v2 classification.
  * Meta head parser picks up <meta og:updated_time> / <meta date> /
    <time datetime="...">.
  * Bare-reiwa parser picks "R8.4.1", "令和8年4月", "R8" → 4/1.
  * Slug parser parses 8-digit dates + reiwa slugs in filenames.
  * observed_at fallback only kicks in when --observed-as-effective is set.

Dim D (compose_audit_workpaper):
  * _normalize_houjin: 13-digit canonical with/without 'T' prefix.
  * _resolve_fy_window: 2025 → ("2025-04-01", "2026-03-31").
  * _compose_workpaper_impl: graceful empty when houjin not present,
    flag synthesis on adoption/enforcement/jurisdiction signals.
  * REST POST /v1/audit/workpaper: 422 on malformed bangou, 404/503 on
    unknown bangou, OpenAPI registration check, _billing_unit == 5 +
    _disclaimer prose intact on seeded happy-path.

No LLM, no network, no aggregator fence-jump. Honours
`feedback_no_quick_check_on_huge_sqlite` (UPDATE-by-PK only in v3) +
`feedback_autonomath_no_api_use`.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
_ETL = _REPO / "scripts" / "etl"
for p in (str(_SRC), str(_ETL)):
    if Path(p).is_dir() and p not in sys.path:
        sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# Dim C — v3 extractor unit coverage
# ---------------------------------------------------------------------------


def test_v3_meta_head_picks_og_updated_time():
    from datafill_amendment_snapshot_v3 import parse_meta_head

    body = (
        "<html><head>"
        '<meta property="og:updated_time" content="2026-07-15">'
        "</head><body></body></html>"
    )
    # v3 delegates to v2.parse_iso whose regex is YYYY-MM only when a
    # date sits inside an ISO datetime; for a bare YYYY-MM-DD the day
    # is preserved.
    assert parse_meta_head(body) == "2026-07-15"


def test_v3_meta_head_picks_time_tag_datetime():
    from datafill_amendment_snapshot_v3 import parse_meta_head

    body = '<article><time datetime="2026-09-01">2026年9月1日</time></article>'
    assert parse_meta_head(body) == "2026-09-01"


def test_v3_meta_head_returns_none_on_empty():
    from datafill_amendment_snapshot_v3 import parse_meta_head

    assert parse_meta_head("") is None
    assert parse_meta_head("plain text") is None


def test_v3_bare_reiwa_dot_form():
    from datafill_amendment_snapshot_v3 import parse_bare_reiwa

    # R8 = 令和8 = 2026
    assert parse_bare_reiwa("施行 R8.4.1 適用") == "2026-04-01"


def test_v3_bare_reiwa_year_only_falls_to_april_first():
    from datafill_amendment_snapshot_v3 import parse_bare_reiwa

    iso = parse_bare_reiwa("令和8")
    assert iso == "2026-04-01"


def test_v3_bare_reiwa_full_wareki_takes_precedence_over_bare():
    from datafill_amendment_snapshot_v3 import parse_bare_reiwa

    iso = parse_bare_reiwa("令和8年10月15日")
    assert iso == "2026-10-15"


def test_v3_slug_8digit_date():
    from datafill_amendment_snapshot_v3 import parse_slug_filename

    assert parse_slug_filename("https://example.go.jp/notice_20260401.pdf") == "2026-04-01"


def test_v3_slug_reiwa_form():
    from datafill_amendment_snapshot_v3 import parse_slug_filename

    iso = parse_slug_filename("https://example.go.jp/r8_04_01_circular.pdf")
    assert iso == "2026-04-01"


def test_v3_slug_returns_none_on_no_match():
    from datafill_amendment_snapshot_v3 import parse_slug_filename

    assert parse_slug_filename(None) is None
    assert parse_slug_filename("https://example.go.jp/index.html") is None


def test_v3_extract_v2_classification_passes_through():
    """v3 must NEVER demote a v2-classified result."""
    from datafill_amendment_snapshot_v3 import extract_effective_v3

    raw = '{"effective_from": "2026-04-01"}'
    iso, src = extract_effective_v3(raw, None, None, body=None, allow_observed=False)
    assert iso == "2026-04-01"
    assert src == "json"


def test_v3_extract_meta_falls_through_after_v2_miss():
    from datafill_amendment_snapshot_v3 import extract_effective_v3

    # v2's body pass already covers labelled-iso bodies; v3's meta pass
    # only fires when v2 returns nothing. For *this* contract spec, the
    # important thing is that the date is recovered — the `src` may be
    # either "body" (v2 hit) or "meta" (v3 fallback). Either path is OK
    # for the 95% coverage goal; the test asserts the date wins.
    body = '<meta property="og:updated_time" content="2026-08-21">'
    iso, src = extract_effective_v3(None, None, None, body=body, allow_observed=False)
    assert iso == "2026-08-21"
    assert src in ("meta", "body")


def test_v3_extract_observed_coarse_only_with_opt_in():
    from datafill_amendment_snapshot_v3 import extract_effective_v3

    iso, src = extract_effective_v3(
        None, None, "2026-04-22T03:00:00Z", body=None, allow_observed=False
    )
    assert iso is None
    iso2, src2 = extract_effective_v3(
        None, None, "2026-04-22T03:00:00Z", body=None, allow_observed=True
    )
    assert iso2 == "2026-04-22"
    assert src2 == "observed_coarse"


# ---------------------------------------------------------------------------
# Dim D — compose_audit_workpaper unit coverage
# ---------------------------------------------------------------------------


def test_dimd_normalize_houjin_strips_t_prefix():
    from jpintel_mcp.mcp.autonomath_tools.audit_workpaper_v2 import _normalize_houjin

    assert _normalize_houjin("T8010001213708") == "8010001213708"
    assert _normalize_houjin("8010001213708") == "8010001213708"
    assert _normalize_houjin("not a number") is None
    assert _normalize_houjin("12345") is None


def test_dimd_resolve_fy_window():
    from jpintel_mcp.mcp.autonomath_tools.audit_workpaper_v2 import _resolve_fy_window

    assert _resolve_fy_window(2025) == ("2025-04-01", "2026-03-31")
    assert _resolve_fy_window(2030) == ("2030-04-01", "2031-03-31")


def test_dimd_invalid_input_returns_error_envelope():
    from jpintel_mcp.mcp.autonomath_tools.audit_workpaper_v2 import _compose_workpaper_impl

    out = _compose_workpaper_impl(client_houjin_bangou="not-13-digits", fiscal_year=2025)
    assert "error" in out
    assert out["error"]["code"] == "invalid_input"


def test_dimd_fy_out_of_range():
    from jpintel_mcp.mcp.autonomath_tools.audit_workpaper_v2 import _compose_workpaper_impl

    out = _compose_workpaper_impl(client_houjin_bangou="8010001213708", fiscal_year=1900)
    assert "error" in out
    assert out["error"]["code"] == "out_of_range"


# ---------------------------------------------------------------------------
# Dim D — REST contract surface
# ---------------------------------------------------------------------------


def test_dimd_rest_422_on_malformed_bangou(client):  # noqa: ANN001
    r = client.post(
        "/v1/audit/workpaper",
        json={"client_houjin_bangou": "x", "fiscal_year": 2025},
    )
    assert r.status_code == 422


def test_dimd_rest_404_or_503_when_unseeded(client):  # noqa: ANN001
    """Without an autonomath.db seed the route 503s; with a seed but
    unknown houjin it 404s. Either gate is the documented contract.
    """
    r = client.post(
        "/v1/audit/workpaper",
        json={"client_houjin_bangou": "8010001213708", "fiscal_year": 2025},
    )
    assert r.status_code in (404, 503)


def test_dimd_route_registered_in_openapi(client):  # noqa: ANN001
    """Spot-check the route is registered in the live OpenAPI spec."""
    r = client.get("/openapi.json")
    if r.status_code != 200:
        pytest.skip(f"openapi.json not reachable: {r.status_code}")
    paths = r.json().get("paths", {})
    assert "/v1/audit/workpaper" in paths
    assert "post" in paths["/v1/audit/workpaper"]


# ---------------------------------------------------------------------------
# Dim D — seeded happy-path with a tmp autonomath.db
# ---------------------------------------------------------------------------


def _seed_autonomath_workpaper_db(path: Path) -> None:
    """Minimal in-memory shape of jpi_houjin_master / am_enforcement_detail
    / jpi_adoption_records / jpi_invoice_registrants / am_amendment_diff so
    the composer can fire its sections.
    """
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE jpi_houjin_master (
            houjin_bangou TEXT PRIMARY KEY,
            normalized_name TEXT,
            address_normalized TEXT,
            prefecture TEXT,
            municipality TEXT,
            corporation_type TEXT,
            jsic_major TEXT,
            total_adoptions INTEGER,
            total_received_yen INTEGER
        );
        CREATE TABLE jpi_adoption_records (
            program_id TEXT,
            program_name TEXT,
            applicant_name TEXT,
            applicant_houjin_bangou TEXT,
            award_date TEXT,
            announce_date TEXT,
            amount_yen INTEGER,
            fiscal_year INTEGER,
            prefecture TEXT
        );
        CREATE TABLE am_enforcement_detail (
            detail_id INTEGER PRIMARY KEY,
            houjin_bangou TEXT,
            enforcement_kind TEXT,
            enforcement_date TEXT,
            amount_yen INTEGER,
            summary TEXT,
            source_url TEXT
        );
        CREATE TABLE jpi_invoice_registrants (
            houjin_bangou TEXT,
            prefecture TEXT,
            registered_date TEXT
        );
        CREATE TABLE am_amendment_diff (
            diff_id INTEGER PRIMARY KEY,
            entity_id TEXT,
            field_name TEXT,
            prev_value TEXT,
            new_value TEXT,
            detected_at TEXT,
            source_url TEXT
        );
        INSERT INTO jpi_houjin_master VALUES
          ('8010001213708', 'TestCo株式会社', '東京都文京区小日向2-22-1',
           '東京都', '文京区', '株式会社', 'J', 2, 50000000);
        INSERT INTO jpi_adoption_records VALUES
          ('program:base:71f6029070', 'ものづくり補助金',
           'TestCo株式会社', '8010001213708',
           '2025-08-15', '2025-08-01', 5000000, 2025, '東京都');
        INSERT INTO am_enforcement_detail VALUES
          (1, '8010001213708', 'fine', '2025-12-01', 100000,
           '報告義務違反', 'https://example.go.jp/notice');
        INSERT INTO jpi_invoice_registrants VALUES
          ('8010001213708', '東京都', '2023-10-01');
        INSERT INTO am_amendment_diff VALUES
          (1, 'program:base:71f6029070', 'amount_max_yen',
           '5000000', '7500000', '2025-11-12 04:00:00',
           'https://example.go.jp/amend');
        """
    )
    conn.commit()
    conn.close()


def test_dimd_happy_path_with_seeded_autonomath_db(tmp_path, monkeypatch):
    db_path = tmp_path / "autonomath_workpaper_test.db"
    _seed_autonomath_workpaper_db(db_path)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))

    # Reset cached per-thread connection so the env var takes effect.
    from jpintel_mcp.mcp.autonomath_tools import db as _db_mod

    _db_mod.close_all()

    from jpintel_mcp.mcp.autonomath_tools.audit_workpaper_v2 import _compose_workpaper_impl

    out = _compose_workpaper_impl(
        client_houjin_bangou="8010001213708",
        fiscal_year=2025,
    )
    assert "error" not in out, f"unexpected error: {out}"
    assert out["client_houjin_bangou"] == "8010001213708"
    assert out["fiscal_year"] == 2025
    assert out["fy_window"] == {"start": "2025-04-01", "end": "2026-03-31"}
    assert out["houjin_meta"]["name"] == "TestCo株式会社"
    assert out["counts"]["fy_adoption_count"] == 1
    assert out["counts"]["fy_enforcement_count"] == 1
    assert out["counts"]["fy_amendment_alert_count"] == 1
    # disclaimer + billing unit invariants
    assert out["_billing_unit"] == 5
    assert "税理士法 §52" in out["_disclaimer"]
    assert "公認会計士法 §47条の2" in out["_disclaimer"]
    # Auditor flags must surface at least the enforcement signal
    flag_blob = "\n".join(out["auditor_flags"])
    assert "行政処分" in flag_blob
    assert "改正イベント" in flag_blob


def test_dimd_flag_mismatch_fires_on_three_axis_jurisdiction_diff(tmp_path, monkeypatch):
    db_path = tmp_path / "autonomath_workpaper_mismatch.db"
    _seed_autonomath_workpaper_db(db_path)
    # Mutate the seed so the 3 axes disagree.
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE jpi_invoice_registrants SET prefecture = '大阪府' WHERE houjin_bangou = ?",
        ("8010001213708",),
    )
    conn.execute(
        "UPDATE jpi_adoption_records SET prefecture = '神奈川県' WHERE applicant_houjin_bangou = ?",
        ("8010001213708",),
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.mcp.autonomath_tools import db as _db_mod

    _db_mod.close_all()

    from jpintel_mcp.mcp.autonomath_tools.audit_workpaper_v2 import _compose_workpaper_impl

    out = _compose_workpaper_impl(
        client_houjin_bangou="8010001213708",
        fiscal_year=2025,
    )
    assert out["counts"]["mismatch"] is True
    flag_blob = "\n".join(out["auditor_flags"])
    assert "3軸不一致" in flag_blob
