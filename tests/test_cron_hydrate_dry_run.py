"""Wave 49 G3 — cron hydrate dry-run gate tests.

Verifies that the 5 AX Layer 5 ETL scripts wired into the daily/monthly
cron workflows succeed (exit 0) when invoked with ``--dry-run`` even
though the operator DB (``autonomath.db``) has not been hydrated yet.

Background
----------
The cron workflows in ``.github/workflows/`` invoke each ETL with
``--dry-run`` as a planning step before optionally writing. On a fresh
CI runner (or during a Fly cold start) the DB file does not exist, so
the pre-Wave-49 hard gate would exit 2 with ``DB not found`` and tear
the whole workflow down. Wave 49 G3 relaxes the gate to a placeholder
JSON payload + exit 0 when ``--dry-run`` is set, and leaves the strict
gate (exit 2) intact for real runs.

Each test invokes the script in a subprocess with a non-existent
``--db`` path so that we don't rely on the real ``autonomath.db`` on
disk. The subprocess must:

* exit 0
* emit a single JSON line on stdout
* include ``"dry_run": true`` and ``"db_not_found_dry_run": true``

This contract is what the cron workflow's ``Dry-run sanity probe`` step
needs in order to plan a no-op rather than fail the entire job.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 5 scripts under test. Mirror of the workflow invocations:
#   .github/workflows/predictive-events-daily.yml         -> build_predictive_watch_v2.py
#   .github/workflows/session-context-daily.yml           -> clean_session_context_expired.py
#   .github/workflows/composed-tools-invocation-daily.yml -> seed_composed_tools.py
#   .github/workflows/time-machine-snapshot-monthly.yml   -> build_monthly_snapshot.py
#   .github/workflows/anonymized-cohort-audit-daily.yml   -> aggregate_anonymized_outcomes.py
SCRIPTS: list[tuple[str, str]] = [
    ("scripts/etl/build_predictive_watch_v2.py", "T"),
    ("scripts/etl/clean_session_context_expired.py", "L"),
    ("scripts/etl/seed_composed_tools.py", "P"),
    ("scripts/etl/build_monthly_snapshot.py", "Q"),
    ("scripts/etl/aggregate_anonymized_outcomes.py", "N"),
]


def _run(script_rel: str, db_path: Path, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Invoke the ETL script with --dry-run in a subprocess.

    Passing an explicit --db to a non-existent path proves the gate works
    even when the real autonomath.db is sitting next to the repo on disk
    (which it is for the user's local jpcite repo). Without this we'd be
    flaky depending on whether the local file is present.
    """
    cmd = [
        sys.executable,
        str(REPO_ROOT / script_rel),
        "--dry-run",
        "--db",
        str(db_path),
    ]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize(("script_rel", "dim"), SCRIPTS)
def test_dry_run_succeeds_without_db(tmp_path: Path, script_rel: str, dim: str) -> None:
    """Each cron-invoked ETL must exit 0 under --dry-run when DB is missing."""
    missing_db = tmp_path / "definitely-does-not-exist.db"
    assert not missing_db.exists()

    proc = _run(script_rel, missing_db)

    assert proc.returncode == 0, (
        f"{script_rel} --dry-run should exit 0 when DB missing; "
        f"got rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    # stdout must contain a JSON line with the dry-run + missing-db markers.
    # We accept additional log lines from logging.basicConfig if any leak to
    # stdout — pluck the last non-empty line that parses as JSON.
    payload = _extract_last_json_line(proc.stdout)
    assert payload is not None, (
        f"{script_rel} --dry-run did not emit a JSON line on stdout. "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert payload.get("dry_run") is True, (
        f"{script_rel} --dry-run payload missing dry_run=true: {payload}"
    )
    assert payload.get("db_not_found_dry_run") is True, (
        f"{script_rel} --dry-run payload missing db_not_found_dry_run=true: {payload}"
    )


def test_dry_run_does_not_create_db(tmp_path: Path) -> None:
    """The dry-run path must NOT create the DB file as a side effect."""
    missing_db = tmp_path / "should-stay-missing.db"
    for script_rel, _ in SCRIPTS:
        proc = _run(script_rel, missing_db)
        assert proc.returncode == 0, (
            f"{script_rel} unexpectedly failed under dry-run: {proc.stderr}"
        )
        assert not missing_db.exists(), (
            f"{script_rel} created {missing_db} during dry-run; should remain absent"
        )


def test_non_dry_run_still_exits_2_when_db_missing(tmp_path: Path) -> None:
    """Strict gate is preserved for real runs (no --dry-run flag)."""
    missing_db = tmp_path / "really-missing.db"
    for script_rel, _ in SCRIPTS:
        cmd = [
            sys.executable,
            str(REPO_ROOT / script_rel),
            "--db",
            str(missing_db),
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 2, (
            f"{script_rel} without --dry-run should exit 2 when DB missing; "
            f"got rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )


def _extract_last_json_line(stdout: str) -> dict | None:
    """Find the last stdout line that parses as a JSON object."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None
