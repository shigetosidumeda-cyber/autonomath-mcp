from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_gbiz_rate_limiter_exposes_legacy_get_wrapper() -> None:
    from jpintel_mcp.ingest import _gbiz_rate_limiter

    assert callable(_gbiz_rate_limiter.get)


def test_gbiz_rate_limiter_429_is_fail_fast(monkeypatch: Any, tmp_path: Path) -> None:
    from jpintel_mcp.ingest import _gbiz_rate_limiter

    class FakeCache:
        def get(self, _key: str) -> None:
            return None

        def set(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("429 responses must not be cached")

    class FakeResponse:
        status_code = 429

        def raise_for_status(self) -> None:
            raise AssertionError("429 must raise before raise_for_status")

        def json(self) -> dict[str, Any]:
            raise AssertionError("429 must not parse json")

    calls: list[str] = []

    class FakeHttpClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def __enter__(self) -> FakeHttpClient:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def get(self, url: str, **_kwargs: Any) -> FakeResponse:
            calls.append(url)
            return FakeResponse()

    monkeypatch.setattr(_gbiz_rate_limiter, "_rate_limit_gate", lambda: None)
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(_gbiz_rate_limiter, "_make_cache", lambda _cache_dir: FakeCache())
    monkeypatch.setattr(_gbiz_rate_limiter.httpx, "Client", FakeHttpClient)

    client = _gbiz_rate_limiter.GbizRateLimitedClient(token="test-token")
    with pytest.raises(RuntimeError, match="gbiz_rate_limit_exceeded"):
        client.get("v2/hojin/8010001213708")
    assert len(calls) == 1


def test_gbiz_attribution_contract_keys() -> None:
    from jpintel_mcp.ingest._gbiz_attribution import build_attribution

    attribution = build_attribution(
        source_url="https://info.gbiz.go.jp/hojin/v2/hojin/8010001213708/subsidy",
        fetched_at="2026-05-06T00:00:00+00:00",
        upstream_source="jGrants",
    )["_attribution"]

    required = {
        "source",
        "publisher",
        "source_url",
        "license",
        "license_url",
        "modification_notice",
        "fetched_via",
        "snapshot_date",
        "upstream_source",
    }
    assert required <= attribution.keys()
    assert attribution["source"] == "Gビズインフォ"
    assert attribution["publisher"] == "経済産業省"
    assert attribution["license_url"].startswith("https://help.info.gbiz.go.jp/")
    assert attribution["fetched_via"] == "gBizINFO REST API v2"
    assert attribution["snapshot_date"] == "2026-05-06T00:00:00+00:00"
    assert attribution["upstream_source"] == "jGrants"


def test_gbiz_attribution_requires_upstream_source() -> None:
    from jpintel_mcp.ingest._gbiz_attribution import build_attribution

    with pytest.raises(ValueError, match="upstream_source"):
        build_attribution(
            source_url="https://info.gbiz.go.jp/",
            fetched_at="2026-05-06T00:00:00+00:00",
            upstream_source="",
        )


def test_gbiz_cron_stores_inner_attribution_not_double_wrapper() -> None:
    scripts = [
        "ingest_gbiz_subsidy_v2.py",
        "ingest_gbiz_certification_v2.py",
        "ingest_gbiz_commendation_v2.py",
        "ingest_gbiz_procurement_v2.py",
    ]
    forbidden = '"_attribution": attribution}'
    for script in scripts:
        source = (REPO_ROOT / "scripts" / "cron" / script).read_text(encoding="utf-8")
        assert forbidden not in source
        assert '"_attribution": attribution_payload}' in source


def test_gbiz_cron_cli_accepts_workflow_db_and_log_file_aliases(tmp_path: Path) -> None:
    scripts = [
        "ingest_gbiz_corporate_v2.py",
        "ingest_gbiz_subsidy_v2.py",
        "ingest_gbiz_certification_v2.py",
        "ingest_gbiz_commendation_v2.py",
        "ingest_gbiz_procurement_v2.py",
        "ingest_gbiz_bulk_jsonl_monthly.py",
    ]
    env = os.environ.copy()
    env["GBIZINFO_INGEST_ENABLED"] = "false"
    env.pop("GBIZINFO_API_TOKEN", None)
    for script in scripts:
        args = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "cron" / script),
            "--db",
            str(tmp_path / "gbiz.sqlite"),
            "--log-file",
            str(tmp_path / f"{script}.log"),
            "--dry-run",
        ]
        if script == "ingest_gbiz_bulk_jsonl_monthly.py":
            args.extend(["--zip-path", str(tmp_path / "missing.zip")])
        else:
            args.extend(["--houjin-bangou", "8010001213708"])
        result = subprocess.run(
            args,
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_gbiz_mirror_migration_matches_cron_insert_columns() -> None:
    migration = REPO_ROOT / "scripts" / "migrations" / "wave24_164_gbiz_v2_mirror_tables.sql"
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(migration.read_text(encoding="utf-8"))
        expected = {
            "gbiz_corp_activity": {
                "legal_name",
                "legal_name_kana",
                "legal_name_en",
                "employee_male",
                "employee_female",
                "founding_year",
                "date_of_establishment",
                "close_date",
                "close_cause",
                "company_url",
                "qualification_grade",
                "gbiz_update_date",
                "cache_age_hours",
                "upstream_source",
                "source_url",
                "attribution_json",
                "raw_json",
            },
            "gbiz_corporation_branch": {
                "branch_kana",
                "location",
                "postal_code",
                "branch_kind",
                "raw_json",
            },
            "gbiz_workplace": {"raw_json"},
            "gbiz_update_log": {"endpoint", "from_date", "to_date", "record_count", "next_token"},
            "gbiz_subsidy_award": {
                "subsidy_resource_id",
                "title",
                "date_of_approval",
                "government_departments",
                "target",
                "note",
                "upstream_source",
                "raw_json",
            },
            "gbiz_certification": {
                "title",
                "category",
                "date_of_approval",
                "government_departments",
                "target",
                "upstream_source",
                "raw_json",
            },
            "gbiz_commendation": {
                "title",
                "date_of_commendation",
                "government_departments",
                "target",
                "upstream_source",
                "raw_json",
            },
            "gbiz_procurement": {
                "title",
                "amount_yen",
                "date_of_order",
                "government_departments",
                "note",
                "upstream_source",
                "raw_json",
            },
        }
        for table, columns in expected.items():
            actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert columns <= actual, (table, sorted(columns - actual))
    finally:
        conn.close()


def test_gbiz_corporate_activity_persists_attribution_json() -> None:
    module = _load_module(
        "gbiz_corporate_for_attribution_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_corporate_v2.py",
    )
    migration = REPO_ROOT / "scripts" / "migrations" / "wave24_164_gbiz_v2_mirror_tables.sql"
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(migration.read_text(encoding="utf-8"))
        inserted = module.upsert_corp_activity(
            conn,
            "8010001213708",
            {
                "hojin_info": {
                    "corporate_number": "8010001213708",
                    "name": "Bookyou株式会社",
                    "update_date": "2026-05-06",
                }
            },
            cache_age_hours=0.0,
            dry_run=False,
        )
        assert inserted == 1
        row = conn.execute(
            """
            SELECT source_url, upstream_source, attribution_json, raw_json
              FROM gbiz_corp_activity
             WHERE houjin_bangou = '8010001213708'
            """
        ).fetchone()
        assert row is not None
        assert row[0].endswith("hojinBango=8010001213708")
        assert row[1] == "NTA Houjin Bangou Web-API"
        attribution = json.loads(row[2])
        assert attribution["source"] == "Gビズインフォ"
        assert attribution["publisher"] == "経済産業省"
        assert attribution["source_url"].endswith("hojinBango=8010001213708")
        assert attribution["upstream_source"] == "NTA Houjin Bangou Web-API"
        raw = json.loads(row[3])
        assert "_attribution" not in raw
    finally:
        conn.close()


def test_gbiz_corporate_delta_paginates_and_accepts_mixed_houjin_number_keys(
    monkeypatch: Any,
) -> None:
    module = _load_module(
        "gbiz_corporate_for_delta_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_corporate_v2.py",
    )
    seen: list[str] = []

    pages_seen: list[int] = []

    def fake_fetch_updates(date_from: str, date_to: str, *, page: int = 1) -> dict[str, Any]:
        assert (date_from, date_to) == ("2026-04-01", "2026-05-01")
        pages_seen.append(page)
        if page == 1:
            return {
                "hojin-infos": [
                    {"corporate_number": "8010001213708"},
                    {"corporateNumber": "4120101047866"},
                    {"corporateNumber": "8010001213708"},
                    {"corporate_number": " "},
                ],
                "totalPage": "2",
            }
        if page == 2:
            return {
                "hojin-infos": [
                    {"houjin_bangou": "6010001196811"},
                    {"corporateNumber": "4120101047866"},
                ],
                "totalPage": "2",
            }
        raise AssertionError(f"unexpected page: {page}")

    def fake_run_mode_a(
        _conn: sqlite3.Connection,
        houjin_bangou: str,
        *,
        dry_run: bool,
        force_refresh: bool = False,
        canonical_enabled: bool = False,
    ) -> dict[str, int]:
        assert dry_run is True
        assert force_refresh is True
        assert canonical_enabled is False
        seen.append(houjin_bangou)
        return {
            "processed": 1,
            "corp_activity": 1,
            "branches": 0,
            "workplaces": 0,
            "new_entities": 1,
            "new_facts": 2,
        }

    conn = sqlite3.connect(":memory:")
    try:
        monkeypatch.setattr(module, "fetch_updates", fake_fetch_updates)
        monkeypatch.setattr(module, "run_mode_a", fake_run_mode_a)
        summary = module.run_mode_b(conn, "2026-04-01", "2026-05-01", dry_run=True)
    finally:
        conn.close()

    assert pages_seen == [1, 2]
    assert seen == ["8010001213708", "4120101047866", "6010001196811"]
    assert summary == {
        "processed": 3,
        "corp_activity": 3,
        "branches": 0,
        "workplaces": 0,
        "new_entities": 3,
        "new_facts": 6,
        "delta_listed": 3,
    }


def test_gbiz_update_fetch_uses_official_page_param_and_force_refresh(
    monkeypatch: Any,
) -> None:
    module = _load_module(
        "gbiz_corporate_for_update_param_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_corporate_v2.py",
    )
    calls: list[tuple[str, dict[str, str], bool]] = []

    def fake_get(
        path: str,
        *,
        params: dict[str, str],
        force_refresh: bool,
    ) -> dict[str, Any]:
        calls.append((path, params, force_refresh))
        return {"hojin-infos": [], "totalPage": "1"}

    monkeypatch.setattr(module._gbiz, "get", fake_get)

    module.fetch_updates("2026-04-01", "2026-05-01", page=3)

    assert calls == [
        (
            "v2/hojin/updateInfo/corporation",
            {"from": "20260401", "to": "20260501", "page": "3"},
            True,
        )
    ]


def test_gbiz_branch_and_workplace_snapshots_replace_stale_rows() -> None:
    module = _load_module(
        "gbiz_corporate_for_child_snapshot_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_corporate_v2.py",
    )
    migration = REPO_ROOT / "scripts" / "migrations" / "wave24_164_gbiz_v2_mirror_tables.sql"
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(migration.read_text(encoding="utf-8"))
        conn.execute(
            """
            INSERT INTO gbiz_corp_activity(houjin_bangou, legal_name, fetched_at)
            VALUES ('8010001213708', 'Bookyou株式会社', 'old')
            """
        )
        conn.execute(
            """
            INSERT INTO gbiz_corporation_branch(
                houjin_bangou, branch_name, location, postal_code, fetched_at
            ) VALUES ('8010001213708', 'old', 'Tokyo', '1000000', 'old')
            """
        )
        conn.execute(
            """
            INSERT INTO gbiz_workplace(
                houjin_bangou, workplace_name, location, postal_code, employee_number, fetched_at
            ) VALUES ('8010001213708', 'old-workplace', 'Tokyo', '1000000', 1, 'old')
            """
        )

        module.upsert_branches(
            conn,
            "8010001213708",
            {"corporation": [{"name": "new", "location": "Osaka", "postal_code": "5300000"}]},
            dry_run=False,
        )
        module.upsert_workplaces(
            conn,
            "8010001213708",
            {
                "workplace": [
                    {
                        "name": "new-workplace",
                        "location": "Osaka",
                        "postal_code": "5300000",
                        "employee_number": 9,
                    }
                ]
            },
            dry_run=False,
        )

        branches = conn.execute(
            "SELECT branch_name, location, postal_code FROM gbiz_corporation_branch"
        ).fetchall()
        workplaces = conn.execute(
            "SELECT workplace_name, location, postal_code, employee_number FROM gbiz_workplace"
        ).fetchall()
        assert branches == [("new", "Osaka", "5300000")]
        assert workplaces == [("new-workplace", "Osaka", "5300000", 9)]
    finally:
        conn.close()


def test_gbiz_cross_write_refreshes_singleton_corporate_facts() -> None:
    module = _load_module(
        "gbiz_corporate_for_fact_refresh_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_corporate_v2.py",
    )
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            """
            CREATE TABLE am_entities (
                canonical_id TEXT PRIMARY KEY,
                record_kind TEXT NOT NULL,
                source_topic TEXT,
                source_record_index INTEGER,
                primary_name TEXT NOT NULL,
                authority_canonical TEXT,
                confidence REAL,
                source_url TEXT,
                source_url_domain TEXT,
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
                field_value_json TEXT,
                field_value_numeric REAL,
                field_kind TEXT NOT NULL,
                unit TEXT,
                source_url TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE UNIQUE INDEX uq_am_facts_entity_field_text
                ON am_entity_facts(entity_id, field_name, COALESCE(field_value_text, ''));
            """
        )
        first = {
            "hojin_info": {
                "corporate_number": "8010001213708",
                "name": "Bookyou株式会社",
                "capital_stock": 100,
                "employee_number": 3,
                "status": "active",
            }
        }
        second = {
            "hojin_info": {
                "corporate_number": "8010001213708",
                "name": "Bookyou株式会社 Updated",
                "capital_stock": 500,
                "employee_number": 9,
                "status": "closed",
            }
        }

        module.cross_write_am_entity(conn, "8010001213708", first, dry_run=False)
        module.cross_write_am_entity(conn, "8010001213708", second, dry_run=False)

        entity_name = conn.execute(
            "SELECT primary_name FROM am_entities WHERE canonical_id = 'houjin:8010001213708'"
        ).fetchone()[0]
        facts = dict(
            conn.execute(
                """
                SELECT field_name, field_value_text
                  FROM am_entity_facts
                 WHERE entity_id = 'houjin:8010001213708'
                   AND field_name IN ('corp.capital_amount', 'corp.employee_count', 'corp.status')
                """
            ).fetchall()
        )
        assert entity_name == "Bookyou株式会社 Updated"
        assert facts == {
            "corp.capital_amount": "500",
            "corp.employee_count": "9",
            "corp.status": "closed",
        }
    finally:
        conn.close()


