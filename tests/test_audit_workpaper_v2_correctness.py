from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

from starlette.requests import Request

from jpintel_mcp.api.audit_workpaper_v2 import (
    AuditWorkpaperRequest,
    _build_workpaper,
    post_audit_workpaper,
)
from jpintel_mcp.api.deps import ApiContext, hash_api_key
from jpintel_mcp.billing.keys import issue_key

REPO_ROOT = Path(__file__).resolve().parents[1]
ETL_SCRIPT = REPO_ROOT / "scripts" / "etl" / "build_audit_workpaper_v2.py"
MIGRATION = REPO_ROOT / "scripts" / "migrations" / "289_audit_workpaper_v2.sql"


def _load_etl_module():
    spec = importlib.util.spec_from_file_location("build_audit_workpaper_v2", ETL_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _seed_current_autonomath_schema(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE jpi_houjin_master (
            houjin_bangou TEXT PRIMARY KEY,
            normalized_name TEXT,
            address_normalized TEXT,
            prefecture TEXT,
            municipality TEXT,
            corporation_type TEXT,
            total_adoptions INTEGER,
            total_received_yen INTEGER
        );
        CREATE TABLE jpi_adoption_records (
            houjin_bangou TEXT,
            program_id TEXT,
            program_name_raw TEXT,
            company_name_raw TEXT,
            announced_at TEXT,
            amount_granted_yen INTEGER,
            prefecture TEXT
        );
        CREATE TABLE am_enforcement_detail (
            enforcement_id TEXT PRIMARY KEY,
            houjin_bangou TEXT,
            enforcement_kind TEXT,
            issuance_date TEXT,
            amount_yen INTEGER,
            reason_summary TEXT,
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
          ('8010001213708', 'TestCo', 'Tokyo address',
           'Tokyo', 'Bunkyo', 'KK', 2, 5000000);
        INSERT INTO jpi_adoption_records VALUES
          ('8010001213708', 'program:test:1', 'Program Raw',
           'TestCo Raw', '2025-08-15T00:00:00Z', 1234000, 'Kanagawa');
        INSERT INTO jpi_adoption_records VALUES
          ('8010001213708', 'program:test:prev', 'Prev FY Program',
           'TestCo Raw', '2025-03-31T23:59:59Z', 999, 'Kanagawa');
        INSERT INTO jpi_adoption_records VALUES
          ('8010001213708', 'program:test:next', 'Next FY Program',
           'TestCo Raw', '2026-04-01T00:00:00Z', 999, 'Kanagawa');
        INSERT INTO am_enforcement_detail VALUES
          ('ENF-1', '8010001213708', 'fine', '2025-12-01',
           100000, 'late report', 'https://example.test/enf');
        INSERT INTO jpi_invoice_registrants VALUES
          ('8010001213708', 'Tokyo', '2023-10-01');
        INSERT INTO am_amendment_diff VALUES
          (1, 'program:test:1', 'amount_max_yen', '100', '200',
           '2025-11-12T00:00:00Z', 'https://example.test/amend');
        INSERT INTO am_amendment_diff VALUES
          (2, 'program:test:1', 'amount_max_yen', '200', '300',
           '2026-04-01T00:00:00Z', 'https://example.test/amend-next');
        """
    )
    conn.commit()
    return conn


def test_rest_build_workpaper_uses_current_autonomath_schema(tmp_path: Path) -> None:
    conn = _seed_current_autonomath_schema(tmp_path / "autonomath.db")
    try:
        body = _build_workpaper(conn, "8010001213708", 2025)
    finally:
        conn.close()

    assert body is not None
    assert body["houjin_meta"]["jsic_major"] is None
    assert body["counts"]["fy_adoption_count"] == 1
    assert body["counts"]["fy_enforcement_count"] == 1
    assert body["counts"]["fy_amendment_alert_count"] == 1
    assert body["jurisdiction_breakdown"]["operational_top_prefecture"] == "Kanagawa"
    assert body["fy_adoptions"][0] == {
        "program_id": "program:test:1",
        "program_name": "Program Raw",
        "applicant_name": "TestCo Raw",
        "award_date": "2025-08-15T00:00:00Z",
        "amount_yen": 1234000,
        "fiscal_year": 2025,
        "announce_date": "2025-08-15T00:00:00Z",
    }
    assert body["fy_enforcement"][0]["detail_id"] == "ENF-1"
    assert body["fy_enforcement"][0]["enforcement_date"] == "2025-12-01"
    assert body["fy_enforcement"][0]["summary"] == "late report"


def test_etl_compose_one_uses_current_autonomath_schema(tmp_path: Path) -> None:
    conn = _seed_current_autonomath_schema(tmp_path / "autonomath.db")
    try:
        etl = _load_etl_module()
        body = etl._compose_one(conn, "8010001213708", 2025)
    finally:
        conn.close()

    assert body is not None
    assert body["houjin_meta"]["jsic_major"] is None
    assert body["counts"]["fy_adoption_count"] == 1
    assert body["counts"]["fy_enforcement_count"] == 1
    assert body["fy_adoptions"][0]["program_name"] == "Program Raw"
    assert body["fy_enforcement"][0]["summary"] == "late report"


def test_mcp_compose_uses_current_autonomath_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    conn = _seed_current_autonomath_schema(tmp_path / "autonomath.db")
    conn.close()
    db_path = str(tmp_path / "autonomath.db")
    monkeypatch.setenv("AUTONOMATH_DB_PATH", db_path)
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", db_path)

    from jpintel_mcp.mcp.autonomath_tools import db as _db_mod
    from jpintel_mcp.mcp.autonomath_tools.audit_workpaper_v2 import (
        _compose_workpaper_impl,
    )

    _db_mod.close_all()
    body = _compose_workpaper_impl("8010001213708", 2025)
    _db_mod.close_all()

    assert "error" not in body, body
    assert body["houjin_meta"]["jsic_major"] is None
    assert body["counts"]["fy_adoption_count"] == 1
    assert body["counts"]["fy_enforcement_count"] == 1
    assert body["counts"]["fy_amendment_alert_count"] == 1
    assert body["jurisdiction_breakdown"]["operational_top_prefecture"] == "Kanagawa"
    assert body["fy_adoptions"][0]["program_name"] == "Program Raw"
    assert body["fy_adoptions"][0]["award_date"] == "2025-08-15T00:00:00Z"
    assert body["fy_enforcement"][0]["detail_id"] == "ENF-1"
    assert body["fy_enforcement"][0]["summary"] == "late report"


def test_mcp_audit_workpaper_avoids_duplicate_legacy_tool_registration() -> None:
    src = (
        REPO_ROOT
        / "src"
        / "jpintel_mcp"
        / "mcp"
        / "autonomath_tools"
        / "audit_workpaper_v2.py"
    ).read_text(encoding="utf-8")

    assert '_has_tool_registered("compose_audit_workpaper")' in src
    assert '"compose_audit_workpaper_v2"' in src
    assert "@mcp.tool(name=_TOOL_NAME" in src


def test_audit_workpaper_migration_289_is_in_boot_manifests() -> None:
    for rel in (
        "scripts/migrations/jpcite_boot_manifest.txt",
        "scripts/migrations/autonomath_boot_manifest.txt",
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "289_audit_workpaper_v2.sql" in text, rel


def test_post_workpaper_logs_paid_success_as_five_units(
    tmp_path: Path,
    seeded_db: Path,
    monkeypatch,
) -> None:
    am_conn = _seed_current_autonomath_schema(tmp_path / "autonomath.db")
    jp_conn = sqlite3.connect(seeded_db)
    jp_conn.row_factory = sqlite3.Row
    raw_key = issue_key(
        jp_conn,
        customer_id="cus_audit_workpaper_v2",
        tier="paid",
        stripe_subscription_id=None,
    )
    jp_conn.commit()
    ctx = ApiContext(
        key_hash=hash_api_key(raw_key),
        tier="paid",
        customer_id="cus_audit_workpaper_v2",
        stripe_subscription_id=None,
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/audit/workpaper",
            "headers": [],
            "client": ("testclient", 50000),
        }
    )
    monkeypatch.setattr(
        "jpintel_mcp.api.audit_workpaper_v2._open_autonomath_ro",
        lambda: am_conn,
    )

    try:
        response = post_audit_workpaper(
            request,
            ctx,
            jp_conn,
            AuditWorkpaperRequest(
                client_houjin_bangou="8010001213708",
                fiscal_year=2025,
            ),
        )
        assert response.status_code == 200
        row = jp_conn.execute(
            """
            SELECT endpoint, quantity, metered, status
              FROM usage_events
             WHERE key_hash = ? AND endpoint = 'audit_workpaper'
             ORDER BY id DESC LIMIT 1
            """,
            (hash_api_key(raw_key),),
        ).fetchone()
    finally:
        jp_conn.close()

    assert tuple(row) == ("audit_workpaper", 5, 1, 200)


def test_post_workpaper_keeps_anonymous_success_unmetered(
    tmp_path: Path,
    seeded_db: Path,
    monkeypatch,
) -> None:
    am_conn = _seed_current_autonomath_schema(tmp_path / "autonomath.db")
    jp_conn = sqlite3.connect(seeded_db)
    jp_conn.row_factory = sqlite3.Row
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/audit/workpaper",
            "headers": [],
            "client": ("testclient", 50001),
        }
    )
    monkeypatch.setattr(
        "jpintel_mcp.api.audit_workpaper_v2._open_autonomath_ro",
        lambda: am_conn,
    )

    try:
        before = jp_conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE endpoint = 'audit_workpaper'"
        ).fetchone()[0]
        response = post_audit_workpaper(
            request,
            ApiContext(key_hash=None, tier="free", customer_id=None),
            jp_conn,
            AuditWorkpaperRequest(
                client_houjin_bangou="8010001213708",
                fiscal_year=2025,
            ),
        )
        after = jp_conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE endpoint = 'audit_workpaper'"
        ).fetchone()[0]
    finally:
        jp_conn.close()

    assert response.status_code == 200
    assert after == before


def test_audit_workpaper_migration_is_idempotent_and_matches_etl(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "mig.db")
    conn.row_factory = sqlite3.Row
    sql = MIGRATION.read_text(encoding="utf-8")
    try:
        conn.executescript(
            """
            CREATE TABLE jpi_adoption_records (
                houjin_bangou TEXT,
                program_id TEXT,
                program_name_raw TEXT,
                company_name_raw TEXT,
                announced_at TEXT,
                amount_granted_yen INTEGER,
                prefecture TEXT
            );
            CREATE TABLE am_enforcement_detail (
                enforcement_id TEXT PRIMARY KEY,
                houjin_bangou TEXT,
                enforcement_kind TEXT,
                issuance_date TEXT,
                amount_yen INTEGER,
                reason_summary TEXT,
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
            """
        )
        conn.executescript(sql)
        conn.executescript(sql)
        etl = _load_etl_module()
        run_id = etl._start_run(conn)
        etl._finish_run(
            conn,
            run_id,
            scanned=2,
            upserted=1,
            skipped=1,
            errors=0,
            error_text=None,
        )
        conn.execute(
            """
            INSERT INTO am_audit_workpaper (
                houjin_bangou, fiscal_year, fy_start, fy_end,
                fy_adoption_count, fy_enforcement_count,
                fy_amendment_alert_count, jurisdiction_mismatch,
                auditor_flag_count, snapshot_json, snapshot_bytes,
                composed_at, composer_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "8010001213708",
                2025,
                "2025-04-01",
                "2026-03-31",
                1,
                1,
                1,
                0,
                2,
                json.dumps({"ok": True}),
                12,
                "2026-05-13T00:00:00.000000Z",
                "audit_workpaper_v2",
            ),
        )
        row = conn.execute(
            "SELECT houjin_scanned, workpapers_upserted, workpapers_skipped "
            "FROM am_audit_workpaper_run_log WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()

    assert tuple(row) == (2, 1, 1)


def test_audit_workpaper_sql_uses_range_friendly_date_predicates() -> None:
    api_sql = (
        REPO_ROOT / "src" / "jpintel_mcp" / "api" / "audit_workpaper_v2.py"
    ).read_text(encoding="utf-8")
    etl_sql = ETL_SCRIPT.read_text(encoding="utf-8")

    assert "substr(announced_at" not in api_sql
    assert "substr(detected_at" not in api_sql
    assert "substr(announced_at" not in etl_sql
    assert "substr(detected_at" not in etl_sql
    assert "announced_at >= ?" in api_sql
    assert "announced_at < ?" in api_sql
    assert "detected_at >= ?" in api_sql
    assert "detected_at < ?" in api_sql


def test_audit_workpaper_migration_adds_source_supporting_indexes(tmp_path: Path) -> None:
    conn = _seed_current_autonomath_schema(tmp_path / "mig-indexes.db")
    sql = MIGRATION.read_text(encoding="utf-8")
    try:
        conn.executescript(sql)
        index_names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
    finally:
        conn.close()

    assert {
        "idx_289_jpi_adoption_records_houjin_announced",
        "idx_289_jpi_adoption_records_announced_houjin",
        "idx_289_jpi_adoption_records_houjin_prefecture",
        "idx_289_am_enforcement_detail_houjin_issuance",
        "idx_289_jpi_invoice_registrants_houjin_registered",
        "idx_289_am_amendment_diff_entity_detected",
    } <= index_names
