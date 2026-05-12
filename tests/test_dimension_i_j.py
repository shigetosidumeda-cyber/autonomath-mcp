"""Tests for Wave 43.2.9 Dim I cross-source agreement + Wave 43.2.10 Dim J
FDI 80-country surface.

Covers migrations 265+266 schema + idempotency + CHECK constraints,
the cross_source_score_v2 REST + MCP tool happy/sad paths, the
foreign_fdi_v2 list+detail REST endpoints, the fill_fdi_80country_2x
deterministic parser, LLM-import 0 regression, and boot manifest refs.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sqlite3
import sys
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

MIG_265 = REPO_ROOT / "scripts" / "migrations" / "265_cross_source_agreement.sql"
MIG_266 = REPO_ROOT / "scripts" / "migrations" / "266_fdi_country_80.sql"
SRC_CSS_REST = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "cross_source_score_v2.py"
SRC_FDI_REST = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "foreign_fdi_v2.py"
SRC_CSS_MCP = (
    REPO_ROOT
    / "src"
    / "jpintel_mcp"
    / "mcp"
    / "autonomath_tools"
    / "cross_source_score_v2.py"
)
ETL_FDI = REPO_ROOT / "scripts" / "etl" / "fill_fdi_80country_2x.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _apply_sql(conn: sqlite3.Connection, sql_path: pathlib.Path) -> None:
    sql = sql_path.read_text(encoding="utf-8")
    conn.executescript(sql)


def _build_am_fixture(tmp_path: pathlib.Path) -> sqlite3.Connection:
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Minimal stub of am_entity_facts so 265 doesn't choke on FK-like joins
    # in helper queries (the migration itself does not declare a FK, but
    # downstream cron does selects against it).
    conn.executescript(
        """
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            confirming_source_count INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    _apply_sql(conn, MIG_265)
    _apply_sql(conn, MIG_266)
    return conn


def _import_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Migration / schema
# ---------------------------------------------------------------------------


def test_mig_265_creates_agreement_table(tmp_path: pathlib.Path) -> None:
    conn = _build_am_fixture(tmp_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(am_fact_source_agreement)").fetchall()}
    assert {"fact_id", "agreement_ratio", "sources_total", "sources_agree", "canonical_value", "source_breakdown"}.issubset(cols)
    # view + run-log
    views = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()}
    assert "v_fact_source_agreement" in views
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "am_fact_source_agreement_run_log" in tables
    conn.close()


def test_mig_265_check_constraints(tmp_path: pathlib.Path) -> None:
    conn = _build_am_fixture(tmp_path)
    # agreement_ratio out of bounds rejected
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO am_fact_source_agreement (fact_id, entity_id, field_name, agreement_ratio, sources_total, sources_agree) VALUES (?, ?, ?, ?, ?, ?)",
            (1, "E-1", "f", 1.5, 3, 3),
        )
    # sources_agree > sources_total rejected
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO am_fact_source_agreement (fact_id, entity_id, field_name, agreement_ratio, sources_total, sources_agree) VALUES (?, ?, ?, ?, ?, ?)",
            (2, "E-2", "f", 0.5, 1, 3),
        )
    conn.close()


def test_mig_265_idempotent(tmp_path: pathlib.Path) -> None:
    conn = _build_am_fixture(tmp_path)
    # Re-apply – idempotent (IF NOT EXISTS)
    _apply_sql(conn, MIG_265)
    n = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='am_fact_source_agreement'"
    ).fetchone()[0]
    assert n == 1
    conn.close()


def test_mig_266_seeds_80_countries(tmp_path: pathlib.Path) -> None:
    conn = _build_am_fixture(tmp_path)
    rows = conn.execute("SELECT count(*) FROM am_fdi_country").fetchone()[0]
    # The migration seeds the 80-country cohort (≥ 80, may include a few
    # priority partners beyond the headline 80 — exact count is bounded
    # below by the spec, not equality-pinned).
    assert rows >= 80
    # Sanity: G7 = 7 rows
    g7 = conn.execute("SELECT count(*) FROM am_fdi_country WHERE is_g7 = 1").fetchone()[0]
    assert g7 == 7
    # has_dta sane on JP self-anchor
    jp = conn.execute("SELECT * FROM am_fdi_country WHERE country_iso = 'JP'").fetchone()
    assert jp is not None
    conn.close()


