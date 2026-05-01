from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "etl"
    / "plan_axis_key_migration.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("plan_axis_key_migration", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_db(path: Path, *, axis_key: bool = False) -> None:
    axis_column = ", axis_key TEXT NOT NULL DEFAULT ''" if axis_key else ""
    conn = sqlite3.connect(path)
    conn.executescript(
        f"""
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value_text TEXT,
            field_kind TEXT NOT NULL{axis_column}
        );
        CREATE INDEX idx_am_facts_entity ON am_entity_facts(entity_id);
        CREATE UNIQUE INDEX uq_am_facts_entity_field_text
            ON am_entity_facts(entity_id, field_name, COALESCE(field_value_text, ''));
        """
    )
    conn.executemany(
        "INSERT INTO am_entity_facts(id, entity_id, field_name, field_value_text, field_kind) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (1, "program:1", "amount_max_yen", "100000", "amount"),
            (2, "program:1", "amount_max_yen__dup1", "200000", "amount"),
            (3, "program:1", "amount_max_yen__dup0", "300000", "amount"),
            (4, "program:2", "name", "Program Two", "text"),
        ],
    )
    conn.commit()
    conn.close()


def _columns(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(am_entity_facts)")]
    conn.close()
    return columns


def _index_names(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    indexes = [row[1] for row in conn.execute("PRAGMA index_list(am_entity_facts)")]
    conn.close()
    return indexes


def _write_preflight(
    path: Path,
    *,
    ok: bool = True,
    issues: list[str] | None = None,
    duplicate_group_count: int = 0,
) -> None:
    payload = {
        "ok": ok,
        "generated_at": "2026-05-01T00:00:00+00:00",
        "issues": issues or [],
        "counts": {
            "am_entity_facts_rows": 4,
            "dup_suffix_rows": 1,
        },
        "schema": {
            "has_axis_key": False,
            "am_entity_facts_columns": [
                "id",
                "entity_id",
                "field_name",
                "field_value_text",
                "field_kind",
            ],
        },
        "duplicate_violations": {
            "proposed_unique_key": "entity_id, field_name, axis_key, COALESCE(field_value_text, '')",
            "group_count": duplicate_group_count,
            "row_count": duplicate_group_count * 2,
            "sample_groups": [],
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_plan_consumes_preflight_and_only_emits_sql_strings(tmp_path: Path) -> None:
    mod = _load_module()
    db = tmp_path / "autonomath.db"
    preflight = tmp_path / "axis_key_preflight.json"
    _make_db(db)
    _write_preflight(preflight)
    before_columns = _columns(db)
    before_indexes = _index_names(db)

    report = mod.build_plan(db=db, preflight_path=preflight)

    assert report["ok"] is True
    assert report["read_mode"] == {
        "sqlite_readonly": True,
        "sqlite_query_only": True,
        "preflight_json_only": True,
        "network_fetch_performed": False,
        "db_mutation_performed": False,
        "live_migration_performed": False,
        "sql_strings_only": True,
    }
    assert report["completion_status"] == {"D6": "plan_only", "complete": False}
    assert report["preflight"]["present"] is True
    assert report["preflight"]["counts"]["dup_suffix_rows"] == 1
    assert report["schema"]["am_entity_facts"]["has_axis_key"] is False
    assert report["schema"]["am_entity_facts"]["strict_dup_suffix_rows"] == 1

    migration_sql = report["sql"]["migration_statements"]
    assert all(isinstance(sql, str) for sql in migration_sql)
    assert any("ADD COLUMN axis_key" in sql for sql in migration_sql)
    assert any("SET axis_key" in sql for sql in migration_sql)
    assert any("CREATE UNIQUE INDEX IF NOT EXISTS uq_am_facts_entity_field_axis_text" in sql for sql in migration_sql)
    assert any("DROP INDEX IF EXISTS uq_am_facts_entity_field_text" in sql for sql in migration_sql)
    assert report["unique_index_strategy"]["legacy_index_present"] is True
    assert report["data_backfill_policy"]["excluded_suffix_examples"] == [
        "__dup0",
        "__dupx",
        "__dup01",
        "__dup1_extra",
    ]
    rollback_sql = "\n".join(report["sql"]["rollback_statements"])
    assert "substr(axis_key, length('dup') + 1)" in rollback_sql
    assert report["report_counts"]["migration_sql_count"] == len(migration_sql)
    assert report["report_counts"]["acceptance_query_count"] == 6
    assert _columns(db) == before_columns
    assert _index_names(db) == before_indexes


def test_build_plan_blocks_on_preflight_duplicate_violations_with_existing_axis_key(
    tmp_path: Path,
) -> None:
    mod = _load_module()
    db = tmp_path / "autonomath.db"
    preflight = tmp_path / "axis_key_preflight.json"
    _make_db(db, axis_key=True)
    _write_preflight(
        preflight,
        ok=False,
        issues=["duplicate_violations:proposed_unique_key"],
        duplicate_group_count=2,
    )

    report = mod.build_plan(db=db, preflight_path=preflight)

    codes = {blocker["code"] for blocker in report["blockers"]}
    assert report["ok"] is False
    assert "preflight:duplicate_violations:proposed_unique_key" in codes
    assert report["schema"]["am_entity_facts"]["has_axis_key"] is True
    assert not any(
        "ADD COLUMN axis_key" in sql for sql in report["sql"]["migration_statements"]
    )
    assert report["conflict_handling"]["migration_gate"] == "blocked_until_precheck_zero"
    assert report["conflict_handling"]["preflight_duplicate_violation_groups"] == 2


def test_cli_writes_plan_without_mutating_temp_db(tmp_path: Path) -> None:
    mod = _load_module()
    db = tmp_path / "autonomath.db"
    preflight = tmp_path / "axis_key_preflight.json"
    output = tmp_path / "axis_key_migration_plan.json"
    _make_db(db)
    _write_preflight(preflight)
    before_columns = _columns(db)
    before_indexes = _index_names(db)

    rc = mod.main(
        [
            "--db",
            str(db),
            "--preflight",
            str(preflight),
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["scope"] == "D6 axis_key migration plan generator; no live migration"
    assert payload["read_mode"]["live_migration_performed"] is False
    assert payload["report_counts"]["blocker_count"] == 0
    assert payload["sql"]["acceptance_queries"]
    assert _columns(db) == before_columns
    assert _index_names(db) == before_indexes
