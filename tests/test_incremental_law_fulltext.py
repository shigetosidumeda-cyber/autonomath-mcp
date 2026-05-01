"""Contract tests for the e-Gov incremental full-text loader.

These tests pin the B4 operating defaults without touching the database or
network: the cron driver and workflow should both default to a 600-law batch,
and the workflow should have enough timeout headroom for that larger batch.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER_PATH = REPO_ROOT / "scripts" / "cron" / "incremental_law_fulltext.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "incremental-law-load.yml"


def _load_driver():
    spec = importlib.util.spec_from_file_location(
        "incremental_law_fulltext",
        DRIVER_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_driver_defaults_to_600_laws_per_batch() -> None:
    drv = _load_driver()

    assert drv._DEFAULT_LIMIT == 600
    assert drv._parse_args([]).limit == 600


def test_workflow_defaults_to_600_with_90_min_timeout() -> None:
    assert WORKFLOW_PATH.is_file(), "incremental-law-load.yml missing"
    wf = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert 'default: "600"' in wf
    assert 'LIMIT="${INPUT_LIMIT:-600}"' in wf
    assert "timeout-minutes: 90" in wf