def test_mig_266_region_check(tmp_path: pathlib.Path) -> None:
    conn = _build_am_fixture(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO am_fdi_country (country_iso, country_name_ja, country_name_en, region, source_url, source_fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("ZZ", "テスト", "Test", "atlantis", "https://www.mofa.go.jp/region/test/", "2026-05-12"),
        )
    conn.close()


def test_mig_266_iso_check(tmp_path: pathlib.Path) -> None:
    conn = _build_am_fixture(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO am_fdi_country (country_iso, country_name_ja, country_name_en, region, source_url, source_fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("usa", "アメリカ", "USA", "north_america", "https://www.mofa.go.jp/", "2026-05-12"),
        )
    conn.close()


# ---------------------------------------------------------------------------
# REST: cross_source_score_v2
# ---------------------------------------------------------------------------


def test_rest_css_v2_shape(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    am = _build_am_fixture(tmp_path)
    am.execute(
        "INSERT INTO am_fact_source_agreement (fact_id, entity_id, field_name, agreement_ratio, sources_total, sources_agree, canonical_value, source_breakdown, egov_value, nta_value, meti_value) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            42, "NTA-foo", "tax_rate_pct", 0.67, 3, 2, "10",
            json.dumps({"egov": 1, "nta": 1, "meti": 1}),
            "10", "10", "10.5",
        ),
    )
    am.commit()
    am.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "autonomath.db"))
    mod = _import_module("jpintel_mcp.api.cross_source_score_v2", SRC_CSS_REST)

    conn = mod._open_autonomath_ro()
    row = mod._fetch_agreement_row(conn, 42)
    conn.close()
    assert row is not None
    body = mod._shape_response(row)
    assert body["fact_id"] == 42
    assert body["agreement_ratio"] == pytest.approx(0.67, abs=1e-6)
    assert body["sources_total"] == 3
    assert body["confidence_band"] in {"high", "medium"}
    assert body["per_source_values"]["meti"] == "10.5"
    assert body["_billing_unit"] == 1
    assert "_disclaimer" in body


def test_rest_css_v2_not_found(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _build_am_fixture(tmp_path).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "autonomath.db"))
    mod = _import_module("jpintel_mcp.api.cross_source_score_v2_b", SRC_CSS_REST)
    conn = mod._open_autonomath_ro()
    row = mod._fetch_agreement_row(conn, 999)
    conn.close()
    assert row is None


# ---------------------------------------------------------------------------
# MCP: cross_source_score_am
# ---------------------------------------------------------------------------


def test_mcp_css_score_impl_happy(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    am = _build_am_fixture(tmp_path)
    am.execute(
        "INSERT INTO am_fact_source_agreement (fact_id, entity_id, field_name, agreement_ratio, sources_total, sources_agree, canonical_value, source_breakdown) VALUES (?,?,?,?,?,?,?,?)",
        (
            7, "NTA-bar", "rate", 1.0, 2, 2, "5",
            json.dumps({"egov": 1, "nta": 1}),
        ),
    )
    am.commit()
    am.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "autonomath.db"))
    # Lazy import of the impl helper to avoid triggering @mcp.tool registration
    # with a real server fixture in the unit test path.
    src = SRC_CSS_MCP.read_text(encoding="utf-8")
    # Ensure the public impl entrypoint exists by name.
    assert "_cross_source_score_am_impl" in src

    mod = _import_module(
        "jpintel_mcp.mcp.autonomath_tools.cross_source_score_v2", SRC_CSS_MCP
    )
    out = mod._cross_source_score_am_impl(fact_id=7)
    assert out["fact_id"] == 7
    assert out["sources_total"] == 2
    assert out["confidence_band"] in {"medium", "high"}
    assert out["_billing_unit"] == 1


def test_mcp_css_invalid_input() -> None:
    mod = _import_module(
        "jpintel_mcp.mcp.autonomath_tools.cross_source_score_v2_b", SRC_CSS_MCP
    )
    out = mod._cross_source_score_am_impl(fact_id="not-a-number")
    assert out.get("code") == "invalid_input"


def test_mcp_css_not_found(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_am_fixture(tmp_path).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "autonomath.db"))
    mod = _import_module(
        "jpintel_mcp.mcp.autonomath_tools.cross_source_score_v2_c", SRC_CSS_MCP
    )
    out = mod._cross_source_score_am_impl(fact_id=12345)
    assert out.get("code") == "not_found"


# ---------------------------------------------------------------------------
# REST: foreign_fdi_v2
# ---------------------------------------------------------------------------


