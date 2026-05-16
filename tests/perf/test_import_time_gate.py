"""PERF-27 cold-start import-time regression gate.

Locks in the post PERF-6 / PERF-7 cold-import wall time for the two
canonical entry points so a future refactor that re-bloats the import
chain (eager ``scipy.stats``, eager ``stripe``, eager autonomath tools
module tree, eager FAISS, eager pandas, etc.) trips the gate before
hitting production.

Two entry points are gated:

  * ``from jpintel_mcp.mcp import server`` — MCP stdio cold start
    (target < 1.5 s wall, PERF-6 ratchet from 1.83 s).
  * ``from jpintel_mcp.api.main import create_app`` — FastAPI cold app
    construction (target < 3.0 s wall, PERF-7 ratchet from 7.12 s).

Each measurement spawns a **fresh** Python subprocess so the test is
not contaminated by ``sys.modules`` already being warm under pytest.
That is the only honest way to measure "cold" import time inside an
in-process test runner.

Budgets sit ~1.6-2x above the median measured on an M-series macOS
runner on 2026-05-17:

  * MCP median over 3 runs: ~1.55 s wall   → budget 2.5 s
  * API median over 3 runs: ~2.55 s wall   → budget 4.5 s

The asymmetric headroom (vs the 1.5 s / 3.0 s aspirational targets in
``docs/_internal/PERFORMANCE_SOT_2026_05_16.md``) reflects two facts:

  1. CI runners are slower than dev laptops; PERF-6 1.83 s on dev box
     can translate to ~3.0 s on a GHA ubuntu-latest cold runner with
     a cold pip cache.
  2. We want the gate to trip on real regressions (eager scipy etc.
     adds 1.0+ s), not on per-runner jitter.

Skipped on CI by default; opt in with either::

    JPCITE_RUN_PERF_GATES=1 pytest tests/perf/test_import_time_gate.py
    pytest tests/perf/test_import_time_gate.py --runperf

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Each entry: (label, import statement, budget seconds wall time).
#
# Budgets are deliberately ~1.6-2x above the median measured on a dev
# laptop, leaving room for CI runner variance + cold pip caches while
# still tripping on a real regression (e.g. eager scipy.stats adds
# ~1.0 s, eager pandas adds ~0.7 s, eager stripe sub-import tree adds
# ~0.4 s — any of those should redden the gate).
IMPORT_BUDGETS: list[tuple[str, str, float]] = [
    (
        "mcp_server",
        "from jpintel_mcp.mcp import server",
        2.5,
    ),
    (
        "api_create_app",
        "from jpintel_mcp.api.main import create_app",
        4.5,
    ),
]

WARMUP_ITERATIONS = 1
MEASURE_ITERATIONS = 3

REPO_ROOT = Path(__file__).resolve().parents[2]


def _opt_in(request: pytest.FixtureRequest) -> bool:
    """Return True when the perf suite is opted in.

    Two routes share the same opt-in (see ``conftest.py``):
      * ``--runperf`` CLI flag
      * ``JPCITE_RUN_PERF_GATES=1`` env var
    """
    try:
        flag = bool(request.config.getoption("--runperf"))
    except (ValueError, KeyError):
        flag = False
    env = os.environ.get("JPCITE_RUN_PERF_GATES") == "1"
    return flag or env


def _measure_cold_import_seconds(import_stmt: str) -> float:
    """Spawn a fresh subprocess that runs ``import_stmt`` and return
    the wall time in seconds.

    A fresh subprocess is mandatory because ``sys.modules`` inside the
    pytest worker already has ``jpintel_mcp.*`` cached from the
    collection phase — measuring it here would always report
    sub-millisecond and miss every regression.
    """
    # ``-I`` (isolated) drops user site-packages + ``PYTHONSTARTUP`` and
    # is closer to the production entrypoint shape. We do NOT pass
    # ``-S`` because the venv's site.py registers the venv site dir
    # which we need for the jpintel_mcp install.
    cmd = [sys.executable, "-c", import_stmt]
    env = os.environ.copy()
    # Defang anything that might add boot work (e.g. autonomath gates
    # that pull in heavy template trees only relevant in production).
    env.setdefault("AUTONOMATH_36_KYOTEI_ENABLED", "0")
    # Don't let a stray PYTHONPATH override the installed package.
    env.pop("PYTHONSTARTUP", None)

    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        check=False,
        timeout=60.0,
    )
    elapsed = time.perf_counter() - t0
    if proc.returncode != 0:
        raise AssertionError(
            f"cold-import subprocess failed ({proc.returncode}): stderr[:500]={proc.stderr[:500]!r}"
        )
    return elapsed


pytestmark = pytest.mark.skipif(
    os.environ.get("JPCITE_RUN_PERF_GATES") != "1" and "--runperf" not in sys.argv,
    reason=(
        "perf gate disabled by default; set JPCITE_RUN_PERF_GATES=1 or pass --runperf to opt in"
    ),
)


@pytest.mark.parametrize(
    ("label", "import_stmt", "budget_s"),
    IMPORT_BUDGETS,
    ids=[row[0] for row in IMPORT_BUDGETS],
)
def test_cold_import_under_budget(label: str, import_stmt: str, budget_s: float) -> None:
    """Cold-import wall time must stay under :data:`IMPORT_BUDGETS`.

    Measures via :func:`_measure_cold_import_seconds` which spawns a
    fresh subprocess per iteration. The reported number is the median
    of :data:`MEASURE_ITERATIONS` runs after :data:`WARMUP_ITERATIONS`
    discarded warm-up runs (filesystem cache priming).
    """
    # Warmup so the OS page cache for the .pyc files is warm and we
    # don't accidentally gate on first-touch disk I/O on a cold CI
    # runner. This still represents a fair "cold import" because
    # Python's in-process import machinery starts from zero each run.
    for _ in range(WARMUP_ITERATIONS):
        _measure_cold_import_seconds(import_stmt)

    samples_s: list[float] = []
    for _ in range(MEASURE_ITERATIONS):
        samples_s.append(_measure_cold_import_seconds(import_stmt))

    samples_s.sort()
    median_s = samples_s[len(samples_s) // 2]
    max_s = samples_s[-1]

    assert median_s <= budget_s, (
        f"cold-import regression on {label}: median {median_s:.2f}s, "
        f"budget {budget_s:.2f}s "
        f"(samples={[f'{s:.2f}s' for s in samples_s]}, "
        f"max={max_s:.2f}s). "
        "PERF-6/PERF-7 ratchet: look for newly eager imports of "
        "scipy.stats, stripe submodules, pandas, faiss, sklearn, "
        "or any autonomath_tools.* sub-tree that should be lazy."
    )