def test_gbiz_mode_a_rolls_back_child_snapshot_on_per_houjin_failure(
    monkeypatch: Any,
) -> None:
    module = _load_module(
        "gbiz_corporate_for_savepoint_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_corporate_v2.py",
    )
    migration = REPO_ROOT / "scripts" / "migrations" / "wave24_164_gbiz_v2_mirror_tables.sql"
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(migration.read_text(encoding="utf-8"))
        conn.execute(
            """
            INSERT INTO gbiz_corp_activity(houjin_bangou, legal_name, fetched_at)
            VALUES ('8010001213708', 'old-name', 'old')
            """
        )
        conn.execute(
            """
            INSERT INTO gbiz_corporation_branch(
                houjin_bangou, branch_name, location, fetched_at
            ) VALUES ('8010001213708', 'old-branch', 'Tokyo', 'old')
            """
        )
        conn.commit()

        monkeypatch.setattr(
            module,
            "fetch_corporation",
            lambda _bangou, *, force_refresh=False: {
                "hojin_info": {
                    "corporate_number": "8010001213708",
                    "name": "new-name",
                }
            },
        )
        monkeypatch.setattr(
            module,
            "fetch_corporation_branches",
            lambda _bangou, *, force_refresh=False: {
                "corporation": [{"name": "new-branch", "location": "Osaka"}]
            },
        )
        monkeypatch.setattr(
            module,
            "fetch_workplaces",
            lambda _bangou, *, force_refresh=False: {"workplace": []},
        )

        def fail_workplaces(*_args: Any, **_kwargs: Any) -> int:
            raise sqlite3.IntegrityError("forced workplace failure")

        monkeypatch.setattr(module, "upsert_workplaces", fail_workplaces)

        with pytest.raises(sqlite3.IntegrityError):
            module.run_mode_a(conn, "8010001213708", dry_run=False, force_refresh=True)

        assert (
            conn.execute(
                "SELECT legal_name FROM gbiz_corp_activity WHERE houjin_bangou = '8010001213708'"
            ).fetchone()[0]
            == "old-name"
        )
        assert conn.execute(
            "SELECT branch_name, location FROM gbiz_corporation_branch"
        ).fetchall() == [("old-branch", "Tokyo")]
    finally:
        conn.close()


