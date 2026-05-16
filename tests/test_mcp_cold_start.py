"""MCP cold-start regression gate (PERF-6).

Background
----------
``jpintel_mcp.mcp.server`` registers 184 tools at default gates. Each
tool used to drag in heavy modules (``stripe`` ~310ms, ``pykakasi``
~437ms, ``fastapi.openapi.models`` ~80ms, ``mcp.types`` ~55ms) at
module-init time, pushing cold start to ~1.6-1.8 s.

PERF-6 lazy-loaded the four worst offenders:

* ``jpintel_mcp.api.me`` — ``stripe`` via PEP 562 ``__getattr__`` hook
* ``jpintel_mcp.api.billing`` — same pattern
* ``jpintel_mcp.api.compliance`` — same pattern
* ``jpintel_mcp.api.device_flow`` — same pattern
* ``jpintel_mcp.utils.slug`` — ``pykakasi.kakasi()`` deferred to first
  slug emission
* ``jpintel_mcp.mcp.autonomath_tools.tools`` — ``api.programs`` rewriter
  imported inside the call site, not at module init

PERF-6 resubmit (2026-05-16) extends the same pattern to six more
``autonomath_tools`` modules that drag ``fastapi.openapi.models`` (cum
~76 ms) via their REST companions:

* ``mcp.autonomath_tools.eligibility_tools`` → defers
  ``api.eligibility_check`` (cum 98 ms); inlines the two int constants
  used in ``Field(le=...)`` signatures with a parity guard.
* ``mcp.autonomath_tools.succession_tools`` → defers ``api.succession``
* ``mcp.autonomath_tools.source_manifest_tools`` →
  defers ``api.source_manifest``
* ``mcp.autonomath_tools.health_tool`` → defers ``api._health_deep``
* ``mcp.autonomath_tools.timeline_trend_tools`` →
  defers ``api.timeline_trend``
* ``mcp.autonomath_tools.validation_tools`` →
  defers ``api._validation_predicates``

All six use the ``@functools.cache``-wrapped ``_api()`` accessor; the
real REST module is imported only on first MCP tool invocation. Cold
start dropped from **1.83 s → 0.70 s** (best of 5 fresh subprocess).

This test runs ``from jpintel_mcp.mcp import server`` in a fresh
subprocess (so the import cache is cold) and asserts the wall-clock
import time stays under the regression budget.

Budget
------
``COLD_START_BUDGET_SEC`` is set to **1.2 s** — well below the
pre-PERF-6 baseline of ~1.6 s but above the steady-state ~0.9 s
measured on a 2026-05-16 dev laptop, leaving headroom for slower CI
runners. Drop the budget if cold start improves; raise it only with a
documented reason (e.g. SDK upgrade adds unavoidable cost).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COLD_START_BUDGET_SEC = 1.2
COLD_START_SAMPLES = 3


def _run_cold_start_once() -> float:
    """Spawn a fresh Python subprocess that imports the MCP server.

    Returns the wall-clock seconds the subprocess took. Each invocation
    starts from a cold import cache because the subprocess is fresh.
    """
    cmd = [
        sys.executable,
        "-c",
        "from jpintel_mcp.mcp import server; assert server.mcp._tool_manager._tools",
    ]
    env = os.environ.copy()
    # Avoid PYTHONDONTWRITEBYTECODE etc. side effects.
    env.setdefault("PYTHONHASHSEED", "0")

    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        check=False,
        timeout=30,
    )
    elapsed = time.perf_counter() - start
    assert proc.returncode == 0, (
        f"MCP server cold-start failed (rc={proc.returncode}): "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    return elapsed


@pytest.mark.benchmark
def test_mcp_cold_start_under_budget() -> None:
    """Best-of-3 cold start stays under ``COLD_START_BUDGET_SEC``.

    We use the minimum (best-of) across ``COLD_START_SAMPLES`` runs to
    smooth over noisy CI scheduling. The pre-PERF-6 baseline was ~1.6 s;
    the 1.2 s budget catches a regression long before the old baseline
    re-emerges.
    """
    samples = [_run_cold_start_once() for _ in range(COLD_START_SAMPLES)]
    best = min(samples)
    assert best < COLD_START_BUDGET_SEC, (
        f"MCP cold start regression: best-of-{COLD_START_SAMPLES} = {best:.3f}s, "
        f"budget = {COLD_START_BUDGET_SEC:.3f}s, samples = {samples!r}. "
        "Re-profile with `.venv/bin/python -X importtime -c "
        "'from jpintel_mcp.mcp import server'` and lazy-load the worst "
        "module-init offender (see PERF-6 lazy-load pattern in "
        "src/jpintel_mcp/api/me.py)."
    )


@pytest.mark.benchmark
def test_lazy_stripe_loaders_resolve() -> None:
    """Lazy ``stripe`` resolvers in the four api modules must still work.

    Importing ``stripe`` is gated through ``module.__getattr__`` (PEP
    562). Make sure each module's hook returns the real ``stripe`` SDK
    on first access — a typo in the hook would only break at call time
    in production, not at import time.
    """
    from jpintel_mcp.api import billing, compliance, device_flow

    for mod in (billing, compliance, device_flow):
        stripe_mod = mod.stripe  # type: ignore[attr-defined]
        assert stripe_mod is not None
        assert getattr(stripe_mod, "__name__", "") == "stripe", (
            f"{mod.__name__}.stripe did not resolve to the real stripe SDK: got {stripe_mod!r}"
        )


@pytest.mark.benchmark
def test_lazy_pykakasi_resolves_slug() -> None:
    """Lazy pykakasi init in ``utils.slug`` must still emit hepburn slugs."""
    from jpintel_mcp.utils.slug import program_static_slug

    slug = program_static_slug("税額控除", "unified-abc-123")
    # The slug suffix is sha1-6 of unified_id; we only assert shape +
    # the hepburn romaji prefix so the test is stable across pykakasi
    # tokenizer revisions.
    assert "-" in slug and len(slug.rsplit("-", 1)[-1]) == 6, f"slug shape unexpected: {slug!r}"
    assert "zeigaku" in slug or "koujo" in slug, (
        f"hepburn romaji missing from slug — pykakasi may not have "
        f"loaded lazily as expected: {slug!r}"
    )


@pytest.mark.benchmark
def test_mcp_tool_count_unchanged() -> None:
    """Lazy-loading must not drop any tool registrations.

    The wire-shape contract is that ``server.mcp._tool_manager._tools``
    carries every published tool. A regression where a lazy-load removed
    a top-level register-call would shrink this dict — guard it here.
    """
    from jpintel_mcp.mcp import server

    tool_count = len(server.mcp._tool_manager._tools)
    assert tool_count >= 180, (
        f"MCP tool count dropped to {tool_count} — lazy-load may have "
        "skipped a tool module. Default gates should expose ~184 tools."
    )


@pytest.mark.benchmark
def test_eligibility_constant_parity() -> None:
    """``eligibility_tools`` inlines two int constants; they must mirror api.

    PERF-6 resubmit moved the heavy ``from jpintel_mcp.api.eligibility_check
    import ...`` off the MCP cold-start path, but ``_MAX_HISTORY_YEARS`` and
    ``_DEFAULT_HISTORY_YEARS`` still appear in ``Annotated[..., Field(...)]``
    decorators that must resolve at @mcp.tool decoration time. We inlined
    the literal values; this test enforces the parity contract so a drift
    in ``api.eligibility_check`` is caught at CI time, not at runtime.
    """
    from jpintel_mcp.api import eligibility_check as api_mod
    from jpintel_mcp.mcp.autonomath_tools import eligibility_tools as mcp_mod

    assert mcp_mod._DEFAULT_HISTORY_YEARS == api_mod._DEFAULT_HISTORY_YEARS, (
        f"PERF-6 inlined constant drifted from api: "
        f"mcp={mcp_mod._DEFAULT_HISTORY_YEARS} vs "
        f"api={api_mod._DEFAULT_HISTORY_YEARS}. "
        "Update both or surface via a shared constants module."
    )
    assert mcp_mod._MAX_HISTORY_YEARS == api_mod._MAX_HISTORY_YEARS, (
        f"PERF-6 inlined constant drifted from api: "
        f"mcp={mcp_mod._MAX_HISTORY_YEARS} vs "
        f"api={api_mod._MAX_HISTORY_YEARS}. "
        "Update both or surface via a shared constants module."
    )


@pytest.mark.benchmark
def test_fastapi_not_loaded_at_mcp_cold_start() -> None:
    """``fastapi`` must not be pulled in at MCP server import time.

    The REST router lives behind ``autonomath-api``; the MCP server stdio
    transport never needs FastAPI routing. Importing ``fastapi`` adds
    ~80 ms (mostly ``fastapi.openapi.models``) at cold start. PERF-6
    resubmit ensures the import is deferred until a tool body actually
    calls into one of the REST modules.
    """
    cmd = [
        sys.executable,
        "-c",
        (
            "import sys\n"
            "from jpintel_mcp.mcp import server\n"
            "assert server.mcp._tool_manager._tools, 'tools missing'\n"
            "if 'fastapi' in sys.modules:\n"
            "    raise SystemExit('fastapi was loaded at MCP cold start')\n"
        ),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=os.environ.copy(),
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"FastAPI presence at MCP cold start (rc={proc.returncode}): "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}. "
        "Defer the ``from jpintel_mcp.api.*`` import inside the tool body "
        "via a @functools.cache _api() accessor — see "
        "src/jpintel_mcp/mcp/autonomath_tools/eligibility_tools.py."
    )
