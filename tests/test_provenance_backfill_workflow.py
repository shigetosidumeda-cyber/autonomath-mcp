"""Wave 49 tick#3 — provenance-backfill-daily.yml workflow wiring tests.

The Dim O provenance backfill v2 ETL
(`scripts/etl/provenance_backfill_6M_facts_v2.py`) has lived upstream
since Wave 49 Phase 1 but its cron-workflow wiring was missing
— flagged as the "cron MISSING" axis of the Wave 49 dim 19 dim O
audit. This PR (Wave 49 tick#3) lands the workflow.

These tests assert:
  * Workflow YAML exists and parses.
  * Daily schedule (03:45 UTC == 12:45 JST) is present and clears
    the 03:15 anonymized-cohort-audit + Sunday-02:00 fact-signature
    slots.
  * workflow_dispatch overrides for max_rows / chunk_size / dry_run.
  * The Fly SSH invocation references the upstream v2 ETL script
    with the daily-1000-row cadence (--max-rows 1000 default,
    --chunk-size 100 default).
  * concurrency guard set to refuse parallel runs (the v2 ETL is
    write-only on am_fact_metadata, parallel = lost commits).
  * No LLM-vendor secret reference (memory:
    feedback_no_operator_llm_api).
"""

from __future__ import annotations

import pathlib

import pytest
import yaml  # PyYAML is already in dev-deps

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "provenance-backfill-daily.yml"
)


def test_workflow_file_exists() -> None:
    """Workflow YAML must exist at the canonical path."""
    assert WORKFLOW.exists(), (
        "Wave 49 tick#3 must land "
        ".github/workflows/provenance-backfill-daily.yml"
    )


def test_workflow_yaml_parses() -> None:
    """Workflow must be valid YAML (CI lint pre-flight)."""
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    # GHA workflow root must declare `on:` and `jobs:` keys. PyYAML
    # parses bare `on:` into the boolean True (YAML 1.1 spec), so we
    # tolerate either key spelling.
    assert "jobs" in parsed
    assert ("on" in parsed) or (True in parsed)


def test_workflow_schedule_is_daily_0345_utc() -> None:
    """Schedule must be daily 03:45 UTC (== 12:45 JST).

    Sits 30 min after `anonymized-cohort-audit-daily` (03:15 UTC) and
    well clear of `refresh-fact-signatures-weekly` (Sunday 02:00 UTC).
    """
    src = WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" in src
    assert "cron:" in src
    # 03:45 UTC daily is the agreed slot.
    assert '"45 3 * * *"' in src


def test_workflow_dispatch_inputs_present() -> None:
    """workflow_dispatch must expose max_rows / chunk_size / dry_run."""
    src = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in src
    assert "max_rows:" in src
    assert "chunk_size:" in src
    assert "dry_run:" in src


def test_workflow_invokes_v2_etl_with_daily_1000() -> None:
    """Fly SSH step must invoke v2 ETL with daily 1000-row default."""
    src = WORKFLOW.read_text(encoding="utf-8")
    assert (
        "scripts/etl/provenance_backfill_6M_facts_v2.py" in src
    ), "Workflow must call the v2 backfill ETL"
    assert "flyctl ssh console" in src
    assert "-a autonomath-api" in src
    # Daily 1000-row / 100-row chunk defaults stated in the docstring.
    assert "MAX_ROWS=\"${INPUT_MAX_ROWS:-1000}\"" in src
    assert "CHUNK_SIZE=\"${INPUT_CHUNK_SIZE:-100}\"" in src
    # --dry-run flag must be conditionally appended.
    assert "--dry-run" in src


def test_workflow_concurrency_guard() -> None:
    """Concurrency group must serialize runs (parallel = lost UPSERTs)."""
    src = WORKFLOW.read_text(encoding="utf-8")
    assert "concurrency:" in src
    assert "group: provenance-backfill-daily" in src
    assert "cancel-in-progress: false" in src


def test_workflow_no_llm_secret_reference() -> None:
    """No LLM-vendor secret may be referenced.

    Per memory `feedback_no_operator_llm_api`: scripts/etl/ is
    PRODUCTION_DIRS and may not import or be wired to call any LLM
    SDK or LLM API key. The Ed25519 sign key lives on Fly machine env
    (NOT as a GHA secret); the workflow should only reference
    `FLY_API_TOKEN` and `github.token`.
    """
    src = WORKFLOW.read_text(encoding="utf-8")
    banned = (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    )
    for needle in banned:
        assert needle not in src, (
            f"provenance-backfill-daily.yml must not reference {needle}"
        )


def test_workflow_does_not_invoke_quick_check() -> None:
    """No PRAGMA quick_check invocation on the 9.7 GB autonomath.db.

    Per memory `feedback_no_quick_check_on_huge_sqlite`: PRAGMA
    quick_check on the prod autonomath.db hangs Fly for 15+ minutes
    and trips the grace-period guard. The v2 ETL is indexed cursor
    pagination only; the workflow must not actually invoke a
    quick_check (mentioning it in a docstring as a documented ban is
    fine — we look for executable forms).
    """
    src = WORKFLOW.read_text(encoding="utf-8").lower()
    # Banned executable forms only — docstring mentions are OK.
    banned_invocations = (
        "pragma quick_check",
        "pragma quick-check",
        '"quick_check"',
        ".quick_check",
    )
    for needle in banned_invocations:
        assert needle not in src, (
            f"provenance-backfill-daily.yml must not invoke {needle!r}"
        )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
