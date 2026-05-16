"""PERF-11 packet generator throughput regression gate.

Locks in the post-orjson + os.write + SQLite-streaming measurements
documented in the PERF-11 commit message so a real regression trips
the test but normal CI runner noise does not.

Skipped on CI by default; opt in with one of::

    JPCITE_RUN_PERF_GATES=1 pytest tests/perf/test_packet_gen_perf.py
    pytest tests/perf/test_packet_gen_perf.py --runperf

The test exercises ``scripts/aws_credit_ops/_packet_base.upload_packet``
+ ``write_packet`` from the acceptance probability generator on a 5,000
synthetic packet workload. We deliberately bypass the SQLite aggregate
step — that path is profiled separately and dominated by the 192K-row
walk in ``aggregate_cohorts`` which is independent of the serializer +
writer levers PERF-11 targets.

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import datetime as dt
import importlib
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "scripts" / "aws_credit_ops"

# Use the canonical package import path so mypy only sees one module
# name for ``_packet_base``. We still need ``SCRIPT_DIR`` on ``sys.path``
# so the acceptance-probability script (which is not a package member,
# just a runnable file under ``scripts/``) can be imported by file
# basename.
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

_packet_base = importlib.import_module("scripts.aws_credit_ops._packet_base")
gen_aprob = importlib.import_module("generate_acceptance_probability_packets")

# PERF-11 baseline numbers (median of 5 warm runs, M-series macOS, 2026-05-16):
#
#   * 5,000 synthetic packets via upload_packet (dry-run, local out):
#       baseline (pre-PERF-11): ~1.65 s
#       optimized (orjson + os.write + hoisted mkdir): ~1.05 s
#
# We pin a regression budget of 1.4 s — 1.3x above the optimized
# median, leaving room for CI noise + slower runners while still
# tripping on a >35% regression. If this test starts flaking on
# infra, bump the budget and document the new floor in the perf SOT.
N_PACKETS = 5_000
BUDGET_S = 1.4
WARMUP_PACKETS = 200


def pytest_collection_modifyitems(  # pragma: no cover - pytest plugin glue
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    pass


def _runperf_opt_in() -> bool:
    if os.environ.get("JPCITE_RUN_PERF_GATES") == "1":
        return True
    # ``--runperf`` is not a pytest builtin; check sys.argv directly so
    # we don't have to register a conftest hook. The test still runs
    # under the env var even if the flag is absent.
    return "--runperf" in sys.argv


pytestmark = pytest.mark.skipif(
    not _runperf_opt_in(),
    reason=(
        "perf gate disabled on CI by default; set "
        "JPCITE_RUN_PERF_GATES=1 or pass --runperf to opt in"
    ),
)


def _make_cohort(i: int) -> Any:
    return gen_aprob.CohortRow(
        prefecture="TOKYO",
        jsic_major="D",
        scale_band="mid",
        program_kind="subsidy",
        fiscal_year="2025",
        n_sample=10 + (i % 5),
        n_eligible_programs=3,
        freshest_announced_at="2026-02-10",
    )


def _render_envelope(cohort: Any, generated_at: Any) -> dict[str, Any]:
    packet = gen_aprob.render_packet(cohort, generated_at=generated_at)
    # The acceptance generator returns a dict[str, object]; cast to the
    # Any-typed dict the shared upload_packet expects.
    return dict(packet)


@pytest.fixture()
def tmp_out_dir(tmp_path: Path) -> Iterator[Path]:
    d = tmp_path / "perf11_packets"
    d.mkdir(parents=True, exist_ok=True)
    yield d


def test_upload_packet_throughput_budget(tmp_out_dir: Path) -> None:
    """PERF-11: 5,000-packet local-write hot path stays under budget."""

    generated_at = dt.datetime(2026, 5, 16, 12, 0, 0, tzinfo=dt.UTC)
    # Warmup so module-level imports (orjson) + page cache don't skew
    # the measured window.
    for i in range(WARMUP_PACKETS):
        cohort = _make_cohort(i)
        # render_packet adds a unique cohort_id segment via the dataclass
        # property, so we mutate prefecture+jsic to dodge filename collisions.
        envelope = _render_envelope(
            gen_aprob.CohortRow(
                prefecture=f"W{i:04d}",
                jsic_major="D",
                scale_band="mid",
                program_kind="subsidy",
                fiscal_year="2025",
                n_sample=cohort.n_sample,
                n_eligible_programs=cohort.n_eligible_programs,
                freshest_announced_at=cohort.freshest_announced_at,
            ),
            generated_at=generated_at,
        )
        _packet_base.upload_packet(
            envelope=envelope,
            output_prefix="s3://perf11-warmup/path",
            dry_run=True,
            s3_client=None,
            local_out_dir=tmp_out_dir,
            packet_id=f"warmup_{i:06d}",
        )

    t0 = time.perf_counter()
    for i in range(N_PACKETS):
        envelope = _render_envelope(
            gen_aprob.CohortRow(
                prefecture=f"M{i:05d}",
                jsic_major="D",
                scale_band="mid",
                program_kind="subsidy",
                fiscal_year="2025",
                n_sample=10 + (i % 5),
                n_eligible_programs=3,
                freshest_announced_at="2026-02-10",
            ),
            generated_at=generated_at,
        )
        _packet_base.upload_packet(
            envelope=envelope,
            output_prefix="s3://perf11-bench/path",
            dry_run=True,
            s3_client=None,
            local_out_dir=tmp_out_dir,
            packet_id=f"measure_{i:06d}",
        )
    elapsed = time.perf_counter() - t0

    assert elapsed < BUDGET_S, (
        f"PERF-11 regression: upload_packet for {N_PACKETS} packets took "
        f"{elapsed:.3f}s (> {BUDGET_S:.3f}s budget). "
        "Either an optimization was removed (orjson, os.write, hoisted "
        "mkdir) or a new sync op was added to the hot path."
    )


def test_orjson_path_active() -> None:
    """orjson is the post-PERF-11 default; the stdlib fallback is only
    exercised on operator boxes that intentionally skip orjson."""

    # The fast-path is wired so ``_HAS_ORJSON`` is True when orjson is
    # available in the environment. The CI image installs it via the
    # project ``[dev]`` extra; if this flag flips False on CI, we've
    # regressed the install matrix and the perf budget will follow.
    assert _packet_base._HAS_ORJSON is True, (
        "orjson not available — PERF-11 fast path is degraded to the "
        "stdlib fallback. Install orjson via the [dev] extra."
    )


def test_dumps_compact_round_trip() -> None:
    """The optimized serializer must remain byte-content-equivalent to
    stdlib compact JSON so Athena / Glue downstream stays valid."""

    import json

    sample: dict[str, Any] = {
        "header": {
            "object_type": "packet",
            "object_id": "test.cohort.1",
            "producer": "jpcite-ai-execution-control-plane",
            "request_time_llm_call_performed": False,
            "schema_version": "jpcir.p0.v1",
            "created_at": "2026-05-16T12:00:00+00:00",
        },
        "cohort_definition": {"cohort_id": "TOKYO.D.mid.subsidy.2025"},
        "n_sample": 12,
        "probability_estimate": 0.5,
        "disclaimer": "日本語 disclaimer string with kanji 採択",
    }
    fast = _packet_base._dumps_compact(sample)
    parsed_fast = json.loads(fast.decode("utf-8"))
    parsed_stdlib = json.loads(json.dumps(sample, ensure_ascii=False, separators=(",", ":")))
    assert parsed_fast == parsed_stdlib, (
        "_dumps_compact diverged from stdlib JSON parse equivalence — "
        "Athena / Glue downstream may break."
    )