def test_gbiz_corporate_main_checks_schema_before_fetch(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    module = _load_module(
        "gbiz_corporate_for_schema_before_fetch_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_corporate_v2.py",
    )
    db_path = tmp_path / "gbiz.sqlite"
    sqlite3.connect(db_path).close()
    fetch_calls: list[str] = []

    def fail_fetch(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        fetch_calls.append("fetch")
        raise AssertionError("fetch must not run before schema check")

    monkeypatch.setattr(module, "fetch_corporation", fail_fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_gbiz_corporate_v2.py",
            "--houjin-bangou",
            "8010001213708",
            "--db-path",
            str(db_path),
        ],
    )

    assert module.main() == 2
    assert fetch_calls == []


def test_gbiz_corporate_dry_run_checks_schema_before_fetch(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    module = _load_module(
        "gbiz_corporate_for_dry_run_schema_before_fetch_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_corporate_v2.py",
    )
    db_path = tmp_path / "gbiz.sqlite"
    sqlite3.connect(db_path).close()
    fetch_calls: list[str] = []

    def fail_fetch(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        fetch_calls.append("fetch")
        raise AssertionError("dry-run fetch must not run before schema check")

    monkeypatch.setattr(module, "fetch_corporation", fail_fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_gbiz_corporate_v2.py",
            "--houjin-bangou",
            "8010001213708",
            "--dry-run",
            "--db-path",
            str(db_path),
        ],
    )

    assert module.main() == 2
    assert fetch_calls == []


def test_gbiz_corporate_delta_main_checks_schema_before_fetch(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    module = _load_module(
        "gbiz_corporate_for_delta_schema_before_fetch_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_corporate_v2.py",
    )
    db_path = tmp_path / "gbiz.sqlite"
    sqlite3.connect(db_path).close()
    fetch_calls: list[str] = []

    def fail_fetch(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        fetch_calls.append("fetch")
        raise AssertionError("delta fetch must not run before schema check")

    monkeypatch.setattr(module, "fetch_updates", fail_fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_gbiz_corporate_v2.py",
            "--from",
            "2026-04-01",
            "--to",
            "2026-05-01",
            "--db-path",
            str(db_path),
        ],
    )

    assert module.main() == 2
    assert fetch_calls == []


def test_gbiz_corporate_canonical_cross_write_is_env_gated(
    monkeypatch: Any,
) -> None:
    module = _load_module(
        "gbiz_corporate_for_canonical_gate_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_corporate_v2.py",
    )
    migration = REPO_ROOT / "scripts" / "migrations" / "wave24_164_gbiz_v2_mirror_tables.sql"
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(migration.read_text(encoding="utf-8"))
        monkeypatch.setattr(
            module,
            "fetch_corporation",
            lambda _bangou, *, force_refresh=False: {
                "hojin_info": {
                    "corporate_number": "8010001213708",
                    "name": "Bookyou株式会社",
                }
            },
        )
        monkeypatch.setattr(
            module,
            "fetch_corporation_branches",
            lambda _bangou, *, force_refresh=False: {"corporation": []},
        )
        monkeypatch.setattr(
            module,
            "fetch_workplaces",
            lambda _bangou, *, force_refresh=False: {"workplace": []},
        )
        cross_write_calls: list[str] = []

        def fake_cross_write(*_args: Any, **_kwargs: Any) -> tuple[int, int]:
            cross_write_calls.append("cross_write")
            return (1, 2)

        monkeypatch.setattr(module, "cross_write_am_entity", fake_cross_write)

        summary_without_gate = module.run_mode_a(
            conn,
            "8010001213708",
            dry_run=False,
            force_refresh=True,
        )
        summary_with_gate = module.run_mode_a(
            conn,
            "8010001213708",
            dry_run=False,
            force_refresh=True,
            canonical_enabled=True,
        )

        assert cross_write_calls == ["cross_write"]
        assert summary_without_gate["new_entities"] == 0
        assert summary_without_gate["new_facts"] == 0
        assert summary_with_gate["new_entities"] == 1
        assert summary_with_gate["new_facts"] == 2
    finally:
        conn.close()


def test_gbiz_corporate_delta_update_log_uses_processed_success_count(
    monkeypatch: Any,
) -> None:
    module = _load_module(
        "gbiz_corporate_for_update_log_processed_count_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_corporate_v2.py",
    )
    migration = REPO_ROOT / "scripts" / "migrations" / "wave24_164_gbiz_v2_mirror_tables.sql"
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(migration.read_text(encoding="utf-8"))
        monkeypatch.setattr(
            module,
            "fetch_updates",
            lambda _from, _to, *, page=1: {
                "hojin-infos": [{"corporate_number": "8010001213708"}],
                "totalPage": "1",
            },
        )
        monkeypatch.setattr(
            module,
            "run_mode_a",
            lambda *_args, **_kwargs: {
                "processed": 1,
                "corp_activity": 1,
                "branches": 0,
                "workplaces": 0,
                "new_entities": 0,
                "new_facts": 0,
            },
        )

        summary = module.run_mode_b(conn, "2026-04-01", "2026-05-01", dry_run=False)
        log_row = conn.execute(
            """
            SELECT endpoint, from_date, to_date, record_count
              FROM gbiz_update_log
            """
        ).fetchone()

        assert summary["delta_listed"] == 1
        assert summary["processed"] == 1
        assert log_row == ("corporation", "2026-04-01", "2026-05-01", 1)
    finally:
        conn.close()


def test_gbiz_corporate_delta_partial_failure_rolls_back_success_log(
    monkeypatch: Any,
) -> None:
    module = _load_module(
        "gbiz_corporate_for_update_log_partial_failure_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_corporate_v2.py",
    )
    migration = REPO_ROOT / "scripts" / "migrations" / "wave24_164_gbiz_v2_mirror_tables.sql"
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(migration.read_text(encoding="utf-8"))
        monkeypatch.setattr(
            module,
            "fetch_updates",
            lambda _from, _to, *, page=1: {
                "hojin-infos": [
                    {"corporate_number": "8010001213708"},
                    {"corporate_number": "4120101047866"},
                ],
                "totalPage": "1",
            },
        )

        def fake_run_mode_a(
            _conn: sqlite3.Connection,
            houjin_bangou: str,
            **_kwargs: Any,
        ) -> dict[str, int]:
            if houjin_bangou == "4120101047866":
                raise RuntimeError("simulated partial failure")
            return {
                "processed": 1,
                "corp_activity": 1,
                "branches": 0,
                "workplaces": 0,
                "new_entities": 0,
                "new_facts": 0,
            }

        monkeypatch.setattr(module, "run_mode_a", fake_run_mode_a)

        with pytest.raises(RuntimeError, match="gbiz_delta_partial_failure"):
            module.run_mode_b(conn, "2026-04-01", "2026-05-01", dry_run=False)

        assert conn.execute("SELECT COUNT(*) FROM gbiz_update_log").fetchone()[0] == 0
    finally:
        conn.close()


def test_delta_endpoints_refetch_per_houjin_records(monkeypatch: Any) -> None:
    cases = [
        ("subsidy", "ingest_gbiz_subsidy_v2.py"),
        ("certification", "ingest_gbiz_certification_v2.py"),
        ("commendation", "ingest_gbiz_commendation_v2.py"),
        ("procurement", "ingest_gbiz_procurement_v2.py"),
    ]

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, str], bool]] = []

        def get(
            self,
            path: str,
            params: dict[str, str],
            *,
            force_refresh: bool,
        ) -> dict[str, Any]:
            assert path.startswith("v2/hojin/updateInfo/")
            self.calls.append((path, params, force_refresh))
            assert force_refresh is True
            if params == {"from": "20260401", "to": "20260501", "page": "1"}:
                return {
                    "hojin-infos": [
                        {"corporate_number": "8010001213708"},
                        {"corporateNumber": "4120101047866"},
                        {"corporate_number": "8010001213708"},
                    ],
                    "totalPage": "2",
                }
            if params == {"from": "20260401", "to": "20260501", "page": "2"}:
                return {
                    "hojin-infos": [
                        {"houjin_bangou": "6010001196811"},
                        {"corporateNumber": "4120101047866"},
                    ],
                    "totalPage": "2",
                }
            raise AssertionError(f"unexpected params: {params}")

    def make_fake_fetch(seen: list[str], family: str) -> Any:
        def fake_fetch(
            _client: FakeClient,
            houjin_bangou: str,
            *,
            force_refresh: bool = False,
        ) -> tuple[list[dict[str, Any]], str]:
            assert force_refresh is True
            seen.append(houjin_bangou)
            return ([{"houjin_bangou": houjin_bangou, "title": family}], "source")

        return fake_fetch

    for family, filename in cases:
        module = _load_module(
            f"gbiz_{family}_for_test",
            REPO_ROOT / "scripts" / "cron" / filename,
        )
        seen: list[str] = []

        monkeypatch.setattr(module, "fetch_per_houjin", make_fake_fetch(seen, family))
        fake_client = FakeClient()
        records, source_url = module.fetch_delta(fake_client, "2026-04-01", "2026-05-01")
        assert [call[1]["page"] for call in fake_client.calls] == ["1", "2"]
        assert seen == ["8010001213708", "4120101047866", "6010001196811"]
        assert [r["houjin_bangou"] for r in records] == [
            "8010001213708",
            "4120101047866",
            "6010001196811",
        ]
        assert source_url.endswith("from=2026-04-01&to=2026-05-01")


