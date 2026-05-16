#!/usr/bin/env python3
"""PERF-20: Consolidated perf benchmark runner.

Drives every ``tests/perf/test_*.py`` under the project-standard ``--runperf``
opt-in (and the ``JPCITE_RUN_PERF_GATES=1`` env var its siblings expect),
captures per-test latency in milliseconds, writes a JSON ledger to
``out/perf_bench_<timestamp>.json`` and emits a Markdown summary table on
stdout (and to ``--md-out`` if requested).

The runner is intentionally minimal: it shells out to pytest once per perf
test file with ``--durations=0 -q`` so we can read the call-phase timing
out of pytest's own duration accounting (the same column pytest prints
when you pass ``--durations``). For PERF-7 / PERF-11 the test bodies
themselves enforce a budget assertion, so a regression already trips a
pytest failure; this runner adds the **regression detection** layer on
top — compares each test's timing against a previous baseline (the
``--baseline`` argument) and flags any test that is more than the
``--regression-pct`` slower than the baseline value.

Used by ``.github/workflows/perf-bench.yml`` (manual + weekly Monday
09:00 JST). Do NOT wire this into per-PR CI — running the full suite
takes minutes on the GHA runner and we explicitly opted *not* to gate
every PR on it (cost + flakiness budget).

Schema of the JSON ledger (stable across runs — downstream tooling reads
this in the workflow comment step):

.. code-block:: json

    {
        "schema": "jpcite.perf_bench.v1",
        "captured_at": "2026-05-16T23:30:00+00:00",
        "git_commit": "abcd1234",
        "git_branch": "main",
        "python_version": "3.13.0",
        "platform": "darwin-arm64",
        "tests": [
            {
                "test_id": "tests/perf/test_api_p95_budget.py::test_endpoint_p95_under_budget[/healthz]",
                "duration_s": 1.23,
                "status": "passed",
                "p50_ms": null,
                "p95_ms": null,
                "p99_ms": null
            }
        ],
        "summary": {
            "total": 5,
            "passed": 5,
            "failed": 0,
            "wall_clock_s": 12.4
        }
    }

p50/p95/p99 are best-effort — they are filled when the underlying test
emits them via a structured-log line ``[perfbench] p50_ms=... p95_ms=...``
on stdout (PERF-7 already does this via the assertion error message;
PERF-11 emits the total elapsed). For tests that do not emit the
percentile triple, only ``duration_s`` is reliable. Regression detection
therefore runs against ``duration_s`` as the canonical metric.

``[lane:solo]`` per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import argparse
import json
import os
import platform as platform_mod
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
PERF_DIR = REPO_ROOT / "tests" / "perf"
OUT_DIR = REPO_ROOT / "out"

LEDGER_SCHEMA = "jpcite.perf_bench.v1"

# Default regression threshold: anything more than +20% slower than the
# baseline is a real regression. Below that lives in CI runner noise +
# warmup variance.
DEFAULT_REGRESSION_PCT = 20.0


def _discover_perf_tests() -> list[Path]:
    """Return every ``tests/perf/test_*.py`` file (excludes ``__init__``)."""
    if not PERF_DIR.is_dir():
        return []
    return sorted(p for p in PERF_DIR.glob("test_*.py") if p.is_file())


def _git_meta() -> dict[str, str]:
    """Return git commit + branch metadata for the ledger header.

    Best-effort — falls back to empty strings when git is unavailable or
    the working tree is detached. The downstream comment step tolerates
    blank values.
    """

    def _run(cmd: list[str]) -> str:
        try:
            out = subprocess.check_output(cmd, cwd=REPO_ROOT, stderr=subprocess.DEVNULL, text=True)
            return out.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""

    return {
        "git_commit": _run(["git", "rev-parse", "--short", "HEAD"]),
        "git_branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
    }


_DURATIONS_RE = re.compile(
    r"^\s*([0-9]+\.[0-9]+)s\s+call\s+([^\s].*?)\s*$",
    re.MULTILINE,
)

# Optional structured emission from test bodies. PERF-7 already prints
# this on assert-fail; PERF-11 prints the wall clock. We tolerate
# missing values.
_STRUCTURED_RE = re.compile(
    r"\[perfbench\]\s+(?P<kv>(?:\w+=\S+\s*)+)",
)


def _parse_pytest_output(stdout: str) -> list[dict[str, Any]]:
    """Parse pytest ``--durations=0`` output into a list of test entries.

    Each entry has ``test_id``, ``duration_s``, plus any p50/p95/p99
    values gleaned from the optional ``[perfbench] k=v`` structured
    emission lines.
    """
    durations: dict[str, float] = {}
    for match in _DURATIONS_RE.finditer(stdout):
        secs = float(match.group(1))
        test_id = match.group(2).strip()
        # pytest may emit duration lines for setup / teardown too — the
        # regex pins to ``call`` so we only get the test body window.
        durations[test_id] = secs

    perc_by_test: dict[str, dict[str, float]] = {}
    for line in stdout.splitlines():
        sm = _STRUCTURED_RE.search(line)
        if not sm:
            continue
        kv = dict(item.split("=", 1) for item in sm.group("kv").split())
        test_id = kv.pop("test_id", "")
        if not test_id:
            continue
        bucket = perc_by_test.setdefault(test_id, {})
        for k in ("p50_ms", "p95_ms", "p99_ms"):
            if k in kv:
                try:
                    bucket[k] = float(kv[k])
                except ValueError:
                    continue

    entries: list[dict[str, Any]] = []
    for test_id, dur in durations.items():
        entry: dict[str, Any] = {
            "test_id": test_id,
            "duration_s": dur,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
        }
        if test_id in perc_by_test:
            entry.update(perc_by_test[test_id])
        entries.append(entry)
    return entries


def _run_pytest(
    files: Iterable[Path],
    *,
    extra_args: list[str] | None = None,
) -> tuple[int, str, str]:
    """Invoke pytest on ``files`` with the perf gate opt-in env + flag.

    Returns ``(returncode, stdout, stderr)``. We collect ``--durations=0``
    so every test's call-phase timing lands in stdout. ``-q`` keeps the
    rest of the output compact so the parser doesn't have to handle the
    verbose summary block.
    """
    env = os.environ.copy()
    env["JPCITE_RUN_PERF_GATES"] = "1"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *(str(f) for f in files),
        "--runperf",
        "--durations=0",
        "-q",
        "--tb=short",
        "--color=no",
    ]
    if extra_args:
        cmd.extend(extra_args)
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _classify_status(stdout: str, returncode: int) -> dict[str, int]:
    """Best-effort pass / fail counts from the pytest summary tail."""
    passed = failed = 0
    for line in stdout.splitlines()[::-1]:
        # pytest summary line looks like "5 passed in 12.3s" or
        # "3 passed, 1 failed in 15.2s". We pick the first match
        # walking from the end.
        if "passed" in line or "failed" in line:
            mp = re.search(r"(\d+)\s+passed", line)
            mf = re.search(r"(\d+)\s+failed", line)
            if mp:
                passed = int(mp.group(1))
            if mf:
                failed = int(mf.group(1))
            if mp or mf:
                break
    if not passed and not failed and returncode != 0:
        failed = 1
    return {"passed": passed, "failed": failed, "total": passed + failed}


def _load_baseline(path: Path | None) -> dict[str, float]:
    """Load a baseline ledger and return ``test_id -> duration_s``."""
    if not path:
        return {}
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, float] = {}
    for t in payload.get("tests", []):
        tid = t.get("test_id")
        dur = t.get("duration_s")
        if isinstance(tid, str) and isinstance(dur, (int, float)):
            out[tid] = float(dur)
    return out


def _format_markdown(
    *,
    tests: list[dict[str, Any]],
    baseline: dict[str, float],
    regression_pct: float,
    summary: dict[str, Any],
    captured_at: str,
    git_commit: str,
) -> str:
    """Render a Markdown summary suitable for a PR comment.

    Includes a per-test row with current duration, baseline duration,
    delta percentage, and a regression flag column. Trailing footer
    documents the regression threshold so the comment is self-contained.
    """
    lines: list[str] = []
    lines.append("## PERF-20 continuous benchmark")
    lines.append("")
    lines.append(
        f"Captured at `{captured_at}` from commit `{git_commit or 'unknown'}`. "
        f"Total **{summary['total']}** tests "
        f"(**{summary['passed']} passed**, **{summary['failed']} failed**), "
        f"wall clock **{summary['wall_clock_s']:.2f}s**."
    )
    lines.append("")
    lines.append(
        "| test | duration (s) | baseline (s) | delta % | p50 ms | p95 ms | p99 ms | regression |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |")
    any_regression = False
    for t in tests:
        tid = t["test_id"]
        dur = float(t["duration_s"])
        base = baseline.get(tid)
        if base is None or base <= 0:
            delta_str = "—"
            regression = False
        else:
            delta = (dur - base) / base * 100.0
            delta_str = f"{delta:+.1f}%"
            regression = delta > regression_pct
            any_regression = any_regression or regression
        base_str = f"{base:.3f}" if base is not None else "—"
        p50 = t.get("p50_ms")
        p95 = t.get("p95_ms")
        p99 = t.get("p99_ms")
        flag = "🔴" if regression else "✅"
        lines.append(
            f"| `{tid}` | {dur:.3f} | {base_str} | {delta_str} | "
            f"{p50 if p50 is not None else '—'} | "
            f"{p95 if p95 is not None else '—'} | "
            f"{p99 if p99 is not None else '—'} | {flag} |"
        )
    lines.append("")
    lines.append(
        f"Regression threshold: **+{regression_pct:.0f}%** slowdown vs baseline. "
        + ("🔴 **Regression detected** — investigate before merge." if any_regression else "")
    )
    lines.append("")
    lines.append(
        "Runner: `scripts/perf/run_all_benchmarks.py` (PERF-20). "
        "Workflow: `.github/workflows/perf-bench.yml`. "
        "Runbook: `docs/_internal/perf_bench_runbook_2026_05_16.md`."
    )
    return "\n".join(lines) + "\n"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run every tests/perf/test_*.py with --runperf, write a JSON ledger "
            "to out/perf_bench_<ts>.json, and emit a Markdown summary table."
        ),
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help=(
            "Optional baseline ledger JSON (a previous run's "
            "out/perf_bench_*.json). When provided, regression detection "
            "compares each test's duration against the baseline value."
        ),
    )
    parser.add_argument(
        "--regression-pct",
        type=float,
        default=DEFAULT_REGRESSION_PCT,
        help=(
            "Regression threshold: any test more than this percent slower "
            "than its baseline duration is flagged. Default: %(default).1f"
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUT_DIR,
        help="Directory for the JSON ledger (default: %(default)s)",
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=None,
        help=(
            "Optional path for the Markdown summary. When omitted, the "
            "summary is written to stdout only."
        ),
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help=(
            "Exit non-zero when any test exceeds the regression threshold. "
            "Used by the GHA workflow's regression gate step."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    perf_files = _discover_perf_tests()
    if not perf_files:
        sys.stderr.write("no tests/perf/test_*.py found — nothing to bench\n")
        return 0

    wall_t0 = time.perf_counter()
    rc, stdout, stderr = _run_pytest(perf_files)
    wall_elapsed = time.perf_counter() - wall_t0
    sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)

    tests = _parse_pytest_output(stdout)
    classify = _classify_status(stdout, rc)
    summary: dict[str, Any] = {
        "total": classify["total"] or len(tests),
        "passed": classify["passed"],
        "failed": classify["failed"],
        "wall_clock_s": wall_elapsed,
        "pytest_returncode": rc,
    }

    captured_at = datetime.now(UTC).isoformat()
    git_meta = _git_meta()
    ledger: dict[str, Any] = {
        "schema": LEDGER_SCHEMA,
        "captured_at": captured_at,
        "python_version": platform_mod.python_version(),
        "platform": f"{platform_mod.system().lower()}-{platform_mod.machine().lower()}",
        "tests": tests,
        "summary": summary,
        **git_meta,
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    ledger_path = args.out_dir / f"perf_bench_{ts}.json"
    ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    sys.stderr.write(f"ledger: {ledger_path}\n")

    baseline = _load_baseline(args.baseline)
    md = _format_markdown(
        tests=tests,
        baseline=baseline,
        regression_pct=args.regression_pct,
        summary=summary,
        captured_at=captured_at,
        git_commit=git_meta.get("git_commit", ""),
    )
    sys.stdout.write("\n" + md)
    if args.md_out:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        args.md_out.write_text(md, encoding="utf-8")
        sys.stderr.write(f"markdown: {args.md_out}\n")

    if args.fail_on_regression and baseline:
        for t in tests:
            base = baseline.get(t["test_id"])
            if base is None or base <= 0:
                continue
            delta = (float(t["duration_s"]) - base) / base * 100.0
            if delta > args.regression_pct:
                sys.stderr.write(
                    f"regression: {t['test_id']} {delta:+.1f}% "
                    f"(threshold +{args.regression_pct:.1f}%)\n"
                )
                return 2

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
