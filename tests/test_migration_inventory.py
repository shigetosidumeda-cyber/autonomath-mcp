from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "migration_inventory.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("migration_inventory", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_classify_filename() -> None:
    mod = _load_module()

    assert mod.classify_filename("001_init.sql") == ("numeric", "001")
    assert mod.classify_filename("wave24_110a_cleanup.sql") == ("wave24", "110a")
    assert mod.classify_filename("notes.txt") == ("other", "")


def test_render_markdown_flags_duplicates_rollbacks_and_danger(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "001_init.sql").write_text(
        "-- target_db: autonomath\ncreate table x(id integer);",
        encoding="utf-8",
    )
    (tmp_path / "001_other.sql").write_text(
        "delete from x;",
        encoding="utf-8",
    )
    (tmp_path / "001_other_rollback.sql").write_text(
        "-- target_db: autonomath\ndrop table x;",
        encoding="utf-8",
    )
    (tmp_path / "wave24_110a_cleanup.sql").write_text(
        "alter table x drop column y;",
        encoding="utf-8",
    )
    (tmp_path / "wave24_999_missing_rollback.sql").write_text("drop index i;", encoding="utf-8")

    text = mod.render_markdown(tmp_path)

    assert "Migration Inventory" in text
    assert "duplicate_forward_numeric_prefixes: `1`" in text
    assert "orphan_rollbacks: `1`" in text
    assert "`001`:" in text
    assert "delete_from" in text
    assert "drop_column" in text
    assert "unmarked_target_db_files: `3`" in text


def test_target_db_and_manual_directives_match_runner_header(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "001_header.sql").write_text(
        "-- target_db: autonomath\n-- boot_time: manual\nselect 1;\n",
        encoding="utf-8",
    )
    (tmp_path / "002_late_directive.sql").write_text(
        "select 1;\n"
        "select 2;\n"
        "select 3;\n"
        "select 4;\n"
        "select 5;\n"
        "-- target_db: autonomath\n"
        "-- boot_time: manual\n",
        encoding="utf-8",
    )

    items = {item.name: item for item in mod.collect_migrations(tmp_path)}

    assert items["001_header.sql"].target_db == "autonomath"
    assert items["001_header.sql"].is_manual is True
    assert items["002_late_directive.sql"].target_db == "unmarked"
    assert items["002_late_directive.sql"].is_manual is False


def test_wave24_164_and_wave24_166_target_db_boundaries() -> None:
    mod = _load_module()
    items = {
        item.name: item for item in mod.collect_migrations(REPO_ROOT / "scripts" / "migrations")
    }

    assert items["wave24_164_gbiz_v2_mirror_tables.sql"].target_db == "autonomath"
    assert items["wave24_166_credit_pack_reservation.sql"].target_db == "jpintel"


def test_preflight_failures_are_opt_in(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "001_safe.sql").write_text(
        "-- target_db: autonomath\ncreate table x(id integer);",
        encoding="utf-8",
    )
    (tmp_path / "002_unmarked.sql").write_text(
        "create table y(id integer);",
        encoding="utf-8",
    )
    (tmp_path / "003_danger.sql").write_text(
        "-- target_db: autonomath\ndelete from x;",
        encoding="utf-8",
    )

    assert mod.preflight_failures(tmp_path) == []
    failures = mod.preflight_failures(
        tmp_path,
        fail_on_unmarked_target_db=True,
        fail_on_dangerous_forward_sql=True,
    )

    assert len(failures) == 2
    assert "002_unmarked.sql" in failures[0]
    assert "003_danger.sql" in failures[1]
