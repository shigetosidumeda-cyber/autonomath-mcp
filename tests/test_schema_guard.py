from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _make_autonomath_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE am_entities(id INTEGER PRIMARY KEY);
            CREATE TABLE am_source(
                id INTEGER PRIMARY KEY,
                source_url TEXT,
                source_type TEXT,
                domain TEXT,
                content_hash TEXT,
                first_seen TEXT,
                last_verified TEXT,
                license TEXT
            );
            CREATE TABLE am_entity_facts(
                id INTEGER PRIMARY KEY,
                entity_id TEXT,
                field_name TEXT,
                field_kind TEXT,
                field_value_text TEXT,
                field_value_json TEXT,
                field_value_numeric REAL,
                source_id INTEGER,
                confirming_source_count INTEGER
            );
            CREATE TABLE am_entity_source(
                entity_id TEXT,
                source_id INTEGER,
                role TEXT
            );
            CREATE TABLE jpi_programs(
                unified_id TEXT,
                primary_name TEXT,
                source_url TEXT,
                source_fetched_at TEXT,
                subsidy_rate_text TEXT
            );
            CREATE TABLE am_alias(
                id INTEGER PRIMARY KEY,
                canonical_id TEXT,
                alias TEXT,
                alias_kind TEXT,
                language TEXT
            );
            CREATE TABLE am_amendment_diff(
                id INTEGER PRIMARY KEY,
                entity_id TEXT,
                field_name TEXT,
                detected_at TEXT
            );
            CREATE TABLE am_program_summary(
                entity_id TEXT PRIMARY KEY,
                summary_50 TEXT,
                summary_200 TEXT,
                token_50_est INTEGER
            );
            CREATE TABLE am_amount_condition(id INTEGER PRIMARY KEY);
            CREATE TABLE am_relation(id INTEGER PRIMARY KEY);
            CREATE TABLE am_authority(id INTEGER PRIMARY KEY);
            CREATE TABLE am_region(id INTEGER PRIMARY KEY);
            CREATE TABLE am_tax_rule(id INTEGER PRIMARY KEY);
            CREATE TABLE am_loan_product(id INTEGER PRIMARY KEY);
            CREATE TABLE am_acceptance_stat(id INTEGER PRIMARY KEY);
            CREATE TABLE am_application_round(id INTEGER PRIMARY KEY);
            CREATE TABLE schema_migrations(
                id TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );

            CREATE VIEW am_unified_rule AS SELECT 1 AS id;
            CREATE VIEW programs_active_at_v2 AS SELECT 1 AS id;
            CREATE VIEW am_uncertainty_view AS SELECT 1 AS id;
            CREATE VIEW v_program_source_manifest AS SELECT 1 AS id;

            INSERT INTO am_entities(id) VALUES (1);
            INSERT INTO am_source(
                id, source_url, source_type, domain, content_hash,
                first_seen, last_verified, license
            ) VALUES (
                1, 'https://example.go.jp/source', 'primary', 'example.go.jp',
                'sha256:test', '2026-05-01', '2026-05-02', 'pdl_v1.0'
            );
            INSERT INTO am_entity_facts(
                id, entity_id, field_name, field_kind, field_value_text,
                source_id, confirming_source_count
            ) VALUES (1, 'program:test', 'amount', 'text', '100万円', 1, 1);
            INSERT INTO am_entity_source(entity_id, source_id, role)
            VALUES ('program:test', 1, 'primary');
            INSERT INTO jpi_programs(
                unified_id, primary_name, source_url, source_fetched_at,
                subsidy_rate_text
            ) VALUES (
                'UNI-test', 'テスト制度', 'https://example.go.jp/source',
                '2026-05-02', '1/2'
            );
            INSERT INTO am_alias(id, canonical_id, alias, alias_kind, language)
            VALUES (1, 'program:test', 'テスト', 'short', 'ja');
            INSERT INTO am_amendment_diff(id, entity_id, field_name, detected_at)
            VALUES (1, 'program:test', 'amount', '2026-05-02');
            INSERT INTO am_program_summary(entity_id, summary_50, summary_200, token_50_est)
            VALUES ('program:test', 'short', 'medium', 10);
            INSERT INTO schema_migrations(id, checksum, applied_at)
            VALUES
                ('049_provenance_strengthen.sql', 'test', 'now'),
                ('075_am_amendment_diff.sql', 'test', 'now'),
                ('090_law_article_body_en.sql', 'test', 'now'),
                ('115_source_manifest_view.sql', 'test', 'now'),
                ('121_jpi_programs_subsidy_rate_text_column.sql', 'test', 'now');
            """
        )
        conn.commit()
    finally:
        conn.close()


def _make_jpintel_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE programs(
                id INTEGER PRIMARY KEY,
                subsidy_rate_text TEXT
            );
            CREATE TABLE api_keys(id INTEGER PRIMARY KEY);
            CREATE TABLE case_studies(id INTEGER PRIMARY KEY);
            CREATE TABLE loan_programs(id INTEGER PRIMARY KEY);
            CREATE TABLE enforcement_cases(id INTEGER PRIMARY KEY);
            CREATE TABLE analytics_events(
                id INTEGER PRIMARY KEY,
                user_agent_class TEXT,
                is_bot INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE funnel_events(
                id INTEGER PRIMARY KEY,
                event_name TEXT NOT NULL,
                is_bot INTEGER NOT NULL DEFAULT 0,
                is_anonymous INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE l4_query_cache(
                cache_key TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                params_json TEXT NOT NULL,
                result_json TEXT NOT NULL
            );
            CREATE TABLE schema_migrations(
                id TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );

            INSERT INTO programs(id, subsidy_rate_text) VALUES (1, '1/2');
            INSERT INTO api_keys(id) VALUES (1);
            INSERT INTO case_studies(id) VALUES (1);
            INSERT INTO loan_programs(id) VALUES (1);
            INSERT INTO enforcement_cases(id) VALUES (1);
            INSERT INTO schema_migrations(id, checksum, applied_at) VALUES
                ('043_l4_cache.sql', 'test', 'now'),
                ('111_analytics_events.sql', 'test', 'now'),
                ('121_subsidy_rate_text_column.sql', 'test', 'now'),
                ('123_funnel_events.sql', 'test', 'now');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_prod_autonomath_guard_skips_quick_check(
    tmp_path: Path, monkeypatch
) -> None:
    from scripts import schema_guard

    db_path = tmp_path / "autonomath.db"
    _make_autonomath_db(db_path)
    monkeypatch.setenv("JPINTEL_ENV", "prod")

    def fail_if_called(_db_path: str) -> str:
        raise AssertionError("autonomath prod guard must not run quick_check")

    monkeypatch.setattr(schema_guard, "_quick_check", fail_if_called)

    schema_guard.assert_am_schema(str(db_path))


def test_autonomath_guard_requires_evidence_critical_tables(tmp_path: Path) -> None:
    from scripts import schema_guard

    db_path = tmp_path / "autonomath_missing_evidence.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE am_entities(id INTEGER PRIMARY KEY);
            CREATE TABLE am_entity_facts(id INTEGER PRIMARY KEY);
            CREATE TABLE am_amount_condition(id INTEGER PRIMARY KEY);
            CREATE TABLE am_relation(id INTEGER PRIMARY KEY);
            CREATE TABLE am_authority(id INTEGER PRIMARY KEY);
            CREATE TABLE am_region(id INTEGER PRIMARY KEY);
            CREATE TABLE am_tax_rule(id INTEGER PRIMARY KEY);
            CREATE TABLE am_loan_product(id INTEGER PRIMARY KEY);
            CREATE TABLE am_acceptance_stat(id INTEGER PRIMARY KEY);
            CREATE TABLE am_application_round(id INTEGER PRIMARY KEY);
            CREATE TABLE schema_migrations(
                id TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            CREATE VIEW am_unified_rule AS SELECT 1 AS id;
            CREATE VIEW programs_active_at_v2 AS SELECT 1 AS id;
            CREATE VIEW am_uncertainty_view AS SELECT 1 AS id;
            CREATE VIEW v_program_source_manifest AS SELECT 1 AS id;
            """
        )
        conn.commit()
    finally:
        conn.close()

    try:
        schema_guard.assert_am_schema(str(db_path))
    except schema_guard.SchemaGuardError as exc:
        message = str(exc)
    else:
        raise AssertionError("assert_am_schema should reject missing evidence tables")

    assert "am_source" in message
    assert "jpi_programs" in message


