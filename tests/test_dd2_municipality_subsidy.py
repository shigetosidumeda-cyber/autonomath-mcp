"""DD2 — 自治体 1,714 市町村 補助金 OCR + structured-ingest test suite.

Coverage map (matches DD2 task scope 2026-05-17):

  1. test_migration_217_applies_idempotently     — schema, 5 indexes, 2 views
  2. test_migration_217_rollback_idempotent      — drop is idempotent
  3. test_manifest_builder_smoke                 — 1,700+ municipalities, 47 prefectures
  4. test_manifest_aggregator_rejected_count     — bans aggregator hosts
  5. test_crawler_module_imports                 — no LLM imports, primary host regex tight
  6. test_textract_module_imports_and_defaults   — region=apse1, budget=$4,500 default
  7. test_ingest_regex_extractors                — amount, rate, deadline, jsic, corp_form
  8. test_ingest_extract_row_end_to_end          — Textract blocks → row dict
  9. test_mcp_tool_returns_envelope              — 4-axis cohort filter + 5-axis citation
 10. test_mcp_tool_invalid_jsic_major            — invalid_enum surfaces correctly
 11. test_mcp_tool_invalid_target_size           — invalid_enum surfaces correctly
 12. test_no_llm_imports_in_dd2_files            — anthropic / openai / claude_agent_sdk absent
 13. test_view_v_municipality_subsidy_by_prefecture  — 47-prefecture aggregate works
 14. test_view_v_municipality_subsidy_by_jsic_major  — JSIC major fan-out works
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = _REPO_ROOT / "scripts" / "migrations" / "wave24_217_am_municipality_subsidy.sql"
_ROLLBACK = (
    _REPO_ROOT / "scripts" / "migrations" / "wave24_217_am_municipality_subsidy_rollback.sql"
)
_MANIFEST_BUILDER = _REPO_ROOT / "scripts" / "etl" / "build_dd2_municipality_manifest_2026_05_17.py"
_CRAWLER = _REPO_ROOT / "scripts" / "etl" / "crawl_municipality_subsidy_2026_05_17.py"
_TEXTRACT = _REPO_ROOT / "scripts" / "aws_credit_ops" / "textract_municipality_bulk_2026_05_17.py"
_INGEST = _REPO_ROOT / "scripts" / "etl" / "ingest_dd2_municipality_subsidy_2026_05_17.py"
_MCP_TOOL = (
    _REPO_ROOT / "src" / "jpintel_mcp" / "mcp" / "autonomath_tools" / "dd2_municipality_tools.py"
)
_MANIFEST = _REPO_ROOT / "data" / "etl_dd2_municipality_manifest_2026_05_17.json"


def _load_module_from(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register before exec — dataclasses introspection (slots=True) looks
    # up ``sys.modules[cls.__module__]`` to resolve annotations.
    import sys as _sys

    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. Migration applies idempotently.
# ---------------------------------------------------------------------------


def test_migration_217_applies_idempotently(tmp_path: Path) -> None:
    """Acceptance: am_municipality_subsidy + 5 indexes + 2 views after twice apply."""
    db_path = tmp_path / "test_dd2.db"
    sql = _MIGRATION.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql)
        conn.executescript(sql)  # second apply must succeed
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'am_municipality%'"
            )
        }
        assert "am_municipality_subsidy" in tables
        indexes = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name LIKE 'ix_am_munic_subsidy_%'"
            )
        }
        assert len(indexes) == 5, f"expected 5 indexes, got {indexes}"
        views = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='view' AND name LIKE 'v_municipality_subsidy_%'"
            )
        }
        assert views == {
            "v_municipality_subsidy_by_prefecture",
            "v_municipality_subsidy_by_jsic_major",
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Rollback is idempotent.
# ---------------------------------------------------------------------------


def test_migration_217_rollback_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test_dd2.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_MIGRATION.read_text(encoding="utf-8"))
        conn.executescript(_ROLLBACK.read_text(encoding="utf-8"))
        conn.executescript(_ROLLBACK.read_text(encoding="utf-8"))  # second drop OK
        tables = list(
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'am_municipality%'"
            )
        )
        assert tables == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. Manifest builder smoke — 1,700+ municipalities, 47 prefectures.
# ---------------------------------------------------------------------------


def test_manifest_builder_smoke() -> None:
    """Acceptance: data/etl_dd2_municipality_manifest_2026_05_17.json exists,
    holds 1,700+ municipalities across 47 prefectures."""
    if not _MANIFEST.exists():
        pytest.skip("manifest not yet generated (CI builds on demand)")
    raw = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert raw["row_total"] >= 1700
    assert raw["row_total"] <= 1750
    prefectures = {m["prefecture"] for m in raw["municipalities"] if m["prefecture"]}
    assert len(prefectures) >= 45  # 47 - small tail of unmapped names


# ---------------------------------------------------------------------------
# 4. Manifest aggregator-rejected count is honest.
# ---------------------------------------------------------------------------


def test_manifest_aggregator_rejected_count() -> None:
    if not _MANIFEST.exists():
        pytest.skip("manifest not yet generated")
    raw = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    blacklist = raw["aggregator_blacklist"]
    assert "noukaweb" in blacklist
    assert "hojyokin-portal" in blacklist
    # The crawler-side constraints carry a 1 req / 3 sec floor.
    assert raw["crawl_constraints"]["req_per_sec"] <= 1.0 / 3.0 + 1e-9
    # Budget envelope must keep worst case well under $19,490 hard-stop.
    assert raw["ocr_constraints"]["worst_case_usd"] < 19490


# ---------------------------------------------------------------------------
# 5. Crawler module imports and exposes the right surface.
# ---------------------------------------------------------------------------


def test_crawler_module_imports() -> None:
    mod = _load_module_from(_CRAWLER, "dd2_crawl_municipality")
    assert hasattr(mod, "CrawlConfig")
    assert hasattr(mod, "CrawlStats")
    assert hasattr(mod, "_is_primary_host")
    assert hasattr(mod, "_is_aggregator")

    assert mod._is_primary_host("https://www.city.shinjuku.lg.jp/x.pdf") is True
    # bare pref. with prefecture stem is allowed
    assert mod._is_primary_host("https://www.pref.tochigi.jp/g03.html") is True
    # non-primary domain is rejected
    assert mod._is_primary_host("https://example.com/x.pdf") is False
    assert mod._is_primary_host("https://noukaweb.example.com/x.pdf") is False
    assert mod._is_aggregator("https://noukaweb.example.com/list") is True
    assert mod._is_aggregator("https://www.city.shinjuku.lg.jp/x.pdf") is False


# ---------------------------------------------------------------------------
# 6. Textract module imports + budget default = $4,500, region = apse1.
# ---------------------------------------------------------------------------


def test_textract_module_imports_and_defaults() -> None:
    mod = _load_module_from(_TEXTRACT, "dd2_textract_municipality")
    ns = mod._parse_args(["--dry-run"])
    assert ns.budget_usd == 4500.0
    assert ns.textract_region == "ap-southeast-1"
    assert ns.commit is False
    assert ns.raw_bucket == "jpcite-credit-993693061769-202605-derived"
    assert ns.out_prefix.startswith("municipality_ocr")


# ---------------------------------------------------------------------------
# 7. Ingest regex extractors.
# ---------------------------------------------------------------------------


def test_ingest_regex_extractors() -> None:
    mod = _load_module_from(_INGEST, "dd2_ingest_municipality")
    text = (
        "令和7年度 省エネ設備導入補助金 募集要項\n"
        "対象事業者: 株式会社・合同会社・個人事業主\n"
        "対象業種: 製造業, 情報通信業\n"
        "補助率: 1/2 以内\n"
        "上限: 1,000,000円\n"
        "締切: 令和7年12月15日\n"
    )
    assert mod._extract_program_name(text.splitlines()) is not None
    assert mod._extract_amount_yen_max(text) == 1_000_000
    rate = mod._extract_subsidy_rate(text)
    assert rate is not None and abs(rate - 0.5) < 1e-9
    assert mod._extract_deadline(text) == "2025-12-15"
    assert set(mod._extract_jsic_majors(text)) >= {"E", "G"}
    forms = set(mod._extract_corporate_forms(text))
    assert forms >= {"kabushiki", "godo", "kojin_jigyou"}


# ---------------------------------------------------------------------------
# 8. End-to-end Textract block → row dict.
# ---------------------------------------------------------------------------


def test_ingest_extract_row_end_to_end() -> None:
    mod = _load_module_from(_INGEST, "dd2_ingest_municipality_e2e")
    blocks: list[dict[str, Any]] = [
        {"BlockType": "PAGE", "Text": ""},
        {"BlockType": "LINE", "Text": "令和7年度 創業支援補助金 募集要項"},
        {"BlockType": "LINE", "Text": "対象: 株式会社・個人事業主"},
        {"BlockType": "LINE", "Text": "対象業種: 製造業"},
        {"BlockType": "LINE", "Text": "補助率: 50%"},
        {"BlockType": "LINE", "Text": "上限額 500,000円"},
        {"BlockType": "LINE", "Text": "申請期限: 令和7年6月30日"},
    ]
    municipality = {
        "municipality_code": "13104",
        "prefecture": "東京都",
        "municipality_name": "新宿区",
        "municipality_type": "special",
    }
    row = mod._extract_row(
        municipality=municipality,
        blocks=blocks,
        source_url="https://www.city.shinjuku.lg.jp/x.pdf",
        sha="deadbeef",
        s3_pdf="s3://x/y.pdf",
        s3_ocr="s3://x/y.json",
        ocr_job_id="job-1",
        ocr_confidence=0.91,
        ocr_page_count=4,
    )
    assert row is not None
    assert row["municipality_code"] == "13104"
    assert row["program_name"].startswith("令和7年度")
    assert row["amount_yen_max"] == 500_000
    assert abs((row["subsidy_rate"] or 0.0) - 0.5) < 1e-9
    assert row["deadline"] == "2025-06-30"
    assert "E" in json.loads(row["target_jsic_majors"])
    assert "kabushiki" in json.loads(row["target_corporate_forms"])
    assert row["license"] == "public_domain_jp_gov"
    assert row["sha256"] == "deadbeef"
    assert row["ocr_job_id"] == "job-1"


# ---------------------------------------------------------------------------
# 9. MCP tool returns the canonical envelope with 5-axis citation.
# ---------------------------------------------------------------------------


def test_mcp_tool_returns_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "dd2_mcp.db"
    sql = _MIGRATION.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO am_municipality_subsidy "
            "(municipality_code, prefecture, municipality_name, municipality_type, "
            " program_name, amount_yen_max, target_jsic_majors, source_url, "
            " source_pdf_s3_uri, ocr_s3_uri, ocr_job_id, sha256, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "13104",
                "東京都",
                "新宿区",
                "special",
                "省エネ補助金",
                1_500_000,
                '["F","G"]',
                "https://www.city.shinjuku.lg.jp/x.pdf",
                "s3://raw/x.pdf",
                "s3://ocr/x.json",
                "job-1",
                "abc123",
                "2026-05-17T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.mcp.autonomath_tools import dd2_municipality_tools as mod

    r = mod._find_municipality_subsidies_impl(prefecture="東京都", jsic_major="G")
    assert r["total"] == 1
    row = r["results"][0]
    # 5-axis citation per row.
    assert row["source_url"].startswith("https://www.city.shinjuku.lg.jp")
    assert row["source_pdf_s3_uri"].startswith("s3://")
    assert row["ocr_s3_uri"].startswith("s3://")
    assert row["ocr_job_id"] == "job-1"
    assert row["sha256"] == "abc123"
    assert row["source_attribution"]["license"] == "public_domain_jp_gov"
    assert r["_billing_unit"] == 1


# ---------------------------------------------------------------------------
# 10-11. MCP tool invalid args.
# ---------------------------------------------------------------------------


def test_mcp_tool_invalid_jsic_major(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "dd2_inv.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_MIGRATION.read_text(encoding="utf-8"))
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.mcp.autonomath_tools import dd2_municipality_tools as mod

    r = mod._find_municipality_subsidies_impl(jsic_major="X")
    assert r["error"]["code"] == "invalid_enum"
    assert r["error"]["field"] == "jsic_major"


def test_mcp_tool_invalid_target_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "dd2_inv2.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_MIGRATION.read_text(encoding="utf-8"))
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.mcp.autonomath_tools import dd2_municipality_tools as mod

    r = mod._find_municipality_subsidies_impl(target_size="gigantic")
    assert r["error"]["code"] == "invalid_enum"
    assert r["error"]["field"] == "target_size"


# ---------------------------------------------------------------------------
# 12. NO LLM imports in any DD2 file.
# ---------------------------------------------------------------------------


_BANNED_MODULES = ("anthropic", "openai", "claude_agent_sdk")


@pytest.mark.parametrize(
    "path",
    [_MANIFEST_BUILDER, _CRAWLER, _TEXTRACT, _INGEST, _MCP_TOOL],
)
def test_no_llm_imports_in_dd2_files(path: Path) -> None:
    """Acceptance: NO LLM SDK imports in any DD2 file (NO LLM API constraint)."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                assert root not in _BANNED_MODULES, (
                    f"banned LLM import in {path.name}: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            assert root not in _BANNED_MODULES, (
                f"banned LLM import-from in {path.name}: {node.module}"
            )


