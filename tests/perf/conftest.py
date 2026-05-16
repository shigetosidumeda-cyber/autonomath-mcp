"""PERF-20: pytest conftest for the ``tests/perf/`` suite.

Two responsibilities:

1. Register the ``--runperf`` CLI flag so pytest's argparse accepts it.
   Previously ``tests/perf/test_packet_gen_perf.py`` walked ``sys.argv``
   directly to decide whether to opt in, but pytest still refused to
   start when the flag was passed because no plugin had registered it.
   Now both ``--runperf`` and the existing ``JPCITE_RUN_PERF_GATES=1``
   env var route work and PERF-7 + PERF-11 + PERF-20 share one opt-in.

2. Expose a ``perf_opt_in`` boolean via ``pytest.Config.getoption`` so
   future perf tests can ``pytest.mark.skipif(not config.getoption(
   "--runperf") and os.environ.get("JPCITE_RUN_PERF_GATES") != "1")``
   without re-doing the sys.argv walk in every file.

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ``--runperf`` so pytest accepts it as a known flag."""
    parser.addoption(
        "--runperf",
        action="store_true",
        default=False,
        help=(
            "Opt in to the perf benchmark suite under tests/perf/. "
            "Equivalent to JPCITE_RUN_PERF_GATES=1 env. Disabled on CI "
            "by default because the suite drives 100+ sequential calls "
            "per test and is too noisy for per-PR gating."
        ),
    )