def test_prod_jpintel_guard_keeps_quick_check(tmp_path: Path, monkeypatch) -> None:
    from scripts import schema_guard

    db_path = tmp_path / "jpintel.db"
    _make_jpintel_db(db_path)
    calls: list[str] = []
    monkeypatch.setenv("JPINTEL_ENV", "prod")
    monkeypatch.setenv("JPINTEL_GUARD_MIN_PROGRAMS", "1")

    def record_quick_check(db_path_arg: str) -> str:
        calls.append(db_path_arg)
        return "ok"

    monkeypatch.setattr(schema_guard, "_quick_check", record_quick_check)

    schema_guard.assert_jpintel_schema(str(db_path))

    assert calls == [str(db_path)]


def test_migrate_continues_after_duplicate_column_in_multi_column_migration(
    tmp_path: Path,
) -> None:
    from scripts import migrate

    db_path = tmp_path / "jpintel.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE analytics_events(
                id INTEGER PRIMARY KEY,
                ts TEXT NOT NULL,
                path TEXT NOT NULL,
                user_agent_class TEXT
            );
            CREATE TABLE schema_migrations(
                id TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            """
        )
        sql = (
            migrate.MIGRATIONS_DIR / "123_funnel_events.sql"
        ).read_text(encoding="utf-8")
        migrate._apply_one(conn, "123_funnel_events.sql", sql, "test")
        cols = {
            row[1] for row in conn.execute("PRAGMA table_info(analytics_events)")
        }
        applied = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE id = ?",
            ("123_funnel_events.sql",),
        ).fetchone()
    finally:
        conn.close()

    assert "is_bot" in cols
    assert applied is not None


def test_migrate_handles_explicit_transaction_scripts(tmp_path: Path) -> None:
    from scripts import migrate

    db_path = tmp_path / "jpintel.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE schema_migrations(
                id TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        migrate._apply_one(
            conn,
            "test_transaction.sql",
            """
            BEGIN;
            CREATE TABLE explicit_txn_guard(id INTEGER PRIMARY KEY);
            INSERT INTO explicit_txn_guard(id) VALUES (1);
            COMMIT;
            """,
            "test",
        )
        count = conn.execute("SELECT COUNT(*) FROM explicit_txn_guard").fetchone()[0]
    finally:
        conn.close()

    assert count == 1


def test_migrate_load_migrations_skips_rollback_and_manual_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from scripts import migrate

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_forward.sql").write_text("CREATE TABLE ok(id INTEGER);\n", encoding="utf-8")
    (migrations_dir / "002_forward_rollback.sql").write_text(
        "DROP TABLE ok;\n",
        encoding="utf-8",
    )
    (migrations_dir / "003_manual.sql").write_text(
        "-- boot_time: manual\nDROP TABLE large_table;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", migrations_dir)

    loaded = migrate._load_migrations()

    assert [mid for mid, _path, _checksum in loaded] == ["001_forward.sql"]
