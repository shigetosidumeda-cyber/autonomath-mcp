"""Smoke + contract tests for `scripts/cron/ingest_nta_invoice_bulk.py`.

These tests pin behaviour that protects three regressions:

  1. The driver imports the underlying ETL primitive
     (`scripts/ingest/ingest_invoice_registrants.py`) at module load
     time. If a refactor renames or moves that file, this test fails
     loud and obvious, not silently at the next monthly cron 03:00 JST.

  2. The driver respects the `--dry-run` + `--limit` flags by forwarding
     them verbatim to the ingest subprocess. Cron operators rely on
     `--limit 1000 --dry-run` to safely preview a new bulk before the
     full run.

  3. The disk-space gate refuses to run a `--mode full` ingest when the
     filesystem holding the DB has < 2 GB free. We cannot write 4M rows
     onto a near-full Fly volume without WAL bloat → corruption.

The tests are intentionally lightweight: no network, no NTA fetch, no
SQLite schema. They pin the *contract* between this driver and its
operating environment — actual end-to-end ingest is exercised by the
weekly workflow run on the Fly volume.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER_PATH = REPO_ROOT / "scripts" / "cron" / "ingest_nta_invoice_bulk.py"
INGEST_PATH = REPO_ROOT / "scripts" / "ingest" / "ingest_invoice_registrants.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "nta-bulk-monthly.yml"


def _load_driver():
    spec = importlib.util.spec_from_file_location(
        "ingest_nta_invoice_bulk", DRIVER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_driver_imports_underlying_ingest_primitive() -> None:
    """Renaming ingest_invoice_registrants.py would break this driver."""
    assert INGEST_PATH.is_file(), (
        "scripts/ingest/ingest_invoice_registrants.py is the ETL primitive "
        "the cron driver wraps; renaming it without updating "
        "scripts/cron/ingest_nta_invoice_bulk.py would break the monthly "
        "cron silently."
    )
    drv = _load_driver()
    # The driver imports `ingest_invoice_registrants` at module load
    # for its `discover_dl_fil_kanri_no` helper. If that import broke,
    # _load_driver() above would already have raised.
    assert hasattr(drv, "_iv"), (
        "driver did not expose the ingest module reference — refactor "
        "drift; expected `_iv = import ingest_invoice_registrants`"
    )
    assert hasattr(drv._iv, "discover_dl_fil_kanri_no"), (
        "ingest module missing discover_dl_fil_kanri_no — date discovery "
        "in the cron driver depends on it"
    )


def test_build_ingest_argv_forwards_dry_run_and_limit() -> None:
    drv = _load_driver()
    argv = drv._build_ingest_argv(
        db_path=Path("/tmp/test.db"),
        mode="delta",
        fmt="csv",
        date_str="2026-04-01",
        limit=1000,
        dry_run=True,
        cache_dir=Path("/tmp/cache"),
        batch_size=10000,
    )
    # Must include --dry-run, --limit 1000, --batch-size 10000, --mode delta.
    assert "--dry-run" in argv
    assert "--limit" in argv
    assert argv[argv.index("--limit") + 1] == "1000"
    assert "--mode" in argv
    assert argv[argv.index("--mode") + 1] == "delta"
    assert "--batch-size" in argv
    assert argv[argv.index("--batch-size") + 1] == "10000"
    # Must point at the real ingest script.
    assert str(INGEST_PATH) in argv


def test_disk_gate_rejects_full_mode_when_volume_low() -> None:
    drv = _load_driver()
    with mock.patch.object(drv, "_free_bytes", return_value=500 * 1024 * 1024):
        # 500 MB free < 2 GB threshold → gate must reject.
        ok = drv._gate_disk(Path("/tmp/x"), "full")
        assert ok is False
    with mock.patch.object(drv, "_free_bytes", return_value=5 * 1024 * 1024 * 1024):
        # 5 GB free > 2 GB → gate passes.
        ok = drv._gate_disk(Path("/tmp/x"), "full")
        assert ok is True


def test_disk_gate_uses_lighter_threshold_for_delta() -> None:
    drv = _load_driver()
    # 500 MB free passes the delta threshold (200 MB) but fails full (2 GB).
    with mock.patch.object(drv, "_free_bytes", return_value=500 * 1024 * 1024):
        assert drv._gate_disk(Path("/tmp/x"), "delta") is True
        assert drv._gate_disk(Path("/tmp/x"), "full") is False


def test_workflow_file_uses_jpintel_db_path_and_120_min_timeout() -> None:
    """Three contract pins on the workflow file itself."""
    assert WORKFLOW_PATH.is_file(), "nta-bulk-monthly.yml missing"
    wf = WORKFLOW_PATH.read_text(encoding="utf-8")
    # Schedule: 1st of month, 18:00 UTC = 03:00 JST.
    assert '0 18 1 * *' in wf, (
        "monthly cron schedule must be '0 18 1 * *' (03:00 JST 1st of month)"
    )
    # Path: must write to /data/jpintel.db, NOT /data/autonomath.db.
    assert "--db /data/jpintel.db" in wf, (
        "invoice_registrants lives in jpintel.db (migration 019); the "
        "workflow MUST NOT point --db at autonomath.db"
    )
    # Timeout: 120 min for the 25-40 min CSV ingest + 2x headroom.
    assert "timeout-minutes: 120" in wf, (
        "monthly bulk needs 120 min to absorb a 4M-row CSV with cold cache"
    )


def test_zenken_date_picks_first_of_month() -> None:
    drv = _load_driver()
    from datetime import date as _date

    assert drv._latest_zenken_date(_date(2026, 4, 29)) == _date(2026, 4, 1)
    assert drv._latest_zenken_date(_date(2026, 4, 1)) == _date(2026, 4, 1)
    assert drv._latest_zenken_date(_date(2026, 12, 31)) == _date(2026, 12, 1)