@pytest.mark.parametrize(
    ("family", "filename", "table", "record1", "record2", "select_sql", "expected"),
    [
        (
            "subsidy",
            "ingest_gbiz_subsidy_v2.py",
            "gbiz_subsidy_award",
            {
                "houjin_bangou": "8010001213708",
                "subsidy_resource_id": "sub-1",
                "title": "old title",
                "amount_yen": 100,
                "government_departments": "old agency",
            },
            {
                "houjin_bangou": "8010001213708",
                "subsidy_resource_id": "sub-1",
                "title": "new title",
                "amount_yen": 900,
                "government_departments": "new agency",
            },
            "SELECT title, amount_yen, government_departments FROM gbiz_subsidy_award",
            [("new title", 900, "new agency")],
        ),
        (
            "certification",
            "ingest_gbiz_certification_v2.py",
            "gbiz_certification",
            {
                "houjin_bangou": "8010001213708",
                "title": "ISO",
                "date_of_approval": "2026-04-01",
                "government_departments": "METI",
                "category": "old",
                "target": "old target",
            },
            {
                "houjin_bangou": "8010001213708",
                "title": "ISO",
                "date_of_approval": "2026-04-01",
                "government_departments": "METI",
                "category": "new",
                "target": "new target",
            },
            "SELECT category, target FROM gbiz_certification",
            [("new", "new target")],
        ),
        (
            "commendation",
            "ingest_gbiz_commendation_v2.py",
            "gbiz_commendation",
            {
                "houjin_bangou": "8010001213708",
                "title": "Award",
                "date_of_commendation": "2026-04-01",
                "government_departments": "METI",
                "target": "old target",
            },
            {
                "houjin_bangou": "8010001213708",
                "title": "Award",
                "date_of_commendation": "2026-04-01",
                "government_departments": "METI",
                "target": "new target",
            },
            "SELECT target FROM gbiz_commendation",
            [("new target",)],
        ),
        (
            "procurement",
            "ingest_gbiz_procurement_v2.py",
            "gbiz_procurement",
            {
                "houjin_bangou": "8010001213708",
                "procurement_resource_id": "proc-1",
                "title": "old title",
                "amount_yen": 100,
                "government_departments": "old agency",
            },
            {
                "houjin_bangou": "8010001213708",
                "procurement_resource_id": "proc-1",
                "title": "new title",
                "amount_yen": 900,
                "government_departments": "new agency",
            },
            "SELECT title, amount_yen, government_departments FROM gbiz_procurement",
            [("new title", 900, "new agency")],
        ),
    ],
)
def test_gbiz_residual_families_upsert_updates_existing_mirror_rows(
    family: str,
    filename: str,
    table: str,
    record1: dict[str, Any],
    record2: dict[str, Any],
    select_sql: str,
    expected: list[tuple[Any, ...]],
) -> None:
    module = _load_module(
        f"gbiz_{family}_for_upsert_update_test",
        REPO_ROOT / "scripts" / "cron" / filename,
    )
    migration = REPO_ROOT / "scripts" / "migrations" / "wave24_164_gbiz_v2_mirror_tables.sql"
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(migration.read_text(encoding="utf-8"))
        module.upsert_records(
            conn,
            [record1],
            f"https://info.gbiz.go.jp/hojin/v2/hojin/{record1['houjin_bangou']}/{family}",
            "2026-05-06T00:00:00+00:00",
        )
        module.upsert_records(
            conn,
            [record2],
            f"https://info.gbiz.go.jp/hojin/v2/hojin/{record2['houjin_bangou']}/{family}",
            "2026-05-06T01:00:00+00:00",
        )

        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
        assert conn.execute(select_sql).fetchall() == expected
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("family", "filename", "table", "records"),
    [
        (
            "subsidy",
            "ingest_gbiz_subsidy_v2.py",
            "gbiz_subsidy_award",
            [
                {"houjin_bangou": "8010001213708", "subsidy_resource_id": "sub-1", "title": "A"},
                {"houjin_bangou": "4120101047866", "subsidy_resource_id": "sub-2", "title": "B"},
            ],
        ),
        (
            "certification",
            "ingest_gbiz_certification_v2.py",
            "gbiz_certification",
            [
                {
                    "houjin_bangou": "8010001213708",
                    "title": "Cert A",
                    "date_of_approval": "2026-04-01",
                    "government_departments": "METI",
                },
                {
                    "houjin_bangou": "4120101047866",
                    "title": "Cert B",
                    "date_of_approval": "2026-04-01",
                    "government_departments": "METI",
                },
            ],
        ),
        (
            "commendation",
            "ingest_gbiz_commendation_v2.py",
            "gbiz_commendation",
            [
                {
                    "houjin_bangou": "8010001213708",
                    "title": "Award A",
                    "date_of_commendation": "2026-04-01",
                    "government_departments": "METI",
                },
                {
                    "houjin_bangou": "4120101047866",
                    "title": "Award B",
                    "date_of_commendation": "2026-04-01",
                    "government_departments": "METI",
                },
            ],
        ),
        (
            "procurement",
            "ingest_gbiz_procurement_v2.py",
            "gbiz_procurement",
            [
                {
                    "houjin_bangou": "8010001213708",
                    "procurement_resource_id": "proc-1",
                    "title": "A",
                },
                {
                    "houjin_bangou": "4120101047866",
                    "procurement_resource_id": "proc-2",
                    "title": "B",
                },
            ],
        ),
    ],
)
def test_gbiz_residual_families_persist_per_houjin_source_url_and_attribution(
    family: str,
    filename: str,
    table: str,
    records: list[dict[str, Any]],
) -> None:
    module = _load_module(
        f"gbiz_{family}_for_per_houjin_attribution_test",
        REPO_ROOT / "scripts" / "cron" / filename,
    )
    migration = REPO_ROOT / "scripts" / "migrations" / "wave24_164_gbiz_v2_mirror_tables.sql"
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(migration.read_text(encoding="utf-8"))
        for record in records:
            per_houjin_source_url = (
                f"https://info.gbiz.go.jp/hojin/v2/hojin/{record['houjin_bangou']}/{family}"
            )
            record["source_url"] = per_houjin_source_url
            record["_gbiz_source_url"] = per_houjin_source_url
            record["_gbiz_fetch_source_url"] = per_houjin_source_url

        module.upsert_records(
            conn,
            records,
            f"https://info.gbiz.go.jp/hojin/v2/hojin/updateInfo/{family}?from=2026-04-01&to=2026-05-01",
            "2026-05-06T00:00:00+00:00",
        )

        rows = conn.execute(
            f"""
            SELECT houjin_bangou, source_url, attribution_json, raw_json
              FROM {table}
             ORDER BY houjin_bangou
            """
        ).fetchall()
        assert len(rows) == 2
        for houjin_bangou, source_url, attribution_json, raw_json in rows:
            assert source_url == (
                f"https://info.gbiz.go.jp/hojin/v2/hojin/{houjin_bangou}/{family}"
            )
            attribution = json.loads(attribution_json)
            raw = json.loads(raw_json)
            assert attribution["source_url"] == source_url
            assert attribution["upstream_source"]
            assert raw["_attribution"]["source_url"] == source_url
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("family", "filename", "mode_args"),
    [
        ("subsidy", "ingest_gbiz_subsidy_v2.py", ["--houjin-bangou", "8010001213708"]),
        ("certification", "ingest_gbiz_certification_v2.py", ["--houjin-bangou", "8010001213708"]),
        ("commendation", "ingest_gbiz_commendation_v2.py", ["--houjin-bangou", "8010001213708"]),
        ("procurement", "ingest_gbiz_procurement_v2.py", ["--houjin-bangou", "8010001213708"]),
    ],
)
def test_gbiz_residual_families_check_schema_before_fetch(
    monkeypatch: Any,
    tmp_path: Path,
    family: str,
    filename: str,
    mode_args: list[str],
) -> None:
    module = _load_module(
        f"gbiz_{family}_for_schema_before_fetch_test",
        REPO_ROOT / "scripts" / "cron" / filename,
    )
    db_path = tmp_path / "gbiz.sqlite"
    sqlite3.connect(db_path).close()
    client_calls: list[str] = []
    fetch_calls: list[str] = []

    def fake_client() -> object:
        client_calls.append("client")
        return object()

    def fail_fetch(*_args: Any, **_kwargs: Any) -> tuple[list[dict[str, Any]], str]:
        fetch_calls.append("fetch")
        raise AssertionError("fetch must not run before schema check")

    monkeypatch.setattr(module, "GbizRateLimitedClient", fake_client)
    monkeypatch.setattr(module, "fetch_per_houjin", fail_fetch)
    monkeypatch.setattr(sys, "argv", [filename, *mode_args, "--db-path", str(db_path)])

    assert module.main() == 2
    assert client_calls == []
    assert fetch_calls == []


