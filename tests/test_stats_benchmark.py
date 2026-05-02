from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _insert_stat_cell(
    conn: sqlite3.Connection,
    cell_id: str,
    *,
    jsic_code_major: str = "D",
    jsic_name_major: str = "建設業",
    region_code: str = "13000",
    region_name: str = "東京都",
    scale_code: str,
    scale_bucket: str,
    establishment_count: int | None,
    employee_count_total: int | None,
) -> None:
    conn.execute(
        "INSERT INTO am_entities("
        "canonical_id, record_kind, source_topic, primary_name, source_url, "
        "fetched_at, raw_json, created_at, updated_at"
        ") VALUES (?,?,?,?,?,?,?,?,?)",
        (
            cell_id,
            "statistic",
            "18_estat_industry_distribution",
            f"{jsic_name_major} {region_name} {scale_bucket}",
            "https://www.e-stat.go.jp/stat-search/files",
            "2026-05-01T00:00:00Z",
            "{}",
            "2026-05-01T00:00:00Z",
            "2026-05-01T00:00:00Z",
        ),
    )

    def fact_text(field: str, value: str) -> None:
        conn.execute(
            "INSERT INTO am_entity_facts(entity_id, field_name, field_value_text, field_kind) "
            "VALUES (?,?,?,?)",
            (cell_id, field, value, "text"),
        )

    def fact_num(field: str, value: int | None) -> None:
        conn.execute(
            "INSERT INTO am_entity_facts("
            "entity_id, field_name, field_value_numeric, field_kind"
            ") VALUES (?,?,?,?)",
            (cell_id, field, value, "number"),
        )

    fact_text("jsic_code_major", jsic_code_major)
    fact_text("jsic_name_major", jsic_name_major)
    fact_text("jsic_code_medium", jsic_code_major)
    fact_text("jsic_name_medium", jsic_name_major)
    fact_text("region_code", region_code)
    fact_text("region_name", region_name)
    fact_text("scale_code", scale_code)
    fact_text("scale_bucket", scale_bucket)
    fact_text("temporal.statistic.raw", "令和3年(2021)")
    fact_text("statistic_source_title", "令和3年経済センサス-活動調査 第3表")
    fact_num("statistic.establishment_count", establishment_count)
    fact_num("statistic.employee_count_total", employee_count_total)


def _build_stats_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE am_entities (
                canonical_id TEXT PRIMARY KEY,
                record_kind TEXT NOT NULL,
                source_topic TEXT,
                primary_name TEXT NOT NULL,
                source_url TEXT,
                fetched_at TEXT,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE am_entity_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                field_value_text TEXT,
                field_value_numeric REAL,
                field_kind TEXT NOT NULL DEFAULT 'text'
            );
            """
        )
        _insert_stat_cell(
            conn,
            "stat:D:13000:total",
            scale_code="00",
            scale_bucket="総数",
            establishment_count=999,
            employee_count_total=999,
        )
        _insert_stat_cell(
            conn,
            "stat:D:13000:01",
            scale_code="01",
            scale_bucket="1～4人",
            establishment_count=10,
            employee_count_total=20,
        )
        _insert_stat_cell(
            conn,
            "stat:D:13000:02",
            scale_code="02",
            scale_bucket="5～9人",
            establishment_count=5,
            employee_count_total=30,
        )
        _insert_stat_cell(
            conn,
            "stat:D:13000:03",
            scale_code="03",
            scale_bucket="10～19人",
            establishment_count=None,
            employee_count_total=None,
        )
        conn.commit()
    finally:
        conn.close()


def test_industry_region_benchmark_surfaces_estat_cells(
    client,
    tmp_path: Path,
    monkeypatch,
) -> None:
    from jpintel_mcp.config import settings

    db = tmp_path / "autonomath_stats.db"
    _build_stats_db(db)
    monkeypatch.setattr(settings, "autonomath_db_path", db)

    response = client.get("/v1/stats/benchmark/industry/D/region/13000")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["benchmark_kind"] == "industry_region"
    assert body["jsic_code_major"] == "D"
    assert body["jsic_name_major"] == "建設業"
    assert body["region_code"] == "13000"
    assert body["region_name"] == "東京都"
    assert body["establishments"] == 15
    assert body["employees_total"] == 50
    assert body["avg_employees_per_establishment"] == 3.33
    assert body["metadata"]["sample_cells"] == 3
    assert body["metadata"]["secrecy_cells"] == 1
    assert body["metadata"]["license"] == "gov_standard_v2.0"
    assert "zero" in body["metadata"]["secrecy_note"]
    assert {row["scale_bucket"] for row in body["scale_distribution"]} == {
        "1～4人",
        "5～9人",
        "10～19人",
    }


def test_industry_region_benchmark_returns_404_for_missing_cell(
    client,
    tmp_path: Path,
    monkeypatch,
) -> None:
    from jpintel_mcp.config import settings

    db = tmp_path / "autonomath_stats.db"
    _build_stats_db(db)
    monkeypatch.setattr(settings, "autonomath_db_path", db)

    response = client.get("/v1/stats/benchmark/industry/K/region/13000")

    assert response.status_code == 404