def test_rest_fdi_list_filters(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_am_fixture(tmp_path).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "autonomath.db"))
    mod = _import_module("jpintel_mcp.api.foreign_fdi_v2", SRC_FDI_REST)

    sql, args = mod._build_list_query(
        region="eu", is_g7=None, is_oecd=1, is_asean=None, is_eu=1, has_dta=None
    )
    assert "WHERE" in sql and "region = ?" in sql and "is_oecd = ?" in sql and "is_eu = ?" in sql
    assert args == ["eu", 1, 1]
    # _build_list_query trails ``ORDER BY country_iso ASC LIMIT ?`` so we
    # only need to supply the limit param at call time.
    conn = mod._open_autonomath_ro()
    rows = conn.execute(sql, [*args, 100]).fetchall()
    conn.close()
    # All seeded EU + OECD intersect ought to include DE / FR.
    isos = {r["country_iso"] for r in rows}
    assert {"DE", "FR"}.issubset(isos)


def test_rest_fdi_detail_row_shape(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_am_fixture(tmp_path).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "autonomath.db"))
    mod = _import_module("jpintel_mcp.api.foreign_fdi_v2_b", SRC_FDI_REST)

    conn = mod._open_autonomath_ro()
    row = conn.execute(
        "SELECT * FROM v_fdi_country_public WHERE country_iso = 'JP'"
    ).fetchone()
    conn.close()
    assert row is not None
    shaped = mod._row_to_dict(row)
    assert shaped["country_iso"] == "JP"
    assert shaped["country_name_ja"] == "日本"
    assert isinstance(shaped["is_g7"], bool)
    assert shaped["license"] == "gov_standard"


# ---------------------------------------------------------------------------
# ETL deterministic parsers
# ---------------------------------------------------------------------------


def test_etl_parse_capital_yen() -> None:
    mod = _import_module("scripts.etl.fill_fdi_80country_2x", ETL_FDI)
    assert mod._parse_capital_yen("最低資本金 500 万円 が必要") == 5_000_000
    assert mod._parse_capital_yen("minimum capital 1,000,000 JPY") == 1_000_000
    assert mod._parse_capital_yen("nothing relevant here") is None


def test_etl_classify_visa() -> None:
    mod = _import_module("scripts.etl.fill_fdi_80country_2x_b", ETL_FDI)
    assert mod._classify_visa("経営・管理ビザの取得が必要です") in {"standard", "expedited"}
    assert mod._classify_visa("nothing") == "unknown"


def test_etl_primary_only_gate() -> None:
    mod = _import_module("scripts.etl.fill_fdi_80country_2x_c", ETL_FDI)
    assert mod._is_primary("https://www.mofa.go.jp/region/abc/") is True
    assert mod._is_primary("https://www.jetro.go.jp/world/us/") is True
    assert mod._is_primary("https://example.com/x") is False
    assert mod._is_banned("https://wikipedia.org/foo") is True


# ---------------------------------------------------------------------------
# Manifest + LLM-import audit
# ---------------------------------------------------------------------------


def test_boot_manifest_references_265_266() -> None:
    manifest = (
        REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"
    ).read_text(encoding="utf-8")
    assert "265_cross_source_agreement.sql" in manifest, (
        "265 migration must be in autonomath_boot_manifest.txt"
    )
    assert "266_fdi_country_80.sql" in manifest, (
        "266 migration must be in autonomath_boot_manifest.txt"
    )


_LLM_PATTERNS = (
    re.compile(r"\bimport\s+anthropic\b"),
    re.compile(r"\bfrom\s+anthropic\b"),
    re.compile(r"\bimport\s+openai\b"),
    re.compile(r"\bfrom\s+openai\b"),
    re.compile(r"\bimport\s+google\.generativeai\b"),
    re.compile(r"\bclaude_agent_sdk\b"),
    re.compile(r"\bANTHROPIC_API_KEY\b"),
    re.compile(r"\bOPENAI_API_KEY\b"),
    re.compile(r"\bGEMINI_API_KEY\b"),
)


@pytest.mark.parametrize(
    "path",
    [SRC_CSS_REST, SRC_FDI_REST, SRC_CSS_MCP, ETL_FDI, MIG_265, MIG_266],
)
def test_no_llm_imports_in_dim_i_j(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    for pat in _LLM_PATTERNS:
        m = pat.search(text)
        assert m is None, f"{path.name}: LLM-API marker {pat.pattern!r} found"