# ---------------------------------------------------------------------------
# 13. View v_municipality_subsidy_by_prefecture.
# ---------------------------------------------------------------------------


def test_view_v_municipality_subsidy_by_prefecture(tmp_path: Path) -> None:
    db_path = tmp_path / "dd2_view1.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_MIGRATION.read_text(encoding="utf-8"))
        for pref, code, amt in (
            ("東京都", "13104", 1_000_000),
            ("東京都", "13105", 2_000_000),
            ("大阪府", "27100", 3_000_000),
        ):
            conn.execute(
                "INSERT INTO am_municipality_subsidy (municipality_code, prefecture, "
                "municipality_name, municipality_type, program_name, amount_yen_max, "
                "source_url, sha256, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (code, pref, "x", "regular", "p", amt, "https://x.lg.jp/p", "s", "t"),
            )
        conn.commit()
        rows = list(conn.execute("SELECT * FROM v_municipality_subsidy_by_prefecture"))
    finally:
        conn.close()
    by_pref = {r[0]: r for r in rows}
    assert by_pref["東京都"][1] == 2  # subsidy_count
    assert by_pref["東京都"][2] == 2  # municipality_with_subsidy_count
    assert by_pref["大阪府"][1] == 1
    assert by_pref["大阪府"][3] == 3_000_000  # avg_amount_yen_max


# ---------------------------------------------------------------------------
# 14. View v_municipality_subsidy_by_jsic_major.
# ---------------------------------------------------------------------------


def test_view_v_municipality_subsidy_by_jsic_major(tmp_path: Path) -> None:
    db_path = tmp_path / "dd2_view2.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_MIGRATION.read_text(encoding="utf-8"))
        for code, majors in (
            ("13104", '["F","G"]'),
            ("13105", '["G"]'),
            ("27100", None),  # __any__
        ):
            conn.execute(
                "INSERT INTO am_municipality_subsidy (municipality_code, prefecture, "
                "municipality_name, municipality_type, program_name, amount_yen_max, "
                "target_jsic_majors, source_url, sha256, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (code, "東京都", "x", "regular", "p", 100, majors, "https://x.lg.jp/p", "s", "t"),
            )
        conn.commit()
        rows = list(
            conn.execute(
                "SELECT jsic_major, subsidy_count FROM v_municipality_subsidy_by_jsic_major"
            )
        )
    finally:
        conn.close()
    by_major = dict(rows)
    assert by_major.get("G") == 2
    assert by_major.get("F") == 1
    assert by_major.get("__any__") == 1
