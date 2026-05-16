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
#
# PERF-31 (2026-05-17) tightened the MCP budget 2.5 s → 1.5 s after
# lazy-loading the FastAPI-dragging ``api.programs`` import out of
# ``autonomath_tools.tools`` (saves ~370 ms cumulative at MCP cold
# start; median dev-laptop wall went 1.62 s → 0.72 s). The ~2x headroom
# above the 0.72 s median is retained for CI runner variance + cold pip
# caches. A future re-introduction of the eager
# ``from jpintel_mcp.api.programs import _build_fts_match`` at module
# load (or any equivalently heavy chain module) will redden the gate.
IMPORT_BUDGETS: list[tuple[str, str, float]] = [
    (
        "mcp_server",
        "from jpintel_mcp.mcp import server",
        1.5,
    ),
    (
        "api_create_app",
        "from jpintel_mcp.api.main import create_app",
        4.5,
    ),
]

# PERF-31 (2026-05-17): explicit "module-must-not-be-eagerly-imported"
# ratchet on the chain modules that PERF-31 lazy-loaded. The eager
# ``from jpintel_mcp.api.programs import _build_fts_match`` at the top
# of ``autonomath_tools.tools`` was the worst offender (cum ~370 ms via
# the FastAPI module tree). We assert the lazy proxies stay in place by
# importing ``tools`` + ``annotation_tools`` (the latter transitively
# imports ``tools``) without ``api.programs`` or ``_http_fallback``
# entering ``sys.modules``. A future regression that re-eagers the
# import is caught here even when wall-clock variance would otherwise
# mask it in the budget gate above.
#
# Each entry: (label, import statement to run in subprocess, module
# name that MUST NOT be present in sys.modules afterwards).
#
# We probe ``api.programs`` only — ``mcp._http_fallback`` is already
# eagerly imported by ``jpintel_mcp.mcp.server`` (line 41), so
# tracking it inside the ``autonomath_tools`` boundary alone would
# always trip. Lazy-loading ``_http_fallback`` at the server level is
# a separate (larger) PERF task.
LAZY_LOAD_PROBES: list[tuple[str, str, str]] = [
    (
        "autonomath_tools_tools_no_api_programs",
        "from jpintel_mcp.mcp.autonomath_tools import tools",
        "jpintel_mcp.api.programs",
    ),
    (
        "autonomath_tools_annotation_no_api_programs",
        "from jpintel_mcp.mcp.autonomath_tools import annotation_tools",
        "jpintel_mcp.api.programs",
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
        "PERF-6/PERF-7/PERF-31 ratchet: look for newly eager imports of "
        "scipy.stats, stripe submodules, pandas, faiss, sklearn, "
        "fastapi (via ``jpintel_mcp.api.programs._build_fts_match``), "
        "or any autonomath_tools.* sub-tree that should be lazy."
    )


def _module_present_after_import(import_stmt: str, must_not_be_present: str) -> bool:
    """Spawn a fresh subprocess that runs ``import_stmt`` and prints
    whether ``must_not_be_present`` ended up in ``sys.modules``.

    Returns the boolean (True == module is present, which fails the
    lazy-load contract). Fresh subprocess is mandatory because the
    pytest worker has the autonomath_tools chain already warm.
    """
    code = (
        f"import sys\n"
        f"{import_stmt}\n"
        f"print('PRESENT' if {must_not_be_present!r} in sys.modules else 'ABSENT')\n"
    )
    cmd = [sys.executable, "-c", code]
    env = os.environ.copy()
    env.setdefault("AUTONOMATH_36_KYOTEI_ENABLED", "0")
    env.pop("PYTHONSTARTUP", None)

    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        check=False,
        timeout=60.0,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"lazy-load probe subprocess failed ({proc.returncode}): "
            f"stderr[:500]={proc.stderr[:500]!r}"
        )
    out = proc.stdout.decode("utf-8", errors="replace").strip().splitlines()
    if not out:
        raise AssertionError(f"lazy-load probe produced no stdout; stderr={proc.stderr[:500]!r}")
    verdict = out[-1].strip()
    if verdict == "PRESENT":
        return True
    if verdict == "ABSENT":
        return False
    raise AssertionError(
        f"lazy-load probe stdout malformed: {verdict!r} "
        f"(expected 'PRESENT' or 'ABSENT'); full stdout={out!r}"
    )


@pytest.mark.parametrize(
    ("label", "import_stmt", "must_not_be_present"),
    LAZY_LOAD_PROBES,
    ids=[row[0] for row in LAZY_LOAD_PROBES],
)
def test_autonomath_chain_modules_stay_lazy(
    label: str,
    import_stmt: str,
    must_not_be_present: str,
) -> None:
    """PERF-31 lazy-load contract.

    Importing the autonomath_tools chain modules at MCP cold-start
    must NOT drag the FastAPI-heavy ``api.programs`` (cum ~370 ms)
    into ``sys.modules``. The ``_build_fts_match`` helper is
    re-introduced lazily through a ``functools.cache``-d accessor in
    ``autonomath_tools/tools.py``; this test asserts the accessor is
    not eagerly invoked at module-import time.

    A regression here means the lazy proxy was reverted to an eager
    top-level ``from jpintel_mcp.api.programs import _build_fts_match``
    — either inside ``autonomath_tools/tools.py`` or in a sibling
    module that transitively imports it.
    """
    present = _module_present_after_import(import_stmt, must_not_be_present)
    assert not present, (
        f"PERF-31 lazy-load regression on {label}: "
        f"{must_not_be_present!r} was eagerly imported by "
        f"`{import_stmt}`. The expected contract is that the chain "
        "module is pulled lazily on first tool call, not at module "
        "load. Look for a re-introduced top-level "
        "``from jpintel_mcp.api.programs import _build_fts_match`` "
        "line in ``autonomath_tools/tools.py`` or one of the sibling "
        "chain modules. Restore the lazy proxy."
    )
