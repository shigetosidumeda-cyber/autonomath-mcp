"""Schema validity test for ``.github/workflows/*cron*.yml`` (and friends).

Validates that every workflow file whose filename contains ``cron`` parses
as YAML, declares at least one valid 5-field cron expression on the
``on.schedule`` trigger, has at least one ``jobs.<id>`` defined, and that
every step in every job satisfies the GitHub Actions step contract
(exactly one of ``uses`` or ``run``). Also flags any ``working-directory``
key whose value is an absolute path (portability foot-gun on hosted
runners).

``name`` on steps is treated as informational rather than hard-required:
GitHub Actions itself does not require step names, and bare ``- uses: ...``
or ``- run: ...`` shorthand is widely used throughout this repo. The
unnamed-step count is surfaced via the
``test_cron_workflow_named_step_coverage`` health probe so regressions
can still be tracked without breaking the cron-validity gate.

All defects are accumulated and reported with ``file: detail`` so a single
test run surfaces every problem instead of bailing on the first one.

This test is intentionally narrow: it does NOT exercise the actions
themselves, contact GitHub, or attempt to validate ``${{ }}`` expression
strings. It is a syntactic / structural gate equivalent to the YAML
linter step that runs in CI, scoped to the cron-bearing surface.

Cron grammar
------------
GitHub Actions accepts the POSIX 5-field cron syntax (no seconds, no @keywords).
Each of the 5 fields supports::

    *                        any value
    a                        literal a
    a-b                      range
    a-b/n                    range with step
    */n                      every n
    a,b,c                    list of any of the above

Per-field bounds: minute 0-59, hour 0-23, day_of_month 1-31, month 1-12,
day_of_week 0-7 (0 and 7 both mean Sunday). ``?`` is accepted as the
day-of-month / day-of-week placeholder (Quartz extension that GitHub
documents as supported).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


# ---------------------------------------------------------------------------
# Cron expression validator
# ---------------------------------------------------------------------------

_FIELD_BOUNDS: tuple[tuple[str, int, int], ...] = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day_of_month", 1, 31),
    ("month", 1, 12),
    ("day_of_week", 0, 7),
)

# numeric atom:        a            a-b            a-b/n      */n      *
_ATOM_RE = re.compile(
    r"""^(?:
        \*(?:/(?P<step_star>\d+))?           # *  or  */n
        |
        (?P<start>\d+)
            (?:-(?P<end>\d+))?
            (?:/(?P<step>\d+))?              # a, a-b, a-b/n, a/n
    )$""",
    re.VERBOSE,
)


def _validate_field(raw: str, lo: int, hi: int) -> str | None:
    """Return ``None`` if ``raw`` is a valid cron field; else an error string."""
    if raw == "?":
        return None
    if raw == "":
        return "empty field"
    for part in raw.split(","):
        match = _ATOM_RE.match(part)
        if match is None:
            return f"unparseable atom {part!r}"
        step_star = match.group("step_star")
        start = match.group("start")
        end = match.group("end")
        step = match.group("step")
        if start is None:
            # leading '*'
            if step_star is not None and int(step_star) <= 0:
                return f"non-positive step in {part!r}"
            continue
        start_i = int(start)
        if start_i < lo or start_i > hi:
            return f"out-of-range start {start_i} (allowed {lo}-{hi}) in {part!r}"
        if end is not None:
            end_i = int(end)
            if end_i < start_i:
                return f"reversed range {start_i}-{end_i} in {part!r}"
            if end_i > hi:
                return f"out-of-range end {end_i} (allowed {lo}-{hi}) in {part!r}"
        if step is not None and int(step) <= 0:
            return f"non-positive step in {part!r}"
    return None


def _validate_cron_expression(expr: str) -> str | None:
    """Return ``None`` if ``expr`` is a valid 5-field cron; else error reason."""
    if not isinstance(expr, str):
        return f"cron expression must be a string, got {type(expr).__name__}"
    fields = expr.split()
    if len(fields) != 5:
        return f"expected 5 cron fields, got {len(fields)} ({expr!r})"
    for value, (name, lo, hi) in zip(fields, _FIELD_BOUNDS, strict=True):
        err = _validate_field(value, lo, hi)
        if err is not None:
            return f"invalid {name} field {value!r}: {err}"
    return None


# ---------------------------------------------------------------------------
# Workflow discovery
# ---------------------------------------------------------------------------


def _discover_cron_workflows() -> list[Path]:
    """Return every workflow file in ``.github/workflows/`` whose filename
    contains ``cron`` OR whose YAML body declares ``on.schedule``.

    PyYAML's ``safe_load`` interprets the bare YAML token ``on`` as the
    boolean ``True`` (YAML 1.1 legacy), so the schedule trigger lands
    under the ``True`` key rather than the ``"on"`` key. We probe both.
    """
    if not WORKFLOWS_DIR.is_dir():
        return []
    candidates: list[Path] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        name_match = "cron" in path.name
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            # Unparseable YAML is itself a defect we want to surface — keep
            # it in the candidate list so the assertion in the test reports
            # the parse failure with the file name.
            candidates.append(path)
            continue
        if not isinstance(data, dict):
            if name_match:
                candidates.append(path)
            continue
        on_section = data.get("on", data.get(True))
        has_schedule = isinstance(on_section, dict) and "schedule" in on_section
        if name_match or has_schedule:
            candidates.append(path)
    return candidates


CRON_WORKFLOWS = _discover_cron_workflows()


# ---------------------------------------------------------------------------
# Per-file validator
# ---------------------------------------------------------------------------


def _on_section(parsed: dict[Any, Any]) -> Any:
    if "on" in parsed:
        return parsed["on"]
    return parsed.get(True)


def _validate_workflow(path: Path) -> list[str]:
    """Return a list of human-readable defect strings for ``path``."""
    defects: list[str] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path.name}: read error: {exc}"]

    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return [f"{path.name}: YAML parse error: {exc}"]

    if not isinstance(parsed, dict):
        return [f"{path.name}: top-level YAML must be a mapping, got {type(parsed).__name__}"]

    # 1) on.schedule[].cron
    on_section = _on_section(parsed)
    if not isinstance(on_section, dict):
        defects.append(f"{path.name}: missing top-level 'on:' mapping")
    else:
        schedule = on_section.get("schedule")
        if schedule is None:
            defects.append(f"{path.name}: missing 'on.schedule' trigger")
        elif not isinstance(schedule, list) or not schedule:
            defects.append(f"{path.name}: 'on.schedule' must be a non-empty list")
        else:
            for idx, entry in enumerate(schedule):
                if not isinstance(entry, dict) or "cron" not in entry:
                    defects.append(f"{path.name}: on.schedule[{idx}] missing 'cron' key")
                    continue
                expr = entry["cron"]
                err = _validate_cron_expression(expr)
                if err is not None:
                    defects.append(f"{path.name}: on.schedule[{idx}].cron invalid: {err}")

    # 2) jobs.<id>
    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        defects.append(f"{path.name}: missing or empty 'jobs:' mapping")
        return defects

    # 3) step structure per job
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            defects.append(f"{path.name}: jobs.{job_id} is not a mapping")
            continue
        steps = job.get("steps")
        if steps is None:
            # Reusable workflow / matrix-only jobs with no steps are rare
            # in this repo; flag them so the operator gets a clear signal.
            if "uses" not in job:
                defects.append(f"{path.name}: jobs.{job_id} has neither 'steps' nor 'uses'")
            continue
        if not isinstance(steps, list) or not steps:
            defects.append(f"{path.name}: jobs.{job_id}.steps must be a non-empty list")
            continue
        for step_idx, step in enumerate(steps):
            label = f"{path.name}: jobs.{job_id}.steps[{step_idx}]"
            if not isinstance(step, dict):
                defects.append(f"{label} is not a mapping")
                continue
            has_uses = "uses" in step
            has_run = "run" in step
            if has_uses == has_run:
                # Both, or neither — both are GitHub Actions schema errors.
                if has_uses and has_run:
                    defects.append(f"{label} has BOTH 'uses' and 'run' (must be exactly one)")
                else:
                    defects.append(f"{label} has NEITHER 'uses' nor 'run' (must be exactly one)")
            # working-directory must not be an absolute path.
            wd = step.get("working-directory")
            if isinstance(wd, str) and wd.startswith("/"):
                defects.append(
                    f"{label} 'working-directory' is absolute: {wd!r} "
                    f"(use a path relative to $GITHUB_WORKSPACE)"
                )

    return defects


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_cron_workflow_discovery_nonempty() -> None:
    """At least one cron-bearing workflow must be discovered.

    Acts as a tripwire: if discovery silently breaks (e.g. someone moves
    the workflows directory), the parameterised validator would emit zero
    cases and the suite would pass vacuously.
    """
    assert WORKFLOWS_DIR.is_dir(), f"workflows dir missing: {WORKFLOWS_DIR}"
    assert CRON_WORKFLOWS, f"no cron-bearing workflows discovered under {WORKFLOWS_DIR}"


@pytest.mark.parametrize(
    "workflow_path",
    CRON_WORKFLOWS,
    ids=[p.name for p in CRON_WORKFLOWS],
)
def test_cron_workflow_schema_valid(workflow_path: Path) -> None:
    """Each cron-bearing workflow file validates clean.

    Parameterised so each defective workflow shows up as its own pytest
    failure with the file name in the ID — cheap operator triage.
    """
    defects = _validate_workflow(workflow_path)
    assert not defects, "cron workflow schema defects:\n  " + "\n  ".join(defects)


def test_cron_validator_self_check_accepts_known_good() -> None:
    """Sanity-pin the cron validator against the canonical samples used in
    this repo so a regression in ``_validate_cron_expression`` is caught
    without depending on the live workflow corpus."""
    good = [
        "10 18 1 * *",  # nta-bulk-monthly
        "10 21 * * *",  # saved-searches-cron
        "30 18 * * *",  # index-now-cron / revalidate-webhook-targets-cron
        "0 9 * * *",  # competitive-watch
        "45 19 * * 0",  # weekly-backup-autonomath
        "0 3 * * *",  # tls-check
        "30 0 * * 1",  # self-improve-weekly
        "*/15 * * * *",  # generic stride
        "0,30 * * * *",  # list
        "0-23/2 * * * *",  # range with step
    ]
    for expr in good:
        err = _validate_cron_expression(expr)
        assert err is None, f"validator rejected known-good {expr!r}: {err}"


def test_cron_workflow_named_step_coverage() -> None:
    """Informational health probe.

    Tracks how many steps in cron-bearing workflows carry an explicit
    ``name``. This is **not** a hard gate (GitHub Actions allows unnamed
    steps), but the ratio is a useful operator signal — a sudden drop
    typically means a copy-paste regression dropped step labels.

    Failure threshold is intentionally generous (>= 50 %) so the test
    passes today and only trips on a major regression.
    """
    total_steps = 0
    named_steps = 0
    for path in CRON_WORKFLOWS:
        try:
            parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(parsed, dict):
            continue
        jobs = parsed.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job in jobs.values():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps")
            if not isinstance(steps, list):
                continue
            for step in steps:
                if not isinstance(step, dict):
                    continue
                total_steps += 1
                if "name" in step:
                    named_steps += 1

    assert total_steps > 0, "no steps discovered to count"
    ratio = named_steps / total_steps
    assert ratio >= 0.5, (
        f"named-step coverage regressed: {named_steps}/{total_steps} "
        f"({ratio:.1%}) — expected >= 50%"
    )


def test_cron_validator_self_check_rejects_known_bad() -> None:
    """Sanity-pin the rejection path."""
    bad = [
        ("", "empty"),
        ("0 0 0 0", "4 fields"),
        ("0 0 0 0 0 0", "6 fields"),
        ("60 0 * * *", "minute out of range"),
        ("0 24 * * *", "hour out of range"),
        ("0 0 0 * *", "day_of_month=0"),
        ("0 0 * 13 *", "month=13"),
        ("0 0 * * 8", "day_of_week=8"),
        ("a b c d e", "non-numeric"),
        ("*/0 * * * *", "non-positive step"),
        ("5-3 * * * *", "reversed range"),
    ]
    for expr, reason in bad:
        err = _validate_cron_expression(expr)
        assert err is not None, f"validator wrongly accepted {expr!r} (expected reject: {reason})"