@pytest.mark.parametrize(
    ("family", "filename"),
    [
        ("subsidy", "ingest_gbiz_subsidy_v2.py"),
        ("certification", "ingest_gbiz_certification_v2.py"),
        ("commendation", "ingest_gbiz_commendation_v2.py"),
        ("procurement", "ingest_gbiz_procurement_v2.py"),
    ],
)
def test_gbiz_residual_families_main_rolls_back_partial_db_writes(
    monkeypatch: Any,
    tmp_path: Path,
    family: str,
    filename: str,
) -> None:
    module = _load_module(
        f"gbiz_{family}_for_transaction_test",
        REPO_ROOT / "scripts" / "cron" / filename,
    )
    db_path = tmp_path / "gbiz.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE marker(value TEXT)")
        conn.commit()
    finally:
        conn.close()

    class FakeClient:
        pass

    def fake_fetch_delta(
        _client: FakeClient,
        _date_from: str,
        _date_to: str,
    ) -> tuple[list[dict[str, Any]], str]:
        return ([{"houjin_bangou": "8010001213708", "title": "x"}], "source")

    def fake_upsert_records(
        conn: sqlite3.Connection,
        _records: list[dict[str, Any]],
        _source_url: str,
        _fetched_at: str,
    ) -> dict[str, int]:
        conn.execute("INSERT INTO marker(value) VALUES ('partial')")
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(module, "GbizRateLimitedClient", lambda: FakeClient())
    monkeypatch.setattr(module, "fetch_delta", fake_fetch_delta)
    monkeypatch.setattr(module, "_ensure_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "upsert_records", fake_upsert_records)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            filename,
            "--from",
            "2026-04-01",
            "--to",
            "2026-05-01",
            "--db-path",
            str(db_path),
        ],
    )

    with pytest.raises(RuntimeError, match="simulated write failure"):
        module.main()

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT value FROM marker").fetchall() == []
    finally:
        conn.close()


