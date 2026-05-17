"""Wave 47.E workflow alias parity test.

Wave 46 tick7#7 (2026-05-12) introduces 10 `jpcite-*` alias workflows that
re-invoke their legacy autonomath-era parents via `gh workflow run` from a
dispatch-only trampoline job (see
[[project_jpcite_internal_autonomath_rename]],
[[feedback_destruction_free_organization]]).

This test sweeps each alias and asserts a tight set of structural invariants
against its parent so we cannot accidentally:

1. Add `schedule:` to an alias and double-trigger the cron (the parent is the
   SOT for cron — aliases must be dispatch-only).
2. Skip the trampoline body and reintroduce duplicated business logic on the
   alias side.
3. Drift the `name:` field or break the `(alias of <parent>)` discoverability
   marker.

Aliases live under `.github/workflows/jpcite-*.yml`; the parent path is the
filename derived from the alias name by stripping the `jpcite-` prefix.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


# (alias_filename, parent_filename)
ALIAS_PAIRS: list[tuple[str, str]] = [
    ("jpcite-weekly-backup.yml", "weekly-backup-autonomath.yml"),
    ("jpcite-nightly-backup.yml", "nightly-backup.yml"),
    ("jpcite-parquet-export-monthly.yml", "parquet-export-monthly.yml"),
    ("jpcite-extended-corpus-weekly.yml", "extended-corpus-weekly.yml"),
    ("jpcite-news-pipeline-cron.yml", "news-pipeline-cron.yml"),
    (
        "jpcite-nta-corpus-incremental-cron.yml",
        "nta-corpus-incremental-cron.yml",
    ),
    ("jpcite-brand-signals-weekly.yml", "brand-signals-weekly.yml"),
    ("jpcite-saved-searches-cron.yml", "saved-searches-cron.yml"),
    ("jpcite-precompute-refresh-cron.yml", "precompute-refresh-cron.yml"),
    ("jpcite-populate-calendar-monthly.yml", "populate-calendar-monthly.yml"),
]


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), f"{path}: not a mapping"
    return data


@pytest.mark.parametrize(("alias_name", "parent_name"), ALIAS_PAIRS)
def test_alias_files_exist(alias_name: str, parent_name: str) -> None:
    """Both alias and parent must be on disk."""
    assert (WORKFLOWS_DIR / alias_name).is_file(), f"missing alias: {alias_name}"
    assert (WORKFLOWS_DIR / parent_name).is_file(), (
        f"missing parent: {parent_name}"
    )


@pytest.mark.parametrize(("alias_name", "parent_name"), ALIAS_PAIRS)
def test_alias_dispatch_only_no_cron(
    alias_name: str, parent_name: str
) -> None:
    """Alias must declare workflow_dispatch only (no cron, no push, no workflow_run).

    PyYAML parses the ``on`` key as boolean True due to YAML 1.1 keyword
    coercion, so we look up both ``"on"`` and ``True`` keys.
    """
    data = _load(WORKFLOWS_DIR / alias_name)
    on_block = data.get("on", data.get(True))
    assert on_block is not None, f"{alias_name}: missing on: block"
    assert isinstance(on_block, dict), (
        f"{alias_name}: on: must be a mapping (got {type(on_block).__name__})"
    )
    assert "workflow_dispatch" in on_block, (
        f"{alias_name}: must define workflow_dispatch"
    )
    # Hard ban on triggers that would double-fire the parent's cron schedule
    # or otherwise widen the alias surface area.
    for forbidden in ("schedule", "push", "workflow_run", "pull_request"):
        assert forbidden not in on_block, (
            f"{alias_name}: forbidden trigger '{forbidden}' would create"
            f" duplicate/unintended runs against parent {parent_name}"
        )


@pytest.mark.parametrize(("alias_name", "parent_name"), ALIAS_PAIRS)
def test_alias_name_marks_parent(alias_name: str, parent_name: str) -> None:
    """Alias `name:` field must contain '(alias of <parent_stem>)' for UI discovery."""
    data = _load(WORKFLOWS_DIR / alias_name)
    name = data.get("name", "")
    assert isinstance(name, str) and name, f"{alias_name}: empty name field"
    parent_stem = parent_name.removesuffix(".yml")
    assert f"alias of {parent_stem}" in name, (
        f"{alias_name}: name '{name}' must mention 'alias of {parent_stem}'"
    )


@pytest.mark.parametrize(("alias_name", "parent_name"), ALIAS_PAIRS)
def test_alias_trampolines_to_parent(
    alias_name: str, parent_name: str
) -> None:
    """Alias body must call `gh workflow run <parent>.yml` to re-invoke parent."""
    text = (WORKFLOWS_DIR / alias_name).read_text(encoding="utf-8")
    needle = f"gh workflow run {parent_name}"
    assert needle in text, (
        f"{alias_name}: trampoline body must call '{needle}' to invoke parent"
    )


@pytest.mark.parametrize(("alias_name", "parent_name"), ALIAS_PAIRS)
def test_parent_cron_untouched(alias_name: str, parent_name: str) -> None:
    """Parent workflow must still carry a `cron:` schedule entry.

    This guards against accidental cron migration: the alias must NEVER take
    over the cron — only the parent keeps the schedule. If a future commit
    moves the cron to the alias, both sides would fire and double-trigger.
    """
    text = (WORKFLOWS_DIR / parent_name).read_text(encoding="utf-8")
    assert "- cron:" in text or "cron:" in text, (
        f"{parent_name}: parent must retain its cron schedule"
        f" (alias {alias_name} is dispatch-only by design)"
    )


def test_no_duplicate_cron_across_alias_and_parent() -> None:
    """Cross-cut: for every (alias, parent) pair, alias must lack `cron:` entirely."""
    for alias_name, parent_name in ALIAS_PAIRS:
        alias_text = (WORKFLOWS_DIR / alias_name).read_text(encoding="utf-8")
        assert "- cron:" not in alias_text, (
            f"{alias_name}: contains '- cron:' — would double-fire alongside"
            f" parent {parent_name}"
        )


def test_alias_count_matches_spec() -> None:
    """Spec says 8-15 aliases; current PR ships exactly 10."""
    assert 8 <= len(ALIAS_PAIRS) <= 15, (
        f"alias count {len(ALIAS_PAIRS)} outside spec range 8-15"
    )