def test_residual_delta_main_rolls_back_partial_db_writes(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    module = _load_module(
        "gbiz_subsidy_for_transaction_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_subsidy_v2.py",
    )
    db_path = tmp_path / "gbiz.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE marker(value TEXT)")
    conn.commit()
    conn.close()

    class FakeClient:
        pass

    def fake_fetch_delta(
        _client: FakeClient,
        _date_from: str,
        _date_to: str,
    ) -> tuple[list[dict[str, Any]], str]:
        return ([{"houjin_bangou": "8010001213708", "title": "x"}], "source")

    def fake_upsert_records(
        conn: sqlite3.Connection,
        _records: list[dict[str, Any]],
        _source_url: str,
        _fetched_at: str,
    ) -> dict[str, int]:
        conn.execute("INSERT INTO marker(value) VALUES ('partial')")
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(module, "GbizRateLimitedClient", lambda: FakeClient())
    monkeypatch.setattr(module, "fetch_delta", fake_fetch_delta)
    monkeypatch.setattr(module, "_ensure_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "upsert_records", fake_upsert_records)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_gbiz_subsidy_v2.py",
            "--from",
            "2026-04-01",
            "--to",
            "2026-05-01",
            "--db-path",
            str(db_path),
        ],
    )

    with pytest.raises(RuntimeError, match="simulated write failure"):
        module.main()

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT value FROM marker").fetchall() == []
    finally:
        conn.close()


def test_bulk_dry_run_does_not_mark_digest_ingested(tmp_path: Path) -> None:
    module = _load_module(
        "gbiz_bulk_for_test",
        REPO_ROOT / "scripts" / "cron" / "ingest_gbiz_bulk_jsonl_monthly.py",
    )
    zip_path = tmp_path / "gbiz.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "corp.jsonl",
            '{"corporate_number":"8010001213708","name":"Bookyou"}\n',
        )
    output_dir = tmp_path / "out"
    rc = module.main(
        [
            "--dry-run",
            "--zip-path",
            str(zip_path),
            "--output-dir",
            str(output_dir),
            "--db",
            str(tmp_path / "unused.sqlite"),
        ]
    )
    assert rc == 0
    digest_log = output_dir / "digest.log"
    assert not digest_log.exists() or digest_log.read_text(encoding="utf-8").strip() == ""
    assert (output_dir / "MANIFEST.json").exists()


def test_gbiz_monthly_workflow_uses_single_fly_app_and_serial_delta() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "gbiz-ingest-monthly.yml").read_text(
        encoding="utf-8"
    )
    assert "FLY_APP: autonomath-api" in workflow
    assert 'flyctl ssh console -a "${FLY_APP}"' in workflow
    assert "max-parallel: 1" in workflow
